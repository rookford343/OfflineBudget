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


def _send_daily_summaries() -> None:
    from backend.database import SessionLocal
    from backend import models
    from backend.services.email_service import send_email, parse_recipients
    from backend.services.summary_generator import generate_daily_summary, generate_weekly_digest

    is_digest_day = bool(settings.digest_recipients_list) and _is_digest_day(date.today(), settings.WEEKLY_DIGEST_DAY)

    db = SessionLocal()
    try:
        users = db.query(models.User).filter(
            models.User.is_active == True,
            models.User.email.isnot(None),
            models.User.email != "",
        ).all()
        for user in users:
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
                for recipient in parse_recipients(user.email):
                    send_email(recipient, subject, html_body, text_body)
            except Exception as exc:
                logger.error("Summary failed for %s: %s", user.username, exc)
    finally:
        db.close()


def _run_bank_sync() -> None:
    from backend.database import SessionLocal
    from backend import models
    from backend.services.bank_sync_service import sync_all
    from backend.services.transfer_verification import verify_scheduled_transfers
    db = SessionLocal()
    try:
        sync_all(db)
        for user in db.query(models.User).filter(models.User.is_active == True).all():
            try:
                verify_scheduled_transfers(db, user.id)
            except Exception as exc:
                logger.error("Transfer verification failed for %s: %s", user.username, exc)
                db.rollback()
    except Exception as exc:
        logger.error("Bank sync job failed: %s", exc)
    finally:
        db.close()


_scheduler = BackgroundScheduler()
_scheduler.add_job(_send_daily_summaries, "cron", hour=settings.DAILY_SUMMARY_HOUR)
_scheduler.add_job(_run_bank_sync, "cron", hour=5)


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


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "version": "2.0.0"}
