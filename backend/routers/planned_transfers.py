from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/planned-transfers", tags=["planned-transfers"])


def _get_owned(db: Session, user: models.User, transfer_id: int) -> models.PlannedTransfer:
    transfer = db.query(models.PlannedTransfer).filter(
        models.PlannedTransfer.id == transfer_id,
        models.PlannedTransfer.user_id == user.id,
    ).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="Planned transfer not found")
    return transfer


def _assert_account_owned(db: Session, user_id: int, account_id: int) -> None:
    if not db.query(models.Account).filter(
        models.Account.id == account_id, models.Account.user_id == user_id,
    ).first():
        raise HTTPException(status_code=404, detail="Account not found")


@router.get("", response_model=list[schemas.PlannedTransferOut])
def list_planned_transfers(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.PlannedTransfer)
        .filter(models.PlannedTransfer.user_id == user.id)
        .order_by(models.PlannedTransfer.target_date)
        .all()
    )


@router.post("", response_model=schemas.PlannedTransferOut, status_code=status.HTTP_201_CREATED)
def create_planned_transfer(
    body: schemas.PlannedTransferCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _assert_account_owned(db, user.id, body.to_account_id)
    if body.from_account_id:
        _assert_account_owned(db, user.id, body.from_account_id)
    transfer = models.PlannedTransfer(
        user_id=user.id,
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        amount=body.amount,
        target_date=body.target_date,
        notes=body.notes,
    )
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transfer


@router.patch("/{transfer_id}", response_model=schemas.PlannedTransferOut)
def update_planned_transfer(
    transfer_id: int,
    body: schemas.PlannedTransferUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    transfer = _get_owned(db, user, transfer_id)
    data = body.model_dump(exclude_unset=True)
    if "to_account_id" in data and data["to_account_id"] is not None:
        _assert_account_owned(db, user.id, data["to_account_id"])
    if "from_account_id" in data and data["from_account_id"] is not None:
        _assert_account_owned(db, user.id, data["from_account_id"])
    for field, value in data.items():
        setattr(transfer, field, value)
    db.commit()
    db.refresh(transfer)
    return transfer


@router.post("/{transfer_id}/mark-scheduled", response_model=schemas.PlannedTransferOut)
def mark_scheduled(
    transfer_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    transfer = _get_owned(db, user, transfer_id)
    if transfer.status != models.PlannedTransferStatus.pending:
        raise HTTPException(status_code=400, detail="Only a pending transfer can be marked scheduled")
    transfer.status = models.PlannedTransferStatus.scheduled
    db.commit()
    db.refresh(transfer)
    return transfer


@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_planned_transfer(
    transfer_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    transfer = _get_owned(db, user, transfer_id)
    db.delete(transfer)
    db.commit()
