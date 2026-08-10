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
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
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


def test_patch_updates_start_date(client, db_session):
    """Regression: RecurringUpdate was missing start_date entirely, so a
    PATCH silently no-opped on it -- e.g. rescheduling a planned purchase
    (the Rivian R2 down payment) to a future start date reverted to the
    item's original creation date, and the forecast kept including it
    starting from day one instead of the real target date."""
    test_client, user, checking = client
    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Rivian R2",
        amount=Decimal("500.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=17,
        start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    resp = test_client.patch(f"/recurring/{item.id}", json={"start_date": "2026-09-15"})
    assert resp.status_code == 200
    assert resp.json()["start_date"] == "2026-09-15"

    resp = test_client.get(f"/recurring/{item.id}")
    assert resp.json()["start_date"] == "2026-09-15"
