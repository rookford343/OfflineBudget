"""Data management endpoints — clear selected data for a fresh start."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from backend import models
from backend.database import get_db
from backend.routers.auth import get_requester

router = APIRouter(prefix="/data", tags=["data"])


@router.delete("/transactions", status_code=status.HTTP_204_NO_CONTENT)
def clear_transactions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_requester),
):
    """Delete all checking transactions and reset account balances to zero."""
    db.query(models.Transaction).filter(
        models.Transaction.user_id == current_user.id
    ).delete(synchronize_session=False)

    db.query(models.Account).filter(
        models.Account.user_id == current_user.id
    ).update({"current_balance": 0}, synchronize_session=False)

    db.commit()


@router.delete("/cc-transactions", status_code=status.HTTP_204_NO_CONTENT)
def clear_cc_transactions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_requester),
):
    """Delete all credit card transactions and reset card balances to zero."""
    db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == current_user.id
    ).delete(synchronize_session=False)

    db.query(models.CreditCard).filter(
        models.CreditCard.user_id == current_user.id
    ).update({"current_balance": 0}, synchronize_session=False)

    db.commit()
