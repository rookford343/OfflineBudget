"""_fires_soon -- the "upcoming bills (next 7 days)" list in the daily email.

Matching on day-of-month alone made every yearly item look due in every month.
Once the annual renewals from Budget.xlsx were entered (nine items, $4,313/yr
including a $2,800 vehicle-insurance renewal), all nine appeared in the email
every single week regardless of the month. Found live 2026-08-12 by reading the
rendered email.
"""
from datetime import date, timedelta
from decimal import Decimal
from backend import models
from backend.services.summary_generator import _fires_soon


def _item(**kwargs) -> models.RecurringItem:
    defaults = dict(
        name="Item", amount=Decimal("10.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1), is_active=True, month_of_year=None,
        end_date=None,
    )
    defaults.update(kwargs)
    return models.RecurringItem(**defaults)


def test_yearly_item_fires_only_in_its_own_month():
    insurance = _item(
        name="Vehicle Insurance", amount=Decimal("2800.00"),
        frequency=models.RecurringFrequency.yearly, month_of_year=5, day_of_month=15,
    )

    assert _fires_soon(insurance, date(2026, 5, 12)), "due in May, should fire"
    assert not _fires_soon(insurance, date(2026, 8, 12)), (
        "a May renewal must not appear in August's upcoming bills"
    )
    assert not _fires_soon(insurance, date(2026, 12, 12))


def test_monthly_item_still_fires_every_month():
    rent = _item(name="Mortgage", day_of_month=23)

    for month in range(1, 13):
        assert _fires_soon(rent, date(2026, month, 20)), f"month {month} should fire"


def test_weekly_item_steps_from_start_date():
    weekly = _item(frequency=models.RecurringFrequency.weekly, start_date=date(2026, 8, 3))

    assert _fires_soon(weekly, date(2026, 8, 12))       # 8/17 is 14 days out
    assert _fires_soon(weekly, date(2026, 9, 1))
    # A weekly item always lands inside any 8-day window, so the interesting
    # assertion is that it is not gated on day_of_month == 15.
    assert _fires_soon(weekly, date(2026, 8, 20))


def test_biweekly_item_steps_fourteen_days():
    biweekly = _item(frequency=models.RecurringFrequency.biweekly, start_date=date(2026, 8, 3))

    assert _fires_soon(biweekly, date(2026, 8, 12))                    # 8/17
    assert not _fires_soon(biweekly, date(2026, 8, 4), days_ahead=7)   # next is 8/17, 13 days out


def test_inactive_item_never_fires():
    assert not _fires_soon(_item(is_active=False), date(2026, 8, 12))


def test_start_and_end_dates_are_respected():
    not_yet = _item(start_date=date(2026, 12, 1))
    assert not _fires_soon(not_yet, date(2026, 8, 12))

    finished = _item(end_date=date(2026, 6, 30))
    assert not _fires_soon(finished, date(2026, 8, 12))


def test_day_of_month_zero_means_last_day():
    payday = _item(day_of_month=0)

    assert _fires_soon(payday, date(2026, 8, 26))        # 8/31 within 7 days
    assert not _fires_soon(payday, date(2026, 8, 12))


def test_day_of_month_clamps_to_short_months():
    """A 31st-of-the-month item must still fire in February."""
    item = _item(day_of_month=31)

    assert _fires_soon(item, date(2026, 2, 25) - timedelta(days=1))
