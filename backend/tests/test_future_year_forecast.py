from datetime import date, timedelta
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast, build_quarters


def _seed(db):
    user = models.User(username="fy", hashed_password="x", display_name="FY")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                          current_balance=Decimal("5000.00"))
    db.add(acct); db.flush()
    db.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Pay", amount=Decimal("3000.00"),
        type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2020, 1, 1), is_active=True))
    db.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Rent", amount=Decimal("2000.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=5, start_date=date(2020, 1, 1), is_active=True))
    db.commit()
    return user, acct


def test_a_future_window_carries_in_the_intervening_months(db_session):
    """Opening at today's balance would discard everything between now and the
    window, so next January started at a figure December never reached."""
    user, acct = _seed(db_session)
    today = date.today()
    next_year = today.year + 1

    this_year = build_quarters(db_session, user.id, acct.id, today.year)
    nxt = build_quarters(db_session, user.id, acct.id, next_year)

    assert nxt, "future year produced no quarters"
    assert nxt[0].open_balance == this_year[-1].close_balance


def test_years_join_without_a_step(db_session):
    user, acct = _seed(db_session)
    y = date.today().year
    years = [build_quarters(db_session, user.id, acct.id, y + i) for i in range(3)]
    for earlier, later in zip(years, years[1:]):
        assert later[0].open_balance == earlier[-1].close_balance


def test_single_year_and_multi_year_agree_on_the_same_year(db_session):
    """Two screens showing the same year must not disagree about it. Walked in
    isolation a future year drifted from the same year inside a longer span."""
    user, acct = _seed(db_session)
    y = date.today().year
    span = build_forecast(db_session, user.id, acct.id,
                          date(y, 1, 1), date(y + 2, 12, 31))
    for target in (y + 1, y + 2):
        alone = build_quarters(db_session, user.id, acct.id, target)
        shared = build_quarters(db_session, user.id, acct.id, target, precomputed_days=span)
        assert [q.close_balance for q in alone] == [q.close_balance for q in shared]


def test_the_current_year_is_unaffected(db_session):
    """The common path must keep anchoring to the real balance."""
    user, acct = _seed(db_session)
    today = date.today()
    rows = build_forecast(db_session, user.id, acct.id, today, today + timedelta(days=1))
    assert rows[0].projected_balance is not None
    qs = build_quarters(db_session, user.id, acct.id, today.year)
    assert len(qs) == 4
