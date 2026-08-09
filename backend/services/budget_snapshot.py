"""Household budget snapshot -- 'Left to Spend' / 'Not saving' and the
supporting credit-card/category/merchant data shown on the Dashboard and in
the weekly email. Formulas reverse-engineered from Dan's Budget.xlsx
(sheets "Budget" and "2026 Overview") and verified to reproduce its real
numbers exactly -- see backend/tests/test_budget_snapshot.py.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import BudgetSnapshot, CardSnapshot, WeeklyDigestCategory, MerchantSpendingEntry
from backend.services.forecast_engine import build_quarters
from backend.services.spending_helpers import category_totals_for_range, merchant_totals


def _monthly_income(db: Session, user_id: int) -> Decimal:
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.income,
        models.RecurringItem.is_active == True,
        models.RecurringItem.frequency == models.RecurringFrequency.monthly,
    ).all()
    return sum((item.amount for item in items), Decimal("0"))


def _monthly_expenses(db: Session, user_id: int, as_of: date) -> Decimal:
    """All active expense recurring items, monthly + any yearly item due
    this month -- covers Checking Bills, Credit Card Bills, and Tithing
    combined, matching how Budget.xlsx's Leftover formula treats them."""
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
    ).all()
    total = Decimal("0")
    for item in items:
        if item.frequency == models.RecurringFrequency.monthly:
            total += item.amount
        elif item.frequency == models.RecurringFrequency.yearly and item.month_of_year == as_of.month:
            total += item.amount
    return total


def _budget_allocation_total(db: Session, user_id: int, category_name: str, year: int) -> Decimal:
    row = (
        db.query(models.BudgetAllocation)
        .join(models.Category, models.Category.id == models.BudgetAllocation.category_id)
        .filter(
            models.BudgetAllocation.user_id == user_id,
            models.Category.name == category_name,
            models.BudgetAllocation.year == year,
            models.BudgetAllocation.month == 0,
        )
        .first()
    )
    return row.budgeted_amount if row else Decimal("0")


def _card_linked_recurring_items(db: Session, user_id: int) -> list[models.RecurringItem]:
    return db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
        models.RecurringItem.card_id.isnot(None),
    ).all()


def _cc_budget_total(db: Session, user_id: int) -> Decimal:
    """Full monthly total of Dan's 'Credit Card Bills' list (recurring
    subscriptions charged to a card) -- Budget.xlsx's F2."""
    items = _card_linked_recurring_items(db, user_id)
    return sum((item.amount for item in items), Decimal("0"))


def _charged_so_far(db: Session, user_id: int, as_of: date) -> Decimal:
    """Sum of recurring card-linked charges whose day_of_month has already
    passed this month -- Dan's 'Credit Card Bills' list, filtered to what's
    already posted, matching Budget.xlsx's SUMIF(...'<=' & DAY(...))."""
    items = _card_linked_recurring_items(db, user_id)
    total = Decimal("0")
    for item in items:
        last_day = calendar.monthrange(as_of.year, as_of.month)[1]
        due_day = item.day_of_month if item.day_of_month > 0 else last_day
        if min(due_day, last_day) <= as_of.day:
            total += item.amount
    return total


def _quarter_minimum(db: Session, user_id: int, account_id: int, as_of: date) -> Decimal:
    """The lowest projected checking balance this quarter, EXCLUDING the
    forecast's own credit-card-payoff injection (apply_cc_payments=False).

    not_saving (below) already subtracts the card balance itself as its own
    term, so a quarter_min that already reflects a projected payoff would
    double-count that same payoff -- once inside the forecast that produced
    this minimum, once again via the explicit subtraction. Confirmed live
    2026-08-08: this collapsed a real not_saving of +$2,085.64-ish down to
    -$8,232.93, because the quarter's minimum day landed exactly on the
    card's due date, already post-payoff. The Forecast page's own chart and
    risk callout are unaffected -- they call build_quarters/build_forecast
    directly with the apply_cc_payments default (True), so they still show
    the real dip.
    """
    quarter_num = (as_of.month - 1) // 3 + 1
    quarters = build_quarters(db, user_id, account_id, as_of.year, apply_cc_payments=False)
    quarter = next((q for q in quarters if q.quarter == quarter_num), None)
    if not quarter or not quarter.days:
        return Decimal("0")
    return min(day.projected_balance for day in quarter.days)


def _weekly_allowance(amount: Decimal, as_of: date) -> tuple[Decimal, int]:
    last_day = calendar.monthrange(as_of.year, as_of.month)[1]
    days_remaining = last_day - as_of.day + 1
    if days_remaining <= 7:
        weekly = amount
    else:
        weekly = (amount / (Decimal(days_remaining) / Decimal(7))).quantize(Decimal("0.01"))
    return weekly, days_remaining


def compute_budget_snapshot(
    db: Session,
    user: models.User,
    account_id: int,
    as_of: date | None = None,
) -> BudgetSnapshot:
    as_of = as_of or date.today()

    monthly_income = _monthly_income(db, user.id)
    monthly_expenses = _monthly_expenses(db, user.id, as_of)
    savings_budget = _budget_allocation_total(db, user.id, "Savings", as_of.year)
    groceries_budget = _budget_allocation_total(db, user.id, "Groceries", as_of.year)
    leftover = monthly_income - monthly_expenses - savings_budget - groceries_budget

    active_cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
        models.CreditCard.is_active == True,
    ).all()
    card_balances = sum((c.current_balance for c in active_cards), Decimal("0"))
    # What will actually be paid off next cycle -- the closed-statement total
    # plus anything charged since, NOT the live running current_balance.
    # Before bank sync, current_balance was itself only as fresh as Dan's last
    # manual update, so it and balance_due rarely diverged enough to matter.
    # Now that sync keeps current_balance accurate to the minute (including
    # charges from after the statement closed, not yet due), the two have
    # genuinely split -- confirmed live 2026-08-08: current_balance $10,528.54
    # vs the real amount due $9,273.76. Not Saving asks "if I paid off what's
    # actually due, how short am I" (Dan's own definition), so it uses
    # balance_due + pending_charges, not current_balance.
    balance_due_total = sum((c.balance_due + c.pending_charges for c in active_cards), Decimal("0"))
    charged_so_far = _charged_so_far(db, user.id, as_of)
    cc_budget_total = _cc_budget_total(db, user.id)

    # CCBudgetTotal cancels out algebraically in Left to Spend (the
    # spreadsheet cell adds it back then subtracts the not-yet-due
    # remainder), but NOT in Not Saving -- verified by hand against the
    # live spreadsheet cell. Do not "simplify" these to look symmetric.
    left_to_spend = leftover - card_balances + charged_so_far
    # quarter_min is computed WITHOUT the forecast's own credit-card-payoff
    # projection (apply_cc_payments=False in _quarter_minimum) -- Not Saving
    # subtracts the card payoff itself via balance_due_total below, so a
    # quarter_min that already reflected a projected payoff would double-
    # count it. Confirmed live 2026-08-08: this collapsed a real Not Saving
    # of roughly +$2,000 down to -$8,232.93, because the quarter's minimum
    # day landed exactly on the card's due date. See
    # backend/tests/test_budget_snapshot.py::test_not_saving_does_not_double_count_the_cc_payoff.
    quarter_min = _quarter_minimum(db, user.id, account_id, as_of)
    not_saving = quarter_min - balance_due_total - cc_budget_total + charged_so_far

    left_to_spend_weekly, days_remaining = _weekly_allowance(left_to_spend, as_of)
    not_saving_weekly, _ = _weekly_allowance(not_saving, as_of)

    cards = [
        CardSnapshot(
            id=c.id, name=c.name, current_balance=c.current_balance,
            pending_charges=c.pending_charges, credit_limit=c.credit_limit,
            utilization_pct=round(float(c.current_balance) / float(c.credit_limit) * 100, 1) if c.credit_limit else 0.0,
            due_day=c.due_day,
        )
        for c in active_cards
    ]

    week_start = as_of - timedelta(days=6)
    cat_totals = category_totals_for_range(db, user.id, week_start, as_of)
    cat_map = {c.id: c.name for c in db.query(models.Category).filter(models.Category.user_id == user.id).all()}
    categories = sorted(
        [
            WeeklyDigestCategory(
                category_id=cid if cid is not None else 0,
                category_name=cat_map.get(cid, "Unknown") if cid is not None else "Uncategorized",
                total=total,
            )
            for cid, total in cat_totals.items()
        ],
        key=lambda c: c.total,
        reverse=True,
    )
    merchants = merchant_totals(db, user.id, week_start, as_of, limit=10)
    top_merchants = [MerchantSpendingEntry(name=n, total=t, count=c) for n, t, c in merchants]

    return BudgetSnapshot(
        as_of=as_of,
        leftover=leftover,
        left_to_spend=left_to_spend,
        left_to_spend_weekly=left_to_spend_weekly,
        not_saving=not_saving,
        not_saving_weekly=not_saving_weekly,
        days_remaining_in_month=days_remaining,
        cards=cards,
        categories=categories,
        top_merchants=top_merchants,
    )
