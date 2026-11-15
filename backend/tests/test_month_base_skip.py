"""RecurringSkip (Task 1) must make a floating item's occurrence vanish from
build_month_base's monthly_bills for the skipped (year, month) only -- other
months still see it. This is one half of the "skip this month" feature
(Task 3); test_forecast_engine_skip.py covers the other half, the day-by-day
forecast, since this codebase has a known failure mode where month_base.py
and forecast_engine.py disagree on the same rule."""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.month_base import build_month_base


def test_skipped_item_excluded_from_monthly_bills(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Cleaning Co",
        amount=Decimal("150.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=0,
        start_date=date(2026, 1, 1), is_floating=True,
    )
    db_session.add(item)
    db_session.commit()
    db_session.add(models.RecurringSkip(user_id=test_user.id, recurring_item_id=item.id, year=2026, month=11))
    db_session.commit()

    base = build_month_base(db_session, test_user, 2026, 11)
    assert all(o.recurring_item_id != item.id for o in base.monthly_bills)

    base_other_month = build_month_base(db_session, test_user, 2026, 12)
    assert any(o.recurring_item_id == item.id for o in base_other_month.monthly_bills)
