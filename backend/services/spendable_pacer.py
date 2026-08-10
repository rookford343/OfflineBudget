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
from sqlalchemy import or_
from sqlalchemy.orm import Session
from backend import models
from backend.services.card_matching import card_matches_description
from backend.services.spending_helpers import NOT_SAVINGS


# Categories whose BUDGETED amount budget_snapshot.py already removes from the
# monthly pool up front, via _budget_allocation_total(..., "Savings"/"Groceries").
# Subtracting their ACTUAL spend here too would deduct the same money twice --
# once as a budget line, again as a transaction. Matched by exact, case-sensitive
# name because that is precisely what budget_snapshot.py hardcodes. The
# CategoryType.savings check in NOT_SAVINGS does NOT cover these: real users
# routinely type their "Savings"/"Groceries" categories as `expense`.
_EXCLUDED_CATEGORY_NAMES = ("Groceries", "Savings")

_TRANSFER_DESCRIPTION_MARKERS = ("online transfer", "transfer to", "transfer from")


def _looks_like_internal_transfer(description: str) -> bool:
    """True when a bank description looks like money moved between the user's
    own accounts (checking -> savings, checking -> checking) rather than spent.

    HEURISTIC, not a fact: `Transaction` has no persisted `is_transfer` column
    (it exists only transiently on CSV-import row schemas and is discarded once
    categorization decisions are made), so the description text is the only
    signal available at this layer. False positives (a merchant literally named
    "Transfer To ...") and false negatives (a bank wording we don't list) are
    both possible. That is the same accuracy tolerance the codebase already
    accepts from `card_matching.card_matches_description`, which is used for
    exactly this class of "is this row really spending?" question.
    """
    desc = (description or "").lower()
    return any(marker in desc for marker in _TRANSFER_DESCRIPTION_MARKERS)


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
    """Sum of card-linked recurring items (RecurringItem.card_id set --
    subscriptions billed to a card, already counted in the monthly leftover
    pool via budget_snapshot.py's _cc_budget_total) that fire on any day in
    [start, end]. Mirrors _charged_so_far's day-of-month firing logic but
    over an arbitrary range instead of "month start through as_of", so it
    still works when a calendar week straddles a month boundary. Like
    _charged_so_far, this fires on the calendar day regardless of whether a
    matching real CreditCardTransaction has posted yet -- same accepted
    tradeoff already established there, not a new gap.
    """
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
        models.RecurringItem.card_id.isnot(None),
    ).all()
    total = Decimal("0")
    day = start
    while day <= end:
        last_day_of_month = calendar.monthrange(day.year, day.month)[1]
        for item in items:
            if item.start_date > day or (item.end_date and item.end_date < day):
                continue
            if item.frequency == models.RecurringFrequency.monthly:
                fires = True
            elif item.frequency == models.RecurringFrequency.yearly:
                fires = item.month_of_year == day.month
            else:
                fires = False
            if not fires:
                continue
            due_day = item.day_of_month if item.day_of_month > 0 else last_day_of_month
            if min(due_day, last_day_of_month) == day.day:
                total += item.amount
        day += timedelta(days=1)
    return total


def discretionary_spend_checking(db: Session, user_id: int, start: date, end: date) -> Decimal:
    verified_txn_ids = {
        row[0] for row in db.query(models.PlannedTransfer.verified_transaction_id)
        .filter(
            models.PlannedTransfer.user_id == user_id,
            models.PlannedTransfer.verified_transaction_id.isnot(None),
        ).all()
    }
    rows = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount < 0,
            models.Transaction.recurring_item_id.is_(None),
            NOT_SAVINGS,
            or_(
                models.Transaction.category_id.is_(None),
                models.Category.name.notin_(_EXCLUDED_CATEGORY_NAMES),
            ),
        )
        .all()
    )

    # The remaining two exclusions can't be expressed as SQL predicates -- both
    # need the description matched against Python-side data (the user's card
    # list / a marker tuple), so filter the fetched rows instead.
    #
    # Credit-card autopay debits ("CHASE CREDIT CRD AUTOPAY") and internal
    # transfers ("Online Transfer to CHK ...0054") land in checking as plain
    # uncategorized negatives with no recurring_item_id, so neither existing
    # exclusion catches them -- yet neither is discretionary spend. A card
    # payment is settling charges this pacer ALREADY counted on the card side
    # (discretionary_spend_card), so counting the payment too double-counts the
    # same dollars; a transfer never leaves the household at all.
    active_cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
    ).all()

    def is_spend(t: models.Transaction) -> bool:
        if t.id in verified_txn_ids:
            return False
        if any(card_matches_description(card, t.description) for card in active_cards):
            return False
        if _looks_like_internal_transfer(t.description):
            return False
        return True

    return sum((abs(t.amount) for t in rows if is_spend(t)), Decimal("0"))


def discretionary_spend_card(db: Session, user_id: int, start: date, end: date) -> Decimal:
    rows = (
        db.query(models.CreditCardTransaction)
        .outerjoin(models.Category, models.CreditCardTransaction.category_id == models.Category.id)
        .filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.date >= start,
            models.CreditCardTransaction.date <= end,
            models.CreditCardTransaction.amount > 0,
            or_(
                models.CreditCardTransaction.category_id.is_(None),
                models.Category.type != models.CategoryType.savings,
            ),
            or_(
                models.CreditCardTransaction.category_id.is_(None),
                models.Category.name.notin_(_EXCLUDED_CATEGORY_NAMES),
            ),
        )
        .all()
    )
    total = sum((t.amount for t in rows), Decimal("0"))
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
    # the MORE negative branch, inflating the deficit (-$24,645.69 shown against
    # a true -$21,245.04 on real July 2026 data) and charging a mid-month
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

    days_left_in_week = (week_end - as_of).days + 1
    spendable_today = (spendable_this_week / Decimal(days_left_in_week)).quantize(Decimal("0.01"))

    return WeeklySpendable(
        spendable_this_week=spendable_this_week,
        spendable_today=spendable_today,
        days_left_in_week=days_left_in_week,
        on_pace=spendable_this_week >= 0,
    )
