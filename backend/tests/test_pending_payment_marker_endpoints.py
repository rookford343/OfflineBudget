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
        statement_day=28, due_day=25, balance_due=Decimal("9098.94"),
        current_balance=Decimal("9098.94"),
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    app = FastAPI()
    app.include_router(credit_cards_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, card


def test_mark_payment_sent_snapshots_balance_due(client, db_session):
    test_client, user, card = client

    resp = test_client.post(f"/credit-cards/{card.id}/mark-payment-sent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["payment_sent_pending_sync"] is True
    assert Decimal(str(body["payment_sent_amount"])) == Decimal("9098.94")

    db_session.refresh(card)
    assert card.payment_sent_pending_sync is True
    assert card.payment_sent_amount == Decimal("9098.94")


def test_mark_payment_sent_rejects_zero_balance_due(client, db_session):
    test_client, user, card = client
    card.balance_due = Decimal("0")
    db_session.commit()

    resp = test_client.post(f"/credit-cards/{card.id}/mark-payment-sent")
    assert resp.status_code == 400


def test_mark_payment_sent_rejects_already_pending(client, db_session):
    test_client, user, card = client
    card.payment_sent_pending_sync = True
    card.payment_sent_amount = Decimal("9098.94")
    db_session.commit()

    resp = test_client.post(f"/credit-cards/{card.id}/mark-payment-sent")
    assert resp.status_code == 400


def test_clear_payment_sent(client, db_session):
    test_client, user, card = client
    card.payment_sent_pending_sync = True
    card.payment_sent_amount = Decimal("9098.94")
    db_session.commit()

    resp = test_client.post(f"/credit-cards/{card.id}/clear-payment-sent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["payment_sent_pending_sync"] is False
    assert body["payment_sent_amount"] is None

    db_session.refresh(card)
    assert card.payment_sent_pending_sync is False
    assert card.payment_sent_amount is None
