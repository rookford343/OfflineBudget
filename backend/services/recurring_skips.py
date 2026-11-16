"""Shared "is this RecurringSkip still in effect" check.

A match always wins over a skip (design doc §3 "My call"): if a transaction
later links to a floating item for a month that already has a RecurringSkip
row, the match overrides it. Before this module existed, that rule was only
enforced inside recurring_floating_status.py's own status computation --
i.e. only when something called GET /recurring/floating-status for that
exact item/year/month -- and NOT when a transaction actually got linked via
import_service._try_auto_match / _try_auto_match_card, run_import's direct
recurring_item_id assignment, or routers/recurring.py's link_pattern_to_item
backfill. month_base.py and forecast_engine.py both read the RecurringSkip
table directly, with no awareness that a real match had already landed, so
a real linked charge could silently disappear from Leftover, discretionary
spend, and the forecast until someone happened to open the Recurring page
for that exact month (which deleted the stale row as a side effect of being
read, masking the problem for every month anyone had actually looked at).

`effective_skips` is the one place that answers "is this skip still true"
-- a skip whose (recurring_item_id, year, month) has a linked Transaction
(checking) or CreditCardTransaction (card) dated in that month is stale and
is excluded from the returned set. month_base.py, forecast_engine.py, and
recurring_floating_status.py all call this instead of querying
RecurringSkip directly, so all three agree on "effective" consistently --
and none of them need to delete the stale row to behave correctly: it
simply has no effect anywhere once a real match exists.
"""
from __future__ import annotations
from calendar import monthrange
from datetime import date
from typing import Iterable
from sqlalchemy.orm import Session
from backend import models


def effective_skips(
    db: Session,
    user_id: int,
    item_ids: Iterable[int],
    year: int | None = None,
    month: int | None = None,
) -> set[tuple[int, int, int]]:
    """RecurringSkip rows for `item_ids` (optionally narrowed to one (year,
    month)) that have no linked transaction yet -- i.e. still-in-effect
    skips. Returns a set of (recurring_item_id, year, month) tuples."""
    item_ids = list(item_ids)
    if not item_ids:
        return set()

    q = db.query(models.RecurringSkip).filter(
        models.RecurringSkip.user_id == user_id,
        models.RecurringSkip.recurring_item_id.in_(item_ids),
    )
    if year is not None:
        q = q.filter(models.RecurringSkip.year == year)
    if month is not None:
        q = q.filter(models.RecurringSkip.month == month)
    skips = q.all()
    if not skips:
        return set()

    items_by_id = {
        i.id: i
        for i in db.query(models.RecurringItem).filter(
            models.RecurringItem.id.in_({s.recurring_item_id for s in skips}),
        ).all()
    }

    out: set[tuple[int, int, int]] = set()
    for s in skips:
        item = items_by_id.get(s.recurring_item_id)
        # No item (deleted, or an id the caller passed that doesn't resolve)
        # -- nothing to check a match against, so the skip stands.
        if item is None or not _has_linked_match(db, item, s.year, s.month):
            out.add((s.recurring_item_id, s.year, s.month))
    return out


def _has_linked_match(db: Session, item: models.RecurringItem, year: int, month: int) -> bool:
    """True if a real Transaction/CreditCardTransaction is already linked to
    `item` with a date inside (year, month) -- the same card_id-set split
    recurring_floating_status.py's own matcher uses."""
    last_day = monthrange(year, month)[1]
    month_start, month_end = date(year, month, 1), date(year, month, last_day)
    if item.card_id is not None:
        return db.query(models.CreditCardTransaction.id).filter(
            models.CreditCardTransaction.recurring_item_id == item.id,
            models.CreditCardTransaction.date >= month_start,
            models.CreditCardTransaction.date <= month_end,
        ).first() is not None
    return db.query(models.Transaction.id).filter(
        models.Transaction.recurring_item_id == item.id,
        models.Transaction.date >= month_start,
        models.Transaction.date <= month_end,
    ).first() is not None
