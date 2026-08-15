"""Merchant grouping corrections.

merchant_normalizer's heuristics will mis-group some descriptors. Without a
way to correct that, a wrong grouping silently corrupts the totals and
nobody can tell -- which is worse than the fragmented list it replaced.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/merchants", tags=["merchants"])


@router.get("/aliases", response_model=list[schemas.MerchantAliasOut])
def list_aliases(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return (
        db.query(models.MerchantAlias)
        .filter(models.MerchantAlias.user_id == user.id)
        .order_by(models.MerchantAlias.display_name)
        .all()
    )


@router.post("/aliases", response_model=schemas.MerchantAliasOut, status_code=status.HTTP_201_CREATED)
def create_alias(
    body: schemas.MerchantAliasCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    existing = db.query(models.MerchantAlias).filter(
        models.MerchantAlias.user_id == user.id,
        models.MerchantAlias.pattern == body.pattern.strip(),
    ).first()
    # Upsert rather than 409: re-mapping a name you already mapped is the
    # normal way to fix a correction that was itself wrong.
    if existing:
        existing.display_name = body.display_name.strip()
        db.commit()
        db.refresh(existing)
        return existing

    alias = models.MerchantAlias(
        user_id=user.id, pattern=body.pattern.strip(), display_name=body.display_name.strip(),
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return alias


@router.delete("/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alias(alias_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    alias = db.query(models.MerchantAlias).filter(
        models.MerchantAlias.id == alias_id,
        models.MerchantAlias.user_id == user.id,
    ).first()
    if not alias:
        raise HTTPException(status_code=404, detail="Alias not found")
    db.delete(alias)
    db.commit()
