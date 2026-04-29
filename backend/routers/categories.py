from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[schemas.CategoryOut])
def list_categories(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Return only top-level categories; children are nested via relationship
    tops = db.query(models.Category).filter(
        models.Category.user_id == user.id,
        models.Category.parent_id == None,
    ).order_by(models.Category.sort_order).all()
    return tops


@router.post("", response_model=schemas.CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if body.parent_id:
        parent = db.query(models.Category).filter(
            models.Category.id == body.parent_id,
            models.Category.user_id == user.id,
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent category not found")
    cat = models.Category(user_id=user.id, **body.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.patch("/{cat_id}", response_model=schemas.CategoryOut)
def update_category(
    cat_id: int,
    body: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    cat = _get_or_404(db, user.id, cat_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(cat, field, value)
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{cat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    cat_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    cat = _get_or_404(db, user.id, cat_id)
    if cat.children:
        raise HTTPException(status_code=400, detail="Cannot delete a category that has sub-categories")
    db.delete(cat)
    db.commit()


def _get_or_404(db: Session, user_id: int, cat_id: int) -> models.Category:
    cat = db.query(models.Category).filter(
        models.Category.id == cat_id,
        models.Category.user_id == user_id,
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    return cat
