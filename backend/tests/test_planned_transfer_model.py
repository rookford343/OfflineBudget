from datetime import date
from decimal import Decimal
from backend import models


def _make_user_and_accounts(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db.add_all([checking, savings])
    db.flush()
    return user, checking, savings


def test_planned_transfer_round_trip_defaults(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 12),
    )
    db_session.add(transfer)
    db_session.commit()
    db_session.refresh(transfer)

    assert transfer.status == models.PlannedTransferStatus.pending
    assert transfer.suggested is False
    assert transfer.verified_transaction_id is None


def test_planned_transfer_from_account_is_nullable(db_session):
    """No savings account, or an ambiguous choice -- from_account_id stays
    unset rather than guessing wrong (per spec's error-handling section)."""
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, to_account_id=checking.id,
        amount=Decimal("5000.00"), target_date=date(2026, 9, 12),
    )
    db_session.add(transfer)
    db_session.commit()
    db_session.refresh(transfer)

    assert transfer.from_account_id is None


def test_user_transfer_increment_defaults_to_1000(db_session):
    user = models.User(username="t2", hashed_password="x", display_name="T2")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.transfer_increment == Decimal("1000.00")


def test_user_transfer_increment_is_settable(db_session):
    user = models.User(username="t3", hashed_password="x", display_name="T3", transfer_increment=Decimal("500.00"))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.transfer_increment == Decimal("500.00")
