from datetime import date
from decimal import Decimal
from backend import models
from backend.services.card_recurring_match import best_card_recurring_match


def test_floating_card_item_matches_anywhere_in_month(db_session, test_user, test_account, test_card):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=test_card.id,
        name="Test Barbers", amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.flush()
    match = best_card_recurring_match(
        [item], description="TEST BARBERS #42", amount=Decimal("45.00"),
        on=date(2026, 11, 3), confirmed_amounts={}, payee_history={},
    )
    assert match is item


def test_non_floating_card_item_never_matched(db_session, test_user, test_account, test_card):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=test_card.id,
        name="Test Barbers", amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1), is_floating=False,
    )
    db_session.add(item)
    db_session.flush()
    match = best_card_recurring_match(
        [item], description="TEST BARBERS #42", amount=Decimal("45.00"),
        on=date(2026, 11, 3), confirmed_amounts={}, payee_history={},
    )
    assert match is None


def test_checking_only_item_never_matched_on_card_side(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=None,
        name="Test Cleaning Co", amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.flush()
    match = best_card_recurring_match(
        [item], description="TEST CLEANING CO", amount=Decimal("150.00"),
        on=date(2026, 11, 3), confirmed_amounts={}, payee_history={},
    )
    assert match is None


def test_predates_start_date_never_matched(db_session, test_user, test_account, test_card):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=test_card.id,
        name="Test Barbers", amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 12, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.flush()
    match = best_card_recurring_match(
        [item], description="TEST BARBERS #42", amount=Decimal("45.00"),
        on=date(2026, 11, 3), confirmed_amounts={}, payee_history={},
    )
    assert match is None
