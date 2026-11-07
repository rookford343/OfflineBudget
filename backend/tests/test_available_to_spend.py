"""Available to Spend, "before budgets", on the shared layer.

This month's income - bills - one-offs - real spending so far, with no
Groceries or Savings budget; its second explanation walks to Left to Spend.
Dates are pinned (forecast_engine reads date.today()). All figures invented.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from backend import models
from backend.routers.spending import available_to_spend as available_route
from backend.services.available_to_spend import available_to_spend
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.explain import children_consistent, replay
from backend.tests.test_month_leftover_parity import BOOST, NET, _budget, _seed as _ss_seed
from backend.tests.test_parity_headline import _headline_fixture, _pin_today

D = Decimal
TODAY = date(2026, 11, 12)


@pytest.fixture(autouse=True)
def _pinned(monkeypatch):
    _pin_today(monkeypatch, TODAY)


def _seed(db):
    user = models.User(username="a", hashed_password="x", display_name="A")
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                          current_balance=D("2000.00"))
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=D("5000"),
                             statement_day=28, due_day=15)
    db.add_all([acct, card])
    db.flush()
    db.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Rent", amount=D("1000.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1), is_active=True))
    db.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Pay", amount=D("5000.00"),
        type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=date(2026, 1, 1), is_active=True))
    db.commit()
    return user, acct, card


def _debit(db, user, acct, description, amount, day=10, **kw):
    db.add(models.Transaction(
        user_id=user.id, account_id=acct.id, date=date(2026, 11, day),
        amount=-D(amount), description=description, is_actual=True, **kw))
    db.commit()


def _card_row(db, user, card, merchant, amount, day=10):
    db.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 11, day),
        amount=D(amount), merchant=merchant))
    db.commit()


def _ats(db, user, as_of=TODAY):
    return available_to_spend(db, user, as_of)


def test_first_of_month_nothing_spent(db_session):
    user, acct, card = _seed(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=acct.id, name="Tires", amount=D("300.00"),
        expected_date=date(2026, 11, 20)))
    db_session.commit()

    r = _ats(db_session, user, as_of=date(2026, 11, 1))
    assert r.spent_this_month == D("0")
    assert r.monthly_income == D("5000.00")
    assert r.committed_expenses == D("1000.00")
    assert r.one_offs_net == D("300.00")
    assert r.available == D("5000.00") - D("1000.00") - D("300.00")


def test_refund_lowers_spent_not_income(db_session):
    user, acct, card = _seed(db_session)
    _debit(db_session, user, acct, "COFFEE SHOP", "63.00", day=3)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, date=date(2026, 11, 5), amount=D("20.00"),
        description="COFFEE SHOP", is_actual=True))
    db_session.commit()

    r = _ats(db_session, user)
    assert r.spent_this_month == D("43.00")
    assert r.monthly_income == D("5000.00")
    assert r.available == D("4000.00") - D("43.00")


def test_recurring_linked_spend_not_double_counted(db_session):
    user, acct, card = _seed(db_session)
    rent = db_session.query(models.RecurringItem).filter_by(name="Rent").one()
    _debit(db_session, user, acct, "RENT ACH", "1000.00", day=1, recurring_item_id=rent.id)

    r = _ats(db_session, user)
    assert r.spent_this_month == D("0")
    assert r.available == D("4000.00")


def test_card_linked_bill_is_not_double_counted_but_other_card_spend_is(db_session):
    user, acct, card = _seed(db_session)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, card_id=card.id, name="Streaming",
        amount=D("20.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1), is_active=True))
    db_session.commit()
    _card_row(db_session, user, card, "Streaming", "20.00", day=1)
    assert _ats(db_session, user).spent_this_month == D("0")

    _card_row(db_session, user, card, "Some Shop", "250.00")
    assert _ats(db_session, user).spent_this_month == D("250.00")


def test_settled_one_off_not_double_counted(db_session):
    user, acct, card = _seed(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=acct.id, name="Tires", amount=D("280.00"),
        expected_date=date(2026, 11, 4), settled_on=date(2026, 11, 4), actual_amount=D("300.00")))
    db_session.commit()
    _debit(db_session, user, acct, "TIRE SHOP", "300.00", day=4)   # the one-off's own charge
    _debit(db_session, user, acct, "HARDWARE", "45.00", day=6)      # ordinary spending

    r = _ats(db_session, user)
    assert r.one_offs_net == D("300.00")
    assert r.spent_this_month == D("45.00")
    assert r.available == D("5000.00") - D("1000.00") - D("300.00") - D("45.00")


def test_a_second_equal_charge_still_counts_after_a_one_off_claims_one(db_session):
    user, acct, card = _seed(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, card_id=card.id, name="Tires", amount=D("300.00"),
        expected_date=date(2026, 11, 4), settled_on=date(2026, 11, 4), actual_amount=D("300.00")))
    db_session.commit()
    _card_row(db_session, user, card, "TIRE SHOP", "300.00", day=4)
    _card_row(db_session, user, card, "TIRE SHOP 2", "300.00", day=5)

    assert _ats(db_session, user).spent_this_month == D("300.00")


def test_card_pending_counted_and_stale_ignored(db_session):
    user, acct, card = _seed(db_session)
    card.pending_charges = D("470.90")
    card.pending_charges_updated_at = datetime(2026, 11, 11, 9, 0)
    db_session.commit()
    assert _ats(db_session, user).spent_this_month == D("470.90")

    card.pending_charges_updated_at = datetime(2026, 11, 12) - timedelta(days=10)
    db_session.commit()
    assert _ats(db_session, user).spent_this_month == D("0")


def test_pending_adds_on_top_of_posted_card_spend(db_session):
    user, acct, card = _seed(db_session)
    _card_row(db_session, user, card, "Some Shop", "250.00")
    card.pending_charges = D("100.00")
    card.pending_charges_updated_at = datetime(2026, 11, 11, 9, 0)
    db_session.commit()
    assert _ats(db_session, user).spent_this_month == D("350.00")


@pytest.mark.parametrize("merchant,expected", [
    ("Some Shop", "250.00"),
    ("AUTOMATIC PAYMENT - THANK YOU", "0"),
])
def test_card_rows_and_payoffs(db_session, merchant, expected):
    user, acct, card = _seed(db_session)
    _card_row(db_session, user, card, merchant, "250.00")
    assert _ats(db_session, user).spent_this_month == D(expected)


def test_discretionary_checking_counts(db_session):
    user, acct, card = _seed(db_session)
    _debit(db_session, user, acct, "COFFEE", "63.00")
    assert _ats(db_session, user).spent_this_month == D("63.00")


def test_ss_boost_in_income(db_session):
    user, checking = _ss_seed(db_session, "ssboost", remaining=D("0"))
    db_session.commit()
    r = _ats(db_session, user, as_of=date(2026, 11, 2))
    assert r.monthly_income == 2 * (NET + BOOST)


def test_explain_replays_to_available(db_session):
    user, acct, card = _seed(db_session)
    _debit(db_session, user, acct, "COFFEE", "63.00")
    _card_row(db_session, user, card, "Some Shop", "250.00")
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=acct.id, name="Tires", amount=D("300.00"),
        expected_date=date(2026, 11, 20)))
    db_session.commit()

    r = _ats(db_session, user)
    assert [row.label for row in r.explain.rows][:4] == [
        "Income this month", "Recurring bills this month", "One-offs this month", "Spent so far"]
    assert replay(r.explain) == r.available == r.explain.result
    assert children_consistent(r.explain)


def test_walk_to_left_to_spend_ends_at_snapshot_value(db_session):
    user, checking = _headline_fixture(db_session)
    visa = db_session.query(models.CreditCard).filter_by(name="Test Visa").one()
    _budget(db_session, user, "Savings", "250.00")
    _card_row(db_session, user, visa, "Lawn", "25.00", day=2)       # the weekly card bill, posted
    _card_row(db_session, user, visa, "Some Shop", "60.00", day=2)
    _debit(db_session, user, checking, "COFFEE", "12.00", day=2)
    # A settled one-off charged to a card, with its own posted charge: Left to
    # Spend adds it back ("Card one-offs already charged"), Available holds it
    # in one-offs and leaves the row out of spending.
    db_session.add(models.PlannedExpense(
        user_id=user.id, card_id=visa.id, name="Dentist", amount=D("180.00"),
        expected_date=date(2026, 11, 2), settled_on=date(2026, 11, 2), actual_amount=D("180.00")))
    _card_row(db_session, user, visa, "DENTIST OFFICE", "180.00", day=2)
    db_session.commit()
    # The fixture's savings-funded one-off (New roof) is really there.
    assert db_session.query(models.PlannedExpense).filter(
        models.PlannedExpense.funding_account_id.isnot(None)).count() == 1
    as_of = date(2026, 11, 2)

    r = _ats(db_session, user, as_of=as_of)
    snapshot = compute_budget_snapshot(db_session, user, checking.id, as_of=as_of)

    assert r.to_left_to_spend is not None
    assert replay(r.to_left_to_spend) == r.to_left_to_spend.result == snapshot.left_to_spend
    assert children_consistent(r.to_left_to_spend)
    assert r.to_left_to_spend.rows[0].amount == r.available
    labels = [row.label for row in r.to_left_to_spend.rows]
    assert "Groceries budget" in labels and "Savings set aside" in labels
    assert "Card one-offs already charged" in labels
    # Spending so far: the coffee, the shop, and the 75 pending; the posted
    # lawn charge is the bill already in bills.
    assert r.spent_this_month == D("12.00") + D("60.00") + D("75.00")


def test_an_unrouted_settled_one_off_claims_nothing(db_session):
    user, acct, card = _seed(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Tires", amount=D("300.00"),
        expected_date=date(2026, 11, 4), settled_on=date(2026, 11, 4), actual_amount=D("300.00")))
    db_session.commit()
    _debit(db_session, user, acct, "TIRE SHOP", "300.00", day=4)
    assert _ats(db_session, user).spent_this_month == D("300.00")


def test_a_failing_snapshot_drops_the_walk_not_the_card(db_session, monkeypatch):
    user, acct, card = _seed(db_session)

    def boom(*a, **k):
        raise RuntimeError("snapshot down")
    monkeypatch.setattr("backend.services.budget_snapshot.compute_budget_snapshot", boom)
    r = _ats(db_session, user)
    assert r.to_left_to_spend is None and r.available == D("4000.00")


def test_no_checking_account_means_no_walk(db_session):
    user = models.User(username="nochk", hashed_password="x", display_name="N")
    db_session.add(user)
    db_session.commit()
    r = _ats(db_session, user)
    assert r.available == D("0") and r.to_left_to_spend is None


def test_route_returns_the_service_figures(db_session, monkeypatch):
    user, acct, card = _seed(db_session)
    _debit(db_session, user, acct, "COFFEE", "63.00")

    class _Today(date):
        @classmethod
        def today(cls):
            return TODAY
    monkeypatch.setattr("backend.routers.spending.date", _Today)
    r = available_route(db=db_session, user=user)
    assert r.available == D("3937.00")
    assert r.explain.result == r.available
