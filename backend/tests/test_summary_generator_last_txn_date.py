from datetime import date
from decimal import Decimal
from backend import models
from backend.services.summary_generator import generate_daily_summary


def _make_user(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    return user


def test_shows_last_transaction_date_for_a_checking_account(db_session):
    user = _make_user(db_session)
    account = models.Account(user_id=user.id, name="Chase Checking", type=models.AccountType.checking, current_balance=Decimal("100"))
    db_session.add(account)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 9, 9),
        amount=Decimal("-12.34"), description="Coffee",
    ))
    db_session.commit()

    html, text = generate_daily_summary(db_session, user)
    assert "last txn Sep 9" in html
    assert "last txn Sep 9" in text


def test_shows_no_transactions_yet_for_a_checking_account_with_none(db_session):
    user = _make_user(db_session)
    account = models.Account(user_id=user.id, name="New Savings", type=models.AccountType.checking, current_balance=Decimal("0"))
    db_session.add(account)
    db_session.commit()

    html, text = generate_daily_summary(db_session, user)
    assert "no transactions yet" in html
    assert "no transactions yet" in text


def test_each_account_shows_its_own_most_recent_date_not_another_accounts(db_session):
    user = _make_user(db_session)
    old_account = models.Account(user_id=user.id, name="Old Checking", type=models.AccountType.checking, current_balance=Decimal("50"))
    new_account = models.Account(user_id=user.id, name="New Checking", type=models.AccountType.checking, current_balance=Decimal("75"))
    db_session.add_all([old_account, new_account])
    db_session.flush()
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=old_account.id, date=date(2026, 1, 1), amount=Decimal("-5"), description="Old"),
        models.Transaction(user_id=user.id, account_id=new_account.id, date=date(2026, 9, 9), amount=Decimal("-5"), description="New"),
    ])
    db_session.commit()

    html, text = generate_daily_summary(db_session, user)
    assert "last txn Jan 1" in html
    assert "last txn Sep 9" in html


def test_shows_last_transaction_date_for_a_credit_card(db_session):
    user = _make_user(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Amex Gold", credit_limit=Decimal("5000"),
        statement_day=1, due_day=15, current_balance=Decimal("200"),
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 9, 8),
        amount=Decimal("42.00"), merchant="Grocery Store",
    ))
    db_session.commit()

    html, text = generate_daily_summary(db_session, user)
    assert "last txn Sep 8" in html
    assert "last txn Sep 8" in text


def test_shows_no_transactions_yet_for_a_credit_card_with_none(db_session):
    user = _make_user(db_session)
    card = models.CreditCard(
        user_id=user.id, name="New Card", credit_limit=Decimal("1000"),
        statement_day=1, due_day=15, current_balance=Decimal("0"),
    )
    db_session.add(card)
    db_session.commit()

    html, text = generate_daily_summary(db_session, user)
    assert "no transactions yet" in html
    assert "no transactions yet" in text
