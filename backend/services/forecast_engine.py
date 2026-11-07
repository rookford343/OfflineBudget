"""
Core day-by-day balance projection engine.

For each day in the requested range:
1. Find all recurring items whose day_of_month fires that day.
2. Check for actual transactions that day (is_actual=True); they override the
   recurring projection for a matched recurring_item_id.
3. Walk the running balance forward from account.current_balance.
"""
from __future__ import annotations
from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from backend import models
from backend.schemas import ForecastEntry, ForecastTransaction, QuarterSummary
from backend.services.tax_service import ss_wage_base_for
from backend.services.card_matching import card_matches_description
from backend.services.cushion import cushion_status

# How many days before "today" a scheduled recurring item can still be
# missing its actual and get folded into today's opening balance anyway,
# rather than silently vanishing from the forecast until bank sync catches
# up. Bank aggregators lag real-world posting by days -- observed live
# 2026-09-01: a $5,000.00 paycheck scheduled Aug 31 sat unconfirmed for a
# full day past "today" with the forecast never accounting for it, because
# the day-walk below never visits a date before start_date. Matches the
# frontend Pending list's own lookback window (Transactions.tsx,
# PENDING_LOOKBACK_DAYS) for the same reason: a card issuer's balance feed
# lagged up to ~6 days earlier this same session.
_UNCONFIRMED_LOOKBACK_DAYS = 7
# The walk horizon: every walk projects from today - WALK_LOOKBACK_DAYS,
# whatever its start (see "Walk horizon" in build_forecast). A recurring item
# due inside it and still unmatched counts as not yet posted; an older one no
# longer reaches today's balance. forecast_walk.standard_walk starts here.
WALK_LOOKBACK_DAYS = 45
# How far either side of a card payoff's date a posted payment still settles
# it (_cc_actual_nearby's window).
_CC_NEARBY_DAYS = 7

# The note bank sync stamps on the daily checkpoint it writes (the posted
# balance). Any other note means the user typed the anchor in.
AUTO_ANCHOR_NOTE = "Auto (bank sync)"


def _last_day_of_month(d: date) -> int:
    return monthrange(d.year, d.month)[1]


def _next_occurrence_on_or_after(day_of_month: int, after: date) -> date:
    """The first date on/after `after` whose day-of-month is `day_of_month`
    (0 = last day of month, matching RecurringItem's day_of_month convention).
    Rolls to next month if this month's occurrence has already passed."""
    last_day = _last_day_of_month(after)
    day = min(day_of_month, last_day) if day_of_month > 0 else last_day
    candidate = date(after.year, after.month, day)
    if candidate >= after:
        return candidate
    year, month = (after.year, after.month + 1) if after.month < 12 else (after.year + 1, 1)
    last_day2 = monthrange(year, month)[1]
    day2 = min(day_of_month, last_day2) if day_of_month > 0 else last_day2
    return date(year, month, day2)


def _most_recent_occurrence_on_or_before(day_of_month: int, before: date) -> date:
    """The last date on/before `before` whose day-of-month is `day_of_month`.
    Mirrors _next_occurrence_on_or_after's short-month clamping, searching
    backward instead of forward."""
    last_day = _last_day_of_month(before)
    day = min(day_of_month, last_day) if day_of_month > 0 else last_day
    candidate = date(before.year, before.month, day)
    if candidate <= before:
        return candidate
    year, month = (before.year, before.month - 1) if before.month > 1 else (before.year - 1, 12)
    last_day2 = monthrange(year, month)[1]
    day2 = min(day_of_month, last_day2) if day_of_month > 0 else last_day2
    return date(year, month, day2)


def _card_payoff_date_for_charge(card: "models.CreditCard", charge_date: date) -> date:
    """When a charge made on `charge_date` actually leaves checking: the due
    date of the FIRST statement that closes on or after the charge -- not
    just the next calendar due_day.

    A statement closes ~3-4 weeks before its own due date (the user's Chase:
    closes the 28th, due the 25th of the FOLLOWING month), so a charge
    posting even one day before a nearby due_day has almost always already
    missed that statement's close and won't be paid off until the NEXT
    cycle. Found live 2026-08-13: a charge the user makes 8/24 was routed to the
    8/25 due date -- one day later -- when in reality that statement closed
    back on 7/28, so the charge can't be paid off until 9/25.

    Two steps: find the close date (first statement_day on/after the
    charge), then the first due_day strictly after that close -- "strictly"
    matters because a due_day numerically less than statement_day (the
    common case) would otherwise match an already-passed same-month date."""
    close_date = _next_occurrence_on_or_after(card.statement_day, charge_date)
    return _next_occurrence_on_or_after(card.due_day, close_date + timedelta(days=1))


def _card_subscription_charges(
    items: list["models.RecurringItem"], start_date: date, end_date: date,
    skip: Callable[["models.RecurringItem", date], bool] | None = None,
) -> dict[date, Decimal]:
    """Total charged to a card on each day by its own recurring subscriptions.

    Scanned from well before `start_date` because a charge is paid off a
    statement cycle later: a subscription billed in June is what leaves
    checking in late July, so the window has to reach back far enough to catch
    the charges whose payoff lands inside the forecast. Two months plus a few
    days covers the user's Chase cycle (closes the 28th, due the 25th of the
    following month) with room to spare.

    Reuses _fires_on so quarterly, yearly, weekly and biweekly subscriptions
    all land on the same dates the checking walk would put them on.

    `skip(item, day)` drops one charge (the Safety Margin walk uses it for
    this month's card bills it subtracts on its own).
    """
    charges: dict[date, Decimal] = {}
    current = start_date - timedelta(days=70)
    while current <= end_date:
        for item in items:
            if _fires_on(item, current) and not (skip and skip(item, current)):
                charges[current] = charges.get(current, Decimal("0")) + item.amount
        current += timedelta(days=1)
    return charges


def _adjust_for_weekend(d: date) -> date:
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d - timedelta(days=2)
    return d


def _compute_transfer_schedule(
    db: Session,
    user_id: int,
    rule: models.BufferTransferRule,
    start_date: date,
    end_date: date,
    overrides: list[dict] | None = None,
    proposal: ScenarioProposal | None = None,
) -> dict[date, Decimal]:
    """Dry-run `rule.to_account_id` with no transfers applied, then decide on
    each check_day whether a buffer transfer is needed to keep it above
    `rule.action_threshold` before the next check_day. Each month's decision
    credits transfers already scheduled in earlier months, so a transfer
    from July isn't re-counted as still needed in August.

    Anchored at January 1st of start_date's year (not start_date itself) so
    the schedule is independent of which window the caller requested --
    otherwise a query starting mid-month (e.g. /forecast/risk starting at
    date.today()) would skip that month's check_day entirely, while a
    full-year query (e.g. /forecast/quarters) would catch it, producing
    contradictory numbers for the same account on the same day.

    Top-ups only; see _compute_transfer_schedules for the sweep as well.
    """
    topups, _ = _compute_transfer_schedules(
        db, user_id, rule, start_date, end_date,
        overrides=overrides, proposal=proposal, include_sweep=False,
    )
    return topups


def _check_day_in(rule: models.BufferTransferRule, year: int, month: int) -> date:
    return date(year, month, min(rule.check_day, _last_day_of_month(date(year, month, 1))))


def _sweep_active(db: Session, user_id: int, rule: models.BufferTransferRule) -> bool:
    """The sweep runs only while the user saves each month, and only once a
    ceiling and destination are set. A ceiling at or below target_floor
    would sweep money the top-up just brought in, so it's treated as off
    (the API refuses one; this guards rows written any other way)."""
    if rule.sweep_ceiling is None or rule.sweep_to_account_id is None:
        return False
    if rule.sweep_ceiling <= rule.target_floor:
        return False
    user = db.query(models.User).filter(models.User.id == user_id).first()
    return user is not None and user.savings_strategy == "save_monthly"


def _compute_transfer_schedules(
    db: Session,
    user_id: int,
    rule: models.BufferTransferRule,
    start_date: date,
    end_date: date,
    overrides: list[dict] | None = None,
    proposal: ScenarioProposal | None = None,
    include_sweep: bool = True,
) -> tuple[dict[date, Decimal], dict[date, Decimal]]:
    """(top-ups into to_account, sweeps out of it), both keyed by check_day.

    Top-ups are exactly _compute_transfer_schedule's original rule. After
    each check_day's top-up decision, when the sweep is active
    (_sweep_active), whole `increment`s of `lowest - sweep_ceiling` move to
    sweep_to_account -- `lowest` being the lowest balance from this check_day
    up to the next one, adjusted for every earlier top-up AND sweep. Sizing
    off the window's LOWEST point is what guarantees the sweep never pushes
    checking under the ceiling before the next check_day.

    The sweep's last window always runs to the day before the NEXT check_day,
    even past end_date: sized on a truncated window, a caller whose range
    ends before the month's low point (e.g. a short risk query) would see a
    bigger sweep on the same day than a full-year caller does. Top-ups keep
    their original end_date clipping so their behaviour is unchanged.
    """
    anchor = date(start_date.year, 1, 1)
    sweeping = include_sweep and _sweep_active(db, user_id, rule)

    # First check_day strictly after end_date: later this month, or next month's.
    next_cd = _check_day_in(rule, end_date.year, end_date.month)
    if next_cd <= end_date:
        following = end_date.replace(day=1) + timedelta(days=32)
        next_cd = _check_day_in(rule, following.year, following.month)
    sweep_horizon = next_cd - timedelta(days=1)
    raw_end = sweep_horizon if sweeping else end_date

    raw_entries = build_forecast(
        db, user_id, rule.to_account_id, anchor, raw_end,
        overrides=overrides,
        apply_buffer_transfers=False,
        proposal=proposal,
    )
    if not raw_entries:
        return {}, {}

    check_days: list[date] = []
    cur = anchor
    while cur <= end_date:
        cd = _check_day_in(rule, cur.year, cur.month)
        if anchor <= cd <= end_date:
            check_days.append(cd)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)

    topups: dict[date, Decimal] = {}
    sweeps: dict[date, Decimal] = {}
    adjusted_so_far = Decimal("0")  # + every earlier top-up, - every earlier sweep
    for i, cd in enumerate(check_days):
        is_last = i + 1 >= len(check_days)
        window_end = end_date if is_last else check_days[i + 1] - timedelta(days=1)
        window = [e for e in raw_entries if cd <= e.date <= window_end]
        if not window:
            continue
        lowest_adjusted = min(e.projected_balance for e in window) + adjusted_so_far
        if lowest_adjusted < rule.action_threshold:
            shortfall = rule.target_floor - lowest_adjusted
            steps = int((shortfall / rule.increment).to_integral_value(rounding=ROUND_CEILING))
            amount = rule.increment * steps
            topups[cd] = amount
            adjusted_so_far += amount

        if not sweeping:
            continue
        sweep_end = sweep_horizon if is_last else window_end
        sweep_window = [e for e in raw_entries if cd <= e.date <= sweep_end]
        lowest_now = min(e.projected_balance for e in sweep_window) + adjusted_so_far
        excess = lowest_now - rule.sweep_ceiling
        if excess >= rule.increment:
            amount = rule.increment * int((excess / rule.increment).to_integral_value(rounding=ROUND_FLOOR))
            sweeps[cd] = amount
            adjusted_so_far -= amount

    return topups, sweeps


def _cc_actual_nearby(
    card: models.CreditCard,
    target: date,
    actuals_by_date: dict[date, list[models.Transaction]],
    window: int = _CC_NEARBY_DAYS,
) -> bool:
    """True if an actual transaction matching this card appears within window days of target.

    Matching uses card_matching.card_matches_description (first-token-of-name
    heuristic, since bank descriptions rarely include the full product name but
    always include the issuer, plus a last_four fallback).
    """
    for offset in range(-window, window + 1):
        check = target + timedelta(days=offset)
        for txn in actuals_by_date.get(check, []):
            if card_matches_description(card, txn.description):
                return True
    return False


def _fires_on(item: models.RecurringItem, d: date) -> bool:
    """Return True if this recurring item fires on date d."""
    if item.start_date > d:
        return False
    if item.end_date and item.end_date < d:
        return False
    if not item.is_active:
        return False
    return _matches_schedule(item, d)


def _matches_schedule(item: models.RecurringItem, d: date) -> bool:
    """Does d fall on this item's schedule pattern? Ignores start_date/end_date
    as bounds (weekly/biweekly still use start_date as the cadence anchor,
    stepping backward as well as forward) and is_active; _fires_on adds those."""
    frequency = getattr(item, "frequency", None)
    if frequency == models.RecurringFrequency.weekly:
        return (d - item.start_date).days % 7 == 0
    if frequency == models.RecurringFrequency.biweekly:
        return (d - item.start_date).days % 14 == 0
    # Yearly items only fire in their designated month
    if frequency == models.RecurringFrequency.yearly:
        month_of_year = getattr(item, "month_of_year", None)
        if month_of_year and d.month != month_of_year:
            return False
    # Quarterly items fire in month_of_year and every third month after it, so
    # month_of_year names the FIRST month of the cycle rather than the only one
    # (3 -> Mar/Jun/Sep/Dec). the user's Stormwater bill is the case this exists
    # for: Budget!C15 marks it "Qtr" and the sheet charges $15.00 on 9/30 and
    # 12/31 while carrying $5.00 as the monthly accrual in Budget!B15. Modeling
    # it as monthly instead put a twelfth of the bill on checking every month --
    # right over a quarter, wrong on any given day.
    if frequency == models.RecurringFrequency.quarterly:
        month_of_year = getattr(item, "month_of_year", None)
        if month_of_year and (d.month - month_of_year) % 3 != 0:
            return False
    if item.day_of_month == 0:
        return d.day == _last_day_of_month(d)
    target = min(item.day_of_month, _last_day_of_month(d))
    return d.day == target


def paycheck_item_ids(
    recurring_items, gross_per_paycheck: Decimal | None, bonus_item_ids: set[int],
) -> set[int]:
    """Ids of the recurring income items that are paychecks: net amount
    between 0.5x and 1.1x of the gross per paycheck (a recurring item holds
    the NET that lands in checking; see build_forecast's SS boost setup for
    why the band is shaped this way). Bonus-plan items are never paychecks.
    Empty when gross_per_paycheck is unset."""
    if not gross_per_paycheck or gross_per_paycheck <= 0:
        return set()
    ids: set[int] = set()
    for item in recurring_items:
        if item.id in bonus_item_ids:
            continue  # a bonus is never a paycheck, whatever its net/gross ratio
        if item.type == models.RecurringType.income and item.amount > 0:
            ratio = item.amount / gross_per_paycheck
            if Decimal("0.5") <= ratio <= Decimal("1.1"):
                ids.add(item.id)
    return ids


def paycheck_dates(items, start: date, end: date) -> list[date]:
    """Sorted distinct dates in [start, end] on which any of `items` fires
    (per _fires_on). Distinct, so a paycheck split across two deposit items
    counts once per pay date."""
    dates: list[date] = []
    d = start
    while d <= end:
        if any(_fires_on(item, d) for item in items):
            dates.append(d)
        d += timedelta(days=1)
    return dates


def pay_year_dates(items, year: int, *, today: date | None = None) -> list[date]:
    """Sorted distinct paydays in `year` from the items' schedule patterns.
    For tax counting only. Bounds:
    - end_date is honored: an item that ended before the year is skipped,
      and each item stops at its end_date.
    - An item starting after the year (a future schedule) is skipped.
    - start_date is otherwise NOT a lower bound: it is usually just when the
      item was entered (the Recurring form defaults it to today), so bounding
      by it under-counts the year it was created in. The exception is a
      replacement schedule: when another item ended this year before this
      one's start_date, that start_date is the real switchover and is honored.
    - Fallback: when NO item applies to the year (e.g. a year before every
      paycheck item was entered), the year is counted in full on today's
      schedule -- the items in effect `today` (started, not ended), with no
      start/end bound -- so pre-tax deductions and withholding don't vanish
      for a past year. All in-effect items are used, not just the newest:
      a split deposit or a semi-monthly pair can have different start_dates.
      Nothing in effect today (only future or ended items) gives [].
    Weekly/biweekly cadences are stepped from start_date in both directions;
    day-of-month items fire every month. Distinct, so a paycheck split across
    deposit items counts once. `today` defaults to date.today()."""
    jan1, dec31 = date(year, 1, 1), date(year, 12, 31)
    live = [i for i in items
            if i.start_date <= dec31 and not (i.end_date and i.end_date < jan1)]
    windows = []
    for item in live:
        replaces_ended = any(
            other is not item and other.end_date and other.end_date < item.start_date
            for other in live  # live end_dates are all on/after jan1
        )
        lo = item.start_date if replaces_ended and item.start_date > jan1 else jan1
        hi = min(item.end_date, dec31) if item.end_date else dec31
        windows.append((item, lo, hi))
    if not live:
        today = today or date.today()
        windows = [(i, jan1, dec31) for i in items
                   if i.start_date <= today and not (i.end_date and i.end_date < today)]
    dates: list[date] = []
    d = jan1
    while d <= dec31:
        if any(lo <= d <= hi and _matches_schedule(item, d) for item, lo, hi in windows):
            dates.append(d)
        d += timedelta(days=1)
    return dates


def is_card_bill_in_month(item: models.RecurringItem, month: date) -> bool:
    """Is this card-linked item on `month`'s 'Credit Card Bills' list -- the
    set behind budget_snapshot's cc_budget_total? Monthly, weekly and
    biweekly items always (budget_snapshot counts each weekly/biweekly
    occurrence since 2026-11, so the Safety Margin walk must leave those out
    of the payoff too), yearly items in their own month, quarterly items
    every third month from month_of_year."""
    if item.frequency in (
        models.RecurringFrequency.monthly,
        models.RecurringFrequency.weekly,
        models.RecurringFrequency.biweekly,
    ):
        return True
    if item.frequency == models.RecurringFrequency.yearly:
        return item.month_of_year == month.month
    if item.frequency == models.RecurringFrequency.quarterly:
        return item.month_of_year is not None and (month.month - item.month_of_year) % 3 == 0
    return False


def has_unsettled_projection(db: Session, user_id: int, account_id: int, target: date) -> bool:
    """True if the forecast still projects anything unposted on `target`.

    Exists for bank_sync_service.py's daily balance-checkpoint anchor.
    build_forecast applies a day's checkpoint AFTER that day's own
    transactions, unconditionally overwriting the running balance with it
    (the checkpoint is meant to BE the settled end-of-day figure) -- so a
    checkpoint dated on a day that still has something projected silently
    erases that projection's effect from every day after it.

    Two real incidents, two days apart, both from this:
      - 2026-09-16: a sync ran before that day's Paycheck posted; the
        checkpoint erased +$5,300 net from the rest of the 3-month forecast.
      - 2026-09-17: a first fix guarded only RecurringItem, so a day holding
        a PlannedExpense's +$20,000 funding transfer got checkpointed anyway
        -- erasing the funding leg while leaving the matching -$20,000
        outflow two days later, dropping the whole forward forecast by
        $20,000.

    Hence this asks build_forecast itself rather than re-deriving "what
    lands on this day" from the models: a one-day window returns every
    projection the engine would apply, so a new projection type can never
    quietly fall outside this guard the way PlannedExpense did.
    """
    # Overdue card payoffs re-planned on today land AFTER today's anchor
    # (see overdue_payoffs in build_forecast), so the anchor can't erase
    # them and they must not stop a re-sync from refreshing it.
    entries = build_forecast(db, user_id, account_id, target, target,
                             replan_overdue_card_payoffs=False)
    if not entries:
        return False
    return any(not t.is_actual for t in entries[0].transactions)


SS_EMPLOYEE_RATE = Decimal("0.062")


def effective_bonus_plans(db: Session, user_id: int, user: models.User | None) -> dict:
    """{recurring_item_id: BonusPlan} for plans whose item is still
    bonus-shaped. A BonusPlan can only be attached to a yearly income item at
    creation time (routers/bonus_plans.py's _own_item), but nothing stops the
    user from editing that same item into a different type or frequency
    afterward on the Recurring page. Filtered once, via the same
    is_bonus_shaped() guard refresh_item_amounts uses, so every use of the
    plans -- the day-walk's own amount lookup, the paycheck-tag skip, and the
    checkpoint-mode SS bonus reconciliation -- agrees with what the item
    actually is right now, instead of applying the plan's net to an item that
    no longer qualifies (e.g. firing it every month instead of once a year)."""
    from backend.services.bonus_plans import is_bonus_shaped, plans_by_item
    return {
        item_id: plan
        for item_id, plan in (plans_by_item(db, user_id) if user else {}).items()
        if is_bonus_shaped(plan.recurring_item)
    }


class SSWageBaseTracker:
    """Social Security wage-base state for one walk through paychecks: how
    much gross is left under the base, whether it has been met, and the boost
    each paycheck gets once it has. build_forecast and ss_paycheck_boosts
    (the Recurring summary and the Household Snapshot's income) both drive
    this one object, so the boost can't disagree between them.

    Once cumulative gross wages pass the base, the 6.2% withholding stops and
    every later paycheck deposits more, until January 1 starts the next
    year's base. The crossing paycheck gets only the part above the base.
    """

    def __init__(
        self, user: models.User, recurring_items, bonus_item_ids: set[int], walk_start: date,
        *, use_checkpoint: bool = True,
    ):
        self.user = user
        self.gross: Decimal = user.ss_gross_per_paycheck
        self.checkpoint_date: date | None = None
        self.limit_reached = False
        if use_checkpoint and user.ss_withheld_ytd is not None and user.ss_withheld_ytd_as_of is not None:
            # Preferred: a direct checkpoint off a real pay stub's YTD SS
            # withholding line, rather than reconstructing YTD gross wages by
            # counting actual paychecks against a flat per-paycheck figure.
            # ss_withheld_ytd / 0.062 recovers gross wages actually subject to
            # SS as of that stub -- correct through every raise in the year
            # with no reconstruction, unlike ss_bonus_ytd below. the user's April
            # raise alone misdated the 2026 crossing by a full paycheck under
            # the old method (found 2026-08-14, YTD withheld $8,500.00 as of
            # the 8/14 check implies gross $138,000.00, still $1,000.00 under
            # the $184,500 base -- crossing is 8/31, not 8/14).
            gross_ytd_at_checkpoint = (user.ss_withheld_ytd / SS_EMPLOYEE_RATE).quantize(Decimal("0.01"))
            self.remaining: Decimal = user.ss_wage_base - gross_ytd_at_checkpoint
            self.checkpoint_date = user.ss_withheld_ytd_as_of
        else:
            self.remaining = user.ss_wage_base - (user.ss_bonus_ytd or Decimal("0"))
        # Quantized like the monthly interest credit -- it is a dollar amount
        # landing in an account, and unrounded it produced paychecks of
        # $5,000.00112.
        self.boost_per_check = (self.gross * SS_EMPLOYEE_RATE).quantize(Decimal("0.01"))
        # Which recurring income items are paychecks (and so stop having Social
        # Security withheld once the wage base is hit)? Compared against
        # ss_gross_per_paycheck, but note the units differ: a recurring income
        # item holds the NET amount that lands in checking, while
        # ss_gross_per_paycheck is gross. Net runs roughly 55-85% of gross after
        # tax, retirement, and benefits, so the old two-sided 0.9..1.1 band
        # could never match a real paycheck -- the user's is 5000.00/7000.00 = 0.714,
        # which meant the boost silently never fired for anyone and left Q4 2026
        # about $2,460 (6 paychecks x $410) low against his spreadsheet.
        # Confirmed live 2026-08-12.
        #
        # The lower bound stays well above incidental recurring income (a
        # smoothed bonus twelfth, a rental payment) without needing to know the
        # exact withholding rate; the upper bound keeps net from exceeding gross
        # by more than rounding.
        self.paycheck_ids: set[int] = paycheck_item_ids(recurring_items, self.gross, bonus_item_ids)
        # The wage base is per calendar year. The figures above describe the
        # year of the checkpoint (or of the walk's start without one); every
        # later January 1 starts over -- see roll_year.
        self.year = self.checkpoint_date.year if self.checkpoint_date is not None else walk_start.year

    @classmethod
    def for_user(
        cls, user, recurring_items, bonus_item_ids: set[int], walk_start: date,
        *, use_checkpoint: bool = True,
    ) -> "SSWageBaseTracker | None":
        """None when the user hasn't set a gross per paycheck and a wage base.
        `use_checkpoint=False` ignores the pay stub and counts the walk's year
        from January 1 (received paychecks plus ss_bonus_ytd) -- for a year
        the stub doesn't describe."""
        if not (
            user
            and user.ss_gross_per_paycheck and user.ss_gross_per_paycheck > 0
            and user.ss_wage_base and user.ss_wage_base > 0
        ):
            return None
        return cls(user, recurring_items, bonus_item_ids, walk_start, use_checkpoint=use_checkpoint)

    def catch_up(self, db: Session, user_id: int, bonus_plans: dict, before: date) -> None:
        """Draw the base down for wages already RECEIVED before `before`.

        Past days are served from actuals, which skip the projection branch
        where the drawdown lives, so without this the base only ever saw
        future paychecks and the boost landed far too late -- or never.

        Counted from January 1 of the walk's year rather than from its start,
        because the wage base is a calendar-year quantity. Scoping it to the
        window instead made the answer depend on the window: /forecast/risk
        asks for today..+90 and would see zero prior paychecks, so it never
        applied the boost and ran ~$410 short per paycheck against the
        Jan-anchored /forecast/quarters the chart draws. That put a false
        at-risk alert (-$200.00 on 2026-08-25) under a chart whose trough was
        +$1,000.00 on the very same day. Found live 2026-08-12.

        Counted, not summed: SS is withheld on gross, while the stored actual
        is the net deposit.

        With a checkpoint, this only needs to bridge the gap between the pay
        stub's date and `before` -- `remaining` already reflects everything
        through the checkpoint itself, so counting from Jan 1 would
        double-count every paycheck already folded into ss_withheld_ytd.
        """
        if self.paycheck_ids:
            catchup_filter = (
                models.Transaction.date > self.checkpoint_date
                if self.checkpoint_date is not None
                # No checkpoint: legacy behaviour, unchanged -- counts from Jan 1
                # inclusive, matching how ss_bonus_ytd has always been reconciled.
                else models.Transaction.date >= date(self.year, 1, 1)
            )
            received = (
                db.query(models.Transaction)
                .filter(
                    models.Transaction.user_id == user_id,
                    models.Transaction.is_actual == True,
                    models.Transaction.recurring_item_id.in_(self.paycheck_ids),
                    catchup_filter,
                    models.Transaction.date < before,
                )
                .count()
            )
            if received:
                self.remaining -= self.gross * received
                if self.remaining <= 0:
                    self.limit_reached = True

        # Bonuses received after the pay-stub checkpoint also used up wage base.
        # Only in checkpoint mode: the legacy ss_bonus_ytd figure already holds
        # the user's bonus, so counting deposits there would double it.
        if self.checkpoint_date is not None and bonus_plans:
            from backend.services.bonus_plans import bonus_gross
            for t in db.query(models.Transaction).filter(
                models.Transaction.user_id == user_id,
                models.Transaction.is_actual == True,
                models.Transaction.recurring_item_id.in_(list(bonus_plans)),
                models.Transaction.date > self.checkpoint_date,
                models.Transaction.date < before,
            ):
                gross = bonus_gross(bonus_plans[t.recurring_item_id], self.user, t.date.year)
                if gross is not None and t.date.year == self.checkpoint_date.year:
                    self.remaining -= gross
            if self.remaining <= 0:
                self.limit_reached = True

    def roll_year(self, current: date) -> None:
        """Every January 1 starts over at the full base, so withholding resumes
        until the new year's base is met. Without this, a boost reached in one
        year carried into every later year's paychecks. The checkpoint year
        uses the user's own setting; a later year uses the published base when
        tax_service bundles it (the base rises each year), else the user's
        setting again."""
        if current.year != self.year:
            self.year = current.year
            self.remaining = ss_wage_base_for(current.year) or self.user.ss_wage_base
            self.limit_reached = False

    def paycheck_boost(self, current: date) -> Decimal:
        """The boost for one paycheck landing on `current`, drawing the base
        down by its gross."""
        # The checkpoint date's own paycheck is already fully accounted for
        # inside `remaining` (the checkpoint is "as of and including" that
        # date) -- decrementing for it again here would subtract it twice.
        if current == self.checkpoint_date:
            return Decimal("0")
        if self.limit_reached:
            return self.boost_per_check
        # Draw down by GROSS, not item.amount -- the wage base is a
        # gross-wages figure, while item.amount is the net deposit.
        # Decrementing by net stretched the run-up ~40% too far
        # (the user: 118,260 remaining / 5,000.00 net = 19.5 paychecks,
        # landing in late Oct 2027 instead of autumn 2026), so the
        # boost never arrived inside the forecast window at all.
        self.remaining -= self.gross
        if self.remaining <= 0:
            self.limit_reached = True
            # The CROSSING paycheck only gets a partial boost: SS is still
            # withheld on the wages up to the base, and only the remainder
            # above it comes back. Granting the full $500.00 here overstated
            # that one check and, worse, pulled the whole step-up a paycheck
            # early -- caught 2026-08-14 reconciling to Budget.xlsx, where the
            # app boosted the 8/14 check while the sheet held flat until 9/15.
            # After the subtraction above, -remaining IS the gross above the
            # base, so it needs no separate bookkeeping. Every check after
            # this one gets the full boost via the limit_reached branch.
            excess = min(-self.remaining, self.gross)
            return (excess * SS_EMPLOYEE_RATE).quantize(Decimal("0.01"))
        return Decimal("0")

    def bonus_boost(self, current: date, bonus_gross_amt: Decimal) -> Decimal:
        """A bonus is wages too: its gross draws the base down, and SS
        withheld on whatever lies above the base comes back."""
        if current == self.checkpoint_date:
            return Decimal("0")
        if self.limit_reached:
            return (bonus_gross_amt * SS_EMPLOYEE_RATE).quantize(Decimal("0.01"))
        self.remaining -= bonus_gross_amt
        if self.remaining <= 0:
            self.limit_reached = True
            excess = min(-self.remaining, bonus_gross_amt)
            return (excess * SS_EMPLOYEE_RATE).quantize(Decimal("0.01"))
        return Decimal("0")


def ss_paycheck_boosts(
    db: Session, user: models.User, income_items, year: int, month: int,
    *, today: date | None = None,
) -> dict[tuple[int, date], Decimal]:
    """{(recurring_item_id, natural fire date): boost} for every paycheck
    occurrence in the month whose Social Security boost is above zero.

    Drives the same SSWageBaseTracker build_forecast does, the same way:
    wages already received (actuals) before a cutoff are caught up, then
    every paycheck and bonus occurrence from the cutoff on draws the base
    down in the forecast's order -- on its weekend-adjusted date (a Saturday
    paycheck counts on the Friday before, exactly as the forecast books it),
    rolling the base over on January 1. The cutoff is today, or the start of
    the month when the month is already under way, so the month's own
    earlier paychecks get their boost too (the forecast only books those as
    actuals). A future month's paychecks get exactly the forecast's
    paycheck-line boost.

    `income_items` is the caller's set of income items -- every account, not
    one checking account like build_forecast -- since the Recurring page and
    the Household Snapshot both total the user's whole month.
    """
    if user is None:
        return {}
    today = today or date.today()
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    cutoff = min(today, _adjust_for_weekend(month_start))
    bonus_plans = effective_bonus_plans(db, user.id, user)
    # A pay stub describes its own calendar year only. For a month in an
    # earlier year (December viewed after a January stub) it says nothing,
    # and walking from it rolled the year over to a fresh base with none of
    # that year's paychecks counted, wiping December's boosts. Such a month
    # is counted from January 1 of its own year instead.
    stub = user.ss_withheld_ytd_as_of if user.ss_withheld_ytd is not None else None
    ss = SSWageBaseTracker.for_user(
        user, income_items, set(bonus_plans), cutoff,
        use_checkpoint=not (stub is not None and stub.year > year),
    )
    if ss is None or not ss.paycheck_ids:
        return {}
    # A same-year pay stub dated on/after the cutoff that shows the base NOT
    # yet met already holds every paycheck up to and including its own date
    # in `remaining`, so the walk starts the day after it: those earlier
    # occurrences got no boost (the stub's YTD says the base wasn't met by
    # then -- or, at most, their boost is already in what landed). Walking
    # from the 1st instead drew the base down a second time for each of
    # them, crossing it a paycheck or more early; and a month wholly before
    # the stub (browsing Recurring backwards) walked the stub's remaining
    # base through checks the stub had already counted.
    #
    # A stub showing the base already MET keeps the old cutoff: the checks
    # before it really were boosted, and with `remaining` at or below zero
    # the walk gives each of them the full boost.
    if (
        ss.checkpoint_date is not None
        and ss.checkpoint_date >= cutoff
        and ss.checkpoint_date.year == year
        and ss.remaining > 0
    ):
        cutoff = ss.checkpoint_date + timedelta(days=1)
    ss.catch_up(db, user.id, bonus_plans, before=cutoff)

    from backend.services.bonus_plans import bonus_gross
    walked = [i for i in income_items if i.id in ss.paycheck_ids or i.id in bonus_plans]
    occurrences = []
    d = cutoff
    # +2 days: a paycheck due on the 1st/2nd of next month can land on this
    # month's last Friday, ahead of this month's own checks that day.
    while d <= month_end + timedelta(days=2):
        for order, item in enumerate(walked):
            if _fires_on(item, d):
                effective = _adjust_for_weekend(d)
                if cutoff <= effective <= month_end:
                    occurrences.append((effective, order, d, item))
        d += timedelta(days=1)
    occurrences.sort(key=lambda o: (o[0], o[1]))

    boosts: dict[tuple[int, date], Decimal] = {}
    for effective, _order, natural, item in occurrences:
        ss.roll_year(effective)
        if item.id not in ss.paycheck_ids:
            # A bonus draws the base down; only paychecks are reported.
            gross = bonus_gross(bonus_plans[item.id], user, natural.year)
            if gross is not None:
                ss.bonus_boost(effective, gross)
            continue
        boost = ss.paycheck_boost(effective)
        if boost > 0 and natural.year == year and natural.month == month:
            boosts[(item.id, natural)] = boost
    return boosts


@dataclass(frozen=True)
class ScenarioProposal:
    """Transient, never-persisted stand-ins for what a scenario proposes.

    `items` are real RecurringItem instances and `expenses` real
    PlannedExpense instances -- constructed but never db.add()ed -- so
    build_forecast can splice them into the lists it already walks and every
    scheduling rule (_fires_on, the weekend pull-forward, end dates,
    actual-vs-projected suppression) applies to a proposal because it IS the
    same object type in the same loop.

    Each item's id is the NEGATION of its proposal row's id. override_map and
    actual_by_ri are keyed by item id; a positive id could collide with a real
    item and silently apply that item's override, or its actuals, to a
    hypothetical.

    Frozen because build_forecast is a read path -- a proposal it could mutate
    would be a proposal that leaks between the baseline and scenario walks.
    """
    items: tuple["models.RecurringItem", ...] = ()
    expenses: tuple["models.PlannedExpense", ...] = ()


def build_forecast(
    db: Session,
    user_id: int,
    account_id: int,
    start_date: date,
    end_date: date,
    *,
    overrides: list[dict] | None = None,
    apply_buffer_transfers: bool = True,
    proposal: ScenarioProposal | None = None,
    include_unbilled_card_bills: bool = True,
    replan_overdue_card_payoffs: bool = True,
) -> list[ForecastEntry]:
    # Imported here: the model reads this module's date helpers, so a
    # top-level import would be circular.
    from backend.services.card_payment_model import (
        card_one_offs_by_payoff, card_payment_plan, pending_card_debits_by_card,
        window_planned_expenses,
    )
    account: models.Account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user_id,
    ).first()
    if not account:
        return []

    recurring_items = [
        item for item in db.query(models.RecurringItem).options(
            joinedload(models.RecurringItem.card)
        ).filter(
            models.RecurringItem.user_id == user_id,
            models.RecurringItem.account_id == account_id,
            models.RecurringItem.is_active == True,
            models.RecurringItem.include_in_forecast == True,
        ).all()
        # CC charges (expense + card_id) hit the card, not the checking account
        if not (item.type == models.RecurringType.expense and item.card_id is not None)
    ]

    # Proposals are spliced into the same lists the real queries produced. The
    # account filter and the card exclusion below mirror the comprehension
    # above exactly: a proposal must be subject to the same routing as the real
    # item it stands in for, or the scenario line diverges from what committing
    # it would actually produce.
    proposal_items = list(proposal.items) if proposal else []
    recurring_items.extend(
        item for item in proposal_items
        if item.account_id == account_id
        and not (item.type == models.RecurringType.expense and item.card_id is not None)
    )

    # SS paycheck boost setup
    user = db.query(models.User).filter(models.User.id == user_id).first()
    from backend.services.bonus_plans import bonus_gross, bonus_net
    bonus_plans = effective_bonus_plans(db, user_id, user)
    # Social Security wage-base state (see SSWageBaseTracker). None when the
    # user hasn't configured it.
    ss = SSWageBaseTracker.for_user(user, recurring_items, set(bonus_plans), start_date)

    # Known statement amounts for specific upcoming occurrences, keyed by
    # (recurring_item_id, natural due_date) so a lookup during the day walk is
    # exact. Two days past end_date: a Saturday or Sunday due date posts on
    # the Friday before it, which may be the window's last day.
    bill_actuals: dict[tuple[int, date], Decimal] = {
        (o.recurring_item_id, o.due_date): o.actual_amount
        for o in db.query(models.BillAmountOverride).filter(
            models.BillAmountOverride.user_id == user_id,
            models.BillAmountOverride.due_date >= start_date,
            models.BillAmountOverride.due_date <= end_date + timedelta(days=2),
        ).all()
    }

    all_active_cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
    ).all()
    active_cards_by_id = {c.id: c for c in all_active_cards}

    today = date.today()
    # Card payments the bank still lists as pending on this checking account,
    # grouped by the card they pay (see pending_card_debits_by_card).
    pending_card_debits = pending_card_debits_by_card(db, account, all_active_cards, today)

    # A scenario's proposed one-offs are spliced in before the routing loop
    # below, not after it: that loop is what derives funding legs and sends
    # card-linked expenses to the card's payoff date instead of their own.
    planned = window_planned_expenses(db, user_id, start_date, end_date, proposal)
    # Funding legs derived from the planned expenses above. A purchase funded
    # from savings implies a transfer INTO the spending account (and out of the
    # savings account), on a date computed from the purchase rather than stored
    # beside it -- so moving the purchase moves its funding automatically.
    funding_by_date: dict[date, list[tuple[models.PlannedExpense, Decimal]]] = {}

    planned_by_date: dict[date, list[models.PlannedExpense]] = {}
    # Card-linked planned expenses don't hit checking on expected_date -- a
    # charge doesn't touch checking until the card gets paid off. Routed
    # instead to the checking hit on the card's NEXT statement due date,
    # alongside the recurring CC payoff/estimate injections below.
    card_planned_by_date = card_one_offs_by_payoff(planned, account_id, active_cards_by_id)
    for pe in planned:
        # The funding leg is evaluated before the account filter below, because
        # it concerns a DIFFERENT account than the purchase: forecasting the
        # savings account must show the money leaving, and forecasting checking
        # must show it arriving. Skipping it with the purchase would make the
        # withdrawal invisible on the savings side.
        if pe.funding_account_id is not None and pe.direction == models.PlannedDirection.outflow:
            move = pe.funding_amount if pe.funding_amount is not None else pe.amount
            fund_date = pe.expected_date - timedelta(days=pe.funding_lead_days or 0)
            if start_date <= fund_date <= end_date:
                if account_id == pe.funding_account_id:
                    funding_by_date.setdefault(fund_date, []).append((pe, -move))
                elif pe.account_id is None or account_id == pe.account_id:
                    funding_by_date.setdefault(fund_date, []).append((pe, move))

        # Only include planned expenses for this account (or unlinked ones)
        if pe.account_id is not None and pe.account_id != account_id:
            continue
        if pe.card_id and active_cards_by_id.get(pe.card_id):
            continue  # routed to its card's payoff date: card_planned_by_date above
        planned_by_date.setdefault(pe.expected_date, []).append(pe)

    # Card payments (locked payoffs, cycle estimates, second hop, flat and
    # subscription estimates) come from the card-payment model, the same one
    # the Household Snapshot's explain notes read. Locked ones render as
    # "CC Payment", the rest as "CC Estimate".
    card_plan = card_payment_plan(
        db, user, account, start_date, end_date,
        include_unbilled_card_bills=include_unbilled_card_bills,
        proposal=proposal, today=today, planned=planned,
    )
    cc_payments: dict[date, list] = {}
    cc_estimates_by_date: dict[date, list] = {}
    for card_payment in card_plan.payments:
        (cc_payments if card_payment.locked else cc_estimates_by_date).setdefault(
            card_payment.due, [],
        ).append(card_payment)
    overdue_payoffs = card_plan.overdue

    # Build override map: recurring_item_id -> amount_delta
    override_map: dict[int, Decimal] = {}
    if overrides:
        for ov in overrides:
            override_map[ov["recurring_item_id"]] = Decimal(str(ov["amount_delta"]))

    # Load all actuals in the forecast window.
    # For dates in the past: current_balance already reflects them, so we reconstruct
    # the starting balance by reversing past actuals — then re-apply them in the walk.
    # This gives an accurate historical line rather than projecting backward from today's balance.
    all_actuals = db.query(models.Transaction).filter(
        models.Transaction.user_id == user_id,
        models.Transaction.account_id == account_id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start_date,
        models.Transaction.date <= end_date,
    ).all()

    actuals_by_date: dict[date, list[models.Transaction]] = {}
    for t in all_actuals:
        actuals_by_date.setdefault(t.date, []).append(t)

    # What _cc_actual_nearby checks a card payoff against: its own reach,
    # not the walk's window. The start=today bridge ends yesterday, so a
    # payment that posted today (or posts after the window) was invisible
    # to it: the payoff stayed in while current_balance already had the
    # payment out, counting it twice.
    nearby_actuals: dict[date, list[models.Transaction]] = {}
    for t in db.query(models.Transaction).filter(
        models.Transaction.user_id == user_id,
        models.Transaction.account_id == account_id,
        models.Transaction.is_actual == True,
        models.Transaction.date >= start_date - timedelta(days=_CC_NEARBY_DAYS),
        models.Transaction.date <= end_date + timedelta(days=_CC_NEARBY_DAYS),
    ).all():
        nearby_actuals.setdefault(t.date, []).append(t)

    # When start_date is in the past, reverse past actuals to find the opening balance.
    # current_balance = opening_balance + sum(all actuals from start_date to yesterday),
    # so opening_balance = current_balance - sum(past actuals).
    current_balance = Decimal(str(account.current_balance))

    # Card payments that have left checking but not posted yet: the bank's
    # pending card debits, and cards hand-marked payment-sent. Both are
    # subtracted on TODAY, after today's balance anchor -- not from the
    # opening seed, as the marker once was. Bank sync anchors today to the
    # POSTED balance, which by definition excludes them, and the walk applies
    # a day's anchor last, so a seed subtraction was silently erased by every
    # sync that anchored today (or any day between the seed and today). A
    # card with both counts once, at the larger figure: the marker and the
    # pending debit are the same payment.
    pending_today_lines: list[ForecastTransaction] = []
    if account.type == models.AccountType.checking:
        for card in all_active_cards:
            rows = pending_card_debits.get(card.id, [])
            for r in rows:
                pending_today_lines.append(ForecastTransaction(
                    name=f"Pending: {r.description}",
                    amount=Decimal(str(r.amount)),
                    type="expense",
                    category_name=None,
                    # Bank-reported, not a projection: has_unsettled_projection
                    # must not hold back today's anchor over it.
                    is_actual=True,
                    is_pending=True,
                    is_cc_payment=True,
                ))
            marker = (
                Decimal(str(card.payment_sent_amount or 0)) if card.payment_sent_pending_sync else Decimal("0")
            )
            pending_total = sum((-Decimal(str(r.amount)) for r in rows), Decimal("0"))
            if marker > pending_total:
                pending_today_lines.append(ForecastTransaction(
                    name=f"Payment sent: {card.name}",
                    amount=-(marker - pending_total),
                    type="expense",
                    category_name=None,
                    is_actual=True,
                    is_pending=True,
                    is_cc_payment=True,
                ))
    # Walk horizon. Every walk projects from `horizon` on, whatever its
    # start, so every start gives the same balance from the horizon on (and
    # so from today on). The standard walk (forecast_walk.standard_walk)
    # starts exactly here.
    #
    # - A walk starting AFTER the horizon (a calendar month, today, a future
    #   month) opens on a bridge walked from the horizon. That carries in the
    #   recurring items due since the horizon and still unmatched -- the
    #   user's rule, 2026-09-01: "keep forecasting as if transactions are
    #   happening as when they say they are happening", not waiting on sync
    #   -- and, for a future window, everything between now and its start.
    #   The bridge always starts at the horizon, so it takes the other branch
    #   and cannot recurse further. It keeps every flag, so a Safety Margin
    #   walk's bridge is a Safety Margin walk too.
    # - A walk starting AT or BEFORE the horizon (the Forecast tab's year
    #   views) seeds from the bank balance and walks its history as before,
    #   then re-seeds at the horizon to the balance a horizon walk opens
    #   with. Whatever that history drew -- a January paycheck that never
    #   matched an actual, an old checkpoint the ledger disagrees with --
    #   stays in the history and stops there.
    #
    # Until 2026-11 the bridges started at Jan 1 (future windows) or 7 days
    # back (start=today), and a past start projected from its own first day.
    # The same day then drew different balances by start: a January
    # paycheck that never matched an actual still sat in the Forecast tab's
    # today balance, and /risk (start=today) missed a bill unmatched for
    # three weeks that the Dashboard's lows counted.
    #
    # current_balance is the live bank balance and already reflects
    # anything dated today, so a walk that reaches today reverses today's
    # actuals as well as earlier ones -- the walk re-applies them below.
    # Reproduced live: $500.00 - $7,500.00 landed at -$7,000.00 when a
    # same-day actual was counted twice.
    horizon = today - timedelta(days=WALK_LOOKBACK_DAYS)
    walked_actuals_sum = sum(
        (Decimal(str(t.amount)) for t in all_actuals if t.date <= today), Decimal("0"),
    )
    horizon_seed: Decimal | None = None
    if start_date > horizon:
        bridge = build_forecast(
            db, user_id, account_id, horizon, start_date - timedelta(days=1),
            overrides=overrides, apply_buffer_transfers=apply_buffer_transfers,
            proposal=proposal,
            include_unbilled_card_bills=include_unbilled_card_bills,
            replan_overdue_card_payoffs=replan_overdue_card_payoffs,
        )
        opening = bridge[-1].projected_balance if bridge else current_balance
        balance = opening - walked_actuals_sum
    else:
        balance = current_balance - walked_actuals_sum
        if start_date < horizon <= end_date:
            horizon_seed = current_balance - sum(
                (Decimal(str(t.amount)) for t in all_actuals if horizon <= t.date <= today),
                Decimal("0"),
            )

    day_checkpoints = db.query(models.ForecastDayCheckpoint).filter(
        models.ForecastDayCheckpoint.user_id == user_id,
        models.ForecastDayCheckpoint.account_id == account_id,
        models.ForecastDayCheckpoint.date >= start_date,
        models.ForecastDayCheckpoint.date <= end_date,
    ).all()
    day_checkpoint_map: dict[date, Decimal] = {cp.date: cp.actual_balance for cp in day_checkpoints}
    # A hand-entered anchor today is the bank's own figure as the user read
    # it, which already has the pending payments out of it; only bank sync's
    # auto anchor is the posted balance that still needs them subtracted.
    todays_anchor_is_manual = any(
        cp.date == today and cp.note != AUTO_ANCHOR_NOTE for cp in day_checkpoints
    )
    # Bank sync's auto anchor today is the POSTED balance, so it erases an
    # unpaid payoff planned on an earlier due date in this walk although
    # nothing has paid it. Such a payoff moves to today, after the anchor,
    # the same way the pending lines do -- unless it already posted. A
    # hand-entered anchor is the bank's available balance as the user read
    # it, which already reflects the bank, so it gets nothing.
    replan_overdue_on_today = (
        replan_overdue_card_payoffs
        and today in day_checkpoint_map
        and not todays_anchor_is_manual
    )
    moved_overdue: dict[date, set[int]] = {}
    overdue_today_lines: list[ForecastTransaction] = []
    if replan_overdue_on_today:
        for overdue_payment in overdue_payoffs:
            card = active_cards_by_id[overdue_payment.card_id]
            due, amount = overdue_payment.due, overdue_payment.amount
            if _cc_actual_nearby(card, due, nearby_actuals):
                continue
            moved_overdue.setdefault(due, set()).add(card.id)
            overdue_today_lines.append(ForecastTransaction(
                name=f"CC Payment: {card.name}",
                amount=-amount,
                type="expense",
                category_name=None,
                is_actual=False,
                is_cc_payment=True,
                is_cc_locked=True,
                basis={"kind": "locked", "due_date": due},
            ))

    incoming_transfer_schedules: list[tuple[models.BufferTransferRule, dict[date, Decimal]]] = []
    outgoing_transfer_schedules: list[tuple[models.BufferTransferRule, dict[date, Decimal]]] = []
    # Sweeps: out of the rule's to_account, into its sweep_to_account.
    sweeps_out: list[tuple[models.BufferTransferRule, dict[date, Decimal]]] = []
    sweeps_in: list[tuple[models.BufferTransferRule, dict[date, Decimal]]] = []
    if apply_buffer_transfers:
        transfer_rules = db.query(models.BufferTransferRule).options(
            joinedload(models.BufferTransferRule.from_account),
            joinedload(models.BufferTransferRule.to_account),
            joinedload(models.BufferTransferRule.sweep_to_account),
        ).filter(
            models.BufferTransferRule.user_id == user_id,
            models.BufferTransferRule.is_active == True,
            or_(
                models.BufferTransferRule.to_account_id == account_id,
                models.BufferTransferRule.from_account_id == account_id,
                models.BufferTransferRule.sweep_to_account_id == account_id,
            ),
        ).all()
        for rule in transfer_rules:
            schedule, sweeps = _compute_transfer_schedules(
                db, user_id, rule, start_date, end_date,
                overrides=overrides, proposal=proposal,
            )
            if schedule and rule.to_account_id == account_id:
                incoming_transfer_schedules.append((rule, schedule))
            if schedule and rule.from_account_id == account_id:
                outgoing_transfer_schedules.append((rule, schedule))
            if sweeps and rule.to_account_id == account_id:
                sweeps_out.append((rule, sweeps))
            if sweeps and rule.sweep_to_account_id == account_id:
                sweeps_in.append((rule, sweeps))

    planned_transfers = db.query(models.PlannedTransfer).options(
        joinedload(models.PlannedTransfer.from_account),
        joinedload(models.PlannedTransfer.to_account),
    ).filter(
        models.PlannedTransfer.user_id == user_id,
        models.PlannedTransfer.status.in_([models.PlannedTransferStatus.pending, models.PlannedTransferStatus.scheduled]),
    ).filter(
        or_(
            models.PlannedTransfer.to_account_id == account_id,
            models.PlannedTransfer.from_account_id == account_id,
        )
    ).all()

    # Deferred import: bonus_allocation.py imports this module back (for
    # _adjust_for_weekend) -- importing it at module scope here would be a
    # circular import.
    from backend.services.bonus_allocation import allocation_transfers
    bonus_transfers = allocation_transfers(db, user, start_date, end_date, override_map) if user else {}

    # Pre-compute which recurring item IDs have linked actuals, and on which dates.
    # Used to suppress projected entries when the actual arrives on a different day.
    actual_by_ri: dict[int, list[date]] = {}
    for t in all_actuals:
        if t.recurring_item_id:
            actual_by_ri.setdefault(t.recurring_item_id, []).append(t.date)

    # Draw the wage base down for wages already RECEIVED before today, before
    # projecting forward -- from today onward the day walk does its own drawdown.
    if ss is not None:
        ss.catch_up(db, user_id, bonus_plans, before=today)

    entries: list[ForecastEntry] = []
    current = start_date

    while current <= end_date:
        if current == horizon and horizon_seed is not None:
            balance = horizon_seed
        if ss is not None:
            ss.roll_year(current)
        day_transactions: list[ForecastTransaction] = []
        actuals_today = actuals_by_date.get(current, [])
        actual_recurring_ids = {t.recurring_item_id for t in actuals_today if t.recurring_item_id}
        actual_manual = [t for t in actuals_today if t.recurring_item_id is None]
        applied_txn_ids: set[int] = set()

        adj_actual_recurring_ids = set(actual_recurring_ids)
        if current.weekday() == 4:
            for offset in (1, 2):
                for t in actuals_by_date.get(current + timedelta(offset), []):
                    if t.recurring_item_id:
                        adj_actual_recurring_ids.add(t.recurring_item_id)

        for item in recurring_items:
            natural_fires = _fires_on(item, current)

            # Actuals always appear on their real date (ISC-17: not shifted)
            if natural_fires and item.id in actual_recurring_ids:
                for actual in actuals_today:
                    if actual.recurring_item_id == item.id:
                        applied_txn_ids.add(actual.id)
                        balance += Decimal(str(actual.amount))
                        day_transactions.append(ForecastTransaction(
                            name=actual.description,
                            amount=actual.amount,
                            type="income" if actual.amount > 0 else "expense",
                            category_name=actual.category.name if actual.category else None,
                            is_actual=True,
                            recurring_item_id=item.id,
                            transaction_id=actual.id,
                        ))
                continue

            if current.weekday() in (5, 6):
                continue  # shifted to preceding Friday

            # The date this item actually fires on before any weekend shift --
            # `current` itself when it fires naturally, or the Sat/Sun it got
            # pulled forward from when the Friday lookahead below is what
            # matched. A yearly bonus's plan year must come from THIS date,
            # not from `current`: a Jan 1 payout landing on a Saturday shifts
            # onto the preceding Friday, which can fall in December of the
            # PRIOR year (see bonus_gross_amt below).
            natural_fire_date = current
            fires_projected = natural_fires
            if not fires_projected and current.weekday() == 4:
                if _fires_on(item, current + timedelta(1)):
                    fires_projected = True
                    natural_fire_date = current + timedelta(1)
                elif _fires_on(item, current + timedelta(2)):
                    fires_projected = True
                    natural_fire_date = current + timedelta(2)

            if not fires_projected:
                continue
            if item.id in adj_actual_recurring_ids:
                continue

            # Suppress projected if a linked actual exists for this item but arrived on a
            # different day: monthly/yearly → any actual this calendar month; biweekly/weekly → ±3 days.
            if item.id in actual_by_ri:
                ri_actual_dates = actual_by_ri[item.id]
                freq = getattr(item, "frequency", None)
                if freq in (models.RecurringFrequency.monthly, models.RecurringFrequency.yearly):
                    if any(d.year == current.year and d.month == current.month for d in ri_actual_dates):
                        continue
                else:
                    if any(abs((d - current).days) <= 3 for d in ri_actual_dates):
                        continue

            # A known real statement wins over the modelled amount for its own
            # due date only. the user's Duke Electric is modelled at $200.00/month
            # while the bill due 2026-09-08 is $250.00; editing the item would
            # rewrite every future month to a September-only number and lose
            # the estimate the forecast needs for October onward.
            #
            # Keyed by the NATURAL due date: the weekend shift moves only the
            # day it posts. Looked up on `current`, a statement due Saturday
            # missed on the Friday it posts and the modelled amount went in.
            actual_override = bill_actuals.get((item.id, natural_fire_date))
            bonus_plan = bonus_plans.get(item.id)
            # Year of the NATURAL fire date, not `current` -- see
            # natural_fire_date above. Counting the gross against the SS
            # wage base on `current` (Dec 31) remains correct as-is: that's
            # a separate question of which calendar year's base the money
            # counts toward, not which year's plan amount it is.
            bonus_gross_amt = bonus_gross(bonus_plan, user, natural_fire_date.year) if bonus_plan else None
            if actual_override is not None:
                base_amount = actual_override
            elif bonus_gross_amt is not None:
                base_amount = bonus_net(bonus_plan, bonus_gross_amt) + override_map.get(item.id, Decimal("0"))
            else:
                base_amount = item.amount + override_map.get(item.id, Decimal("0"))
            is_cc = item.type == models.RecurringType.credit_card_payment

            # SS paycheck boost: accumulate gross, apply boost once wage base is hit
            # (SSWageBaseTracker holds the rules, shared with ss_paycheck_boosts).
            ss_boost = Decimal("0")
            if ss is not None and item.id in ss.paycheck_ids:
                ss_boost = ss.paycheck_boost(current)
            elif ss is not None and bonus_gross_amt is not None:
                ss_boost = ss.bonus_boost(current, bonus_gross_amt)

            signed = (base_amount + ss_boost) if item.type == models.RecurringType.income else -base_amount
            balance += signed
            cc_name = item.card.name if is_cc and item.card else None
            day_transactions.append(ForecastTransaction(
                name=f"CC Payment: {cc_name}" if cc_name else item.name,
                amount=signed,
                type=item.type.value,
                category_name=item.category.name if item.category else None,
                is_actual=False,
                is_cc_payment=is_cc,
                recurring_item_id=item.id,
                is_ss_boosted=ss_boost > 0,
            ))

        # Apply linked actuals that arrived on a different day than their natural_fires date.
        # These have recurring_item_id set but weren't handled in the items loop above.
        for actual in actuals_today:
            if actual.recurring_item_id is not None and actual.id not in applied_txn_ids:
                balance += Decimal(str(actual.amount))
                day_transactions.append(ForecastTransaction(
                    name=actual.description,
                    amount=actual.amount,
                    type="income" if actual.amount > 0 else "expense",
                    category_name=actual.category.name if actual.category else None,
                    is_actual=True,
                    recurring_item_id=actual.recurring_item_id,
                    transaction_id=actual.id,
                ))

        # Apply manual actual transactions (not linked to any recurring item)
        for actual in actual_manual:
            balance += Decimal(str(actual.amount))
            day_transactions.append(ForecastTransaction(
                name=actual.description,
                amount=actual.amount,
                type="income" if actual.amount > 0 else "expense",
                category_name=actual.category.name if actual.category else None,
                is_actual=True,
                transaction_id=actual.id,
            ))

        # Funding legs first: the money has to arrive before the purchase can
        # draw on it, and on a same-day transfer the ordering is what keeps
        # the running balance from dipping through a trough that never
        # actually happens.
        for pe, signed_move in funding_by_date.get(current, []):
            balance += signed_move
            day_transactions.append(ForecastTransaction(
                name=(f"Transfer for {pe.name}" if signed_move > 0 else f"Funding {pe.name}"),
                amount=signed_move,
                type="income" if signed_move > 0 else "expense",
                category_name=None,
                is_actual=False,
                is_planned=True,
                is_transfer=True,
            ))

        for pe in planned_by_date.get(current, []):
            # abs() then re-sign from `direction`, so a row stored with either
            # sign behaves the same and an inflow is not silently flipped
            # negative -- which is what happened before `direction` existed and
            # was why a known one-off inflow (a bonus, an Airbnb payout) could
            # not be modeled at all.
            is_inflow = pe.direction == models.PlannedDirection.inflow
            signed = abs(pe.amount) if is_inflow else -abs(pe.amount)
            balance += signed
            day_transactions.append(ForecastTransaction(
                name=pe.name,
                amount=signed,
                type="income" if is_inflow else "expense",
                category_name=pe.category.name if pe.category else None,
                is_actual=False,
                is_planned=True,
            ))

        for pe, card in card_planned_by_date.get(current, []):
            # Card-linked planned expenses land here, on the card's due date,
            # not on pe.expected_date -- see card_planned_by_date's comment
            # above. Suppression against a real posted charge is deliberately
            # NOT attempted here: unlike the recurring CC payoff/estimate
            # injections (which suppress against ANY actual near the due
            # date), a one-off planned purchase has no reliable way to match
            # itself to one specific imported transaction among many on the
            # same statement, so it would risk suppressing on an unrelated
            # charge here. Instead bank sync settles the plan against its
            # real charge (services/planned_auto_settle.py), which drops it
            # from the query above.
            is_inflow = pe.direction == models.PlannedDirection.inflow
            signed = abs(pe.amount) if is_inflow else -abs(pe.amount)
            balance += signed
            day_transactions.append(ForecastTransaction(
                name=f"{pe.name} (via {card.name})",
                amount=signed,
                type="income" if is_inflow else "expense",
                category_name=pe.category.name if pe.category else None,
                is_actual=False,
                is_planned=True,
                is_cc_payment=True,
            ))

        for card_payment in cc_payments.get(current, []):
            if card_payment.card_id in moved_overdue.get(current, ()):
                continue  # re-planned on today, after today's auto anchor
            # Suppress if an actual CC payment for this card was imported near this date
            card_obj = active_cards_by_id[card_payment.card_id]
            if _cc_actual_nearby(card_obj, current, nearby_actuals):
                continue
            signed = -card_payment.amount
            balance += signed
            day_transactions.append(ForecastTransaction(
                name=f"CC Payment: {card_obj.name}",
                amount=signed,
                type="expense",
                category_name=None,
                is_actual=False,
                is_cc_payment=True,
                is_cc_locked=True,
                basis=card_payment.basis,
            ))

        for card_payment in cc_estimates_by_date.get(current, []):
            # An estimate is a guess about a payment still to come; on a date
            # already behind today it only resurrects a paid or superseded
            # cycle (a paid month looks unclaimed again once the next
            # statement arrives).
            if current < today:
                continue
            # Suppress if an actual CC payment for this card was imported near this date
            card_obj = active_cards_by_id[card_payment.card_id]
            if _cc_actual_nearby(card_obj, current, nearby_actuals):
                continue
            signed = -card_payment.amount
            balance += signed
            day_transactions.append(ForecastTransaction(
                name=f"CC Estimate: {card_obj.name}",
                amount=signed,
                type="expense",
                category_name="Credit Card Estimate",
                is_actual=False,
                is_cc_payment=True,
                basis=card_payment.basis,
            ))

        interest_rate = getattr(account, "interest_rate", None)
        if (
            interest_rate
            and interest_rate > 0
            and current.day == _last_day_of_month(current)
        ):
            rate = Decimal(str(interest_rate))
            monthly_interest = round(balance * rate / Decimal("100") / Decimal("12"), 2)
            if monthly_interest > 0:
                balance += monthly_interest
                day_transactions.append(ForecastTransaction(
                    name="Interest Credit",
                    amount=monthly_interest,
                    type="income",
                    is_actual=False,
                ))

        for rule, schedule in incoming_transfer_schedules:
            amt = schedule.get(current)
            if amt:
                balance += amt
                day_transactions.append(ForecastTransaction(
                    name=f"Transfer from {rule.from_account.name}",
                    amount=amt,
                    type="income",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                ))

        for rule, schedule in outgoing_transfer_schedules:
            amt = schedule.get(current)
            if amt:
                balance -= amt
                day_transactions.append(ForecastTransaction(
                    name=f"Transfer to {rule.to_account.name}",
                    amount=-amt,
                    type="expense",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                ))

        for rule, sweeps in sweeps_out:
            amt = sweeps.get(current)
            if amt:
                balance -= amt
                day_transactions.append(ForecastTransaction(
                    name=f"Sweep to {rule.sweep_to_account.name if rule.sweep_to_account else 'Savings'}",
                    amount=-amt,
                    type="expense",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                    is_planned_transfer=True,
                ))

        for rule, sweeps in sweeps_in:
            amt = sweeps.get(current)
            if amt:
                balance += amt
                day_transactions.append(ForecastTransaction(
                    name=f"Sweep from {rule.to_account.name}",
                    amount=amt,
                    type="income",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                    is_planned_transfer=True,
                ))

        for pt in planned_transfers:
            if pt.target_date != current:
                continue
            if pt.to_account_id == account_id:
                balance += pt.amount
                day_transactions.append(ForecastTransaction(
                    name=f"Planned Transfer from {pt.from_account.name if pt.from_account else 'Savings'}",
                    amount=pt.amount,
                    type="income",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                    is_planned_transfer=True,
                ))
            if pt.from_account_id == account_id:
                balance -= pt.amount
                day_transactions.append(ForecastTransaction(
                    name=f"Planned Transfer to {pt.to_account.name}",
                    amount=-pt.amount,
                    type="expense",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                    is_planned_transfer=True,
                ))

        for bt in bonus_transfers.get(current, []):
            if bt.to_account_id == account_id:
                balance += bt.amount
                day_transactions.append(ForecastTransaction(
                    name=f"Bonus transfer from {bt.from_name}",
                    amount=bt.amount,
                    type="income",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                    is_planned_transfer=True,
                ))
            if bt.from_account_id == account_id:
                balance -= bt.amount
                day_transactions.append(ForecastTransaction(
                    name=f"Bonus transfer to {bt.to_name}",
                    amount=-bt.amount,
                    type="expense",
                    category_name=None,
                    is_actual=False,
                    is_transfer=True,
                    is_planned_transfer=True,
                ))

        # Apply day checkpoint AFTER all transactions so the anchor value is the
        # final balance for the day (and the starting point for the next day).
        if current in day_checkpoint_map:
            balance = day_checkpoint_map[current]
        # After the anchor, which is the posted balance -- see
        # pending_today_lines above.
        if current == today and not todays_anchor_is_manual:
            for line in pending_today_lines:
                balance += line.amount
                day_transactions.append(line)
        if current == today:
            for line in overdue_today_lines:
                balance += line.amount
                day_transactions.append(line)

        # Did the day's checkpoint move the balance? Walked is yesterday's
        # balance plus the day's settled lines (pending card payments land
        # after the anchor, so they are not part of what it replaced). The
        # window's first day has no yesterday and always counts as moved.
        anchor_moved, anchor_delta = False, None
        if current in day_checkpoint_map:
            if entries:
                walked = entries[-1].projected_balance + sum(
                    (t.amount for t in day_transactions if not t.is_pending), Decimal("0"),
                )
                anchor_delta = day_checkpoint_map[current] - walked
                anchor_moved = abs(anchor_delta) >= Decimal("0.005")
            else:
                anchor_moved = True
        entries.append(ForecastEntry(
            date=current,
            projected_balance=balance,
            transactions=day_transactions,
            anchor_moved=anchor_moved,
            anchor_delta=anchor_delta,
        ))
        current += timedelta(days=1)

    return entries


def find_balance_risk(entries: list[ForecastEntry], threshold: Decimal) -> dict:
    """Scan forecast entries in order and return the first day the balance drops
    below threshold. entries must already be sorted by date ascending (build_forecast
    returns them in that order).
    """
    for entry in entries:
        if entry.projected_balance < threshold:
            return {
                "at_risk": True,
                "date": entry.date,
                "amount": entry.projected_balance,
                "threshold": threshold,
            }
    return {"at_risk": False, "date": None, "amount": None, "threshold": threshold}


def risk_status(entries: list[ForecastEntry], cushion: Decimal) -> str:
    """The window's lowest balance read against the one cushion: "danger" below
    $0, "warning" below the cushion, else "ok" (no entries -> "ok")."""
    if not entries:
        return "ok"
    return cushion_status(min(e.projected_balance for e in entries), cushion)


def suggest_transfer(
    db: Session,
    user: models.User,
    account_id: int,
    risk: dict,
    entries: list[ForecastEntry],
) -> dict:
    """Given a risk dict from find_balance_risk (at_risk=True) and the same
    `entries` list that risk was computed from, compute a suggested one-time
    transfer that would clear the WHOLE window, rounded UP to the user's
    transfer_increment (default $1000).

    Sized off the window minimum, not the first breach. find_balance_risk
    reports the FIRST day the balance dips below threshold, which is not
    necessarily the lowest point. A shallow dip (a small bill) followed by a
    deep one (a down payment) used to produce a suggestion sized to the
    shallow dip, leaving the real hole uncovered.

    already_planned is informational only, never suppression. build_forecast
    already injects every pending/scheduled PlannedTransfer into the day-by-day
    walk, so `entries` -- and therefore this shortfall -- is already net of
    whatever the user has accepted. If at_risk is still True after that injection,
    the existing plans are demonstrably not enough and the correct answer is a
    top-up sized to what's still missing.

    The old behavior suppressed on the *existence* of a nearby active plan
    rather than its *adequacy*: accepting a too-small suggestion permanently
    dead-ended the banner, which stayed red with no way to get a corrected
    suggestion short of hand-editing the transfer's amount. Callers can still
    use already_planned to word this as "top up the transfer you already have"
    versus "no plan here yet".
    """
    empty = {"amount": None, "date": None, "from_account_id": None, "already_planned": False}
    if not risk.get("at_risk"):
        return empty

    risk_date = risk["date"]

    window_start = risk_date - timedelta(days=5)
    window_end = risk_date + timedelta(days=5)
    already_planned = db.query(models.PlannedTransfer).filter(
        models.PlannedTransfer.user_id == user.id,
        models.PlannedTransfer.to_account_id == account_id,
        models.PlannedTransfer.status.in_([models.PlannedTransferStatus.pending, models.PlannedTransferStatus.scheduled]),
        models.PlannedTransfer.target_date >= window_start,
        models.PlannedTransfer.target_date <= window_end,
    ).first() is not None

    window_min = min(
        (e.projected_balance for e in entries),
        default=risk["amount"],
    )
    shortfall = risk["threshold"] - window_min
    if shortfall <= 0:
        return {**empty, "already_planned": already_planned}

    increment = user.transfer_increment or Decimal("1000.00")
    amount = (shortfall / increment).to_integral_value(rounding=ROUND_CEILING) * increment

    savings_accounts = db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.type == models.AccountType.savings,
        models.Account.is_active == True,
        # Never suggest moving money from an account to itself.
        models.Account.id != account_id,
    ).all()
    from_account_id = savings_accounts[0].id if len(savings_accounts) == 1 else None

    return {
        "amount": amount,
        # Default to the 1st of the risk month -- the user pulls the transfer in
        # at the start of the month the shortfall lands in, not a few days
        # before the dip itself. Never a date already in the past though.
        "date": max(risk_date.replace(day=1), date.today()),
        "from_account_id": from_account_id,
        "already_planned": already_planned,
    }


def find_transfer_signal(entries: list[ForecastEntry]) -> dict:
    """Scan forecast entries in order and return the first scheduled buffer
    transfer (a ForecastTransaction with is_transfer=True and a positive
    amount, i.e. money arriving). entries must already be sorted by date
    ascending (build_forecast returns them in that order).
    """
    for entry in entries:
        for txn in entry.transactions:
            if txn.is_transfer and txn.amount > 0 and not txn.is_planned_transfer:
                from_name = txn.name.removeprefix("Transfer from ")
                return {
                    "triggered": True,
                    "date": entry.date,
                    "amount": txn.amount,
                    "from_name": from_name,
                }
    return {"triggered": False, "date": None, "amount": None, "from_name": None}


def build_quarters(
    db: Session,
    user_id: int,
    account_id: int,
    year: int,
    overrides: list[dict] | None = None,
    precomputed_days: list[ForecastEntry] | None = None,
    proposal: ScenarioProposal | None = None,
) -> list[QuarterSummary]:
    """Quarter summaries for one calendar year.

    `precomputed_days` lets a multi-year caller supply one continuous walk
    covering every year it wants. Re-walking per year re-derives the opening
    balance each time, and a fresh window does not reproduce a continuous one
    exactly -- the SS wage base is one contributor -- which left a visible
    step between December and January. Sharing a single walk removes the
    seam by construction rather than by reconciling two paths.
    """
    # Custom walk: a year view needs its history from Jan 1. From the walk
    # horizon on, build_forecast gives the standard walk's balances.
    # Build the full year in one pass so Q2+ open balances chain from Q1 close.
    full_start = date(year, 1, 1)
    full_end = date(year, 12, 31)
    if precomputed_days is not None:
        all_days = [d for d in precomputed_days if full_start <= d.date <= full_end]
    elif year > date.today().year:
        # A future year is walked continuously from the start of the current
        # one, not as an isolated window. Both reach the same December, but
        # only if they take the same path -- walked in isolation the year
        # ended ~$750 apart from the same year inside a multi-year view,
        # so the two screens disagreed about the same date.
        span = build_forecast(
            db, user_id, account_id, date(date.today().year, 1, 1), full_end,
            overrides=overrides, proposal=proposal,
        )
        all_days = [d for d in span if full_start <= d.date <= full_end]
    else:
        all_days = build_forecast(
            db, user_id, account_id, full_start, full_end,
            overrides=overrides, proposal=proposal,
        )
    if not all_days:
        return []

    quarters = []
    for q in range(1, 5):
        month_start = (q - 1) * 3 + 1
        start = date(year, month_start, 1)
        end_month = month_start + 2
        end = date(year, end_month, monthrange(year, end_month)[1])

        days = [d for d in all_days if start <= d.date <= end]
        if not days:
            continue

        open_balance = days[0].projected_balance - sum(
            t.amount for t in days[0].transactions
        )
        close_balance = days[-1].projected_balance
        total_income = sum(
            t.amount for day in days for t in day.transactions if t.amount > 0
        )
        total_expenses = sum(
            -t.amount for day in days for t in day.transactions if t.amount < 0
        )
        quarters.append(QuarterSummary(
            quarter=q,
            year=year,
            open_balance=open_balance,
            close_balance=close_balance,
            total_income=total_income,
            total_expenses=total_expenses,
            net=total_income - total_expenses,
            days=days,
        ))
    return quarters
