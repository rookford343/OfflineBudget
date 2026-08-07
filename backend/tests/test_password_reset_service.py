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


from backend.services.password_reset import (
    issue_recovery_code,
    verify_and_consume_recovery_code,
)


def test_issue_recovery_code_returns_raw_and_stores_hash_only(db_session):
    user = _make_user(db_session)
    code = issue_recovery_code(db_session, user)
    assert len(code) >= 12
    assert user.recovery_code_hash is not None
    assert user.recovery_code_hash != code
    assert user.recovery_code_created_at is not None


def test_verify_and_consume_recovery_code_succeeds_and_rotates(db_session):
    user = _make_user(db_session)
    code = issue_recovery_code(db_session, user)
    assert verify_and_consume_recovery_code(db_session, user, code) is True
    # single-use: the same code fails on a second attempt
    assert user.recovery_code_hash is None
    assert verify_and_consume_recovery_code(db_session, user, code) is False


def test_verify_and_consume_recovery_code_rejects_wrong_code(db_session):
    user = _make_user(db_session)
    issue_recovery_code(db_session, user)
    assert verify_and_consume_recovery_code(db_session, user, "wrong-code") is False
    # a wrong attempt does not consume the real code
    assert user.recovery_code_hash is not None


def test_verify_and_consume_recovery_code_false_when_none_set(db_session):
    user = _make_user(db_session)
    assert verify_and_consume_recovery_code(db_session, user, "anything") is False
