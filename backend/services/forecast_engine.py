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
from sqlalchemy.orm import Session, joinedload
from backend import models
from backend.schemas import ForecastEntry, ForecastTransaction, QuarterSummary


def _last_day_of_month(d: date) -> int:
    return monthrange(d.year, d.month)[1]


def _adjust_for_weekend(d: date) -> date:
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d - timedelta(days=2)
    return d


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

    planned = db.query(models.PlannedExpense).options(
        joinedload(models.PlannedExpense.category)
    ).filter(
        models.PlannedExpense.user_id == user_id,
        models.PlannedExpense.expected_date >= start_date,
        models.PlannedExpense.expected_date <= end_date,
    ).all()
    planned_by_date: dict[date, list[models.PlannedExpense]] = {}
    for pe in planned:
        planned_by_date.setdefault(pe.expected_date, []).append(pe)

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

        adj_actual_recurring_ids = set(actual_recurring_ids)
        if current.weekday() == 4:
            for offset in (1, 2):
                for t in actuals_by_date.get(current + timedelta(offset), []):
                    if t.recurring_item_id:
                        adj_actual_recurring_ids.add(t.recurring_item_id)

        for item in recurring_items:
            natural_fires = _fires_on(item, current)

            # Actuals always appear on their real date (ISC-17: not shifted)
            if natural_fires and item.id in actual_recurring_ids:
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
                continue

            if current.weekday() in (5, 6):
                continue  # shifted to preceding Friday

            fires_projected = natural_fires
            if not fires_projected and current.weekday() == 4:
                fires_projected = (
                    _fires_on(item, current + timedelta(1)) or
                    _fires_on(item, current + timedelta(2))
                )

            if not fires_projected:
                continue
            if item.id in adj_actual_recurring_ids:
                continue

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

        for pe in planned_by_date.get(current, []):
            signed = -abs(pe.amount)
            balance += signed
            day_transactions.append(ForecastTransaction(
                name=pe.name,
                amount=signed,
                type="expense",
                category_name=pe.category.name if pe.category else None,
                is_actual=False,
                is_planned=True,
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
