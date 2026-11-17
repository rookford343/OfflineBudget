"""Promotes a scheduled amount change once its effective date arrives."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from backend import models


def promote_due_pending_amounts(db: Session, as_of: date) -> list[int]:
    """Every RecurringItem whose pending_amount_effective_date has arrived:
    amount becomes pending_amount, and both pending fields clear. Returns the
    promoted ids. Safe to call repeatedly -- an item with nothing pending, or
    whose date hasn't arrived yet, is left untouched."""
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.pending_amount.isnot(None),
        models.RecurringItem.pending_amount_effective_date <= as_of,
    ).all()
    for item in items:
        item.amount = item.pending_amount
        item.pending_amount = None
        item.pending_amount_effective_date = None
    db.commit()
    return [item.id for item in items]
