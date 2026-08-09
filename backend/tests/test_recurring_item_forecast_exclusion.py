from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast
from backend.services.budget_snapshot import _monthly_income


def test_include_in_forecast_false_excludes_item_from_cash_forecast(db_session):
    """Reproduces a live request (2026-08-09): a recurring item can represent
    real annual income (e.g. an end-of-year bonus, modeled as 1/12th per
    month for budget-planning purposes) that Dan considers already spoken
    for -- allocated to spending categories or savings the moment it lands
    -- so it should count toward monthly budget totals but never show up as
    projected checking-account cash in the day-by-day forecast.
    include_in_forecast=False (default True, so every other item is
    unaffected) achieves exactly that split."""
    user = models.User(username="forecastexcl", hashed_password="x", display_name="ForecastExcl")
    db_session.add(user)
    db_session.flush()

    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    db_session.add(checking)
    db_session.flush()

    bonus = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Bonus (1/12)", amount=Decimal("1599.04"),
        type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1), include_in_forecast=False,
    )
    db_session.add(bonus)
    db_session.commit()

    # Still counts toward monthly budget income -- unaffected by the flag.
    assert _monthly_income(db_session, user.id) == Decimal("1599.04")

    # Never appears as projected cash in the forecast walk.
    entries = build_forecast(db_session, user.id, checking.id, date(2026, 1, 1), date(2026, 1, 31))
    all_names = [t.name for e in entries for t in e.transactions]
    assert "Bonus (1/12)" not in all_names
    assert entries[-1].projected_balance == checking.current_balance


def test_include_in_forecast_defaults_true_for_every_other_item(db_session):
    """Every recurring item created before this flag existed -- and every
    new one that doesn't explicitly opt out -- must keep showing up in the
    forecast exactly as before."""
    user = models.User(username="forecastdefault", hashed_password="x", display_name="ForecastDefault")
    db_session.add(user)
    db_session.flush()

    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db_session.add(checking)
    db_session.flush()

    rent = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Rent", amount=Decimal("500.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
    )
    db_session.add(rent)
    db_session.commit()
    assert rent.include_in_forecast is True

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 1, 1), date(2026, 1, 31))
    all_names = [t.name for e in entries for t in e.transactions]
    assert "Rent" in all_names
