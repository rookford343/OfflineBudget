"""Weekly spendable pacer -- a transaction-driven, calendar-week view into
the same monthly discretionary budget `budget_snapshot.py` already computes
as `leftover`. Does NOT touch left_to_spend/safety_margin (spreadsheet-verified,
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
from sqlalchemy.orm import Session
from backend import models
from backend.services.month_base import build_month_base, card_bill_occurrences


# Categories whose BUDGETED amount budget_snapshot.py already removes from the
# monthly pool up front, via _budget_allocation_total(..., "Savings"/"Groceries").
# Subtracting their ACTUAL spend here too would deduct the same money twice --
# once as a budget line, again as a transaction. Matched by exact, case-sensitive
# name because that is precisely what budget_snapshot.py hardcodes. The
# savings-category transfer verdict (services/real_spend.py) does NOT cover these: real users
# routinely type their "Savings"/"Groceries" categories as `expense`.
# Groceries is back on this list: budget_snapshot removes the Groceries
# BUDGET from the pool up front, so counting the actual spend here too would
# deduct the same money twice.
_EXCLUDED_CATEGORY_NAMES = ("Groceries", "Savings")

# Moved to spending_helpers 2026-08-15 and re-exported here for the existing
# tests that import it. Holding the only copy in this module is why the
# Spending page and the weekly email -- which read through spending_helpers --
# never got this exclusion and counted card payoffs and transfers as spend.
from backend.services.spending_helpers import (  # noqa: E402, F401 -- re-export for tests that import it from here
    is_real_checking_spend,
)


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


def _recurring_card_charges_in_range(db: Session, user_id: int, start: date, end: date) -> Decimal:
    """Card bills (card-linked recurring expenses) landing in [start, end],
    taken from the same list Leftover subtracts: build_month_base's
    card-linked occurrences (month_base.card_bill_occurrences) at their
    month-base amounts -- weekly and biweekly bills each time they fire,
    quarterly and yearly bills in the month they're due, an entered statement
    amount in place of the item's base amount. The same source as Left to
    Spend's card add-back (budget_snapshot's card_bills_charged), so a card
    bill Leftover already subtracted never also counts as discretionary card
    spend.

    Walks every month the range touches, so it still works when a calendar
    week straddles a month boundary. Like card_bills_charged, a bill counts
    on its due day whether or not the real CreditCardTransaction has posted
    yet -- the same accepted tradeoff.

    Until 2026-11 this ran its own day-of-month walk that knew only monthly
    and yearly bills at item.amount: a weekly, biweekly or quarterly card
    bill counted as discretionary spend on top of Leftover subtracting it,
    and an entered statement amount left the difference behind.
    """
    user = db.get(models.User, user_id)
    if user is None:
        return Decimal("0")
    total = Decimal("0")
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        base = build_month_base(db, user, year, month)
        total += sum(
            (o.amount for o in card_bill_occurrences(base) if start <= o.date <= end),
            Decimal("0"),
        )
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return total


def _is_pacer_excluded(row) -> bool:
    """Spend the pacer leaves out because Leftover already holds it: rows in
    the Groceries/Savings budget lines (see _EXCLUDED_CATEGORY_NAMES)."""
    return row.category is not None and row.category.name in _EXCLUDED_CATEGORY_NAMES


def discretionary_spend_checking(db: Session, user_id: int, start: date, end: date) -> Decimal:
    """Checking real spending (services/real_spend.py: refunds net, card
    payoffs, transfers, savings and income categories excluded) minus what
    Leftover already counts: posted recurring bills, Groceries/Savings budget
    lines, and the debit that verified a planned transfer."""
    from backend.services.real_spend import classified_rows

    verified_txn_ids = {
        row[0] for row in db.query(models.PlannedTransfer.verified_transaction_id)
        .filter(
            models.PlannedTransfer.user_id == user_id,
            models.PlannedTransfer.verified_transaction_id.isnot(None),
        ).all()
    }
    total = Decimal("0")
    for r in classified_rows(db, user_id, start, end, include_cards=False):
        t = r.row
        if r.verdict.kind != "spend" or t.recurring_item_id is not None:
            continue
        if t.id in verified_txn_ids or _is_pacer_excluded(t):
            continue
        total += r.verdict.amount
    return total


def discretionary_spend_card(db: Session, user_id: int, start: date, end: date) -> Decimal:
    """Card real spending (charges minus refunds, payments excluded, per
    services/real_spend.classify_card) outside the Groceries/Savings budget
    lines, minus card-linked recurring subscriptions already counted in
    `leftover`."""
    from backend.services.real_spend import classified_rows

    total = sum(
        (
            r.verdict.amount
            for r in classified_rows(db, user_id, start, end, include_checking=False)
            if r.verdict.kind == "spend" and not _is_pacer_excluded(r.row)
        ),
        Decimal("0"),
    )
    if total < 0:
        # Already a net refund period -- a subscription's assumed firing
        # (which may not have even posted as a real row yet, see
        # _recurring_card_charges_in_range's docstring) must not erase real
        # refunded money. Only subtract the recurring estimate from a
        # non-negative total, which is what the floor below protects.
        return total
    recurring = _recurring_card_charges_in_range(db, user_id, start, end)
    return max(total - recurring, Decimal("0"))


def discretionary_spend_in_range(db: Session, user_id: int, start: date, end: date) -> Decimal:
    """Total discretionary spend (checking + card) in [start, end] --
    excludes bills, savings movements, and card subscriptions already
    counted elsewhere. See module docstring."""
    return discretionary_spend_checking(db, user_id, start, end) + discretionary_spend_card(db, user_id, start, end)


from dataclasses import dataclass


@dataclass
class WeeklySpendable:
    spendable_this_week: Decimal
    spendable_today: Decimal
    days_left_in_week: int
    on_pace: bool
    # The month-level figure this week's number is a share of. Exposed so the
    # UI can show week and month from ONE calculation: pairing the pacer's
    # weekly value with the legacy balance-derived left_to_spend showed
    # $500.00 for the week against $350.00 for the month -- a week larger
    # than the month it sits inside.
    remaining_this_month: Decimal


def compute_weekly_spendable(db: Session, user_id: int, leftover: Decimal, as_of: date) -> WeeklySpendable:
    """The weekly/daily spendable pacer. `leftover` is the caller's already-
    computed monthly discretionary budget (budget_snapshot.py's `leftover` --
    income minus fixed bills minus savings/groceries budgets). Recomputed
    fresh every call from actual transactions; no persisted state. See
    module docstring for the rollover model.

    IMPORTANT: the pool that gets divided across remaining weeks must be
    depleted only by spend from BEFORE this week (`spend_prior_to_this_week`)
    -- not month-to-date spend. Month-to-date always includes this week's
    own spend-so-far (effective_week_start is always >= month_start), so
    subtracting the full MTD total here and then ALSO subtracting this
    week's spend from the per-week target a few lines down would double
    count every dollar spent so far this week. Depleting the pool by prior
    weeks only, then subtracting this week's own spend exactly once from
    this_week_target, is what makes a prior week's overspend roll into
    later weeks without a second, redundant deduction inside the very week
    that spend happened in.
    """
    month_start = as_of.replace(day=1)
    week_start, week_end = week_bounds(as_of)
    effective_week_start = max(week_start, month_start)

    if effective_week_start > month_start:
        spend_prior_to_this_week = discretionary_spend_in_range(
            db, user_id, month_start, effective_week_start - timedelta(days=1)
        )
    else:
        spend_prior_to_this_week = Decimal("0")  # this week IS the first week of the month
    remaining_pool = leftover - spend_prior_to_this_week

    weeks_left = weeks_remaining_in_month(effective_week_start)

    # This week claims a share of the pool proportional to how many of its days
    # actually fall INSIDE this month, NOT a flat 1/weeks_left. Both ends of the
    # week must be clipped to the month for that count to be meaningful:
    # effective_week_start already clips the front (a month can open mid-week),
    # and week_end_capped clips the back (a month can end mid-week). Clipping
    # only the front is what used to make this_week_share exceed weeks_left --
    # which IS correctly capped at month end -- pushing the ratio above 1 in the
    # trailing week.
    #
    # With both ends clipped, this_week_days <= weeks_left * 7 always, so the
    # ratio lands in (0, 1] and |this_week_target| <= |remaining_pool| falls out
    # structurally -- for BOTH signs, with no clamp. That is the whole point:
    # a min() clamp only bounds a positive pool. On a negative pool min() picks
    # the MORE negative branch, inflating the deficit (-$19,500.00 shown against
    # a true -$16,500.00 on real July 2026 data) and charging a mid-month
    # deficit in full to every remaining week instead of amortizing it.
    #
    # One proportional formula now covers every week position -- leading stub
    # (Aug 1 2026 is a Saturday -> a one-day "week", which would otherwise get a
    # full week's dollars and spike day one ~7x), full mid-month week, and
    # trailing partial week -- with no special-casing. A whole 7-day week inside
    # the month has this_week_share == 1, leaving the common case untouched.
    last_day = calendar.monthrange(as_of.year, as_of.month)[1]
    month_end = date(as_of.year, as_of.month, last_day)
    week_end_capped = min(week_end, month_end)
    this_week_days = (week_end_capped - effective_week_start).days + 1
    this_week_share = Decimal(this_week_days) / Decimal(7)
    this_week_target = remaining_pool * (this_week_share / weeks_left)

    spend_this_week = discretionary_spend_in_range(db, user_id, effective_week_start, as_of)
    spendable_this_week = (this_week_target - spend_this_week).quantize(Decimal("0.01"))

    # remaining_pool is depleted by prior weeks only (see the docstring), so
    # this week's own spend comes off once more to get true month-to-date
    # remaining. spendable_this_week <= remaining_this_month falls out of
    # this_week_share / weeks_left <= 1.
    remaining_this_month = (remaining_pool - spend_this_week).quantize(Decimal("0.01"))

    # Capped at month end for the same reason this_week_days is: spendable_this_week
    # only covers the week's days that fall INSIDE this month, so the daily pace must
    # divide by that same count. Dividing the trailing week's 2 real days of budget
    # across a raw 7-day week understated the daily figure by up to 3.5x -- exactly
    # backwards for a number whose whole job is answering "what can I spend today?".
    days_left_in_week = (week_end_capped - as_of).days + 1
    spendable_today = (spendable_this_week / Decimal(days_left_in_week)).quantize(Decimal("0.01"))

    return WeeklySpendable(
        spendable_this_week=spendable_this_week,
        spendable_today=spendable_today,
        days_left_in_week=days_left_in_week,
        on_pace=spendable_this_week >= 0,
        remaining_this_month=remaining_this_month,
    )
