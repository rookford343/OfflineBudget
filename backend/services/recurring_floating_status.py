"""Per-item, per-month Matched/Pending/Skipped status for floating recurring
items -- GET /recurring/floating-status (Task 5 of the
floating-recurring-expenses plan).

A floating item has no fixed due date (checking/card matching -- Tasks 2/4 --
accepts the real transaction anywhere in the item's due month), so "did this
happen yet" can't be read off a single date the way a fixed-day bill can.
This answers it per item for one calendar month by checking, in order:

  1. matched -- a Transaction (checking item) or CreditCardTransaction (card
     item, card_id set) linked via recurring_item_id with a date inside the
     month.
  2. skipped -- an effective (still-in-effect) RecurringSkip row exists for
     (item, year, month). effective_skips() -- shared with month_base.py and
     forecast_engine.py -- already excludes a skip whose month has a real
     linked match, so a match always wins over a skip consistently, without
     this function needing to delete the stale row itself: it simply has no
     effect, here or anywhere else, once a real match exists. (Status
     "matched" above is derived straight from a linked transaction existing,
     so the ordering here can never produce both "matched" and "skipped" for
     the same (item, year, month) even with the stale row left in place.)
  3. pending -- neither, and the item actually fires this month
     (_fires_in_month) -- an item that hasn't started yet, has already
     ended, or isn't monthly is left out entirely rather than shown as
     "Pending" with a Skip button for a month month_base.py/
     forecast_engine.py already exclude it from.
"""
from __future__ import annotations
from calendar import monthrange
from datetime import date
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.services.recurring_schedule import _fires_in_month
from backend.services.recurring_skips import effective_skips


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
    # Nothing at the data layer ties is_floating to frequency == monthly
    # (schemas.py's validators reject the combination through the API, but
    # a row from before that validation existed could still have it) --
    # same explicit monthly guard the checking/card matchers already carry
    # alongside their own _fires_in_month check, for the same reason: a
    # weekly/biweekly/quarterly/yearly item fires correctly within the
    # month by _fires_in_month's definition, just more than once, which
    # isn't a shape this one-row-per-item-per-month status display can
    # represent.
    items = [
        i for i in items
        if i.frequency == models.RecurringFrequency.monthly and _fires_in_month(i, year, month)
    ]

    skipped_item_ids = {
        item_id
        for (item_id, _y, _m) in effective_skips(
            db, user_id, [i.id for i in items], year=year, month=month,
        )
    }

    rows: list[schemas.RecurringFloatingStatus] = []
    for item in items:
        match = _find_match(db, item, month_start, month_end)
        if match is not None:
            matched_amount = abs(match.amount)
            rows.append(schemas.RecurringFloatingStatus(
                recurring_item_id=item.id, status="matched",
                matched_date=match.date, matched_amount=matched_amount,
                variance=matched_amount - item.amount,
            ))
            continue

        rows.append(schemas.RecurringFloatingStatus(
            recurring_item_id=item.id,
            status="skipped" if item.id in skipped_item_ids else "pending",
        ))

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
