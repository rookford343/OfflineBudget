"""Bonuses in the day-by-day forecast: the plan's net for that year lands on
the payout date, and the gross counts toward the Social Security wage base.
All figures are made up."""
from datetime import date, timedelta
from decimal import Decimal

from backend import models
from backend.services.forecast_engine import build_forecast

GROSS_PAY = Decimal("5000.00")       # per paycheck, gross
NET_PAY = Decimal("3500.00")
BOOST = (GROSS_PAY * Decimal("0.062")).quantize(Decimal("0.01"))


def _seed(db, *, wage_base="1000000", month=4, day=15, pay_day=None, fixed=None, salary="100000"):
    user = models.User(username=f"bf{wage_base}{month}{day}", hashed_password="x", display_name="B",
                       annual_salary=Decimal(salary), annual_salary_year=2026, annual_raise_pct=Decimal("0"),
                       ss_gross_per_paycheck=GROSS_PAY, ss_wage_base=Decimal(wage_base),
                       ss_bonus_ytd=Decimal("0"))
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("1000"))
    db.add(acct)
    db.flush()
    pay = models.RecurringItem(user_id=user.id, account_id=acct.id, name="Paycheck", amount=NET_PAY,
                               type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
                               day_of_month=pay_day or day, start_date=date(2026, 1, 1))
    bonus = models.RecurringItem(user_id=user.id, account_id=acct.id, name="Annual Bonus", amount=Decimal("1"),
                                 type=models.RecurringType.income, frequency=models.RecurringFrequency.yearly,
                                 month_of_year=month, day_of_month=day, start_date=date(2026, 1, 1))
    db.add_all([pay, bonus])
    db.flush()
    plan = models.BonusPlan(user_id=user.id, recurring_item_id=bonus.id, target_pct=Decimal("20"),
                            salary_lag_years=1, withholding_pct=Decimal("30"))
    db.add(plan)
    db.flush()
    for year, gross in (fixed or {}).items():
        db.add(models.BonusPlanYear(plan_id=plan.id, year=year, gross_amount=Decimal(gross)))
    db.commit()
    return user, acct, pay, bonus


def _lines(entries, item_id):
    return [(e.date, t.amount) for e in entries for t in e.transactions
            if t.recurring_item_id == item_id and not t.is_actual]


def test_bonus_lands_at_net_on_its_date(db_session):
    user, acct, _, bonus = _seed(db_session)
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 12, 31))
    assert _lines(entries, bonus.id) == [(date(2027, 4, 15), Decimal("14000.00"))]


def test_each_year_uses_its_own_amount(db_session):
    user, acct, _, bonus = _seed(db_session, fixed={2028: "30000"})
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2028, 12, 31))
    assert [amt for _, amt in _lines(entries, bonus.id)] == [Decimal("14000.00"), Decimal("21000.00")]


def test_a_weekend_payout_moves_to_friday(db_session):
    # 2027-05-15 is a Saturday.
    user, acct, _, bonus = _seed(db_session, month=5)
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 12, 31))
    assert [d for d, _ in _lines(entries, bonus.id)] == [date(2027, 5, 14)]


def test_a_linked_deposit_replaces_the_projection(db_session):
    user, acct, _, bonus = _seed(db_session)
    db_session.add(models.Transaction(user_id=user.id, account_id=acct.id, recurring_item_id=bonus.id,
                                      date=date(2027, 4, 15), amount=Decimal("13900.00"),
                                      description="PAYROLL", is_actual=True))
    db_session.commit()
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 12, 31))
    assert _lines(entries, bonus.id) == []


def test_the_bonus_is_never_tagged_as_a_paycheck(db_session):
    """A bonus whose net happens to sit near a paycheck's gross must not get
    the paycheck SS boost or be drawn down as one."""
    user, acct, _, bonus = _seed(db_session, wage_base="10000", fixed={2027: "6000"})  # net 4200 ~ 0.84 x gross pay
    # The paycheck-ratio check reads the stored RecurringItem.amount, not the
    # live bonus_net() figure -- set it to what refresh_item_amounts() would
    # have already written, so this test actually exercises the guard.
    bonus.amount = Decimal("4200.00")
    db_session.commit()
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 12, 31))
    assert _lines(entries, bonus.id) == [(date(2027, 4, 15), Decimal("4200.00") + (Decimal("6000") * Decimal("0.062")).quantize(Decimal("0.01")))]


def test_bonus_gross_pulls_the_ss_crossing_earlier(db_session):
    """Wage base = 3 paychecks + the bonus. The Jan-Mar paychecks and the
    April 10 bonus use it up exactly, so April 20's paycheck is the first
    boosted one. Without counting the bonus, the boost would not start until
    several paychecks later."""
    base = GROSS_PAY * 3 + Decimal("20000")
    user, acct, pay, bonus = _seed(db_session, wage_base=str(base), day=10, pay_day=20)
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 6, 30))
    checks = _lines(entries, pay.id)
    assert [amt for _, amt in checks[:3]] == [NET_PAY] * 3
    assert checks[3][1] == NET_PAY + BOOST   # April 20, after the Apr 9 (Friday) bonus used the rest of the base
    assert checks[4][1] == NET_PAY + BOOST
    # The bonus itself lands exactly on the base (20,000 of base left when it
    # fires) -- none of it sits above the base, so it earns no boost either.
    assert _lines(entries, bonus.id) == [(date(2027, 4, 9), Decimal("14000.00"))], (
        "the bonus crosses the base exactly -- no excess above it, so no boost"
    )


def test_a_bonus_that_crosses_the_base_gets_a_partial_boost(db_session):
    base = GROSS_PAY * 3 + Decimal("5000")   # 15,000 of the 20,000 bonus is above the base
    user, acct, _, bonus = _seed(db_session, wage_base=str(base), day=10, pay_day=20)
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 6, 30))
    [(_, amt)] = _lines(entries, bonus.id)
    assert amt == Decimal("14000.00") + (Decimal("15000") * Decimal("0.062")).quantize(Decimal("0.01"))


# ── Minor A: the engine must guard on the item's own type/frequency ─────────
#
# A BonusPlan can only be attached to a yearly income item at creation time
# (routers/bonus_plans.py's _own_item), but nothing stops the user from
# editing that same item on the Recurring page afterward. Before this fix the
# engine applied the plan's net to ANY item still listed in bonus_plans,
# regardless of what it had become -- a monthly item would fire the bonus's
# net every month instead of its own amount.

def test_bonus_plan_ignored_once_the_item_is_no_longer_yearly_income(db_session):
    user, acct, _, bonus = _seed(db_session)
    bonus.frequency = models.RecurringFrequency.monthly
    bonus.amount = Decimal("42.00")
    db_session.commit()

    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 3, 31))

    assert _lines(entries, bonus.id) == [
        (date(2027, 1, 15), Decimal("42.00")),
        (date(2027, 2, 15), Decimal("42.00")),
        (date(2027, 3, 15), Decimal("42.00")),
    ], "edited to monthly, the item's own amount must fire -- not the bonus plan's net"


def test_bonus_plan_ignored_once_the_item_is_an_expense(db_session):
    user, acct, _, bonus = _seed(db_session)
    bonus.type = models.RecurringType.expense
    bonus.amount = Decimal("500.00")
    db_session.commit()

    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 12, 31))

    assert _lines(entries, bonus.id) == [(date(2027, 4, 15), Decimal("-500.00"))], (
        "edited to an expense, the item's own amount must fire as a debit -- "
        "not the bonus plan's net as a credit"
    )


# ── Minor B: a payout shifted onto Dec 31 must use the shifted-FROM year ────
#
# A Jan 1/Jan 2 payout that falls on a weekend shifts to the preceding
# Friday, which can land in December of the PRIOR year. The engine read the
# plan year from `current.year` (the projection's own date), so a Jan 1 2028
# payout shifted to Fri 2027-12-31 got priced with 2027's gross instead of
# 2028's.

def test_a_jan1_payout_shifted_onto_dec31_uses_the_shifted_from_years_amount(db_session):
    # 2028-01-01 is a Saturday, so that payout shifts to Fri 2027-12-31.
    # 2027-01-01 is itself a Friday, so that payout needs no shift at all --
    # both are exercised in the same window to also prove neither payout is
    # double-counted.
    user, acct, _, bonus = _seed(db_session, month=1, day=1, fixed={2027: "10000", 2028: "20000"})
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2028, 12, 31))

    assert _lines(entries, bonus.id) == [
        (date(2027, 1, 1), Decimal("7000.00")),     # 2027's own payout, unshifted
        (date(2027, 12, 31), Decimal("14000.00")),  # 2028's payout, shifted onto Dec 31 2027
    ], (
        "the Dec-31-shifted projection must price 2028's amount (14,000.00 "
        "net), and 2027 must not be counted twice"
    )


# --- Checkpoint-mode bonus reconciliation (forecast_engine.py's
# "Bonuses received after the pay-stub checkpoint..." block) -------------
#
# These seed ss_withheld_ytd/ss_withheld_ytd_as_of directly (rather than
# going through _seed(), which only ever sets the legacy ss_bonus_ytd field)
# AND freeze forecast_engine.date.today() at a fixed calendar date (the
# pattern test_email_upcoming_dates_20260814.py:104-112 uses for
# summary_generator) instead of deriving every date from the real
# date.today() via timedelta.
#
# That freeze is not cosmetic -- a review caught these tests failing on
# roughly a third of real calendar dates despite the engine being correct,
# because deriving checkpoint/deposit/window dates with a fixed day offset
# from the real "today" dragged the fixture across whichever boundary the
# wall clock happened to be near that day: the Jan-1 per-year wage-base
# reset, the year-match guard (if the checkpoint rolled into last year), or
# simply running out of days left in the year for a day-15 monthly paycheck
# to still fire. Freezing `today` makes every date in these three tests a
# fixed, inspectable constant instead of a moving target.
#
# wage_base is set to exactly the bonus's own gross (10,000.00) with zero
# extra paycheck headroom in every test below, on purpose: the very FIRST
# projected paycheck then shows the whole story in one amount (boosted or
# not), with no need to line up two or three monthly occurrences inside the
# window. That matters here because the forecast's wage base is a
# CALENDAR-YEAR quantity (build_forecast resets ss_remaining_gross to the
# full base the moment current.year advances past the checkpoint's year) --
# a window or a checkpoint spanning a year boundary would see that reset
# fire and silently erase whatever this block computed, independent of
# whether the block itself is correct. Keeping each test's checkpoint and
# forecast window inside one calendar year sidesteps that entirely.


def _freeze_today(monkeypatch, fixed: date) -> date:
    """Pin forecast_engine.date.today() at `fixed` for the duration of the
    test -- monkeypatch restores the real `date` automatically on teardown,
    same as the referenced summary_generator pattern (which restores it by
    hand in a finally: block instead, since it predates this fixture's use
    here)."""
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)
    return fixed


def _distant_month(anchor: date) -> int:
    """A month_of_year for the tests' throwaway bonus RecurringItem, picked
    so it never NATURALLY fires inside these tests' short forecast windows
    (well under a year each) -- these tests care about the bonus's gross
    only through its BonusPlan/BonusPlanYear and an explicit actual deposit,
    and a coincidental second projected bonus line in the window would muddy
    the paycheck-only assertions below. 6 months away from `anchor` can
    never land inside a window that short in either direction."""
    return (anchor.month + 5) % 12 + 1


def _checkpoint_seed(db, *, anchor, wage_base, bonus_plan_year, bonus_plan_gross, username,
                      checkpoint_as_of=None, withheld_ytd="0", legacy_bonus_ytd=None):
    """A user paid monthly (day 15) with one BonusPlan, in either checkpoint
    mode (ss_withheld_ytd/_as_of, when `checkpoint_as_of` is given) or legacy
    mode (ss_bonus_ytd, when it's None). `anchor` only seeds the throwaway
    bonus item's distant month_of_year -- pass whichever date each test's
    forecast window is actually built around. Returns (user, acct, pay,
    bonus, plan) -- `plan` so a test can attach extra BonusPlanYear rows of
    its own."""
    fields = dict(ss_gross_per_paycheck=GROSS_PAY, ss_wage_base=Decimal(wage_base))
    if checkpoint_as_of is not None:
        fields["ss_withheld_ytd"] = Decimal(withheld_ytd)
        fields["ss_withheld_ytd_as_of"] = checkpoint_as_of
    else:
        fields["ss_bonus_ytd"] = Decimal(legacy_bonus_ytd if legacy_bonus_ytd is not None else "0")
    user = models.User(username=username, hashed_password="x", display_name="B", **fields)
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("1000"))
    db.add(acct)
    db.flush()
    pay = models.RecurringItem(user_id=user.id, account_id=acct.id, name="Paycheck", amount=NET_PAY,
                               type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
                               day_of_month=15, start_date=date(2020, 1, 1))
    bonus = models.RecurringItem(user_id=user.id, account_id=acct.id, name="Annual Bonus", amount=Decimal("1"),
                                 type=models.RecurringType.income, frequency=models.RecurringFrequency.yearly,
                                 month_of_year=_distant_month(anchor), day_of_month=1, start_date=date(2020, 1, 1))
    db.add_all([pay, bonus])
    db.flush()
    plan = models.BonusPlan(user_id=user.id, recurring_item_id=bonus.id, target_pct=Decimal("20"),
                            salary_lag_years=1, withholding_pct=Decimal("30"))
    db.add(plan)
    db.flush()
    db.add(models.BonusPlanYear(plan_id=plan.id, year=bonus_plan_year, gross_amount=Decimal(bonus_plan_gross)))
    db.commit()
    return user, acct, pay, bonus, plan


def test_checkpoint_mode_counts_a_bonus_deposited_after_it(db_session, monkeypatch):
    """A bonus paid out after the pay-stub checkpoint (and before today) is
    wages too -- its gross must draw the remaining wage base down just like a
    paycheck would. wage_base equals the bonus's own gross exactly, so once
    the bonus is counted the base is already exhausted and the very next
    projected paycheck gets the full boost immediately -- without counting
    it, that same paycheck would still show no boost at all."""
    today = _freeze_today(monkeypatch, date(2027, 7, 1))
    checkpoint_date = date(2027, 4, 1)
    bonus_actual_date = date(2027, 5, 14)   # after the checkpoint, before today, same year as both
    user, acct, pay, bonus, _ = _checkpoint_seed(
        db_session, anchor=today, wage_base="10000.00",
        bonus_plan_year=checkpoint_date.year, bonus_plan_gross="10000.00",
        username="ckpt_a", checkpoint_as_of=checkpoint_date, withheld_ytd="0",
    )
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, recurring_item_id=bonus.id,
        date=bonus_actual_date, amount=Decimal("7000.00"), description="BONUS PAYROLL", is_actual=True,
    ))
    db_session.commit()

    # Window stays inside the checkpoint's own calendar year -- see the
    # module comment above on why crossing into the next year would reset
    # ss_remaining_gross before this assertion ever gets exercised.
    entries = build_forecast(db_session, user.id, acct.id, today, date(2027, 12, 31))
    checks = _lines(entries, pay.id)

    assert checks, "no projected paycheck in the window"
    assert checks[0][1] == NET_PAY + BOOST, (
        "the bonus deposit already exhausted the base -- the very next "
        "paycheck must be boosted; without counting the deposit it would "
        "still show no boost at all"
    )


def test_legacy_mode_ignores_an_actual_bonus_deposit(db_session, monkeypatch):
    """Without a checkpoint, the wage base is tracked through the legacy
    ss_bonus_ytd figure alone. An actual bonus deposit must NOT also get
    counted through the checkpoint-mode reconciliation block -- a bonus
    ss_bonus_ytd already accounts for would otherwise be subtracted twice."""
    today = _freeze_today(monkeypatch, date(2027, 7, 1))
    bonus_actual_date = date(2027, 5, 14)
    user, acct, pay, bonus, _ = _checkpoint_seed(
        db_session, anchor=today, wage_base="10000.00",
        bonus_plan_year=today.year, bonus_plan_gross="10000.00",
        username="ckpt_b", checkpoint_as_of=None, legacy_bonus_ytd="0",
    )
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, recurring_item_id=bonus.id,
        date=bonus_actual_date, amount=Decimal("7000.00"), description="BONUS PAYROLL", is_actual=True,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, acct.id, today, date(2027, 12, 31))
    checks = _lines(entries, pay.id)

    assert checks, "no projected paycheck in the window"
    assert checks[0][1] == NET_PAY, (
        "legacy mode (ss_bonus_ytd=0, no checkpoint) must not draw the base "
        "down for the actual bonus deposit -- counting it would exhaust the "
        "base immediately and boost this very first paycheck"
    )


def test_checkpoint_mode_ignores_a_bonus_deposited_a_different_year(db_session, monkeypatch):
    """ss_remaining_gross describes ONE calendar year -- the checkpoint's
    own. A bonus deposit dated in a different year, even though it still
    falls inside the reconciliation query's date > checkpoint / date < today
    range, must not draw that year's base down.

    The checkpoint sits in 2026, the deposit in 2027 (still before the
    frozen "today" of mid-2027) -- but the forecast window itself is placed
    inside the CHECKPOINT's own year, 2026 (not anchored at today), per the
    module comment above: a window in a later year would hit the per-year
    reset and pass even if the year-match guard this test targets were
    deleted."""
    # The window below is anchored at checkpoint_date, not today -- the
    # freeze still matters for the reconciliation query's `date < today`
    # bound, just not as a local variable here.
    _freeze_today(monkeypatch, date(2027, 7, 1))
    checkpoint_date = date(2026, 11, 1)
    bonus_actual_date = date(2027, 2, 1)  # before today, but a later calendar year than the checkpoint
    assert bonus_actual_date.year != checkpoint_date.year, "fixture needs a real year boundary between the two"
    user, acct, pay, bonus, plan = _checkpoint_seed(
        db_session, anchor=checkpoint_date, wage_base="10000.00",
        bonus_plan_year=checkpoint_date.year, bonus_plan_gross="10000.00",
        username="ckpt_c", checkpoint_as_of=checkpoint_date, withheld_ytd="0",
    )
    # A real, fixed gross for the DEPOSIT's own year too, so bonus_gross()
    # does not return None for it -- the only thing standing in the way of
    # the subtraction must be the explicit same-calendar-year check, not an
    # incidentally-unknown amount.
    db_session.add(models.BonusPlanYear(plan_id=plan.id, year=bonus_actual_date.year, gross_amount=Decimal("10000.00")))
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, recurring_item_id=bonus.id,
        date=bonus_actual_date, amount=Decimal("7000.00"), description="BONUS PAYROLL", is_actual=True,
    ))
    db_session.commit()

    entries = build_forecast(
        db_session, user.id, acct.id,
        checkpoint_date + timedelta(days=5), date(checkpoint_date.year, 12, 31),
    )
    checks = _lines(entries, pay.id)

    assert checks, "no projected paycheck in the window"
    assert checks[0][1] == NET_PAY, (
        "a bonus deposit dated outside the checkpoint's own calendar year "
        "must not draw that year's wage base down -- counting it would "
        "exhaust the base immediately and boost this very first paycheck"
    )
