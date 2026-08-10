from datetime import date
from decimal import Decimal
from backend.services.spendable_pacer import week_bounds, weeks_remaining_in_month


def test_week_bounds_for_a_midweek_date():
    # Aug 7 2026 is a Friday; the Sun-Sat week containing it is Aug 2-8.
    assert week_bounds(date(2026, 8, 7)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_week_bounds_when_as_of_is_the_sunday_itself():
    assert week_bounds(date(2026, 8, 2)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_week_bounds_when_as_of_is_the_saturday_itself():
    assert week_bounds(date(2026, 8, 8)) == (date(2026, 8, 2), date(2026, 8, 8))


def test_weeks_remaining_in_month_on_the_first_of_a_28_day_month():
    # Feb 2026 has 28 days (not a leap year) -- exactly 4 weeks remain on day 1.
    assert weeks_remaining_in_month(date(2026, 2, 1)) == Decimal("4")


def test_weeks_remaining_in_month_on_the_last_day():
    # 1 day remaining -> 1/7 of a week, never zero (avoids downstream division by zero).
    assert weeks_remaining_in_month(date(2026, 2, 28)) == Decimal("1") / Decimal("7")


def test_weeks_remaining_in_month_mid_month():
    # Feb 8 2026: days_remaining = 28 - 8 + 1 = 21 -> 21/7 = 3 exactly.
    assert weeks_remaining_in_month(date(2026, 2, 8)) == Decimal("3")
