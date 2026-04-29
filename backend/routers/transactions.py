from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[schemas.TransactionOut])
def list_transactions(
    account_id: int | None = None,
    category_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.Transaction).filter(models.Transaction.user_id == user.id)
    if account_id:
        q = q.filter(models.Transaction.account_id == account_id)
    if category_id:
        q = q.filter(models.Transaction.category_id == category_id)
    if start:
        q = q.filter(models.Transaction.date >= start)
    if end:
        q = q.filter(models.Transaction.date <= end)
    return q.order_by(models.Transaction.date.desc()).all()


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
