"""Annual bonus plans (see services/bonus_plans.py)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.database import SessionLocal
from backend.dependencies import get_current_user
from backend.services.bonus_plans import refresh_item_amounts, upcoming_payouts

router = APIRouter(prefix="/bonus-plans", tags=["bonus-plans"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _out(plan: models.BonusPlan, user: models.User) -> schemas.BonusPlanOut:
    return schemas.BonusPlanOut(
        id=plan.id, recurring_item_id=plan.recurring_item_id, item_name=plan.recurring_item.name,
        target_pct=plan.target_pct, salary_lag_years=plan.salary_lag_years, withholding_pct=plan.withholding_pct,
        years=[schemas.BonusPlanYearIn(year=y.year, gross_amount=y.gross_amount) for y in plan.years],
        upcoming=[schemas.BonusPayoutOut(**row) for row in upcoming_payouts(plan, user, date.today())],
    )


def _own_item(db: Session, user: models.User, item_id: int) -> models.RecurringItem:
    item = db.query(models.RecurringItem).filter(
        models.RecurringItem.id == item_id, models.RecurringItem.user_id == user.id,
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Recurring item not found")
    if item.type != models.RecurringType.income or item.frequency != models.RecurringFrequency.yearly:
        raise HTTPException(status_code=422, detail="A bonus must use a yearly income item")
    return item


def _own_plan(db: Session, user: models.User, plan_id: int) -> models.BonusPlan:
    plan = db.query(models.BonusPlan).filter(
        models.BonusPlan.id == plan_id, models.BonusPlan.user_id == user.id,
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Bonus plan not found")
    return plan


def _apply(plan: models.BonusPlan, body: schemas.BonusPlanIn) -> None:
    plan.recurring_item_id = body.recurring_item_id
    plan.target_pct = body.target_pct
    plan.salary_lag_years = body.salary_lag_years
    plan.withholding_pct = body.withholding_pct
    plan.years = [models.BonusPlanYear(year=y.year, gross_amount=y.gross_amount) for y in body.years]


def _taken(db: Session, item_id: int, except_id: int | None = None) -> bool:
    q = db.query(models.BonusPlan).filter(models.BonusPlan.recurring_item_id == item_id)
    if except_id is not None:
        q = q.filter(models.BonusPlan.id != except_id)
    return q.first() is not None


@router.get("", response_model=list[schemas.BonusPlanOut])
def list_plans(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    refresh_item_amounts(db, user, date.today())
    plans = db.query(models.BonusPlan).filter(models.BonusPlan.user_id == user.id).order_by(models.BonusPlan.id).all()
    return [_out(p, user) for p in plans]


@router.post("", response_model=schemas.BonusPlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(body: schemas.BonusPlanIn, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    _own_item(db, user, body.recurring_item_id)
    if _taken(db, body.recurring_item_id):
        raise HTTPException(status_code=409, detail="That item already has a bonus plan")
    plan = models.BonusPlan(user_id=user.id)
    _apply(plan, body)
    db.add(plan)
    db.commit()
    refresh_item_amounts(db, user, date.today())
    db.refresh(plan)
    return _out(plan, user)


@router.put("/{plan_id}", response_model=schemas.BonusPlanOut)
def update_plan(plan_id: int, body: schemas.BonusPlanIn, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    plan = _own_plan(db, user, plan_id)
    _own_item(db, user, body.recurring_item_id)
    if _taken(db, body.recurring_item_id, except_id=plan.id):
        raise HTTPException(status_code=409, detail="That item already has a bonus plan")
    _apply(plan, body)
    db.commit()
    refresh_item_amounts(db, user, date.today())
    db.refresh(plan)
    return _out(plan, user)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.delete(_own_plan(db, user, plan_id))
    db.commit()
