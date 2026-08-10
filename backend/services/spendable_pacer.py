"""Weekly spendable pacer -- a transaction-driven, calendar-week view into
the same monthly discretionary budget `budget_snapshot.py` already computes
as `leftover`. Does NOT touch left_to_spend/not_saving (spreadsheet-verified,
balance-derived, unchanged) -- this is a second, independent calculation
that fixes the gap those formulas have: discretionary checking/debit
spending never moved them at all, only credit card balances did.

No persisted state. Every value here is recomputed fresh from `leftover`
(caller-supplied) and actual Transaction/CreditCardTransaction rows on every
call, so a week's over/underspend is automatically visible today and
automatically reshapes every later week's target this month -- one shared
pool, not four independent per-week budgets.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import or_
from sqlalchemy.orm import Session
from backend import models
from backend.services.spending_helpers import NOT_SAVINGS


def week_bounds(as_of: date) -> tuple[date, date]:
    """The Sunday-Saturday calendar week containing as_of."""
    # date.weekday(): Monday=0 .. Sunday=6. Convert to "days since Sunday".
    days_since_sunday = (as_of.weekday() + 1) % 7
    week_start = as_of - timedelta(days=days_since_sunday)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def weeks_remaining_in_month(as_of: date) -> Decimal:
    """Fractional weeks remaining in as_of's month, counting today through
    month-end inclusive, in 7-day units -- e.g. a 3-day final stretch of
    the month counts as 3/7, not a full week. Always > 0 since as_of is
    always on or before its own month's last day."""
    last_day = calendar.monthrange(as_of.year, as_of.month)[1]
    month_end = date(as_of.year, as_of.month, last_day)
    days_remaining = (month_end - as_of).days + 1
    return Decimal(days_remaining) / Decimal(7)


def _recurring_card_charges_in_range(db: Session, user_id: int, start: date, end: date) -> Decimal:
    """Sum of card-linked recurring items (RecurringItem.card_id set --
    subscriptions billed to a card, already counted in the monthly leftover
    pool via budget_snapshot.py's _cc_budget_total) that fire on any day in
    [start, end]. Mirrors _charged_so_far's day-of-month firing logic but
    over an arbitrary range instead of "month start through as_of", so it
    still works when a calendar week straddles a month boundary. Like
    _charged_so_far, this fires on the calendar day regardless of whether a
    matching real CreditCardTransaction has posted yet -- same accepted
    tradeoff already established there, not a new gap.
    """
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
        models.RecurringItem.card_id.isnot(None),
    ).all()
    total = Decimal("0")
    day = start
    while day <= end:
        last_day_of_month = calendar.monthrange(day.year, day.month)[1]
        for item in items:
            if item.start_date > day or (item.end_date and item.end_date < day):
                continue
            if item.frequency == models.RecurringFrequency.monthly:
                fires = True
            elif item.frequency == models.RecurringFrequency.yearly:
                fires = item.month_of_year == day.month
            else:
                fires = False
            if not fires:
                continue
            due_day = item.day_of_month if item.day_of_month > 0 else last_day_of_month
            if min(due_day, last_day_of_month) == day.day:
                total += item.amount
        day += timedelta(days=1)
    return total


def discretionary_spend_checking(db: Session, user_id: int, start: date, end: date) -> Decimal:
    verified_txn_ids = {
        row[0] for row in db.query(models.PlannedTransfer.verified_transaction_id)
        .filter(
            models.PlannedTransfer.user_id == user_id,
            models.PlannedTransfer.verified_transaction_id.isnot(None),
        ).all()
    }
    rows = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount < 0,
            models.Transaction.recurring_item_id.is_(None),
            NOT_SAVINGS,
        )
        .all()
    )
    return sum((abs(t.amount) for t in rows if t.id not in verified_txn_ids), Decimal("0"))


def discretionary_spend_card(db: Session, user_id: int, start: date, end: date) -> Decimal:
    rows = (
        db.query(models.CreditCardTransaction)
        .outerjoin(models.Category, models.CreditCardTransaction.category_id == models.Category.id)
        .filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.date >= start,
            models.CreditCardTransaction.date <= end,
            models.CreditCardTransaction.amount > 0,
            or_(
                models.CreditCardTransaction.category_id.is_(None),
                models.Category.type != models.CategoryType.savings,
            ),
        )
        .all()
    )
    total = sum((t.amount for t in rows), Decimal("0"))
    recurring = _recurring_card_charges_in_range(db, user_id, start, end)
    return max(total - recurring, Decimal("0"))


def discretionary_spend_in_range(db: Session, user_id: int, start: date, end: date) -> Decimal:
    """Total discretionary spend (checking + card) in [start, end] --
    excludes bills, savings movements, and card subscriptions already
    counted elsewhere. See module docstring."""
    return discretionary_spend_checking(db, user_id, start, end) + discretionary_spend_card(db, user_id, start, end)
