"""Request helpers every router shares, so an ownership or validation fix
lands once instead of in each router's private copy."""
from fastapi import HTTPException
from sqlalchemy.orm import Session


def owned_or_404(db: Session, model, obj_id: int, user_id: int, detail: str = "Not found"):
    """The row, if it exists and belongs to `user_id`; otherwise 404. Another
    user's row is indistinguishable from a missing one."""
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user_id:
        raise HTTPException(status_code=404, detail=detail)
    return obj


def reject_nulls(data: dict, required: set[str]) -> None:
    """422s an explicit JSON null on a field the model stores NOT NULL. Without
    this, the setattr loops write None straight through and the eventual
    commit surfaces as an IntegrityError (500) instead of a validation error."""
    for key in required:
        if key in data and data[key] is None:
            raise HTTPException(status_code=422, detail=f"{key} can't be empty")
