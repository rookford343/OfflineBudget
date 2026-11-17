"""Promotes a scheduled amount change once its effective date arrives."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend import models


def promote_due_pending_amounts(db: Session, as_of: date) -> list[int]:
    """Every RecurringItem whose pending_amount_effective_date has arrived:
    amount becomes pending_amount, and both pending fields clear. Returns the
    promoted ids. Safe to call repeatedly -- an item with nothing pending, or
    whose date hasn't arrived yet, is left untouched.

    Also pushes drift_dismissed_through (services/amount_drift.py) to the day
    before the new amount took effect, never pulling it backward if it's
    already later. Without this, the last linked payment -- made at the OLD
    amount -- would immediately trip the "Amounts changed?" drift prompt
    against the item's new amount, offering to revert the very change just
    promoted."""
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.pending_amount.isnot(None),
        models.RecurringItem.pending_amount_effective_date <= as_of,
    ).all()
    for item in items:
        cutoff = item.pending_amount_effective_date - timedelta(days=1)
        item.drift_dismissed_through = (
            max(item.drift_dismissed_through, cutoff)
            if item.drift_dismissed_through is not None
            else cutoff
        )
        item.amount = item.pending_amount
        item.pending_amount = None
        item.pending_amount_effective_date = None
    db.commit()
    return [item.id for item in items]
