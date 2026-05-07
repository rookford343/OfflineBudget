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


@router.get("/multi-year", response_model=list[schemas.QuarterSummary])
def get_multi_year(
    account_id: int,
    start_year: int = Query(default=date.today().year),
    years: int = Query(default=3, ge=1, le=5),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    all_quarters = []
    for y in range(start_year, start_year + years):
        all_quarters.extend(build_quarters(db, user.id, account_id, y))
    return all_quarters


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
    return build_quarters(db, user.id, body.account_id, body.year, overrides=body.overrides)
