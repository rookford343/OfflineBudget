from datetime import date, timedelta
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import forecast as forecast_router_module
from backend.dependencies import get_db, get_current_user


@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("1000.00"))
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("30000.00"))
    db_session.add_all([checking, savings])
    db_session.commit()
    db_session.refresh(checking)

    app = FastAPI()
    app.include_router(forecast_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, checking


def test_risk_response_includes_suggestion_when_at_risk(client):
    test_client, user, checking = client
    db = test_client.app.dependency_overrides[get_db]()
    db.add(models.PlannedExpense(
        user_id=user.id, name="Big Expense", amount=Decimal("5000.00"),
        expected_date=date.today() + timedelta(days=10),
    ))
    db.commit()

    resp = test_client.get("/forecast/risk", params={"account_id": checking.id, "days": 90})

    assert resp.status_code == 200
    body = resp.json()
    assert body["at_risk"] is True
    assert body["suggested_transfer_amount"] is not None
    assert body["suggested_transfer_already_planned"] is False


def test_risk_response_has_no_suggestion_when_not_at_risk(client):
    test_client, user, checking = client

    resp = test_client.get("/forecast/risk", params={"account_id": checking.id, "days": 90})

    assert resp.status_code == 200
    body = resp.json()
    assert body["at_risk"] is False
    assert body["suggested_transfer_amount"] is None
