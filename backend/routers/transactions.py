from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/raw/{external_id}", response_model=schemas.RawSnapshotOut)
def get_raw_snapshot(
    external_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Debug capture only -- see BankSyncRawSnapshot. 404 whenever
    debug_capture_raw_bank_data was off at sync time (the normal case), not
    just when the transaction itself doesn't exist; the frontend treats both
    identically (no raw data to show)."""
    snap = db.query(models.BankSyncRawSnapshot).filter(
        models.BankSyncRawSnapshot.user_id == user.id,
        models.BankSyncRawSnapshot.external_id == external_id,
    ).first()
    if not snap:
        raise HTTPException(status_code=404, detail="No raw snapshot captured for this transaction")
    return snap


@router.get("", response_model=list[schemas.TransactionOut])
def list_transactions(
    account_id: int | None = None,
    category_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    q: str | None = Query(None, description="Search description (case-insensitive)"),
    amount_min: Decimal | None = Query(None, description="Minimum amount (inclusive)"),
    amount_max: Decimal | None = Query(None, description="Maximum amount (inclusive)"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = db.query(models.Transaction).filter(models.Transaction.user_id == user.id)
    if account_id:
        query = query.filter(models.Transaction.account_id == account_id)
    if category_id:
        query = query.filter(models.Transaction.category_id == category_id)
    if start:
        query = query.filter(models.Transaction.date >= start)
    if end:
        query = query.filter(models.Transaction.date <= end)
    if q:
        query = query.filter(func.lower(models.Transaction.description).like(f"%{q.lower()}%"))
    if amount_min is not None:
        query = query.filter(models.Transaction.amount >= amount_min)
    if amount_max is not None:
        query = query.filter(models.Transaction.amount <= amount_max)
    return query.order_by(models.Transaction.date.desc()).all()


@router.post("", response_model=schemas.TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    body: schemas.TransactionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _assert_account_owned(db, user.id, body.account_id)
    txn = models.Transaction(user_id=user.id, is_actual=True, **body.model_dump())
    db.add(txn)
    # Update account balance
    account = db.get(models.Account, body.account_id)
    account.current_balance += body.amount
    db.commit()
    db.refresh(txn)
    return txn


@router.get("/{txn_id}", response_model=schemas.TransactionOut)
def get_transaction(
    txn_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return _get_or_404(db, user.id, txn_id)


@router.patch("/{txn_id}", response_model=schemas.TransactionOut)
def update_transaction(
    txn_id: int,
    body: schemas.TransactionUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    txn = _get_or_404(db, user.id, txn_id)
    if body.amount is not None:
        diff = body.amount - txn.amount
        account = db.get(models.Account, txn.account_id)
        account.current_balance += diff
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(txn, field, value)
    db.commit()
    db.refresh(txn)
    return txn


@router.delete("/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    txn_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    txn = _get_or_404(db, user.id, txn_id)
    account = db.get(models.Account, txn.account_id)
    account.current_balance -= txn.amount
    db.delete(txn)
    db.commit()


def _get_or_404(db: Session, user_id: int, txn_id: int) -> models.Transaction:
    txn = db.query(models.Transaction).filter(
        models.Transaction.id == txn_id,
        models.Transaction.user_id == user_id,
    ).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


def _assert_account_owned(db: Session, user_id: int, account_id: int) -> None:
    if not db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user_id,
    ).first():
        raise HTTPException(status_code=404, detail="Account not found")
