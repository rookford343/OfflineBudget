"""pending_amount / pending_amount_effective_date on RecurringItem -- lets the
user schedule a recurring item's future amount change today (e.g. a mortgage
payment dropping after an escrow re-analysis) without it retroactively
applying to months before the change takes effect. This task adds just the
two fields plus both-or-neither validation; Task 2/3 make the forecast engine
and a scheduler sweep read them, Task 4 adds the frontend UI.

This repo wires auth via a get_current_user dependency override rather than a
bearer-token scheme (see test_recurring_breakdown_account.py) -- auth_headers
below is an empty placeholder kept only so the call shape matches other
router test files; no real header is required.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import recurring as recurring_router_module

D = Decimal


@pytest.fixture()
def client(db_session, test_user):
    app = FastAPI()
    app.include_router(recurring_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: test_user
    return TestClient(app)


@pytest.fixture()
def auth_headers():
    return {}


def _world(db):
    user = models.User(username="pendingamt", hashed_password="x", display_name="PendingAmt")
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=D("1000.00"),
    )
    db.add(checking)
    db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Mortgage", amount=D("2200.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
    )
    db.add(item)
    db.commit()
    return user, checking, item


def test_pending_fields_default_to_none(db_session):
    _, _, item = _world(db_session)
    assert item.pending_amount is None and item.pending_amount_effective_date is None


def test_create_rejects_a_half_entered_pair(client, auth_headers, test_account):
    body = {
        "name": "Half Entered", "amount": "100.00", "type": "expense", "frequency": "monthly",
        "account_id": test_account.id, "day_of_month": 1, "start_date": "2026-01-01",
        "pending_amount": "90.00",
    }
    r = client.post("/recurring", json=body, headers=auth_headers)
    assert r.status_code == 422


def test_create_accepts_a_complete_pair(client, auth_headers, test_account):
    body = {
        "name": "Complete Pair", "amount": "2200.00", "type": "expense", "frequency": "monthly",
        "account_id": test_account.id, "day_of_month": 1, "start_date": "2026-01-01",
        "pending_amount": "1950.00", "pending_amount_effective_date": "2027-01-01",
    }
    r = client.post("/recurring", json=body, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["pending_amount"] == "1950.00"
    assert r.json()["pending_amount_effective_date"] == "2027-01-01"


def test_update_rejects_a_half_entered_pair(client, auth_headers, db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item", amount=D("100.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    r = client.patch(f"/recurring/{item.id}", json={"pending_amount": "90.00"}, headers=auth_headers)
    assert r.status_code == 422


def test_breakdown_is_unaffected_by_a_future_pending_change(client, auth_headers, db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Mortgage", amount=D("2200.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
        pending_amount=D("1950.00"), pending_amount_effective_date=date(2027, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    r = client.get("/recurring/breakdown", headers=auth_headers)
    row = next(
        i for g in r.json()["by_category"] for i in (g["items"] or [it for c in g["categories"] for it in c["items"]])
        if i["id"] == item.id
    )
    assert row["amount"] == "2200.00"


def test_update_can_clear_a_scheduled_change(client, auth_headers, db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item", amount=D("100.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
        pending_amount=D("90.00"), pending_amount_effective_date=date(2027, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    r = client.patch(
        f"/recurring/{item.id}", json={"pending_amount": None, "pending_amount_effective_date": None},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["pending_amount"] is None and r.json()["pending_amount_effective_date"] is None
