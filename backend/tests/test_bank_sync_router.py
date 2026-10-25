import base64
from datetime import date
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
from backend.services.job_locks import _bank_sync_lock
from backend.services.plaid_client import PlaidAccount, PlaidError, PlaidNotConfigured, PlaidNotReady
from backend.services.plaid_sync_service import ImportReportRow, PlaidSyncReport
from backend.services.simplefin_client import SimpleFinAccount


@pytest.fixture()
def client(db_session, monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user = models.User(username="dan", hashed_password="x", display_name="the user")
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
    user = models.User(username="dan", hashed_password="x", display_name="the user")
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
    owner = models.User(username="dan", hashed_password="x", display_name="the user")
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
    owner = models.User(username="dan", hashed_password="x", display_name="the user")
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


# ── Plaid: link-token ────────────────────────────────────────────────────────

def test_plaid_link_token_new_link_requests_no_access_token(client):
    test_client, user = client
    with patch("backend.routers.bank_sync.create_link_token", return_value="link-sandbox-new") as mock_create:
        resp = test_client.post("/bank-sync/plaid/link-token", json={"connection_id": None})

    assert resp.status_code == 200
    assert resp.json() == {"link_token": "link-sandbox-new"}
    mock_create.assert_called_once_with(str(user.id), access_token=None)


def test_plaid_link_token_update_mode_decrypts_and_passes_the_connections_token(client, db_session):
    test_client, user = client
    connection = models.BankConnection(
        user_id=user.id, provider="plaid", plaid_item_id="item-1",
        access_url_encrypted=crypto.encrypt("plaid-access-abc123"),
    )
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    with patch("backend.routers.bank_sync.create_link_token", return_value="link-sandbox-update") as mock_create:
        resp = test_client.post("/bank-sync/plaid/link-token", json={"connection_id": connection.id})

    assert resp.status_code == 200
    assert resp.json() == {"link_token": "link-sandbox-update"}
    mock_create.assert_called_once_with(str(user.id), access_token="plaid-access-abc123")


def test_plaid_link_token_update_mode_fails_without_encryption_key(db_session, monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user = models.User(username="dan", hashed_password="x", display_name="the user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    connection = models.BankConnection(
        user_id=user.id, provider="plaid", access_url_encrypted=crypto.encrypt("plaid-access-token"),
    )
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    # Break the key AFTER encrypting, so decrypt (inside the endpoint) fails.
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", None)
    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", None, raising=False)

    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    test_client = TestClient(app)

    with patch("backend.routers.bank_sync.create_link_token") as mock_create:
        resp = test_client.post("/bank-sync/plaid/link-token", json={"connection_id": connection.id})

    assert resp.status_code == 400
    mock_create.assert_not_called()


def test_plaid_link_token_rejects_simplefin_connection_id(client, db_session):
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.post("/bank-sync/plaid/link-token", json={"connection_id": connection.id})

    assert resp.status_code == 400


def test_plaid_link_token_not_configured_returns_400_with_the_env_var_message(client):
    test_client, _user = client
    message = "Plaid isn't set up: add PLAID_CLIENT_ID and PLAID_SECRET to the backend .env"
    with patch("backend.routers.bank_sync.create_link_token", side_effect=PlaidNotConfigured("NOT_CONFIGURED", message)):
        resp = test_client.post("/bank-sync/plaid/link-token", json={"connection_id": None})

    assert resp.status_code == 400
    assert resp.json()["detail"] == message


def test_plaid_link_token_other_plaid_error_returns_422_with_code_and_message(client):
    test_client, _user = client
    with patch("backend.routers.bank_sync.create_link_token", side_effect=PlaidError("INVALID_REQUEST", "bad params")):
        resp = test_client.post("/bank-sync/plaid/link-token", json={"connection_id": None})

    assert resp.status_code == 422
    assert resp.json()["detail"] == "INVALID_REQUEST: bad params"


# ── Plaid: exchange ──────────────────────────────────────────────────────────

def test_plaid_exchange_stores_encrypted_token_sets_cutover_and_lists_accounts(client, db_session):
    test_client, user = client
    plaid_accounts = [
        PlaidAccount(id="plaid-acc-1", name="Checking", mask="4321", type="depository", subtype="checking",
                     current=Decimal("312.45"), available=Decimal("300.00"), limit=None),
    ]
    with patch("backend.routers.bank_sync.exchange_public_token",
               return_value=("real-plaid-access-token-999", "item-xyz")), \
         patch("backend.routers.bank_sync.get_plaid_accounts", return_value=plaid_accounts):
        resp = test_client.post("/bank-sync/plaid/exchange", json={"public_token": "public-abc"})

    assert resp.status_code == 201
    body = resp.json()
    account = body["accounts"][0]
    assert account["simplefin_account_id"] == "plaid-acc-1"
    assert account["org_name"] == "Plaid"
    assert account["balance"] == "312.45"
    assert account["mask"] == "4321"
    assert account["kind"] == "checking"

    stored = db_session.get(models.BankConnection, body["connection_id"])
    assert stored.provider == "plaid"
    assert stored.plaid_item_id == "item-xyz"
    assert stored.cutover_date == date.today()
    assert stored.access_url_encrypted != "real-plaid-access-token-999"
    assert crypto.decrypt(stored.access_url_encrypted) == "real-plaid-access-token-999"


def test_plaid_exchange_fails_without_encryption_key(db_session, monkeypatch):
    monkeypatch.setattr(crypto.settings, "BANK_TOKEN_ENCRYPTION_KEY", None)
    monkeypatch.setattr(crypto.settings, "APP_ENCRYPTION_KEY", None, raising=False)
    user = models.User(username="dan", hashed_password="x", display_name="the user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    test_client = TestClient(app)

    with patch("backend.routers.bank_sync.exchange_public_token") as mock_exchange:
        resp = test_client.post("/bank-sync/plaid/exchange", json={"public_token": "public-abc"})

    assert resp.status_code == 400
    # A Plaid public token can only be exchanged once -- failing the
    # encryption check AFTER exchanging would burn it on a request that
    # 400s anyway.
    mock_exchange.assert_not_called()


def test_plaid_exchange_not_configured_returns_400(client):
    test_client, _user = client
    message = "Plaid isn't set up: add PLAID_CLIENT_ID and PLAID_SECRET to the backend .env"
    with patch("backend.routers.bank_sync.exchange_public_token", side_effect=PlaidNotConfigured("NOT_CONFIGURED", message)):
        resp = test_client.post("/bank-sync/plaid/exchange", json={"public_token": "public-abc"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == message


def test_plaid_exchange_account_listing_failure_still_leaves_connection_stored(client, db_session):
    test_client, user = client
    with patch("backend.routers.bank_sync.exchange_public_token",
               return_value=("real-plaid-access-token-999", "item-xyz")), \
         patch("backend.routers.bank_sync.get_plaid_accounts",
               side_effect=PlaidError("API_ERROR", "accounts unavailable")):
        resp = test_client.post("/bank-sync/plaid/exchange", json={"public_token": "public-abc"})

    assert resp.status_code == 422
    assert "API_ERROR" in resp.json()["detail"]
    stored = db_session.query(models.BankConnection).filter_by(user_id=user.id, provider="plaid").one()
    assert crypto.decrypt(stored.access_url_encrypted) == "real-plaid-access-token-999"


# ── Plaid: GET accounts dispatch ─────────────────────────────────────────────

def test_list_connection_accounts_dispatches_to_plaid_for_a_plaid_connection(client, db_session):
    test_client, user = client
    connection = models.BankConnection(
        user_id=user.id, provider="plaid", plaid_item_id="item-1",
        access_url_encrypted=crypto.encrypt("plaid-access-token"),
    )
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)
    plaid_accounts = [
        PlaidAccount(id="plaid-acc-1", name="Savings", mask="0001", type="depository", subtype=None,
                     current=None, available=None, limit=None),
    ]

    with patch("backend.routers.bank_sync.get_plaid_accounts", return_value=plaid_accounts) as mock_get:
        resp = test_client.get(f"/bank-sync/{connection.id}/accounts")

    assert resp.status_code == 200
    mock_get.assert_called_once_with("plaid-access-token")
    body = resp.json()
    assert body[0]["org_name"] == "Plaid"
    assert body[0]["balance"] == "0.00" or body[0]["balance"] == "0"
    assert body[0]["kind"] == "depository"  # falls back to type when subtype is None


def test_list_connection_accounts_maps_plaid_error_for_a_plaid_connection(client, db_session):
    test_client, user = client
    connection = models.BankConnection(
        user_id=user.id, provider="plaid", access_url_encrypted=crypto.encrypt("plaid-access-token"),
    )
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    with patch("backend.routers.bank_sync.get_plaid_accounts",
               side_effect=PlaidError("API_ERROR", "accounts unavailable")):
        resp = test_client.get(f"/bank-sync/{connection.id}/accounts")

    assert resp.status_code == 422
    assert resp.json()["detail"] == "API_ERROR: accounts unavailable"


# ── Links: one-active-link rule ──────────────────────────────────────────────

def test_link_409s_when_another_active_link_targets_the_same_account(client, db_session):
    test_client, user = client
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    old_connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    new_connection = models.BankConnection(
        user_id=user.id, provider="plaid", access_url_encrypted=crypto.encrypt("plaid-token"),
    )
    db_session.add_all([old_connection, new_connection])
    db_session.commit()
    db_session.refresh(old_connection)
    db_session.refresh(new_connection)

    old_link = models.BankConnectionAccountLink(
        connection_id=old_connection.id, simplefin_account_id="acc-old", simplefin_account_name="Checking",
        local_account_id=account.id,
    )
    db_session.add(old_link)
    db_session.commit()
    db_session.refresh(old_link)

    resp = test_client.post(f"/bank-sync/{new_connection.id}/link", json={
        "simplefin_account_id": "plaid-acc-1", "simplefin_account_name": "Checking",
        "local_account_id": account.id,
    })

    assert resp.status_code == 409
    assert resp.json()["detail"]["existing_link_id"] == old_link.id
    assert resp.json()["detail"]["existing_provider"] == "simplefin"


def test_link_409s_when_another_active_link_targets_the_same_credit_card(client, db_session):
    test_client, user = client
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("5000"),
                             statement_day=1, due_day=15)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    old_connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    new_connection = models.BankConnection(
        user_id=user.id, provider="plaid", access_url_encrypted=crypto.encrypt("plaid-token"),
    )
    db_session.add_all([old_connection, new_connection])
    db_session.commit()
    db_session.refresh(old_connection)
    db_session.refresh(new_connection)

    old_link = models.BankConnectionAccountLink(
        connection_id=old_connection.id, simplefin_account_id="card-old", simplefin_account_name="Visa",
        local_credit_card_id=card.id,
    )
    db_session.add(old_link)
    db_session.commit()
    db_session.refresh(old_link)

    resp = test_client.post(f"/bank-sync/{new_connection.id}/link", json={
        "simplefin_account_id": "plaid-card-1", "simplefin_account_name": "Visa",
        "local_credit_card_id": card.id,
    })

    assert resp.status_code == 409
    assert resp.json()["detail"]["existing_link_id"] == old_link.id


def test_link_switch_existing_deactivates_the_old_link_and_activates_the_new_one(client, db_session):
    test_client, user = client
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    old_connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    new_connection = models.BankConnection(
        user_id=user.id, provider="plaid", access_url_encrypted=crypto.encrypt("plaid-token"),
    )
    db_session.add_all([old_connection, new_connection])
    db_session.commit()
    db_session.refresh(old_connection)
    db_session.refresh(new_connection)

    old_link = models.BankConnectionAccountLink(
        connection_id=old_connection.id, simplefin_account_id="acc-old", simplefin_account_name="Checking",
        local_account_id=account.id,
    )
    db_session.add(old_link)
    db_session.commit()
    db_session.refresh(old_link)

    resp = test_client.post(f"/bank-sync/{new_connection.id}/link", json={
        "simplefin_account_id": "plaid-acc-1", "simplefin_account_name": "Checking",
        "local_account_id": account.id, "switch_existing": True,
    })

    assert resp.status_code == 201
    assert resp.json()["is_active"] is True
    db_session.refresh(old_link)
    assert old_link.is_active is False


def test_link_out_includes_is_active_and_status_includes_provider(client, db_session):
    test_client, user = client
    connection = models.BankConnection(
        user_id=user.id, provider="plaid", access_url_encrypted=crypto.encrypt("plaid-token"),
    )
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.get("/bank-sync/status")
    assert resp.status_code == 200
    assert resp.json()[0]["provider"] == "plaid"


# ── Plaid: first import ──────────────────────────────────────────────────────

def _plaid_connection(db_session, user, sync_cursor=None):
    connection = models.BankConnection(
        user_id=user.id, provider="plaid", plaid_item_id="item-1",
        access_url_encrypted=crypto.encrypt("plaid-access-token"),
        cutover_date=date.today(), sync_cursor=sync_cursor,
    )
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)
    return connection


def test_first_import_preview_writes_nothing_then_confirm_imports_then_confirming_again_409s(client, db_session):
    test_client, user = client
    connection = _plaid_connection(db_session, user)

    preview_report = PlaidSyncReport(
        imported=2, matched=1, ignored=0,
        rows=[ImportReportRow(date=date(2026, 10, 1), amount=Decimal("42.50"), description="COFFEE SHOP",
                              outcome="imported", target="Checking")],
        unlinked_accounts=["Brokerage ••0004"],
    )

    def fake_sync(db, conn, *, first_import=False, dry_run=False):
        assert dry_run is True
        return preview_report

    with patch("backend.routers.bank_sync.sync_plaid_connection", side_effect=fake_sync) as mock_sync:
        resp = test_client.post(f"/bank-sync/{connection.id}/plaid/first-import?confirm=false")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "imported": 2, "matched": 1, "ignored": 0,
        "rows": [{"date": "2026-10-01", "amount": "42.50", "description": "COFFEE SHOP",
                  "outcome": "imported", "target": "Checking"}],
        "unlinked_accounts": ["Brokerage ••0004"],
    }
    mock_sync.assert_called_once()
    # Dry run must not have touched the connection's cursor.
    db_session.refresh(connection)
    assert connection.sync_cursor is None

    confirm_report = PlaidSyncReport(imported=5, matched=0, ignored=0, rows=[])

    def fake_confirm(db, conn, *, first_import=False, dry_run=False):
        assert first_import is True
        conn.sync_cursor = "cursor-after-first-import"
        return confirm_report

    with patch("backend.routers.bank_sync.sync_plaid_connection", side_effect=fake_confirm):
        resp = test_client.post(f"/bank-sync/{connection.id}/plaid/first-import?confirm=true")

    assert resp.status_code == 200
    assert resp.json()["imported"] == 5
    # Not db_session.refresh(): fake_confirm mutated the connection in place
    # (standing in for sync_plaid_connection's own commit) without actually
    # committing, and the test and router share one session/identity map, so
    # a refresh here would just discard that in-memory change and reload the
    # pre-sync NULL -- this checks what the router saw and returned, not a
    # round trip through the database.
    assert connection.sync_cursor == "cursor-after-first-import"

    # A second confirm (sync_cursor is now set) must 409 without calling sync again.
    with patch("backend.routers.bank_sync.sync_plaid_connection") as mock_sync_again:
        resp = test_client.post(f"/bank-sync/{connection.id}/plaid/first-import?confirm=true")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "First import already done"
    mock_sync_again.assert_not_called()


def test_first_import_rejects_non_plaid_connection(client, db_session):
    test_client, user = client
    connection = models.BankConnection(user_id=user.id, access_url_encrypted=crypto.encrypt("https://access.url"))
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    resp = test_client.post(f"/bank-sync/{connection.id}/plaid/first-import?confirm=false")

    assert resp.status_code == 400


def test_first_import_preview_maps_plaid_error(client, db_session):
    test_client, user = client
    connection = _plaid_connection(db_session, user)

    with patch("backend.routers.bank_sync.sync_plaid_connection",
               side_effect=PlaidError("ITEM_LOGIN_REQUIRED", "reconnect needed")):
        resp = test_client.post(f"/bank-sync/{connection.id}/plaid/first-import?confirm=false")

    assert resp.status_code == 422
    assert resp.json()["detail"] == "ITEM_LOGIN_REQUIRED: reconnect needed"


@pytest.mark.parametrize("confirm", ["false", "true"])
def test_first_import_409s_while_plaid_is_still_fetching(client, db_session, confirm):
    test_client, user = client
    connection = _plaid_connection(db_session, user)

    with patch("backend.routers.bank_sync.sync_plaid_connection", side_effect=PlaidNotReady()):
        resp = test_client.post(f"/bank-sync/{connection.id}/plaid/first-import?confirm={confirm}")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Plaid is still fetching your history; try again in a minute"
    db_session.refresh(connection)
    assert connection.sync_cursor is None
    assert _bank_sync_lock.acquire(blocking=False)
    _bank_sync_lock.release()


def test_status_reports_first_import_done(client, db_session):
    test_client, user = client
    pending = _plaid_connection(db_session, user)
    done = _plaid_connection(db_session, user, sync_cursor="cur-1")

    by_id = {c["id"]: c for c in test_client.get("/bank-sync/status").json()}
    assert by_id[pending.id]["first_import_done"] is False
    assert by_id[done.id]["first_import_done"] is True


def test_first_import_confirm_409s_when_a_sync_is_already_running(client, db_session):
    test_client, user = client
    connection = _plaid_connection(db_session, user)

    assert _bank_sync_lock.acquire(blocking=False)
    try:
        with patch("backend.routers.bank_sync.sync_plaid_connection") as mock_sync:
            resp = test_client.post(f"/bank-sync/{connection.id}/plaid/first-import?confirm=true")
    finally:
        _bank_sync_lock.release()

    assert resp.status_code == 409
    assert resp.json()["detail"] == "A sync is already running"
    mock_sync.assert_not_called()


def test_first_import_confirm_releases_lock_on_plaid_error(client, db_session):
    test_client, user = client
    connection = _plaid_connection(db_session, user)

    with patch("backend.routers.bank_sync.sync_plaid_connection",
               side_effect=PlaidError("ITEM_LOGIN_REQUIRED", "reconnect needed")):
        resp = test_client.post(f"/bank-sync/{connection.id}/plaid/first-import?confirm=true")

    assert resp.status_code == 422
    # The lock must have been released, not left held by the failed run.
    assert _bank_sync_lock.acquire(blocking=False)
    _bank_sync_lock.release()


# ── Plaid: disconnect ─────────────────────────────────────────────────────────

def test_disconnect_plaid_connection_calls_remove_item_with_the_decrypted_token(client, db_session):
    test_client, user = client
    connection = _plaid_connection(db_session, user)

    with patch("backend.routers.bank_sync.remove_item") as mock_remove:
        resp = test_client.delete(f"/bank-sync/{connection.id}")

    assert resp.status_code == 204
    mock_remove.assert_called_once_with("plaid-access-token")
    assert db_session.get(models.BankConnection, connection.id) is None


def test_disconnect_plaid_connection_still_deletes_locally_when_remove_item_fails(client, db_session):
    test_client, user = client
    connection = _plaid_connection(db_session, user)

    with patch("backend.routers.bank_sync.remove_item", side_effect=PlaidError("API_ERROR", "Plaid is down")):
        resp = test_client.delete(f"/bank-sync/{connection.id}")

    assert resp.status_code == 204
    assert db_session.get(models.BankConnection, connection.id) is None


def test_disconnect_plaid_connection_still_deletes_locally_on_an_unexpected_error(client, db_session):
    """Not just PlaidError -- ANY exception while removing the item (a
    decrypt failure, a network library bug, ...) must still let the local
    delete go through."""
    test_client, user = client
    connection = _plaid_connection(db_session, user)

    with patch("backend.routers.bank_sync.remove_item", side_effect=RuntimeError("unexpected")):
        resp = test_client.delete(f"/bank-sync/{connection.id}")

    assert resp.status_code == 204
    assert db_session.get(models.BankConnection, connection.id) is None
