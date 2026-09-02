from datetime import date, timedelta
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


def test_cc_payment_injection_excludes_pending_charges(db_session):
    """Corrected 2026-08-09 after reading Dan's real spreadsheet directly:
    the forecast's payoff projection pays off only balance_due (the last
    closed statement), matching "2026 Forecast" row 24
    ("=L23-9273.76-180.16" -- no pending-charges term). pending_charges is
    counted exactly once, downstream, via
    budget_snapshot.py's new_spending_total. Including it here too used to
    double-count it.

    Dates relative to date.today() rather than hardcoded 2026-08 values --
    hardcoded dates rotted here once wall-clock time passed them: a fixed
    August query window stopped containing next_payment_date's rollforward
    target once "today" moved past August entirely, so the payoff was never
    found rather than found-with-the-wrong-amount. Same root cause as
    forecast_engine.py's _UNCONFIRMED_LOOKBACK_DAYS fix (2026-09-02) --
    this test just needs to stay valid regardless of which day it runs,
    not exercise that fix directly."""
    today = date.today()
    due_date = today + timedelta(days=10)  # in the future -- next_payment_date is not stale
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=due_date.day, due_day=due_date.day, balance_due=Decimal("1000.00"),
        next_payment_date=due_date, pending_charges=Decimal("250.00"),
    )
    db_session.add(card)
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, today, today + timedelta(days=40))

    due_entry = next(e for e in entries if e.date == due_date)
    cc_txns = [t for t in due_entry.transactions if t.is_cc_payment]
    assert len(cc_txns) == 1
    assert cc_txns[0].amount == Decimal("-1000.00")  # balance_due only, pending_charges excluded


def test_cc_payment_injection_unaffected_when_pending_charges_zero(db_session):
    today = date.today()
    due_date = today + timedelta(days=10)
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=due_date.day, due_day=due_date.day, balance_due=Decimal("1000.00"),
        next_payment_date=due_date,
    )
    db_session.add(card)
    db_session.commit()

    entries = build_forecast(db_session, user.id, checking.id, today, today + timedelta(days=40))

    due_entry = next(e for e in entries if e.date == due_date)
    cc_txns = [t for t in due_entry.transactions if t.is_cc_payment]
    assert cc_txns[0].amount == Decimal("-1000.00")  # unchanged from today's behavior
