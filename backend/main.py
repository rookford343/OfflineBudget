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

logger = logging.getLogger(__name__)


def _send_daily_summaries() -> None:
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

    cat_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{c.category_name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(c.total)}</td></tr>"
        for c in digest.categories
    ) or "<tr><td style='color:#888'>No categorized spending this week</td></tr>"

    merchant_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{m.name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(m.total)}</td></tr>"
        for m in digest.top_merchants[:10]
    ) or "<tr><td style='color:#888'>No merchant activity this week</td></tr>"

    risk_html = ""
    risk_text = ""
    if digest.risk.at_risk and digest.risk.date is not None:
        risk_html = (
            f"<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px;color:#dc2626'>Balance Risk</h3>"
            f"<p style='color:#991b1b'>Projected to drop to {fmt(digest.risk.amount)} on "
            f"{digest.risk.date.strftime('%B %-d, %Y')}.</p>"
        )
        risk_text = f"\nBALANCE RISK\n  Projected to drop to {fmt(digest.risk.amount)} on {digest.risk.date.strftime('%B %-d, %Y')}.\n"

    html = f"""<!DOCTYPE html>
<html><body style='font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1f2937'>
<h2 style='color:#4f46e5;margin-bottom:4px'>OfflineBudget Weekly Digest</h2>
<p style='color:#6b7280;margin-top:0'>{digest.week_start.strftime("%B %-d")} – {digest.week_end.strftime("%B %-d, %Y")}</p>

<p>Total spent this week: <b>{fmt(digest.total_spent)}</b></p>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Spending by Category</h3>
<table style='width:100%'>{cat_rows}</table>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Top Merchants</h3>
<table style='width:100%'>{merchant_rows}</table>

{risk_html}

<p style='color:#9ca3af;font-size:12px;margin-top:24px'>Sent by OfflineBudget</p>
</body></html>"""

    cat_text = "\n".join(f"  {c.category_name}: {fmt(c.total)}" for c in digest.categories) or "  No categorized spending this week"
    merchant_text = "\n".join(f"  {m.name}: {fmt(m.total)}" for m in digest.top_merchants[:10]) or "  No merchant activity this week"

    text = f"""OfflineBudget Weekly Digest — {digest.week_start.strftime("%B %-d")} to {digest.week_end.strftime("%B %-d, %Y")}

Total spent this week: {fmt(digest.total_spent)}

SPENDING BY CATEGORY
{cat_text}

TOP MERCHANTS
{merchant_text}
{risk_text}"""
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
        users = db.query(models.User).filter(models.User.is_active == True).all()
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


_scheduler = BackgroundScheduler()
_scheduler.add_job(_send_daily_summaries, "cron", hour=settings.DAILY_SUMMARY_HOUR)
_scheduler.add_job(_send_weekly_digest, "cron", day_of_week=settings.WEEKLY_DIGEST_DAY, hour=settings.WEEKLY_DIGEST_HOUR)


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


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "version": "2.0.0"}
