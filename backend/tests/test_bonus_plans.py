"""Bonus plan math: salary by year, gross from target % or a fixed ramp
amount, net after withholding, and keeping the backing item's amount equal
to the next payout. All figures are made up."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from backend import models
from backend.services.bonus_plans import (
    bonus_gross, bonus_net, payout_date, plans_by_item, refresh_item_amounts,
    salary_for_year, upcoming_payouts,
)
from backend.services.csv_parser import ParsedRow
from backend.services.import_service import _MATCH_WINDOW_DAYS, build_preview


def _user(db, **kw):
    user = models.User(username="bonus", hashed_password="x", display_name="B",
                       annual_salary=Decimal("100000"), annual_salary_year=2026,
                       annual_raise_pct=Decimal("3"), **kw)
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("1000"))
    db.add(acct)
    db.flush()
    return user, acct


def _plan(db, user, acct, *, lag=1, pct="20", wh="30", fixed=None, day=15, month=4):
    item = models.RecurringItem(user_id=user.id, account_id=acct.id, name="Annual Bonus",
                                amount=Decimal("1"), type=models.RecurringType.income,
                                frequency=models.RecurringFrequency.yearly, month_of_year=month,
                                day_of_month=day, start_date=date(2026, 1, 1))
    db.add(item)
    db.flush()
    plan = models.BonusPlan(user_id=user.id, recurring_item_id=item.id, target_pct=Decimal(pct),
                            salary_lag_years=lag, withholding_pct=Decimal(wh))
    db.add(plan)
    db.flush()
    for year, gross in (fixed or {}).items():
        db.add(models.BonusPlanYear(plan_id=plan.id, year=year, gross_amount=Decimal(gross)))
    db.commit()
    db.refresh(plan)
    return plan, item


def test_salary_compounds_from_its_base_year(db_session):
    user, _ = _user(db_session)
    assert salary_for_year(user, 2026) == Decimal("100000.00")
    assert salary_for_year(user, 2027) == Decimal("103000.00")
    assert salary_for_year(user, 2028) == Decimal("106090.00")
    assert salary_for_year(user, 2025) == Decimal("97087.38")


def test_salary_unknown_without_settings(db_session):
    user, _ = _user(db_session)
    user.annual_salary_year = None
    assert salary_for_year(user, 2027) is None


@pytest.mark.parametrize("lag,year,expected", [
    pytest.param(1, 2027, "20000.00", id="last_years_salary"),
    pytest.param(1, 2028, "20600.00", id="raise_carries_forward"),
    pytest.param(3, 2029, "20000.00", id="three_years_back"),
])
def test_gross_is_target_pct_of_the_lagged_salary(db_session, lag, year, expected):
    user, acct = _user(db_session)
    plan, _ = _plan(db_session, user, acct, lag=lag)
    assert bonus_gross(plan, user, year) == Decimal(expected)


def test_a_fixed_ramp_amount_wins_over_the_formula(db_session):
    user, acct = _user(db_session)
    plan, _ = _plan(db_session, user, acct, lag=3, fixed={2027: "12000", 2028: "17000"})
    assert bonus_gross(plan, user, 2027) == Decimal("12000.00")
    assert bonus_gross(plan, user, 2028) == Decimal("17000.00")
    assert bonus_gross(plan, user, 2029) == Decimal("20000.00")


def test_net_applies_withholding(db_session):
    user, acct = _user(db_session)
    plan, _ = _plan(db_session, user, acct, wh="30")
    assert bonus_net(plan, Decimal("20000.00")) == Decimal("14000.00")


def test_payout_date_handles_last_day(db_session):
    user, acct = _user(db_session)
    _, item = _plan(db_session, user, acct, day=0, month=2)
    assert payout_date(item, 2028) == date(2028, 2, 29)


def test_upcoming_payouts_start_after_this_years_date(db_session):
    user, acct = _user(db_session)
    plan, _ = _plan(db_session, user, acct)
    rows = upcoming_payouts(plan, user, date(2026, 10, 16), count=2)
    assert [(r["year"], r["date"], r["gross"], r["net"]) for r in rows] == [
        (2027, date(2027, 4, 15), Decimal("20000.00"), Decimal("14000.00")),
        (2028, date(2028, 4, 15), Decimal("20600.00"), Decimal("14420.00")),
    ]


def test_refresh_sets_the_item_amount_to_the_next_net(db_session):
    user, acct = _user(db_session)
    plan, item = _plan(db_session, user, acct)
    refresh_item_amounts(db_session, user, date(2026, 10, 16))
    db_session.refresh(item)
    assert item.amount == Decimal("14000.00")
    assert plans_by_item(db_session, user.id) == {item.id: plan}


def test_refresh_skips_an_item_no_longer_shaped_like_a_bonus(db_session):
    """Mirrors forecast_engine.py's own bonus_plans filter (is_bonus_shaped):
    a BonusPlan can only be attached to a yearly income item at creation
    time, but nothing stops the user from editing that same item into a
    different frequency afterward on the Recurring page. The engine already
    ignores such a plan entirely, so refresh_item_amounts must stop
    overwriting the item's amount too, or the two would disagree on what
    the item currently is."""
    user, acct = _user(db_session)
    _, item = _plan(db_session, user, acct)
    item.frequency = models.RecurringFrequency.monthly
    item.amount = Decimal("42.00")
    db_session.commit()

    refresh_item_amounts(db_session, user, date(2026, 10, 16))

    db_session.refresh(item)
    assert item.amount == Decimal("42.00")


# ── I1: a late deposit must still match THIS year's plan ────────────────────
#
# Bank sync imports once a day at 07:00, so a bonus posting after 07:00 on
# its payout day, or a few days late, was checked by refresh_item_amounts
# against NEXT year's net the instant `today > payout_date` -- in a ramp
# year that can differ enough (0.71x here) to fall outside the import
# matcher's own +/-15% amount window and never link. Fix: keep this year's
# payout as the target until _MATCH_WINDOW_DAYS after it.

def _suggested(db, user, description, amount, on):
    row = ParsedRow(date=on, description=description, amount=Decimal(amount), external_id="x")
    return build_preview(db, user, [row])[0]


def test_refresh_keeps_this_years_net_within_the_match_window(db_session):
    user, acct = _user(db_session)
    _, item = _plan(db_session, user, acct, fixed={2027: "12000", 2028: "17000"})
    payout = payout_date(item, 2027)  # 2027-04-15, a Thursday -- no weekend shift

    refresh_item_amounts(db_session, user, payout + timedelta(days=1))

    db_session.refresh(item)
    assert item.amount == Decimal("8400.00"), (
        "this year's net (12,000 gross x 70%) must still be the target the "
        "day after payout -- not 2028's 11,900.00"
    )


def test_refresh_rolls_to_next_years_net_past_the_match_window(db_session):
    user, acct = _user(db_session)
    _, item = _plan(db_session, user, acct, fixed={2027: "12000", 2028: "17000"})
    payout = payout_date(item, 2027)

    refresh_item_amounts(db_session, user, payout + timedelta(days=_MATCH_WINDOW_DAYS + 1))

    db_session.refresh(item)
    assert item.amount == Decimal("11900.00"), (
        "past the matcher's own window, the target rolls to next year's net "
        "(17,000 gross x 70%)"
    )


def test_a_late_bonus_deposit_still_links_via_the_import_matcher(db_session):
    """End to end: a bonus that posts the day after payout, in a ramp year
    where next year's net is far off, must still link through
    build_preview's suggestion -- the whole point of keeping item.amount at
    THIS year's net past the payout date."""
    user, acct = _user(db_session)
    _, item = _plan(db_session, user, acct, fixed={2027: "12000", 2028: "17000"})
    payout = payout_date(item, 2027)
    deposit_date = payout + timedelta(days=1)
    refresh_item_amounts(db_session, user, deposit_date)
    db_session.refresh(item)
    assert item.amount == Decimal("8400.00")

    row = _suggested(db_session, user, "ACME CORP BONUS PAYROLL", "8400.00", deposit_date)

    assert row.suggested_recurring_item_id == item.id
    assert row.suggested_recurring_item_name == item.name
