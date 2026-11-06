"""Dashboard "Month in Review" totals (summary_generator.generate_summary).

Card charges are the spending; the checking autopay that settles them, and
money moved between the user's own accounts, are not -- in either direction.
Synthetic figures only.
"""
from datetime import date
from decimal import Decimal

from backend import models
from backend.services.summary_generator import generate_summary


def _setup(db):
    user = models.User(username="review", hashed_password="x", display_name="Review")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", last_four="1111",
        credit_limit=Decimal("5000.00"), statement_day=1, due_day=20,
    )
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense, color="#111111", sort_order=0)
    utilities = models.Category(user_id=user.id, name="Utilities", type=models.CategoryType.expense, color="#222222", sort_order=1)
    salary = models.Category(user_id=user.id, name="Salary", type=models.CategoryType.income, color="#333333", sort_order=2)
    db.add_all([account, card, groceries, utilities, salary])
    db.flush()
    return user, account, card, groceries, utilities, salary


def _txn(db, user, account, day, amount, desc, category=None):
    db.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=day, amount=Decimal(amount),
        description=desc, is_actual=True, category_id=category.id if category else None,
    ))


def _charge(db, user, card, day, amount, merchant, category=None):
    db.add(models.CreditCardTransaction(
        user_id=user.id, card_id=card.id, date=day, amount=Decimal(amount),
        merchant=merchant, category_id=category.id if category else None,
    ))


def _month(db, user, account, card, groceries, utilities, salary, year, month, scale="1"):
    s = Decimal(scale)
    d = lambda day: date(year, month, day)  # noqa: E731
    _txn(db, user, account, d(1), str(Decimal("3000.00") * s), "PAYROLL DEPOSIT", salary)
    _txn(db, user, account, d(5), str(Decimal("-150.00") * s), "CITY ELECTRIC", utilities)
    _charge(db, user, card, d(8), str(Decimal("200.00") * s), "GROCER ONE", groceries)
    _charge(db, user, card, d(12), str(Decimal("100.00") * s), "GROCER TWO", groceries)
    # Card side of the payoff -- a payment credit, never a purchase.
    _charge(db, user, card, d(20), str(Decimal("-300.00") * s), "AUTOPAY PAYMENT - THANK YOU")
    # Checking side of the same payoff: settles charges counted above.
    _txn(db, user, account, d(20), str(Decimal("-300.00") * s), "CHASE CREDIT CRD AUTOPAY")
    # Own-account moves, out and back in.
    _txn(db, user, account, d(22), str(Decimal("-1000.00") * s), "Online Transfer to SAV ...9999")
    _txn(db, user, account, d(25), str(Decimal("400.00") * s), "Online Transfer from SAV ...9999")


def test_spending_excludes_autopay_and_transfers_and_income_excludes_transfer_in(db_session):
    user, account, card, groceries, utilities, salary = _setup(db_session)
    _month(db_session, user, account, card, groceries, utilities, salary, 2026, 10)
    db_session.commit()

    s = generate_summary(db_session, user.id, 2026, 10)

    # Spending = 150 utilities + 300 card groceries = 450; income = 3000.
    assert s.net_cashflow == Decimal("2550.00")
    assert s.top_category == "Groceries"
    assert s.top_category_amount == Decimal("300.00")


def test_month_over_month_compares_two_full_months_of_real_spend(db_session):
    user, account, card, groceries, utilities, salary = _setup(db_session)
    _month(db_session, user, account, card, groceries, utilities, salary, 2026, 9)
    _month(db_session, user, account, card, groceries, utilities, salary, 2026, 10, scale="2")
    db_session.commit()

    s = generate_summary(db_session, user.id, 2026, 10)

    # Real spend 450 in September, 900 in October.
    assert s.mom_delta == Decimal("450.00")
    assert s.mom_delta_pct == Decimal("100.0")


def test_january_compares_against_prior_december(db_session):
    user, account, card, groceries, utilities, salary = _setup(db_session)
    _month(db_session, user, account, card, groceries, utilities, salary, 2025, 12)
    _month(db_session, user, account, card, groceries, utilities, salary, 2026, 1, scale="2")
    db_session.commit()

    s = generate_summary(db_session, user.id, 2026, 1)

    assert s.mom_delta == Decimal("450.00")


def test_income_category_debit_is_not_spending(db_session):
    user, account, card, groceries, utilities, salary = _setup(db_session)
    _txn(db_session, user, account, date(2026, 10, 1), "3000.00", "PAYROLL DEPOSIT", salary)
    # A paycheck correction/reversal lands as a debit tagged with the income category.
    _txn(db_session, user, account, date(2026, 10, 2), "-50.00", "PAYROLL ADJUSTMENT", salary)
    _txn(db_session, user, account, date(2026, 10, 5), "-150.00", "CITY ELECTRIC", utilities)
    db_session.commit()

    s = generate_summary(db_session, user.id, 2026, 10)

    assert s.top_category == "Utilities"
    assert s.net_cashflow == Decimal("2850.00")
