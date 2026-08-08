from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from backend import models, schemas
from backend.services.bank_sync_service import sync_connection, sync_all
from backend.services.import_service import run_import
from backend.services.simplefin_client import SimpleFinTransaction, SimpleFinError


def _make_connection(db, username="dan"):
    user = models.User(username=username, hashed_password="x", display_name="Dan")
    db.add(user)
    db.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("100.00"))
    db.add(account)
    db.flush()
    connection = models.BankConnection(user_id=user.id, access_url_encrypted="ciphertext")
    db.add(connection)
    db.flush()
    link = models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="acc-1",
        simplefin_account_name="Checking", local_account_id=account.id,
    )
    db.add(link)
    db.commit()
    return user, account, connection, link


def test_sync_connection_imports_transactions_and_updates_balance(db_session):
    user, account, connection, link = _make_connection(db_session)
    txns = [SimpleFinTransaction(id="t1", posted=datetime(2026, 8, 5), amount=Decimal("-52.90"), description="Meijer")]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("47.10"))):
        sync_connection(db_session, connection)

    db_session.refresh(account)
    db_session.refresh(link)
    db_session.refresh(connection)
    assert account.current_balance == Decimal("47.10")
    assert link.last_synced_at is not None
    assert connection.last_error is None
    imported = db_session.query(models.Transaction).filter_by(
        account_id=account.id, source=models.TransactionSource.bank_sync,
    ).all()
    assert len(imported) == 1
    assert imported[0].description == "Meijer"
    assert imported[0].amount == Decimal("-52.90")


def test_sync_connection_dedupes_on_rerun(db_session):
    user, account, connection, link = _make_connection(db_session)
    txns = [SimpleFinTransaction(id="t1", posted=datetime(2026, 8, 5), amount=Decimal("-52.90"), description="Meijer")]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("47.10"))):
        sync_connection(db_session, connection)
        sync_connection(db_session, connection)  # re-run, overlapping window re-fetches the same txn

    imported = db_session.query(models.Transaction).filter_by(account_id=account.id).all()
    assert len(imported) == 1


def test_sync_connection_isolates_per_account_failure(db_session):
    user, account, connection, link = _make_connection(db_session)
    account2 = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("0"))
    db_session.add(account2)
    db_session.flush()
    link2 = models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="acc-2",
        simplefin_account_name="Savings", local_account_id=account2.id,
    )
    db_session.add(link2)
    db_session.commit()

    def fake_fetch(access_url, account_id, since):
        if account_id == "acc-1":
            raise SimpleFinError("bank unreachable")
        return [SimpleFinTransaction(id="t2", posted=datetime(2026, 8, 5), amount=Decimal("500.00"), description="Transfer")], Decimal("500.00")

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", side_effect=fake_fetch):
        sync_connection(db_session, connection)

    db_session.refresh(account2)
    db_session.refresh(connection)
    assert account2.current_balance == Decimal("500.00")  # second link still synced
    assert connection.last_error == "bank unreachable"


def test_sync_connection_marks_status_error_when_all_links_fail(db_session):
    user, account, connection, link = _make_connection(db_session)

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", side_effect=SimpleFinError("bank unreachable")):
        sync_connection(db_session, connection)

    db_session.refresh(connection)
    assert connection.status == models.BankConnectionStatus.error
    assert connection.last_error == "bank unreachable"


def test_sync_all_skips_inactive_connections(db_session):
    user, account, connection, link = _make_connection(db_session)
    connection.status = models.BankConnectionStatus.disconnected
    db_session.commit()

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions") as mock_fetch:
        sync_all(db_session)

    mock_fetch.assert_not_called()


def test_run_import_tags_transactions_with_given_source(db_session):
    """Direct unit test of import_service.run_import's source override --
    the mechanism bank_sync_service relies on to distinguish bank-sync-origin
    transactions from CSV imports, without any read-then-update workaround."""
    user = models.User(username="dan2", hashed_password="x", display_name="Dan2")
    db_session.add(user)
    db_session.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("100.00"))
    db_session.add(account)
    db_session.commit()

    rows = [schemas.ImportConfirmRow(date=date(2026, 8, 5), description="Meijer", amount=Decimal("-52.90"))]
    run_import(db_session, user, rows, account_id=account.id, card_id=None, source=models.TransactionSource.bank_sync)

    txn = db_session.query(models.Transaction).filter_by(account_id=account.id).one()
    assert txn.source == models.TransactionSource.bank_sync

    # Default behavior (no source override) is unchanged -- existing CSV-import
    # callers keep tagging csv_import without passing the new parameter.
    rows2 = [schemas.ImportConfirmRow(date=date(2026, 8, 6), description="Kroger", amount=Decimal("-10.00"))]
    run_import(db_session, user, rows2, account_id=account.id, card_id=None)
    txn2 = db_session.query(models.Transaction).filter_by(account_id=account.id, description="Kroger").one()
    assert txn2.source == models.TransactionSource.csv_import


def test_run_import_tags_card_transactions_with_given_card_source(db_session):
    user = models.User(username="dan3", hashed_password="x", display_name="Dan3")
    db_session.add(user)
    db_session.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1, current_balance=Decimal("100.00"),
    )
    db_session.add(card)
    db_session.commit()

    rows = [schemas.ImportConfirmRow(date=date(2026, 8, 5), description="Meijer", amount=Decimal("-52.90"))]
    run_import(
        db_session, user, rows, account_id=None, card_id=card.id,
        card_source=models.CardTransactionSource.bank_sync,
    )

    ct = db_session.query(models.CreditCardTransaction).filter_by(card_id=card.id).one()
    assert ct.source == models.CardTransactionSource.bank_sync


def test_sync_connection_isolates_unexpected_error_per_link(db_session):
    """An exception other than SimpleFinError out of one link's sync (e.g. an
    unexpected error from build_preview/run_import) must not stop the other
    links on the same connection from syncing."""
    user, account, connection, link = _make_connection(db_session)
    account2 = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("0"))
    db_session.add(account2)
    db_session.flush()
    link2 = models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="acc-2",
        simplefin_account_name="Savings", local_account_id=account2.id,
    )
    db_session.add(link2)
    db_session.commit()

    def fake_fetch(access_url, account_id, since):
        if account_id == "acc-1":
            raise RuntimeError("unexpected boom")
        return [SimpleFinTransaction(id="t2", posted=datetime(2026, 8, 5), amount=Decimal("500.00"), description="Transfer")], Decimal("500.00")

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", side_effect=fake_fetch):
        sync_connection(db_session, connection)

    db_session.refresh(account2)
    db_session.refresh(connection)
    assert account2.current_balance == Decimal("500.00")  # second link still synced
    assert connection.last_error == "unexpected boom"


def test_sync_all_isolates_decrypt_failure_per_connection(db_session):
    """A decrypt() failure on one connection's stored token must not abort
    sync_all's job -- other active connections still get processed."""
    user1, account1, connection1, link1 = _make_connection(db_session, username="dan1")
    user2, account2, connection2, link2 = _make_connection(db_session, username="dan2")
    connection1.access_url_encrypted = "bad-ciphertext"
    connection2.access_url_encrypted = "good-ciphertext"
    db_session.commit()

    txns = [SimpleFinTransaction(id="t1", posted=datetime(2026, 8, 5), amount=Decimal("10.00"), description="Deposit")]

    def fake_decrypt(ciphertext):
        if ciphertext == "bad-ciphertext":
            raise ValueError("key mismatch")
        return "https://access.url"

    with patch("backend.services.bank_sync_service.decrypt", side_effect=fake_decrypt), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("10.00"))):
        sync_all(db_session)

    db_session.refresh(connection1)
    db_session.refresh(connection2)
    db_session.refresh(account2)
    assert connection1.status == models.BankConnectionStatus.error
    assert connection1.last_error == "key mismatch"
    assert connection2.status == models.BankConnectionStatus.active
    assert account2.current_balance == Decimal("10.00")  # second connection still synced
