"""Real month totals for the Recurring page.

Unlike services/recurring_math.monthly_equivalent (a smoothed "what does this
cost per month on average" figure used by /recurring/breakdown), this answers
"what actually lands in this specific calendar month": every day of the month
is walked through forecast_engine._fires_on, the same predicate build_forecast
itself uses, so this can never disagree with the day-by-day cash forecast on
start/end dates, quarterly/yearly firing months, or last-day (day_of_month=0)
handling.

Scoped to the user, not an account -- like /recurring/breakdown, this covers
every active recurring item the user owns regardless of which account it's
on, since the Recurring page has no per-account context to filter by.
"""
from __future__ import annotations
from calendar import monthrange
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.forecast_engine import _fires_on


def build_month_summary(db: Session, user_id: int, year: int, month: int) -> schemas.MonthSummaryOut:
    last_day = monthrange(year, month)[1]
    days = [date(year, month, d) for d in range(1, last_day + 1)]
    month_start, month_end = days[0], days[-1]

    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.is_active == True,
        models.RecurringItem.type != models.RecurringType.credit_card_payment,
        # Real but not cash landing this month -- e.g. an annual bonus
        # modelled as 1/12th per month for budget planning (models.py's own
        # comment on this column). build_forecast excludes these from the
        # day-by-day forecast the same way (forecast_engine.py ~line 329 and
        # ~488); this summary has to agree with it or "real cash this month"
        # stops being true.
        models.RecurringItem.include_in_forecast == True,
    ).all()

    # Keyed by (recurring_item_id, due_date) so a lookup during the day walk
    # is exact -- mirrors build_forecast's own bill_actuals map (~line 407).
    overrides: dict[tuple[int, date], Decimal] = {
        (o.recurring_item_id, o.due_date): o.actual_amount
        for o in db.query(models.BillAmountOverride).filter(
            models.BillAmountOverride.user_id == user_id,
            models.BillAmountOverride.due_date >= month_start,
            models.BillAmountOverride.due_date <= month_end,
        ).all()
    }

    income_items: list[schemas.MonthIncomeOccurrence] = []
    monthly_bills: list[schemas.MonthlyBillOccurrence] = []
    periodic_due: list[schemas.PeriodicDueOccurrence] = []

    monthly_like = {
        models.RecurringFrequency.monthly,
        models.RecurringFrequency.weekly,
        models.RecurringFrequency.biweekly,
    }

    for item in items:
        for d in days:
            if not _fires_on(item, d):
                continue

            override = overrides.get((item.id, d))
            amount = override if override is not None else item.amount
            overridden = override is not None

            if item.type == models.RecurringType.income:
                income_items.append(schemas.MonthIncomeOccurrence(
                    recurring_item_id=item.id, name=item.name, date=d, amount=amount,
                ))
            elif item.frequency in monthly_like:
                monthly_bills.append(schemas.MonthlyBillOccurrence(
                    recurring_item_id=item.id, name=item.name, date=d, amount=amount,
                    overridden=overridden, card_id=item.card_id,
                ))
            else:  # quarterly / yearly
                periodic_due.append(schemas.PeriodicDueOccurrence(
                    recurring_item_id=item.id, name=item.name, frequency=item.frequency,
                    date=d, amount=amount, overridden=overridden, card_id=item.card_id,
                ))

    income_items.sort(key=lambda o: o.date)
    monthly_bills.sort(key=lambda o: o.date)
    periodic_due.sort(key=lambda o: o.date)

    income_total = sum((o.amount for o in income_items), Decimal("0"))
    monthly_bills_total = sum((o.amount for o in monthly_bills), Decimal("0"))
    periodic_total = sum((o.amount for o in periodic_due), Decimal("0"))
    expense_total = monthly_bills_total + periodic_total

    # Not scoped by due_date/expected_date up front (unlike the override
    # query) because the effective date can be settled_on, which may differ
    # from expected_date -- filtered below, after computing which date to use.
    planned = db.query(models.PlannedExpense).filter(
        models.PlannedExpense.user_id == user_id,
    ).all()

    one_offs: list[schemas.OneOffOccurrence] = []
    for pe in planned:
        settled = pe.settled_on is not None
        if settled:
            eff_date = pe.settled_on
            eff_amount = pe.actual_amount if pe.actual_amount is not None else pe.amount
        else:
            eff_date = pe.expected_date
            eff_amount = pe.amount
        if eff_date.year != year or eff_date.month != month:
            continue
        one_offs.append(schemas.OneOffOccurrence(
            planned_expense_id=pe.id, name=pe.name, date=eff_date,
            amount=abs(eff_amount), direction=pe.direction, settled=settled,
        ))

    one_offs.sort(key=lambda o: o.date)
    one_off_out_total = sum(
        (o.amount for o in one_offs if o.direction == models.PlannedDirection.outflow), Decimal("0"),
    )
    one_off_in_total = sum(
        (o.amount for o in one_offs if o.direction == models.PlannedDirection.inflow), Decimal("0"),
    )

    left_over = income_total - expense_total - one_off_out_total + one_off_in_total

    return schemas.MonthSummaryOut(
        year=year, month=month,
        income_items=income_items, income_total=income_total,
        monthly_bills=monthly_bills, monthly_bills_total=monthly_bills_total,
        periodic_due=periodic_due, periodic_total=periodic_total,
        expense_total=expense_total,
        one_offs=one_offs, one_off_out_total=one_off_out_total, one_off_in_total=one_off_in_total,
        left_over=left_over,
    )
