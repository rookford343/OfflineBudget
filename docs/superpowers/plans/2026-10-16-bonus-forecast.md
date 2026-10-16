# Bonus Forecasting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Forecast each annual bonus as a net deposit on its payout date, computed from salary × target % (or a fixed ramp amount), and count its gross toward the Social Security wage base.

**Architecture:** A `BonusPlan` row hangs off a yearly income `RecurringItem` (which already handles firing, Friday shift, matching and actual-suppression). A pure service (`backend/services/bonus_plans.py`) turns salary settings + plan into per-year gross/net. `build_forecast` swaps the item's amount for that year's net and draws the gross down the SS wage base. A `/bonus-plans` router and a Settings → Tax section manage plans.

**Tech Stack:** FastAPI, SQLAlchemy 2, SQLite, Pydantic v2; React + TS + TanStack Query; bun; Python via uv.

**Spec:** `docs/superpowers/specs/2026-10-16-bonus-forecast-design.md`

## Global Constraints

- Public repo: code, comments, tests and commit messages use made-up names and amounts only. Never the user's real salary, bonus, employer or dates.
- Python only through uv: `cd backend && uv run --locked python -m pytest -q`; lint `uv run --locked ruff check .` (repo root). Never bare pip/python.
- Frontend: bun/bunx only. Type-check baseline is 39 errors in 11 files (`cd frontend && bunx tsc -b --force | grep -c "error TS"`); it must not grow.
- The live backend runs `uvicorn --reload` against the real DB: schema changes apply on save. The controller backs up the DB before Task 1 starts.
- Commit directly on `main`, never push (the controller asks the user).
- Money is `Decimal`, quantized to cents (`Decimal("0.01")`).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1: Data model + bonus math service

**Files:**
- Modify: `backend/models.py` (User: two columns; new `BonusPlan`, `BonusPlanYear` classes after `RecurringItem`)
- Modify: `backend/database.py` (append two `ALTER TABLE users` statements to the migration list, after the `drift_dismissed_through` line)
- Create: `backend/services/bonus_plans.py`
- Test: `backend/tests/test_bonus_plans.py`

**Interfaces:**
- Produces:
  - `models.BonusPlan` (`id, user_id, recurring_item_id, target_pct, salary_lag_years, withholding_pct, recurring_item, years`)
  - `models.BonusPlanYear` (`id, plan_id, year, gross_amount`)
  - `User.annual_salary_year: int | None`, `User.annual_raise_pct: Decimal | None`
  - `salary_for_year(user, year: int) -> Decimal | None`
  - `bonus_gross(plan, user, year: int) -> Decimal | None`
  - `bonus_net(plan, gross: Decimal) -> Decimal`
  - `payout_date(item, year: int) -> date`
  - `plans_by_item(db, user_id: int) -> dict[int, models.BonusPlan]`
  - `upcoming_payouts(plan, user, today: date, count: int = 3) -> list[dict]` (keys `year, date, gross, net`)
  - `refresh_item_amounts(db, user, today: date) -> None` (commits)

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_bonus_plans.py`

```python
"""Bonus plan math: salary by year, gross from target % or a fixed ramp
amount, net after withholding, and keeping the backing item's amount equal
to the next payout. All figures are made up."""
from datetime import date
from decimal import Decimal

import pytest

from backend import models
from backend.services.bonus_plans import (
    bonus_gross, bonus_net, payout_date, plans_by_item, refresh_item_amounts,
    salary_for_year, upcoming_payouts,
)


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run --locked python -m pytest -q tests/test_bonus_plans.py`
Expected: collection error, `ModuleNotFoundError: backend.services.bonus_plans`.

- [ ] **Step 3: Model columns and tables** — in `backend/models.py`, add to `User` directly under `annual_salary`:

```python
    # Bonus forecasting (services/bonus_plans.py): the year annual_salary is
    # for, and the expected yearly raise in percent, so later years' salary
    # (and so a %-of-salary bonus) can be projected.
    annual_salary_year: Mapped[int | None] = mapped_column(Integer)
    annual_raise_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
```

Add after the `RecurringItem` class:

```python
class BonusPlan(Base):
    """An annual bonus paid through a yearly income RecurringItem. The item
    carries the date, account and matching; the plan supplies each year's
    amount (services/bonus_plans.py)."""
    __tablename__ = "bonus_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    recurring_item_id: Mapped[int] = mapped_column(Integer, ForeignKey("recurring_items.id"), nullable=False, unique=True)
    target_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    # Which year's salary the % applies to: 1 = last year's, 3 = a grant that
    # vests over three years and pays on the salary from three years back.
    salary_lag_years: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    withholding_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    recurring_item: Mapped[RecurringItem] = relationship()
    years: Mapped[list[BonusPlanYear]] = relationship(cascade="all, delete-orphan", order_by="BonusPlanYear.year")


class BonusPlanYear(Base):
    """A fixed gross amount for one year (e.g. a ramp year the employer states
    outright). Wins over the target-% formula."""
    __tablename__ = "bonus_plan_years"
    __table_args__ = (UniqueConstraint("plan_id", "year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("bonus_plans.id", ondelete="CASCADE"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
```

In `backend/database.py`, append after the `drift_dismissed_through` statement:

```python
        # Bonus forecasting -- see services/bonus_plans.py. bonus_plans and
        # bonus_plan_years are new tables, created by create_all.
        "ALTER TABLE users ADD COLUMN annual_salary_year INTEGER",
        "ALTER TABLE users ADD COLUMN annual_raise_pct NUMERIC(6,3)",
```

- [ ] **Step 4: Service** — `backend/services/bonus_plans.py`

```python
"""Annual bonus amounts.

A BonusPlan pays through a yearly income RecurringItem. For payout year Y:

    gross = fixed amount for Y (BonusPlanYear), else
            target_pct% x salary(Y - salary_lag_years)
    net   = gross x (1 - withholding_pct%)

salary(Y) = users.annual_salary x (1 + annual_raise_pct%)^(Y - annual_salary_year).
Unknown (None) when the salary settings are incomplete and no fixed amount
covers the year.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models

CENT = Decimal("0.01")


def salary_for_year(user: models.User, year: int) -> Decimal | None:
    if not user.annual_salary or not user.annual_salary_year:
        return None
    growth = Decimal(1) + Decimal(user.annual_raise_pct or 0) / 100
    return (Decimal(user.annual_salary) * growth ** (year - user.annual_salary_year)).quantize(CENT)


def bonus_gross(plan: models.BonusPlan, user: models.User, year: int) -> Decimal | None:
    for fixed in plan.years:
        if fixed.year == year:
            return Decimal(fixed.gross_amount).quantize(CENT)
    salary = salary_for_year(user, year - plan.salary_lag_years)
    if salary is None:
        return None
    return (salary * Decimal(plan.target_pct) / 100).quantize(CENT)


def bonus_net(plan: models.BonusPlan, gross: Decimal) -> Decimal:
    return (gross * (Decimal(1) - Decimal(plan.withholding_pct) / 100)).quantize(CENT)


def payout_date(item: models.RecurringItem, year: int) -> date:
    from calendar import monthrange
    last = monthrange(year, item.month_of_year)[1]
    day = last if item.day_of_month == 0 else min(item.day_of_month, last)
    return date(year, item.month_of_year, day)


def plans_by_item(db: Session, user_id: int) -> dict[int, models.BonusPlan]:
    plans = db.query(models.BonusPlan).filter(models.BonusPlan.user_id == user_id).all()
    return {p.recurring_item_id: p for p in plans}


def upcoming_payouts(plan: models.BonusPlan, user: models.User, today: date, count: int = 3) -> list[dict]:
    item = plan.recurring_item
    year = today.year if payout_date(item, today.year) >= today else today.year + 1
    rows = []
    for y in range(year, year + count):
        gross = bonus_gross(plan, user, y)
        rows.append({"year": y, "date": payout_date(item, y), "gross": gross,
                     "net": bonus_net(plan, gross) if gross is not None else None})
    return rows


def refresh_item_amounts(db: Session, user: models.User, today: date) -> None:
    """Keep each bonus item's amount equal to its next payout's net, so the
    Recurring page, budget totals and the matcher's amount check see a real
    figure. Leaves the amount alone when the next gross is unknown."""
    for plan in plans_by_item(db, user.id).values():
        nxt = upcoming_payouts(plan, user, today, count=1)[0]
        if nxt["net"] is not None and nxt["net"] > 0:
            plan.recurring_item.amount = nxt["net"]
    db.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run --locked python -m pytest -q tests/test_bonus_plans.py`
Expected: all pass. Then the full suite: `uv run --locked python -m pytest -q` (all pass) and `cd .. && uv run --locked ruff check .` (clean).

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/database.py backend/services/bonus_plans.py backend/tests/test_bonus_plans.py
git commit -m "feat(bonus): bonus plan model and per-year gross/net math

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Forecast engine — bonus amount and Social Security

**Files:**
- Modify: `backend/services/forecast_engine.py` (SS setup block near the `ss_paycheck_item_ids` loop; the received-paychecks reconciliation block; the per-item projection in the day walk)
- Test: `backend/tests/test_bonus_forecast.py`

**Interfaces:**
- Consumes: `plans_by_item`, `bonus_gross`, `bonus_net` from Task 1.
- Produces: projected bonus `ForecastTransaction` rows with `recurring_item_id` = the bonus item and `amount` = net (+ any SS boost).

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_bonus_forecast.py`

```python
"""Bonuses in the day-by-day forecast: the plan's net for that year lands on
the payout date, and the gross counts toward the Social Security wage base.
All figures are made up."""
from datetime import date
from decimal import Decimal

from backend import models
from backend.services.forecast_engine import build_forecast

GROSS_PAY = Decimal("5000.00")       # per paycheck, gross
NET_PAY = Decimal("3500.00")
BOOST = (GROSS_PAY * Decimal("0.062")).quantize(Decimal("0.01"))


def _seed(db, *, wage_base="1000000", month=4, day=15, pay_day=None, fixed=None, salary="100000"):
    user = models.User(username=f"bf{wage_base}{month}{day}", hashed_password="x", display_name="B",
                       annual_salary=Decimal(salary), annual_salary_year=2026, annual_raise_pct=Decimal("0"),
                       ss_gross_per_paycheck=GROSS_PAY, ss_wage_base=Decimal(wage_base),
                       ss_bonus_ytd=Decimal("0"))
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("1000"))
    db.add(acct)
    db.flush()
    pay = models.RecurringItem(user_id=user.id, account_id=acct.id, name="Paycheck", amount=NET_PAY,
                               type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
                               day_of_month=pay_day or day, start_date=date(2026, 1, 1))
    bonus = models.RecurringItem(user_id=user.id, account_id=acct.id, name="Annual Bonus", amount=Decimal("1"),
                                 type=models.RecurringType.income, frequency=models.RecurringFrequency.yearly,
                                 month_of_year=month, day_of_month=day, start_date=date(2026, 1, 1))
    db.add_all([pay, bonus])
    db.flush()
    plan = models.BonusPlan(user_id=user.id, recurring_item_id=bonus.id, target_pct=Decimal("20"),
                            salary_lag_years=1, withholding_pct=Decimal("30"))
    db.add(plan)
    db.flush()
    for year, gross in (fixed or {}).items():
        db.add(models.BonusPlanYear(plan_id=plan.id, year=year, gross_amount=Decimal(gross)))
    db.commit()
    return user, acct, pay, bonus


def _lines(entries, item_id):
    return [(e.date, t.amount) for e in entries for t in e.transactions
            if t.recurring_item_id == item_id and not t.is_actual]


def test_bonus_lands_at_net_on_its_date(db_session):
    user, acct, _, bonus = _seed(db_session)
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 12, 31))
    assert _lines(entries, bonus.id) == [(date(2027, 4, 15), Decimal("14000.00"))]


def test_each_year_uses_its_own_amount(db_session):
    user, acct, _, bonus = _seed(db_session, fixed={2028: "30000"})
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2028, 12, 31))
    assert [amt for _, amt in _lines(entries, bonus.id)] == [Decimal("14000.00"), Decimal("21000.00")]


def test_a_weekend_payout_moves_to_friday(db_session):
    # 2027-05-15 is a Saturday.
    user, acct, _, bonus = _seed(db_session, month=5)
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 12, 31))
    assert [d for d, _ in _lines(entries, bonus.id)] == [date(2027, 5, 14)]


def test_a_linked_deposit_replaces_the_projection(db_session):
    user, acct, _, bonus = _seed(db_session)
    db_session.add(models.Transaction(user_id=user.id, account_id=acct.id, recurring_item_id=bonus.id,
                                      date=date(2027, 4, 15), amount=Decimal("13900.00"),
                                      description="PAYROLL", is_actual=True))
    db_session.commit()
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 12, 31))
    assert _lines(entries, bonus.id) == []


def test_the_bonus_is_never_tagged_as_a_paycheck(db_session):
    """A bonus whose net happens to sit near a paycheck's gross must not get
    the paycheck SS boost or be drawn down as one."""
    user, acct, _, bonus = _seed(db_session, wage_base="10000", fixed={2027: "6000"})  # net 4200 ~ 0.84 x gross pay
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 12, 31))
    assert _lines(entries, bonus.id) == [(date(2027, 4, 15), Decimal("4200.00") + (Decimal("6000") * Decimal("0.062")).quantize(Decimal("0.01")))]


def test_bonus_gross_pulls_the_ss_crossing_earlier(db_session):
    """Wage base = 3 paychecks + the bonus. The Jan-Mar paychecks and the
    April 10 bonus use it up exactly, so April 20's paycheck is the first
    boosted one. Without counting the bonus, the boost would not start until
    several paychecks later."""
    base = GROSS_PAY * 3 + Decimal("20000")
    user, acct, pay, _ = _seed(db_session, wage_base=str(base), day=10, pay_day=20)
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 6, 30))
    checks = _lines(entries, pay.id)
    assert [amt for _, amt in checks[:3]] == [NET_PAY] * 3
    assert checks[3][1] == NET_PAY + BOOST   # April 20, after the Apr 9 (Friday) bonus used the rest of the base
    assert checks[4][1] == NET_PAY + BOOST


def test_a_bonus_that_crosses_the_base_gets_a_partial_boost(db_session):
    base = GROSS_PAY * 3 + Decimal("5000")   # 15,000 of the 20,000 bonus is above the base
    user, acct, _, bonus = _seed(db_session, wage_base=str(base), day=10, pay_day=20)
    entries = build_forecast(db_session, user.id, acct.id, date(2027, 1, 1), date(2027, 6, 30))
    [(_, amt)] = _lines(entries, bonus.id)
    assert amt == Decimal("14000.00") + (Decimal("15000") * Decimal("0.062")).quantize(Decimal("0.01"))
```

Note: in the two SS-crossing tests the bonus pays on the 10th and paychecks on the 20th, so the bonus always draws the base down before April's paycheck. 2027-04-10 is a Saturday, so the bonus lands Friday Apr 9.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run --locked python -m pytest -q tests/test_bonus_forecast.py`
Expected: failures (the bonus projects at `Decimal("1")`, no SS effect).

- [ ] **Step 3: Engine changes** — in `backend/services/forecast_engine.py`:

(a) Directly after `user = db.query(models.User)...first()` in the SS setup block, load plans:

```python
    from backend.services.bonus_plans import bonus_gross, bonus_net, plans_by_item
    bonus_plans = plans_by_item(db, user_id) if user else {}
```

(b) In the loop that tags paychecks, skip bonus items:

```python
        for item in recurring_items:
            if item.id in bonus_plans:
                continue  # a bonus is never a paycheck, whatever its net/gross ratio
            if item.type == models.RecurringType.income and item.amount > 0:
```

(c) After the existing received-paychecks reconciliation block (the one ending `ss_limit_reached = True`), add bonus reconciliation, checkpoint mode only:

```python
    # Bonuses received after the pay-stub checkpoint also used up wage base.
    # Only in checkpoint mode: the legacy ss_bonus_ytd figure already holds
    # the user's bonus, so counting deposits there would double it.
    if ss_remaining_gross is not None and ss_checkpoint_date is not None and bonus_plans:
        for t in db.query(models.Transaction).filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.recurring_item_id.in_(list(bonus_plans)),
            models.Transaction.date > ss_checkpoint_date,
            models.Transaction.date < today,
        ):
            gross = bonus_gross(bonus_plans[t.recurring_item_id], user, t.date.year)
            if gross is not None and t.date.year == ss_checkpoint_date.year:
                ss_remaining_gross -= gross
        if ss_remaining_gross <= 0:
            ss_limit_reached = True
```

(d) In the day walk, replace the `base_amount` assignment block:

```python
            actual_override = bill_actuals.get((item.id, current))
            bonus_plan = bonus_plans.get(item.id)
            bonus_gross_amt = bonus_gross(bonus_plan, user, current.year) if bonus_plan else None
            if actual_override is not None:
                base_amount = actual_override
            elif bonus_gross_amt is not None:
                base_amount = bonus_net(bonus_plan, bonus_gross_amt) + override_map.get(item.id, Decimal("0"))
            else:
                base_amount = item.amount + override_map.get(item.id, Decimal("0"))
```

and extend the SS branch with a bonus case after the existing `elif ss_remaining_gross is not None and item.id in ss_paycheck_item_ids:` block (same indentation, before `signed = ...`):

```python
            elif ss_remaining_gross is not None and bonus_gross_amt is not None and current != ss_checkpoint_date:
                # A bonus is wages too: its gross draws the base down, and SS
                # withheld on whatever lies above the base comes back.
                if ss_limit_reached:
                    ss_boost = (bonus_gross_amt * Decimal("0.062")).quantize(Decimal("0.01"))
                else:
                    ss_remaining_gross -= bonus_gross_amt
                    if ss_remaining_gross <= 0:
                        ss_limit_reached = True
                        excess = min(-ss_remaining_gross, bonus_gross_amt)
                        ss_boost = (excess * Decimal("0.062")).quantize(Decimal("0.01"))
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run --locked python -m pytest -q tests/test_bonus_forecast.py tests/test_ss_paycheck_boost.py`
Expected: all pass. Then full suite and ruff as in Task 1.

- [ ] **Step 5: Prove a test can fail** — temporarily delete the `if item.id in bonus_plans: continue` line, run `tests/test_bonus_forecast.py::test_the_bonus_is_never_tagged_as_a_paycheck`, see it fail, restore.

- [ ] **Step 6: Commit**

```bash
git add backend/services/forecast_engine.py backend/tests/test_bonus_forecast.py
git commit -m "feat(forecast): project bonuses at each year's net and count them toward the SS wage base

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: API — bonus plans and salary settings

**Files:**
- Create: `backend/routers/bonus_plans.py`
- Modify: `backend/main.py` (import + `app.include_router(bonus_plans_router_module.router)` beside the other `*_router_module` lines)
- Modify: `backend/schemas.py` (UserOut/UserUpdate fields; new bonus schemas)
- Modify: `backend/routers/auth.py` (`update_me`: refresh bonus amounts after commit)
- Test: `backend/tests/test_bonus_plans_api.py`; add one case to `backend/tests/test_security_regressions.py`

**Interfaces:**
- Consumes: Task 1 service functions and models.
- Produces (HTTP, used by Task 4):
  - `GET /bonus-plans` → `list[BonusPlanOut]`
  - `POST /bonus-plans` body `BonusPlanIn` → `BonusPlanOut` (201)
  - `PUT /bonus-plans/{id}` body `BonusPlanIn` → `BonusPlanOut`
  - `DELETE /bonus-plans/{id}` → 204
  - `BonusPlanOut` = `{id, recurring_item_id, item_name, target_pct, salary_lag_years, withholding_pct, years: [{year, gross_amount}], upcoming: [{year, date, gross, net}]}`
  - `UserOut`/`UserUpdate` gain `annual_salary_year: int | None`, `annual_raise_pct: Decimal | None`

- [ ] **Step 1: Schemas** — in `backend/schemas.py` add `annual_salary_year: Optional[int] = None` and `annual_raise_pct: Optional[Decimal] = None` to both `UserOut` and `UserUpdate` (next to `annual_salary`). In `UserUpdate` add validators:

```python
    @field_validator("annual_salary_year")
    @classmethod
    def validate_salary_year(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (2000 <= v <= 2100):
            raise ValueError("annual_salary_year must be 2000-2100")
        return v

    @field_validator("annual_raise_pct")
    @classmethod
    def validate_raise(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and not (0 <= v <= 25):
            raise ValueError("annual_raise_pct must be 0-25")
        return v
```

Add bonus schemas:

```python
class BonusPlanYearIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    gross_amount: Decimal = Field(gt=0)


class BonusPlanIn(BaseModel):
    recurring_item_id: int
    target_pct: Decimal = Field(ge=0, le=100)
    salary_lag_years: int = Field(ge=0, le=5)
    withholding_pct: Decimal = Field(ge=0, le=90)
    years: list[BonusPlanYearIn] = []

    @field_validator("years")
    @classmethod
    def unique_years(cls, v: list[BonusPlanYearIn]) -> list[BonusPlanYearIn]:
        if len({y.year for y in v}) != len(v):
            raise ValueError("each year may appear once")
        return v


class BonusPayoutOut(BaseModel):
    year: int
    date: date
    gross: Optional[Decimal]
    net: Optional[Decimal]


class BonusPlanOut(BaseModel):
    id: int
    recurring_item_id: int
    item_name: str
    target_pct: Decimal
    salary_lag_years: int
    withholding_pct: Decimal
    years: list[BonusPlanYearIn]
    upcoming: list[BonusPayoutOut]
```

(Check `Field` is imported from pydantic at the top of schemas.py; add it if not.)

- [ ] **Step 2: Write the failing API tests** — `backend/tests/test_bonus_plans_api.py`

```python
"""/bonus-plans CRUD. Made-up figures."""
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user
from backend.routers import bonus_plans as bonus_router


def _client(db, user):
    app = FastAPI()
    app.include_router(bonus_router.router)
    app.dependency_overrides[bonus_router.get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db, username="api"):
    user = models.User(username=username, hashed_password="x", display_name="A",
                       annual_salary=Decimal("100000"), annual_salary_year=2026, annual_raise_pct=Decimal("0"))
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                          current_balance=Decimal("1"))
    db.add(acct)
    db.flush()
    item = models.RecurringItem(user_id=user.id, account_id=acct.id, name="Annual Bonus", amount=Decimal("1"),
                                type=models.RecurringType.income, frequency=models.RecurringFrequency.yearly,
                                month_of_year=4, day_of_month=15, start_date=date(2026, 1, 1))
    db.add(item)
    db.commit()
    return user, item


BODY = {"target_pct": "20", "salary_lag_years": 1, "withholding_pct": "30",
        "years": [{"year": 2027, "gross_amount": "12000"}]}


def test_create_list_update_delete(db_session):
    user, item = _seed(db_session)
    c = _client(db_session, user)
    r = c.post("/bonus-plans", json={**BODY, "recurring_item_id": item.id})
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["item_name"] == "Annual Bonus"
    assert len(plan["upcoming"]) == 3
    db_session.refresh(item)
    assert item.amount == Decimal(plan["upcoming"][0]["net"])
    r = c.put(f"/bonus-plans/{plan['id']}", json={**BODY, "recurring_item_id": item.id, "years": []})
    assert r.status_code == 200 and r.json()["years"] == []
    assert len(c.get("/bonus-plans").json()) == 1
    assert c.delete(f"/bonus-plans/{plan['id']}").status_code == 204
    assert c.get("/bonus-plans").json() == []


def test_one_plan_per_item(db_session):
    user, item = _seed(db_session)
    c = _client(db_session, user)
    assert c.post("/bonus-plans", json={**BODY, "recurring_item_id": item.id}).status_code == 201
    assert c.post("/bonus-plans", json={**BODY, "recurring_item_id": item.id}).status_code == 409


def test_item_must_be_a_yearly_income_item(db_session):
    user, item = _seed(db_session)
    item.frequency = models.RecurringFrequency.monthly
    db_session.commit()
    assert _client(db_session, user).post("/bonus-plans", json={**BODY, "recurring_item_id": item.id}).status_code == 422


def test_duplicate_years_are_refused(db_session):
    user, item = _seed(db_session)
    body = {**BODY, "recurring_item_id": item.id,
            "years": [{"year": 2027, "gross_amount": "1"}, {"year": 2027, "gross_amount": "2"}]}
    assert _client(db_session, user).post("/bonus-plans", json=body).status_code == 422
```

Add to `backend/tests/test_security_regressions.py` (and a line to its module docstring list: "bonus plans: another user's plan or item is 404, never readable or editable"):

```python
def test_bonus_plans_are_user_scoped(db_session):
    from datetime import date
    from decimal import Decimal
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend import models
    from backend.dependencies import get_current_user
    from backend.routers import bonus_plans as bonus_router

    def client(user):
        app = FastAPI()
        app.include_router(bonus_router.router)
        app.dependency_overrides[bonus_router.get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    owner = models.User(username="bp-owner", hashed_password="x", display_name="O")
    other = models.User(username="bp-other", hashed_password="x", display_name="X")
    db_session.add_all([owner, other])
    db_session.flush()
    acct = models.Account(user_id=owner.id, name="C", type=models.AccountType.checking, current_balance=Decimal("1"))
    db_session.add(acct)
    db_session.flush()
    item = models.RecurringItem(user_id=owner.id, account_id=acct.id, name="Bonus", amount=Decimal("1"),
                                type=models.RecurringType.income, frequency=models.RecurringFrequency.yearly,
                                month_of_year=4, day_of_month=15, start_date=date(2026, 1, 1))
    db_session.add(item)
    db_session.commit()
    body = {"recurring_item_id": item.id, "target_pct": "20", "salary_lag_years": 1, "withholding_pct": "30", "years": []}
    assert client(other).post("/bonus-plans", json=body).status_code == 404
    plan_id = client(owner).post("/bonus-plans", json=body).json()["id"]
    assert client(other).put(f"/bonus-plans/{plan_id}", json=body).status_code == 404
    assert client(other).delete(f"/bonus-plans/{plan_id}").status_code == 404
    assert client(other).get("/bonus-plans").json() == []
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd backend && uv run --locked python -m pytest -q tests/test_bonus_plans_api.py tests/test_security_regressions.py -k bonus`
Expected: ImportError for `backend.routers.bonus_plans`.

- [ ] **Step 4: Router** — `backend/routers/bonus_plans.py`

```python
"""Annual bonus plans (see services/bonus_plans.py)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.database import SessionLocal
from backend.dependencies import get_current_user
from backend.services.bonus_plans import refresh_item_amounts, upcoming_payouts

router = APIRouter(prefix="/bonus-plans", tags=["bonus-plans"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _out(plan: models.BonusPlan, user: models.User) -> schemas.BonusPlanOut:
    return schemas.BonusPlanOut(
        id=plan.id, recurring_item_id=plan.recurring_item_id, item_name=plan.recurring_item.name,
        target_pct=plan.target_pct, salary_lag_years=plan.salary_lag_years, withholding_pct=plan.withholding_pct,
        years=[schemas.BonusPlanYearIn(year=y.year, gross_amount=y.gross_amount) for y in plan.years],
        upcoming=[schemas.BonusPayoutOut(**row) for row in upcoming_payouts(plan, user, date.today())],
    )


def _own_item(db: Session, user: models.User, item_id: int) -> models.RecurringItem:
    item = db.query(models.RecurringItem).filter(
        models.RecurringItem.id == item_id, models.RecurringItem.user_id == user.id,
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Recurring item not found")
    if item.type != models.RecurringType.income or item.frequency != models.RecurringFrequency.yearly:
        raise HTTPException(status_code=422, detail="A bonus must use a yearly income item")
    return item


def _own_plan(db: Session, user: models.User, plan_id: int) -> models.BonusPlan:
    plan = db.query(models.BonusPlan).filter(
        models.BonusPlan.id == plan_id, models.BonusPlan.user_id == user.id,
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Bonus plan not found")
    return plan


def _apply(plan: models.BonusPlan, body: schemas.BonusPlanIn) -> None:
    plan.recurring_item_id = body.recurring_item_id
    plan.target_pct = body.target_pct
    plan.salary_lag_years = body.salary_lag_years
    plan.withholding_pct = body.withholding_pct
    plan.years = [models.BonusPlanYear(year=y.year, gross_amount=y.gross_amount) for y in body.years]


def _taken(db: Session, item_id: int, except_id: int | None = None) -> bool:
    q = db.query(models.BonusPlan).filter(models.BonusPlan.recurring_item_id == item_id)
    if except_id is not None:
        q = q.filter(models.BonusPlan.id != except_id)
    return q.first() is not None


@router.get("", response_model=list[schemas.BonusPlanOut])
def list_plans(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    refresh_item_amounts(db, user, date.today())
    plans = db.query(models.BonusPlan).filter(models.BonusPlan.user_id == user.id).order_by(models.BonusPlan.id).all()
    return [_out(p, user) for p in plans]


@router.post("", response_model=schemas.BonusPlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(body: schemas.BonusPlanIn, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    _own_item(db, user, body.recurring_item_id)
    if _taken(db, body.recurring_item_id):
        raise HTTPException(status_code=409, detail="That item already has a bonus plan")
    plan = models.BonusPlan(user_id=user.id)
    _apply(plan, body)
    db.add(plan)
    db.commit()
    refresh_item_amounts(db, user, date.today())
    db.refresh(plan)
    return _out(plan, user)


@router.put("/{plan_id}", response_model=schemas.BonusPlanOut)
def update_plan(plan_id: int, body: schemas.BonusPlanIn, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    plan = _own_plan(db, user, plan_id)
    _own_item(db, user, body.recurring_item_id)
    if _taken(db, body.recurring_item_id, except_id=plan.id):
        raise HTTPException(status_code=409, detail="That item already has a bonus plan")
    _apply(plan, body)
    db.commit()
    refresh_item_amounts(db, user, date.today())
    db.refresh(plan)
    return _out(plan, user)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.delete(_own_plan(db, user, plan_id))
    db.commit()
```

Register in `backend/main.py`: add `from backend.routers import bonus_plans as bonus_plans_router_module` next to the other `*_router_module` imports and `app.include_router(bonus_plans_router_module.router)` after the wish-list line.

In `backend/routers/auth.py` `update_me`, after `db.refresh(current_user)` and before `return`:

```python
    # Salary or raise changes move every %-of-salary bonus.
    from datetime import date
    from backend.services.bonus_plans import refresh_item_amounts
    refresh_item_amounts(db, current_user, date.today())
```

- [ ] **Step 5: Run tests** — the two files above, then the full suite, ruff, and `uv run --locked python -c "import backend.main, cli.budget"`. All pass.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/bonus_plans.py backend/main.py backend/schemas.py backend/routers/auth.py backend/tests/test_bonus_plans_api.py backend/tests/test_security_regressions.py
git commit -m "feat(bonus): bonus plan API and salary-year/raise settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Settings → Tax "Salary & bonuses" UI + docs

**Files:**
- Create: `frontend/src/pages/settings/BonusPlansSection.tsx`
- Modify: `frontend/src/pages/settings/TaxTab.tsx` (render `<BonusPlansSection />` at the end of the card's content)
- Modify: `frontend/src/api/index.ts` (add `bonusPlansApi`)
- Modify: `docs/start-guide.md` (short "Bonuses" subsection under the Forecast step)

**Interfaces:**
- Consumes: Task 3 HTTP API; `authApi.me`/`authApi.updateMe` (`annual_salary`, `annual_salary_year`, `annual_raise_pct`); `recurringApi.list()`.

- [ ] **Step 1: API client** — in `frontend/src/api/index.ts`:

```ts
export const bonusPlansApi = {
  list: () => api.get("/bonus-plans").then((r) => r.data),
  create: (data: object) => api.post("/bonus-plans", data).then((r) => r.data),
  update: (id: number, data: object) => api.put(`/bonus-plans/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/bonus-plans/${id}`),
};
```

- [ ] **Step 2: Component** — `frontend/src/pages/settings/BonusPlansSection.tsx`

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authApi, bonusPlansApi, recurringApi } from "../../api";
import { fmt } from "../../lib/utils";
import { Plus, Trash2 } from "lucide-react";

type Draft = {
  id?: number;
  recurring_item_id: string;
  target_pct: string;
  salary_lag_years: string;
  withholding_pct: string;
  years: { year: string; gross_amount: string }[];
};

const blank: Draft = { recurring_item_id: "", target_pct: "20", salary_lag_years: "1", withholding_pct: "", years: [] };

/** Salary settings and annual bonus plans. Each plan pays through a yearly
 *  income item (created on the Recurring page); the forecast adds that
 *  year's net on the item's date and counts the gross toward the Social
 *  Security wage base. */
export default function BonusPlansSection() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const { data: plans = [] } = useQuery<any[]>({ queryKey: ["bonus-plans"], queryFn: bonusPlansApi.list });
  const { data: items = [] } = useQuery<any[]>({ queryKey: ["recurring"], queryFn: () => recurringApi.list(false) });
  const yearlyIncome = items.filter((i: any) => i.type === "income" && i.frequency === "yearly" && i.is_active);

  const [salary, setSalary] = useState("");
  const [salaryYear, setSalaryYear] = useState("");
  const [raise, setRaise] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);

  useEffect(() => {
    if (me) {
      setSalary(me.annual_salary ?? "");
      setSalaryYear(me.annual_salary_year != null ? String(me.annual_salary_year) : String(new Date().getFullYear()));
      setRaise(me.annual_raise_pct ?? "");
    }
  }, [me]);

  const invalidate = () => {
    ["me", "bonus-plans", "recurring", "forecast-quarters", "forecast-multi-year", "forecast-risk", "budget-snapshot"]
      .forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  };
  const salaryMut = useMutation({ mutationFn: authApi.updateMe, onSuccess: invalidate });
  const saveMut = useMutation({
    mutationFn: (d: Draft) => {
      const body = {
        recurring_item_id: parseInt(d.recurring_item_id),
        target_pct: d.target_pct, salary_lag_years: parseInt(d.salary_lag_years), withholding_pct: d.withholding_pct,
        years: d.years.filter((y) => y.year && y.gross_amount).map((y) => ({ year: parseInt(y.year), gross_amount: y.gross_amount })),
      };
      return d.id ? bonusPlansApi.update(d.id, body) : bonusPlansApi.create(body);
    },
    onSuccess: () => { invalidate(); setDraft(null); },
  });
  const deleteMut = useMutation({ mutationFn: (id: number) => bonusPlansApi.remove(id), onSuccess: invalidate });

  const edit = (p: any) => setDraft({
    id: p.id, recurring_item_id: String(p.recurring_item_id), target_pct: String(p.target_pct),
    salary_lag_years: String(p.salary_lag_years), withholding_pct: String(p.withholding_pct),
    years: p.years.map((y: any) => ({ year: String(y.year), gross_amount: String(y.gross_amount) })),
  });

  return (
    <div className="space-y-3 pt-6 mt-6 border-t border-gray-100 dark:border-gray-800">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100">Salary & bonuses</h3>
      <p className="text-xs text-gray-500 dark:text-gray-400">
        Bonuses are forecast on their pay date at the net amount, and their gross counts toward the Social Security wage base.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl">
        <div><label className="label">Base salary (gross)</label>
          <input type="number" className="input" value={salary} onChange={(e) => setSalary(e.target.value)} /></div>
        <div><label className="label">For year</label>
          <input type="number" className="input" value={salaryYear} onChange={(e) => setSalaryYear(e.target.value)} /></div>
        <div><label className="label">Expected yearly raise %</label>
          <input type="number" step="0.1" className="input" value={raise} onChange={(e) => setRaise(e.target.value)} /></div>
      </div>
      <button className="btn-secondary text-sm" disabled={salaryMut.isPending}
        onClick={() => salaryMut.mutate({ annual_salary: salary || null, annual_salary_year: salaryYear ? parseInt(salaryYear) : null, annual_raise_pct: raise || null })}>
        Save salary
      </button>

      <div className="space-y-2">
        {plans.map((p: any) => (
          <div key={p.id} className="rounded-lg border border-gray-100 dark:border-gray-800 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-gray-900 dark:text-white">{p.item_name}</p>
              <div className="flex gap-2">
                <button className="text-xs text-indigo-500 hover:underline" onClick={() => edit(p)}>Edit</button>
                <button className="text-gray-400 hover:text-red-500" aria-label={`Delete ${p.item_name} plan`}
                  onClick={() => deleteMut.mutate(p.id)}><Trash2 size={14} /></button>
              </div>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {p.target_pct}% of {p.salary_lag_years === 1 ? "last year's" : `the salary ${p.salary_lag_years} years back`} · {p.withholding_pct}% withheld
            </p>
            <div className="text-xs text-gray-600 dark:text-gray-300 mt-1 flex flex-wrap gap-x-4">
              {p.upcoming.map((u: any) => (
                <span key={u.year}>{u.year}: {u.gross != null ? `${fmt(u.gross)} gross → ${fmt(u.net)} net` : "salary not set"}</span>
              ))}
            </div>
          </div>
        ))}
      </div>

      {draft ? (
        <div className="rounded-lg border border-indigo-200 dark:border-indigo-900 p-3 space-y-2 max-w-xl">
          <div><label className="label">Paid through (yearly income item)</label>
            <select className="input" value={draft.recurring_item_id}
              onChange={(e) => setDraft({ ...draft, recurring_item_id: e.target.value })}>
              <option value="">Choose…</option>
              {yearlyIncome.map((i: any) => <option key={i.id} value={i.id}>{i.name}</option>)}
            </select>
            {yearlyIncome.length === 0 && (
              <p className="text-xs text-amber-600 mt-1">Add a yearly income item on the Recurring page first (frequency Yearly, its pay date).</p>
            )}
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div><label className="label">Target %</label>
              <input type="number" step="0.1" className="input" value={draft.target_pct}
                onChange={(e) => setDraft({ ...draft, target_pct: e.target.value })} /></div>
            <div><label className="label">Based on salary</label>
              <select className="input" value={draft.salary_lag_years}
                onChange={(e) => setDraft({ ...draft, salary_lag_years: e.target.value })}>
                <option value="1">Last year</option>
                <option value="2">2 years back</option>
                <option value="3">3 years back</option>
              </select></div>
            <div><label className="label">Withheld %</label>
              <input type="number" step="0.01" className="input" value={draft.withholding_pct}
                onChange={(e) => setDraft({ ...draft, withholding_pct: e.target.value })} /></div>
          </div>
          <div>
            <label className="label">Fixed amounts (gross, e.g. ramp years)</label>
            {draft.years.map((y, i) => (
              <div key={i} className="flex gap-2 mb-1">
                <input type="number" className="input w-24" placeholder="Year" value={y.year}
                  onChange={(e) => setDraft({ ...draft, years: draft.years.map((r, j) => j === i ? { ...r, year: e.target.value } : r) })} />
                <input type="number" className="input" placeholder="Gross" value={y.gross_amount}
                  onChange={(e) => setDraft({ ...draft, years: draft.years.map((r, j) => j === i ? { ...r, gross_amount: e.target.value } : r) })} />
                <button className="text-gray-400 hover:text-red-500" aria-label="Remove year"
                  onClick={() => setDraft({ ...draft, years: draft.years.filter((_, j) => j !== i) })}><Trash2 size={14} /></button>
              </div>
            ))}
            <button className="text-xs text-indigo-500 hover:underline"
              onClick={() => setDraft({ ...draft, years: [...draft.years, { year: "", gross_amount: "" }] })}>+ Add a year</button>
          </div>
          {saveMut.isError && <p className="text-xs text-red-500" role="alert">Couldn't save that plan. Check the fields and try again.</p>}
          <div className="flex gap-2">
            <button className="btn-primary text-sm" disabled={!draft.recurring_item_id || !draft.withholding_pct || saveMut.isPending}
              onClick={() => saveMut.mutate(draft)}>Save plan</button>
            <button className="btn-secondary text-sm" onClick={() => setDraft(null)}>Cancel</button>
          </div>
        </div>
      ) : (
        <button className="btn-secondary text-sm flex items-center gap-1" onClick={() => setDraft({ ...blank })}>
          <Plus size={14} /> Add bonus plan
        </button>
      )}
    </div>
  );
}
```

In `TaxTab.tsx`: `import BonusPlansSection from "./BonusPlansSection";` and render `<BonusPlansSection />` as the last child inside the outer `<div className="card">`.

- [ ] **Step 3: Type check** — `cd frontend && bunx tsc -b --force | grep -c "error TS"` → still 39; `bunx vite build` succeeds.

- [ ] **Step 4: Docs** — in `docs/start-guide.md`, under "Step 6 — View Your Forecast", add:

```markdown
- **Bonuses:** add a yearly income item on the Recurring page for each bonus
  (frequency Yearly, its pay date), then in **Settings → Tax → Salary &
  bonuses** set your base salary and expected raise and add a plan for each:
  target %, whether it's based on last year's salary or one from a few years
  back, the % withheld, and any fixed amounts for ramp years. The forecast
  adds each year's net on the pay date, and the gross counts toward the
  Social Security wage base.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/settings/BonusPlansSection.tsx frontend/src/pages/settings/TaxTab.tsx frontend/src/api/index.ts docs/start-guide.md
git commit -m "feat(bonus): Salary & bonuses settings section

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the tasks (controller, not an implementer)

- Final whole-branch review, then verify Settings → Tax and the Forecast page with Interceptor.
- Entering the user's real salary/plans is a live-data write: ask the user first, back up the DB, enter through the UI or API, then compare the 2027 forecast against the figures the user confirmed in chat.
- Ask before pushing.
