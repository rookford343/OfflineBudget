"""Bonuses in the day-by-day forecast: the plan's net for that year lands on
the payout date, and the gross counts toward the Social Security wage base.
All figures are made up."""
from datetime import date
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
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 12, 31))
    assert _lines(entries, bonus.id) == [(date(2027, 4, 15), Decimal("4200.00") + (Decimal("6000") * Decimal("0.062")).quantize(Decimal("0.01")))]


def test_bonus_gross_pulls_the_ss_crossing_earlier(db_session):
    """Wage base = 3 paychecks + the bonus. The Jan-Mar paychecks and the
    April 10 bonus use it up exactly, so April 20's paycheck is the first
    boosted one. Without counting the bonus, the boost would not start until
    several paychecks later."""
    base = GROSS_PAY * 3 + Decimal("20000")
    user, acct, pay, _ = _seed(db_session, wage_base=str(base), day=10, pay_day=20)
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 6, 30))
    checks = _lines(entries, pay.id)
    assert [amt for _, amt in checks[:3]] == [NET_PAY] * 3
    assert checks[3][1] == NET_PAY + BOOST   # April 20, after the Apr 9 (Friday) bonus used the rest of the base
    assert checks[4][1] == NET_PAY + BOOST


def test_a_bonus_that_crosses_the_base_gets_a_partial_boost(db_session):
    base = GROSS_PAY * 3 + Decimal("5000")   # 15,000 of the 20,000 bonus is above the base
    user, acct, _, bonus = _seed(db_session, wage_base=str(base), day=10, pay_day=20)
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 6, 30))
    [(_, amt)] = _lines(entries, bonus.id)
    assert amt == Decimal("14000.00") + (Decimal("15000") * Decimal("0.062")).quantize(Decimal("0.01"))
