from datetime import date, timedelta
from decimal import Decimal
from backend import models
from backend.services.spending_helpers import merchant_totals, category_totals_for_range
from backend.services.summary_generator import generate_weekly_digest


def _make_user_account(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("0"))
    db.add(account)
    db.flush()
    return user, account


def test_merchant_totals_ranks_checking_transactions(db_session):
    user, account = _make_user_account(db_session)
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 1), amount=Decimal("-40.00"), description="Kroger"),
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 2), amount=Decimal("-15.00"), description="Kroger"),
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 3), amount=Decimal("-100.00"), description="Amazon"),
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 4), amount=Decimal("500.00"), description="Paycheck"),
    ])
    db_session.commit()

    result = merchant_totals(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7))

    assert result[0] == ("Amazon", Decimal("100.00"), 1)
    assert result[1] == ("Kroger", Decimal("55.00"), 2)
    assert len(result) == 2


def test_merchant_totals_respects_limit(db_session):
    user, account = _make_user_account(db_session)
    for i in range(5):
        db_session.add(models.Transaction(
            user_id=user.id, account_id=account.id, date=date(2026, 8, 1),
            amount=Decimal(f"-{i + 1}.00"), description=f"Merchant{i}",
        ))
    db_session.commit()

    result = merchant_totals(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7), limit=2)
    assert len(result) == 2


def test_category_totals_for_range_groups_checking_spend(db_session):
    user, account = _make_user_account(db_session)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db_session.add(groceries)
    db_session.flush()
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 1), amount=Decimal("-60.00"), description="Kroger", category_id=groceries.id),
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 15), amount=Decimal("-999.00"), description="Out of range", category_id=groceries.id),
    ])
    db_session.commit()

    totals = category_totals_for_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7))
    assert totals[groceries.id] == Decimal("60.00")


def test_category_totals_for_range_excludes_savings(db_session):
    user, account = _make_user_account(db_session)
    savings_cat = models.Category(user_id=user.id, name="Emergency Fund", type=models.CategoryType.savings)
    db_session.add(savings_cat)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 1),
        amount=Decimal("-200.00"), description="Transfer", category_id=savings_cat.id,
    ))
    db_session.commit()

    totals = category_totals_for_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7))
    assert savings_cat.id not in totals


def test_category_totals_for_range_buckets_uncategorized_under_none(db_session):
    user, account = _make_user_account(db_session)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db_session.add(groceries)
    db_session.flush()
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 1), amount=Decimal("-60.00"), description="Kroger", category_id=groceries.id),
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 2), amount=Decimal("-25.00"), description="Uncategorized Charge", category_id=None),
    ])
    db_session.commit()

    totals = category_totals_for_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7))
    assert totals[groceries.id] == Decimal("60.00")
    assert totals[None] == Decimal("25.00")
    assert sum(totals.values(), Decimal("0")) == Decimal("85.00")


def _make_card(db, user):
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=15, due_day=1,
    )
    db.add(card)
    db.flush()
    return card


def test_category_totals_for_range_groups_card_spend(db_session):
    user, account = _make_user_account(db_session)
    card = _make_card(db_session, user)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db_session.add(groceries)
    db_session.flush()
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, category_id=groceries.id,
        date=date(2026, 8, 3), amount=Decimal("75.00"), merchant="Kroger",
    ))
    db_session.commit()

    totals = category_totals_for_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7))
    assert totals[groceries.id] == Decimal("75.00")


def test_category_totals_for_range_excludes_savings_for_card(db_session):
    user, account = _make_user_account(db_session)
    card = _make_card(db_session, user)
    savings_cat = models.Category(user_id=user.id, name="Emergency Fund", type=models.CategoryType.savings)
    db_session.add(savings_cat)
    db_session.flush()
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, category_id=savings_cat.id,
        date=date(2026, 8, 3), amount=Decimal("150.00"), merchant="Transfer",
    ))
    db_session.commit()

    totals = category_totals_for_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7))
    assert savings_cat.id not in totals


def test_generate_weekly_digest_smoke(db_session):
    user, account = _make_user_account(db_session)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db_session.add(groceries)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date.today() - timedelta(days=1),
        amount=Decimal("-42.00"), description="Kroger", category_id=groceries.id,
    ))
    db_session.commit()

    digest = generate_weekly_digest(db_session, user, account.id)
    assert digest.total_spent == Decimal("42.00")
    assert digest.categories[0].category_name == "Groceries"
    assert digest.risk.at_risk is False


def test_generate_weekly_digest_reconciles_uncategorized_spend(db_session):
    user, account = _make_user_account(db_session)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db_session.add(groceries)
    db_session.flush()
    db_session.add_all([
        models.Transaction(
            user_id=user.id, account_id=account.id, date=date.today() - timedelta(days=1),
            amount=Decimal("-42.00"), description="Kroger", category_id=groceries.id,
        ),
        models.Transaction(
            user_id=user.id, account_id=account.id, date=date.today() - timedelta(days=1),
            amount=Decimal("-500.00"), description="Big Uncategorized Charge", category_id=None,
        ),
    ])
    db_session.commit()

    digest = generate_weekly_digest(db_session, user, account.id)
    # total_spent must reconcile with the sum of all category buckets, including Uncategorized.
    assert digest.total_spent == Decimal("542.00")
    uncategorized = next(c for c in digest.categories if c.category_name == "Uncategorized")
    assert uncategorized.total == Decimal("500.00")
    assert uncategorized.category_id == 0
