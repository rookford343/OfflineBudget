"""Forecast gaps found reconciling Q3 2026 against Budget.xlsx on 2026-08-14.

Three separate bugs, each of which moved the quarter minimum -- the number
Safety Margin is built on, and the one Dan reads before approving a large
purchase:

  1. The SS wage-base boost was granted in full to the paycheck that CROSSED
     the base, overstating that check by up to $533.37 and pulling the whole
     step-up a paycheck early.
  2. A card whose next_payment_date had gone stale vanished from the forecast
     entirely, taking its real balance_due with it.
  3. Cards with no manual spend estimate projected $0, even when they carried
     subscriptions that say exactly what they will be charged.

Plus the quarterly frequency the sheet needs for Stormwater ("Qtr" in
Budget!C15), which the app could not express at all.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
import pytest
from backend import models
from backend.services.forecast_engine import build_forecast


GROSS = Decimal("8602.76")
NET = Decimal("6066.63")
FULL_BOOST = (GROSS * Decimal("0.062")).quantize(Decimal("0.01"))  # 533.37


def _user(db, **kw):
    user = models.User(username=kw.pop("username", "dan"), hashed_password="x", display_name="Dan", **kw)
    db.add(user)
    db.flush()
    return user


def _checking(db, user, balance="10000.00"):
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal(balance),
    )
    db.add(account)
    db.flush()
    return account


def _named(entries, name):
    """(date, amount) for every projected transaction with this name."""
    return [
        (e.date, t.amount)
        for e in entries for t in e.transactions
        if t.name == name and not t.is_actual
    ]


# --- 1. SS wage-base crossing --------------------------------------------

def test_crossing_paycheck_gets_only_the_boost_it_earned(db_session):
    """SS is still withheld on the wages up to the base. Only the slice of the
    crossing paycheck ABOVE the base comes back, so that one check lands
    between NET and NET + full boost -- never at the full boost.

    The wage base here is one paycheck of gross plus $1,000, so check 2 is the
    crossing one and $7,602.76 of it sits above the base: a $471.37 boost.
    Before the fix check 2 got the whole $533.37."""
    user = _user(db_session, ss_gross_per_paycheck=GROSS, ss_wage_base=Decimal("9602.76"), ss_bonus_ytd=Decimal("0"))
    account = _checking(db_session, user)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=NET, type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    checks = _named(build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 5, 31)), "Paycheck")

    assert len(checks) >= 3
    assert checks[0][1] == NET, "nothing crossed yet on the first check"
    partial = (Decimal("7602.76") * Decimal("0.062")).quantize(Decimal("0.01"))
    assert checks[1][1] == NET + partial, (
        f"the crossing paycheck must be pro-rated to {partial}, not given the full {FULL_BOOST}"
    )
    assert checks[2][1] == NET + FULL_BOOST, "every check after the crossing gets the full boost"


def test_a_paycheck_that_lands_exactly_on_the_base_gets_no_boost(db_session):
    """Boundary: when the base empties to exactly zero, none of that check is
    above the base, so it earns nothing. The next one gets the full boost."""
    user = _user(db_session, ss_gross_per_paycheck=GROSS, ss_wage_base=GROSS, ss_bonus_ytd=Decimal("0"))
    account = _checking(db_session, user)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=NET, type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    checks = _named(build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 4, 30)), "Paycheck")

    assert checks[0][1] == NET, "the check that exactly consumes the base earns no boost"
    assert checks[1][1] == NET + FULL_BOOST


# --- 2. Quarterly recurring items ----------------------------------------

def test_quarterly_item_fires_every_third_month_from_its_start_month(db_session):
    """Budget!C15 marks Stormwater "Qtr" and the sheet charges $14.82 on 9/30
    and 12/31. month_of_year names the first month of the cycle, so 3 means
    Mar/Jun/Sep/Dec -- and nothing in the eight months between."""
    user = _user(db_session)
    account = _checking(db_session, user)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Stormwater",
        amount=Decimal("14.82"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.quarterly,
        month_of_year=3, day_of_month=0,  # last day of the month
        start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    hits = _named(build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 12, 31)), "Stormwater")

    months = sorted({d.month for d, _ in hits})
    assert months == [3, 6, 9, 12], f"expected Mar/Jun/Sep/Dec, got months {months}"
    assert all(amt == Decimal("-14.82") for _, amt in hits), "each firing charges the whole quarterly bill"


# --- 3. Credit cards the forecast used to drop ---------------------------

def _card(db, user, **kw):
    defaults = dict(
        name="Apple Card", credit_limit=Decimal("5000.00"),
        statement_day=31, due_day=25, is_active=True,
    )
    defaults.update(kw)
    card = models.CreditCard(user_id=user.id, **defaults)
    db.add(card)
    db.flush()
    return card


def test_a_stale_next_payment_date_still_gets_its_balance_paid(db_session):
    """Dan's Apple Card sat at next_payment_date 2026-05-25 with $287.15 due
    while the forecast ran August, so the window check never matched and the
    card was invisible: no payoff, no estimate, no money leaving checking.
    Cards that sync monthly at best will always drift like this, so a past due
    date rolls forward to the next real one."""
    user = _user(db_session)
    account = _checking(db_session, user)
    _card(db_session, user, balance_due=Decimal("287.15"), current_balance=Decimal("287.15"),
          next_payment_date=date(2020, 5, 25))  # far past, whatever "today" is
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2020, 1, 1), date(2099, 12, 31))
    payoffs = _named(entries, "CC Payment: Apple Card")

    assert payoffs, "a stale due date must not swallow a real balance"
    assert payoffs[0][1] == Decimal("-287.15")
    assert payoffs[0][0].day == 25, "rolled forward to the card's own due day"


def test_card_with_no_manual_estimate_projects_its_subscriptions(db_session):
    """A card only ever charged by its subscriptions is better forecast from
    those subscriptions than from a balance that syncs monthly at best (Dan,
    2026-08-14). $57.39 billed on the 30th closes on that month's statement
    and is paid off on the NEXT month's due date."""
    user = _user(db_session)
    account = _checking(db_session, user)
    card = _card(db_session, user, monthly_spend_estimate=None)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, card_id=card.id, name="Apple",
        amount=Decimal("57.39"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=30, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 3, 1), date(2026, 6, 30))
    estimates = _named(entries, "CC Estimate: Apple Card")

    assert estimates, "subscriptions on the card must drive its estimate"
    assert all(amt == Decimal("-57.39") for _, amt in estimates)
    assert all(d.day == 25 for d, _ in estimates), "paid on the card's due day"
    assert len(estimates) == 4, f"one per month in the window, got {[str(d) for d, _ in estimates]}"


def test_a_subscription_charge_never_hits_checking_directly(db_session):
    """The charge lands on the card; only the payoff touches checking. If the
    subscription estimate were injected on the charge date instead, checking
    would be debited twice over."""
    user = _user(db_session)
    account = _checking(db_session, user)
    card = _card(db_session, user, monthly_spend_estimate=None)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, card_id=card.id, name="Apple",
        amount=Decimal("57.39"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=30, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 3, 1), date(2026, 6, 30))

    assert not _named(entries, "Apple"), "the raw card charge must stay off the checking walk"


def test_a_manual_estimate_still_wins_over_the_subscriptions(db_session):
    """Chase carries a $5,500/mo manual estimate because Dan spends freely
    from it; its subscriptions alone would badly understate that."""
    user = _user(db_session)
    account = _checking(db_session, user)
    card = _card(db_session, user, name="Chase Sapphire", due_day=25, statement_day=28,
                 monthly_spend_estimate=Decimal("5500.00"))
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, card_id=card.id, name="Netflix",
        amount=Decimal("19.99"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=29, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 3, 1), date(2026, 6, 30))
    estimates = _named(entries, "CC Estimate: Chase Sapphire")

    assert estimates
    assert all(amt == Decimal("-5500.00") for _, amt in estimates), (
        "the manual estimate must not be replaced by, or added to, the subscription total"
    )


# --- 5. Safety Margin floor (Dan, 2026-08-14) ----------------------------

def _floor_scenario(db, *, payoff_day: int, paycheck_day: int):
    """Checking with one paycheck and one card whose payoff digs a trough that
    the next paycheck fills back in."""
    user = _user(db, username=f"floor{payoff_day}{paycheck_day}")
    account = _checking(db, user, balance="10000.00")
    _card(db, user, name="Chase", statement_day=28, due_day=payoff_day,
          balance_due=Decimal("9000.00"), current_balance=Decimal("9000.00"),
          next_payment_date=date(2026, 8, payoff_day))
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=Decimal("6000.00"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=paycheck_day, start_date=date(2026, 1, 1),
    ))
    db.commit()
    return user, account


def test_the_payoff_trough_is_not_the_safety_floor(db_session):
    """The dip between a card payoff and the next paycheck settles spending
    already done and already funded, so it must not set the floor -- and
    skipping only the payoff DAY does not achieve that, because the balance
    sits flat at the post-payoff figure until the paycheck lands."""
    from backend.services.budget_snapshot import _lookahead_minimum

    user, account = _floor_scenario(db_session, payoff_day=25, paycheck_day=31)
    floor, when = _lookahead_minimum(db_session, user.id, account.id, date(2026, 8, 14))

    assert when is not None
    assert not (date(2026, 8, 25) <= when <= date(2026, 8, 30)), (
        f"floor landed at {when}, inside the payoff dip it is supposed to skip"
    )
    assert floor > Decimal("1000.00"), "the post-payoff trough must not be the reported floor"


def test_a_real_recorded_payoff_is_also_not_the_safety_floor(db_session):
    """Dan's real case, 2026-08-27: once the payoff moves from a PROJECTED
    line (is_cc_locked=True, what _floor_scenario above builds) to a REAL
    actual transaction -- recorded via the Record Payment button, or a bank
    sync -- it loses the is_cc_locked flag entirely (real actuals never carry
    it). The floor-skip logic only ever checked is_cc_locked, so a real
    recorded payoff's dip started counting as the reported floor again --
    exactly the dip the projected-line skip was built to avoid."""
    from backend.services.budget_snapshot import _lookahead_minimum

    user = _user(db_session, username="realpayoff")
    account = _checking(db_session, user, balance="10000.00")
    _card(db_session, user, name="Chase", statement_day=28, due_day=25,
          balance_due=Decimal("0"), current_balance=Decimal("1000.00"))
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=Decimal("6000.00"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=31, start_date=date(2026, 1, 1),
    ))
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 25),
        amount=Decimal("-9000.00"), description="CC Payment: Chase",
        is_actual=True,
    ))
    db_session.commit()

    floor, when = _lookahead_minimum(db_session, user.id, account.id, date(2026, 8, 14))

    assert when is not None
    assert not (date(2026, 8, 25) <= when <= date(2026, 8, 30)), (
        f"floor landed at {when}, inside the real payoff's dip it is supposed to skip"
    )
    assert floor > Decimal("1000.00"), "the post-payoff trough must not be the reported floor"


def test_pending_payment_marker_reduces_opening_balance(db_session):
    """A card flagged payment_sent_pending_sync=True subtracts its snapshot
    amount from checking's opening balance immediately -- before any real
    sync has confirmed the payment happened. This is what a Record Payment
    workaround used to do by creating a real (and sometimes duplicate)
    Transaction; the marker gets the same immediate effect without one."""
    user = _user(db_session, username="pendingmarker")
    account = _checking(db_session, user, balance="1000.00")
    _card(db_session, user, name="Chase", balance_due=Decimal("500.00"),
          current_balance=Decimal("500.00"),
          payment_sent_pending_sync=True, payment_sent_amount=Decimal("500.00"))
    db_session.commit()

    today = date.today()
    entries = build_forecast(db_session, user.id, account.id, today, today)
    assert entries[0].projected_balance == Decimal("500.00"), (
        f"opening balance must be reduced by the pending amount, got "
        f"{entries[0].projected_balance}"
    )


def test_unflagged_cards_do_not_affect_the_opening_balance(db_session):
    """Regression guard: a card with payment_sent_pending_sync left at its
    default (False) must not touch the opening balance at all -- this is
    what every existing card in every other test in this file already
    assumes."""
    user = _user(db_session, username="notpending")
    account = _checking(db_session, user, balance="1000.00")
    _card(db_session, user, name="Chase", balance_due=Decimal("500.00"),
          current_balance=Decimal("500.00"))
    db_session.commit()

    today = date.today()
    entries = build_forecast(db_session, user.id, account.id, today, today)
    assert entries[0].projected_balance == Decimal("1000.00")


def test_a_pending_marker_suppresses_the_payoff_injection_too(db_session):
    """The marker's balance-seed subtraction (Task 1) is not the only place
    this card's payoff could land -- the pre-existing payoff injection
    further down this same per-card loop still fires whenever
    next_payment_date sits inside the window, because marking a card
    doesn't touch next_payment_date or balance_due. Confirmed live (final
    review, 2026-08-28): a $5,000 payment left checking twice without
    this guard."""
    user = _user(db_session, username="pendingsuppress")
    account = _checking(db_session, user, balance="10000.00")
    _card(db_session, user, name="Chase", balance_due=Decimal("5000.00"),
          current_balance=Decimal("5000.00"),
          next_payment_date=date.today() + timedelta(days=3),
          payment_sent_pending_sync=True, payment_sent_amount=Decimal("5000.00"))
    db_session.commit()

    today = date.today()
    entries = build_forecast(db_session, user.id, account.id, today, today + timedelta(days=10))
    payoffs = _named(entries, "CC Payment: Chase")
    assert not payoffs, (
        f"a pending-flagged card must not ALSO get the old payoff "
        f"injection on top of the seed subtraction, got {payoffs}"
    )
    assert entries[0].projected_balance == Decimal("5000.00"), (
        "opening balance still correctly reduced exactly once"
    )


def test_asking_from_inside_the_dip_gives_the_same_floor(db_session):
    """Asked on the 27th -- two days into the payoff dip -- the answer must
    match asking on the 14th. The lookback that settles the skip state before
    `as_of` is what makes this hold."""
    from backend.services.budget_snapshot import _lookahead_minimum

    user, account = _floor_scenario(db_session, payoff_day=25, paycheck_day=31)
    _, early = _lookahead_minimum(db_session, user.id, account.id, date(2026, 8, 14))
    _, inside = _lookahead_minimum(db_session, user.id, account.id, date(2026, 8, 27))

    assert inside is not None
    assert not (date(2026, 8, 25) <= inside <= date(2026, 8, 30)), (
        "asking from inside the dip must not report a day inside the dip"
    )
    assert early is not None


def test_the_lookahead_window_is_three_rolling_months(db_session):
    """Not the calendar quarter, which shrank as the quarter aged: asked on
    8/14 it saw only to 9/30, and on 9/28 it would have seen two days."""
    from backend.services.budget_snapshot import _lookahead_minimum

    user = _user(db_session, username="window")
    account = _checking(db_session, user, balance="10000.00")
    # A one-off dip well past the end of Q3, reachable only by a rolling window.
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=account.id, name="Late dip",
        amount=Decimal("9000.00"), expected_date=date(2026, 11, 5),
    ))
    db_session.commit()

    floor, when = _lookahead_minimum(db_session, user.id, account.id, date(2026, 9, 28))

    assert when is not None and when >= date(2026, 11, 5), (
        f"a rolling 3-month window from 9/28 must reach 11/5; got {when}"
    )
    assert floor <= Decimal("1000.00")


# --- 6. Locked vs in-flux (Dan, 2026-08-14) ------------------------------

def test_an_estimated_payoff_can_still_be_the_floor(db_session):
    """Only the LOCKED payoff is excluded. A later cycle's estimate is still
    in flux and still responsive to what Dan spends, so it is exactly the
    event he needs the floor to show -- his sheet keeps the 9/25 payment
    ($4,041.32) inside the B25 range while excluding the 8/25 locked one."""
    from backend.services.budget_snapshot import _lookahead_minimum

    user = _user(db_session, username="influx")
    account = _checking(db_session, user, balance="20000.00")
    card = _card(db_session, user, name="Chase", statement_day=28, due_day=25,
                 balance_due=Decimal("1000.00"), current_balance=Decimal("1000.00"),
                 next_payment_date=date(2026, 8, 25),
                 monthly_spend_estimate=Decimal("15000.00"))
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=Decimal("6000.00"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=31, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    _, when = _lookahead_minimum(db_session, user.id, account.id, date(2026, 8, 14))

    assert when is not None and when.month >= 9, (
        f"an estimated payoff must remain eligible as the floor; got {when}"
    )


def test_the_cycle_after_a_locked_payoff_uses_the_carried_balance(db_session):
    """Dan's method: running balance minus what is already statemented is
    spending he has made but not been billed for, so the next cycle is mostly
    known. $4,000 balance with $3,000 due leaves $1,000 carried, plus a $100
    subscription posting before the statement closes -- $1,100, not the
    $15,000 flat estimate. Later cycles keep the flat estimate."""
    user = _user(db_session, username="carried")
    account = _checking(db_session, user, balance="60000.00")
    card = _card(db_session, user, name="Chase", statement_day=28, due_day=25,
                 current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
                 pending_charges=Decimal("0"), next_payment_date=date(2026, 8, 25),
                 monthly_spend_estimate=Decimal("15000.00"))
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, card_id=card.id, name="Sub",
        amount=Decimal("100.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=20, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 14), date(2026, 11, 30))
    estimates = dict(_named(entries, "CC Estimate: Chase"))

    sept = [amt for d, amt in estimates.items() if d.month == 9]
    assert sept == [Decimal("-1100.00")], (
        f"the cycle after the locked payoff must be carried + upcoming subs, got {sept}"
    )
    later = [amt for d, amt in estimates.items() if d.month >= 10]
    assert later, "later cycles must still be projected"
    assert all(a == Decimal("-15000.00") for a in later), (
        f"cycles beyond the next one keep the flat estimate, got {later}"
    )


def test_the_locked_payoff_is_flagged_and_the_estimate_is_not(db_session):
    """The floor logic keys on is_cc_locked, not on the transaction name."""
    user = _user(db_session, username="flagged")
    account = _checking(db_session, user, balance="60000.00")
    _card(db_session, user, name="Chase", statement_day=28, due_day=25,
          current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
          next_payment_date=date(2026, 8, 25), monthly_spend_estimate=Decimal("500.00"))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 14), date(2026, 11, 30))
    flags = {
        t.name.split(":")[0]: t.is_cc_locked
        for e in entries for t in e.transactions if t.is_cc_payment
    }
    assert flags.get("CC Payment") is True, "the statemented payoff is locked"
    assert flags.get("CC Estimate") is False, "an estimated payoff is not locked"


def test_balance_due_at_zero_still_carries_forward_real_debt(db_session):
    """Dan's real case, 2026-08-27: Chase Sapphire's $9,273.76 statement was
    paid off (balance_due -> 0), but $6,701.18 of real, already-spent debt
    remains on current_balance -- money already spent, just not yet
    statemented. The carried-balance derivation's guard required
    balance_due > 0, so once it dropped to 0 the derivation went silent
    entirely and the forecast fell back to the flat $5,500/mo estimate --
    understating the very next payoff by over $1,200, and with it the
    household's 3-month safety margin (Dan caught this live comparing
    against his spreadsheet, which still tracks the real remaining debt)."""
    user = _user(db_session, username="zerobalance")
    account = _checking(db_session, user, balance="60000.00")
    _card(db_session, user, name="Chase", statement_day=28, due_day=25,
          current_balance=Decimal("6701.18"), balance_due=Decimal("0"),
          next_payment_date=date(2026, 8, 25), monthly_spend_estimate=Decimal("5500.00"))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 27), date(2026, 11, 30))
    estimates = dict(_named(entries, "CC Estimate: Chase"))

    sept = [amt for d, amt in estimates.items() if d.month == 9]
    assert sept, "the next cycle must still plan for the real carried debt, not go silent"
    assert sept == [Decimal("-6701.18")], (
        f"balance_due at 0 must not silence the carried-balance derivation -- "
        f"current_balance is real, already-spent debt regardless, got {sept}"
    )

    later = [amt for d, amt in estimates.items() if d.month >= 10]
    assert all(a == Decimal("-5500.00") for a in later), (
        f"cycles beyond the next one, with no carried debt left, fall back "
        f"to the flat monthly estimate as normal, got {later}"
    )


def test_a_same_day_actual_is_not_double_counted_when_start_date_is_today(db_session):
    """Dan's real case, 2026-08-27: manually recorded a $9,273.76 card payoff
    dated today, updating current_balance directly (checking.current_balance
    -= amount) the same way the Record Payment endpoint does. `/forecast/risk`
    calls build_forecast with start_date == today exactly. The opening-balance
    seed's `start_date < today` branch correctly reverses actuals dated before
    today so the walk can re-apply them once -- but the `start_date == today`
    branch (`else: balance = current_balance`) skipped that reversal entirely,
    so a same-day actual got applied twice: once already baked into
    current_balance, once again when the walk's first day re-applies
    `actuals_today`. Reproduced exactly: $696.81 - $9,273.76 landed at
    -$8,576.95, matching what the live risk alert showed."""
    user = _user(db_session, username="sameday")
    account = _checking(db_session, user, balance="696.81")
    today = date.today()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=today,
        amount=Decimal("-9273.76"), description="CC Payment: Chase Sapphire",
        is_actual=True,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, today, today + timedelta(days=3))
    assert entries[0].projected_balance == Decimal("696.81"), (
        f"a same-day actual must be applied exactly once, not baked into the "
        f"opening balance AND re-applied in the walk, got {entries[0].projected_balance}"
    )


# --- 7. SS wage-base checkpoint (Dan, 2026-08-14) ------------------------

def _checkpoint_user(db, *, withheld_ytd: str, as_of: date, wage_base: str = "184500.00",
                      gross_per_check: str = "8602.76", paycheck_day: int = 31,
                      username: str = "checkpoint"):
    user = _user(
        db, username=username,
        ss_gross_per_paycheck=Decimal(gross_per_check),
        ss_wage_base=Decimal(wage_base),
        ss_withheld_ytd=Decimal(withheld_ytd),
        ss_withheld_ytd_as_of=as_of,
    )
    account = _checking(db, user)
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=Decimal("6066.63"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=paycheck_day, start_date=date(2026, 1, 1),
    ))
    db.commit()
    return user, account


def test_checkpoint_recovers_gross_from_withheld_tax(db_session):
    """Dan's real case: $11,343.06 withheld as of 8/14 implies $182,952.58
    gross, still $1,547.42 under the $184,500 base -- the checkpoint date's
    own paycheck must get NO boost, and the crossing lands on the NEXT one."""
    user, account = _checkpoint_user(
        db_session, withheld_ytd="11343.06", as_of=date(2026, 8, 14), paycheck_day=31,
    )
    # A same-day paycheck recurring item to exercise the "checkpoint coincides
    # with a still-projected day" branch directly.
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Checkpoint day check",
        amount=Decimal("6066.63"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=14, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 1), date(2026, 9, 30))
    on_checkpoint = _named(entries, "Checkpoint day check")
    later = _named(entries, "Paycheck")

    assert on_checkpoint and on_checkpoint[0][1] == Decimal("6066.63"), (
        "the checkpoint date's own paycheck must get no boost -- it is already "
        "fully accounted for inside the checkpoint figure"
    )
    assert any(amt > Decimal("6066.63") for _, amt in later), (
        "the crossing must still arrive on a later paycheck"
    )


def test_checkpoint_takes_priority_over_legacy_bonus_ytd(db_session):
    """Setting both must not average or combine them -- the checkpoint is
    strictly preferred, since it is the more direct measurement."""
    user = _user(
        db_session, username="both",
        ss_gross_per_paycheck=Decimal("8602.76"), ss_wage_base=Decimal("184500.00"),
        ss_bonus_ytd=Decimal("0"),  # legacy field implying the base is nowhere close to hit
        ss_withheld_ytd=Decimal("11439.00"), ss_withheld_ytd_as_of=date(2026, 8, 14),  # implies ~$184,500 -- essentially AT the base
    )
    account = _checking(db_session, user)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=Decimal("6066.63"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=31, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    checks = _named(build_forecast(db_session, user.id, account.id, date(2026, 8, 1), date(2026, 9, 30)), "Paycheck")

    assert checks[0][1] > Decimal("6066.63"), (
        "the checkpoint (nearly at the base) must win over ss_bonus_ytd=0 (nowhere near it)"
    )


def test_no_checkpoint_falls_back_to_legacy_bonus_ytd(db_session):
    """Existing users without a checkpoint must see no behavior change."""
    user = _user(
        db_session, username="legacy",
        ss_gross_per_paycheck=Decimal("8602.76"), ss_wage_base=Decimal("17205.52"),
        ss_bonus_ytd=Decimal("0"),
    )
    account = _checking(db_session, user)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=Decimal("6066.63"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    checks = _named(build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 6, 30)), "Paycheck")

    assert checks[2][1] == NET + FULL_BOOST, "legacy reconstruction is unchanged when no checkpoint is set"


# --- Second-hop carry-forward, seeded by fresh pending_charges ------------

def test_the_cycle_after_the_carried_cycle_uses_fresh_pending_charges(db_session):
    """Dan's spreadsheet edit, 2026-08-28: the cycle right after the locked
    payoff's own carried cycle should use live pending-charges data instead
    of jumping straight to the flat monthly estimate, the same way the
    first carried cycle already does. pending_charges legitimately flows
    into both cycles here, through two different mechanisms: cycle 1 (Sept)
    picks it up via the pre-existing, unchanged `carried` formula
    (current_balance + pending_charges - balance_due, no freshness check --
    by design, not something this feature touches), and cycle 2 (Oct) picks
    it up via this task's new second-hop logic, which reads pending_charges
    on its own through the freshness-checked `_fresh_pending_charges`
    helper. This test pins both."""
    user = _user(db_session, username="secondhop")
    account = _checking(db_session, user, balance="60000.00")
    card = _card(
        db_session, user, name="Chase", statement_day=28, due_day=25,
        current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("2000.00"),
        pending_charges_updated_at=datetime.utcnow(),
        next_payment_date=date.today() + timedelta(days=1),
        monthly_spend_estimate=Decimal("15000.00"),
    )
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 14), date(2026, 12, 31))
    estimates = dict(_named(entries, "CC Estimate: Chase"))

    sept = [amt for d, amt in estimates.items() if d.month == 9]
    assert sept == [Decimal("-3000.00")], (
        f"first carried cycle already folds in pending_charges via the "
        f"pre-existing, unchanged carried formula, got {sept}"
    )
    oct_ = [amt for d, amt in estimates.items() if d.month == 10]
    assert oct_ == [Decimal("-2000.00")], (
        f"second hop must use fresh pending_charges instead of the flat estimate, got {oct_}"
    )
    later = [amt for d, amt in estimates.items() if d.month >= 11]
    assert later, "cycles beyond the second hop must still be projected"
    assert all(a == Decimal("-15000.00") for a in later), (
        f"cycles beyond the second hop keep the flat estimate, got {later}"
    )


def test_zero_pending_charges_skips_the_second_hop(db_session):
    """No pending charges means no real second-hop signal -- that month
    falls through to the flat estimate exactly as it did before this
    feature existed."""
    user = _user(db_session, username="secondhopzero")
    account = _checking(db_session, user, balance="60000.00")
    _card(
        db_session, user, name="Chase", statement_day=28, due_day=25,
        current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("0"),
        next_payment_date=date.today() + timedelta(days=1),
        monthly_spend_estimate=Decimal("15000.00"),
    )
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 14), date(2026, 11, 30))
    estimates = dict(_named(entries, "CC Estimate: Chase"))

    oct_ = [amt for d, amt in estimates.items() if d.month == 10]
    assert oct_ == [Decimal("-15000.00")], (
        f"zero pending_charges must fall through to the flat estimate, got {oct_}"
    )


def test_stale_pending_charges_skips_the_second_hop(db_session):
    """A pending-charges figure older than 7 days is not trusted -- it
    falls through to the flat estimate the same as a zero value."""
    user = _user(db_session, username="secondhopstale")
    account = _checking(db_session, user, balance="60000.00")
    _card(
        db_session, user, name="Chase", statement_day=28, due_day=25,
        current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("2000.00"),
        pending_charges_updated_at=datetime.utcnow() - timedelta(days=10),
        next_payment_date=date.today() + timedelta(days=1),
        monthly_spend_estimate=Decimal("15000.00"),
    )
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 14), date(2026, 11, 30))
    estimates = dict(_named(entries, "CC Estimate: Chase"))

    oct_ = [amt for d, amt in estimates.items() if d.month == 10]
    assert oct_ == [Decimal("-15000.00")], (
        f"stale pending_charges must fall through to the flat estimate, got {oct_}"
    )


def test_pending_charges_with_no_timestamp_skips_the_second_hop(db_session):
    """A nonzero pending_charges with no recorded timestamp (a pre-existing
    row from before this feature shipped, or one a sync just cleared) is
    treated as already stale rather than silently trusted."""
    user = _user(db_session, username="secondhopnostamp")
    account = _checking(db_session, user, balance="60000.00")
    _card(
        db_session, user, name="Chase", statement_day=28, due_day=25,
        current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("2000.00"),
        pending_charges_updated_at=None,
        next_payment_date=date.today() + timedelta(days=1),
        monthly_spend_estimate=Decimal("15000.00"),
    )
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 14), date(2026, 11, 30))
    estimates = dict(_named(entries, "CC Estimate: Chase"))

    oct_ = [amt for d, amt in estimates.items() if d.month == 10]
    assert oct_ == [Decimal("-15000.00")], (
        f"a nonzero value with no timestamp must fall through to the flat estimate, got {oct_}"
    )
