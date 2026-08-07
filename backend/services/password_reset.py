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
