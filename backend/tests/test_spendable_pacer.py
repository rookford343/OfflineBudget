from datetime import date
from decimal import Decimal
from backend.services.spendable_pacer import week_bounds, weeks_remaining_in_month


def test_week_bounds_for_a_midweek_date():
    # Aug 7 2026 is a Friday; the Sun-Sat week containing it is Aug 2-8.
    assert week_bounds(date(2026, 8, 7)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_week_bounds_when_as_of_is_the_sunday_itself():
    assert week_bounds(date(2026, 8, 2)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_week_bounds_when_as_of_is_the_saturday_itself():
    assert week_bounds(date(2026, 8, 8)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_weeks_remaining_in_month_on_the_first_of_a_28_day_month():
    # Feb 2026 has 28 days (not a leap year) -- exactly 4 weeks remain on day 1.
    assert weeks_remaining_in_month(date(2026, 2, 1)) == Decimal("4")


def test_weeks_remaining_in_month_on_the_last_day():
    # 1 day remaining -> 1/7 of a week, never zero (avoids downstream division by zero).
    assert weeks_remaining_in_month(date(2026, 2, 28)) == Decimal("1") / Decimal("7")


def test_weeks_remaining_in_month_mid_month():
    # Feb 8 2026: days_remaining = 28 - 8 + 1 = 21 -> 21/7 = 3 exactly.
    assert weeks_remaining_in_month(date(2026, 2, 8)) == Decimal("3")


from backend import models
from backend.services.spendable_pacer import discretionary_spend_in_range


def _make_user_and_checking(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking)
    db.add(checking)
    db.flush()
    return user, checking


def test_counts_a_plain_discretionary_checking_transaction(db_session):
    user, checking = _make_user_and_checking(db_session)
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-45.00"), description="Coffee shop", is_actual=True,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("45.00")


def test_excludes_a_recurring_linked_checking_transaction(db_session):
    """A bill payment (e.g. mortgage debit) is already counted in `leftover`
    up front -- counting it again here would double-dip."""
    user, checking = _make_user_and_checking(db_session)
    recurring = models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Mortgage", amount=Decimal("2000.00"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=3, start_date=date(2026, 1, 1),
    )
    db_session.add(recurring)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-2000.00"), description="Mortgage Co", is_actual=True,
        recurring_item_id=recurring.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_excludes_a_savings_category_checking_transaction(db_session):
    user, checking = _make_user_and_checking(db_session)
    savings_cat = models.Category(user_id=user.id, name="Savings", type=models.CategoryType.savings)
    db_session.add(savings_cat)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-500.00"), description="To savings", is_actual=True,
        category_id=savings_cat.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_excludes_a_verified_planned_transfer_transaction(db_session):
    """A PlannedTransfer's verified_transaction_id points at the real
    transaction that fulfilled it -- a savings movement, not spending, even
    if it landed in an uncategorized or non-savings-tagged row."""
    user, checking = _make_user_and_checking(db_session)
    savings = models.Account(user_id=user.id, name="Savings", type=models.AccountType.savings)
    db_session.add(savings)
    db_session.flush()
    txn = models.Transaction(
        user_id=user.id, account_id=checking.id, date=date(2026, 8, 3),
        amount=Decimal("-1000.00"), description="Transfer to savings", is_actual=True,
    )
    db_session.add(txn)
    db_session.flush()
    db_session.add(models.PlannedTransfer(
        user_id=user.id, from_account_id=checking.id, to_account_id=savings.id,
        amount=Decimal("1000.00"), target_date=date(2026, 8, 3),
        status=models.PlannedTransferStatus.verified, verified_transaction_id=txn.id,
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("0.00")


def test_counts_a_plain_card_charge(db_session):
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=15,
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("80.00"), merchant="Grocery Store",
    ))
    db_session.commit()

    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("80.00")


def test_excludes_a_card_linked_recurring_subscription_from_card_spend(db_session):
    """A subscription billed to a card (RecurringItem.card_id set) is
    already counted in `leftover` via _cc_budget_total -- deduct it from
    the card total for the range it fires in, the same day-of-month
    'firing' logic budget_snapshot.py's _charged_so_far already uses
    (not per-transaction fuzzy matching)."""
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=15,
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Streaming", amount=Decimal("15.99"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=3, start_date=date(2026, 1, 1), card_id=card.id,
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("80.00"), merchant="Grocery Store",
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 3),
        amount=Decimal("15.99"), merchant="Streaming Co",
    ))
    db_session.commit()

    # Total card charges in range = 95.99; the subscription's 15.99 is
    # deducted (it fires day_of_month=3, inside [Aug 1, Aug 7]) -> 80.00.
    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7)) == Decimal("80.00")


def test_recurring_card_charge_firing_across_a_month_boundary(db_session):
    user, checking = _make_user_and_checking(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=15,
    )
    db_session.add(card)
    db_session.flush()
    # Fires on the 2nd of every month -- Sep 2 falls inside a week that
    # starts Aug 30 (Sunday) and ends Sep 5 (Saturday).
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Streaming", amount=Decimal("15.99"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=2, start_date=date(2026, 1, 1), card_id=card.id,
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 9, 2),
        amount=Decimal("100.00"), merchant="Grocery Store",
    ))
    db_session.commit()

    # 100.00 total in range, 15.99 subscription deducted (fires Sep 2, inside range).
    assert discretionary_spend_in_range(db_session, user.id, date(2026, 8, 30), date(2026, 9, 5)) == Decimal("84.01")
