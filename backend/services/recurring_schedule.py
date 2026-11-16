"""Shared "does this item fire somewhere in this calendar month" check.

Used by the checking and card floating matchers
(import_service._best_recurring_match / card_recurring_match.
best_card_recurring_match) to decide whether a floating item is even a
candidate for a transaction's month, and by recurring_floating_status.py to
decide whether a floating item should show a Matched/Pending/Skipped row for
the requested month at all.

Before this module existed, each matcher looped `_fires_on` over every day
of the month inline -- duplicated almost verbatim between the two files --
and the status service didn't do this check at all, so an item that hadn't
started yet, had already ended, or wasn't actually monthly (nothing at the
data layer ties is_floating to frequency == monthly) could still show
"Pending -- expected this month" with a Skip button for a month
month_base.py/forecast_engine.py had already correctly excluded it from.
"""
from __future__ import annotations
from calendar import monthrange
from datetime import date
from backend import models


def _fires_in_month(item: models.RecurringItem, year: int, month: int) -> bool:
    """True if `item` fires on at least one day of (year, month), honouring
    the exact same is_active/start_date/end_date/frequency gate every other
    _fires_on check already runs under -- no special-casing for the
    floating path, which is what the checking-side matcher had to revert to
    once before (see import_service._best_recurring_match's history)."""
    from backend.services.forecast_engine import _fires_on

    days_in_month = monthrange(year, month)[1]
    return any(_fires_on(item, date(year, month, day)) for day in range(1, days_in_month + 1))
