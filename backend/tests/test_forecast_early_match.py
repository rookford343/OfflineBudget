"""A bill matched before the forecast start is not projected again.

`build_forecast` read the linked actuals only from `start_date`, so a monthly
item paid on the 12th was invisible to a forecast starting on the 26th and got
projected a second time on the 30th. The suppression lookup now reaches back to
the first of the start's month (or 3 days, for biweekly items).

All names and amounts are invented; the repo is public."""
from datetime import date
from decimal import Decimal

import pytest

from backend import models
from backend.services.forecast_engine import build_forecast

START = date(2026, 11, 26)


def _freeze_today(monkeypatch, fixed: date) -> None:
    """Pin date.today() in every module on the build_forecast path."""
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)
    monkeypatch.setattr("backend.services.budget_snapshot.date", _FixedDate)


@pytest.fixture(autouse=True)
def _pin_today(monkeypatch):
    # Default to START; tests with another start re-pin to their own start.
    _freeze_today(monkeypatch, START)


def _item(db, user, account, *, floating=True, day=0,
          freq=models.RecurringFrequency.monthly, start=date(2026, 1, 1)):
    item = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Test Water Co",
        amount=Decimal("80.00"), type=models.RecurringType.expense,
        frequency=freq, day_of_month=day, start_date=start, is_floating=floating,
    )
    db.add(item)
    db.commit()
    return item


def _actual(db, user, account, item, when):
    db.add(models.Transaction(
        user_id=user.id, account_id=account.id, recurring_item_id=item.id,
        date=when, amount=Decimal("-80.00"), description="Test Water Co", is_actual=True,
    ))
    db.commit()


def _projected_dates(entries, name="Test Water Co"):
    return [e.date for e in entries for t in e.transactions
            if t.name == name and not t.is_actual]


def test_floating_matched_earlier_in_month_not_reprojected(db_session, test_user, test_account):
    item = _item(db_session, test_user, test_account)
    _actual(db_session, test_user, test_account, item, date(2026, 11, 12))
    entries = build_forecast(db_session, test_user.id, test_account.id, START, date(2027, 1, 2))
    dates = _projected_dates(entries)
    assert date(2026, 11, 30) not in dates
    assert date(2026, 12, 31) in dates


def test_fixed_day_paid_early_not_reprojected(db_session, test_user, test_account):
    item = _item(db_session, test_user, test_account, floating=False, day=28)
    _actual(db_session, test_user, test_account, item, date(2026, 11, 12))
    entries = build_forecast(db_session, test_user.id, test_account.id, START, date(2027, 1, 2))
    dates = _projected_dates(entries)
    assert not any(d.year == 2026 and d.month == 11 for d in dates)
    assert any(d.year == 2026 and d.month == 12 for d in dates)


def test_previous_month_actual_does_not_suppress(db_session, test_user, test_account):
    item = _item(db_session, test_user, test_account)
    _actual(db_session, test_user, test_account, item, date(2026, 10, 30))
    entries = build_forecast(db_session, test_user.id, test_account.id, START, date(2026, 12, 5))
    assert date(2026, 11, 30) in _projected_dates(entries)


def test_pre_start_actual_not_added_to_balance(db_session, test_user, test_account):
    # Starts in November so the bridge has no unmatched October projection.
    item = _item(db_session, test_user, test_account, start=date(2026, 11, 1))
    _actual(db_session, test_user, test_account, item, date(2026, 11, 12))
    with_match = build_forecast(db_session, test_user.id, test_account.id, START, date(2026, 12, 5))
    assert not any(t.is_actual and t.name == "Test Water Co"
                   for e in with_match for t in e.transactions)
    db_session.query(models.Transaction).delete()
    db_session.query(models.RecurringItem).delete()
    db_session.commit()
    without = build_forecast(db_session, test_user.id, test_account.id, START, date(2026, 12, 5))
    assert [(e.date, e.projected_balance) for e in with_match] == \
           [(e.date, e.projected_balance) for e in without]


def test_biweekly_actual_just_before_start_suppressed(db_session, test_user, test_account):
    item = _item(db_session, test_user, test_account, floating=False, day=27,
                 freq=models.RecurringFrequency.biweekly, start=date(2026, 11, 13))
    _actual(db_session, test_user, test_account, item, date(2026, 11, 25))
    entries = build_forecast(db_session, test_user.id, test_account.id, START, date(2026, 12, 5))
    assert date(2026, 11, 27) not in _projected_dates(entries)


def test_previous_month_actual_just_before_start_does_not_suppress(
        db_session, test_user, test_account, monkeypatch):
    start = date(2026, 11, 2)
    _freeze_today(monkeypatch, start)
    item = _item(db_session, test_user, test_account)
    _actual(db_session, test_user, test_account, item, date(2026, 10, 30))
    entries = build_forecast(db_session, test_user.id, test_account.id, start, date(2026, 12, 5))
    assert date(2026, 11, 30) in _projected_dates(entries)


def test_weekend_first_bill_not_hidden_by_last_months_payment(
        db_session, test_user, test_account, monkeypatch):
    # May 1 2027 is a Saturday, so the bill is projected on Fri Apr 30. The
    # April 1 payment belongs to April; it must not suppress May's bill.
    start = date(2027, 4, 20)
    _freeze_today(monkeypatch, start)
    item = _item(db_session, test_user, test_account, floating=False, day=1)
    _actual(db_session, test_user, test_account, item, date(2027, 4, 1))
    entries = build_forecast(db_session, test_user.id, test_account.id, start, date(2027, 5, 10))
    assert date(2027, 4, 30) in _projected_dates(entries)
