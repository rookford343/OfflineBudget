from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast


def _make_user_and_accounts(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("1000.00"))
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("30000.00"))
    db.add_all([checking, savings])
    db.flush()
    return user, checking, savings


def test_pending_transfer_injects_on_target_date_both_accounts(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("5000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.pending,
    ))
    db_session.commit()

    checking_entries = build_forecast(db_session, user.id, checking.id, date(2026, 9, 1), date(2026, 9, 30))
    sep15_checking = next(e for e in checking_entries if e.date == date(2026, 9, 15))
    transfer_txns = [t for t in sep15_checking.transactions if t.is_transfer]
    assert len(transfer_txns) == 1
    assert transfer_txns[0].amount == Decimal("5000.00")

    savings_entries = build_forecast(db_session, user.id, savings.id, date(2026, 9, 1), date(2026, 9, 30))
    sep15_savings = next(e for e in savings_entries if e.date == date(2026, 9, 15))
    savings_transfer_txns = [t for t in sep15_savings.transactions if t.is_transfer]
    assert len(savings_transfer_txns) == 1
    assert savings_transfer_txns[0].amount == Decimal("-5000.00")


def test_scheduled_transfer_also_injects(db_session):
    user, checking, savings = _make_user_and_accounts(db_session)
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("2000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.scheduled,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 9, 1), date(2026, 9, 30))
    sep15 = next(e for e in entries if e.date == date(2026, 9, 15))
    assert any(t.is_transfer for t in sep15.transactions)


def test_verified_transfer_does_not_inject(db_session):
    """A verified transfer's real transaction is already in the actuals
    feed -- injecting it too would double-count."""
    user, checking, savings = _make_user_and_accounts(db_session)
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        amount=Decimal("2000.00"), target_date=date(2026, 9, 15),
        status=models.PlannedTransferStatus.verified,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 9, 1), date(2026, 9, 30))
    sep15 = next(e for e in entries if e.date == date(2026, 9, 15))
    assert not any(t.is_transfer for t in sep15.transactions)
