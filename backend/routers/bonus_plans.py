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


def _apply(db: Session, plan: models.BonusPlan, body: schemas.BonusPlanIn) -> None:
    plan.recurring_item_id = body.recurring_item_id
    plan.target_pct = body.target_pct
    plan.salary_lag_years = body.salary_lag_years
    plan.withholding_pct = body.withholding_pct
    # Flush the clear (the orphaned rows' DELETE) before the new rows' INSERT.
    # Replacing plan.years wholesale in one assignment lets SQLAlchemy flush
    # both sides in the same statement batch, and it orders INSERTs before
    # DELETEs -- a resent year collides with its own not-yet-deleted old row
    # on UniqueConstraint(plan_id, year) and 500s.
    plan.years.clear()
    db.flush()
    plan.years.extend(models.BonusPlanYear(year=y.year, gross_amount=y.gross_amount) for y in body.years)


def _taken(db: Session, item_id: int, except_id: int | None = None) -> bool:
    q = db.query(models.BonusPlan).filter(models.BonusPlan.recurring_item_id == item_id)
    if except_id is not None:
        q = q.filter(models.BonusPlan.id != except_id)
    return q.first() is not None


def _own_account(db: Session, user: models.User, account_id: int) -> models.Account:
    account = db.query(models.Account).filter(
        models.Account.id == account_id, models.Account.user_id == user.id,
    ).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.is_active:
        # Same style as _own_item above: right account, but the wrong shape
        # for this use (a closed account can't be a new allocation target).
        raise HTTPException(status_code=422, detail="Account is not active")
    return account


def _allocation_out(db: Session, user_id: int) -> schemas.BonusAllocationOut:
    # Takes a plain user_id and re-queries everything through `db` rather
    # than reading off a `user` object -- get_current_user resolves through
    # backend.dependencies.get_db, a DIFFERENT session from this router's
    # own get_db above, so a value just written via `db` would not yet be
    # visible on a `user` object sourced from that other session. See
    # update_allocation below.
    steps = (
        db.query(models.BonusAllocationStep)
        .filter(models.BonusAllocationStep.user_id == user_id)
        .order_by(models.BonusAllocationStep.position)
        .all()
    )
    user_row = db.query(models.User).filter(models.User.id == user_id).first()
    return schemas.BonusAllocationOut(
        steps=[
            schemas.BonusAllocationStepIn(account_id=s.account_id, kind=s.kind, value=s.value, round_to=s.round_to)
            for s in steps
        ],
        shortfall_account_id=user_row.bonus_shortfall_account_id,
        shortfall_round_to=user_row.bonus_shortfall_round_to,
    )


@router.get("", response_model=list[schemas.BonusPlanOut])
def list_plans(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    # Read-only: GET must never write, or a View Only account could trigger
    # one (backend/dependencies.py's get_current_user only blocks writes on
    # non-GET methods). Item amounts are kept fresh by POST, PUT, PATCH
    # /auth/me, and the scheduler sweep instead.
    plans = db.query(models.BonusPlan).filter(models.BonusPlan.user_id == user.id).order_by(models.BonusPlan.id).all()
    return [_out(p, user) for p in plans]


@router.post("", response_model=schemas.BonusPlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(body: schemas.BonusPlanIn, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    _own_item(db, user, body.recurring_item_id)
    if _taken(db, body.recurring_item_id):
        raise HTTPException(status_code=409, detail="That item already has a bonus plan")
    plan = models.BonusPlan(user_id=user.id)
    _apply(db, plan, body)
    db.add(plan)
    db.commit()
    refresh_item_amounts(db, user, date.today())
    db.refresh(plan)
    return _out(plan, user)


@router.get("/allocation", response_model=schemas.BonusAllocationOut)
def get_allocation(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    # Read-only, same rationale as list_plans above: must never write.
    return _allocation_out(db, user.id)


@router.put("/allocation", response_model=schemas.BonusAllocationOut)
def update_allocation(body: schemas.BonusAllocationIn, db: Session = Depends(get_db),
                      user: models.User = Depends(get_current_user)):
    for step in body.steps:
        _own_account(db, user, step.account_id)
    if body.shortfall_account_id is not None:
        _own_account(db, user, body.shortfall_account_id)

    # Everything below goes through `db` (this router's own session), using
    # only the scalar user.id off the get_current_user object -- see
    # _allocation_out's comment on why that object's own relationships/
    # fields can't be trusted to persist through THIS session's commit.
    user_row = db.query(models.User).filter(models.User.id == user.id).first()

    # Clear + flush + add, same pattern as _apply's plan.years above: flush
    # the clear's DELETE before the new rows' INSERT so a position collision
    # with the not-yet-deleted old rows can't happen.
    db.query(models.BonusAllocationStep).filter(models.BonusAllocationStep.user_id == user.id).delete()
    db.flush()
    db.add_all(
        models.BonusAllocationStep(user_id=user.id, position=position, account_id=step.account_id,
                                   kind=step.kind, value=step.value, round_to=step.round_to)
        for position, step in enumerate(body.steps)
    )
    user_row.bonus_shortfall_account_id = body.shortfall_account_id
    user_row.bonus_shortfall_round_to = body.shortfall_round_to
    db.commit()
    return _allocation_out(db, user.id)


@router.put("/{plan_id}", response_model=schemas.BonusPlanOut)
def update_plan(plan_id: int, body: schemas.BonusPlanIn, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    plan = _own_plan(db, user, plan_id)
    _own_item(db, user, body.recurring_item_id)
    if _taken(db, body.recurring_item_id, except_id=plan.id):
        raise HTTPException(status_code=409, detail="That item already has a bonus plan")
    _apply(db, plan, body)
    db.commit()
    refresh_item_amounts(db, user, date.today())
    db.refresh(plan)
    return _out(plan, user)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.delete(_own_plan(db, user, plan_id))
    db.commit()
