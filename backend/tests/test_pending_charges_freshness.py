from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import credit_cards as credit_cards_router_module
from backend.dependencies import get_db, get_current_user


@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    card = models.CreditCard(
        user_id=user.id, name="Chase", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25, pending_charges=Decimal("0"),
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    app = FastAPI()
    app.include_router(credit_cards_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, card


def test_patching_pending_charges_stamps_the_freshness_timestamp(client, db_session):
    test_client, user, card = client
    assert card.pending_charges_updated_at is None

    resp = test_client.patch(f"/credit-cards/{card.id}", json={"pending_charges": "134.31"})
    assert resp.status_code == 200
    assert resp.json()["pending_charges_updated_at"] is not None

    db_session.refresh(card)
    assert card.pending_charges_updated_at is not None


def test_patching_pending_charges_back_to_zero_clears_the_timestamp(client, db_session):
    test_client, user, card = client
    card.pending_charges = Decimal("134.31")
    from datetime import datetime
    card.pending_charges_updated_at = datetime.utcnow()
    db_session.commit()

    resp = test_client.patch(f"/credit-cards/{card.id}", json={"pending_charges": "0"})
    assert resp.status_code == 200
    assert resp.json()["pending_charges_updated_at"] is None

    db_session.refresh(card)
    assert card.pending_charges_updated_at is None


def test_patching_an_unrelated_field_does_not_stamp_pending_charges(client, db_session):
    test_client, user, card = client
    resp = test_client.patch(f"/credit-cards/{card.id}", json={"notes": "updated"})
    assert resp.status_code == 200

    db_session.refresh(card)
    assert card.pending_charges_updated_at is None


def test_creating_a_card_with_pending_charges_stamps_the_freshness_timestamp(client, db_session):
    """create_card previously never called _stamp_pending_charges_freshness,
    so a card created with pending_charges > 0 in the request body was
    permanently treated as stale by the forecast until a later PATCH."""
    test_client, user, _card = client
    resp = test_client.post("/credit-cards", json={
        "name": "Amex",
        "credit_limit": "15000.00",
        "statement_day": 10,
        "due_day": 5,
        "pending_charges": "134.31",
    })
    assert resp.status_code == 201
    assert resp.json()["pending_charges_updated_at"] is not None

    card = db_session.query(models.CreditCard).filter_by(name="Amex").one()
    assert card.pending_charges_updated_at is not None


def test_creating_a_card_with_no_pending_charges_leaves_the_timestamp_null(client, db_session):
    test_client, user, _card = client
    resp = test_client.post("/credit-cards", json={
        "name": "Discover",
        "credit_limit": "4000.00",
        "statement_day": 12,
        "due_day": 3,
    })
    assert resp.status_code == 201
    assert resp.json()["pending_charges_updated_at"] is None

    card = db_session.query(models.CreditCard).filter_by(name="Discover").one()
    assert card.pending_charges_updated_at is None


def test_repatching_the_same_pending_charges_value_does_not_restamp(client, db_session):
    """Re-sending the same value (a no-op edit) is not a fresh signal --
    only a real change updates the timestamp."""
    test_client, user, card = client
    card.pending_charges = Decimal("134.31")
    from datetime import datetime, timedelta
    old_stamp = datetime.utcnow() - timedelta(days=3)
    card.pending_charges_updated_at = old_stamp
    db_session.commit()

    resp = test_client.patch(f"/credit-cards/{card.id}", json={"pending_charges": "134.31"})
    assert resp.status_code == 200

    db_session.refresh(card)
    assert abs((card.pending_charges_updated_at - old_stamp).total_seconds()) < 1
