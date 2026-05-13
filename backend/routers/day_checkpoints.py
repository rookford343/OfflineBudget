"""Day-level forecast balance checkpoints."""
from __future__ import annotations
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.database import SessionLocal
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/forecast/day-checkpoints", tags=["forecast"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=list[schemas.ForecastDayCheckpointOut])
def list_day_checkpoints(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == current_user.id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return db.query(models.ForecastDayCheckpoint).filter(
        models.ForecastDayCheckpoint.account_id == account_id,
        models.ForecastDayCheckpoint.user_id == current_user.id,
    ).order_by(models.ForecastDayCheckpoint.date).all()


@router.put("/{checkpoint_date}", response_model=schemas.ForecastDayCheckpointOut)
def upsert_day_checkpoint(
    checkpoint_date: date,
    body: schemas.ForecastDayCheckpointUpsert,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    account = db.query(models.Account).filter(
        models.Account.id == body.account_id,
        models.Account.user_id == current_user.id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    existing = db.query(models.ForecastDayCheckpoint).filter(
        models.ForecastDayCheckpoint.user_id == current_user.id,
        models.ForecastDayCheckpoint.account_id == body.account_id,
        models.ForecastDayCheckpoint.date == checkpoint_date,
    ).first()
    if existing:
        existing.actual_balance = body.actual_balance
        existing.note = body.note
    else:
        existing = models.ForecastDayCheckpoint(
            user_id=current_user.id,
            account_id=body.account_id,
            date=checkpoint_date,
            actual_balance=body.actual_balance,
            note=body.note,
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/{checkpoint_date}", status_code=204)
def delete_day_checkpoint(
    checkpoint_date: date,
    account_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    existing = db.query(models.ForecastDayCheckpoint).filter(
        models.ForecastDayCheckpoint.user_id == current_user.id,
        models.ForecastDayCheckpoint.account_id == account_id,
        models.ForecastDayCheckpoint.date == checkpoint_date,
    ).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    db.delete(existing)
    db.commit()
