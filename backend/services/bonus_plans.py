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
