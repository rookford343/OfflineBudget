from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/planned-expenses", tags=["planned-expenses"])


@router.get("", response_model=list[schemas.PlannedExpenseOut])
def list_planned_expenses(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.PlannedExpense)
        .filter(models.PlannedExpense.user_id == user.id)
        .order_by(models.PlannedExpense.expected_date)
        .all()
    )


@router.post("", response_model=schemas.PlannedExpenseOut, status_code=status.HTTP_201_CREATED)
def create_planned_expense(
    body: schemas.PlannedExpenseCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
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
    for field, value in body.model_dump(exclude_unset=True).items():
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
    db.delete(expense)
    db.commit()
