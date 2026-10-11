"""Pending card transactions: each card sync replaces the card's snapshot of
what the issuer currently lists as pending. A charge that posts drops out of
the pending feed and arrives as a posted transaction, so the snapshot never
needs matching against posted rows and can't duplicate them."""
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import credit_cards as credit_cards_router
from backend.services.bank_sync_service import sync_connection
from backend.services.simplefin_client import SimpleFinTransaction
from tests.test_bank_sync_service import _make_card_connection


def _txn(id_, amount, day, *, pending, description="SHOP"):
    return SimpleFinTransaction(id=id_, posted=datetime(2026, 10, day), amount=Decimal(amount),
                                description=description, pending=pending)


def _sync(db, connection, feed, *, cards_only=False):
    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions",
               return_value=(feed, Decimal("-300.00"), None)) as fetch:
        sync_connection(db, connection, cards_only=cards_only)
    return fetch


def _pending_rows(db, card):
    return sorted(
        (r.external_id, r.amount, r.merchant)
        for r in db.query(models.CardPendingTransaction).filter_by(card_id=card.id)
    )


def test_sync_stores_the_pending_snapshot_as_positive_charges(db_session):
    user, card, connection, link = _make_card_connection(db_session)
    _sync(db_session, connection, [
        _txn("p1", "-40.00", 8, pending=True, description="COFFEE"),
        _txn("p2", "5.00", 8, pending=True, description="REFUND CO"),
    ])
    assert _pending_rows(db_session, card) == [
        ("p1", Decimal("40.00"), "COFFEE"), ("p2", Decimal("-5.00"), "REFUND CO"),
    ]
    db_session.refresh(card)
    assert card.pending_charges == Decimal("35.00")


def test_a_posted_charge_replaces_its_pending_row(db_session):
    """Next sync: p1 posted (new id, no longer pending), p2 still pending,
    p3 is new. The snapshot is exactly the current pending list and the
    posted copy is imported once."""
    user, card, connection, link = _make_card_connection(db_session)
    _sync(db_session, connection, [_txn("p1", "-40.00", 8, pending=True), _txn("p2", "-10.00", 8, pending=True)])
    _sync(db_session, connection, [
        _txn("posted-1", "-40.00", 9, pending=False),
        _txn("p2", "-10.00", 8, pending=True),
        _txn("p3", "-7.00", 9, pending=True),
    ])
    assert [r[0] for r in _pending_rows(db_session, card)] == ["p2", "p3"]
    posted = db_session.query(models.CreditCardTransaction).filter_by(card_id=card.id).all()
    assert [(p.amount, p.date.day) for p in posted] == [(Decimal("40.00"), 9)]
    db_session.refresh(card)
    assert card.pending_charges == Decimal("17.00")


def test_pending_list_emptying_zeroes_the_figure_for_a_card_that_reports_pending(db_session):
    user, card, connection, link = _make_card_connection(db_session)
    _sync(db_session, connection, [_txn("p1", "-40.00", 8, pending=True)])
    _sync(db_session, connection, [])
    assert _pending_rows(db_session, card) == []
    db_session.refresh(card)
    assert card.pending_charges == Decimal("0")


def test_a_card_that_never_reports_pending_keeps_its_hand_typed_figure(db_session):
    user, card, connection, link = _make_card_connection(db_session)
    card.pending_charges = Decimal("116.99")
    db_session.commit()
    _sync(db_session, connection, [])
    db_session.refresh(card)
    assert card.pending_charges == Decimal("116.99")


def test_cards_only_sync_skips_bank_account_links(db_session):
    user, card, connection, card_link = _make_card_connection(db_session)
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                             current_balance=Decimal("100.00"))
    db_session.add(account)
    db_session.flush()
    db_session.add(models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="acc-1",
        simplefin_account_name="Checking", local_account_id=account.id,
    ))
    db_session.commit()
    fetch = _sync(db_session, connection, [], cards_only=True)
    assert [c.args[1] for c in fetch.call_args_list] == ["card-1"]


def test_pending_endpoint_lists_only_the_users_rows(db_session):
    user, card, connection, link = _make_card_connection(db_session)
    _sync(db_session, connection, [_txn("p1", "-40.00", 8, pending=True, description="COFFEE")])
    other, other_card, other_conn, _ = _make_card_connection(db_session, username="other")
    _sync(db_session, other_conn, [_txn("x1", "-99.00", 8, pending=True)])

    app = FastAPI()
    app.include_router(credit_cards_router.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    rows = TestClient(app).get("/credit-cards/pending-transactions").json()
    assert [(r["merchant"], r["amount"], r["card_id"]) for r in rows] == [("COFFEE", "40.00", card.id)]
