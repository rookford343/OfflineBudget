import logging
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
from backend.services import scenario_service
from backend.services.forecast_engine import build_forecast, build_quarters, find_balance_risk, find_transfer_signal, suggest_transfer
from backend.services.reconciliation_helper import compute_reconciliation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forecast", tags=["forecast"])


def _today() -> date:
    # Indirection so tests can pin "today" without patching the date class.
    return date.today()


@router.get("", response_model=list[schemas.ForecastEntry])
def get_forecast(
    account_id: int,
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return build_forecast(db, user.id, account_id, start, end)


@router.get("/baseline", response_model=schemas.ForecastBaselineOut)
def get_forecast_baseline(
    account_id: int,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """The month's forecast as saved at the start of the month (see
    services/forecast_baseline.py). Only the current month can be created,
    and only in its first week; anything else is read-only."""
    from backend.services.forecast_baseline import ensure_month_baseline, get_month_baseline, baseline_points
    if not db.query(models.Account).filter(
        models.Account.id == account_id, models.Account.user_id == user.id,
    ).first():
        raise HTTPException(status_code=404, detail="Account not found")

    today = _today()
    if (year, month) == (today.year, today.month):
        try:
            row = ensure_month_baseline(db, user.id, account_id, today)
        except Exception:
            db.rollback()
            logger.exception("Could not save forecast baseline for account %s", account_id)
            raise HTTPException(status_code=503, detail="Forecast baseline unavailable")
    else:
        row = get_month_baseline(db, user.id, account_id, year, month)

    points = baseline_points(row)
    if row is None or points is None or row.taken_on is None:
        raise HTTPException(status_code=404, detail="No forecast baseline for this month")
    return schemas.ForecastBaselineOut(year=row.year, month=row.month, taken_on=row.taken_on, points=points)


@router.get("/risk", response_model=schemas.ForecastRisk)
def get_forecast_risk(
    account_id: int,
    days: int = Query(default=90, ge=1, le=730),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user.id,
    ).first()
    threshold = account.low_balance_threshold if account and account.low_balance_threshold is not None else Decimal("0")
    start = date.today()
    end = start + timedelta(days=days)
    entries = build_forecast(db, user.id, account_id, start, end)
    risk = find_balance_risk(entries, threshold)
    transfer = find_transfer_signal(entries)
    suggestion = suggest_transfer(db, user, account_id, risk, entries)
    active_rule = db.query(models.BufferTransferRule).filter(
        models.BufferTransferRule.user_id == user.id,
        models.BufferTransferRule.to_account_id == account_id,
        models.BufferTransferRule.is_active == True,
    ).first()
    return schemas.ForecastRisk(
        at_risk=risk["at_risk"],
        date=risk["date"],
        amount=risk["amount"],
        threshold=risk["threshold"],
        transfer_triggered=transfer["triggered"],
        transfer_date=transfer["date"],
        transfer_amount=transfer["amount"],
        transfer_from=transfer["from_name"],
        action_threshold=active_rule.action_threshold if active_rule else None,
        suggested_transfer_amount=suggestion["amount"],
        suggested_transfer_date=suggestion["date"],
        suggested_transfer_from_account_id=suggestion["from_account_id"],
        suggested_transfer_already_planned=suggestion["already_planned"],
    )


def _attach_quarter_checkpoints(
    quarters: list[schemas.QuarterSummary],
    db: Session,
    user_id: int,
    account_id: int,
) -> list[schemas.QuarterSummary]:
    """Look up a ForecastDayCheckpoint near each quarter's last day and attach it."""
    if not quarters:
        return quarters
    min_year = min(q.year for q in quarters)
    max_year = max(q.year for q in quarters)
    start_range = date(min_year, 1, 1)
    end_range = date(max_year, 12, 31)

    checkpoints = db.query(models.ForecastDayCheckpoint).filter(
        models.ForecastDayCheckpoint.user_id == user_id,
        models.ForecastDayCheckpoint.account_id == account_id,
        models.ForecastDayCheckpoint.date >= start_range,
        models.ForecastDayCheckpoint.date <= end_range,
    ).all()
    cp_by_date: dict[date, Decimal] = {cp.date: cp.actual_balance for cp in checkpoints}

    updated: list[schemas.QuarterSummary] = []
    for q in quarters:
        end_month = q.quarter * 3
        end_day = monthrange(q.year, end_month)[1]
        q_end = date(q.year, end_month, end_day)
        # Find nearest checkpoint on or within 7 days before quarter end
        candidates = [
            (abs((d - q_end).days), v)
            for d, v in cp_by_date.items()
            if q_end - timedelta(days=7) <= d <= q_end
        ]
        checkpoint_val = min(candidates, key=lambda x: x[0])[1] if candidates else None
        updated.append(q.model_copy(update={"quarter_end_checkpoint": checkpoint_val}))
    return updated


@router.get("/quarters", response_model=list[schemas.QuarterSummary])
def get_quarters(
    account_id: int,
    year: int = Query(default=date.today().year),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    quarters = build_quarters(db, user.id, account_id, year)
    return _attach_quarter_checkpoints(quarters, db, user.id, account_id)


@router.get("/multi-year", response_model=list[schemas.QuarterSummary])
def get_multi_year(
    account_id: int,
    start_year: int = Query(default=date.today().year),
    years: int = Query(default=3, ge=1, le=5),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # One walk across the whole span, sliced per year. Building each year
    # independently re-derived its opening balance and produced a step between
    # December and January; a shared walk cannot disagree with itself.
    span = build_forecast(
        db, user.id, account_id,
        date(start_year, 1, 1), date(start_year + years - 1, 12, 31),
    )
    all_quarters: list[schemas.QuarterSummary] = []
    for y in range(start_year, start_year + years):
        all_quarters.extend(build_quarters(db, user.id, account_id, y, precomputed_days=span))
    return _attach_quarter_checkpoints(all_quarters, db, user.id, account_id)


@router.get("/monthly-summary", response_model=schemas.MonthlyForecastSummary)
def get_monthly_summary(
    account_id: int,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    end_day = monthrange(year, month)[1]
    end = date(year, month, end_day)

    # Always recompute from Jan 1 so monthly balances chain correctly.
    # Snapshots were removed to avoid serving stale forecasts after engine or data changes.
    year_start = date(year, 1, 1)
    entries = build_forecast(db, user.id, account_id, year_start, end)
    month_entries = [e for e in entries if e.date.year == year and e.date.month == month]
    if month_entries:
        forecasted_open = month_entries[0].projected_balance - sum(
            t.amount for t in month_entries[0].transactions
        )
        forecasted_close = month_entries[-1].projected_balance
    else:
        forecasted_open = Decimal("0")
        forecasted_close = Decimal("0")

    # Actual close: nearest ForecastDayCheckpoint within 7 days before month-end
    actual_close: Decimal | None = None
    checkpoints = db.query(models.ForecastDayCheckpoint).filter(
        models.ForecastDayCheckpoint.user_id == user.id,
        models.ForecastDayCheckpoint.account_id == account_id,
        models.ForecastDayCheckpoint.date >= end - timedelta(days=7),
        models.ForecastDayCheckpoint.date <= end,
    ).all()
    if checkpoints:
        closest = min(checkpoints, key=lambda c: abs((c.date - end).days))
        actual_close = closest.actual_balance

    delta = (actual_close - forecasted_close) if actual_close is not None else None

    reconcile = compute_reconciliation(db, user.id, account_id, year, month)

    return schemas.MonthlyForecastSummary(
        account_id=account_id,
        year=year,
        month=month,
        forecasted_open=forecasted_open,
        forecasted_close=forecasted_close,
        snapshot_taken_at=None,
        actual_close=actual_close,
        delta=delta,
        reconcile=reconcile,
    )


class ScenarioForecastRequest(BaseModel):
    account_id: int
    year: int
    # Kept for the existing Forecast page, which assembles overrides itself
    # from the scenario it has already loaded (Forecast.tsx:343-354).
    overrides: list[dict[str, Any]] = []
    # Preferred: let the server resolve the scenario, which is the only side
    # that can build a proposal's transient objects, and the only side that
    # knows a committed scenario resolves to nothing.
    scenario_id: int | None = None


@router.post("/quarters-scenario", response_model=list[schemas.QuarterSummary])
def get_quarters_with_scenario(
    body: ScenarioForecastRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    overrides = body.overrides
    proposal = None
    if body.scenario_id is not None:
        resolved = scenario_service.resolve_scenario(db, user.id, body.scenario_id)
        if resolved is None:
            raise HTTPException(404, "Scenario not found")
        resolved_overrides, proposal = resolved
        # A scenario_id supersedes a client-supplied override list: mixing the
        # two would apply the same delta twice when the client sent both.
        overrides = resolved_overrides
    return build_quarters(
        db, user.id, body.account_id, body.year,
        overrides=overrides, proposal=proposal,
    )
