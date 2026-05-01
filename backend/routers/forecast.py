from calendar import monthrange
from datetime import date
from typing import Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
from backend.services.forecast_engine import build_forecast, build_quarters

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("", response_model=list[schemas.ForecastEntry])
def get_forecast(
    account_id: int,
    start: date = Query(...),
    end: date = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return build_forecast(db, user.id, account_id, start, end)


@router.get("/quarters", response_model=list[schemas.QuarterSummary])
def get_quarters(
    account_id: int,
    year: int = Query(default=date.today().year),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return build_quarters(db, user.id, account_id, year)


class ScenarioForecastRequest(BaseModel):
    account_id: int
    year: int
    overrides: list[dict[str, Any]] = []


@router.post("/quarters-scenario", response_model=list[schemas.QuarterSummary])
def get_quarters_with_scenario(
    body: ScenarioForecastRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    quarters = []
    for q in range(1, 5):
        month_start = (q - 1) * 3 + 1
        start = date(body.year, month_start, 1)
        end_month = month_start + 2
        end = date(body.year, end_month, monthrange(body.year, end_month)[1])
        days = build_forecast(db, user.id, body.account_id, start, end, overrides=body.overrides)
        if not days:
            continue
        open_balance = days[0].projected_balance - sum(t.amount for t in days[0].transactions)
        close_balance = days[-1].projected_balance
        total_income = sum(t.amount for day in days for t in day.transactions if t.amount > 0)
        total_expenses = sum(-t.amount for day in days for t in day.transactions if t.amount < 0)
        quarters.append(schemas.QuarterSummary(
            quarter=q, year=body.year,
            open_balance=open_balance, close_balance=close_balance,
            total_income=total_income, total_expenses=total_expenses,
            net=total_income - total_expenses, days=days,
        ))
    return quarters
