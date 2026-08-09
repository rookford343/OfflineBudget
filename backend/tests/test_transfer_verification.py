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


def test_one_real_transaction_cannot_verify_two_transfers(db_session):
    """Two scheduled transfers near the same date, one real deposit. The
    deposit can only close out one of them -- claiming it twice would mark a
    transfer done that never happened, and leave both rows pointing at the
    same verified_transaction_id."""
    user, checking, savings = _make_user_and_accounts(db_session)
    first = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    )
    second = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 17),
        status=models.PlannedTransferStatus.scheduled,
    )
    db_session.add_all([first, second])
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

    db_session.refresh(first)
    db_session.refresh(second)
    assert verified_count == 1
    statuses = sorted([first.status, second.status], key=lambda s: s.value)
    assert statuses == [
        models.PlannedTransferStatus.scheduled,
        models.PlannedTransferStatus.verified,
    ]
    claimed = [t.verified_transaction_id for t in (first, second) if t.verified_transaction_id]
    assert claimed == [real_txn.id]


def test_a_transaction_already_claimed_in_a_prior_run_is_not_reused(db_session):
    """The exclusion has to survive across runs, not just within one loop."""
    user, checking, savings = _make_user_and_accounts(db_session)
    real_txn = models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 9, 16),
        amount=Decimal("22000.00"), description="Online Transfer from SAV",
        is_actual=True, source=models.TransactionSource.bank_sync,
    )
    db_session.add(real_txn)
    db_session.flush()
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.verified,
        verified_transaction_id=real_txn.id,
    ))
    late = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 18),
        status=models.PlannedTransferStatus.scheduled,
    )
    db_session.add(late)
    db_session.commit()

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(late)
    assert verified_count == 0
    assert late.status == models.PlannedTransferStatus.scheduled
    assert late.verified_transaction_id is None


def test_a_recurring_paycheck_does_not_verify_a_transfer(db_session):
    """A deposit already recognized as a recurring item (a paycheck) is never
    a manual planned transfer, even when it lands inside the amount and date
    tolerance."""
    user, checking, savings = _make_user_and_accounts(db_session)
    paycheck_item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Paycheck",
        amount=Decimal("22000.00"), type=models.RecurringType.income,
        day_of_month=15, frequency=models.RecurringFrequency.monthly,
        start_date=date(2026, 1, 1), is_active=True, include_in_forecast=True,
    )
    db_session.add(paycheck_item)
    db_session.flush()
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    )
    db_session.add(transfer)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 9, 15),
        amount=Decimal("22000.00"), description="ACME PAYROLL DIRECT DEP",
        is_actual=True, source=models.TransactionSource.bank_sync,
        recurring_item_id=paycheck_item.id,
    ))
    db_session.commit()

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(transfer)
    assert verified_count == 0
    assert transfer.status == models.PlannedTransferStatus.scheduled
    assert transfer.verified_transaction_id is None


def test_unlinked_deposit_alongside_a_paycheck_still_verifies(db_session):
    """The recurring-item exclusion must not block a genuine match when a
    paycheck happens to share the window."""
    user, checking, savings = _make_user_and_accounts(db_session)
    paycheck_item = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Paycheck",
        amount=Decimal("22000.00"), type=models.RecurringType.income,
        day_of_month=15, frequency=models.RecurringFrequency.monthly,
        start_date=date(2026, 1, 1), is_active=True, include_in_forecast=True,
    )
    db_session.add(paycheck_item)
    db_session.flush()
    transfer = models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    )
    db_session.add(transfer)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 9, 15),
        amount=Decimal("22000.00"), description="ACME PAYROLL DIRECT DEP",
        is_actual=True, source=models.TransactionSource.bank_sync,
        recurring_item_id=paycheck_item.id,
    ))
    real_transfer_txn = models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 9, 16),
        amount=Decimal("22000.00"), description="Online Transfer from SAV",
        is_actual=True, source=models.TransactionSource.bank_sync,
    )
    db_session.add(real_transfer_txn)
    db_session.commit()
    db_session.refresh(real_transfer_txn)

    verified_count = verify_scheduled_transfers(db_session, user.id)

    db_session.refresh(transfer)
    assert verified_count == 1
    assert transfer.verified_transaction_id == real_transfer_txn.id
