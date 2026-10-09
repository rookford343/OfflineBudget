from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.auth import decode_token
from backend import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _resolve_user(token: str, db: Session) -> models.User:
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.get(models.User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_requester(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """Always returns the actual logged-in user — never resolves linked accounts."""
    return _resolve_user(token, db)


_READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """Returns the data owner: linked admin if set, otherwise the logged-in user.

    The View Only role is enforced here, the one dependency every data
    endpoint shares: a viewer may read but never write. Their own login
    (/auth/me, password) goes through get_requester and stays writable."""
    user = _resolve_user(token, db)
    if user.role == models.UserRole.viewer and request.method not in _READ_METHODS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="View Only accounts can't make changes")
    if user.linked_to_user_id:
        owner = db.get(models.User, user.linked_to_user_id)
        if owner and owner.is_active:
            return owner
    return user


def require_admin(requester: models.User = Depends(get_requester)) -> models.User:
    if requester.role != models.UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return requester
