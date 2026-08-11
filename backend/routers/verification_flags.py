import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/verification-flags", tags=["verification-flags"])


def _get_owned(db: Session, user: models.User, flag_id: int) -> models.VerificationFlag:
    flag = db.query(models.VerificationFlag).filter(
        models.VerificationFlag.id == flag_id,
        models.VerificationFlag.user_id == user.id,
    ).first()
    if not flag:
        raise HTTPException(status_code=404, detail="Verification flag not found")
    return flag


@router.get("", response_model=list[schemas.VerificationFlagOut])
def list_verification_flags(
    feature: models.VerificationFeature | None = None,
    status: models.VerificationFlagStatus | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = db.query(models.VerificationFlag).filter(models.VerificationFlag.user_id == user.id)
    if feature is not None:
        query = query.filter(models.VerificationFlag.feature == feature)
    if status is not None:
        query = query.filter(models.VerificationFlag.status == status)
    return query.order_by(models.VerificationFlag.created_at.desc()).all()


@router.post("", response_model=schemas.VerificationFlagOut, status_code=status.HTTP_201_CREATED)
def create_verification_flag(
    body: schemas.VerificationFlagCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    flag = models.VerificationFlag(
        user_id=user.id,
        feature=body.feature,
        reference_type=body.reference_type,
        reference_id=body.reference_id,
        observed_json=json.dumps(body.observed),
        expected_value=body.expected_value,
        note=body.note,
    )
    db.add(flag)
    db.commit()
    db.refresh(flag)
    return flag


@router.patch("/{flag_id}", response_model=schemas.VerificationFlagOut)
def update_verification_flag_status(
    flag_id: int,
    body: schemas.VerificationFlagResolve,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    flag = _get_owned(db, user, flag_id)
    flag.status = body.status
    flag.resolved_at = datetime.utcnow() if body.status == models.VerificationFlagStatus.resolved else None
    db.commit()
    db.refresh(flag)
    return flag
