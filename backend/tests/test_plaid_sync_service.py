"""Plaid sync service: transactions/sync pages through the shared import,
balance, pending and statement logic, plus the previewable first import that
matches rows SimpleFIN already stored. All figures are invented."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend import models
from backend.services.bank_sync_service import sync_all, sync_connection
from backend.services.plaid_client import (
    PlaidAccount, PlaidCardStatement, PlaidError, PlaidRateLimited, PlaidSyncPage, PlaidTransaction,
)
from backend.services.plaid_sync_service import sync_plaid_connection

CUTOVER = date(2026, 3, 20)


def _make_plaid_connection(db, username="dan", *, cursor="cur-0", cutover=CUTOVER, token="tok-dan"):
    """Plaid connection with checking, savings and card links -- modelled on
    test_bank_sync_service._make_connection. `access_url_encrypted` holds the
    plain token here because tests patch decrypt to pass it through."""
    user = models.User(username=username, hashed_password="x", display_name="the user")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                              current_balance=Decimal("100.00"))
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings,
                             current_balance=Decimal("500.00"))
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
                             statement_day=5, due_day=1, current_balance=Decimal("0.00"))
    db.add_all([checking, savings, card])
    db.flush()
    connection = models.BankConnection(
        user_id=user.id, access_url_encrypted=token, provider="plaid",
        plaid_item_id=f"item-{username}", sync_cursor=cursor, cutover_date=cutover,
    )
    db.add(connection)
    db.flush()
    db.add_all([
        models.BankConnectionAccountLink(connection_id=connection.id, simplefin_account_id="p-chk",
                                         simplefin_account_name="Checking", local_account_id=checking.id),
        models.BankConnectionAccountLink(connection_id=connection.id, simplefin_account_id="p-sav",
                                         simplefin_account_name="Savings", local_account_id=savings.id),
        models.BankConnectionAccountLink(connection_id=connection.id, simplefin_account_id="p-card",
                                         simplefin_account_name="Visa", local_credit_card_id=card.id),
    ])
    db.commit()
    return user, checking, savings, card, connection


def _t(tid, account, d, amount, desc, *, pending=False, merchant=None, authorized=None):
    """PlaidTransaction in app (checking) convention: negative = money out."""
    return PlaidTransaction(id=tid, account_id=account, date=d, authorized_date=authorized,
                            amount=Decimal(amount), description=desc, merchant_name=merchant, pending=pending)


def _page(added=(), modified=(), removed=(), cursor="cur-1", has_more=False):
    return PlaidSyncPage(added=list(added), modified=list(modified), removed=list(removed),
                         next_cursor=cursor, has_more=has_more)


def _client(pages=None, *, accounts=None, last_update=None, statements=None):
    client = MagicMock()
    if pages is not None:
        client.sync_page.side_effect = list(pages)
    client.get_accounts.return_value = accounts or []
    client.get_last_successful_update.return_value = last_update
    client.get_card_statements.return_value = statements or []
    return client


@contextmanager
def _patched(client):
    with patch("backend.services.plaid_sync_service.decrypt", side_effect=lambda c: c), \
         patch("backend.services.plaid_sync_service.plaid_client", client):
        yield client


def test_posted_rows_imported_with_plaid_prefix(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session)
    client = _client([_page(added=[
        _t("t1", "p-chk", date(2026, 4, 1), "-12.34", "COFFEE SHOP"),
        _t("t2", "p-card", date(2026, 4, 2), "-45.00", "GROCERY MART"),
        _t("t3", "p-unmapped", date(2026, 4, 2), "-9.99", "NOT LINKED"),
    ])])
    with _patched(client):
        report = sync_plaid_connection(db_session, conn)

    txn = db_session.query(models.Transaction).one()
    assert txn.external_id == "plaid:t1"
    assert txn.amount == Decimal("-12.34")
    assert txn.account_id == checking.id
    assert txn.source == models.TransactionSource.bank_sync
    ct = db_session.query(models.CreditCardTransaction).one()
    assert ct.external_id == "plaid:t2"
    assert ct.amount == Decimal("45.00")  # card convention: positive = charge
    assert ct.source == models.CardTransactionSource.bank_sync
    assert report.imported == 2
    assert conn.sync_cursor == "cur-1"
    client.sync_page.assert_called_once_with("tok-dan", "cur-0")


def test_pending_card_rows_snapshot_not_imported(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session)
    client = _client([
        _page(added=[
            _t("p1", "p-card", date(2026, 4, 3), "-20.00", "GAS STATION", pending=True),
            _t("p2", "p-chk", date(2026, 4, 3), "-7.00", "CHECKING PENDING", pending=True),
        ]),
        # A later delta that doesn't mention p1: it is still pending.
        _page(cursor="cur-2"),
        # Plaid removes the pending id once it posts.
        _page(removed=["p1"], cursor="cur-3"),
    ])
    with _patched(client):
        sync_plaid_connection(db_session, conn)
        assert db_session.query(models.CreditCardTransaction).count() == 0
        assert db_session.query(models.Transaction).count() == 0
        pend = db_session.query(models.CardPendingTransaction).one()
        assert pend.external_id == "plaid:p1"
        assert pend.amount == Decimal("20.00")
        assert card.pending_charges == Decimal("20.00")

        sync_plaid_connection(db_session, conn)
        assert db_session.query(models.CardPendingTransaction).count() == 1
        assert card.pending_charges == Decimal("20.00")

        sync_plaid_connection(db_session, conn)
        assert db_session.query(models.CardPendingTransaction).count() == 0
        assert card.pending_charges == Decimal("0")


def _seed_cutover_rows(db, user, checking):
    """An existing SimpleFIN row that Plaid will re-send under its own id."""
    existing = models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 3, 15), amount=Decimal("-30.00"),
        description="HARDWARE STORE 123", is_actual=True, source=models.TransactionSource.bank_sync,
        external_id="sf-1",
    )
    db.add(existing)
    db.commit()
    return existing


def _cutover_pages():
    return [_page(added=[
        _t("t1", "p-chk", date(2026, 3, 1), "-5.00", "OLD PURCHASE"),
        _t("t2", "p-chk", date(2026, 3, 15), "-30.00", "HARDWARE STORE 123"),
        _t("t3", "p-chk", date(2026, 3, 21), "-8.00", "BAKERY"),
    ])]


def test_first_import_ignores_old_matches_overlap_imports_rest(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session, cursor=None)
    existing = _seed_cutover_rows(db_session, user, checking)
    with _patched(_client(_cutover_pages())):
        report = sync_plaid_connection(db_session, conn, first_import=True)

    assert (report.imported, report.matched, report.ignored) == (1, 1, 1)
    outcomes = {r.description: r.outcome for r in report.rows}
    assert outcomes == {"OLD PURCHASE": "ignored", "HARDWARE STORE 123": "matched", "BAKERY": "imported"}
    db_session.refresh(existing)
    assert existing.alt_external_id == "plaid:t2"
    rows = db_session.query(models.Transaction).order_by(models.Transaction.id).all()
    assert [r.external_id for r in rows] == ["sf-1", "plaid:t3"]
    assert conn.sync_cursor == "cur-1"


def test_dry_run_writes_nothing(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session, cursor=None)
    existing = _seed_cutover_rows(db_session, user, checking)
    card.pending_charges = Decimal("15.00")
    db_session.commit()
    pages = _cutover_pages()
    pages[0].added.append(_t("p1", "p-card", date(2026, 3, 22), "-20.00", "GAS STATION", pending=True))
    client = _client(pages, accounts=[
        PlaidAccount(id="p-chk", name="Checking", mask="0001", type="depository", subtype="checking",
                     current=Decimal("999.00"), available=None, limit=None),
    ])
    before_txns = db_session.query(models.Transaction).count()
    before_cps = db_session.query(models.ForecastDayCheckpoint).count()

    with _patched(client):
        report = sync_plaid_connection(db_session, conn, first_import=True, dry_run=True)

    assert (report.imported, report.matched, report.ignored) == (1, 1, 1)
    db_session.expire_all()
    assert db_session.query(models.Transaction).count() == before_txns
    assert db_session.query(models.ForecastDayCheckpoint).count() == before_cps
    assert db_session.query(models.CardPendingTransaction).count() == 0
    assert db_session.get(models.BankConnection, conn.id).sync_cursor is None
    assert db_session.get(models.Account, checking.id).current_balance == Decimal("100.00")
    assert db_session.get(models.CreditCard, card.id).pending_charges == Decimal("15.00")
    assert db_session.get(models.Transaction, existing.id).alt_external_id is None
    client.refresh_transactions.assert_not_called()
    client.get_accounts.assert_not_called()


def test_modified_updates_in_place(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session)
    txn = models.Transaction(user_id=user.id, account_id=checking.id, date=date(2026, 4, 1),
                             amount=Decimal("-10.00"), description="CAFE", is_actual=True,
                             external_id="plaid:m1")
    ct = models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 4, 1),
                                      amount=Decimal("20.00"), merchant="STORE", alt_external_id="plaid:m2",
                                      external_id="sf-9")
    db_session.add_all([txn, ct])
    db_session.commit()
    client = _client([_page(modified=[
        _t("m1", "p-chk", date(2026, 4, 2), "-11.50", "CAFE DOWNTOWN"),
        _t("m2", "p-card", date(2026, 4, 3), "-25.00", "STORE TWO"),
        _t("m3", "p-chk", date(2026, 4, 4), "-3.00", "NEVER SEEN"),  # not stored: treated as added
    ])])
    with _patched(client):
        report = sync_plaid_connection(db_session, conn)

    db_session.refresh(txn)
    db_session.refresh(ct)
    assert (txn.date, txn.amount, txn.description) == (date(2026, 4, 2), Decimal("-11.50"), "CAFE DOWNTOWN")
    assert (ct.date, ct.amount, ct.merchant) == (date(2026, 4, 3), Decimal("25.00"), "STORE TWO")
    assert db_session.query(models.Transaction).filter_by(external_id="plaid:m3").count() == 1
    assert db_session.query(models.Transaction).count() == 2
    assert report.imported == 1


def test_removed_deletes_unless_user_edited(db_session, caplog):
    user, checking, savings, card, conn = _make_plaid_connection(db_session)
    noted = models.Transaction(user_id=user.id, account_id=checking.id, date=date(2026, 4, 1),
                               amount=Decimal("-40.00"), description="DINNER", notes="split with a friend",
                               is_actual=True, external_id="plaid:r1")
    plain = models.Transaction(user_id=user.id, account_id=checking.id, date=date(2026, 4, 1),
                               amount=Decimal("-6.00"), description="SNACK", is_actual=True,
                               external_id="plaid:r2")
    card_plain = models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 4, 1),
                                              amount=Decimal("12.00"), merchant="BOOKS", external_id="sf-3",
                                              alt_external_id="plaid:r3")
    card_edited = models.CreditCardTransaction(user_id=user.id, card_id=card.id, date=date(2026, 4, 1),
                                               amount=Decimal("18.00"), merchant="TOY SHOP",
                                               description="birthday present", external_id="plaid:r4")
    db_session.add_all([noted, plain, card_plain, card_edited])
    db_session.commit()
    ids = {"noted": noted.id, "plain": plain.id, "card_plain": card_plain.id, "card_edited": card_edited.id}

    with _patched(_client([_page(removed=["r1", "r2", "r3", "r4"])])), caplog.at_level("WARNING"):
        sync_plaid_connection(db_session, conn)

    db_session.expire_all()
    assert db_session.get(models.Transaction, ids["noted"]) is not None
    assert db_session.get(models.Transaction, ids["plain"]) is None
    assert db_session.get(models.CreditCardTransaction, ids["card_plain"]) is None
    assert db_session.get(models.CreditCardTransaction, ids["card_edited"]) is not None
    assert str(ids["noted"]) in caplog.text
    assert "split with a friend" not in caplog.text


def test_page_error_keeps_cursor(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session)
    client = _client([
        _page(added=[_t("t1", "p-chk", date(2026, 4, 1), "-12.34", "COFFEE SHOP")], cursor="cur-1", has_more=True),
        PlaidError("INTERNAL_SERVER_ERROR", "something broke"),
    ])
    with _patched(client), pytest.raises(PlaidError):
        sync_plaid_connection(db_session, conn)

    db_session.expire_all()
    stored = db_session.get(models.BankConnection, conn.id)
    assert stored.sync_cursor == "cur-0"
    assert db_session.query(models.Transaction).count() == 0
    assert stored.status == models.BankConnectionStatus.error
    assert stored.last_error == "INTERNAL_SERVER_ERROR: something broke"


def test_rate_limit_before_commit_leaves_state_untouched(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session)
    client = _client([_page(added=[_t("t1", "p-chk", date(2026, 4, 1), "-12.34", "COFFEE SHOP")])])
    client.get_accounts.side_effect = PlaidRateLimited("RATE_LIMIT_EXCEEDED", "slow down")
    with _patched(client), pytest.raises(PlaidRateLimited):
        sync_plaid_connection(db_session, conn)

    db_session.expire_all()
    stored = db_session.get(models.BankConnection, conn.id)
    assert stored.sync_cursor == "cur-0"
    assert stored.status == models.BankConnectionStatus.active
    assert stored.last_error == "Plaid rate limit reached; will retry next run"
    assert db_session.query(models.Transaction).count() == 0


def test_login_required_sets_error_message(db_session):
    _, _, _, _, broken = _make_plaid_connection(db_session, "dan", token="tok-a")
    _, other_checking, _, _, healthy = _make_plaid_connection(db_session, "sam", token="tok-b")

    def sync_page(token, cursor):
        if token == "tok-a":
            raise PlaidError("ITEM_LOGIN_REQUIRED", "the login details of this item have changed")
        return _page(added=[_t("t1", "p-chk", date(2026, 4, 1), "-12.34", "COFFEE SHOP")])

    client = _client()
    client.sync_page.side_effect = sync_page
    with _patched(client):
        sync_all(db_session)

    db_session.expire_all()
    broken = db_session.get(models.BankConnection, broken.id)
    healthy = db_session.get(models.BankConnection, healthy.id)
    assert broken.status == models.BankConnectionStatus.error
    assert broken.last_error == "Chase needs you to log in again. Use Reconnect in Settings → Accounts."
    assert "tok-a" not in broken.last_error
    assert healthy.status == models.BankConnectionStatus.active
    assert healthy.sync_cursor == "cur-1"
    assert db_session.query(models.Transaction).filter_by(account_id=other_checking.id).count() == 1


def _statement(issue, balance="321.00"):
    return PlaidCardStatement(account_id="p-card", last_statement_balance=Decimal(balance),
                              last_statement_issue_date=issue, next_payment_due_date=date(2026, 5, 1),
                              minimum_payment_amount=Decimal("35.00"))


def test_new_statement_sets_balance_due(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session)
    card.balance_due = Decimal("100.00")
    card.last_statement_issue_date = date(2026, 3, 5)
    db_session.commit()
    with _patched(_client([_page()], statements=[_statement(date(2026, 4, 5))])):
        sync_plaid_connection(db_session, conn)

    db_session.refresh(card)
    assert card.balance_due == Decimal("321.00")
    assert card.last_statement_issue_date == date(2026, 4, 5)
    assert card.next_payment_date == date(2026, 5, 1)
    assert card.minimum_payment_amount == Decimal("35.00")
    assert card.balance_due_updated_at is not None


def test_same_statement_keeps_reduced_balance_due(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session)
    # record_payment already brought the statement balance down.
    card.balance_due = Decimal("50.00")
    card.last_statement_issue_date = date(2026, 4, 5)
    db_session.commit()
    with _patched(_client([_page()], statements=[_statement(date(2026, 4, 5))])):
        sync_plaid_connection(db_session, conn)

    db_session.refresh(card)
    assert card.balance_due == Decimal("50.00")
    assert card.balance_due_updated_at is None
    assert card.minimum_payment_amount is None


def test_card_balance_not_sign_flipped(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session)
    accounts = [
        PlaidAccount(id="p-card", name="Visa", mask="1234", type="credit", subtype="credit card",
                     current=Decimal("250.00"), available=None, limit=Decimal("5000.00")),
        PlaidAccount(id="p-chk", name="Checking", mask="0001", type="depository", subtype="checking",
                     current=Decimal("1234.56"), available=None, limit=None),
        PlaidAccount(id="p-sav", name="Savings", mask="0002", type="depository", subtype="savings",
                     current=Decimal("777.00"), available=None, limit=None),
    ]
    last_update = datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc)
    with _patched(_client([_page()], accounts=accounts, last_update=last_update)):
        sync_plaid_connection(db_session, conn)

    db_session.refresh(card)
    assert card.current_balance == Decimal("250.00")
    assert card.balance_as_of == datetime(2026, 4, 6, 14, 0)  # stored UTC-naive
    assert checking.current_balance == Decimal("1234.56")
    assert savings.current_balance == Decimal("777.00")
    cp = db_session.query(models.ForecastDayCheckpoint).one()
    assert (cp.account_id, cp.date, cp.actual_balance) == (checking.id, date(2026, 4, 6), Decimal("1234.56"))


def test_refresh_called_after_commit(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session)
    calls = []
    real_commit = db_session.commit

    def commit():
        calls.append("commit")
        real_commit()

    client = _client([_page(), _page(cursor="cur-2")])
    client.refresh_transactions.side_effect = lambda token: calls.append("refresh")
    with _patched(client), patch.object(db_session, "commit", side_effect=commit):
        sync_plaid_connection(db_session, conn)
    assert calls[-2:] == ["commit", "refresh"]
    client.refresh_transactions.assert_called_once_with("tok-dan")

    # A rate-limited refresh is logged and ignored: the sync still succeeded.
    client.refresh_transactions.side_effect = PlaidRateLimited("RATE_LIMIT_EXCEEDED", "slow down")
    with _patched(client):
        sync_plaid_connection(db_session, conn)
    db_session.expire_all()
    stored = db_session.get(models.BankConnection, conn.id)
    assert stored.sync_cursor == "cur-2"
    assert stored.status == models.BankConnectionStatus.active
    assert stored.last_error is None


def test_sync_connection_skips_plaid_without_cursor(db_session):
    user, checking, savings, card, conn = _make_plaid_connection(db_session, cursor=None)
    client = _client([_page(added=[_t("t1", "p-chk", date(2026, 4, 1), "-12.34", "COFFEE SHOP")])])
    with _patched(client):
        assert sync_connection(db_session, conn) == (0, 0)
    client.sync_page.assert_not_called()
    assert conn.last_synced_at is None

    conn.sync_cursor = "cur-0"
    db_session.commit()
    with _patched(client):
        imported, _ = sync_connection(db_session, conn)
    assert imported == 1
    client.sync_page.assert_called_once()
