from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import spending as spending_router_module
from backend.dependencies import get_db, get_current_user


def _make_user(db_session, username="alice"):
    user = models.User(username=username, hashed_password="x", display_name="Alice")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def client(db_session):
    user = _make_user(db_session)
    app = FastAPI()
    app.include_router(spending_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user


def test_budget_snapshot_returns_200_for_own_account(client, db_session):
    test_client, user = client
    account = models.Account(
        user_id=user.id, name="Main Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db_session.add(account)
    db_session.commit()

    resp = test_client.get(f"/spending/budget-snapshot?account_id={account.id}")

    assert resp.status_code == 200
    assert resp.json()["as_of"] is not None


def test_budget_snapshot_returns_404_for_foreign_account(client, db_session):
    test_client, user = client
    other_user = models.User(username="bob", hashed_password="x", display_name="Bob")
    db_session.add(other_user)
    db_session.flush()
    foreign_account = models.Account(
        user_id=other_user.id, name="Bob's Checking", type=models.AccountType.checking,
        current_balance=Decimal("500.00"),
    )
    db_session.add(foreign_account)
    db_session.commit()

    resp = test_client.get(f"/spending/budget-snapshot?account_id={foreign_account.id}")

    assert resp.status_code == 404


def test_budget_snapshot_returns_404_for_nonexistent_account(client):
    test_client, _user = client

    resp = test_client.get("/spending/budget-snapshot?account_id=999999")

    assert resp.status_code == 404
