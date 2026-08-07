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
from decimal import Decimal, ROUND_CEILING
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


def _compute_transfer_schedule(
    db: Session,
    user_id: int,
    rule: models.BufferTransferRule,
    start_date: date,
    end_date: date,
) -> dict[date, Decimal]:
    """Dry-run `rule.to_account_id` with no transfers applied, then decide on
    each check_day whether a buffer transfer is needed to keep it above
    `rule.action_threshold` before the next check_day. Each month's decision
    credits transfers already scheduled in earlier months, so a transfer
    from July isn't re-counted as still needed in August."""
    raw_entries = build_forecast(
        db, user_id, rule.to_account_id, start_date, end_date,
        apply_buffer_transfers=False,
    )
    if not raw_entries:
        return {}

    check_days: list[date] = []
    cur = date(start_date.year, start_date.month, 1)
    while cur <= end_date:
        last_day = _last_day_of_month(cur)
        cd = date(cur.year, cur.month, min(rule.check_day, last_day))
        if start_date <= cd <= end_date:
            check_days.append(cd)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)

    schedule: dict[date, Decimal] = {}
    injected_so_far = Decimal("0")
    for i, cd in enumerate(check_days):
        window_end = check_days[i + 1] - timedelta(days=1) if i + 1 < len(check_days) else end_date
        window = [e for e in raw_entries if cd <= e.date <= window_end]
        if not window:
            continue
        lowest_raw = min(e.projected_balance for e in window)
        lowest_adjusted = lowest_raw + injected_so_far
        if lowest_adjusted < rule.action_threshold:
            shortfall = rule.target_floor - lowest_adjusted
            steps = int((shortfall / rule.increment).to_integral_value(rounding=ROUND_CEILING))
            amount = rule.increment * steps
            schedule[cd] = amount
            injected_so_far += amount

    return schedule


def _cc_actual_nearby(
    card: models.CreditCard,
    target: date,
    actuals_by_date: dict[date, list[models.Transaction]],
    window: int = 7,
) -> bool:
    """True if an actual transaction matching this card appears within window days of target.

    Uses the first token of the card name (e.g. 'Chase' from 'Chase Sapphire') as the
    identifier since bank descriptions rarely include the full product name but always
    include the issuer. Falls back to last_four if available.
    """
    name_lower = (card.name or "").lower().strip()
    first_token = name_lower.split()[0] if name_lower else ""
    for offset in range(-window, window + 1):
        check = target + timedelta(days=offset)
        for txn in actuals_by_date.get(check, []):
            desc_lower = txn.description.lower()
            if first_token and first_token in desc_lower:
                return True
            if card.last_four and card.last_four in txn.description:
                return True
    return False


def _fires_on(item: models.RecurringItem, d: date) -> bool:
    """Return True if this recurring item fires on date d."""
    if item.start_date > d:
        return False
    if item.end_date and item.end_date < d:
        return False
    if not item.is_active:
        return False
    frequency = getattr(item, "frequency", None)
    if frequency == models.RecurringFrequency.weekly:
        return (d - item.start_date).days % 7 == 0
    if frequency == models.RecurringFrequency.biweekly:
        return (d - item.start_date).days % 14 == 0
    # Yearly items only fire in their designated month
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
    apply_buffer_transfers: bool = True,
) -> list[ForecastEntry]:
    account: models.Account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user_id,
    ).first()
    if not account:
        return []

    recurring_items = [
        item for item in db.query(models.RecurringItem).options(
            joinedload(models.RecurringItem.card)
        ).filter(
            models.RecurringItem.user_id == user_id,
            models.RecurringItem.account_id == account_id,
            models.RecurringItem.is_active == True,
        ).all()
        # CC charges (expense + card_id) hit the card, not the checking account
        if not (item.type == models.RecurringType.expense and item.card_id is not None)
    ]

    # SS paycheck boost setup
    user = db.query(models.User).filter(models.User.id == user_id).first()
    ss_paycheck_item_ids: set[int] = set()
    ss_remaining_gross: Decimal | None = None
    ss_boost_per_check = Decimal("0")
    ss_limit_reached = False
    if (
        user
        and user.ss_gross_per_paycheck and user.ss_gross_per_paycheck > 0
        and user.ss_wage_base and user.ss_wage_base > 0
    ):
        ss_gross = user.ss_gross_per_paycheck
        ss_bonus_ytd = user.ss_bonus_ytd or Decimal("0")
        ss_remaining_gross = user.ss_wage_base - ss_bonus_ytd
        ss_boost_per_check = ss_gross * Decimal("0.062")
        for item in recurring_items:
            if item.type == models.RecurringType.income and item.amount > 0:
                ratio = item.amount / ss_gross
                if Decimal("0.9") <= ratio <= Decimal("1.1"):
                    ss_paycheck_item_ids.add(item.id)

    planned = db.query(models.PlannedExpense).options(
        joinedload(models.PlannedExpense.category)
    ).filter(
        models.PlannedExpense.user_id == user_id,
        models.PlannedExpense.expected_date >= start_date,
        models.PlannedExpense.expected_date <= end_date,
    ).all()
    planned_by_date: dict[date, list[models.PlannedExpense]] = {}
    for pe in planned:
        # Only include planned expenses for this account (or unlinked ones)
        if pe.account_id is None or pe.account_id == account_id:
            planned_by_date.setdefault(pe.expected_date, []).append(pe)

    # CC payment injections: cards with next_payment_date set, balance_due > 0,
    # and no existing recurring CC payment item already handling this card (avoid double-count).
    recurring_cc_card_ids = {item.card_id for item in recurring_items if item.type == models.RecurringType.credit_card_payment}
    cc_payments: dict[date, list[tuple[str, Decimal]]] = {}
    cc_estimates_by_date: dict[date, list[tuple[str, Decimal]]] = {}

    all_active_cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
    ).all()
    for card in all_active_cards:
        if card.id in recurring_cc_card_ids:
            continue  # recurring CC payment item already handles this card
        if (
            card.next_payment_date is not None
            and start_date <= card.next_payment_date <= end_date
            and card.balance_due and card.balance_due > 0
        ):
            cc_payments.setdefault(card.next_payment_date, []).append(
                (card.name, Decimal(str(card.balance_due)))
            )
        if card.monthly_spend_estimate and card.monthly_spend_estimate > 0:
            estimate = Decimal(str(card.monthly_spend_estimate))
            cur = date(start_date.year, start_date.month, 1)
            while cur <= end_date:
                due_day = min(card.due_day, _last_day_of_month(cur))
                inject_date = date(cur.year, cur.month, due_day)
                # Skip estimate when we already have the real balance_due for this payment
                payment_covers_this_date = (
                    card.next_payment_date is not None
                    and card.next_payment_date.year == cur.year
                    and card.next_payment_date.month == cur.month
                    and card.balance_due and card.balance_due > 0
                )
                if start_date <= inject_date <= end_date and not payment_covers_this_date:
                    cc_estimates_by_date.setdefault(inject_date, []).append((card.name, estimate))
                cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)

    # Build override map: recurring_item_id -> amount_delta
    override_map: dict[int, Decimal] = {}
    if overrides:
        for ov in overrides:
            override_map[ov["recurring_item_id"]] = Decimal(str(ov["amount_delta"]))

    today = date.today()

    # Load all actuals in the forecast window.
    # For dates in the past: current_balance already reflects them, so we reconstruct
    # the starting balance by reversing past actuals — then re-apply them in the walk.
    # This gives an accurate historical line rather than projecting backward from today's balance.
    all_actuals = db.query(models.Transaction).filter(
        models.Transaction.user_id == user_id,
        models.Transaction.account_id == account_id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start_date,
        models.Transaction.date <= end_date,
    ).all()

    actuals_by_date: dict[date, list[models.Transaction]] = {}
    for t in all_actuals:
        actuals_by_date.setdefault(t.date, []).append(t)

    # When start_date is in the past, reverse past actuals to find the opening balance.
    # current_balance = opening_balance + sum(all actuals from start_date to yesterday),
    # so opening_balance = current_balance - sum(past actuals).
    current_balance = Decimal(str(account.current_balance))
    if start_date < today:
        past_sum = sum(
            Decimal(str(t.amount)) for t in all_actuals if t.date < today
        )
        balance = current_balance - past_sum
    else:
        balance = current_balance

    # Lookup for CC suppression — keyed by the name stored in cc_payments / cc_estimates_by_date
    card_by_name: dict[str, models.CreditCard] = {(c.name or ""): c for c in all_active_cards}

    day_checkpoint_map: dict[date, Decimal] = {
        cp.date: cp.actual_balance
        for cp in db.query(models.ForecastDayCheckpoint).filter(
            models.ForecastDayCheckpoint.user_id == user_id,
            models.ForecastDayCheckpoint.account_id == account_id,
            models.ForecastDayCheckpoint.date >= start_date,
            models.ForecastDayCheckpoint.date <= end_date,
        ).all()
    }

    # Pre-compute which recurring item IDs have linked actuals, and on which dates.
    # Used to suppress projected entries when the actual arrives on a different day.
    actual_by_ri: dict[int, list[date]] = {}
    for t in all_actuals:
        if t.recurring_item_id:
            actual_by_ri.setdefault(t.recurring_item_id, []).append(t.date)

    entries: list[ForecastEntry] = []
    current = start_date

    while current <= end_date:
        day_transactions: list[ForecastTransaction] = []
        actuals_today = actuals_by_date.get(current, [])
        actual_recurring_ids = {t.recurring_item_id for t in actuals_today if t.recurring_item_id}
        actual_manual = [t for t in actuals_today if t.recurring_item_id is None]
        applied_txn_ids: set[int] = set()

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
                        applied_txn_ids.add(actual.id)
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

            # Suppress projected if a linked actual exists for this item but arrived on a
            # different day: monthly/yearly → any actual this calendar month; biweekly/weekly → ±3 days.
            if item.id in actual_by_ri:
                ri_actual_dates = actual_by_ri[item.id]
                freq = getattr(item, "frequency", None)
                if freq in (models.RecurringFrequency.monthly, models.RecurringFrequency.yearly):
                    if any(d.year == current.year and d.month == current.month for d in ri_actual_dates):
                        continue
                else:
                    if any(abs((d - current).days) <= 3 for d in ri_actual_dates):
                        continue

            base_amount = item.amount + override_map.get(item.id, Decimal("0"))
            is_cc = item.type == models.RecurringType.credit_card_payment

            # SS paycheck boost: accumulate gross, apply boost once wage base is hit
            ss_boost = Decimal("0")
            if ss_remaining_gross is not None and item.id in ss_paycheck_item_ids:
                if ss_limit_reached:
                    ss_boost = ss_boost_per_check
                else:
                    ss_remaining_gross -= item.amount
                    if ss_remaining_gross <= 0:
                        ss_limit_reached = True
                        ss_boost = ss_boost_per_check

            signed = (base_amount + ss_boost) if item.type == models.RecurringType.income else -base_amount
            balance += signed
            cc_name = item.card.name if is_cc and item.card else None
            day_transactions.append(ForecastTransaction(
                name=f"CC Payment: {cc_name}" if cc_name else item.name,
                amount=signed,
                type=item.type.value,
                category_name=item.category.name if item.category else None,
                is_actual=False,
                is_cc_payment=is_cc,
                recurring_item_id=item.id,
            ))

        # Apply linked actuals that arrived on a different day than their natural_fires date.
        # These have recurring_item_id set but weren't handled in the items loop above.
        for actual in actuals_today:
            if actual.recurring_item_id is not None and actual.id not in applied_txn_ids:
                balance += Decimal(str(actual.amount))
                day_transactions.append(ForecastTransaction(
                    name=actual.description,
                    amount=actual.amount,
                    type="income" if actual.amount > 0 else "expense",
                    category_name=actual.category.name if actual.category else None,
                    is_actual=True,
                    recurring_item_id=actual.recurring_item_id,
                    transaction_id=actual.id,
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

        for card_name, amount in cc_payments.get(current, []):
            # Suppress if an actual CC payment for this card was imported near this date
            card_obj = card_by_name.get(card_name)
            if card_obj and _cc_actual_nearby(card_obj, current, actuals_by_date):
                continue
            signed = -amount
            balance += signed
            day_transactions.append(ForecastTransaction(
                name=f"CC Payment: {card_name}",
                amount=signed,
                type="expense",
                category_name=None,
                is_actual=False,
                is_cc_payment=True,
            ))

        for card_name, amount in cc_estimates_by_date.get(current, []):
            # Suppress if an actual CC payment for this card was imported near this date
            card_obj = card_by_name.get(card_name)
            if card_obj and _cc_actual_nearby(card_obj, current, actuals_by_date):
                continue
            signed = -amount
            balance += signed
            day_transactions.append(ForecastTransaction(
                name=f"CC Estimate: {card_name}",
                amount=signed,
                type="expense",
                category_name="Credit Card Estimate",
                is_actual=False,
                is_cc_payment=True,
            ))

        interest_rate = getattr(account, "interest_rate", None)
        if (
            interest_rate
            and interest_rate > 0
            and current.day == _last_day_of_month(current)
        ):
            rate = Decimal(str(interest_rate))
            monthly_interest = round(balance * rate / Decimal("100") / Decimal("12"), 2)
            if monthly_interest > 0:
                balance += monthly_interest
                day_transactions.append(ForecastTransaction(
                    name="Interest Credit",
                    amount=monthly_interest,
                    type="income",
                    is_actual=False,
                ))

        # Apply day checkpoint AFTER all transactions so the anchor value is the
        # final balance for the day (and the starting point for the next day).
        if current in day_checkpoint_map:
            balance = day_checkpoint_map[current]

        entries.append(ForecastEntry(
            date=current,
            projected_balance=balance,
            transactions=day_transactions,
        ))
        current += timedelta(days=1)

    return entries


def find_balance_risk(entries: list[ForecastEntry], threshold: Decimal) -> dict:
    """Scan forecast entries in order and return the first day the balance drops
    below threshold. entries must already be sorted by date ascending (build_forecast
    returns them in that order).
    """
    for entry in entries:
        if entry.projected_balance < threshold:
            return {
                "at_risk": True,
                "date": entry.date,
                "amount": entry.projected_balance,
                "threshold": threshold,
            }
    return {"at_risk": False, "date": None, "amount": None, "threshold": threshold}


def build_quarters(
    db: Session,
    user_id: int,
    account_id: int,
    year: int,
    overrides: list[dict] | None = None,
) -> list[QuarterSummary]:
    # Build the full year in one pass so Q2+ open balances chain from Q1 close.
    full_start = date(year, 1, 1)
    full_end = date(year, 12, 31)
    all_days = build_forecast(db, user_id, account_id, full_start, full_end, overrides=overrides)
    if not all_days:
        return []

    quarters = []
    for q in range(1, 5):
        month_start = (q - 1) * 3 + 1
        start = date(year, month_start, 1)
        end_month = month_start + 2
        end = date(year, end_month, monthrange(year, end_month)[1])

        days = [d for d in all_days if start <= d.date <= end]
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
