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
    # Scoped to this user AND to active items only: a cross-user reference
    # should no longer be creatable (recurring.py validates owner_id against
    # the caller's own household members on create/update), but this count
    # stays defensively user-scoped regardless, and a soft-deleted
    # (is_active=False) item never counts -- a removed item shouldn't make
    # the member it once pointed at permanently undeletable.
    referenced = db.query(models.RecurringItem).filter(
        models.RecurringItem.owner_id == member.id,
        models.RecurringItem.user_id == user.id,
        models.RecurringItem.is_active == True,
    ).count()
    if referenced:
        raise HTTPException(status_code=400, detail="Cannot delete a household member referenced by recurring items")
    # The guard above only blocks on this user's active items, so a row can
    # still physically reference this member via the raw owner_id FK at this
    # point: this user's own soft-deleted item. owner_id has no ON DELETE
    # behavior, so leaving that in place would turn db.delete(member) below
    # into an unhandled FK IntegrityError instead of the clean 204 the guard
    # just decided this delete should get. Clear the FK on every such row
    # first -- a soft-deleted item keeps its own history, it just stops
    # pointing at a member that no longer exists. Deliberately scoped to
    # this user: another user's row must never be mutated by this request,
    # even a stale/defensive-only cross-tenant reference (recurring.py
    # blocks creating new ones), so we do NOT touch it here.
    db.query(models.RecurringItem).filter(
        models.RecurringItem.owner_id == member.id,
        models.RecurringItem.user_id == user.id,
    ).update({models.RecurringItem.owner_id: None}, synchronize_session=False)
    db.delete(member)
    # A stale cross-tenant row (pre-dating the ownership validation in
    # recurring.py, or otherwise pre-existing corrupt data) can still
    # reference this member and was deliberately left untouched above, so
    # this commit can legitimately hit the FK constraint. Converting that
    # into the same 400 the guard above already returns -- rather than
    # letting it surface as an unhandled 500 -- keeps the member stuck
    # undeletable in that narrow, should-no-longer-happen case instead of
    # either crashing or silently mutating the other tenant's data.
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot delete a household member referenced by recurring items")


def _get_or_404(db: Session, user_id: int, member_id: int) -> models.HouseholdMember:
    return owned_or_404(db, models.HouseholdMember, member_id, user_id, "Household member not found")
