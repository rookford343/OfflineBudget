import logging
import os
from contextlib import asynccontextmanager
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import create_tables, upgrade_schema, upgrade_categories
from backend.middleware import AuditMiddleware
from backend.routers import (
    accounts, auth, budget, categories, credit_cards,
    forecast, recurring, transactions, spending,
)
from backend.routers import admin as admin_router_module
from backend.routers import imports as imports_router_module
from backend.routers import goals as goals_router_module
from backend.routers import networth as networth_router_module
from backend.routers import scenarios as scenarios_router_module
from backend.routers import planned_expenses as planned_expenses_router_module
from backend.routers import reconciliation as reconciliation_router_module
from backend.routers import day_checkpoints as day_checkpoints_router_module
from backend.routers import rules as rules_router_module
from backend.routers import exports as exports_router_module
from backend.routers import data as data_router_module
from backend.routers import bank_sync as bank_sync_router_module
from backend.routers import planned_transfers as planned_transfers_router_module
from backend.routers import verification_flags as verification_flags_router_module
from backend.routers import settings as settings_router_module
from backend.routers import merchants as merchants_router_module

logger = logging.getLogger(__name__)


_WEEKDAY_ABBREVIATIONS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WEEKDAY_FULL_NAMES = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
]


def _is_digest_day(today: date, digest_day: str) -> bool:
    """True when `today` is the weekday the Weekly Digest's extra content
    (settings.WEEKLY_DIGEST_DAY, APScheduler cron day_of_week format, e.g.
    'fri') gets appended to the Daily Summary email.

    Recognizes the three-letter abbreviation ('fri') and the full weekday
    name ('friday'), both case- and whitespace-insensitive. APScheduler's
    day_of_week field also accepts integers, comma lists ('mon,fri') and
    ranges ('mon-fri'); this helper deliberately does NOT parse those and
    simply returns False for them. That fails open -- the Daily Summary
    still sends (just without the weekly addendum) rather than silently
    dropping mail on a form it can't parse.
    """
    day = digest_day.strip().lower()
    return _WEEKDAY_ABBREVIATIONS[today.weekday()] == day or _WEEKDAY_FULL_NAMES[today.weekday()] == day


_BANK_SYNC_HOUR = 5

# Generous on purpose -- covers "the Mac slept straight through the trigger
# and only woke hours later." APScheduler fires a missed cron trigger once on
# resume if wall-clock time is still within this window of the scheduled
# fire; past it, that day's run is skipped rather than firing something
# arbitrarily stale. This is the "didn't fire at all" half of the fix; the
# "fired but failed" half is _scheduler_sweep below, which doesn't need a
# grace window because it isn't reacting to a missed trigger at all.
_MISFIRE_GRACE_SECONDS = 12 * 3600


def _send_daily_summaries() -> None:
    from backend.database import SessionLocal
    from backend import models
    from backend.services.email_service import send_email_via
    from backend.services.summary_generator import generate_daily_summary, generate_weekly_digest
    from backend.services import scheduler_state, app_settings

    db = SessionLocal()
    # Read through app_settings so a change made on the Settings page takes
    # effect on the next run without a restart or an .env edit.
    is_digest_day = bool(app_settings.get_effective(db, "WEEKLY_DIGEST_ENABLED")) and _is_digest_day(
        date.today(), app_settings.get_effective(db, "WEEKLY_DIGEST_DAY") or settings.WEEKLY_DIGEST_DAY,
    )
    scheduler_state.record_attempt(db, "daily_summary")
    last_error: str | None = None
    try:
        # No longer filtered on User.email being non-empty: recipients can now
        # come from REPORT_RECIPIENTS instead, so a user with a blank account
        # email can still have a report going to their household. The
        # per-user recipient check below is what decides whether to send.
        users = db.query(models.User).filter(models.User.is_active == True).all()
        for user in users:
            recipients = app_settings.get_recipients(db, user)
            if not recipients:
                continue
            accounts = db.query(models.Account).filter(
                models.Account.user_id == user.id,
                models.Account.is_active == True,
            ).all()
            if not accounts:
                continue
            try:
                weekly_digest = None
                if is_digest_day:
                    checking = next((a for a in accounts if a.type == models.AccountType.checking), None)
                    if checking:
                        weekly_digest = generate_weekly_digest(db, user, checking.id)
                html_body, text_body = generate_daily_summary(db, user, weekly_digest=weekly_digest)
                subject = f"Daily Budget Summary — {date.today().strftime('%B %-d, %Y')}"
                if weekly_digest is not None:
                    subject += " + Weekly Digest"
                for recipient in recipients:
                    ok, err = send_email_via(db, recipient, subject, html_body, text_body)
                    if not ok:
                        last_error = f"{recipient}: {err}"
            except Exception as exc:
                logger.error("Summary failed for %s: %s", user.username, exc)
                last_error = f"{user.username}: {exc}"
        # A per-user exception is caught above and never propagates, so
        # "the function returned" cannot itself signal success -- a bad SMTP
        # config would otherwise get recorded as a successful run forever.
        if last_error:
            scheduler_state.record_failure(db, "daily_summary", last_error)
        else:
            scheduler_state.record_success(db, "daily_summary")
    finally:
        db.close()


def _run_bank_sync() -> None:
    from backend.database import SessionLocal
    from backend import models
    from backend.services.bank_sync_service import sync_all
    from backend.services.transfer_verification import verify_scheduled_transfers
    from backend.services import scheduler_state
    db = SessionLocal()
    scheduler_state.record_attempt(db, "bank_sync")
    try:
        sync_all(db)
        for user in db.query(models.User).filter(models.User.is_active == True).all():
            try:
                verify_scheduled_transfers(db, user.id)
            except Exception as exc:
                logger.error("Transfer verification failed for %s: %s", user.username, exc)
                db.rollback()
        # sync_connection is the only writer of BankConnection.status/last_error
        # and already isolates per-connection failures, so it's the more
        # precise signal for "did the sync actually work" than this
        # function's own control flow, which -- like the summary job -- never
        # raises on a per-connection failure.
        errored = db.query(models.BankConnection).filter(
            models.BankConnection.status == models.BankConnectionStatus.error,
        ).all()
        if errored:
            scheduler_state.record_failure(
                db, "bank_sync", "; ".join(f"{c.id}: {c.last_error}" for c in errored),
            )
        else:
            scheduler_state.record_success(db, "bank_sync")
    except Exception as exc:
        logger.error("Bank sync job failed: %s", exc)
        scheduler_state.record_failure(db, "bank_sync", str(exc))
    finally:
        db.close()


def _scheduler_sweep() -> None:
    """Runs every _SWEEP_MINUTES. Catches the failure shape misfire_grace_time
    can't: a trigger that DID fire (the process was awake and running) but the
    job failed -- most often no network yet in the first few minutes after a
    scheduled wake. Idempotent by construction: both jobs are safe to re-run
    (sync dedupes by external_id, the email loop just sends the same day's
    summary again), so a retry that turns out to have been unnecessary
    (e.g. a slow success landed between the miss check and the retry) costs
    nothing beyond one redundant run."""
    from backend.database import SessionLocal
    from backend.services import scheduler_state, app_settings
    db = SessionLocal()
    try:
        if scheduler_state.due_for_retry(db, "bank_sync", target_hour=_BANK_SYNC_HOUR):
            logger.info("Scheduler sweep: bank_sync missed today, retrying")
            _run_bank_sync()
        summary_hour = app_settings.get_effective(db, "DAILY_SUMMARY_HOUR")
        if summary_hour is None:
            summary_hour = settings.DAILY_SUMMARY_HOUR
        # The cron trigger's own hour is fixed at process start (APScheduler
        # reads it once), so changing the hour on the Settings page takes full
        # effect on the next restart. Until then the sweep is what honours it:
        # it re-checks every 20 minutes and fires the job once the new hour has
        # passed without a success, so a changed hour still sends the same day.
        if scheduler_state.due_for_retry(db, "daily_summary", target_hour=summary_hour):
            logger.info("Scheduler sweep: daily_summary missed today, retrying")
            _send_daily_summaries()
    finally:
        db.close()


_SWEEP_MINUTES = 20

_scheduler = BackgroundScheduler()
_scheduler.add_job(
    _send_daily_summaries, "cron", hour=settings.DAILY_SUMMARY_HOUR,
    misfire_grace_time=_MISFIRE_GRACE_SECONDS,
)
_scheduler.add_job(
    _run_bank_sync, "cron", hour=_BANK_SYNC_HOUR,
    misfire_grace_time=_MISFIRE_GRACE_SECONDS,
)
_scheduler.add_job(_scheduler_sweep, "interval", minutes=_SWEEP_MINUTES)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    os.makedirs("data", exist_ok=True)
    create_tables()
    upgrade_schema()
    upgrade_categories()
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(
    title="OfflineBudget",
    description="Forecasting-first personal budget tracker",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=_lifespan,
)

app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(categories.router)
app.include_router(recurring.router)
app.include_router(forecast.router)
app.include_router(transactions.router)
app.include_router(budget.router)
app.include_router(credit_cards.router)
app.include_router(spending.router)
app.include_router(admin_router_module.router)
app.include_router(imports_router_module.router)
app.include_router(goals_router_module.router)
app.include_router(networth_router_module.router)
app.include_router(scenarios_router_module.router)
app.include_router(planned_expenses_router_module.router)
app.include_router(reconciliation_router_module.router)
app.include_router(day_checkpoints_router_module.router)
app.include_router(rules_router_module.router)
app.include_router(exports_router_module.router)
app.include_router(data_router_module.router)
app.include_router(bank_sync_router_module.router)
app.include_router(planned_transfers_router_module.router)
app.include_router(verification_flags_router_module.router)
app.include_router(settings_router_module.router)
app.include_router(merchants_router_module.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "version": "2.0.0"}
