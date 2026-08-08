from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from backend import models
from backend.services.bank_sync_service import sync_connection, sync_all
from backend.services.simplefin_client import SimpleFinTransaction, SimpleFinError


def _make_connection(db):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
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
