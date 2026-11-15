from datetime import date
from decimal import Decimal
import pytest
from backend import models


def test_recurring_item_is_floating_defaults_false(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Floating Co",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    assert item.is_floating is False


def test_recurring_skip_unique_per_item_month(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Floating Co",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.commit()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=12))
    db_session.commit()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=12))
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_credit_card_transaction_recurring_item_id(db_session, test_user, test_card):
    ct = models.CreditCardTransaction(
        card_id=test_card.id, user_id=test_user.id, date=date(2026, 11, 14),
        amount=Decimal("45.00"), merchant="Test Barbers",
    )
    db_session.add(ct)
    db_session.commit()
    assert ct.recurring_item_id is None
