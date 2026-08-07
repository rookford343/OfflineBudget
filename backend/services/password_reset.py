import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from backend import models
from backend.auth import hash_password, verify_password

# Unambiguous charset — no 0/O, 1/I/l — so a hand-copied code doesn't misread.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_GROUP_LEN = 4
_CODE_GROUPS = 3

RESET_TOKEN_TTL = timedelta(minutes=15)


def _generate_recovery_code() -> str:
    groups = [
        "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_GROUP_LEN))
        for _ in range(_CODE_GROUPS)
    ]
    return "-".join(groups)


def issue_recovery_code(db: Session, user: models.User) -> str:
    """Generates a new recovery code, stores only its hash, and returns the
    raw code once. Overwrites any previously issued code."""
    code = _generate_recovery_code()
    user.recovery_code_hash = hash_password(code)
    user.recovery_code_created_at = datetime.now(timezone.utc)
    db.commit()
    return code


def verify_and_consume_recovery_code(db: Session, user: models.User, code: str) -> bool:
    """Verifies a recovery code and, on success, clears it (single-use)."""
    if not user.recovery_code_hash:
        return False
    if not verify_password(code, user.recovery_code_hash):
        return False
    user.recovery_code_hash = None
    user.recovery_code_created_at = None
    db.commit()
    return True


def create_reset_token(db: Session, user: models.User) -> str:
    """Invalidates any outstanding tokens for this user, issues a new one,
    and returns the raw token (only its hash is persisted)."""
    now = datetime.now(timezone.utc)
    outstanding = (
        db.query(models.PasswordResetToken)
        .filter(models.PasswordResetToken.user_id == user.id)
        .filter(models.PasswordResetToken.used_at.is_(None))
        .all()
    )
    for t in outstanding:
        t.used_at = now

    raw_token = secrets.token_urlsafe(32)
    record = models.PasswordResetToken(
        user_id=user.id,
        token_hash=hash_password(raw_token),
        expires_at=now + RESET_TOKEN_TTL,
    )
    db.add(record)
    db.commit()
    return raw_token


def consume_reset_token(db: Session, raw_token: str, new_password: str) -> bool:
    """Verifies a raw reset token, sets the new password, and marks the
    token used. Bcrypt hashes aren't lookup-able by value, so this scans
    unused, unexpired tokens — a small, bounded set in a single-household
    deployment — and verifies each candidate."""
    now = datetime.now(timezone.utc)
    candidates = (
        db.query(models.PasswordResetToken)
        .filter(models.PasswordResetToken.used_at.is_(None))
        .filter(models.PasswordResetToken.expires_at > now)
        .all()
    )
    for candidate in candidates:
        if verify_password(raw_token, candidate.token_hash):
            user = db.get(models.User, candidate.user_id)
            if not user:
                return False
            user.hashed_password = hash_password(new_password)
            candidate.used_at = now
            db.commit()
            return True
    return False
