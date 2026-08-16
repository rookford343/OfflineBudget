from calendar import monthrange
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("", response_model=list[schemas.BudgetAllocationOut])
def list_allocations(
    year: int = date.today().year,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return db.query(models.BudgetAllocation).filter(
        models.BudgetAllocation.user_id == user.id,
        models.BudgetAllocation.year == year,
    ).all()


@router.post("", response_model=schemas.BudgetAllocationOut)
def upsert_allocation(
    body: schemas.BudgetAllocationCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    existing = db.query(models.BudgetAllocation).filter(
        models.BudgetAllocation.user_id == user.id,
        models.BudgetAllocation.category_id == body.category_id,
        models.BudgetAllocation.year == body.year,
        models.BudgetAllocation.month == body.month,
    ).first()
    if existing:
        existing.budgeted_amount = body.budgeted_amount
        db.commit()
        db.refresh(existing)
        return existing
    alloc = models.BudgetAllocation(user_id=user.id, **body.model_dump())
    db.add(alloc)
    db.commit()
    db.refresh(alloc)
    return alloc


@router.get("/overview", response_model=list[schemas.BudgetOverviewRow])
def budget_overview(
    year: int = date.today().year,
    month: int = date.today().month,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.budget_calculator import compute_overview
    return compute_overview(db, user.id, year, month)


@router.post("/rollover/{year}/{month}")
def apply_rollover(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from backend.services.budget_calculator import apply_rollover as _apply
    updated = _apply(db, user.id, year, month)
    return {"updated_categories": updated, "year": year, "month": month}


@router.patch("/categories/{category_id}/rollover")
def set_category_rollover(
    category_id: int,
    body: schemas.CategoryRolloverUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    cat = db.query(models.Category).filter(
        models.Category.id == category_id,
        models.Category.user_id == user.id,
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    cat.rollover_enabled = body.rollover_enabled
    db.commit()
    return {"category_id": category_id, "rollover_enabled": cat.rollover_enabled}


@router.get("/category-breakdown", response_model=list[schemas.MerchantSpendingEntry])
def budget_category_breakdown(
    category_id: int,
    year: int = date.today().year,
    month: int = date.today().month,
    limit: int = 25,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """The merchants making up one budget line this month.

    Answers "what is actually in my $800 Subscriptions?" without leaving the
    Budget page. Includes the category's children, because a budget set on a
    parent is measured against everything beneath it -- which is the whole
    point of budgeting at the top level.
    """
    category = db.query(models.Category).filter(
        models.Category.id == category_id,
        models.Category.user_id == user.id,
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    child_ids = [
        c.id for c in db.query(models.Category).filter(
            models.Category.user_id == user.id,
            models.Category.parent_id == category_id,
        ).all()
    ]
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    from backend.services.spending_helpers import merchant_totals
    rows = merchant_totals(
        db, user.id, start, end,
        category_ids=[category_id] + child_ids, limit=limit,
    )
    return [
        schemas.MerchantSpendingEntry(name=name, total=total, count=count)
        for name, total, count in rows
    ]


@router.delete("/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Remove a budget line entirely.

    Distinct from setting it to 0: a zero budget means "spend nothing here"
    and reports every dollar as an overage, while no allocation means the
    category simply isn't budgeted and shouldn't be scored at all.
    """
    alloc = db.query(models.BudgetAllocation).filter(
        models.BudgetAllocation.id == allocation_id,
        models.BudgetAllocation.user_id == user.id,
    ).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Budget allocation not found")
    db.delete(alloc)
    db.commit()
