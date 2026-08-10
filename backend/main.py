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

logger = logging.getLogger(__name__)


_WEEKDAY_ABBREVIATIONS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WEEKDAY_FULL_NAMES = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
]


def _is_digest_day(today: date, digest_day: str) -> bool:
    """True when `today` is the weekday the Weekly Digest sends on
    (settings.WEEKLY_DIGEST_DAY, APScheduler cron day_of_week format, e.g.
    'fri') -- the Daily Summary is skipped that day since the digest
    already covers the same ground (account/card balances, spending).

    Recognizes the three-letter abbreviation ('fri') and the full weekday
    name ('friday'), both case- and whitespace-insensitive. APScheduler's
    day_of_week field also accepts integers, comma lists ('mon,fri') and
    ranges ('mon-fri'); this helper deliberately does NOT parse those and
    simply returns False for them. That fails open -- the Daily Summary
    keeps sending and the user loses nothing, which is the correct failure
    direction; the alternative (guessing wrong and skipping) silently drops
    mail.
    """
    day = digest_day.strip().lower()
    return _WEEKDAY_ABBREVIATIONS[today.weekday()] == day or _WEEKDAY_FULL_NAMES[today.weekday()] == day


def _send_daily_summaries() -> None:
    # Only skip when the digest is actually going to send. A blank
    # DIGEST_RECIPIENTS is the documented way (.env.example) to turn the
    # Weekly Digest off; skipping on weekday alone would silently drop one
    # Daily Summary every week and send nothing in its place.
    if settings.digest_recipients_list and _is_digest_day(date.today(), settings.WEEKLY_DIGEST_DAY):
        logger.info("Skipping daily summary -- weekly digest covers today.")
        return
    from backend.database import SessionLocal
    from backend import models
    from backend.services.email_service import send_email
    from backend.services.summary_generator import generate_daily_summary
    db = SessionLocal()
    try:
        users = db.query(models.User).filter(
            models.User.is_active == True,
            models.User.email.isnot(None),
            models.User.email != "",
        ).all()
        for user in users:
            has_accts = db.query(models.Account).filter(
                models.Account.user_id == user.id,
                models.Account.is_active == True,
            ).count() > 0
            if not has_accts:
                continue
            try:
                html_body, text_body = generate_daily_summary(db, user)
                subject = f"Daily Budget Summary — {date.today().strftime('%B %-d, %Y')}"
                send_email(user.email, subject, html_body, text_body)
            except Exception as exc:
                logger.error("Summary failed for %s: %s", user.username, exc)
    finally:
        db.close()


def _digest_html(user: "models.User", digest) -> tuple[str, str]:
    def fmt(v) -> str:
        return f"${v:,.2f}"

    snap = digest.snapshot

    def section(title: str, body: str) -> str:
        return (
            f"<div style='margin-bottom:20px'>"
            f"<h3 style='font-size:13px;font-weight:600;color:#6b7280;text-transform:uppercase;"
            f"letter-spacing:0.05em;border-bottom:1px solid #e5e7eb;padding-bottom:6px;margin-bottom:10px'>{title}</h3>"
            f"{body}</div>"
        )

    def stat_card(label: str, value: str, color: str, sub: str = "") -> str:
        sub_html = f"<div style='font-size:10px;color:{color};margin-top:2px'>{sub}</div>" if sub else ""
        return (
            f"<td style='padding:14px;background:#f9fafb;border-radius:10px;text-align:center;width:50%;"
            f"box-shadow:0 1px 2px rgba(0,0,0,0.04)'>"
            f"<div style='font-size:11px;color:#6b7280;margin-bottom:4px'>{label}</div>"
            f"<div style='font-size:22px;font-weight:700;color:{color}'>{value}</div>{sub_html}</td>"
        )

    pace_color = "#059669" if snap.on_pace else "#dc2626"
    pace_text = f"${abs(float(snap.spendable_today)):,.2f}/day" + (" · on pace" if snap.on_pace else " · over pace")
    snapshot_html = section(
        "Household Snapshot",
        f"<table style='width:100%;border-spacing:10px 0'><tr>"
        f"{stat_card('Spendable this week', fmt(snap.left_to_spend_weekly), pace_color, pace_text)}"
        f"{stat_card('Not Saving (this week)', fmt(snap.not_saving_weekly), '#d97706')}"
        f"</tr></table>"
        f"<p style='font-size:12px;color:#9ca3af;margin:8px 0 0'>Monthly: {fmt(snap.left_to_spend)} left to spend, "
        f"{fmt(snap.not_saving)} before it eats into savings.</p>",
    )

    card_rows = "".join(
        f"<tr><td style='padding:6px 12px 6px 0'>{c.name}</td>"
        f"<td style='padding:6px 0;text-align:right;font-weight:600'>{fmt(c.current_balance)}</td>"
        f"<td style='padding:6px 0 6px 12px;text-align:right;color:#9ca3af;font-size:12px'>{c.utilization_pct}% of {fmt(c.credit_limit)}"
        + (f" · pending {fmt(c.pending_charges)}" if c.pending_charges and c.pending_charges > 0 else "")
        + "</td></tr>"
        for c in snap.cards
    ) or "<tr><td style='color:#888'>No active cards</td></tr>"
    cards_html = section("Credit Cards", f"<table style='width:100%'>{card_rows}</table>")

    cat_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{c.category_name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(c.total)}</td></tr>"
        for c in digest.categories
    ) or "<tr><td style='color:#888'>No categorized spending this week</td></tr>"
    cat_html = section("Spending by Category", f"<table style='width:100%'>{cat_rows}</table>")

    merchant_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{m.name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(m.total)}</td></tr>"
        for m in digest.top_merchants[:10]
    ) or "<tr><td style='color:#888'>No merchant activity this week</td></tr>"
    merchant_html = section("Top Merchants", f"<table style='width:100%'>{merchant_rows}</table>")

    risk_html = ""
    risk_text = ""
    if digest.risk.at_risk and digest.risk.date is not None:
        risk_html = (
            f"<div style='background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px;margin-bottom:20px'>"
            f"<p style='margin:0;color:#991b1b;font-weight:600;font-size:13px'>Balance Risk</p>"
            f"<p style='margin:4px 0 0;color:#991b1b;font-size:13px'>Projected to drop to {fmt(digest.risk.amount)} on "
            f"{digest.risk.date.strftime('%B %-d, %Y')}.</p></div>"
        )
        risk_text = f"\nBALANCE RISK\n  Projected to drop to {fmt(digest.risk.amount)} on {digest.risk.date.strftime('%B %-d, %Y')}.\n"

    html = f"""<!DOCTYPE html>
<html><body style='font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:24px;background:#f3f4f6'>
<div style='max-width:520px;margin:0 auto;padding:28px;color:#1f2937;background:#ffffff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,0.08)'>
<h2 style='color:#4f46e5;margin:0 0 4px;font-size:20px'>OfflineBudget Weekly Digest</h2>
<p style='color:#6b7280;margin:0 0 20px;font-size:13px'>{digest.week_start.strftime("%B %-d")} – {digest.week_end.strftime("%B %-d, %Y")} · For {user.display_name}</p>

<p style='font-size:14px'>Total spent this week: <b>{fmt(digest.total_spent)}</b></p>

{snapshot_html}
{risk_html}
{cards_html}
{cat_html}
{merchant_html}

<p style='color:#9ca3af;font-size:11px;margin-top:20px'>Sent by OfflineBudget</p>
</div>
</body></html>"""

    cat_text = "\n".join(f"  {c.category_name}: {fmt(c.total)}" for c in digest.categories) or "  No categorized spending this week"
    merchant_text = "\n".join(f"  {m.name}: {fmt(m.total)}" for m in digest.top_merchants[:10]) or "  No merchant activity this week"
    card_text = "\n".join(
        f"  {c.name}: {fmt(c.current_balance)} ({c.utilization_pct}% of {fmt(c.credit_limit)}"
        + (f", pending {fmt(c.pending_charges)}" if c.pending_charges and c.pending_charges > 0 else "")
        + ")"
        for c in snap.cards
    ) or "  No active cards"

    text = f"""OfflineBudget Weekly Digest — {digest.week_start.strftime("%B %-d")} to {digest.week_end.strftime("%B %-d, %Y")}
For {user.display_name}

Total spent this week: {fmt(digest.total_spent)}

HOUSEHOLD SNAPSHOT
  Spendable this week: {fmt(snap.left_to_spend_weekly)} (${abs(float(snap.spendable_today)):,.2f}/day for the next {snap.days_left_in_week} day{"" if snap.days_left_in_week == 1 else "s"}, {"on pace" if snap.on_pace else "over pace"})
  Not Saving this week: {fmt(snap.not_saving_weekly)} (monthly: {fmt(snap.not_saving)})
{risk_text}
CREDIT CARDS
{card_text}

SPENDING BY CATEGORY
{cat_text}

TOP MERCHANTS
{merchant_text}
"""
    return html, text


def _send_weekly_digest() -> None:
    from backend.database import SessionLocal
    from backend import models
    from backend.services.email_service import send_email
    from backend.services.summary_generator import generate_weekly_digest

    recipients = settings.digest_recipients_list
    if not recipients:
        return

    db = SessionLocal()
    try:
        users = db.query(models.User).filter(models.User.is_active == True).order_by(models.User.id).all()
        if len(users) > 1:
            logger.warning(
                "Weekly digest: multiple active users found (%d), sending only for %s",
                len(users), users[0].username,
            )
            users = users[:1]
        for user in users:
            account = db.query(models.Account).filter(
                models.Account.user_id == user.id,
                models.Account.type == models.AccountType.checking,
                models.Account.is_active == True,
            ).first()
            if not account:
                continue
            try:
                digest = generate_weekly_digest(db, user, account.id)
                html_body, text_body = _digest_html(user, digest)
                subject = f"Weekly Spending Digest — {digest.week_start.strftime('%b %-d')}–{digest.week_end.strftime('%b %-d, %Y')}"
                for recipient in recipients:
                    send_email(recipient, subject, html_body, text_body)
            except Exception as exc:
                logger.error("Weekly digest failed for %s: %s", user.username, exc)
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
_scheduler.add_job(_send_weekly_digest, "cron", day_of_week=settings.WEEKLY_DIGEST_DAY, hour=settings.WEEKLY_DIGEST_HOUR)
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


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "version": "2.0.0"}
