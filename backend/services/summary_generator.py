import calendar
from datetime import date, timedelta
from decimal import Decimal
from collections import defaultdict
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import MonthlySummary, WeeklyDigest, ForecastRisk
from backend.services.spending_helpers import category_totals_for_range
from backend.services.forecast_engine import build_forecast, find_balance_risk
from backend.services.budget_snapshot import compute_budget_snapshot


# ── Daily email summary ───────────────────────────────────────────────────────

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


def generate_daily_summary(db: Session, user: models.User) -> tuple[str, str]:
    """Return (html_body, text_body) for a daily budget summary email."""
    today = date.today()
    month_start = today.replace(day=1)

    accounts = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.is_active == True,
        models.Account.type == models.AccountType.checking,
    ).all()

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

    def fmt(v: Decimal) -> str:
        return f"${v:,.2f}"

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

    html = f"""<!DOCTYPE html>
<html><body style='font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1f2937'>
<h2 style='color:#4f46e5;margin-bottom:4px'>OfflineBudget Daily Summary</h2>
<p style='color:#6b7280;margin-top:0'>{today.strftime("%A, %B %-d, %Y")}</p>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Checking Accounts</h3>
<table style='width:100%'>{acct_rows}</table>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Upcoming (next 7 days)</h3>
<table style='width:100%'>{upcoming_rows}</table>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Month-to-Date Spending</h3>
<p>Expenses: <b>{fmt(mtd_expenses)}</b> &nbsp;|&nbsp; Monthly income: <b>{fmt(monthly_income)}</b></p>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Credit Cards</h3>
<table style='width:100%'>{card_rows}</table>

<p style='color:#9ca3af;font-size:12px;margin-top:24px'>Sent by OfflineBudget</p>
</body></html>"""

    acct_text = "\n".join(f"  {a.name}: {fmt(a.current_balance)}" for a in accounts) or "  No checking accounts"
    upcoming_text = "\n".join(f"  {r.name}: {fmt(r.amount)}" for r in upcoming) or "  None in the next 7 days"
    card_text = "\n".join(f"  {c.name}: {fmt(c.current_balance)} (due day {c.due_day})" for c in cards) or "  No credit cards"

    text = f"""OfflineBudget Daily Summary — {today.strftime("%B %-d, %Y")}

CHECKING ACCOUNTS
{acct_text}

UPCOMING BILLS (next 7 days)
{upcoming_text}

MONTH-TO-DATE
  Expenses: {fmt(mtd_expenses)} | Monthly income: {fmt(monthly_income)}

CREDIT CARDS
{card_text}
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
