"""Social Security wage-base paycheck boost.

Once cumulative gross wages pass the SS wage base, the 6.2% withholding stops
and every later paycheck deposits more. Dan's spreadsheet models this by hand
('2026 Forecast' Q4 paychecks are "+Budget!$B$2+Salary!O31").

The feature shipped with no test and was inert in three separate ways, all
found live 2026-08-12 -- together worth ~$3,150 of Q4 2026 error and a false
projected overdraft. Each is pinned below.
"""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast


GROSS = Decimal("8602.76")
NET = Decimal("6066.63")
BOOST = (GROSS * Decimal("0.062")).quantize(Decimal("0.01"))  # 533.37


def _seed(db, name=None, *, wage_base: str, bonus_ytd: str = "0", paychecks_received: int = 0):
    """A checking account paid twice monthly (15th and last day), optionally
    with some paychecks already recorded as actuals earlier in the year."""
    user = models.User(
        username=name or f"ss{wage_base}{bonus_ytd}{paychecks_received}",
        hashed_password="x", display_name="SS",
        ss_gross_per_paycheck=GROSS,
        ss_wage_base=Decimal(wage_base),
        ss_bonus_ytd=Decimal(bonus_ytd),
    )
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("10000.00"),
    )
    db.add(account)
    db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=NET, type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db.add(item)
    db.flush()
    for i in range(paychecks_received):
        db.add(models.Transaction(
            user_id=user.id, account_id=account.id, recurring_item_id=item.id,
            date=date(2026, 1 + i, 15), amount=NET, description="Paycheck",
            is_actual=True, source=models.TransactionSource.bank_sync,
        ))
    db.commit()
    return user, account


def _paychecks(entries):
    return [
        (e.date, t.amount)
        for e in entries for t in e.transactions
        if t.name == "Paycheck" and not t.is_actual
    ]


def test_boost_applies_to_a_net_paycheck(db_session):
    """A recurring income item holds the NET deposit, while
    ss_gross_per_paycheck is gross -- here 6066.63/8602.76 = 0.705. The
    original 0.9..1.1 tagging band could not match any real paycheck, so no
    item was ever treated as one and the boost never fired for anybody."""
    user, account = _seed(db_session, wage_base="17205.52")  # exactly 2 paychecks of gross

    entries = build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 4, 30))
    amounts = [amt for _, amt in _paychecks(entries)]

    assert amounts, "no projected paychecks were produced"
    assert any(a > NET for a in amounts), (
        "the boost never fired -- a net-vs-gross ratio near 0.7 must still be "
        "recognised as a paycheck"
    )


def test_wage_base_draws_down_by_gross_not_by_the_net_deposit(db_session):
    """The wage base is a gross-wages figure. Drawing it down by the net
    deposit stretched the run-up ~40% too far and pushed the crossing outside
    the forecast window entirely.

    wage_base is set to just over two paychecks of GROSS, so the boost must
    arrive on the third. Under the old net drawdown it would not arrive until
    the fourth."""
    user, account = _seed(db_session, wage_base="17205.53")

    entries = build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 6, 30))
    checks = _paychecks(entries)

    assert len(checks) >= 4
    assert checks[0][1] == NET
    assert checks[1][1] == NET
    assert checks[2][1] == NET + BOOST, "boost belongs on the 3rd paycheck when the base is 2x gross"
    assert checks[3][1] == NET + BOOST, "and on every paycheck after it"


def test_paychecks_already_received_count_against_the_wage_base(db_session):
    """Days in the past are served from actuals, which skip the projection
    branch where the drawdown lives. Without counting those, a Jan-Dec window
    run late in the year only ever saw future paychecks, so the base never
    emptied. Dan had 14 paychecks in the books by August 2026.

    Two paychecks' worth of base, two already received -- so the very first
    projected paycheck must already be boosted."""
    user, account = _seed(db_session, wage_base="17205.52", paychecks_received=2)

    entries = build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 12, 31))
    checks = _paychecks(entries)

    assert checks, "no projected paychecks were produced"
    assert checks[0][1] == NET + BOOST, (
        "paychecks already received must draw the wage base down too"
    )


def test_boost_does_not_depend_on_the_forecast_window_start(db_session):
    """The wage base is a calendar-year quantity, so paychecks already received
    this year must count no matter where the requested window starts.

    Scoping the drawdown to the window made /forecast/risk (today..+90, which
    sees no prior paychecks) disagree with /forecast/quarters (Jan..Dec) by the
    boost amount on every paycheck -- putting a false at-risk banner above a
    chart whose trough on that very day was comfortably positive. Live on
    2026-08-12: -$230.23 vs +$1,083.14 for the same date."""
    user, account = _seed(db_session, "ss_window", wage_base="17205.52", paychecks_received=2)

    from_january = build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 12, 31))
    from_midyear = build_forecast(db_session, user.id, account.id, date(2026, 4, 1), date(2026, 12, 31))

    jan_amounts = {d: a for d, a in _paychecks(from_january) if d >= date(2026, 4, 1)}
    mid_amounts = dict(_paychecks(from_midyear))

    assert jan_amounts, "no projected paychecks in the overlap"
    assert mid_amounts == jan_amounts, (
        "a window starting mid-year must see the same boosted paychecks as a "
        "Jan-anchored one"
    )


def test_bonus_ytd_reduces_the_remaining_base(db_session):
    """Bonus wages are subject to SS too, so a large bonus already paid brings
    the crossing forward. One paycheck of gross of headroom left after the
    bonus means the boost lands on the second paycheck. Headroom is set just
    OVER one gross paycheck: the engine boosts the paycheck that crosses the
    base, so exactly-one-paycheck of headroom would boost the first."""
    user, account = _seed(db_session, wage_base="17205.53", bonus_ytd="8602.76")

    entries = build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 5, 31))
    checks = _paychecks(entries)

    assert len(checks) >= 2
    assert checks[0][1] == NET
    assert checks[1][1] == NET + BOOST


def test_no_boost_without_ss_settings(db_session):
    """The whole feature stays off unless both SS fields are populated, so
    users who never fill them in see plain paychecks."""
    user = models.User(username="nossconf", hashed_password="x", display_name="NoSS")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("10000.00"),
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=NET, type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 12, 31))

    assert all(amt == NET for _, amt in _paychecks(entries))


def test_incidental_recurring_income_is_not_treated_as_a_paycheck(db_session):
    """A smoothed bonus twelfth or small rental inflow is far below gross and
    must not draw the wage base down or collect a boost. Dan's "Bonus (1/12)"
    is 1599.04 against 8602.76 gross -- a ratio of 0.19."""
    user, account = _seed(db_session, wage_base="17205.52")
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Bonus twelfth",
        amount=Decimal("1599.04"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 1, 1), date(2026, 6, 30))
    bonuses = [
        t.amount for e in entries for t in e.transactions
        if t.name == "Bonus twelfth" and not t.is_actual
    ]

    assert bonuses, "no projected bonus twelfths were produced"
    assert all(b == Decimal("1599.04") for b in bonuses), "incidental income must never be boosted"
