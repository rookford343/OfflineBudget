"""'Amounts changed?' prompts.

A recurring expense whose latest linked payment (a real transaction tied to
it by recurring_item_id) differs from its planned amount asks the user
whether to use the new amount going forward. The app never changes the
amount by itself.

Rules, for an active monthly-or-other expense that is not marked
amount_varies and has no statement_day (those are confirmed every month
through "Bills to confirm" instead):

1. Look at linked actual payments in the last LOOKBACK_DAYS.
2. Flag when the latest one differs from the plan by more than
   MIN_PCT of the plan AND more than MIN_DOLLARS, and is newer than the
   last payment the user already answered "Keep" for.
3. The suggestion is the latest payment, not an average: a price change is
   a step, and an average across it is a number nobody pays.
4. If none of the last VARIES_SAMPLE payments agree with each other (within
   AGREE_PCT), the item swings on its own and is offered "stop asking"
   instead of a number. One odd charge among steady ones (a device bought
   on a phone bill) doesn't count: two steady payments still agree.

Income is left out: a paycheck's deposits move with withholding (e.g. the
Social Security wage-base boost the forecast already models), which would
look like drift that isn't.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models, schemas

LOOKBACK_DAYS = 120
MIN_PCT = Decimal("0.01")
MIN_DOLLARS = Decimal("5")
AGREE_PCT = Decimal("0.05")
VARIES_SAMPLE = 3


def _agree(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(a, b) * AGREE_PCT


def _recent_payments(db: Session, item: models.RecurringItem, today: date) -> list[models.Transaction]:
    return (
        db.query(models.Transaction)
        .filter(
            models.Transaction.user_id == item.user_id,
            models.Transaction.recurring_item_id == item.id,
            models.Transaction.is_actual.is_(True),
            models.Transaction.date >= today - timedelta(days=LOOKBACK_DAYS),
            models.Transaction.date <= today,
        )
        .order_by(models.Transaction.date.desc(), models.Transaction.id.desc())
        .all()
    )


def _drift_for(db: Session, item: models.RecurringItem, today: date) -> schemas.AmountDriftOut | None:
    payments = _recent_payments(db, item, today)
    if not payments:
        return None
    latest = payments[0]
    if item.drift_dismissed_through and latest.date <= item.drift_dismissed_through:
        return None
    planned = Decimal(item.amount)
    paid = abs(Decimal(latest.amount))
    diff = abs(paid - planned)
    if diff <= planned * MIN_PCT or diff <= MIN_DOLLARS:
        return None
    sample = [abs(Decimal(p.amount)) for p in payments[:VARIES_SAMPLE]]
    varies = len(sample) == VARIES_SAMPLE and not any(
        _agree(a, b) for i, a in enumerate(sample) for b in sample[i + 1:]
    )
    return schemas.AmountDriftOut(
        recurring_item_id=item.id, name=item.name, type=item.type,
        planned_amount=planned, latest_amount=paid, latest_date=latest.date,
        recent_amounts=sample, varies=varies,
    )


def _eligible(db: Session, user_id: int):
    return db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.is_active.is_(True),
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.statement_day.is_(None),
        models.RecurringItem.amount_varies.isnot(True),
    )


def items_with_drift(db: Session, user_id: int, today: date) -> list[schemas.AmountDriftOut]:
    found = (_drift_for(db, item, today) for item in _eligible(db, user_id).order_by(models.RecurringItem.name))
    return [d for d in found if d is not None]


def answer_drift(db: Session, user_id: int, item_id: int, action: str, today: date) -> models.RecurringItem:
    """Apply the user's answer. Raises LookupError when the item is not the
    user's or has no open prompt, so a stale screen can't change an amount."""
    item = _eligible(db, user_id).filter(models.RecurringItem.id == item_id).first()
    drift = _drift_for(db, item, today) if item else None
    if drift is None:
        raise LookupError("no amount change to answer for this item")
    if action == "update":
        item.amount = drift.latest_amount
    elif action == "varies":
        item.amount_varies = True
    item.drift_dismissed_through = drift.latest_date
    db.commit()
    db.refresh(item)
    return item
