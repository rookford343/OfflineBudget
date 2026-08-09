from datetime import date
from decimal import Decimal
from backend import models
from backend.services.transfer_verification import verify_scheduled_transfers


def _make_user_and_accounts(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db.add_all([checking, savings])
    db.flush()
    return user, checking, savings


def test_matching_real_transaction_verifies_the_transfer(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    )
    db_session.add(transfer)
    db_session.flush()
    real_txn = models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 9, 16),
        amount=Decimal("22000.00"), description="Online Transfer from SAV",
        is_actual=True, source=models.TransactionSource.bank_sync,
    )
    db_session.add(real_txn)
    db_session.commit()
    db_session.refresh(real_txn)

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(transfer)
    assert verified_count == 1
    assert transfer.status == models.PlannedTransferStatus.verified
    assert transfer.verified_transaction_id == real_txn.id


def test_no_match_outside_date_window_stays_scheduled(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    )
    db_session.add(transfer)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 10, 1),  # 16 days late
        amount=Decimal("22000.00"), description="Unrelated deposit",
        is_actual=True, source=models.TransactionSource.bank_sync,
    ))
    db_session.commit()

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(transfer)
    assert verified_count == 0
    assert transfer.status == models.PlannedTransferStatus.scheduled


def test_no_match_outside_amount_tolerance_stays_scheduled(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    )
    db_session.add(transfer)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 9, 15),
        amount=Decimal("5000.00"),  # far outside 5% tolerance
        description="Small deposit", is_actual=True, source=models.TransactionSource.bank_sync,
    ))
    db_session.commit()

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(transfer)
    assert verified_count == 0
    assert transfer.status == models.PlannedTransferStatus.scheduled


def test_pending_transfers_are_not_checked(db_session):
    """Only scheduled transfers get auto-verified -- a pending one hasn't
    even been confirmed as executed yet, so there's nothing to verify."""
    user, checking, savings = _make_user_and_accounts(db_session)
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.pending,
    )
    db_session.add(transfer)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 9, 15),
        amount=Decimal("22000.00"), description="Online Transfer from SAV",
        is_actual=True, source=models.TransactionSource.bank_sync,
    ))
    db_session.commit()

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(transfer)
    assert verified_count == 0
    assert transfer.status == models.PlannedTransferStatus.pending
