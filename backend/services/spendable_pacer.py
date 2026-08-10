"""Weekly spendable pacer -- a transaction-driven, calendar-week view into
the same monthly discretionary budget `budget_snapshot.py` already computes
as `leftover`. Does NOT touch left_to_spend/not_saving (spreadsheet-verified,
balance-derived, unchanged) -- this is a second, independent calculation
that fixes the gap those formulas have: discretionary checking/debit
spending never moved them at all, only credit card balances did.

No persisted state. Every value here is recomputed fresh from `leftover`
(caller-supplied) and actual Transaction/CreditCardTransaction rows on every
call, so a week's over/underspend is automatically visible today and
automatically reshapes every later week's target this month -- one shared
pool, not four independent per-week budgets.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta
from decimal import Decimal


def week_bounds(as_of: date) -> tuple[date, date]:
    """The Sunday-Saturday calendar week containing as_of."""
    # date.weekday(): Monday=0 .. Sunday=6. Convert to "days since Sunday".
    days_since_sunday = (as_of.weekday() + 1) % 7
    week_start = as_of - timedelta(days=days_since_sunday)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def weeks_remaining_in_month(as_of: date) -> Decimal:
    """Fractional weeks remaining in as_of's month, counting today through
    month-end inclusive, in 7-day units -- e.g. a 3-day final stretch of
    the month counts as 3/7, not a full week. Always > 0 since as_of is
    always on or before its own month's last day."""
    last_day = calendar.monthrange(as_of.year, as_of.month)[1]
    month_end = date(as_of.year, as_of.month, last_day)
    days_remaining = (month_end - as_of).days + 1
    return Decimal(days_remaining) / Decimal(7)
