"""Tax estimate: bonus income, pre-tax deductions, and projected withholding.

The estimate used to compare a partial-year YTD withholding figure against a
full-year tax, ignore the annual bonus, and tax wages before 401k/HSA/premium
deductions. Withholding is now projected from one pay stub:

    YTD + this-period x paychecks left after the stub + bonus withholding
    for bonuses paid after the stub (22% federal supplemental + state rate)

All figures are synthetic round numbers. "Today" is never read: every date
is pinned.
"""
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user
from backend.routers import spending as spending_router
from backend.services.forecast_engine import paycheck_dates, paycheck_item_ids
from backend.services.tax_service import (
    SUPPLEMENTAL_FEDERAL_RATE,
    assumed_biweekly_counts,
    estimate_taxes,
)

D = Decimal
SALARY = D("100000")
# Biweekly from Fri 2026-01-02: 26 paydays in 2026, the last on Dec 18.
# 2026-07-03 is the 14th, leaving 12 after it.
FIRST_PAYDAY = date(2026, 1, 2)
AS_OF = date(2026, 7, 3)
IN_2026 = 0.0295


def _estimate(year=2026, *, salary=SALARY, bonuses=(), pretax=None, fed_pp=D("200"),
              state_pp=D("50"), as_of=AS_OF, fed_ytd=D("5000"), state_ytd=D("1500"),
              in_year=26, remaining=12, basis="schedule", state="IN"):
    return estimate_taxes(
        filing_status="single",
        state=state,
        gross_income=salary,
        other_income=D("0"),
        deductible_expenses=D("0"),
        federal_withheld=fed_ytd,
        state_withheld=state_ytd,
        year=year,
        bonuses=bonuses,
        pretax_per_paycheck=pretax,
        federal_per_paycheck=fed_pp,
        state_per_paycheck=state_pp,
        withholding_as_of=as_of,
        paychecks_in_year=in_year,
        paychecks_remaining=remaining,
        paycheck_basis=basis,
    )


# --- Paycheck schedule ------------------------------------------------------

def _seed(db, *, ss_gross=D("4000"), bonus_month=None, bonus_day=15):
    user = models.User(
        username="tax", hashed_password="x", display_name="T",
        annual_salary=SALARY, annual_salary_year=2026, annual_raise_pct=D("0"),
        ss_gross_per_paycheck=ss_gross, tax_filing_status="single", tax_state="IN",
        federal_withholding_ytd=D("5000"), state_withholding_ytd=D("1500"),
        federal_withheld_per_paycheck=D("200"), state_withheld_per_paycheck=D("50"),
        tax_withholding_as_of=AS_OF,
    )
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=D("1000"))
    db.add(acct)
    db.flush()
    pay = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Paycheck", amount=D("2800"),
        type=models.RecurringType.income, frequency=models.RecurringFrequency.biweekly,
        day_of_month=2, start_date=FIRST_PAYDAY,
    )
    rent = models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Rent", amount=D("1500"),
        type=models.RecurringType.expense, frequency=models.RecurringFrequency.monthly,
        day_of_month=1, start_date=FIRST_PAYDAY,
    )
    db.add_all([pay, rent])
    db.flush()
    if bonus_month:
        bonus = models.RecurringItem(
            user_id=user.id, account_id=acct.id, name="Bonus", amount=D("3000"),
            type=models.RecurringType.income, frequency=models.RecurringFrequency.yearly,
            month_of_year=bonus_month, day_of_month=bonus_day, start_date=date(2025, 1, 1),
        )
        db.add(bonus)
        db.flush()
        db.add(models.BonusPlan(user_id=user.id, recurring_item_id=bonus.id, target_pct=D("10"),
                                salary_lag_years=0, withholding_pct=D("30")))
    db.commit()
    return user, pay


def test_paycheck_dates_follow_the_biweekly_schedule(db_session):
    user, pay = _seed(db_session)
    items = db_session.query(models.RecurringItem).all()
    ids = paycheck_item_ids(items, user.ss_gross_per_paycheck, set())
    assert ids == {pay.id}
    paychecks = [i for i in items if i.id in ids]
    year = paycheck_dates(paychecks, date(2026, 1, 1), date(2026, 12, 31))
    assert len(year) == 26 and year[0] == FIRST_PAYDAY and year[-1] == date(2026, 12, 18)
    assert len(paycheck_dates(paychecks, date(2026, 7, 4), date(2026, 12, 31))) == 12


def test_a_bonus_item_is_never_a_paycheck(db_session):
    user, pay = _seed(db_session)
    items = db_session.query(models.RecurringItem).all()
    assert paycheck_item_ids(items, user.ss_gross_per_paycheck, {pay.id}) == set()


# --- Withholding projection ---------------------------------------------------

def test_salary_only_mid_year_projection():
    r = _estimate()
    assert r["withholding_basis"] == "projected"
    assert r["federal_withheld"] == D("5000") + 12 * D("200")
    assert r["state_withheld"] == D("1500") + 12 * D("50")
    fed = r["withholding"]["federal"]
    assert fed["ytd"] == D("5000")
    assert fed["per_paycheck"] == D("200")
    assert fed["remaining_paychecks"] == D("2400")
    assert fed["bonus"] == D("0")
    assert fed["total"] == D("7400")
    assert r["paychecks_in_year"] == 26 and r["paychecks_remaining"] == 12
    assert r["federal_refund_or_owed"] == r["federal_withheld"] - r["federal_tax"]


def test_bonus_after_as_of_adds_gross_and_supplemental_withholding():
    base = _estimate()
    r = _estimate(bonuses=[(date(2026, 9, 15), D("10000"))])
    assert r["bonus_gross"] == D("10000")
    assert r["taxable_income"] == base["taxable_income"] + D("10000")
    assert SUPPLEMENTAL_FEDERAL_RATE == D("0.22")
    assert r["withholding"]["federal"]["bonus"] == D("2200.00")
    assert r["withholding"]["state"]["bonus"] == D("295.00")
    assert r["federal_withheld"] == base["federal_withheld"] + D("2200")
    assert r["state_withheld"] == base["state_withheld"] + D("295")


def test_bonus_before_as_of_is_already_in_ytd():
    base = _estimate()
    r = _estimate(bonuses=[(date(2026, 3, 15), D("10000"))])
    assert r["bonus_gross"] == D("10000")
    assert r["federal_tax"] > base["federal_tax"]
    assert r["withholding"]["federal"]["bonus"] == D("0")
    assert r["federal_withheld"] == base["federal_withheld"]
    assert r["state_withheld"] == base["state_withheld"]


def test_pretax_reduces_income_tax_wages_but_not_fica():
    base = _estimate()
    r = _estimate(pretax=D("500"))
    assert r["pretax_deductions"] == D("13000")
    assert r["taxable_income"] == base["taxable_income"] - D("13000")
    assert r["state_tax"] == base["state_tax"] - D("13000") * D(str(IN_2026))
    assert r["fica_ss"] == base["fica_ss"] == SALARY * D("0.062")
    assert r["fica_medicare"] == base["fica_medicare"]


def test_future_year_uses_full_year_per_paycheck_and_ignores_ytd():
    r = _estimate(year=2027, remaining=26, bonuses=[(date(2027, 3, 15), D("10000"))])
    assert r["withholding_basis"] == "projected_full_year"
    assert r["withholding"]["federal"]["ytd"] == D("0")
    assert r["federal_withheld"] == 26 * D("200") + D("2200")
    assert r["state_withheld"] == 26 * D("50") + D("10000") * D("0.029")


def test_future_year_with_no_as_of_date_is_full_year_too():
    r = _estimate(as_of=None, remaining=26)
    assert r["withholding_basis"] == "projected_full_year"
    assert r["federal_withheld"] == 26 * D("200")


def test_past_year_has_no_withholding_to_compare():
    r = _estimate(year=2025, remaining=0)
    assert r["withholding_basis"] == "past_year"
    assert r["federal_withheld"] == D("0") and r["state_withheld"] == D("0")
    assert r["federal_refund_or_owed"] is None
    assert r["total_refund_or_owed"] is None
    assert r["federal_tax"] > 0


def test_without_per_paycheck_amounts_ytd_is_compared_as_is():
    r = _estimate(fed_pp=None, state_pp=None, bonuses=[(date(2026, 9, 15), D("10000"))])
    assert r["withholding_basis"] == "ytd_only"
    assert r["federal_withheld"] == D("5000") and r["state_withheld"] == D("1500")
    assert r["federal_refund_or_owed"] == D("5000") - r["federal_tax"]


def test_social_security_caps_salary_plus_bonus_at_the_wage_base():
    r = _estimate(salary=D("180000"), bonuses=[(date(2026, 9, 15), D("20000"))])
    assert r["fica_ss"] == D("184500") * D("0.062")
    assert r["fica_medicare"] == D("200000") * D("0.0145")


def test_assumed_biweekly_counts_prorate_by_remaining_days():
    assert assumed_biweekly_counts(2026, AS_OF) == (26, 13)  # 181 of 365 days left
    assert assumed_biweekly_counts(2027, AS_OF) == (26, 26)
    assert assumed_biweekly_counts(2027, None) == (26, 26)
    assert assumed_biweekly_counts(2025, AS_OF) == (26, 0)


def test_legacy_call_without_new_inputs_still_works():
    r = estimate_taxes("single", "TX", SALARY, D("0"), D("0"), D("1000"), D("0"), year=2026)
    assert r["withholding_basis"] == "ytd_only"
    assert r["federal_withheld"] == D("1000")
    assert r["salary"] == SALARY and r["bonus_gross"] == D("0")


# --- Endpoint -------------------------------------------------------------------

def _client(db, user):
    app = FastAPI()
    app.include_router(spending_router.router)
    app.dependency_overrides[spending_router.get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _prefix():
    return spending_router.router.prefix


def test_endpoint_projects_from_schedule_with_bonus_after_as_of(db_session):
    user, _ = _seed(db_session, bonus_month=9)
    r = _client(db_session, user).get(f"{_prefix()}/tax-estimate", params={"year": 2026})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["paycheck_basis"] == "schedule"
    assert body["withholding_basis"] == "projected"
    assert body["paychecks_in_year"] == 26 and body["paychecks_remaining"] == 12
    assert body["salary"] == 100000 and body["bonus_gross"] == 10000
    assert body["withholding"]["federal"]["total"] == 5000 + 12 * 200 + 2200
    assert body["federal_withheld"] == body["withholding"]["federal"]["total"]
    assert body["withholding_as_of"] == "2026-07-03"


def test_endpoint_salary_is_raise_aware(db_session):
    user, _ = _seed(db_session)
    user.annual_raise_pct = D("10")
    db_session.commit()
    body = _client(db_session, user).get(f"{_prefix()}/tax-estimate", params={"year": 2027}).json()
    assert body["salary"] == 110000
    assert body["withholding_basis"] == "projected_full_year"


def test_endpoint_falls_back_to_assumed_biweekly_without_a_paycheck_match(db_session):
    user, _ = _seed(db_session, ss_gross=None)
    body = _client(db_session, user).get(f"{_prefix()}/tax-estimate", params={"year": 2026}).json()
    assert body["paycheck_basis"] == "assumed_biweekly"
    assert body["paychecks_in_year"] == 26 and body["paychecks_remaining"] == 13
