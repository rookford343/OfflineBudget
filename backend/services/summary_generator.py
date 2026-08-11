import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import MonthlySummary, WeeklyDigest, ForecastRisk
from backend.services.spending_helpers import category_totals_for_range
from backend.services.forecast_engine import build_forecast, find_balance_risk
from backend.services.budget_snapshot import compute_budget_snapshot

_STALE_SYNC_HOURS = 24


def _fmt(v: Decimal) -> str:
    return f"${v:,.2f}"


# ── Daily email summary ───────────────────────────────────────────────────────

def _stale_bank_connections(db: Session, user_id: int, now: datetime | None = None) -> list[models.BankConnection]:
    """Connections either actively erroring, or that haven't completed a
    sync in the last 24 hours -- data the Daily Summary is built from could
    be out of date without any other signal to the user. A deliberately
    `disconnected` connection is excluded: that's a user action, not a
    failure, and shouldn't nag daily forever after."""
    now = now or datetime.utcnow()
    threshold = now - timedelta(hours=_STALE_SYNC_HOURS)
    connections = db.query(models.BankConnection).filter(
        models.BankConnection.user_id == user_id,
        models.BankConnection.status != models.BankConnectionStatus.disconnected,
    ).all()
    return [
        c for c in connections
        if c.status == models.BankConnectionStatus.error
        or c.last_synced_at is None
        or c.last_synced_at < threshold
    ]


def _fires_soon(item: models.RecurringItem, today: date, days_ahead: int = 7) -> bool:
    for offset in range(days_ahead + 1):
        d = today + timedelta(days=offset)
        if item.start_date > d:
            continue
        if item.end_date and item.end_date < d:
            continue
        if not item.is_active:
            return False
        target_day = item.day_of_month or calendar.monthrange(d.year, d.month)[1]
        target_day = min(target_day, calendar.monthrange(d.year, d.month)[1])
        if d.day == target_day:
            return True
    return False


def generate_daily_summary(
    db: Session, user: models.User, *, weekly_digest: WeeklyDigest | None = None,
) -> tuple[str, str]:
    """Return (html_body, text_body) for a daily budget summary email.

    Pass `weekly_digest` (from `generate_weekly_digest`) on the day the
    Weekly Digest runs -- its spending-by-category/top-merchants/balance-risk
    sections get appended to this same email instead of going out as a
    separate one.
    """
    today = date.today()
    month_start = today.replace(day=1)

    accounts = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.is_active == True,
        models.Account.type == models.AccountType.checking,
    ).all()
    primary_account = accounts[0] if accounts else None
    snap = compute_budget_snapshot(db, user, primary_account.id, as_of=today) if primary_account else None

    all_recurring = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.is_active == True,
    ).all()
    upcoming = sorted(
        [r for r in all_recurring if _fires_soon(r, today, 7)],
        key=lambda x: x.day_of_month or 31,
    )

    mtd_txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.date >= month_start,
        models.Transaction.date <= today,
        models.Transaction.amount < 0,
        models.Transaction.is_actual == True,
    ).all()
    mtd_expenses = sum(abs(t.amount) for t in mtd_txns)
    monthly_income = sum(r.amount for r in all_recurring if r.type == models.RecurringType.income)

    cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
        models.CreditCard.is_active == True,
    ).all()

    stale_connections = _stale_bank_connections(db, user.id)

    fmt = _fmt

    def _connection_label(c: models.BankConnection) -> str:
        names = [link.simplefin_account_name for link in c.links if link.simplefin_account_name]
        return ", ".join(names) if names else f"Bank connection #{c.id}"

    stale_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{_connection_label(c)}</td>"
        f"<td style='padding:4px 0;color:#991b1b'>"
        + (
            f"failing: {c.last_error}" if c.status == models.BankConnectionStatus.error and c.last_error
            else "sync failing" if c.status == models.BankConnectionStatus.error
            else "no sync in 24+ hours" if c.last_synced_at is None
            else f"last synced {c.last_synced_at.strftime('%b %-d, %-I:%M %p')} UTC"
        )
        + "</td></tr>"
        for c in stale_connections
    )
    stale_html = (
        f"<div style='background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px;margin-bottom:16px'>"
        f"<p style='margin:0 0 6px;color:#991b1b;font-weight:600;font-size:13px'>⚠ Stale bank data</p>"
        f"<table style='width:100%;font-size:13px'>{stale_rows}</table>"
        f"<p style='margin:6px 0 0;color:#991b1b;font-size:12px'>Balances and transactions below may not reflect today's activity.</p>"
        f"</div>"
    ) if stale_connections else ""

    acct_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{a.name}</td>"
        f"<td style='padding:4px 0;text-align:right'><b>{fmt(a.current_balance)}</b></td></tr>"
        for a in accounts
    ) or "<tr><td style='color:#888'>No checking accounts</td></tr>"

    upcoming_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{r.name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(r.amount)}</td></tr>"
        for r in upcoming
    ) or "<tr><td style='color:#888'>None in the next 7 days</td></tr>"

    card_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{c.name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(c.current_balance)}</td>"
        f"<td style='padding:4px 0;text-align:right;color:#888'>due day&nbsp;{c.due_day}</td></tr>"
        for c in cards
    ) or "<tr><td colspan='3' style='color:#888'>No credit cards</td></tr>"

    if snap is not None:
        household_rows = (
            f"<tr><td style='padding:4px 12px 4px 0'>Spendable this week</td>"
            f"<td style='padding:4px 0;text-align:right'><b>{fmt(snap.left_to_spend_weekly)}</b></td></tr>"
            f"<tr><td style='padding:4px 12px 4px 0'>Not saving (this week)</td>"
            f"<td style='padding:4px 0;text-align:right'>{fmt(snap.not_saving_weekly)}</td></tr>"
        )
        household_html = (
            f"<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Household Snapshot</h3>"
            f"<table style='width:100%'>{household_rows}</table>"
            f"<p style='color:#6b7280;font-size:12px;margin:4px 0 16px'>Monthly: {fmt(snap.left_to_spend)} left to spend, "
            f"{fmt(snap.not_saving)} before it eats into savings.</p>"
        )
    else:
        household_html = (
            "<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Household Snapshot</h3>"
            "<p style='color:#888'>No checking account to compute a snapshot from.</p>"
        )

    weekly_html, weekly_text = _weekly_digest_section(weekly_digest) if weekly_digest else ("", "")

    html = f"""<!DOCTYPE html>
<html><body style='font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1f2937'>
<h2 style='color:#4f46e5;margin-bottom:4px'>OfflineBudget Daily Summary</h2>
<p style='color:#6b7280;margin-top:0'>{today.strftime("%A, %B %-d, %Y")}</p>

{stale_html}
{household_html}
<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Checking Accounts</h3>
<table style='width:100%'>{acct_rows}</table>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Upcoming (next 7 days)</h3>
<table style='width:100%'>{upcoming_rows}</table>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Month-to-Date Spending</h3>
<p>Expenses: <b>{fmt(mtd_expenses)}</b> &nbsp;|&nbsp; Monthly income: <b>{fmt(monthly_income)}</b></p>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Credit Cards</h3>
<table style='width:100%'>{card_rows}</table>
{weekly_html}
<p style='color:#9ca3af;font-size:12px;margin-top:24px'>Sent by OfflineBudget</p>
</body></html>"""

    acct_text = "\n".join(f"  {a.name}: {fmt(a.current_balance)}" for a in accounts) or "  No checking accounts"
    upcoming_text = "\n".join(f"  {r.name}: {fmt(r.amount)}" for r in upcoming) or "  None in the next 7 days"
    card_text = "\n".join(f"  {c.name}: {fmt(c.current_balance)} (due day {c.due_day})" for c in cards) or "  No credit cards"

    if snap is not None:
        household_text = (
            "HOUSEHOLD SNAPSHOT\n"
            f"  Spendable this week: {fmt(snap.left_to_spend_weekly)}\n"
            f"  Not saving (this week): {fmt(snap.not_saving_weekly)}\n"
            f"  Monthly: {fmt(snap.left_to_spend)} left to spend, {fmt(snap.not_saving)} before it eats into savings.\n"
        )
    else:
        household_text = "HOUSEHOLD SNAPSHOT\n  No checking account to compute a snapshot from.\n"

    def _stale_reason(c: models.BankConnection) -> str:
        if c.status == models.BankConnectionStatus.error:
            return f"failing: {c.last_error}" if c.last_error else "sync failing"
        if c.last_synced_at is None:
            return "no sync in 24+ hours"
        return f"last synced {c.last_synced_at.strftime('%b %-d, %-I:%M %p')} UTC"

    stale_text = (
        "\nSTALE BANK DATA -- balances/transactions below may not reflect today's activity\n"
        + "\n".join(f"  {_connection_label(c)}: {_stale_reason(c)}" for c in stale_connections) + "\n"
    ) if stale_connections else ""

    text = f"""OfflineBudget Daily Summary — {today.strftime("%B %-d, %Y")}
{stale_text}
{household_text}
CHECKING ACCOUNTS
{acct_text}

UPCOMING BILLS (next 7 days)
{upcoming_text}

MONTH-TO-DATE
  Expenses: {fmt(mtd_expenses)} | Monthly income: {fmt(monthly_income)}

CREDIT CARDS
{card_text}
{weekly_text}"""
    return html, text


def _weekly_digest_section(digest: WeeklyDigest) -> tuple[str, str]:
    """Render the Weekly Digest's own content (spending by category, top
    merchants, balance risk) as an HTML/text fragment appended to that
    day's Daily Summary -- the Household Snapshot and Credit Cards sections
    already live in the Daily Summary itself, so they aren't repeated here.
    """
    fmt = _fmt

    cat_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{c.category_name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(c.total)}</td></tr>"
        for c in digest.categories
    ) or "<tr><td style='color:#888'>No categorized spending this week</td></tr>"
    cat_text = "\n".join(
        f"  {c.category_name}: {fmt(c.total)}" for c in digest.categories
    ) or "  No categorized spending this week"

    merchant_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{m.name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(m.total)}</td></tr>"
        for m in digest.top_merchants[:10]
    ) or "<tr><td style='color:#888'>No merchant activity this week</td></tr>"
    merchant_text = "\n".join(
        f"  {m.name}: {fmt(m.total)}" for m in digest.top_merchants[:10]
    ) or "  No merchant activity this week"

    risk_html = ""
    risk_text = ""
    if digest.risk.at_risk and digest.risk.date is not None:
        risk_html = (
            f"<div style='background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px;margin:12px 0'>"
            f"<p style='margin:0;color:#991b1b;font-weight:600;font-size:13px'>Balance Risk</p>"
            f"<p style='margin:4px 0 0;color:#991b1b;font-size:13px'>Projected to drop to {fmt(digest.risk.amount)} on "
            f"{digest.risk.date.strftime('%B %-d, %Y')}.</p></div>"
        )
        risk_text = f"\n  Balance risk: projected to drop to {fmt(digest.risk.amount)} on {digest.risk.date.strftime('%B %-d, %Y')}\n"

    html = f"""
<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px;margin-top:24px'>Weekly Digest — {digest.week_start.strftime('%B %-d')}–{digest.week_end.strftime('%B %-d, %Y')}</h3>
<p>Total spent this week: <b>{fmt(digest.total_spent)}</b></p>
{risk_html}
<h4 style='margin-bottom:4px'>Spending by Category</h4>
<table style='width:100%'>{cat_rows}</table>

<h4 style='margin:12px 0 4px'>Top Merchants</h4>
<table style='width:100%'>{merchant_rows}</table>
"""

    text = f"""
WEEKLY DIGEST — {digest.week_start.strftime('%B %-d')} to {digest.week_end.strftime('%B %-d, %Y')}
  Total spent this week: {fmt(digest.total_spent)}
{risk_text}
SPENDING BY CATEGORY (past 7 days)
{cat_text}

TOP MERCHANTS (past 7 days)
{merchant_text}
"""
    return html, text


def _month_spending_by_category(
    db: Session, user_id: int, year: int, month: int
) -> tuple[dict[int, Decimal], Decimal, Decimal]:
    """Returns (spending_by_category_id, total_debits, total_credits).

    Includes both checking transactions and credit card charges so totals
    match the budget overview rather than being understated.
    """
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])

    checking_txns = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
        )
        .all()
    )

    card_txns = (
        db.query(models.CreditCardTransaction)
        .filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.date >= start,
            models.CreditCardTransaction.date <= end,
        )
        .all()
    )

    by_cat: dict[int, Decimal] = defaultdict(Decimal)
    total_debits = Decimal("0")
    total_credits = Decimal("0")

    for t in checking_txns:
        if t.amount < 0:
            total_debits += abs(t.amount)
            if t.category_id:
                by_cat[t.category_id] += abs(t.amount)
        else:
            total_credits += t.amount

    for t in card_txns:
        if t.amount > 0:
            total_debits += t.amount
            if t.category_id:
                by_cat[t.category_id] += t.amount

    return dict(by_cat), total_debits, total_credits


def generate_summary(db: Session, user_id: int, year: int, month: int) -> MonthlySummary:
    by_cat, total_debits, total_credits = _month_spending_by_category(db, user_id, year, month)

    if not by_cat and total_debits == 0 and total_credits == 0:
        return MonthlySummary(
            year=year,
            month=month,
            top_category=None,
            top_category_amount=None,
            mom_delta=None,
            mom_delta_pct=None,
            net_cashflow=Decimal("0"),
            text="Not enough data yet for this month.",
        )

    top_cat_id = max(by_cat, key=lambda k: by_cat[k]) if by_cat else None
    top_cat_name: str | None = None
    top_cat_amount: Decimal | None = None
    if top_cat_id:
        cat_map = {c.id: c.name for c in db.query(models.Category).filter(
            models.Category.user_id == user_id).all()}
        top_cat_name = cat_map.get(top_cat_id)
        top_cat_amount = by_cat[top_cat_id]

    prior_year, prior_month = (year - 1, 12) if month == 1 else (year, month - 1)
    _, prior_debits, _ = _month_spending_by_category(db, user_id, prior_year, prior_month)
    mom_delta = total_debits - prior_debits if prior_debits > 0 else None
    mom_delta_pct: Decimal | None = None
    if prior_debits > 0:
        mom_delta_pct = Decimal(str(round(float((total_debits - prior_debits) / prior_debits * 100), 1)))

    net_cashflow = total_credits - total_debits

    parts: list[str] = []

    if top_cat_name and top_cat_amount:
        parts.append(f"Your top spending category was {top_cat_name} at ${top_cat_amount:,.2f}.")

    if mom_delta is not None and mom_delta_pct is not None:
        direction = "up" if mom_delta > 0 else "down"
        label = "more" if mom_delta > 0 else "less"
        parts.append(
            f"Overall spending was {direction} {abs(mom_delta_pct):.1f}% "
            f"(${abs(mom_delta):,.2f} {label}) vs. last month."
        )

    if net_cashflow >= 0:
        parts.append(f"You came out ahead by ${net_cashflow:,.2f} this month.")
    else:
        parts.append(f"You spent ${abs(net_cashflow):,.2f} more than you earned this month.")

    return MonthlySummary(
        year=year,
        month=month,
        top_category=top_cat_name,
        top_category_amount=top_cat_amount,
        mom_delta=mom_delta,
        mom_delta_pct=mom_delta_pct,
        net_cashflow=net_cashflow,
        text=" ".join(parts),
    )


# ── Weekly digest ─────────────────────────────────────────────────────────────

def generate_weekly_digest(db: Session, user: models.User, account_id: int) -> WeeklyDigest:
    """Trailing 7 days of spending (category totals + top merchants) plus the
    forward-looking negative-balance risk for the given checking account.
    """
    today = date.today()
    week_start = today - timedelta(days=6)
    week_end = today

    # total_spent is this function's own computation (the trailing-7-day sum),
    # kept independent of compute_budget_snapshot. categories/top_merchants,
    # however, are the identical trailing-7-day breakdown compute_budget_snapshot
    # already computes -- reused below instead of recomputed.
    cat_totals = category_totals_for_range(db, user.id, week_start, week_end)
    total_spent = sum(cat_totals.values(), Decimal("0"))

    account = db.query(models.Account).filter(
        models.Account.id == account_id, models.Account.user_id == user.id,
    ).first()
    threshold = account.low_balance_threshold if account and account.low_balance_threshold is not None else Decimal("0")
    forecast_entries = build_forecast(db, user.id, account_id, today, today + timedelta(days=90))
    risk_dict = find_balance_risk(forecast_entries, threshold)
    risk = ForecastRisk(**risk_dict)

    snapshot = compute_budget_snapshot(db, user, account_id, as_of=today)

    return WeeklyDigest(
        week_start=week_start,
        week_end=week_end,
        total_spent=total_spent,
        categories=snapshot.categories,
        top_merchants=snapshot.top_merchants,
        risk=risk,
        snapshot=snapshot,
    )
