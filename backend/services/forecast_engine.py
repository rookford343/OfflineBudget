"""
Core day-by-day balance projection engine.

For each day in the requested range:
1. Find all recurring items whose day_of_month fires that day.
2. Check for actual transactions that day (is_actual=True); they override the
   recurring projection for a matched recurring_item_id.
3. Walk the running balance forward from account.current_balance.
"""
from __future__ import annotations
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import ForecastEntry, ForecastTransaction, QuarterSummary


def _last_day_of_month(d: date) -> int:
    return monthrange(d.year, d.month)[1]


def _fires_on(item: models.RecurringItem, d: date) -> bool:
    """Return True if this recurring item fires on date d."""
    if item.start_date > d:
        return False
    if item.end_date and item.end_date < d:
        return False
    if not item.is_active:
        return False
    # Yearly items only fire in their designated month
    frequency = getattr(item, "frequency", None)
    if frequency == models.RecurringFrequency.yearly:
        month_of_year = getattr(item, "month_of_year", None)
        if month_of_year and d.month != month_of_year:
            return False
    if item.day_of_month == 0:
        return d.day == _last_day_of_month(d)
    target = min(item.day_of_month, _last_day_of_month(d))
    return d.day == target


def build_forecast(
    db: Session,
    user_id: int,
    account_id: int,
    start_date: date,
    end_date: date,
    *,
    overrides: list[dict] | None = None,
) -> list[ForecastEntry]:
    account: models.Account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user_id,
    ).first()
    if not account:
        return []

    recurring_items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.account_id == account_id,
        models.RecurringItem.is_active == True,
    ).all()

    # Build override map: recurring_item_id -> amount_delta
    override_map: dict[int, Decimal] = {}
    if overrides:
        for ov in overrides:
            override_map[ov["recurring_item_id"]] = Decimal(str(ov["amount_delta"]))

    actual_txns = db.query(models.Transaction).filter(
        models.Transaction.user_id == user_id,
        models.Transaction.account_id == account_id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start_date,
        models.Transaction.date <= end_date,
    ).all()

    # Index actuals by date, then by recurring_item_id (or None for manual)
    actuals_by_date: dict[date, list[models.Transaction]] = {}
    for t in actual_txns:
        actuals_by_date.setdefault(t.date, []).append(t)

    balance = Decimal(str(account.current_balance))

    # Walk balance UP TO start_date using actual transactions before start_date
    prior_actuals = db.query(models.Transaction).filter(
        models.Transaction.user_id == user_id,
        models.Transaction.account_id == account_id,
        models.Transaction.is_actual == True,
        models.Transaction.date < start_date,
    ).order_by(models.Transaction.date).all()

    # The current_balance is the live balance — we project forward from today.
    # If start_date is in the future we just use current_balance as starting point.
    # If start_date is in the past we need to rewind — not supported in MVP; use current_balance.

    entries: list[ForecastEntry] = []
    current = start_date

    while current <= end_date:
        day_transactions: list[ForecastTransaction] = []
        actuals_today = actuals_by_date.get(current, [])
        actual_recurring_ids = {t.recurring_item_id for t in actuals_today if t.recurring_item_id}
        actual_manual = [t for t in actuals_today if t.recurring_item_id is None]

        # Apply recurring items, skipping any overridden by an actual
        for item in recurring_items:
            if not _fires_on(item, current):
                continue
            if item.id in actual_recurring_ids:
                # Use the actual transaction instead
                for actual in actuals_today:
                    if actual.recurring_item_id == item.id:
                        balance += Decimal(str(actual.amount))
                        day_transactions.append(ForecastTransaction(
                            name=actual.description,
                            amount=actual.amount,
                            type="income" if actual.amount > 0 else "expense",
                            category_name=actual.category.name if actual.category else None,
                            is_actual=True,
                            recurring_item_id=item.id,
                            transaction_id=actual.id,
                        ))
            else:
                # Use projected recurring amount, applying scenario delta if present
                base_amount = item.amount + override_map.get(item.id, Decimal("0"))
                signed = base_amount if item.type == models.RecurringType.income else -base_amount
                balance += signed
                day_transactions.append(ForecastTransaction(
                    name=item.name,
                    amount=signed,
                    type=item.type.value,
                    category_name=item.category.name if item.category else None,
                    is_actual=False,
                    recurring_item_id=item.id,
                ))

        # Apply manual actual transactions (not linked to any recurring item)
        for actual in actual_manual:
            balance += Decimal(str(actual.amount))
            day_transactions.append(ForecastTransaction(
                name=actual.description,
                amount=actual.amount,
                type="income" if actual.amount > 0 else "expense",
                category_name=actual.category.name if actual.category else None,
                is_actual=True,
                transaction_id=actual.id,
            ))

        entries.append(ForecastEntry(
            date=current,
            projected_balance=balance,
            transactions=day_transactions,
        ))
        current += timedelta(days=1)

    return entries


def build_quarters(
    db: Session,
    user_id: int,
    account_id: int,
    year: int,
) -> list[QuarterSummary]:
    quarters = []
    for q in range(1, 5):
        month_start = (q - 1) * 3 + 1
        start = date(year, month_start, 1)
        end_month = month_start + 2
        end = date(year, end_month, monthrange(year, end_month)[1])

        days = build_forecast(db, user_id, account_id, start, end)
        if not days:
            continue

        open_balance = days[0].projected_balance - sum(
            t.amount for t in days[0].transactions
        )
        close_balance = days[-1].projected_balance
        total_income = sum(
            t.amount for day in days for t in day.transactions if t.amount > 0
        )
        total_expenses = sum(
            -t.amount for day in days for t in day.transactions if t.amount < 0
        )
        quarters.append(QuarterSummary(
            quarter=q,
            year=year,
            open_balance=open_balance,
            close_balance=close_balance,
            total_income=total_income,
            total_expenses=total_expenses,
            net=total_income - total_expenses,
            days=days,
        ))
    return quarters
