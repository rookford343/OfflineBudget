"""POST/DELETE /recurring/{item_id}/skip -- the endpoints the frontend (and
Task 5's status display) use to mark/unmark a floating item's occurrence
'not this month'. Mirrors test_recurring_router.py's local client fixture:
this repo wires auth via a get_current_user dependency override rather than
a bearer-token auth_headers fixture, so no header is needed here either."""
from datetime import date
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import recurring as recurring_router_module
from backend.dependencies import get_db, get_current_user


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


def test_skip_then_unskip(client, db_session):
    test_client, user, checking = client
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    r = test_client.post(f"/recurring/{item.id}/skip", json={"year": 2026, "month": 11})
    assert r.status_code == 201

    # idempotent: creating an existing skip is a no-op, not an error, and
    # must not create a second row (the unique constraint would raise if it
    # tried to commit a duplicate).
    r2 = test_client.post(f"/recurring/{item.id}/skip", json={"year": 2026, "month": 11})
    assert r2.status_code == 201
    assert db_session.query(models.RecurringSkip).filter(
        models.RecurringSkip.recurring_item_id == item.id,
    ).count() == 1

    r3 = test_client.delete(f"/recurring/{item.id}/skip", params={"year": 2026, "month": 11})
    assert r3.status_code == 204
    assert db_session.query(models.RecurringSkip).filter(
        models.RecurringSkip.recurring_item_id == item.id,
    ).count() == 0


@pytest.mark.parametrize("month", [0, 13, -5])
def test_skip_rejects_out_of_range_month(client, db_session, month):
    """RecurringSkipBody.month used to accept any integer -- 0, 13, -5 --
    silently creating a skip row that could never match any real
    (item, year, month) lookup."""
    test_client, user, checking = client
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    r = test_client.post(f"/recurring/{item.id}/skip", json={"year": 2026, "month": month})
    assert r.status_code == 422
    assert db_session.query(models.RecurringSkip).filter(
        models.RecurringSkip.recurring_item_id == item.id,
    ).count() == 0


def test_skip_rejected_for_non_floating_item(client, db_session):
    """RecurringSkip is keyed on (item, year, month) with no day/occurrence
    granularity -- unambiguous only for a floating monthly item (exactly one
    occurrence a month). A non-floating item has a fixed due date an
    override can target instead, so skip_month must reject it rather than
    silently removing whatever occurrence(s) land that month."""
    test_client, user, checking = client
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Test Mortgage Co",
        amount=Decimal("1800.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1), is_floating=False,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    r = test_client.post(f"/recurring/{item.id}/skip", json={"year": 2026, "month": 11})
    assert r.status_code == 400
    assert db_session.query(models.RecurringSkip).filter(
        models.RecurringSkip.recurring_item_id == item.id,
    ).count() == 0
