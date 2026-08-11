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


def _make_card_connection(db, username="dancard"):
    """Connection whose single link targets a CREDIT CARD rather than a checking
    account -- the branch none of the account-based tests exercise."""
    user = models.User(username=username, hashed_password="x", display_name="Dan")
    db.add(user)
    db.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1, current_balance=Decimal("0.00"),
    )
    db.add(card)
    db.flush()
    connection = models.BankConnection(user_id=user.id, access_url_encrypted="ciphertext")
    db.add(connection)
    db.flush()
    link = models.BankConnectionAccountLink(
        connection_id=connection.id, simplefin_account_id="card-1",
        simplefin_account_name="Visa", local_credit_card_id=card.id,
    )
    db.add(link)
    db.commit()
    return user, card, connection, link


def test_sync_connection_stores_card_balance_as_positive_amount_owed(db_session):
    """SimpleFIN reports card liabilities as NEGATIVE, but CreditCard.current_balance
    is a positive amount owed everywhere else (import_service subtracts signed
    amounts; utilization_pct divides by credit_limit). Assigning SimpleFIN's value
    straight through inverted the sign on every sync."""
    user, card, connection, link = _make_card_connection(db_session)
    txns = [SimpleFinTransaction(id="c1", posted=datetime(2026, 8, 5), amount=Decimal("-52.90"), description="Meijer")]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("-500.00"))):
        sync_connection(db_session, connection)

    db_session.refresh(card)
    assert card.current_balance == Decimal("500.00")
    assert card.current_balance > 0  # never a negative "owed" figure

    ct = db_session.query(models.CreditCardTransaction).filter_by(card_id=card.id).one()
    assert ct.merchant == "Meijer"
    assert ct.source == models.CardTransactionSource.bank_sync


def test_sync_connection_imports_transactions_and_updates_balance(db_session):
    user, account, connection, link = _make_connection(db_session)
    txns = [SimpleFinTransaction(id="t1", posted=datetime(2026, 8, 5), amount=Decimal("-52.90"), description="Meijer")]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("47.10"))):
        imported_count, skipped_count = sync_connection(db_session, connection)

    assert (imported_count, skipped_count) == (1, 0)
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
        second_run = sync_connection(db_session, connection)  # re-run, overlapping window re-fetches the same txn

    assert second_run == (0, 1)  # nothing new imported, the one txn skipped as a duplicate
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


def test_sync_all_retries_errored_connection_and_restores_active(db_session):
    """sync_connection is the ONLY path that can flip a connection back to
    `active`, so if sync_all skipped `error` connections a single transient
    failure (timeout, bank unreachable) would be permanent."""
    user, account, connection, link = _make_connection(db_session)
    connection.status = models.BankConnectionStatus.error
    connection.last_error = "bank unreachable"
    db_session.commit()

    txns = [SimpleFinTransaction(id="t9", posted=datetime(2026, 8, 5), amount=Decimal("25.00"), description="Deposit")]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("125.00"))) as mock_fetch:
        sync_all(db_session)

    mock_fetch.assert_called_once()
    db_session.refresh(connection)
    db_session.refresh(account)
    assert connection.status == models.BankConnectionStatus.active
    assert connection.last_error is None
    assert account.current_balance == Decimal("125.00")


def test_sync_keeps_distinct_same_day_transactions_with_different_ids(db_session):
    """Two genuinely distinct transactions sharing date/amount/description (two
    identical coffees at the same shop) must both import. The legacy
    (date, amount, description) heuristic collapsed them into one, and with
    auto-accept there is no review queue to make that loss visible."""
    user, account, connection, link = _make_connection(db_session)
    txns = [
        SimpleFinTransaction(id="sf-a", posted=datetime(2026, 8, 5), amount=Decimal("-4.50"), description="Starbucks"),
        SimpleFinTransaction(id="sf-b", posted=datetime(2026, 8, 5), amount=Decimal("-4.50"), description="Starbucks"),
    ]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("91.00"))):
        sync_connection(db_session, connection)

    imported = db_session.query(models.Transaction).filter_by(account_id=account.id).all()
    assert len(imported) == 2
    assert {t.external_id for t in imported} == {"sf-a", "sf-b"}


def test_sync_dedupes_same_external_id_across_overlap_window(db_session):
    """The 3-day overlap re-fetch re-presents the same SimpleFIN ids each run.
    Those must still dedupe -- even when the description changes as a pending
    charge settles, which the old date/amount/description heuristic missed."""
    user, account, connection, link = _make_connection(db_session)
    first = [SimpleFinTransaction(id="sf-1", posted=datetime(2026, 8, 5), amount=Decimal("-52.90"), description="PENDING MEIJER")]
    second = [SimpleFinTransaction(id="sf-1", posted=datetime(2026, 8, 5), amount=Decimal("-52.90"), description="MEIJER #123")]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", side_effect=[(first, Decimal("47.10")), (second, Decimal("47.10"))]):
        sync_connection(db_session, connection)
        sync_connection(db_session, connection)

    imported = db_session.query(models.Transaction).filter_by(account_id=account.id).all()
    assert len(imported) == 1
    assert imported[0].external_id == "sf-1"


def test_sync_does_not_reimport_legacy_rows_lacking_external_id(db_session):
    """Rows synced before the external_id column existed have external_id NULL.
    The first sync after upgrading must not duplicate them, so the id lookup
    falls back to the legacy heuristic restricted to NULL-id rows."""
    user, account, connection, link = _make_connection(db_session)
    legacy = models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 5),
        amount=Decimal("-52.90"), description="Meijer", is_actual=True,
        source=models.TransactionSource.bank_sync, external_id=None,
    )
    db_session.add(legacy)
    db_session.commit()

    txns = [SimpleFinTransaction(id="sf-1", posted=datetime(2026, 8, 5), amount=Decimal("-52.90"), description="Meijer")]
    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("47.10"))):
        sync_connection(db_session, connection)

    imported = db_session.query(models.Transaction).filter_by(account_id=account.id).all()
    assert len(imported) == 1


def test_sync_keeps_distinct_same_day_card_transactions(db_session):
    """Card-side twin of the checking-account distinct-duplicates case."""
    user, card, connection, link = _make_card_connection(db_session)
    txns = [
        SimpleFinTransaction(id="cc-a", posted=datetime(2026, 8, 5), amount=Decimal("-4.50"), description="Starbucks"),
        SimpleFinTransaction(id="cc-b", posted=datetime(2026, 8, 5), amount=Decimal("-4.50"), description="Starbucks"),
    ]

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=(txns, Decimal("-9.00"))):
        sync_connection(db_session, connection)

    cts = db_session.query(models.CreditCardTransaction).filter_by(card_id=card.id).all()
    assert len(cts) == 2
    assert {c.external_id for c in cts} == {"cc-a", "cc-b"}


def test_run_import_without_external_id_keeps_legacy_dedup(db_session):
    """CSV/OFX rows carry no external_id and must keep collapsing on the old
    (date, amount, description) heuristic -- behavior unchanged."""
    user = models.User(username="dancsv", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("100.00"))
    db_session.add(account)
    db_session.commit()

    rows = [
        schemas.ImportConfirmRow(date=date(2026, 8, 5), description="Meijer", amount=Decimal("-10.00")),
        schemas.ImportConfirmRow(date=date(2026, 8, 5), description="Meijer", amount=Decimal("-10.00")),
    ]
    result = run_import(db_session, user, rows, account_id=account.id, card_id=None)

    assert result.imported == 1
    assert result.skipped_duplicates == 1
    txn = db_session.query(models.Transaction).filter_by(account_id=account.id).one()
    assert txn.external_id is None


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
