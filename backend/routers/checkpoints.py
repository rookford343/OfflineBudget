from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/checkpoints", tags=["checkpoints"])


@router.get("", response_model=list[schemas.QuarterlyCheckpointOut])
def list_checkpoints(
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user.id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return db.query(models.QuarterlyCheckpoint).filter(
        models.QuarterlyCheckpoint.user_id == user.id,
        models.QuarterlyCheckpoint.account_id == account_id,
    ).order_by(models.QuarterlyCheckpoint.year, models.QuarterlyCheckpoint.quarter).all()


@router.put("/{year}/{quarter}", response_model=schemas.QuarterlyCheckpointOut)
def upsert_checkpoint(
    year: int,
    quarter: int,
    body: schemas.QuarterlyCheckpointUpsert,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if quarter not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="Quarter must be 1–4")
    account = db.query(models.Account).filter(
        models.Account.id == body.account_id,
        models.Account.user_id == user.id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    existing = db.query(models.QuarterlyCheckpoint).filter(
        models.QuarterlyCheckpoint.user_id == user.id,
        models.QuarterlyCheckpoint.account_id == body.account_id,
        models.QuarterlyCheckpoint.year == year,
        models.QuarterlyCheckpoint.quarter == quarter,
    ).first()

    if existing:
        existing.actual_balance = body.actual_balance
    else:
        existing = models.QuarterlyCheckpoint(
            user_id=user.id,
            account_id=body.account_id,
            year=year,
            quarter=quarter,
            actual_balance=body.actual_balance,
        )
        db.add(existing)

    db.commit()
    db.refresh(existing)
    return existing
