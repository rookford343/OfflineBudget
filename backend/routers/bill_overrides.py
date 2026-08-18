"""Known statement amounts for individual upcoming bills.

A RecurringItem carries one typical amount, which is right for planning and
wrong the moment the real bill lands: Duke Electric is modelled at $180.00/mo
while the statement due 2026-09-08 is $224.31. Editing the item would rewrite
every future month to a September-only number and lose the estimate the
forecast still needs for October. These records pin the real amount to a
single due date and leave the model alone.
"""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/bill-overrides", tags=["bill-overrides"])


def _to_out(o: models.BillAmountOverride) -> schemas.BillAmountOverrideOut:
    """Carries the projected amount alongside the actual so a caller can show
    the variance without a second round trip -- comparing the two is the
    entire point of the feature."""
    return schemas.BillAmountOverrideOut(
        id=o.id,
        recurring_item_id=o.recurring_item_id,
        recurring_item_name=o.recurring_item.name if o.recurring_item else "",
        due_date=o.due_date,
        actual_amount=o.actual_amount,
        projected_amount=o.recurring_item.amount if o.recurring_item else 0,
        notes=o.notes,
    )


@router.get("", response_model=list[schemas.BillAmountOverrideOut])
def list_overrides(
    upcoming_only: bool = True,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.BillAmountOverride).options(
        joinedload(models.BillAmountOverride.recurring_item)
    ).filter(models.BillAmountOverride.user_id == user.id)
    if upcoming_only:
        # A due date in the past is history: the real transaction has landed
        # and the forecast no longer projects that day at all.
        q = q.filter(models.BillAmountOverride.due_date >= date.today())
    return [_to_out(o) for o in q.order_by(models.BillAmountOverride.due_date).all()]


@router.post("", response_model=schemas.BillAmountOverrideOut, status_code=status.HTTP_201_CREATED)
def upsert_override(
    body: schemas.BillAmountOverrideCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Set the known amount for one occurrence.

    Upserts rather than 409s on a repeat: a bill can be restated before it is
    paid, and making the caller delete-then-recreate to correct a typo would
    be ceremony with no benefit.
    """
    item = db.query(models.RecurringItem).filter(
        models.RecurringItem.id == body.recurring_item_id,
        models.RecurringItem.user_id == user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Recurring item not found")

    existing = db.query(models.BillAmountOverride).filter(
        models.BillAmountOverride.user_id == user.id,
        models.BillAmountOverride.recurring_item_id == body.recurring_item_id,
        models.BillAmountOverride.due_date == body.due_date,
    ).first()
    if existing:
        existing.actual_amount = body.actual_amount
        existing.notes = body.notes
        db.commit()
        db.refresh(existing)
        return _to_out(existing)

    override = models.BillAmountOverride(
        user_id=user.id,
        recurring_item_id=body.recurring_item_id,
        due_date=body.due_date,
        actual_amount=body.actual_amount,
        notes=body.notes,
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    return _to_out(override)


@router.delete("/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_override(
    override_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Drop back to the modelled amount for that date."""
    override = db.query(models.BillAmountOverride).filter(
        models.BillAmountOverride.id == override_id,
        models.BillAmountOverride.user_id == user.id,
    ).first()
    if not override:
        raise HTTPException(status_code=404, detail="Override not found")
    db.delete(override)
    db.commit()
