"""Shared "what's coming due" logic for recurring items.

Two callers used to compute this independently and drifted: GET
/recurring/upcoming (the Dashboard's Upcoming Bills card, backend/routers/
recurring.py) read `summary_generator._next_fire_date` for the real next
occurrence and substituted the confirmed BillAmountOverride for that exact
(recurring_item_id, due_date) pair, while the daily email's "Upcoming (next
7 days)" section (backend/services/summary_generator.py) used the same
_next_fire_date but read RecurringItem.amount directly -- so entering the
real billed amount as an override changed the Dashboard card but never
changed what the email showed. Bug found 2026-10-04, see
.superpowers/sdd/sync-race/brief.md.

This module is the single source of truth both callers now go through.
`_next_fire_date` stays put in summary_generator.py (existing tests import
it from there directly) and is imported lazily here, at call time, to avoid
a module-load-order cycle with summary_generator.py importing this module.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models


@dataclass(frozen=True)
class UpcomingBill:
    recurring_item_id: int
    name: str
    due_date: date
    # The confirmed actual for this exact (item, due_date) when one exists,
    # else the item's own planning amount -- estimated_amount always stays
    # the planning amount so a caller can show both.
    amount: Decimal
    estimated_amount: Decimal
    is_actual: bool
    card_id: int | None
    type: models.RecurringType


def upcoming_bills(
    db: Session,
    user_id: int,
    today: date,
    days: int,
    *,
    types: list[models.RecurringType] | None = None,
) -> list[UpcomingBill]:
    """Active recurring items firing within [today, today+days], with the
    confirmed BillAmountOverride substituted in for amount where one exists.

    `types` restricts which RecurringItem.type values are considered; `None`
    (the default) considers every type, matching the daily email's existing
    row set (income shown alongside expenses, with its own sign/color). The
    Dashboard's GET /recurring/upcoming passes `[RecurringType.expense]` to
    keep its own existing, narrower row set unchanged.

    Returned in whatever order the underlying query yields (unsorted) --
    callers already have their own sort (the router sorts by (due_date,
    name); the email sorts by due_date only), so sorting is left to them
    rather than imposed here.
    """
    from backend.services.summary_generator import _next_fire_date

    query = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.is_active == True,
    )
    if types:
        query = query.filter(models.RecurringItem.type.in_(types))
    items = query.all()

    due: list[tuple[models.RecurringItem, date]] = [
        (item, d) for item in items if (d := _next_fire_date(item, today, days)) is not None
    ]

    overrides: dict[tuple[int, date], Decimal] = {
        (o.recurring_item_id, o.due_date): o.actual_amount
        for o in db.query(models.BillAmountOverride).filter(
            models.BillAmountOverride.user_id == user_id,
            models.BillAmountOverride.due_date >= today,
            models.BillAmountOverride.due_date <= today + timedelta(days=days),
        ).all()
    }

    return [
        UpcomingBill(
            recurring_item_id=item.id,
            name=item.name,
            due_date=d,
            amount=overrides.get((item.id, d), item.amount),
            estimated_amount=item.amount,
            is_actual=(item.id, d) in overrides,
            card_id=item.card_id,
            type=item.type,
        )
        for item, d in due
    ]
