from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/recurring", tags=["recurring"])


@router.get("", response_model=list[schemas.RecurringOut])
def list_recurring(
    active_only: bool = True,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.RecurringItem).filter(models.RecurringItem.user_id == user.id)
    if active_only:
        q = q.filter(models.RecurringItem.is_active == True)
    return q.order_by(models.RecurringItem.day_of_month).all()


@router.post("", response_model=schemas.RecurringOut, status_code=status.HTTP_201_CREATED)
def create_recurring(
    body: schemas.RecurringCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _assert_account_owned(db, user.id, body.account_id)
    item = models.RecurringItem(user_id=user.id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=schemas.RecurringOut)
def get_recurring(
    item_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return _get_or_404(db, user.id, item_id)


@router.patch("/{item_id}", response_model=schemas.RecurringOut)
def update_recurring(
    item_id: int,
    body: schemas.RecurringUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    item = _get_or_404(db, user.id, item_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring(
    item_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    item = _get_or_404(db, user.id, item_id)
    item.is_active = False
    db.commit()


def _get_or_404(db: Session, user_id: int, item_id: int) -> models.RecurringItem:
    item = db.query(models.RecurringItem).filter(
        models.RecurringItem.id == item_id,
        models.RecurringItem.user_id == user_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Recurring item not found")
    return item


def _assert_account_owned(db: Session, user_id: int, account_id: int) -> None:
    if not db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user_id,
    ).first():
        raise HTTPException(status_code=404, detail="Account not found")
