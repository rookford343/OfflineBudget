from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import household_members as household_members_router_module


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
    app.include_router(household_members_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, checking


def test_create_and_list_household_member(client):
    test_client, user, checking = client

    r = test_client.post("/household-members", json={"name": "Test Member"})
    assert r.status_code == 201
    member_id = r.json()["id"]

    r2 = test_client.get("/household-members")
    assert any(m["id"] == member_id for m in r2.json())


def test_duplicate_name_rejected(client):
    test_client, user, checking = client

    test_client.post("/household-members", json={"name": "Test Member"})
    r = test_client.post("/household-members", json={"name": "Test Member"})
    assert r.status_code == 400


def test_recurring_item_owner_id_defaults_null(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    assert item.owner_id is None


def test_delete_blocked_while_referenced_by_recurring_item(client, db_session):
    """Mirrors categories.py's delete_category sub-category guard (400, not a
    raw FK-constraint 500) -- applied to the one FK relationship categories.py
    itself doesn't guard: RecurringItem.owner_id."""
    test_client, user, checking = client

    r = test_client.post("/household-members", json={"name": "Spouse"})
    member_id = r.json()["id"]

    item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Spouse's Car Payment",
        amount=Decimal("350.00"), type=models.RecurringType.expense,
        day_of_month=1, start_date=date(2026, 1, 1), owner_id=member_id,
    )
    db_session.add(item)
    db_session.commit()

    r2 = test_client.delete(f"/household-members/{member_id}")
    assert r2.status_code == 400
    assert r2.json()["detail"] == "Cannot delete a household member referenced by recurring items"

    # Still there -- the blocked delete must not have removed it.
    r3 = test_client.get("/household-members")
    assert any(m["id"] == member_id for m in r3.json())


def test_delete_unreferenced_household_member_succeeds(client):
    test_client, user, checking = client

    r = test_client.post("/household-members", json={"name": "Kid"})
    member_id = r.json()["id"]

    r2 = test_client.delete(f"/household-members/{member_id}")
    assert r2.status_code == 204

    r3 = test_client.get("/household-members")
    assert not any(m["id"] == member_id for m in r3.json())
