"""PlannedExpense.direction -- one-off events can be money coming IN.

Before `direction`, the forecast forced every planned event negative
(`signed = -abs(pe.amount)`), so a known one-off inflow had nowhere to live:
the user's spreadsheet forecast carries the April bonus (+$33,362.69 on 4/15),
Airbnb money from family (+$1,300 on 7/21), and eBay payouts as explicit rows,
none of which the app could represent.
"""
import pytest
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
        amount=Decimal("798.25"), expected_date=date(2026, 9, 15),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 9, 14), date(2026, 9, 16))

    assert _balance_on(entries, date(2026, 9, 15)) == Decimal("201.75")  # 1000 - 798.25


@pytest.mark.parametrize("name,amount,on,start,expected", [
    pytest.param("Bonus", "33362.69", date(2026, 4, 15), date(2026, 4, 14), "34362.69", id="inflow_adds"),
    # Amounts are re-signed from `direction`, not trusted as stored, so an
    # inflow entered as a negative number still reads as money in.
    pytest.param("Refund", "-500.00", date(2026, 5, 10), date(2026, 5, 10), "1500.00", id="direction_wins_over_stored_sign"),
])
def test_inflow_adds_to_the_balance(db_session, name, amount, on, start, expected):
    user, account = _seed(db_session, f"pe_{name.lower()}")
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=account.id, name=name,
        amount=Decimal(amount), expected_date=on,
        direction=models.PlannedDirection.inflow,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, start, on + (on - start))

    assert _balance_on(entries, on) == Decimal(expected)


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

