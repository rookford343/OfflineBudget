import base64
from decimal import Decimal
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from backend import models
from backend.routers import bank_sync as bank_sync_router_module
from backend.dependencies import get_db, get_current_user
from backend.services import crypto
from backend.services.simplefin_client import SimpleFinAccount


@pytest.fixture()
def client(db_session, monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user


def test_connect_stores_encrypted_token_and_returns_accounts(client, db_session):
    test_client, user = client
    claim_url = "https://bridge.simplefin.org/simplefin/claim/abc"
    setup_token = base64.b64encode(claim_url.encode()).decode()

    with patch("backend.routers.bank_sync.claim_setup_token", return_value="https://u:p@bridge.simplefin.org/simplefin"), \
         patch("backend.routers.bank_sync.fetch_accounts", return_value=[
             SimpleFinAccount(id="acc-1", name="Checking", org_name="Chase", balance=Decimal("100.00"), currency="USD"),
         ]):
        resp = test_client.post("/bank-sync/connect", json={"setup_token": setup_token})

    assert resp.status_code == 201
    body = resp.json()
    assert body["accounts"][0]["simplefin_account_id"] == "acc-1"

    stored = db_session.get(models.BankConnection, body["connection_id"])
    assert stored.access_url_encrypted != "https://u:p@bridge.simplefin.org/simplefin"
    assert crypto.decrypt(stored.access_url_encrypted) == "https://u:p@bridge.simplefin.org/simplefin"


def test_connect_fails_without_encryption_key(db_session, monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", None)
    # Both names must be cleared: APP_ENCRYPTION_KEY is the current name
    # and BANK_TOKEN_ENCRYPTION_KEY only its legacy alias, so clearing one
    # leaves encryption configured. Also keeps this test independent of
    # whatever the developer happens to have in their real .env.
    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", None, raising=False)
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    test_client = TestClient(app)

    setup_token = base64.b64encode(b"https://bridge.simplefin.org/claim/x").decode()
    with patch("backend.routers.bank_sync.claim_setup_token", return_value="https://u:p@bridge.simplefin.org/simplefin") as mock_claim:
        resp = test_client.post("/bank-sync/connect", json={"setup_token": setup_token})

    assert resp.status_code == 400
    # A SimpleFIN setup token can only be claimed once. Failing the encryption
    # check AFTER claiming burned the user's token on a request that 400s
    # anyway, forcing them back to the bank for a new one.
    mock_claim.assert_not_called()


def test_link_creates_account_link(client, db_session):
    test_client, user = client
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.post(f"/bank-sync/{connection.id}/link", json={
        "simplefin_account_id": "acc-1", "simplefin_account_name": "Checking",
        "local_account_id": account.id,
    })

    assert resp.status_code == 201
    assert resp.json()["local_account_id"] == account.id


def test_link_requires_local_target(client, db_session):
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.post(f"/bank-sync/{connection.id}/link", json={
        "simplefin_account_id": "acc-1", "simplefin_account_name": "Checking",
    })

    assert resp.status_code == 400


def test_link_rejects_other_users_local_account(client, db_session):
    test_client, user = client
    other = models.User(username="mallory", hashed_password="x", display_name="Mallory")
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    other_account = models.Account(user_id=other.id, name="Mallory Checking", type=models.AccountType.checking)
    db_session.add(other_account)
    db_session.commit()
    db_session.refresh(other_account)
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.post(f"/bank-sync/{connection.id}/link", json={
        "simplefin_account_id": "acc-1", "simplefin_account_name": "Checking",
        "local_account_id": other_account.id,
    })

    assert resp.status_code == 404


def test_link_rejects_other_users_local_credit_card(client, db_session):
    test_client, user = client
    other = models.User(username="mallory", hashed_password="x", display_name="Mallory")
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    other_card = models.CreditCard(
        user_id=other.id, name="Mallory Card", credit_limit=Decimal("1000"),
        statement_day=1, due_day=15,
    )
    db_session.add(other_card)
    db_session.commit()
    db_session.refresh(other_card)
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.post(f"/bank-sync/{connection.id}/link", json={
        "simplefin_account_id": "acc-1", "simplefin_account_name": "Checking",
        "local_credit_card_id": other_card.id,
    })

    assert resp.status_code == 404


def test_status_lists_connections_with_links(client, db_session):
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"), last_error="boom")
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)
    link = models.BankConnectionAccountLink(connection_id=connection.id, simplefin_account_id="acc-1", simplefin_account_name="Checking")
    db_session.add(link)
    db_session.commit()

    resp = test_client.get("/bank-sync/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["last_error"] == "boom"
    assert body[0]["links"][0]["simplefin_account_id"] == "acc-1"


def test_sync_now_invokes_service_and_reports_errors(client, db_session):
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    def fake_sync(db, conn):
        conn.last_error = "simulated failure"
        return (0, 0)

    with patch("backend.routers.bank_sync.sync_connection", side_effect=fake_sync):
        resp = test_client.post("/bank-sync/sync-now")

    assert resp.status_code == 200
    body = resp.json()
    assert body["synced_connections"] == 1
    assert body["errors"] == ["simulated failure"]
    assert body["imported"] == 0
    assert body["skipped_duplicates"] == 0


def test_sync_now_reports_imported_and_skipped_counts(client, db_session):
    """Regression: Sync Now used to only expose synced_connections/errors --
    a clean run that found nothing new looked identical to one that pulled in
    real transactions, with no way to tell them apart short of eyeballing
    whether last_synced_at moved."""
    test_client, user = client
    conn1 = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    conn2 = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add_all([conn1, conn2])
    db_session.commit()

    counts = iter([(3, 1), (0, 0)])

    def fake_sync(db, conn):
        return next(counts)

    with patch("backend.routers.bank_sync.sync_connection", side_effect=fake_sync):
        resp = test_client.post("/bank-sync/sync-now")

    body = resp.json()
    assert body["imported"] == 3
    assert body["skipped_duplicates"] == 1


def test_sync_now_includes_errored_connections(client, db_session):
    """An errored connection must keep being retried: sync_connection is the
    only path that restores `active`, so excluding it here made a transient
    failure permanent and left "Sync Now" silently reporting 0 connections."""
    test_client, user = client
    active = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    errored = models.BankConnection(
        user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"),
        status=models.BankConnectionStatus.error, last_error="bank unreachable",
    )
    disconnected = models.BankConnection(
        user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"),
        status=models.BankConnectionStatus.disconnected,
    )
    db_session.add_all([active, errored, disconnected])
    db_session.commit()
    db_session.refresh(errored)
    db_session.refresh(disconnected)

    attempted = []

    def fake_sync(db, conn):
        attempted.append(conn.id)
        conn.last_error = None
        return (0, 0)

    with patch("backend.routers.bank_sync.sync_connection", side_effect=fake_sync):
        resp = test_client.post("/bank-sync/sync-now")

    assert resp.status_code == 200
    assert resp.json()["synced_connections"] == 2
    assert errored.id in attempted
    assert disconnected.id not in attempted


def test_list_connection_accounts_refetches_discovered_accounts(client, db_session):
    """/connect returns the discovered-account list exactly once and the setup
    token is spent by then; this endpoint is the only way to recover it."""
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    with patch("backend.routers.bank_sync.fetch_accounts", return_value=[
        SimpleFinAccount(id="acc-1", name="Checking", org_name="Chase", balance=Decimal("100.00"), currency="USD"),
        SimpleFinAccount(id="card-1", name="Visa", org_name="Chase", balance=Decimal("-500.00"), currency="USD"),
    ]) as mock_fetch:
        resp = test_client.get(f"/bank-sync/{connection.id}/accounts")

    assert resp.status_code == 200
    mock_fetch.assert_called_once_with("https://access.url")
    body = resp.json()
    assert [a["simplefin_account_id"] for a in body] == ["acc-1", "card-1"]
    assert body[1]["name"] == "Visa"


def test_list_connection_accounts_rejects_other_users_connection(db_session, monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    owner = models.User(username="dan", hashed_password="x", display_name="Dan")
    other = models.User(username="mallory", hashed_password="x", display_name="Mallory")
    db_session.add_all([owner, other])
    db_session.commit()
    connection = models.BankConnection(user_id=owner.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: other
    test_client = TestClient(app)

    with patch("backend.routers.bank_sync.fetch_accounts") as mock_fetch:
        resp = test_client.get(f"/bank-sync/{connection.id}/accounts")

    assert resp.status_code == 404
    mock_fetch.assert_not_called()  # ownership rejected before touching the bank


def test_disconnect_removes_connection(client, db_session):
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.delete(f"/bank-sync/{connection.id}")

    assert resp.status_code == 204
    assert db_session.get(models.BankConnection, connection.id) is None


def test_disconnect_rejects_other_users_connection(db_session):
    owner = models.User(username="dan", hashed_password="x", display_name="Dan")
    other = models.User(username="mallory", hashed_password="x", display_name="Mallory")
    db_session.add_all([owner, other])
    db_session.commit()
    connection = models.BankConnection(user_id=owner.id, access_url_encrypted="x")
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: other
    test_client = TestClient(app)

    resp = test_client.delete(f"/bank-sync/{connection.id}")

    assert resp.status_code == 404
