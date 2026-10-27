from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
from backend.routers._shared import owned_or_404
from backend.services.forecast_engine import pending_snapshot_is_live

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[schemas.AccountOut])
def list_accounts(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return db.query(models.Account).filter(
        models.Account.user_id == user.id,
        models.Account.is_active == True,
    ).all()


@router.post("", response_model=schemas.AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    body: schemas.AccountCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = models.Account(user_id=user.id, **body.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}", response_model=schemas.AccountOut)
def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = _get_or_404(db, user.id, account_id)
    return account


@router.get("/{account_id}/pending-transactions", response_model=list[schemas.AccountPendingTransactionOut])
def list_pending_transactions(
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """What the bank currently lists as pending on this account, newest
    first. Display-only. Empty unless an active Plaid link keeps the
    snapshot fresh -- the same rule the forecast uses before subtracting
    any of it, so the page never shows a row the forecast ignores."""
    account = _get_or_404(db, user.id, account_id)
    if not pending_snapshot_is_live(db, account):
        return []
    return db.query(models.AccountPendingTransaction).filter(
        models.AccountPendingTransaction.user_id == user.id,
        models.AccountPendingTransaction.account_id == account.id,
    ).order_by(models.AccountPendingTransaction.date.desc(), models.AccountPendingTransaction.id).all()


@router.patch("/{account_id}", response_model=schemas.AccountOut)
def update_account(
    account_id: int,
    body: schemas.AccountUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = _get_or_404(db, user.id, account_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = _get_or_404(db, user.id, account_id)
    account.is_active = False
    db.commit()


def _get_or_404(db: Session, user_id: int, account_id: int) -> models.Account:
    return owned_or_404(db, models.Account, account_id, user_id, "Account not found")
