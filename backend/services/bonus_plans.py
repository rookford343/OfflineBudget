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

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models

CENT = Decimal("0.01")

try:
    # The import matcher's own amount-window constant (import_service.py) --
    # a bonus posting within this many days of its payout date must still be
    # checked against THIS year's net, not next year's. Falls back to the
    # matcher's current value in case this module ever can't be imported
    # (e.g. a stripped-down context that doesn't load the routers package).
    from backend.services.import_service import _MATCH_WINDOW_DAYS
except ImportError:  # pragma: no cover - defensive fallback, see above
    _MATCH_WINDOW_DAYS = 7


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


def is_bonus_shaped(item: models.RecurringItem) -> bool:
    """True when a RecurringItem is still shaped the way a BonusPlan can be
    attached to: a yearly income item. A BonusPlan can only be attached at
    creation time (routers/bonus_plans.py's _own_item), but nothing stops
    the user from editing that same item into a different type or
    frequency afterward on the Recurring page. Both the forecast engine's
    bonus_plans filter and refresh_item_amounts call this so the two can't
    drift on what counts as a live bonus item."""
    return (
        item.type == models.RecurringType.income
        and item.frequency == models.RecurringFrequency.yearly
    )


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
    """Keep each bonus item's amount equal to its current target payout's
    net, so the Recurring page, budget totals and the matcher's amount check
    see a real figure. Leaves the amount alone when the gross is unknown.

    Bank sync imports once a day at 07:00, so a bonus that posts after 07:00
    on payout day -- or a few days late -- must still be checked against
    THIS year's net, not next year's: in a ramp year the two can differ
    enough (e.g. a 0.71 ratio) to fall outside the import matcher's own
    +/-15% amount window and never link, dropping the deposit out of
    checkpoint-mode SS reconciliation and double-projecting it in any
    forecast window that starts before the payout. upcoming_payouts() itself
    rolls to next year the instant `today > payout_date`; this delays that
    roll by _MATCH_WINDOW_DAYS by asking it from a point that many days
    earlier, which only affects which YEAR it starts counting from, not the
    gross/net it returns for that year.

    A no-op -- no commit -- when the user has no bonus plans, so callers that
    run across every user regardless of whether they use this feature (the
    scheduler sweep, PATCH /auth/me) don't open a write transaction for
    accounts with nothing to refresh.

    Skips any plan whose recurring_item is no longer bonus-shaped (see
    is_bonus_shaped) -- the forecast engine already ignores such an item's
    plan entirely, so overwriting its amount here would fight whatever the
    user just edited it to (e.g. a monthly item) on every save and every
    scheduler sweep."""
    plans = plans_by_item(db, user.id)
    if not plans:
        return
    effective_today = today - timedelta(days=_MATCH_WINDOW_DAYS)
    for plan in plans.values():
        if not is_bonus_shaped(plan.recurring_item):
            continue
        nxt = upcoming_payouts(plan, user, effective_today, count=1)[0]
        if nxt["net"] is not None and nxt["net"] > 0:
            plan.recurring_item.amount = nxt["net"]
    db.commit()
