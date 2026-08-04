from datetime import date
from decimal import Decimal
from backend import models
from backend.services.spending_helpers import merchant_totals


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
