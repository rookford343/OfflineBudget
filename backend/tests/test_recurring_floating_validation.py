"""is_floating is only meaningful for an expense item that fires exactly
once a month -- the checking/card matchers and the skip endpoint all
assume that shape. The frontend form gates the checkbox to
type=expense/frequency=monthly, but nothing at the API stopped a direct
call from setting is_floating=True on an income item or a
credit_card_payment-type item, or on a weekly/quarterly/yearly item.
schemas.RecurringCreate's model_validator and routers/recurring.py's
update_recurring (RecurringUpdate is partial, so it validates the MERGED
state) both reject that combination now."""
from datetime import date
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import recurring as recurring_router_module
from backend.dependencies import get_db, get_current_user

D = Decimal


@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="the user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(checking)
    db_session.commit()
    db_session.refresh(checking)

    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, checking


def _base_body(account_id: int, **overrides) -> dict:
    body = dict(
        name="Test Item", amount="45.00", type="expense", frequency="monthly",
        account_id=account_id, day_of_month=15, start_date="2026-01-01",
        is_floating=True,
    )
    body.update(overrides)
    return body


def test_create_rejects_floating_income(client):
    test_client, _user, checking = client
    resp = test_client.post("/recurring", json=_base_body(checking.id, type="income"))
    assert resp.status_code == 422


def test_create_rejects_floating_credit_card_payment(client):
    test_client, _user, checking = client
    resp = test_client.post("/recurring", json=_base_body(checking.id, type="credit_card_payment"))
    assert resp.status_code == 422


def test_create_rejects_floating_quarterly(client):
    test_client, _user, checking = client
    resp = test_client.post("/recurring", json=_base_body(checking.id, frequency="quarterly", month_of_year=1))
    assert resp.status_code == 422


def test_create_rejects_floating_yearly(client):
    test_client, _user, checking = client
    resp = test_client.post("/recurring", json=_base_body(checking.id, frequency="yearly", month_of_year=1))
    assert resp.status_code == 422


def test_create_accepts_floating_monthly_expense(client):
    test_client, _user, checking = client
    resp = test_client.post("/recurring", json=_base_body(checking.id))
    assert resp.status_code == 201
    assert resp.json()["is_floating"] is True


def test_update_rejects_turning_floating_on_for_an_income_item(client, db_session):
    test_client, user, checking = client
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Paycheck",
        amount=D("3000.00"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    resp = test_client.patch(f"/recurring/{item.id}", json={"is_floating": True})
    assert resp.status_code == 422
    db_session.refresh(item)
    assert item.is_floating is False


def test_update_rejects_changing_frequency_on_an_already_floating_item(client, db_session):
    """RecurringUpdate is partial -- this PATCH doesn't even mention
    is_floating, so the check must read the item's CURRENT is_floating
    (True) merged with this PATCH's new frequency, not just the fields the
    PATCH itself carries."""
    test_client, user, checking = client
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Cleaning Co",
        amount=D("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    resp = test_client.patch(f"/recurring/{item.id}", json={"frequency": "quarterly", "month_of_year": 1})
    assert resp.status_code == 422
    db_session.refresh(item)
    assert item.frequency == models.RecurringFrequency.monthly


def test_update_accepts_turning_floating_on_for_an_eligible_expense(client, db_session):
    test_client, user, checking = client
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Cleaning Co",
        amount=D("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=False,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    resp = test_client.patch(f"/recurring/{item.id}", json={"is_floating": True})
    assert resp.status_code == 200
    assert resp.json()["is_floating"] is True
