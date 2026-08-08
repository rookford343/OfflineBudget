from datetime import date
from decimal import Decimal
from backend import models


def _make_user(db):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db.add(user)
    db.flush()
    return user


def test_bank_connection_round_trip(db_session):
    user = _make_user(db_session)
    connection = models.BankConnection(user_id=user.id, access_url_encrypted="ciphertext")
    db_session.add(connection)
    db_session.flush()

    link = models.BankConnectionAccountLink(
        connection_id=connection.id,
        simplefin_account_id="acc-1",
        simplefin_account_name="Chase Checking",
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(connection)

    assert connection.status == models.BankConnectionStatus.active
    assert len(connection.links) == 1
    assert connection.links[0].simplefin_account_id == "acc-1"


def test_disconnect_cascades_links(db_session):
    user = _make_user(db_session)
    connection = models.BankConnection(user_id=user.id, access_url_encrypted="x")
    db_session.add(connection)
    db_session.flush()
    link = models.BankConnectionAccountLink(connection_id=connection.id, simplefin_account_id="a", simplefin_account_name="A")
    db_session.add(link)
    db_session.commit()

    db_session.delete(connection)
    db_session.commit()

    assert db_session.query(models.BankConnectionAccountLink).count() == 0


def test_bank_sync_transaction_source_persists(db_session):
    user = _make_user(db_session)
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db_session.add(account)
    db_session.flush()

    txn = models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 1),
        amount=Decimal("-10.00"), description="Test", source=models.TransactionSource.bank_sync,
    )
    db_session.add(txn)
    db_session.commit()

    assert txn.source == models.TransactionSource.bank_sync


def test_bank_sync_card_transaction_source_persists(db_session):
    user = _make_user(db_session)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("5000"), statement_day=15, due_day=1)
    db_session.add(card)
    db_session.flush()

    ct = models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 1),
        amount=Decimal("25.00"), merchant="Test Merchant", source=models.CardTransactionSource.bank_sync,
    )
    db_session.add(ct)
    db_session.commit()

    assert ct.source == models.CardTransactionSource.bank_sync
