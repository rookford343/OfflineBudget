from datetime import datetime, timedelta, timezone
from backend import models


def _make_user(db_session, username="alice"):
    user = models.User(
        username=username,
        hashed_password="x",
        display_name="Alice",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_user_recovery_fields_default_to_none(db_session):
    user = _make_user(db_session)
    assert user.recovery_code_hash is None
    assert user.recovery_code_created_at is None


def test_password_reset_token_round_trips(db_session):
    user = _make_user(db_session)
    token = models.PasswordResetToken(
        user_id=user.id,
        token_hash="hashed-value",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db_session.add(token)
    db_session.commit()
    db_session.refresh(token)
    assert token.used_at is None
    assert token.user_id == user.id
