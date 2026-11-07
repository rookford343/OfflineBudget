"""Change history: what moved each headline figure between readings."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.dependencies import get_current_user, get_db
from backend.services import metric_history
from backend.services.metric_diff import changes_for

router = APIRouter(prefix="/history", tags=["history"])

KEY_PATTERN = r"^[a-z_]{1,40}(:\d{1,9})?$"


@router.post("/snapshot")
def take_snapshot(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return {"recorded": metric_history.record_snapshot(db, user, "manual") is not None}


@router.delete("")
def clear_history(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    ids = [row[0] for row in db.query(models.MetricSnapshot.id)
           .filter(models.MetricSnapshot.user_id == user.id).all()]
    if ids:
        db.query(models.MetricReading).filter(
            models.MetricReading.snapshot_id.in_(ids),
        ).delete(synchronize_session=False)
        db.query(models.MetricSnapshot).filter(
            models.MetricSnapshot.id.in_(ids),
        ).delete(synchronize_session=False)
        db.commit()
    return {"deleted": len(ids)}


@router.get("/{metric_key}", response_model=schemas.MetricHistoryOut)
def metric_history_for(
    metric_key: str = Path(pattern=KEY_PATTERN),
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    newest = (
        db.query(models.MetricReading)
        .join(models.MetricSnapshot, models.MetricReading.snapshot_id == models.MetricSnapshot.id)
        .filter(models.MetricSnapshot.user_id == user.id, models.MetricReading.metric_key == metric_key)
        .order_by(models.MetricSnapshot.taken_at.desc(), models.MetricSnapshot.id.desc())
        .first()
    )
    if newest is None:
        raise HTTPException(status_code=404, detail="No history for that figure")
    return schemas.MetricHistoryOut(
        metric_key=metric_key, label=newest.label, current_value=newest.value,
        changes=changes_for(db, user.id, metric_key, limit),
    )
