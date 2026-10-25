"""Task 1 (Plaid sync): new provider/cutover columns, the PLAID_ENV config
validator, and the sync_all provider/active-link filters that make room for
Plaid as a second bank-sync provider alongside SimpleFIN."""
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend import models
from backend.services.bank_sync_service import sync_all


def test_new_columns_default(db_session):
    """A new BankConnection defaults to provider="simplefin" with no cutover
    date, and a new link defaults to active -- existing behaviour for every
    row that predates Plaid."""
    user = models.User(username="plaidschemauser", hashed_password="x", display_name="Test User")
    db_session.add(user)
    db_session.flush()

    connection = models.BankConnection(user_id=user.id, access_url_encrypted="ciphertext")
    db_session.add(connection)
    db_session.flush()
    assert connection.provider == "simplefin"
    assert connection.cutover_date is None
    assert connection.plaid_item_id is None
    assert connection.sync_cursor is None

    link = models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="acc-1", simplefin_account_name="Checking",
    )
    db_session.add(link)
    db_session.flush()
    assert link.is_active is True


def test_upgrade_schema_adds_plaid_columns(monkeypatch):
    """Build an old-shape SQLite DB (the 5 affected tables, none of the new
    columns), point database.upgrade_schema() at it, and confirm each new
    column is added. Statements for tables this minimal DB doesn't have
    (every other ALTER in the big stmts list) fail and roll back
    individually -- upgrade_schema() is written to tolerate exactly that."""
    import backend.database as database_module

    test_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with test_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE bank_connections (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                access_url_encrypted TEXT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                last_synced_at DATETIME,
                last_error TEXT,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE bank_connection_account_links (
                id INTEGER PRIMARY KEY,
                connection_id INTEGER NOT NULL,
                simplefin_account_id VARCHAR(128) NOT NULL,
                simplefin_account_name VARCHAR(256) NOT NULL,
                local_account_id INTEGER,
                local_credit_card_id INTEGER,
                last_synced_at DATETIME,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE credit_cards (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name VARCHAR(128) NOT NULL,
                credit_limit NUMERIC(14,2) NOT NULL,
                statement_day INTEGER NOT NULL,
                due_day INTEGER NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                date DATE NOT NULL,
                amount NUMERIC(14,2) NOT NULL,
                description VARCHAR(256) NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE credit_card_transactions (
                id INTEGER PRIMARY KEY,
                card_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date DATE NOT NULL,
                amount NUMERIC(14,2) NOT NULL,
                merchant VARCHAR(256) NOT NULL
            )
        """))
        conn.commit()

    monkeypatch.setattr(database_module, "engine", test_engine)
    try:
        database_module.upgrade_schema()

        with test_engine.connect() as conn:
            def columns(table):
                return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}

            bank_connections_cols = columns("bank_connections")
            assert "provider" in bank_connections_cols
            assert "plaid_item_id" in bank_connections_cols
            assert "sync_cursor" in bank_connections_cols
            assert "cutover_date" in bank_connections_cols

            assert "is_active" in columns("bank_connection_account_links")

            credit_cards_cols = columns("credit_cards")
            assert "last_statement_issue_date" in credit_cards_cols
            assert "minimum_payment_amount" in credit_cards_cols

            assert "alt_external_id" in columns("transactions")
            assert "alt_external_id" in columns("credit_card_transactions")
    finally:
        test_engine.dispose()


def test_plaid_env_rejects_unknown():
    from pydantic import ValidationError

    from backend.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, PLAID_ENV="staging")


def test_plaid_env_accepts_sandbox_and_production():
    from backend.config import Settings

    assert Settings(_env_file=None, PLAID_ENV="sandbox").PLAID_ENV == "sandbox"
    assert Settings(_env_file=None, PLAID_ENV="production").PLAID_ENV == "production"


def _make_checking_link(db, *, username: str, provider: str = "simplefin", is_active: bool = True):
    user = models.User(username=username, hashed_password="x", display_name="Test User")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("100.00"),
    )
    db.add(account)
    db.flush()
    connection = models.BankConnection(user_id=user.id, access_url_encrypted="ciphertext", provider=provider)
    db.add(connection)
    db.flush()
    link = models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="acc-1", simplefin_account_name="Checking",
        local_account_id=account.id, is_active=is_active,
    )
    db.add(link)
    db.commit()
    return user, account, connection, link


def test_sync_all_skips_inactive_links(db_session):
    """A SimpleFIN connection whose only link is inactive must never fetch --
    the Plaid cutover deactivates a link instead of deleting it, and an
    inactive link must stay silent on every later sync."""
    _make_checking_link(db_session, username="inactivelinkuser", is_active=False)

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions") as mock_fetch:
        sync_all(db_session)

    mock_fetch.assert_not_called()


def test_sync_all_provider_filter(db_session):
    """providers={"plaid"} must not sync a SimpleFIN connection -- the
    four-times-a-day Plaid schedule and the once-a-day SimpleFIN schedule
    have to be able to run independently without double-syncing anything."""
    _make_checking_link(db_session, username="providerfilteruser", provider="simplefin")

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions") as mock_fetch:
        sync_all(db_session, providers={"plaid"})

    mock_fetch.assert_not_called()


def test_sync_all_provider_filter_none_syncs_everything(db_session):
    """The default (providers=None) must keep syncing every provider -- this
    is the existing scheduled-job call path and must not regress."""
    from backend.services.simplefin_client import SimpleFinTransaction
    from datetime import datetime

    _make_checking_link(db_session, username="providerfilternoneuser", provider="simplefin")
    txns = [SimpleFinTransaction(id="t1", posted=datetime(2026, 10, 1), amount=Decimal("-12.34"), description="Coffee")]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("87.66"), None)) as mock_fetch:
        sync_all(db_session)

    mock_fetch.assert_called_once()
