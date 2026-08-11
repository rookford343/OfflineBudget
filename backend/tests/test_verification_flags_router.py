from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import verification_flags as verification_flags_router_module
from backend.dependencies import get_db, get_current_user


@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    app = FastAPI()
    app.include_router(verification_flags_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user


def test_create_and_list_a_flag(client):
    test_client, user = client
    resp = test_client.post("/verification-flags", json={
        "feature": "household_snapshot",
        "reference_type": "account",
        "reference_id": 3,
        "observed": {"left_to_spend": "-6999.59", "flagged_field": "left_to_spend"},
        "expected_value": 945.85,
        "note": "Spreadsheet says $945.85",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["feature"] == "household_snapshot"
    assert body["status"] == "open"
    assert Decimal(str(body["expected_value"])) == Decimal("945.85")

    resp = test_client.get("/verification-flags")
    listed = resp.json()
    assert len(listed) == 1
    assert listed[0]["note"] == "Spreadsheet says $945.85"


def test_list_filters_by_feature_and_status(client):
    test_client, user = client
    test_client.post("/verification-flags", json={"feature": "forecast", "observed": {"a": 1}})
    test_client.post("/verification-flags", json={"feature": "transactions", "observed": {"b": 2}})

    resp = test_client.get("/verification-flags", params={"feature": "forecast"})
    assert [f["feature"] for f in resp.json()] == ["forecast"]


def test_resolve_sets_status_and_resolved_at(client):
    test_client, user = client
    created = test_client.post("/verification-flags", json={"feature": "transactions", "observed": {"amount": "5.00"}}).json()

    resp = test_client.patch(f"/verification-flags/{created['id']}", json={"status": "resolved"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    assert resp.json()["resolved_at"] is not None

    resp = test_client.get("/verification-flags", params={"status": "open"})
    assert resp.json() == []


def test_a_user_cannot_see_or_resolve_another_users_flag(client, db_session):
    test_client, user = client
    other = models.User(username="other", hashed_password="x", display_name="Other")
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    other_flag = models.VerificationFlag(
        user_id=other.id, feature=models.VerificationFeature.forecast,
        observed_json="{}",
    )
    db_session.add(other_flag)
    db_session.commit()
    db_session.refresh(other_flag)

    resp = test_client.get("/verification-flags")
    assert resp.json() == []

    resp = test_client.patch(f"/verification-flags/{other_flag.id}", json={"status": "resolved"})
    assert resp.status_code == 404
