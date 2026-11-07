"""Combined savings balance per day, for the Forecast chart's savings bars.

The Forecast page used to add each savings account's projected balance up
itself. This is the one recipe: every active savings-type account's forecast
(the same quarter walks the page reads for any single account), summed by date.
Money market and other non-savings types are left out on purpose.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models
from backend.services.forecast_engine import build_forecast, build_quarters

ZERO = Decimal("0")


def combined_savings_balances(
    db: Session, user_id: int, year: int, years: int,
) -> list[tuple[date, Decimal]]:
    """(date, combined projected balance) for each day in the span, oldest first."""
    accounts = db.query(models.Account).filter(
        models.Account.user_id == user_id,
        models.Account.type == models.AccountType.savings,
        models.Account.is_active == True,  # noqa: E712
    ).all()
    by_date: dict[date, Decimal] = {}
    for acct in accounts:
        if years == 1:
            quarters = build_quarters(db, user_id, acct.id, year)
        else:
            span = build_forecast(
                db, user_id, acct.id, date(year, 1, 1), date(year + years - 1, 12, 31),
            )
            quarters = [
                q for y in range(year, year + years)
                for q in build_quarters(db, user_id, acct.id, y, precomputed_days=span)
            ]
        for q in quarters:
            for d in q.days:
                by_date[d.date] = by_date.get(d.date, ZERO) + d.projected_balance
    return sorted(by_date.items())
