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
from backend.services.forecast_engine import build_forecast

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


# Task 2: build_forecast resolves the scheduled amount change by occurrence date.
#
# ForecastTransaction.amount is signed (confirmed against test_checking_level.py's
# sweep/inflow assertions and by running build_forecast directly against this
# fixture before writing these assertions): an expense's occurrence amount comes
# back negative. _amount_on below returns that signed value as-is, so a
# "Test Mortgage" expense of $2,200.00/mo appears as Decimal("-2200.00"), not
# Decimal("2200.00").

def _mortgage_world(db, pending_amount=None, effective_date=None):
    user = models.User(username="forecastpending", hashed_password="x", display_name="ForecastPending")
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=D("10000.00"),
    )
    db.add(checking)
    db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Mortgage", amount=D("2200.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1),
        pending_amount=pending_amount, pending_amount_effective_date=effective_date,
    )
    db.add(item)
    db.commit()
    return user, checking, item


def _amount_on(entries, name, on_day):
    for e in entries:
        if e.date == on_day:
            for t in e.transactions:
                if t.name == name:
                    return t.amount
    return None


def test_pre_effective_occurrence_keeps_the_old_amount(db_session):
    user, checking, _ = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    entries = build_forecast(db_session, user.id, checking.id, date(2026, 12, 1), date(2026, 12, 31))
    assert _amount_on(entries, "Test Mortgage", date(2026, 12, 1)) == D("-2200.00")


def test_on_and_after_effective_occurrence_uses_the_new_amount(db_session):
    user, checking, _ = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 1, 31))
    assert _amount_on(entries, "Test Mortgage", date(2027, 1, 1)) == D("-1950.00")


def test_no_pending_amount_is_unaffected(db_session):
    user, checking, _ = _mortgage_world(db_session)
    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 1, 31))
    assert _amount_on(entries, "Test Mortgage", date(2027, 1, 1)) == D("-2200.00")


def test_a_confirmed_statement_amount_still_beats_a_pending_change(db_session):
    user, checking, item = _mortgage_world(
        db_session, pending_amount=D("1950.00"), effective_date=date(2027, 1, 1),
    )
    db_session.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id, due_date=date(2027, 1, 1), actual_amount=D("2015.42"),
    ))
    db_session.commit()
    entries = build_forecast(db_session, user.id, checking.id, date(2027, 1, 1), date(2027, 1, 31))
    assert _amount_on(entries, "Test Mortgage", date(2027, 1, 1)) == D("-2015.42")
