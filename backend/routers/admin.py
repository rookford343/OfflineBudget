from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.auth import hash_password
from backend.dependencies import get_db, require_admin, get_requester
from backend.seed import seed_default_categories

router = APIRouter(prefix="/admin", tags=["admin"])


# ── User Management ───────────────────────────────────────────────────────────

@router.get("/users", response_model=list[schemas.UserAdminOut])
def list_users(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    return db.query(models.User).order_by(models.User.created_at).all()


@router.post("/users", response_model=schemas.UserAdminOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: schemas.UserAdminCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    if db.query(models.User).filter(models.User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    user = models.User(
        username=body.username,
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
        role=body.role,
        linked_to_user_id=body.linked_to_user_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if not body.linked_to_user_id:
        seed_default_categories(db, user)
    return user


@router.patch("/users/{user_id}", response_model=schemas.UserAdminOut)
def update_user(
    user_id: int,
    body: schemas.UserAdminUpdate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(require_admin),
):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_admin.id and body.role == models.UserRole.viewer:
        raise HTTPException(status_code=400, detail="Cannot demote your own account to viewer")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


# ── Audit Logs ────────────────────────────────────────────────────────────────

@router.get("/logs", response_model=schemas.AuditLogPage)
def list_logs(
    limit: int = Query(50, le=200),
    offset: int = 0,
    method: Optional[str] = None,
    username: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    q = db.query(models.AuditLog)
    if method:
        q = q.filter(models.AuditLog.method == method.upper())
    if username:
        q = q.filter(models.AuditLog.username.ilike(f"%{username}%"))
    if start_date:
        q = q.filter(models.AuditLog.timestamp >= start_date)
    if end_date:
        from datetime import datetime, time
        q = q.filter(models.AuditLog.timestamp <= datetime.combine(end_date, time.max))
    total = q.count()
    items = q.order_by(models.AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
    return schemas.AuditLogPage(total=total, items=items)
