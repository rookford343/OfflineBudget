from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/goals", tags=["goals"])


def _enrich(goal: models.SavingsGoal) -> dict:
    pct = float(goal.current_amount / goal.target_amount * 100) if goal.target_amount else 0.0
    monthly_needed = None
    months_remaining = None
    if goal.target_date:
        today = date.today()
        if goal.target_date > today:
            months = (goal.target_date.year - today.year) * 12 + (goal.target_date.month - today.month)
            months_remaining = max(months, 1)
            remaining = goal.target_amount - goal.current_amount
            monthly_needed = remaining / months_remaining if remaining > 0 else Decimal("0")
    return {
        "id": goal.id,
        "name": goal.name,
        "target_amount": goal.target_amount,
        "target_date": goal.target_date,
        "linked_account_id": goal.linked_account_id,
        "current_amount": goal.current_amount,
        "notes": goal.notes,
        "is_active": goal.is_active,
        "created_at": goal.created_at,
        "percent_complete": round(pct, 1),
        "monthly_needed": monthly_needed,
        "months_remaining": months_remaining,
    }


@router.get("/", response_model=list[schemas.SavingsGoalOut])
def list_goals(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    goals = db.query(models.SavingsGoal).filter(
        models.SavingsGoal.user_id == user.id,
        models.SavingsGoal.is_active == True,
    ).all()
    return [_enrich(g) for g in goals]


@router.post("/", response_model=schemas.SavingsGoalOut)
def create_goal(
    data: schemas.SavingsGoalCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    goal = models.SavingsGoal(user_id=user.id, **data.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return _enrich(goal)


@router.patch("/{goal_id}", response_model=schemas.SavingsGoalOut)
def update_goal(
    goal_id: int,
    data: schemas.SavingsGoalUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    goal = db.query(models.SavingsGoal).filter(
        models.SavingsGoal.id == goal_id,
        models.SavingsGoal.user_id == user.id,
    ).first()
    if not goal:
        raise HTTPException(404, "Goal not found")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(goal, k, v)
    db.commit()
    db.refresh(goal)
    return _enrich(goal)


@router.delete("/{goal_id}")
def delete_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    goal = db.query(models.SavingsGoal).filter(
        models.SavingsGoal.id == goal_id,
        models.SavingsGoal.user_id == user.id,
    ).first()
    if not goal:
        raise HTTPException(404, "Goal not found")
    db.delete(goal)
    db.commit()
    return {"ok": True}
