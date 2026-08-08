from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast


def _make_user_and_checking(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("5000.00"))
    db.add(checking)
    db.flush()
    return user, checking


def test_cc_payment_injection_includes_pending_charges(db_session):
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25, balance_due=Decimal("1000.00"),
        next_payment_date=date(2026, 8, 25), pending_charges=Decimal("250.00"),
    )
    db_session.add(card)
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 8, 1), date(2026, 8, 31))

    aug25 = next(e for e in entries if e.date == date(2026, 8, 25))
    cc_txns = [t for t in aug25.transactions if t.is_cc_payment]
    assert len(cc_txns) == 1
    assert cc_txns[0].amount == Decimal("-1250.00")  # balance_due + pending_charges


def test_cc_payment_injection_unaffected_when_pending_charges_zero(db_session):
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25, balance_due=Decimal("1000.00"),
        next_payment_date=date(2026, 8, 25),
    )
    db_session.add(card)
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, date(2026, 8, 1), date(2026, 8, 31))

    aug25 = next(e for e in entries if e.date == date(2026, 8, 25))
    cc_txns = [t for t in aug25.transactions if t.is_cc_payment]
    assert cc_txns[0].amount == Decimal("-1000.00")  # unchanged from today's behavior
