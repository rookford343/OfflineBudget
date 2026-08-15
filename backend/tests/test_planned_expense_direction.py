"""PlannedExpense.direction -- one-off events can be money coming IN.

Before `direction`, the forecast forced every planned event negative
(`signed = -abs(pe.amount)`), so a known one-off inflow had nowhere to live:
Dan's spreadsheet forecast carries the April bonus (+$38,347.92 on 4/15),
Airbnb money from family (+$1,300 on 7/21), and eBay payouts as explicit rows,
none of which the app could represent.
"""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast


def _seed(db, username: str):
    user = models.User(username=username, hashed_password="x", display_name="PE")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.commit()
    return user, account


def _balance_on(entries, d: date) -> Decimal:
    return next(e.projected_balance for e in entries if e.date == d)


def test_outflow_is_the_default_and_subtracts(db_session):
    """Existing rows carry no explicit direction, so the default must keep
    behaving exactly as before."""
    user, account = _seed(db_session, "pe_out")
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=account.id, name="Vacation",
        amount=Decimal("917.04"), expected_date=date(2026, 9, 15),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 9, 14), date(2026, 9, 16))

    assert _balance_on(entries, date(2026, 9, 15)) == Decimal("82.96")  # 1000 - 917.04


def test_inflow_adds_instead_of_subtracting(db_session):
    user, account = _seed(db_session, "pe_in")
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=account.id, name="Bonus",
        amount=Decimal("38347.92"), expected_date=date(2026, 4, 15),
        direction=models.PlannedDirection.inflow,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 4, 14), date(2026, 4, 16))

    assert _balance_on(entries, date(2026, 4, 15)) == Decimal("39347.92")  # 1000 + 38347.92


def test_inflow_is_reported_as_income_with_a_positive_amount(db_session):
    """The Forecast page colours and labels rows off these fields, and the
    quarter income/expense totals are derived from the sign."""
    user, account = _seed(db_session, "pe_in_shape")
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=account.id, name="Airbnb from Mom",
        amount=Decimal("1300.00"), expected_date=date(2026, 7, 21),
        direction=models.PlannedDirection.inflow,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 7, 21), date(2026, 7, 21))
    txns = entries[0].transactions

    assert len(txns) == 1
    assert txns[0].amount == Decimal("1300.00")
    assert txns[0].type == "income"
    assert txns[0].is_planned is True
    assert txns[0].is_actual is False


def test_direction_wins_over_a_stored_negative_amount(db_session):
    """Amounts are re-signed from `direction`, not trusted as stored, so an
    inflow entered as a negative number still reads as money in."""
    user, account = _seed(db_session, "pe_neg")
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=account.id, name="Refund",
        amount=Decimal("-500.00"), expected_date=date(2026, 5, 10),
        direction=models.PlannedDirection.inflow,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 5, 10), date(2026, 5, 10))

    assert _balance_on(entries, date(2026, 5, 10)) == Decimal("1500.00")
