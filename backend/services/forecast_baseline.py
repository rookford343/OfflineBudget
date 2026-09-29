"""The forecast as it stood at the start of the month, saved once.

The Dashboard's Balance Flow card measures how far the month is drifting from
plan. A forecast recomputed on demand would move every time a recurring item
is edited and quietly absorb the drift, so the day-by-day projection is saved
the first time it's asked for in a month and never rewritten.
"""
from __future__ import annotations
import calendar
import json
import logging
from datetime import date
from sqlalchemy.orm import Session
from backend import models
from backend.services.forecast_engine import build_forecast

logger = logging.getLogger(__name__)

# Only save in the first week. A forecast saved late is mostly actuals and
# would report almost no deviation, which misleads; a week still covers a Mac
# that slept through the 1st.
BASELINE_SAVE_WINDOW_DAYS = 7


def get_month_baseline(db: Session, user_id: int, account_id: int, year: int, month: int):
    return db.query(models.MonthlyForecastSnapshot).filter(
        models.MonthlyForecastSnapshot.user_id == user_id,
        models.MonthlyForecastSnapshot.account_id == account_id,
        models.MonthlyForecastSnapshot.year == year,
        models.MonthlyForecastSnapshot.month == month,
    ).first()


def ensure_month_baseline(db: Session, user_id: int, account_id: int, as_of: date):
    existing = get_month_baseline(db, user_id, account_id, as_of.year, as_of.month)
    if existing is not None:
        return existing
    if as_of.day > BASELINE_SAVE_WINDOW_DAYS:
        return None

    start = date(as_of.year, as_of.month, 1)
    end = date(as_of.year, as_of.month, calendar.monthrange(as_of.year, as_of.month)[1])
    entries = build_forecast(db, user_id, account_id, start, end)
    points = [
        {"date": e.date.isoformat(), "projected_balance": f"{e.projected_balance:.2f}"}
        for e in entries
    ]
    row = models.MonthlyForecastSnapshot(
        user_id=user_id, account_id=account_id, year=as_of.year, month=as_of.month,
        forecasted_open=entries[0].projected_balance if entries else 0,
        forecasted_close=entries[-1].projected_balance if entries else 0,
        taken_on=as_of,
        daily_points=json.dumps(points),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def baseline_points(row) -> list[dict] | None:
    if row is None or not row.daily_points:
        return None
    try:
        points = json.loads(row.daily_points)
    except (TypeError, ValueError):
        return None
    return points if isinstance(points, list) and points else None


def ensure_baselines_for_all(db: Session, as_of: date) -> int:
    """Every active checking account, one at a time; a failure on one is
    logged and never stops the others (or the scheduler sweep calling this)."""
    accounts = db.query(models.Account).filter(
        models.Account.type == models.AccountType.checking,
        models.Account.is_active == True,
    ).all()
    saved = 0
    for acct in accounts:
        try:
            if ensure_month_baseline(db, acct.user_id, acct.id, as_of) is not None:
                saved += 1
        except Exception:
            db.rollback()
            logger.exception("Could not save forecast baseline for account %s", acct.id)
    return saved
