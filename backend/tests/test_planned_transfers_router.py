from datetime import date
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import planned_transfers as planned_transfers_router_module
from backend.dependencies import get_db, get_current_user


@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db_session.add_all([checking, savings])
    db_session.commit()
    db_session.refresh(checking)
    db_session.refresh(savings)

    app = FastAPI()
    app.include_router(planned_transfers_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, checking, savings


def test_create_and_list_planned_transfer(client):
    test_client, user, checking, savings = client

    resp = test_client.post("/planned-transfers", json={
        "from_account_id": savings.id, "to_account_id": checking.id,
        "amount": "22000.00", "target_date": "2026-09-12",
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"

    resp = test_client.get("/planned-transfers")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_create_rejects_account_owned_by_another_user(db_session, client):
    test_client, user, checking, savings = client
    other = models.User(username="mallory", hashed_password="x", display_name="Mallory")
    db_session.add(other)
    db_session.commit()
    other_account = models.Account(user_id=other.id, name="Mallory Checking", type=models.AccountType.checking)
    db_session.add(other_account)
    db_session.commit()
    db_session.refresh(other_account)

    resp = test_client.post("/planned-transfers", json={
        "to_account_id": other_account.id, "amount": "1000.00", "target_date": "2026-09-12",
    })
    assert resp.status_code == 404


def test_create_rejects_from_account_same_as_to_account(client):
    test_client, user, checking, savings = client

    resp = test_client.post("/planned-transfers", json={
        "from_account_id": checking.id, "to_account_id": checking.id,
        "amount": "1000.00", "target_date": "2026-09-12",
    })
    assert resp.status_code == 422


def test_update_rejects_from_account_same_as_to_account(client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "from_account_id": savings.id, "to_account_id": checking.id,
        "amount": "1000.00", "target_date": "2026-09-12",
    }).json()

    resp = test_client.patch(f"/planned-transfers/{created['id']}", json={"from_account_id": checking.id})
    assert resp.status_code == 422


def test_update_planned_transfer(client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()

    resp = test_client.patch(f"/planned-transfers/{created['id']}", json={"amount": "1500.00"})
    assert resp.status_code == 200
    assert resp.json()["amount"] == "1500.00"


def test_patch_cannot_change_status(client):
    """The general PATCH must not be a back door around mark-scheduled.

    Allowing an arbitrary transition (notably verified -> pending) would
    silently re-enable forecast injection for a transfer whose real
    transaction is already sitting in actuals, double-counting it.
    """
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()
    test_client.post(f"/planned-transfers/{created['id']}/mark-scheduled")

    resp = test_client.patch(f"/planned-transfers/{created['id']}", json={"status": "pending"})

    assert resp.status_code in (200, 422)
    after = test_client.get("/planned-transfers").json()[0]
    assert after["status"] == "scheduled"


def test_patch_ignoring_status_still_applies_other_fields(client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()
    test_client.post(f"/planned-transfers/{created['id']}/mark-scheduled")

    resp = test_client.patch(
        f"/planned-transfers/{created['id']}",
        json={"status": "pending", "amount": "1750.00"},
    )

    assert resp.status_code == 200
    assert resp.json()["amount"] == "1750.00"
    assert resp.json()["status"] == "scheduled"


def test_create_accepts_and_persists_the_suggested_flag(client):
    test_client, user, checking, savings = client

    resp = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00",
        "target_date": "2026-09-12", "suggested": True,
    })

    assert resp.status_code == 201
    assert resp.json()["suggested"] is True
    assert test_client.get("/planned-transfers").json()[0]["suggested"] is True


def test_create_defaults_suggested_to_false(client):
    test_client, user, checking, savings = client

    resp = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    })

    assert resp.status_code == 201
    assert resp.json()["suggested"] is False


@pytest.mark.parametrize("amount", ["0", "-500.00"])
def test_create_rejects_non_positive_amount(client, amount):
    """A non-positive amount inverts the forecast injection on both accounts."""
    test_client, user, checking, savings = client

    resp = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": amount, "target_date": "2026-09-12",
    })

    assert resp.status_code == 422


@pytest.mark.parametrize("amount", ["0", "-500.00"])
def test_update_rejects_non_positive_amount(client, amount):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()

    resp = test_client.patch(f"/planned-transfers/{created['id']}", json={"amount": amount})

    assert resp.status_code == 422


def test_mark_scheduled_transitions_pending_to_scheduled(client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()

    resp = test_client.post(f"/planned-transfers/{created['id']}/mark-scheduled")
    assert resp.status_code == 200
    assert resp.json()["status"] == "scheduled"


def test_mark_scheduled_rejects_already_scheduled(client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()
    test_client.post(f"/planned-transfers/{created['id']}/mark-scheduled")

    resp = test_client.post(f"/planned-transfers/{created['id']}/mark-scheduled")
    assert resp.status_code == 400


def test_delete_planned_transfer(client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()

    resp = test_client.delete(f"/planned-transfers/{created['id']}")
    assert resp.status_code == 204
    assert test_client.get("/planned-transfers").json() == []


def test_cross_user_delete_is_rejected(db_session, client):
    test_client, user, checking, savings = client
    created = test_client.post("/planned-transfers", json={
        "to_account_id": checking.id, "amount": "1000.00", "target_date": "2026-09-12",
    }).json()

    other = models.User(username="mallory2", hashed_password="x", display_name="Mallory2")
    db_session.add(other)
    db_session.commit()
    app = FastAPI()
    app.include_router(planned_transfers_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: other
    other_client = TestClient(app)

    resp = other_client.delete(f"/planned-transfers/{created['id']}")
    assert resp.status_code == 404
