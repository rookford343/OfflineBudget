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
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from backend import models
from backend.schemas import ForecastEntry, ForecastTransaction, QuarterSummary
from backend.services.card_matching import card_matches_description

# How many days before "today" a scheduled recurring item can still be
# missing its actual and get folded into today's opening balance anyway,
# rather than silently vanishing from the forecast until bank sync catches
# up. Bank aggregators lag real-world posting by days -- observed live
# 2026-09-01: a $6,504.06 paycheck scheduled Aug 31 sat unconfirmed for a
# full day past "today" with the forecast never accounting for it, because
# the day-walk below never visits a date before start_date. Matches the
# frontend Pending list's own lookback window (Transactions.tsx,
# PENDING_LOOKBACK_DAYS) for the same reason: a card issuer's balance feed
# lagged up to ~6 days earlier this same session.
_UNCONFIRMED_LOOKBACK_DAYS = 7


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


def _card_payoff_date_for_charge(card: "models.CreditCard", charge_date: date) -> date:
    """When a charge made on `charge_date` actually leaves checking: the due
    date of the FIRST statement that closes on or after the charge -- not
    just the next calendar due_day.

    A statement closes ~3-4 weeks before its own due date (Dan's Chase:
    closes the 28th, due the 25th of the FOLLOWING month), so a charge
    posting even one day before a nearby due_day has almost always already
    missed that statement's close and won't be paid off until the NEXT
    cycle. Found live 2026-08-13: a charge Dan makes 8/24 was routed to the
    8/25 due date -- one day later -- when in reality that statement closed
    back on 7/28, so the charge can't be paid off until 9/25.

    Two steps: find the close date (first statement_day on/after the
    charge), then the first due_day strictly after that close -- "strictly"
    matters because a due_day numerically less than statement_day (the
    common case) would otherwise match an already-passed same-month date."""
    close_date = _next_occurrence_on_or_after(card.statement_day, charge_date)
    return _next_occurrence_on_or_after(card.due_day, close_date + timedelta(days=1))


def _fresh_pending_charges(card: "models.CreditCard", today: date) -> Decimal:
    """pending_charges is a hand-typed, point-in-time figure -- trustworthy
    right after Dan enters it, increasingly not as days pass without a real
    sync confirming it. A stale or absent timestamp is treated the same as
    nothing pending at all, never silently carried forward."""
    if not card.pending_charges or card.pending_charges <= 0:
        return Decimal("0")
    if card.pending_charges_updated_at is None:
        return Decimal("0")
    if (today - card.pending_charges_updated_at.date()).days > 7:
        return Decimal("0")
    return Decimal(str(card.pending_charges))


def _card_subscription_charges(
    items: list["models.RecurringItem"], start_date: date, end_date: date,
) -> dict[date, Decimal]:
    """Total charged to a card on each day by its own recurring subscriptions.

    Scanned from well before `start_date` because a charge is paid off a
    statement cycle later: a subscription billed in June is what leaves
    checking in late July, so the window has to reach back far enough to catch
    the charges whose payoff lands inside the forecast. Two months plus a few
    days covers Dan's Chase cycle (closes the 28th, due the 25th of the
    following month) with room to spare.

    Reuses _fires_on so quarterly, yearly, weekly and biweekly subscriptions
    all land on the same dates the checking walk would put them on.
    """
    charges: dict[date, Decimal] = {}
    current = start_date - timedelta(days=70)
    while current <= end_date:
        for item in items:
            if _fires_on(item, current):
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
    """
    anchor = date(start_date.year, 1, 1)
    raw_entries = build_forecast(
        db, user_id, rule.to_account_id, anchor, end_date,
        overrides=overrides,
        apply_buffer_transfers=False,
    )
    if not raw_entries:
        return {}

    check_days: list[date] = []
    cur = anchor
    while cur <= end_date:
        last_day = _last_day_of_month(cur)
        cd = date(cur.year, cur.month, min(rule.check_day, last_day))
        if anchor <= cd <= end_date:
            check_days.append(cd)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)

    schedule: dict[date, Decimal] = {}
    injected_so_far = Decimal("0")
    for i, cd in enumerate(check_days):
        window_end = check_days[i + 1] - timedelta(days=1) if i + 1 < len(check_days) else end_date
        window = [e for e in raw_entries if cd <= e.date <= window_end]
        if not window:
            continue
        lowest_raw = min(e.projected_balance for e in window)
        lowest_adjusted = lowest_raw + injected_so_far
        if lowest_adjusted < rule.action_threshold:
            shortfall = rule.target_floor - lowest_adjusted
            steps = int((shortfall / rule.increment).to_integral_value(rounding=ROUND_CEILING))
            amount = rule.increment * steps
            schedule[cd] = amount
            injected_so_far += amount

    return schedule


def _cc_actual_nearby(
    card: models.CreditCard,
    target: date,
    actuals_by_date: dict[date, list[models.Transaction]],
    window: int = 7,
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
    # (3 -> Mar/Jun/Sep/Dec). Dan's Stormwater bill is the case this exists
    # for: Budget!C15 marks it "Qtr" and the sheet charges $14.82 on 9/30 and
    # 12/31 while carrying $4.94 as the monthly accrual in Budget!B15. Modeling
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


def build_forecast(
    db: Session,
    user_id: int,
    account_id: int,
    start_date: date,
    end_date: date,
    *,
    overrides: list[dict] | None = None,
    apply_buffer_transfers: bool = True,
) -> list[ForecastEntry]:
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

    # SS paycheck boost setup
    user = db.query(models.User).filter(models.User.id == user_id).first()
    ss_paycheck_item_ids: set[int] = set()
    ss_remaining_gross: Decimal | None = None
    ss_boost_per_check = Decimal("0")
    ss_limit_reached = False
    ss_checkpoint_date: date | None = None
    if (
        user
        and user.ss_gross_per_paycheck and user.ss_gross_per_paycheck > 0
        and user.ss_wage_base and user.ss_wage_base > 0
    ):
        ss_gross = user.ss_gross_per_paycheck
        if user.ss_withheld_ytd is not None and user.ss_withheld_ytd_as_of is not None:
            # Preferred: a direct checkpoint off a real pay stub's YTD SS
            # withholding line, rather than reconstructing YTD gross wages by
            # counting actual paychecks against a flat per-paycheck figure.
            # ss_withheld_ytd / 0.062 recovers gross wages actually subject to
            # SS as of that stub -- correct through every raise in the year
            # with no reconstruction, unlike ss_bonus_ytd below. Dan's April
            # raise alone misdated the 2026 crossing by a full paycheck under
            # the old method (found 2026-08-14, YTD withheld $11,343.06 as of
            # the 8/14 check implies gross $182,952.58, still $1,547.42 under
            # the $184,500 base -- crossing is 8/31, not 8/14).
            SS_EMPLOYEE_RATE = Decimal("0.062")
            gross_ytd_at_checkpoint = (user.ss_withheld_ytd / SS_EMPLOYEE_RATE).quantize(Decimal("0.01"))
            ss_remaining_gross = user.ss_wage_base - gross_ytd_at_checkpoint
            ss_checkpoint_date = user.ss_withheld_ytd_as_of
        else:
            ss_bonus_ytd = user.ss_bonus_ytd or Decimal("0")
            ss_remaining_gross = user.ss_wage_base - ss_bonus_ytd
        # Quantized like the monthly interest credit -- it is a dollar amount
        # landing in an account, and unrounded it produced paychecks of
        # $6,600.00112.
        ss_boost_per_check = (ss_gross * Decimal("0.062")).quantize(Decimal("0.01"))
        # Which recurring income items are paychecks (and so stop having Social
        # Security withheld once the wage base is hit)? Compared against
        # ss_gross_per_paycheck, but note the units differ: a recurring income
        # item holds the NET amount that lands in checking, while
        # ss_gross_per_paycheck is gross. Net runs roughly 55-85% of gross after
        # tax, retirement, and benefits, so the old two-sided 0.9..1.1 band
        # could never match a real paycheck -- Dan's is 6066.63/8602.76 = 0.705,
        # which meant the boost silently never fired for anyone and left Q4 2026
        # about $3,150 (6 paychecks x $533) low against his spreadsheet.
        # Confirmed live 2026-08-12.
        #
        # The lower bound stays well above incidental recurring income (a
        # smoothed bonus twelfth, a rental payment) without needing to know the
        # exact withholding rate; the upper bound keeps net from exceeding gross
        # by more than rounding.
        for item in recurring_items:
            if item.type == models.RecurringType.income and item.amount > 0:
                ratio = item.amount / ss_gross
                if Decimal("0.5") <= ratio <= Decimal("1.1"):
                    ss_paycheck_item_ids.add(item.id)

    # Known statement amounts for specific upcoming occurrences, keyed by
    # (recurring_item_id, due_date) so a lookup during the day walk is exact.
    bill_actuals: dict[tuple[int, date], Decimal] = {
        (o.recurring_item_id, o.due_date): o.actual_amount
        for o in db.query(models.BillAmountOverride).filter(
            models.BillAmountOverride.user_id == user_id,
            models.BillAmountOverride.due_date >= start_date,
            models.BillAmountOverride.due_date <= end_date,
        ).all()
    }

    all_active_cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user_id,
        models.CreditCard.is_active == True,
    ).all()
    active_cards_by_id = {c.id: c for c in all_active_cards}

    planned = db.query(models.PlannedExpense).options(
        joinedload(models.PlannedExpense.category)
    ).filter(
        models.PlannedExpense.user_id == user_id,
        models.PlannedExpense.expected_date >= start_date,
        models.PlannedExpense.expected_date <= end_date,
        # A settled one-off already happened, so the real transaction is in
        # the ledger and the balance reflects it. Projecting the estimate too
        # would count the same money twice.
        models.PlannedExpense.settled_on.is_(None),
    ).all()
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
    card_planned_by_date: dict[date, list[tuple[models.PlannedExpense, models.CreditCard]]] = {}
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
        card = active_cards_by_id.get(pe.card_id) if pe.card_id else None
        if card:
            payoff_date = _card_payoff_date_for_charge(card, pe.expected_date)
            card_planned_by_date.setdefault(payoff_date, []).append((pe, card))
        else:
            planned_by_date.setdefault(pe.expected_date, []).append(pe)

    today = date.today()

    # Card-linked expense items -- excluded from the checking walk above (they
    # hit the card, not checking), but they ARE what a lightly-used card is
    # expected to be charged, so they drive its spend estimate below.
    card_expense_items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.account_id == account_id,
        models.RecurringItem.is_active == True,
        models.RecurringItem.include_in_forecast == True,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.card_id.isnot(None),
    ).all()
    card_items_by_card: dict[int, list[models.RecurringItem]] = {}
    for item in card_expense_items:
        card_items_by_card.setdefault(item.card_id, []).append(item)

    # CC payment injections: cards with next_payment_date set, balance_due > 0,
    # and no existing recurring CC payment item already handling this card (avoid double-count).
    recurring_cc_card_ids = {item.card_id for item in recurring_items if item.type == models.RecurringType.credit_card_payment}
    cc_payments: dict[date, list[tuple[str, Decimal]]] = {}
    cc_estimates_by_date: dict[date, list[tuple[str, Decimal]]] = {}
    # Card bills are paid from checking. CreditCard has no payment-account
    # link, so without this guard every payoff and estimate was injected into
    # whichever account was being forecast -- forecasting Dan's savings drew
    # the Chase payoff and two monthly estimates out of it and ended at
    # -$18,298.05. Recurring credit_card_payment items are already scoped by
    # their own account_id and are unaffected.
    injects_card_bills = account.type == models.AccountType.checking
    for card in (all_active_cards if injects_card_bills else []):
        if card.id in recurring_cc_card_ids:
            continue  # recurring CC payment item already handles this card

        if card.payment_sent_pending_sync:
            # Already subtracted once at the opening-balance seed (Task 1,
            # forecast_engine.py's current_balance seed). Every injection
            # path below this point -- locked payoff, carried-forward
            # estimate, flat monthly estimate -- would double it, because
            # marking a card doesn't change next_payment_date or
            # balance_due, the fields those paths key off. Confirmed live
            # by the final whole-branch review, 2026-08-28: a $5,000
            # payment left checking twice without this guard.
            continue

        # A next_payment_date that has gone stale must not swallow the balance.
        # Dan's Apple Card sat at 2026-05-25 with $287.15 due while the forecast
        # ran August: the window check below never matched, so the card was
        # invisible to the forecast entirely -- no payoff, and no estimate
        # either, because its monthly_spend_estimate was 0. Cards that only sync
        # monthly will drift like this by design, so roll a past due date
        # forward to the next real one instead of dropping the money.
        next_payment = card.next_payment_date
        payment_is_stale = bool(
            next_payment is not None
            and next_payment < today
            and card.balance_due and card.balance_due > 0
        )
        if payment_is_stale:
            next_payment = _next_occurrence_on_or_after(card.due_day, max(today, start_date))

        # The cycle right after a locked payoff is not a guess -- most of it is
        # already sitting on the card. Dan derives it exactly this way
        # (2026-08-14): "based on current balance due on 8/25 of $9104.29 and
        # running balance of $12418.45 we get the forecast for next credit
        # card due date which would be 9/25." The gap between running balance
        # and statemented balance is spending already made that simply has not
        # been billed yet; add the subscriptions that will still post before
        # the statement closes and the cycle is nearly determined. A flat
        # monthly estimate ignores all of that and overstated Dan's 9/25 payoff
        # by roughly $1,900.
        #
        # Computed before the stale-payment injection below (not after, as
        # originally written) because a stale `next_payment_date` rolls
        # forward using the same `_next_occurrence_on_or_after(due_day, ...)`
        # math this derives, so the two land on the identical date whenever
        # the real payoff already happened and is just waiting on bank sync --
        # need derived_amount in hand before deciding whether the stale
        # payment would double it up.
        derived_due: date | None = None
        derived_amount = Decimal("0")
        # balance_due at 0 is not "nothing owed" -- it means the last
        # statement is fully paid, but current_balance can still carry real,
        # already-spent debt that hasn't hit a statement yet (Dan's Chase,
        # 2026-08-27: balance_due dropped to $0 right after payoff, while
        # current_balance still carried $6,701.18 of real spend). The
        # original guard required balance_due > 0, so that money silently
        # stopped being planned for the moment a card got paid off -- the
        # forecast fell back to the flat monthly_spend_estimate and
        # understated the very next payoff. `carried` below already computes
        # the right number in both cases (it's current_balance minus
        # whatever's already been billed); only the guard was too narrow.
        if (
            next_payment is not None
            and card.current_balance is not None
            and (
                (card.balance_due and card.balance_due > 0)
                or Decimal(str(card.current_balance)) > 0
            )
        ):
            carried = (
                Decimal(str(card.current_balance))
                + Decimal(str(card.pending_charges or 0))
                - Decimal(str(card.balance_due))
            )
            carried = max(carried, Decimal("0"))
            next_close = _next_occurrence_on_or_after(card.statement_day, max(today, start_date))
            derived_due = _next_occurrence_on_or_after(card.due_day, next_close + timedelta(days=1))
            upcoming = Decimal("0")
            cursor = max(today, start_date) + timedelta(days=1)
            while cursor <= next_close:
                for item in card_items_by_card.get(card.id, []):
                    if _fires_on(item, cursor):
                        upcoming += item.amount
                cursor += timedelta(days=1)
            derived_amount = carried + upcoming

        # Second hop: the cycle right after the one just derived above.
        # There is no "carried" real balance signal for it yet -- that
        # window has not started accruing real spend as of today -- but a
        # fresh pending_charges figure (Dan's own hand-tracked read of what
        # is already posting toward it, per his spreadsheet, 2026-08-28) is
        # still better than jumping straight to the flat monthly estimate.
        # Only one hop: cycles beyond this one have no real signal at all
        # and keep the flat estimate, matching Dan's own unedited
        # spreadsheet cells for every month past this one.
        second_close: date | None = None
        second_due: date | None = None
        second_amount = Decimal("0")
        if derived_due is not None and card.monthly_spend_estimate and card.monthly_spend_estimate > 0:
            # Restricted to monthly_spend_estimate cards only (controller
            # ruling, final whole-branch review, 2026-08-28): on a
            # subscription-driven card, this hop's suppression logic below
            # would delete that month's subscription-based projection
            # instead of supplementing it, since _covered_by_real_payment
            # is shared with the subscription-fallback branch further down
            # this function. The spec's scope was always manually-estimated
            # cards (Dan's Chase); subscription-driven cards (Apple Card)
            # keep their existing, untouched projection unchanged.
            second_close = _next_occurrence_on_or_after(card.statement_day, derived_due + timedelta(days=1))
            second_due = _next_occurrence_on_or_after(card.due_day, second_close + timedelta(days=1))
            second_amount = _fresh_pending_charges(card, today)

        # A stale next_payment_date rolled forward lands on the exact date
        # derived_due just computed above whenever the real payoff already
        # happened and is only waiting on bank sync to confirm it (both use
        # `_next_occurrence_on_or_after(due_day, ...)` anchored near `today`).
        # Injecting the old balance_due there on top of derived_amount would
        # double-charge the card -- $9,273.76 (the stale, presumably
        # already-paid balance) plus $6,416.60 (the next cycle's own carried
        # estimate) on the same day (confirmed live 2026-08-26, crashed the
        # forecast to -$4,478.25). Trust that the payoff happened and fold the
        # two into one line rather than dropping either: the carried figure
        # IS the real, known money (current_balance minus the last statement,
        # both hard numbers) plus a small subscription projection, so it
        # belongs on the "CC Payment" / is_cc_locked=True side, not
        # downgraded to "CC Estimate" just because it merged with the stale
        # payoff (Dan, 2026-08-26). Only merge when derived_amount is
        # actually going to cover the money; a card with nothing carried and
        # no card-linked subscriptions (derived_amount == 0) has nothing
        # standing in for the stale payment, and dropping it there
        # resurrects the original "Apple Card invisible" bug this rollover
        # was written to fix. Same date + a real number to replace it with
        # is what makes merging it safe.
        payment_double_counts_derived = bool(
            payment_is_stale
            and derived_due is not None
            and next_payment == derived_due
            and derived_amount > 0
        )

        if payment_double_counts_derived:
            if start_date <= derived_due <= end_date:
                cc_payments.setdefault(derived_due, []).append((card.name, derived_amount))
        elif (
            next_payment is not None
            and start_date <= next_payment <= end_date
            and card.balance_due and card.balance_due > 0
        ):
            # balance_due only, NOT + pending_charges -- Dan's real
            # spreadsheet forecast pays off only the last-statement total on
            # the due date ("2026 Forecast" row 24: "=L23-9273.76-180.16",
            # no pending-charges term), and separately counts pending_charges
            # exactly once via budget_snapshot.py's new_spending_total.
            # Adding it here too double-counted it: once in this payoff
            # projection, once again downstream. Confirmed live 2026-08-09.
            cc_payments.setdefault(next_payment, []).append(
                (card.name, Decimal(str(card.balance_due)))
            )

        def _covered_by_real_payment(when: date) -> bool:
            """Something better than an estimate already lands in this month --
            either the locked balance_due payoff, or the carried-balance figure
            derived above. A flat estimate on top of either would charge the
            same statement twice."""
            if derived_due is not None and (derived_due.year, derived_due.month) == (when.year, when.month):
                return True
            if second_due is not None and second_amount > 0 and (second_due.year, second_due.month) == (when.year, when.month):
                return True
            return (
                next_payment is not None
                and next_payment.year == when.year
                and next_payment.month == when.month
                and bool(card.balance_due and card.balance_due > 0)
            )

        # Already folded into cc_payments above when it merged with the
        # stale payoff -- injecting it again here would be the exact
        # double-count this whole block exists to prevent.
        if (
            not payment_double_counts_derived
            and derived_due is not None
            and start_date <= derived_due <= end_date
            and derived_amount > 0
        ):
            cc_estimates_by_date.setdefault(derived_due, []).append((card.name, derived_amount))

        if (
            second_due is not None
            and start_date <= second_due <= end_date
            and second_amount > 0
        ):
            cc_estimates_by_date.setdefault(second_due, []).append((card.name, second_amount))

        if card.monthly_spend_estimate and card.monthly_spend_estimate > 0:
            # A manually-set estimate wins: it is Dan's own read on a card he
            # spends freely from (Chase, $5,500/mo), which subscriptions alone
            # would badly understate.
            estimate = Decimal(str(card.monthly_spend_estimate))
            cur = date(start_date.year, start_date.month, 1)
            while cur <= end_date:
                due_day = min(card.due_day, _last_day_of_month(cur))
                inject_date = date(cur.year, cur.month, due_day)
                if start_date <= inject_date <= end_date and not _covered_by_real_payment(inject_date):
                    cc_estimates_by_date.setdefault(inject_date, []).append((card.name, estimate))
                cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
        else:
            # No manual estimate: build one from the subscriptions actually
            # assigned to this card. Dan's Apple Card is only ever charged by
            # its subscriptions, and bank sync refreshes it monthly at best, so
            # the recurring items are a better forward signal than a balance
            # that is stale most of the time (his call, 2026-08-14). Charges are
            # routed through _card_payoff_date_for_charge rather than dropped on
            # the due date in their own month -- a subscription billed the 30th
            # misses that statement's close and is not paid off for another full
            # cycle.
            by_payoff: dict[date, Decimal] = {}
            for charge_date, amount in _card_subscription_charges(
                card_items_by_card.get(card.id, []), start_date, end_date,
            ).items():
                payoff = _card_payoff_date_for_charge(card, charge_date)
                by_payoff[payoff] = by_payoff.get(payoff, Decimal("0")) + amount
            for payoff, amount in sorted(by_payoff.items()):
                if start_date <= payoff <= end_date and not _covered_by_real_payment(payoff):
                    cc_estimates_by_date.setdefault(payoff, []).append((card.name, amount))

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

    # When start_date is in the past, reverse past actuals to find the opening balance.
    # current_balance = opening_balance + sum(all actuals from start_date to yesterday),
    # so opening_balance = current_balance - sum(past actuals).
    current_balance = Decimal(str(account.current_balance))
    if account.type == models.AccountType.checking:
        pending_sent = db.query(models.CreditCard).filter(
            models.CreditCard.user_id == user_id,
            models.CreditCard.is_active == True,
            models.CreditCard.payment_sent_pending_sync == True,
        ).all()
        for card in pending_sent:
            current_balance -= Decimal(str(card.payment_sent_amount or 0))
    if start_date < today:
        past_sum = sum(
            Decimal(str(t.amount)) for t in all_actuals if t.date < today
        )
        balance = current_balance - past_sum
    elif start_date > today:
        # A window that begins in the future has to carry in everything that
        # happens between now and then. Without this it opened at TODAY's
        # balance, so asking for next year silently discarded the remainder of
        # this one -- next January started richer or poorer than December
        # ended, and the two years did not join up.
        #
        # The bridge starts at the beginning of the CURRENT year, not at
        # today, so it walks exactly the same path a same-year request walks.
        # Starting it at today instead made the two disagree on day one: a
        # window opening in the past re-projects bills whose due date has
        # passed but which have not posted yet, while a window opening today
        # anchors to the real bank balance and never sees them. That
        # difference showed up as a seam between December and January.
        #
        # The bridge always starts in the past, so it takes the first branch
        # above and cannot recurse further.
        bridge_start = date(today.year, 1, 1)
        bridge = build_forecast(
            db, user_id, account_id, bridge_start, start_date - timedelta(days=1),
            overrides=overrides, apply_buffer_transfers=apply_buffer_transfers,
        )
        balance = bridge[-1].projected_balance if bridge else current_balance
    else:
        # start_date == today exactly. current_balance is the live bank
        # balance -- it already reflects anything dated today (a same-day
        # bank-synced or manually-recorded transaction, e.g. Dan's Chase
        # payoff, 2026-08-27). The walk's first day re-applies `actuals_today`
        # below, so without this reversal a same-day actual gets counted
        # twice: once already baked into current_balance, once again in the
        # walk. The `start_date < today` branch above already reverses
        # actuals strictly before today for the same reason -- this mirrors
        # it for the one day that branch doesn't cover. Reproduced live:
        # $696.81 - $9,273.76 landed at -$8,576.95 without this.
        today_actuals_sum = sum(
            (Decimal(str(t.amount)) for t in all_actuals if t.date == today),
            Decimal("0"),
        )

        # current_balance only knows what the bank has actually posted. A
        # recurring item due in the last _UNCONFIRMED_LOOKBACK_DAYS is
        # invisible here otherwise: the day-walk below never visits a date
        # before start_date (today), so a paycheck or bill that's scheduled
        # but still unconfirmed by bank sync just silently vanishes from the
        # forecast instead of landing on the date it's supposed to -- Dan's
        # correction, 2026-09-01: "keep forecasting as if transactions are
        # happening as when they say they are happening", not waiting on
        # sync. Bridging through a short recent window (same established
        # pattern as the start_date > today branch above, just with a bounded
        # lookback instead of back to January -- this runs on every
        # start=today call, the common case, so it has to stay cheap) lets
        # the existing day-walk's own actual-vs-projected suppression do the
        # work: when everything in the window is already confirmed, the
        # bridge's ending balance reduces to exactly current_balance (each
        # actual gets reversed out of the seed then re-applied walking
        # forward, net zero); when something recent is still unconfirmed, its
        # projected amount gets added in instead, exactly once, without
        # touching how any OTHER start_date behaves.
        lookback_start = today - timedelta(days=_UNCONFIRMED_LOOKBACK_DAYS)
        bridge = build_forecast(
            db, user_id, account_id, lookback_start, today - timedelta(days=1),
            overrides=overrides, apply_buffer_transfers=apply_buffer_transfers,
        )
        bridged_balance = bridge[-1].projected_balance if bridge else current_balance
        balance = bridged_balance - today_actuals_sum

    # Lookup for CC suppression — keyed by the name stored in cc_payments / cc_estimates_by_date
    card_by_name: dict[str, models.CreditCard] = {(c.name or ""): c for c in all_active_cards}

    day_checkpoint_map: dict[date, Decimal] = {
        cp.date: cp.actual_balance
        for cp in db.query(models.ForecastDayCheckpoint).filter(
            models.ForecastDayCheckpoint.user_id == user_id,
            models.ForecastDayCheckpoint.account_id == account_id,
            models.ForecastDayCheckpoint.date >= start_date,
            models.ForecastDayCheckpoint.date <= end_date,
        ).all()
    }

    incoming_transfer_schedules: list[tuple[models.BufferTransferRule, dict[date, Decimal]]] = []
    outgoing_transfer_schedules: list[tuple[models.BufferTransferRule, dict[date, Decimal]]] = []
    if apply_buffer_transfers:
        transfer_rules = db.query(models.BufferTransferRule).options(
            joinedload(models.BufferTransferRule.from_account),
            joinedload(models.BufferTransferRule.to_account),
        ).filter(
            models.BufferTransferRule.user_id == user_id,
            models.BufferTransferRule.is_active == True,
            or_(
                models.BufferTransferRule.to_account_id == account_id,
                models.BufferTransferRule.from_account_id == account_id,
            ),
        ).all()
        for rule in transfer_rules:
            schedule = _compute_transfer_schedule(db, user_id, rule, start_date, end_date, overrides=overrides)
            if not schedule:
                continue
            if rule.to_account_id == account_id:
                incoming_transfer_schedules.append((rule, schedule))
            if rule.from_account_id == account_id:
                outgoing_transfer_schedules.append((rule, schedule))

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

    # Pre-compute which recurring item IDs have linked actuals, and on which dates.
    # Used to suppress projected entries when the actual arrives on a different day.
    actual_by_ri: dict[int, list[date]] = {}
    for t in all_actuals:
        if t.recurring_item_id:
            actual_by_ri.setdefault(t.recurring_item_id, []).append(t.date)

    # Draw the wage base down for paychecks already RECEIVED this calendar year,
    # before projecting forward. Past days are served from actuals, which
    # `continue` past the projection branch where the drawdown lives, so without
    # this the base only ever saw future paychecks and the boost landed far too
    # late -- or never arrived at all.
    #
    # Counted from January 1 of the forecast year rather than from start_date,
    # because the wage base is a calendar-year quantity. Scoping it to the
    # window instead made the answer depend on the window: /forecast/risk asks
    # for today..+90 and would see zero prior paychecks, so it never applied the
    # boost and ran ~$533 short per paycheck against the Jan-anchored
    # /forecast/quarters the chart draws. That put a false at-risk alert
    # (-$230.23 on 2026-08-25) under a chart whose trough was +$1,083 on the
    # very same day. Found live 2026-08-12.
    #
    # Counted, not summed: SS is withheld on gross, while the stored actual is
    # the net deposit. Only paychecks strictly before today count -- from today
    # onward the day walk does its own drawdown.
    #
    # With a checkpoint, this only needs to bridge the gap between the pay
    # stub's date and today -- ss_remaining_gross already reflects everything
    # through the checkpoint itself, so counting from Jan 1 would double-count
    # every paycheck already folded into ss_withheld_ytd.
    if ss_remaining_gross is not None and ss_paycheck_item_ids:
        catchup_filter = (
            models.Transaction.date > ss_checkpoint_date
            if ss_checkpoint_date is not None
            # No checkpoint: legacy behaviour, unchanged -- counts from Jan 1
            # inclusive, matching how ss_bonus_ytd has always been reconciled.
            else models.Transaction.date >= date(start_date.year, 1, 1)
        )
        received = (
            db.query(models.Transaction)
            .filter(
                models.Transaction.user_id == user_id,
                models.Transaction.is_actual == True,
                models.Transaction.recurring_item_id.in_(ss_paycheck_item_ids),
                catchup_filter,
                models.Transaction.date < today,
            )
            .count()
        )
        if received:
            ss_remaining_gross -= ss_gross * received
            if ss_remaining_gross <= 0:
                ss_limit_reached = True

    entries: list[ForecastEntry] = []
    current = start_date

    while current <= end_date:
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

            fires_projected = natural_fires
            if not fires_projected and current.weekday() == 4:
                fires_projected = (
                    _fires_on(item, current + timedelta(1)) or
                    _fires_on(item, current + timedelta(2))
                )

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
            # due date only. Dan's Duke Electric is modelled at $180.00/month
            # while the bill due 2026-09-08 is $224.31; editing the item would
            # rewrite every future month to a September-only number and lose
            # the estimate the forecast needs for October onward.
            actual_override = bill_actuals.get((item.id, current))
            if actual_override is not None:
                base_amount = actual_override
            else:
                base_amount = item.amount + override_map.get(item.id, Decimal("0"))
            is_cc = item.type == models.RecurringType.credit_card_payment

            # SS paycheck boost: accumulate gross, apply boost once wage base is hit
            ss_boost = Decimal("0")
            # The checkpoint date's own paycheck is already fully accounted
            # for inside ss_remaining_gross (the checkpoint is "as of and
            # including" that date) -- decrementing for it again here would
            # subtract it twice. This only matters on the one day where the
            # checkpoint coincides with a day the live walk still projects
            # (no actual on record for it yet, e.g. it landed today but bank
            # sync hasn't imported it).
            if ss_remaining_gross is not None and item.id in ss_paycheck_item_ids and current == ss_checkpoint_date:
                pass
            elif ss_remaining_gross is not None and item.id in ss_paycheck_item_ids:
                if ss_limit_reached:
                    ss_boost = ss_boost_per_check
                else:
                    # Draw down by GROSS, not item.amount -- the wage base is a
                    # gross-wages figure, while item.amount is the net deposit.
                    # Decrementing by net stretched the run-up ~40% too far
                    # (Dan: 118,260 remaining / 6,066.63 net = 19.5 paychecks,
                    # landing in late Oct 2027 instead of autumn 2026), so the
                    # boost never arrived inside the forecast window at all.
                    ss_remaining_gross -= ss_gross
                    if ss_remaining_gross <= 0:
                        ss_limit_reached = True
                        # The CROSSING paycheck only gets a partial boost: SS is
                        # still withheld on the wages up to the base, and only
                        # the remainder above it comes back. Granting the full
                        # $533.37 here overstated that one check and, worse,
                        # pulled the whole step-up a paycheck early -- caught
                        # 2026-08-14 reconciling to Budget.xlsx, where the app
                        # boosted the 8/14 check while the sheet held flat until
                        # 9/15. After the subtraction above, -ss_remaining_gross
                        # IS the gross above the base, so it needs no separate
                        # bookkeeping. Every check after this one gets the full
                        # boost via the ss_limit_reached branch.
                        excess = min(-ss_remaining_gross, ss_gross)
                        ss_boost = (excess * Decimal("0.062")).quantize(Decimal("0.01"))

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
            # charge. Mark the plan resolved by deleting it once the real
            # purchase posts.
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

        for card_name, amount in cc_payments.get(current, []):
            # Suppress if an actual CC payment for this card was imported near this date
            card_obj = card_by_name.get(card_name)
            if card_obj and _cc_actual_nearby(card_obj, current, actuals_by_date):
                continue
            signed = -amount
            balance += signed
            day_transactions.append(ForecastTransaction(
                name=f"CC Payment: {card_name}",
                amount=signed,
                type="expense",
                category_name=None,
                is_actual=False,
                is_cc_payment=True,
                is_cc_locked=True,
            ))

        for card_name, amount in cc_estimates_by_date.get(current, []):
            # Suppress if an actual CC payment for this card was imported near this date
            card_obj = card_by_name.get(card_name)
            if card_obj and _cc_actual_nearby(card_obj, current, actuals_by_date):
                continue
            signed = -amount
            balance += signed
            day_transactions.append(ForecastTransaction(
                name=f"CC Estimate: {card_name}",
                amount=signed,
                type="expense",
                category_name="Credit Card Estimate",
                is_actual=False,
                is_cc_payment=True,
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

        # Apply day checkpoint AFTER all transactions so the anchor value is the
        # final balance for the day (and the starting point for the next day).
        if current in day_checkpoint_map:
            balance = day_checkpoint_map[current]

        entries.append(ForecastEntry(
            date=current,
            projected_balance=balance,
            transactions=day_transactions,
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
    whatever Dan has accepted. If at_risk is still True after that injection,
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
        # Default to the 1st of the risk month -- Dan pulls the transfer in
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
) -> list[QuarterSummary]:
    """Quarter summaries for one calendar year.

    `precomputed_days` lets a multi-year caller supply one continuous walk
    covering every year it wants. Re-walking per year re-derives the opening
    balance each time, and a fresh window does not reproduce a continuous one
    exactly -- the SS wage base is one contributor -- which left a visible
    step between December and January. Sharing a single walk removes the
    seam by construction rather than by reconciling two paths.
    """
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
            overrides=overrides,
        )
        all_days = [d for d in span if full_start <= d.date <= full_end]
    else:
        all_days = build_forecast(db, user_id, account_id, full_start, full_end, overrides=overrides)
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
