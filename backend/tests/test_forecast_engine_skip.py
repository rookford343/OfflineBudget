"""RecurringSkip (Task 1) must also suppress the projected occurrence in
build_forecast's day walk for the skipped (year, month) only -- not just in
month_base.py's monthly totals. This codebase has a known failure mode
(2026-11, floating-recurring-expenses plan) where a new recurring-item rule
lands in services/month_base.py but its sibling path
services/forecast_engine.py is never updated, so the Dashboard/Recurring
page and the Forecast tab disagree on the same month. This test proves the
skip actually suppresses the entry inside build_forecast itself, mirroring
the call pattern used by test_recurring_item_forecast_exclusion.py."""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import build_forecast


def test_skipped_item_not_projected_in_forecast(db_session, test_user, test_account):
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

    entries = build_forecast(db_session, test_user.id, test_account.id, date(2026, 11, 1), date(2026, 11, 30))
    assert not any(
        t.recurring_item_id == item.id
        for e in entries for t in e.transactions
    )

    # Un-skipped month still projects the occurrence -- proves the skip is
    # scoped to (item, year, month), not a blanket exclusion.
    entries_december = build_forecast(db_session, test_user.id, test_account.id, date(2026, 12, 1), date(2026, 12, 31))
    assert any(
        t.recurring_item_id == item.id
        for e in entries_december for t in e.transactions
    )
