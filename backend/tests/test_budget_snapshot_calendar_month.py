"""Left to Spend counts card spending by CALENDAR MONTH (2026-10-30).

left_to_spend = leftover - card_spending_this_month - pending_charges_total
                + charged_so_far

card_spending_this_month is the sum of posted CreditCardTransaction rows on
active cards dated from the 1st of as_of's month through as_of: charges add,
returns subtract, card payments are excluded. It used to be "spending since
each card's last statement" (current_balance - balance_due + pending), which
jumped up the moment a statement closed late in the month. All figures here
are invented.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from backend import models
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.explain import children_consistent, replay
from backend.tests.test_budget_snapshot import _fake_quarter_min


def _seed(db, username="calmonth", *, current_balance="0.00", balance_due="0.00", pending="0.00"):
    user = models.User(username=username, hashed_password="x", display_name=username)
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Test Visa", credit_limit=Decimal("10000.00"),
        statement_day=28, due_day=25,
        current_balance=Decimal(current_balance), balance_due=Decimal(balance_due),
        pending_charges=Decimal(pending), next_payment_date=date(2026, 11, 25),
    )
    db.add_all([checking, card])
    db.flush()
    return user, checking, card


def _txn(db, card, d, amount, merchant="SOME STORE"):
    db.add(models.CreditCardTransaction(
        card_id=card.id, user_id=card.user_id, date=d,
        amount=Decimal(amount), merchant=merchant,
    ))


def _snap(db, user, checking, as_of):
    db.commit()
    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("3000.00")):
        return compute_budget_snapshot(db, user, checking.id, as_of=as_of)


def test_last_months_purchases_are_excluded_and_this_months_included(db_session):
    user, checking, card = _seed(db_session)
    _txn(db_session, card, date(2026, 9, 30), "400.00")   # last month: ignored
    _txn(db_session, card, date(2026, 10, 1), "100.00")
    _txn(db_session, card, date(2026, 10, 9), "50.00")
    _txn(db_session, card, date(2026, 10, 11), "999.00")  # after as_of: ignored

    snap = _snap(db_session, user, checking, date(2026, 10, 10))

    assert snap.left_to_spend == snap.leftover - Decimal("150.00")


def test_a_return_this_month_subtracts(db_session):
    user, checking, card = _seed(db_session)
    _txn(db_session, card, date(2026, 10, 2), "200.00")
    _txn(db_session, card, date(2026, 10, 6), "-30.00", merchant="SOME STORE RETURN")

    snap = _snap(db_session, user, checking, date(2026, 10, 10))

    assert snap.left_to_spend == snap.leftover - Decimal("170.00")


def test_card_payment_credits_are_excluded(db_session):
    user, checking, card = _seed(db_session)
    _txn(db_session, card, date(2026, 10, 2), "80.00")
    _txn(db_session, card, date(2026, 10, 5), "-1500.00", merchant="AUTOMATIC PAYMENT - THANK YOU")
    _txn(db_session, card, date(2026, 10, 6), "-700.00", merchant="Payment Thank You")
    _txn(db_session, card, date(2026, 10, 7), "-250.00",
         merchant="ACH DEPOSIT INTERNET TRANSFER FROM ACCOUNT ENDING IN 0000")

    snap = _snap(db_session, user, checking, date(2026, 10, 10))

    assert snap.left_to_spend == snap.leftover - Decimal("80.00")


def test_pending_is_counted_once(db_session):
    user, checking, card = _seed(db_session, pending="45.00")
    _txn(db_session, card, date(2026, 10, 3), "60.00")

    snap = _snap(db_session, user, checking, date(2026, 10, 10))

    assert snap.left_to_spend == snap.leftover - Decimal("60.00") - Decimal("45.00")


def test_a_recurring_card_bill_charged_this_month_is_not_double_counted(db_session):
    """The subscription sits in leftover as a bill, in card spending as a
    posted transaction, and is added back by charged_so_far -- net, it is
    counted exactly once (as the bill), same as before it posted."""
    user, checking, card = _seed(db_session)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, card_id=card.id, name="Streaming",
        amount=Decimal("15.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=5,
        start_date=date(2026, 1, 1),
    ))

    before = _snap(db_session, user, checking, date(2026, 10, 4))
    _txn(db_session, card, date(2026, 10, 5), "15.00", merchant="STREAMING")
    after = _snap(db_session, user, checking, date(2026, 10, 10))

    assert after.leftover == before.leftover == Decimal("-15.00")
    assert after.left_to_spend == before.left_to_spend == Decimal("-15.00")


def test_a_statement_closing_mid_month_does_not_change_left_to_spend(db_session):
    """Closes on the 28th. Before the close the purchases are current-cycle
    spending; after it they're the statement balance. Left to Spend on the
    29th must still count Oct 1-28's purchases."""
    user, checking, card = _seed(db_session, current_balance="300.00", balance_due="0.00")
    _txn(db_session, card, date(2026, 10, 3), "100.00")
    _txn(db_session, card, date(2026, 10, 20), "200.00")
    before_close = _snap(db_session, user, checking, date(2026, 10, 27))

    card.balance_due = Decimal("300.00")   # statement closed on the 28th
    after_close = _snap(db_session, user, checking, date(2026, 10, 29))

    assert after_close.left_to_spend == before_close.left_to_spend == before_close.leftover - Decimal("300.00")


def test_inactive_cards_are_ignored(db_session):
    user, checking, card = _seed(db_session)
    _txn(db_session, card, date(2026, 10, 3), "25.00")
    old = models.CreditCard(
        user_id=user.id, name="Closed Card", credit_limit=Decimal("1000.00"),
        statement_day=10, due_day=5, is_active=False,
        current_balance=Decimal("500.00"), pending_charges=Decimal("40.00"),
    )
    db_session.add(old)
    db_session.flush()
    _txn(db_session, old, date(2026, 10, 4), "500.00")

    snap = _snap(db_session, user, checking, date(2026, 10, 10))

    assert snap.left_to_spend == snap.leftover - Decimal("25.00")


def test_explain_rows_sum_to_left_to_spend(db_session):
    user, checking, card = _seed(db_session, pending="12.00")
    second = models.CreditCard(
        user_id=user.id, name="Other Card", credit_limit=Decimal("5000.00"),
        statement_day=1, due_day=20, pending_charges=Decimal("8.00"),
    )
    db_session.add(second)
    db_session.flush()
    _txn(db_session, card, date(2026, 10, 3), "70.00")
    _txn(db_session, card, date(2026, 10, 4), "-10.00", merchant="SOME STORE RETURN")
    _txn(db_session, second, date(2026, 10, 5), "33.00")
    _txn(db_session, second, date(2026, 10, 6), "-900.00", merchant="AUTOMATIC PAYMENT - THANK YOU")

    snap = _snap(db_session, user, checking, date(2026, 10, 10))
    ex = snap.explain["left_to_spend"]

    assert [r.op for r in ex.rows] == ["start", "subtract", "subtract", "add", "result"]
    labels = [r.label for r in ex.rows]
    assert "Card spending this month" in labels and "Pending charges" in labels
    assert "New card spending" not in labels
    spending = next(r for r in ex.rows if r.label == "Card spending this month")
    assert spending.amount == Decimal("93.00")
    assert {c.label: c.amount for c in spending.children} == {
        "Test Visa: purchases since Oct 1": Decimal("60.00"),
        "Other Card: purchases since Oct 1": Decimal("33.00"),
    }
    pending = next(r for r in ex.rows if r.label == "Pending charges")
    assert pending.amount == Decimal("20.00")
    assert ex.result == snap.left_to_spend == snap.leftover - Decimal("113.00")
    assert replay(ex) == snap.left_to_spend
    assert children_consistent(ex)
