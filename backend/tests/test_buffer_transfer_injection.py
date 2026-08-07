from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast


def _make_user_accounts(db):
    user = models.User(username="t3", hashed_password="x", display_name="T3")
    db.add(user)
    db.flush()
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings, current_balance=Decimal("10000.00"))
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("500.00"))
    db.add_all([savings, checking])
    db.flush()
    return user, savings, checking


def _make_rule(db, user, savings, checking):
    rule = models.BufferTransferRule(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        action_threshold=Decimal("100"), target_floor=Decimal("200"),
        increment=Decimal("1000"), check_day=1,
    )
    db.add(rule)
    db.flush()
    return rule


def _add_big_bill(db, user, checking):
    db.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Big Bill", amount=Decimal("3125.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    ))


def test_no_rule_means_no_behavior_change(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    _add_big_bill(db_session, user, checking)
    db_session.commit()

    with_flag = build_forecast(db_session, user.id, checking.id, date(2026, 7, 1), date(2026, 7, 31))
    without_flag = build_forecast(db_session, user.id, checking.id, date(2026, 7, 1), date(2026, 7, 31), apply_buffer_transfers=False)

    assert [e.projected_balance for e in with_flag] == [e.projected_balance for e in without_flag]
    assert not any(t.is_transfer for e in with_flag for t in e.transactions)


def test_transfer_injected_on_checking_when_rule_active(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    _make_rule(db_session, user, savings, checking)
    _add_big_bill(db_session, user, checking)
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 7, 1), date(2026, 7, 31))

    jul1 = next(e for e in entries if e.date == date(2026, 7, 1))
    transfer_txns = [t for t in jul1.transactions if t.is_transfer]
    assert len(transfer_txns) == 1
    assert transfer_txns[0].amount == Decimal("3000.00")
    assert transfer_txns[0].name == "Transfer from Savings"

    jul15 = next(e for e in entries if e.date == date(2026, 7, 15))
    # $500 open + $3,000 transfer - $3,125 bill = $375, never dips negative.
    assert jul15.projected_balance == Decimal("375.00")


def test_transfer_mirrored_as_outflow_on_savings(db_session):
    user, savings, checking = _make_user_accounts(db_session)
    _make_rule(db_session, user, savings, checking)
    _add_big_bill(db_session, user, checking)
    db_session.commit()

    savings_entries = build_forecast(db_session, user.id, savings.id, date(2026, 7, 1), date(2026, 7, 31))

    jul1 = next(e for e in savings_entries if e.date == date(2026, 7, 1))
    transfer_txns = [t for t in jul1.transactions if t.is_transfer]
    assert len(transfer_txns) == 1
    assert transfer_txns[0].amount == Decimal("-3000.00")
    assert transfer_txns[0].name == "Transfer to Main Checking"
    assert jul1.projected_balance == Decimal("7000.00")  # $10,000 - $3,000
