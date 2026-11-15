from datetime import date
from decimal import Decimal
from backend import models
from backend.services.import_service import _best_recurring_match


def test_floating_item_matches_anywhere_in_month():
    item = models.RecurringItem(
        id=1, user_id=1, account_id=1, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True, card_id=None,
    )
    match = _best_recurring_match(
        [item], description="TEST CLEANING CO DEBIT", amount=Decimal("-150.00"),
        on=date(2026, 11, 12), confirmed_amounts={}, payee_history={},
    )
    assert match is item


def test_non_floating_item_still_requires_window():
    item = models.RecurringItem(
        id=1, user_id=1, account_id=1, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=False, card_id=None,
    )
    match = _best_recurring_match(
        [item], description="TEST CLEANING CO DEBIT", amount=Decimal("-150.00"),
        on=date(2026, 11, 12), confirmed_amounts={}, payee_history={},
    )
    assert match is None
