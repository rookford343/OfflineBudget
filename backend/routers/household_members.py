from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
from backend.routers._shared import owned_or_404

router = APIRouter(prefix="/household-members", tags=["household-members"])


@router.get("", response_model=list[schemas.HouseholdMemberOut])
def list_household_members(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return db.query(models.HouseholdMember).filter(
        models.HouseholdMember.user_id == user.id,
    ).order_by(models.HouseholdMember.name).all()


@router.post("", response_model=schemas.HouseholdMemberOut, status_code=status.HTTP_201_CREATED)
def create_household_member(
    body: schemas.HouseholdMemberCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    member = models.HouseholdMember(user_id=user.id, **body.model_dump())
    db.add(member)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="A household member with this name already exists")
    db.refresh(member)
    return member


@router.patch("/{member_id}", response_model=schemas.HouseholdMemberOut)
def update_household_member(
    member_id: int,
    body: schemas.HouseholdMemberCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    member = _get_or_404(db, user.id, member_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(member, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="A household member with this name already exists")
    db.refresh(member)
    return member


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_household_member(
    member_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    member = _get_or_404(db, user.id, member_id)
    referenced = db.query(models.RecurringItem).filter(
        models.RecurringItem.owner_id == member.id,
    ).count()
    if referenced:
        raise HTTPException(status_code=400, detail="Cannot delete a household member referenced by recurring items")
    db.delete(member)
    db.commit()


def _get_or_404(db: Session, user_id: int, member_id: int) -> models.HouseholdMember:
    return owned_or_404(db, models.HouseholdMember, member_id, user_id, "Household member not found")
