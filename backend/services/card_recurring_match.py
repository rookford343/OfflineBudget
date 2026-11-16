"""Card-side twin of import_service._best_recurring_match.

Matches an imported credit-card transaction to a floating recurring expense
charged to that card. Non-floating card expenses have no auto-match path at
all yet -- per the floating-expenses design doc, this round only covers the
floating case, so the candidate filter below excludes everything else."""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.import_service import _evidence_tokens, _name_score
from backend.services.recurring_schedule import _fires_in_month

# Wider than the checking-side bills' +/-15% (import_service._AMOUNT_RATIO,
# left untouched): a card-charged floating item like a haircut has more
# day-to-day amount variance (tips) than a fixed bill does. Decided by the
# controller, not carried over unexamined -- the design doc flagged the
# checking-side constant as an open question for this exact case.
_CARD_AMOUNT_RATIO = (Decimal("0.70"), Decimal("1.30"))


def best_card_recurring_match(
    candidates: list[models.RecurringItem],
    description: str,
    amount: Decimal,
    on: date,
    confirmed_amounts: dict[int, list[Decimal]],
    payee_history: dict[int, set[str]],
) -> models.RecurringItem | None:
    """The one place an imported credit-card transaction is matched to a
    floating recurring expense.

    Same contract and evidence/amount gates as
    import_service._best_recurring_match, with two scope differences:
      - a candidate must be charged to a card (`card_id is not None`)
        instead of to checking (`card_id is None`);
      - only `is_floating` items are matched -- non-floating card expenses
        stay out of scope this round, per the design doc.
    Because every matched candidate here is floating, there's no fixed due
    date to be "near", so there's no +/-window check at all (unlike the
    checking matcher, which still has one for its non-floating candidates):
    every candidate must fire somewhere in the transaction's calendar month.
    That check reuses the shared `_fires_in_month` helper (recurring_schedule.
    py, also used by import_service._best_recurring_match's floating branch
    and recurring_floating_status.py), which loops `_fires_on` over each day
    of the month rather than an inline start_date/end_date bounds check, so
    the floating path runs under the exact same is_active/start_date/end_date
    gate as every other candidate -- the checking-side matcher special-cased
    this away once and had to revert it after review; see that function's
    docstring/history for why.

    Scoped to monthly, same as import_service._best_recurring_match's
    floating branch: nothing enforces "is_floating implies monthly" at the
    data layer (no validator ties the two together in schemas.py/
    routers/recurring.py), so a weekly/biweekly/quarterly/yearly card item
    could be flagged is_floating via an ordinary PATCH. Without this guard,
    the whole-month loop would treat "fires somewhere in the month" as a
    pass for an item that already fires several times a month, which is far
    more permissive than even the old +/-window ever was -- effectively no
    date filtering at all for that item.
    """
    amount = abs(amount)
    lo, hi = _CARD_AMOUNT_RATIO
    words = _evidence_tokens(description)
    best, best_key = None, (0, 0)
    for item in candidates:
        if (
            item.card_id is None
            or not item.is_floating
            or item.amount <= 0
            or item.frequency != models.RecurringFrequency.monthly
        ):
            continue
        name_hits = _name_score(description, item.name)
        history_hits = len(words & payee_history.get(item.id, set()))
        if not (name_hits or history_hits):
            continue
        if not _fires_in_month(item, on.year, on.month):
            continue
        targets = [item.amount, *confirmed_amounts.get(item.id, [])]
        if not any(t > 0 and lo <= amount / t <= hi for t in targets):
            continue
        key = (name_hits, history_hits)
        if key > best_key:
            best, best_key = item, key
    return best
