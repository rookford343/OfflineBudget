from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.schemas import ReconcileResponse
from backend.services.reconciliation_helper import compute_reconciliation

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.get("", response_model=ReconcileResponse)
def reconcile(
    account_id: int,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return compute_reconciliation(db, user.id, account_id, year, month)
