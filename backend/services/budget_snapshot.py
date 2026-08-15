"""Household budget snapshot -- 'Left to Spend' / 'Safety Margin' and the
supporting credit-card/category/merchant data shown on the Dashboard and in
the weekly email. Formulas reverse-engineered from Dan's Budget.xlsx
(sheets "Budget" and "2026 Overview") and verified to reproduce its real
numbers exactly -- see backend/tests/test_budget_snapshot.py.
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import BudgetSnapshot, CardSnapshot, WeeklyDigestCategory, MerchantSpendingEntry
from backend.services.forecast_engine import build_forecast
from backend.services.spendable_pacer import compute_weekly_spendable
from backend.services.spending_helpers import category_totals_for_range, merchant_totals


def _monthly_income(db: Session, user_id: int) -> Decimal:
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.income,
        models.RecurringItem.is_active == True,
        models.RecurringItem.frequency == models.RecurringFrequency.monthly,
    ).all()
    return sum((item.amount for item in items), Decimal("0"))


def _monthly_expenses(db: Session, user_id: int, as_of: date) -> Decimal:
    """All active expense recurring items, monthly + any yearly item due
    this month -- covers Checking Bills, Credit Card Bills, and Tithing
    combined, matching how Budget.xlsx's Leftover formula treats them."""
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
    ).all()
    total = Decimal("0")
    for item in items:
        if item.frequency == models.RecurringFrequency.monthly:
            total += item.amount
        elif item.frequency == models.RecurringFrequency.quarterly:
            # Accrued, not charged: a quarterly bill spreads across the three
            # months it covers, exactly as the sheet does -- Budget!B15 carries
            # Stormwater at $4.94/mo while the forecast charges the full $14.82
            # once a quarter. Counting the whole bill in its own month would
            # make Leftover lurch every third month.
            total += (item.amount / 3).quantize(Decimal("0.01"))
        elif item.frequency == models.RecurringFrequency.yearly and item.month_of_year == as_of.month:
            total += item.amount
    return total


def _budget_allocation_total(
    db: Session, user_id: int, category_name: str, year: int, month: int,
) -> Decimal:
    """The budgeted amount for a category, honouring a month-specific override.

    month == 0 is the "all months" default and 1-12 overrides it. Sorting
    ascending and taking the last row means a month-specific figure wins --
    the same resolution budget_calculator.compute_overview uses (see its
    month.in_([0, month]) query). This used to filter month == 0 only, so
    setting, say, a higher December savings target left the snapshot still
    quoting the annual default.
    """
    rows = (
        db.query(models.BudgetAllocation)
        .join(models.Category, models.Category.id == models.BudgetAllocation.category_id)
        .filter(
            models.BudgetAllocation.user_id == user_id,
            models.Category.name == category_name,
            models.BudgetAllocation.year == year,
            models.BudgetAllocation.month.in_([0, month]),
        )
        .order_by(models.BudgetAllocation.month)
        .all()
    )
    return rows[-1].budgeted_amount if rows else Decimal("0")


def _card_linked_recurring_items(
    db: Session, user_id: int, as_of: date,
) -> list[models.RecurringItem]:
    """Card-linked expense items that charge in the month containing `as_of`.

    Frequency matters: both callers below treat this list as a set of charges
    landing THIS month, so a yearly item must only appear in its own month.
    Without that filter the annual card subscriptions (Fitbod, Runna,
    Bitdefender, Apple TV+, Rivian Connect+, Natural Cycles -- $597.96/yr)
    counted as if each were billed monthly, overstating the credit-card bill
    total by that amount in all twelve months. Mirrors _monthly_expenses.
    """
    items = db.query(models.RecurringItem).filter(
        models.RecurringItem.user_id == user_id,
        models.RecurringItem.type == models.RecurringType.expense,
        models.RecurringItem.is_active == True,
        models.RecurringItem.card_id.isnot(None),
    ).all()
    return [
        item for item in items
        if item.frequency == models.RecurringFrequency.monthly
        or (
            item.frequency == models.RecurringFrequency.yearly
            and item.month_of_year == as_of.month
        )
        or (
            # Quarterly card charges land whole in their own month, unlike the
            # accrual treatment in _monthly_expenses: both callers here ask
            # "what hits the card this month", which is the full bill or
            # nothing. Dan has no quarterly card items today; this keeps the
            # filter honest if he adds one.
            item.frequency == models.RecurringFrequency.quarterly
            and item.month_of_year is not None
            and (as_of.month - item.month_of_year) % 3 == 0
        )
    ]


def _cc_budget_total(db: Session, user_id: int, as_of: date) -> Decimal:
    """Full monthly total of Dan's 'Credit Card Bills' list (recurring
    subscriptions charged to a card) -- Budget.xlsx's F2."""
    items = _card_linked_recurring_items(db, user_id, as_of)
    return sum((item.amount for item in items), Decimal("0"))


def _charged_so_far(db: Session, user_id: int, as_of: date) -> Decimal:
    """Sum of recurring card-linked charges whose day_of_month has already
    passed this month -- Dan's 'Credit Card Bills' list, filtered to what's
    already posted, matching Budget.xlsx's SUMIF(...'<=' & DAY(...))."""
    items = _card_linked_recurring_items(db, user_id, as_of)
    total = Decimal("0")
    for item in items:
        last_day = calendar.monthrange(as_of.year, as_of.month)[1]
        due_day = item.day_of_month if item.day_of_month > 0 else last_day
        if min(due_day, last_day) <= as_of.day:
            total += item.amount
    return total


def _lookahead_minimum(
    db: Session, user_id: int, account_id: int, as_of: date, months: int = 3,
) -> tuple[Decimal, date | None]:
    """The lowest projected checking balance over the NEXT `months` months and
    the day it lands, EXCLUDING the dip caused by the LOCKED-IN card payoff.

    The distinction is locked vs in-flux, not payoff vs everything else (Dan,
    2026-08-14). The next payoff has already been statemented: its amount is
    known and its date is fixed, so "8/25 is locked in and typically does not
    change unless a refund happens". It cannot be the answer to "how much more
    can I spend", because no amount of restraint changes it. Every LATER
    payoff is a forecast, still in flux and still responsive to what Dan
    spends, so those stay in the running and can absolutely be the floor.

    Skipping only the locked payoff DAY is not enough and was tried first: the
    balance sits flat at the post-payoff figure until the next inflow, so the
    minimum simply moved to 8/26 and nothing changed. The locked dip has to be
    skipped through to the next income event.

    A first pass on 2026-08-14 excluded EVERY payoff dip this way and put the
    floor on 8/31 at $7,147.31, which was too generous: it also excluded the
    9/25 estimated payoff, the very event Dan needs to see. His sheet includes
    it -- '2026 Forecast'!L36 is the 9/25 payment at $4,041.32, sitting inside
    the B25 range.

    The locked payoff still shows up in the balance walk; it is only barred
    from being the reported floor.

    Rolling window, not the calendar quarter (Dan, 2026-08-14: "the lowest
    point in the next 3 months"). The calendar quarter shrank as the quarter
    aged -- asked on 8/14 it looked only as far as 9/30, six and a half weeks,
    and on 9/28 it would have looked two days ahead and called that a floor.
    A large purchase in September has to answer for October and November too.

    The date is returned as well as the amount because it is the more
    actionable half: Dan's spreadsheet keeps both side by side
    ('2026 Overview'!B23:C27) and reads them together before approving a large
    purchase. A trough of $500 next week means something very different from
    the same trough in ten weeks.

    History worth keeping, because this function has now been wrong in both
    directions. A version before 2026-08-09 excluded the payoff from the walk
    ENTIRELY, on the theory that subtracting the card balance downstream
    double-counted it; that was wrong, and the real double-count was
    downstream using the full balance instead of new-spending-since-statement.
    The fix then swung to letting the payoff set the floor, which is what Dan
    corrected on 2026-08-14. The distinction that reconciles both: the payoff
    belongs in the BALANCE (it is real money leaving), and does not belong in
    the FLOOR (it is not a constraint on future spending). Safety Margin still
    subtracts only the recurring card bills not yet charged this month, never
    the statemented balance again.
    """
    end_month = as_of.month + months
    end_year = as_of.year + (end_month - 1) // 12
    end_month = (end_month - 1) % 12 + 1
    end = date(end_year, end_month, min(as_of.day, calendar.monthrange(end_year, end_month)[1]))

    # Started early so the skip state below is already settled by `as_of` --
    # asking on the 27th, three days into a payoff dip, must give the same
    # answer as asking on the 14th.
    days = build_forecast(db, user_id, account_id, as_of - timedelta(days=45), end)
    if not days:
        return Decimal("0"), None

    in_locked_dip = False
    candidates = []
    for day in days:
        if any(t.is_cc_locked for t in day.transactions):
            in_locked_dip = True
        if any(t.type == "income" and t.amount > 0 for t in day.transactions):
            in_locked_dip = False
        if day.date >= as_of and not in_locked_dip:
            candidates.append(day)

    if not candidates:
        candidates = [d for d in days if d.date >= as_of]
    if not candidates:
        return Decimal("0"), None
    low = min(candidates, key=lambda day: day.projected_balance)
    return low.projected_balance, low.date


def _weekly_allowance(amount: Decimal, as_of: date) -> tuple[Decimal, int]:
    last_day = calendar.monthrange(as_of.year, as_of.month)[1]
    days_remaining = last_day - as_of.day + 1
    if days_remaining <= 7:
        weekly = amount
    else:
        weekly = (amount / (Decimal(days_remaining) / Decimal(7))).quantize(Decimal("0.01"))
    return weekly, days_remaining


def compute_budget_snapshot(
    db: Session,
    user: models.User,
    account_id: int,
    as_of: date | None = None,
) -> BudgetSnapshot:
    as_of = as_of or date.today()

    monthly_income = _monthly_income(db, user.id)
    monthly_expenses = _monthly_expenses(db, user.id, as_of)
    savings_budget = _budget_allocation_total(db, user.id, "Savings", as_of.year, as_of.month)
    groceries_budget = _budget_allocation_total(db, user.id, "Groceries", as_of.year, as_of.month)
    leftover = monthly_income - monthly_expenses - savings_budget - groceries_budget

    active_cards = db.query(models.CreditCard).filter(
        models.CreditCard.user_id == user.id,
        models.CreditCard.is_active == True,
    ).all()
    # NEW spending accumulated since each card's last statement closed --
    # NOT the full running balance, and NOT just balance_due. quarter_min
    # (below) already reflects paying off each card's last-statement total
    # (balance_due) via the forecast's own payoff projection, so subtracting
    # the full current_balance again here would double-count that same
    # statement amount; subtracting only balance_due would miss the new,
    # not-yet-statemented spending entirely. current_balance - balance_due
    # + pending_charges is exactly that gap. Read directly from Dan's real
    # spreadsheet 2026-08-09 ("2026 Overview"!B12: "=-9273.76+10524.22+605.99"
    # -- literally -balance_due + current_balance + pending_charges for
    # Chase Sapphire). Before bank sync this was usually ~0 (current_balance
    # tracked balance_due closely by hand); live sync now keeps
    # current_balance accurate to the minute, so the gap is real and
    # material -- confirmed live: Chase Sapphire alone carried a $1,860.77
    # gap on 2026-08-09.
    #
    # Left to Spend used to subtract the full sum of current_balance instead,
    # which double-counted every card's already-statemented balance_due: that
    # amount is a payment Dan has already budgeted for (it sits in Checking
    # Bills and lands in the forecast on the due date), not money eroding this
    # month's spending room. Confirmed live 2026-08-12: the app showed Left to
    # Spend -$8,290.67 against the spreadsheet's +$945.85, a $9,236 gap almost
    # exactly equal to the $9,560.91 of balance_due across both cards. The old
    # test fixture hid this by pre-computing the delta into current_balance
    # and leaving balance_due at 0.
    new_spending_total = sum((c.current_balance - c.balance_due + c.pending_charges for c in active_cards), Decimal("0"))
    charged_so_far = _charged_so_far(db, user.id, as_of)
    cc_budget_total = _cc_budget_total(db, user.id, as_of)

    left_to_spend = leftover - new_spending_total + charged_so_far
    quarter_min, quarter_min_date = _lookahead_minimum(db, user.id, account_id, as_of)
    # Safety Margin does NOT subtract new_spending_total -- unlike Left to
    # Spend, quarter_min here is a CHECKING-account balance that the new
    # spending has already flowed through (a card swipe debits checking the
    # moment the statement's payoff hits the forecast's due-date injection;
    # the money isn't sitting outside quarter_min waiting to be counted).
    # An earlier version subtracted it here too, on the theory that this
    # metric (then called "Not Saving") needed its own view of "new
    # spending" the way Left to Spend does -- that was the same shape of
    # double-count as the Left to Spend bug above, just on the other
    # formula. Dan caught it directly in his
    # spreadsheet 2026-08-13 and rewrote '2026 Overview'!B18 to
    # "=B25-(Budget!F2-SUMIF(Budget!C22:C40,'<='&DAY(B11),Budget!B22:B40))" --
    # quarter minimum minus only the recurring card bills not yet charged
    # this month, nothing else. Do not re-add the new_spending_total term to
    # make this look symmetric with Left to Spend -- they aren't, by design.
    #
    # This formula is right -- resolved 2026-08-13 after two rounds against
    # Dan's spreadsheet. The app's original $303.14 vs the sheet's $676.12 on
    # 8/25 traced to real gaps in the app's data, not this formula:
    #   1. "Holland Vacation" (-$917.04) is a real purchase Dan puts on his
    #      Chase card, but PlannedExpense had no way to route a one-off to a
    #      card -- see forecast_engine.py's card_planned_by_date, added to
    #      fix exactly this. It now waits for Chase's real payoff cycle
    #      (statement closes the 28th, due the 25th of the FOLLOWING month --
    #      see _card_payoff_date_for_charge) instead of hitting checking on
    #      the day of the trip. That alone moved the 8/25 quarter minimum
    #      from $303.14 to $1,220.18.
    #   2. The SS wage-base crossing: the app computes it dynamically from
    #      Dan's configured ss_wage_base (184,500, confirmed current --
    #      2026 tax data) and his actual paycheck history, landing on 8/14.
    #      The sheet still hardcodes a 9/15 crossing, a manual guess from
    #      when it was last written by hand -- the app is ahead of the
    #      sheet here, not behind it, and this is expected to stay a
    #      permanent (small, ~$533/paycheck) divergence until Dan updates
    #      the sheet formula to match.
    safety_margin = quarter_min - cc_budget_total + charged_so_far

    safety_margin_weekly, days_remaining = _weekly_allowance(safety_margin, as_of)
    weekly_spendable = compute_weekly_spendable(db, user.id, leftover, as_of)

    cards = [
        CardSnapshot(
            id=c.id, name=c.name, current_balance=c.current_balance,
            pending_charges=c.pending_charges, credit_limit=c.credit_limit,
            utilization_pct=round(float(c.current_balance) / float(c.credit_limit) * 100, 1) if c.credit_limit else 0.0,
            due_day=c.due_day,
        )
        for c in active_cards
    ]

    week_start = as_of - timedelta(days=6)
    cat_totals = category_totals_for_range(db, user.id, week_start, as_of)
    cat_map = {c.id: c.name for c in db.query(models.Category).filter(models.Category.user_id == user.id).all()}
    categories = sorted(
        [
            WeeklyDigestCategory(
                category_id=cid if cid is not None else 0,
                category_name=cat_map.get(cid, "Unknown") if cid is not None else "Uncategorized",
                total=total,
            )
            for cid, total in cat_totals.items()
        ],
        key=lambda c: c.total,
        reverse=True,
    )
    merchants = merchant_totals(db, user.id, week_start, as_of, limit=10)
    top_merchants = [MerchantSpendingEntry(name=n, total=t, count=c) for n, t, c in merchants]

    return BudgetSnapshot(
        as_of=as_of,
        leftover=leftover,
        left_to_spend=left_to_spend,
        left_to_spend_weekly=weekly_spendable.spendable_this_week,
        spendable_today=weekly_spendable.spendable_today,
        days_left_in_week=weekly_spendable.days_left_in_week,
        on_pace=weekly_spendable.on_pace,
        safety_margin=safety_margin,
        safety_margin_weekly=safety_margin_weekly,
        days_remaining_in_month=days_remaining,
        lookahead_minimum=quarter_min,
        lookahead_minimum_date=quarter_min_date,
        cards=cards,
        categories=categories,
        top_merchants=top_merchants,
    )
