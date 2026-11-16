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


def test_floating_non_monthly_card_item_never_matched(db_session, test_user, test_account, test_card):
    # Nothing at the data layer ties is_floating to frequency == monthly
    # (no validator in schemas.py/routers/recurring.py enforces that
    # combination), so a weekly item could be flagged is_floating via an
    # ordinary PATCH. Without the monthly guard in best_card_recurring_match,
    # the whole-month loop would treat "fires somewhere in the month" as a
    # pass for an item that already fires ~4x/month -- far more permissive
    # than even the old +/-window ever was.
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=test_card.id,
        name="Test Barbers", amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.weekly, day_of_month=0,
        start_date=date(2026, 1, 5), is_floating=True,
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


def test_amount_within_card_tolerance_but_outside_checking_tolerance_matches(db_session, test_user, test_account, test_card):
    """The card-side floating matcher's amount tolerance is +/-30%
    (_CARD_AMOUNT_RATIO), wider than the checking-side bills' +/-15%
    (import_service._AMOUNT_RATIO, left untouched) -- a card-charged
    floating item like a haircut has more day-to-day variance (tips) than a
    fixed bill. $55.00 against a $45.00 item is a 1.222x ratio: outside the
    old +/-15% window (max 1.15x) but inside the new +/-30% one (max 1.30x)."""
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=test_card.id,
        name="Test Barbers", amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.flush()
    match = best_card_recurring_match(
        [item], description="TEST BARBERS #42", amount=Decimal("55.00"),
        on=date(2026, 11, 3), confirmed_amounts={}, payee_history={},
    )
    assert match is item


def test_amount_outside_card_tolerance_never_matches(db_session, test_user, test_account, test_card):
    """$60.00 against a $45.00 item is a 1.333x ratio -- outside even the
    wider +/-30% card tolerance."""
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=test_card.id,
        name="Test Barbers", amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.flush()
    match = best_card_recurring_match(
        [item], description="TEST BARBERS #42", amount=Decimal("60.00"),
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
