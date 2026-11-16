"""Per-item, per-month Matched/Pending/Skipped status for floating recurring
items -- GET /recurring/floating-status (Task 5 of the
floating-recurring-expenses plan).

A floating item has no fixed due date (checking/card matching -- Tasks 2/4 --
accepts the real transaction anywhere in the item's due month), so "did this
happen yet" can't be read off a single date the way a fixed-day bill can.
This answers it per item for one calendar month by checking, in order:

  1. matched -- a Transaction (checking item) or CreditCardTransaction (card
     item, card_id set) linked via recurring_item_id with a date inside the
     month. Wins over a skip: per the design doc, finding both a skip row
     and a real match for the same (item, year, month) is a stale-skip
     condition, not a tie to display -- the skip row is deleted here as
     part of computing status, so the database never sits in that
     contradictory state.
  2. skipped -- a RecurringSkip row exists for (item, year, month).
  3. pending -- neither.
"""
from __future__ import annotations
from calendar import monthrange
from datetime import date
from sqlalchemy.orm import Session
from backend import models, schemas


def build_floating_status(
    db: Session, user_id: int, year: int, month: int,
) -> list[schemas.RecurringFloatingStatus]:
    last_day = monthrange(year, month)[1]
    month_start, month_end = date(year, month, 1), date(year, month, last_day)

    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.is_active == True,
        models.RecurringItem.is_floating == True,
    ).order_by(models.RecurringItem.id).all()

    rows: list[schemas.RecurringFloatingStatus] = []
    for item in items:
        match = _find_match(db, item, month_start, month_end)
        if match is not None:
            # Match wins over skip -- clear the now-stale skip row rather
            # than report "matched" while leaving the database holding a
            # contradictory "skipped" row for the same month.
            db.query(models.RecurringSkip).filter(
                models.RecurringSkip.recurring_item_id == item.id,
                models.RecurringSkip.year == year,
                models.RecurringSkip.month == month,
            ).delete()
            matched_amount = abs(match.amount)
            rows.append(schemas.RecurringFloatingStatus(
                recurring_item_id=item.id, status="matched",
                matched_date=match.date, matched_amount=matched_amount,
                variance=matched_amount - item.amount,
            ))
            continue

        skipped = db.query(models.RecurringSkip).filter(
            models.RecurringSkip.recurring_item_id == item.id,
            models.RecurringSkip.year == year,
            models.RecurringSkip.month == month,
        ).first() is not None
        rows.append(schemas.RecurringFloatingStatus(
            recurring_item_id=item.id,
            status="skipped" if skipped else "pending",
        ))

    db.commit()
    return rows


def _find_match(
    db: Session, item: models.RecurringItem, month_start: date, month_end: date,
) -> models.Transaction | models.CreditCardTransaction | None:
    """A card-linked floating item (card_id set) matches against
    CreditCardTransaction; every other floating item matches against the
    checking-side Transaction table -- same split Task 4 drew between the
    two matchers."""
    if item.card_id is not None:
        return db.query(models.CreditCardTransaction).filter(
            models.CreditCardTransaction.recurring_item_id == item.id,
            models.CreditCardTransaction.date >= month_start,
            models.CreditCardTransaction.date <= month_end,
        ).order_by(models.CreditCardTransaction.date).first()
    return db.query(models.Transaction).filter(
        models.Transaction.recurring_item_id == item.id,
        models.Transaction.date >= month_start,
        models.Transaction.date <= month_end,
    ).order_by(models.Transaction.date).first()
