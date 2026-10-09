from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from jose import jwt, JWTError
from passlib.context import CryptContext
from backend.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


MIN_PASSWORD_LENGTH = 6


def check_new_password(password: str) -> None:
    """The one password rule. Every endpoint that sets a password calls this."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400,
                            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "username": username, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return {}
