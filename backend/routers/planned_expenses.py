from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user
from backend.services.one_off_preview import preview_one_off
from backend.services.planned_auto_settle import apply_settlement

router = APIRouter(prefix="/planned-expenses", tags=["planned-expenses"])


def _require_owned(
    db: Session, user: models.User, *,
    account_id: int | None = None, card_id: int | None = None,
    funding_account_id: int | None = None,
) -> None:
    """404 "Not found" for any non-null id the caller doesn't own.

    One message for every case, so a caller can't tell another user's row
    from a missing one."""
    for aid in (account_id, funding_account_id):
        if aid is not None and not db.query(models.Account.id).filter(
            models.Account.id == aid, models.Account.user_id == user.id,
        ).first():
            raise HTTPException(status_code=404, detail="Not found")
    if card_id is not None and not db.query(models.CreditCard.id).filter(
        models.CreditCard.id == card_id, models.CreditCard.user_id == user.id,
    ).first():
        raise HTTPException(status_code=404, detail="Not found")


@router.get("", response_model=list[schemas.PlannedExpenseOut])
def list_planned_expenses(
    include_settled: bool = False,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Unsettled one-offs by default.

    A settled row is history, not a plan, so it drops out of the panel rather
    than accumulating -- the April bonus was still listed in August. Pass
    include_settled=true to see the archive with estimate vs actual.
    """
    q = db.query(models.PlannedExpense).filter(models.PlannedExpense.user_id == user.id)
    if not include_settled:
        q = q.filter(models.PlannedExpense.settled_on.is_(None))
    return q.order_by(models.PlannedExpense.expected_date).all()


@router.post("/preview", response_model=schemas.OneOffPreviewOut)
def preview_planned_expense(
    body: schemas.PlannedExpenseCreate,
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Safety Margin before and after a draft one-off. Writes nothing."""
    _require_owned(
        db, user, account_id=account_id, card_id=body.card_id,
        funding_account_id=body.funding_account_id,
    )
    _require_owned(db, user, account_id=body.account_id)
    return preview_one_off(db, user, account_id, body)


@router.post("", response_model=schemas.PlannedExpenseOut, status_code=status.HTTP_201_CREATED)
def create_planned_expense(
    body: schemas.PlannedExpenseCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _require_owned(
        db, user, account_id=body.account_id, card_id=body.card_id,
        funding_account_id=body.funding_account_id,
    )
    expense = models.PlannedExpense(
        user_id=user.id,
        name=body.name,
        amount=body.amount,
        expected_date=body.expected_date,
        notes=body.notes,
        category_id=body.category_id,
        # account_id was accepted by the schema but silently dropped here, so
        # every planned expense behaved as "applies to all accounts" (the
        # forecast treats a null account_id that way).
        account_id=body.account_id,
        card_id=body.card_id,
        direction=body.direction,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.patch("/{expense_id}", response_model=schemas.PlannedExpenseOut)
def update_planned_expense(
    expense_id: int,
    body: schemas.PlannedExpenseUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    expense = db.query(models.PlannedExpense).filter(
        models.PlannedExpense.id == expense_id,
        models.PlannedExpense.user_id == user.id,
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Planned expense not found")
    changes = body.model_dump(exclude_unset=True)
    _require_owned(
        db, user, account_id=changes.get("account_id"), card_id=changes.get("card_id"),
        funding_account_id=changes.get("funding_account_id"),
    )
    for field, value in changes.items():
        setattr(expense, field, value)
    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_planned_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    expense = db.query(models.PlannedExpense).filter(
        models.PlannedExpense.id == expense_id,
        models.PlannedExpense.user_id == user.id,
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Planned expense not found")
    # An Adventures trip item can link to this one-off via
    # TripItem.planned_expense_id. The FK has no ondelete, so null the link
    # before deleting or SQLite raises an IntegrityError.
    for item in db.query(models.TripItem).filter(
        models.TripItem.planned_expense_id == expense.id,
        models.TripItem.user_id == user.id,
    ).all():
        item.planned_expense_id = None
    db.flush()
    db.delete(expense)
    db.commit()


@router.post("/{expense_id}/settle", response_model=schemas.PlannedExpenseOut)
def settle_planned_expense(
    expense_id: int,
    payload: schemas.PlannedExpenseSettle,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Reconcile a past-dated one-off against what actually happened.

    Deliberately does NOT overwrite `amount`: keeping the estimate beside the
    actual is what makes the next estimate better. Settling a still-future
    row is allowed (a purchase can land early) but it must exist and belong
    to the caller.
    """
    expense = (
        db.query(models.PlannedExpense)
        .filter(
            models.PlannedExpense.id == expense_id,
            models.PlannedExpense.user_id == user.id,
        )
        .first()
    )
    if not expense:
        raise HTTPException(status_code=404, detail="Planned expense not found")

    apply_settlement(expense, payload.settled_on or date.today(), payload.actual_amount)
    db.commit()
    db.refresh(expense)
    return expense


@router.post("/{expense_id}/unsettle", response_model=schemas.PlannedExpenseOut)
def unsettle_planned_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Undo a settlement -- reconciling the wrong row shouldn't need a rebuild."""
    expense = (
        db.query(models.PlannedExpense)
        .filter(
            models.PlannedExpense.id == expense_id,
            models.PlannedExpense.user_id == user.id,
        )
        .first()
    )
    if not expense:
        raise HTTPException(status_code=404, detail="Planned expense not found")
    expense.settled_on = None
    expense.actual_amount = None
    db.commit()
    db.refresh(expense)
    return expense
