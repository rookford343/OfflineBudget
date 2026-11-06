"""Year-aware tax tables.

The estimator used to encode only 2025 federal tables (and the pre-OBBBA 2025
standard deduction), so every other year was estimated with the wrong
brackets. Figures below are the published ones: IRS Rev. Proc. 2025-32 (2026)
and 2026-35 (2027), the OBBBA's 2025 standard deduction, and the SSA's
contribution and benefit base.
"""
from datetime import date
from decimal import Decimal

import pytest

from backend import models
from backend.services import tax_service
from backend.services.forecast_engine import build_forecast
from backend.services.tax_service import estimate_taxes, ss_wage_base_for


def _estimate(year, *, filing_status="single", state="TX", gross="0", other="0"):
    return estimate_taxes(
        filing_status=filing_status,
        state=state,
        gross_income=Decimal(gross),
        other_income=Decimal(other),
        deductible_expenses=Decimal("0"),
        federal_withheld=Decimal("0"),
        state_withheld=Decimal("0"),
        year=year,
    )


@pytest.mark.parametrize("year, status, expected", [
    (2025, "single", "15750"),
    (2025, "married_jointly", "31500"),
    (2025, "head_of_household", "23625"),
    (2026, "married_jointly", "32200"),
    (2026, "head_of_household", "24150"),
    (2027, "single", "16600"),
    (2027, "married_separately", "16600"),
    (2027, "head_of_household", "24925"),
])
def test_each_year_uses_its_own_standard_deduction(year, status, expected):
    result = _estimate(year, filing_status=status, gross="100000")
    assert result["standard_deduction"] == Decimal(expected)
    assert result["bracket_year"] == year


def test_2027_single_bracket_total_matches_rev_proc_cumulative_amounts():
    """Rev. Proc. 2026-35: single tax at 52,025 is 5,987.00; the next 7,975
    of taxable income sits in the 22% bracket."""
    at_floor = _estimate(2027, gross=str(52025 + 16600))
    assert at_floor["taxable_income"] == Decimal("52025")
    assert at_floor["federal_tax"] == Decimal("5987.00")

    result = _estimate(2027, gross=str(60000 + 16600))
    assert result["taxable_income"] == Decimal("60000")
    expected = (
        Decimal("12800") * Decimal("0.10")
        + (Decimal("52025") - Decimal("12800")) * Decimal("0.12")
        + (Decimal("60000") - Decimal("52025")) * Decimal("0.22")
    )
    assert expected == Decimal("7741.50")
    assert result["federal_tax"] == expected


def test_2027_married_jointly_tax_at_the_22_percent_floor():
    result = _estimate(2027, filing_status="married_jointly", gross=str(104050 + 33200))
    assert result["federal_tax"] == Decimal("11974.00")


def test_2026_and_2025_tables_differ_for_the_same_income():
    """Same gross, different year: the inflation-adjusted floors and larger
    deduction must lower the tax, not repeat 2025's figure."""
    t2025 = _estimate(2025, gross="90000")["federal_tax"]
    t2026 = _estimate(2026, gross="90000")["federal_tax"]
    assert t2026 < t2025


@pytest.mark.parametrize("year, used", [(2024, 2025), (2019, 2025), (2030, 2027), (2028, 2027)])
def test_unbundled_years_fall_back_to_the_nearest_bundled_table(year, used):
    result = _estimate(year, gross="100000")
    assert result["bracket_year"] == used
    assert result["standard_deduction"] == _estimate(used, gross="100000")["standard_deduction"]


def test_no_year_uses_the_latest_bundled_table():
    result = _estimate(None, gross="100000")
    assert result["bracket_year"] == max(tax_service._TABLES)


@pytest.mark.parametrize("year, base", [(2025, "176100"), (2026, "184500"), (2027, "192300")])
def test_social_security_tax_caps_at_that_years_wage_base(year, base):
    result = _estimate(year, gross="300000")
    assert result["fica_ss"] == Decimal(base) * Decimal("0.062")
    assert ss_wage_base_for(year) == Decimal(base)


def test_wage_base_is_unknown_for_unpublished_years():
    assert ss_wage_base_for(2024) is None
    assert ss_wage_base_for(2028) is None


@pytest.mark.parametrize("year, rate", [(2025, 0.030), (2026, 0.0295), (2027, 0.029)])
def test_indiana_flat_rate_by_year(year, rate):
    assert _estimate(year, state="IN", gross="80000")["state_rate"] == rate


def test_other_states_keep_the_flat_fallback_rate():
    assert _estimate(2027, state="IL", gross="80000")["state_rate"] == tax_service.STATE_RATES["IL"]
    # Outside the Indiana override's years, Indiana falls back too.
    assert _estimate(2030, state="IN", gross="80000")["state_rate"] == tax_service.STATE_RATES["IN"]


# --- Forecast: the wage base rolls over to the published figure -------------

GROSS = Decimal("20000.00")
NET = Decimal("14000.00")  # 0.70 of gross, inside the paycheck-tagging band
FULL_BOOST = (GROSS * Decimal("0.062")).quantize(Decimal("0.01"))


def _freeze_today(monkeypatch, fixed: date) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)


def _seed_paid_user(db):
    """A user whose own wage-base setting (two paychecks of gross) is already
    exhausted by ten 2026 paychecks in the books."""
    user = models.User(
        username="ss_rollover", hashed_password="x", display_name="SS",
        ss_gross_per_paycheck=GROSS, ss_wage_base=Decimal("40000.00"),
        ss_bonus_ytd=Decimal("0"),
    )
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("10000.00"),
    )
    db.add(account)
    db.flush()
    item = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=NET, type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db.add(item)
    db.flush()
    for i in range(10):
        db.add(models.Transaction(
            user_id=user.id, account_id=account.id, recurring_item_id=item.id,
            date=date(2026, 1 + i, 15), amount=NET, description="Paycheck",
            is_actual=True, source=models.TransactionSource.bank_sync,
        ))
    db.commit()
    return user, account


def _paychecks_by_month(entries):
    return {
        (e.date.year, e.date.month): t.amount
        for e in entries for t in e.transactions
        if t.name == "Paycheck" and not t.is_actual
    }


def test_2027_paychecks_use_the_published_2027_wage_base(db_session, monkeypatch):
    """On Jan 1 the forecast used to reset to the user's own (2026) setting,
    so 2027 paychecks would stop SS withholding against last year's base.
    With 192,300 published: nine 20,000 checks leave 12,300, the tenth
    (October) crosses with 7,700 of excess, and November is fully boosted.
    Against the user's 40,000 setting the boost would start in February."""
    _freeze_today(monkeypatch, date(2026, 10, 31))
    user, account = _seed_paid_user(db_session)

    entries = build_forecast(db_session, user.id, account.id, date(2026, 11, 1), date(2027, 12, 31))
    by_month = _paychecks_by_month(entries)

    assert by_month[(2026, 11)] == NET + FULL_BOOST, "the checkpoint year keeps the user's setting"
    for month in range(1, 10):
        assert by_month[(2027, month)] == NET, f"2027-{month:02d} must still withhold SS"
    assert by_month[(2027, 10)] == NET + (Decimal("7700") * Decimal("0.062")).quantize(Decimal("0.01"))
    assert by_month[(2027, 11)] == NET + FULL_BOOST
