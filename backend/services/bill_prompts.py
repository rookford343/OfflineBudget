"""Statement-date prompts ("Bills to confirm").

A monthly checking bill can carry an optional statement day (e.g. Duke
Electric's statement lands around the 17th). Around that day the app asks
for the real amount of the bill due next, saving the answer through the
existing bill-override feature (BillAmountOverride / POST /bill-overrides)
so the forecast uses it for that one due date -- the same mechanism the
Recurring page's inline $ button already writes to.

Window rule, given today T, an eligible item with statement day S and due
day `day_of_month` (0 = last day, the existing RecurringItem convention):

1. S_this = day S of T's month, clamped to the month length. If
   T >= S_this - 1 day, D = S_this. Otherwise D = day S of the PREVIOUS
   month, clamped.
2. due = the first occurrence of day_of_month strictly after D.
3. Prompt when D - 1 day <= T <= due and no BillAmountOverride exists for
   (item.id, due).

Worked example, Duke with S=17 and due day 8:
  - Oct 16 prompts (D = Oct 17, due = Nov 8).
  - Oct 15 doesn't (D = Sep 17, due = Oct 8, already passed).
  - Nov 5 still prompts (same window) unless the amount was already entered.
  - Nov 9: no prompt (window closed the day after the due date).
"""
from __future__ import annotations
from calendar import monthrange
from datetime import date, timedelta
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.forecast_engine import _next_occurrence_on_or_after


def _clamp_day(year: int, month: int, day: int) -> int:
    return min(day, monthrange(year, month)[1])


def _statement_date_for_month(year: int, month: int, statement_day: int) -> date:
    return date(year, month, _clamp_day(year, month, statement_day))


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year, month - 1) if month > 1 else (year - 1, 12)


def _statement_date(today: date, statement_day: int) -> date:
    """D: the statement date this bill's window is anchored to -- this
    month's once it's due to have arrived (from one day before it),
    otherwise last month's, whose due date may still be open."""
    this_month = _statement_date_for_month(today.year, today.month, statement_day)
    if today >= this_month - timedelta(days=1):
        return this_month
    prev_year, prev_month = _previous_month(today.year, today.month)
    return _statement_date_for_month(prev_year, prev_month, statement_day)


def bills_to_confirm(db: Session, user_id: int, today: date) -> list[schemas.BillToConfirmOut]:
    """Eligible items: the same rule as Recurring.tsx's inline $ button
    (canOverride) -- active, expense, monthly, no card -- plus a statement
    day set. Returns one entry per item currently inside its window and not
    yet overridden for that due date, sorted by due date.
    """
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.is_active == True,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.frequency == models.RecurringFrequency.monthly,
        models.RecurringItem.card_id.is_(None),
        models.RecurringItem.statement_day.isnot(None),
    ).all()

    out: list[schemas.BillToConfirmOut] = []
    for item in items:
        statement_date = _statement_date(today, item.statement_day)
        due_date = _next_occurrence_on_or_after(item.day_of_month, statement_date + timedelta(days=1))
        if not (statement_date - timedelta(days=1) <= today <= due_date):
            continue

        already_confirmed = db.query(models.BillAmountOverride).filter(
            models.BillAmountOverride.user_id == user_id,
            models.BillAmountOverride.recurring_item_id == item.id,
            models.BillAmountOverride.due_date == due_date,
        ).first()
        if already_confirmed:
            continue

        out.append(schemas.BillToConfirmOut(
            recurring_item_id=item.id,
            name=item.name,
            estimated_amount=item.amount,
            statement_date=statement_date,
            due_date=due_date,
        ))

    out.sort(key=lambda b: b.due_date)
    return out
