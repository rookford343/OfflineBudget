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
from backend.auth import verify_password


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
    assert verify_and_consume_recovery_code(db_session, user, code, "brand-new-pw") is True
    # single-use: the same code fails on a second attempt
    assert user.recovery_code_hash is None
    # atomic: the password change landed in the same operation as the consume
    assert verify_password("brand-new-pw", user.hashed_password)
    assert verify_and_consume_recovery_code(db_session, user, code, "another-pw") is False
    # the second (rejected) attempt did not touch the already-set password
    assert verify_password("brand-new-pw", user.hashed_password)


def test_verify_and_consume_recovery_code_rejects_wrong_code(db_session):
    user = _make_user(db_session)
    issue_recovery_code(db_session, user)
    original_hash = user.hashed_password
    assert verify_and_consume_recovery_code(db_session, user, "wrong-code", "brand-new-pw") is False
    # a wrong attempt does not consume the real code or change the password
    assert user.recovery_code_hash is not None
    assert user.hashed_password == original_hash


def test_verify_and_consume_recovery_code_false_when_none_set(db_session):
    user = _make_user(db_session)
    assert verify_and_consume_recovery_code(db_session, user, "anything", "brand-new-pw") is False


from backend.services.password_reset import create_reset_token, consume_reset_token


def test_create_reset_token_returns_raw_and_stores_only_hash(db_session):
    user = _make_user(db_session)
    raw = create_reset_token(db_session, user)
    stored = db_session.query(models.PasswordResetToken).filter_by(user_id=user.id).one()
    assert stored.token_hash != raw
    assert stored.used_at is None


def test_consume_reset_token_sets_new_password_and_marks_used(db_session):
    user = _make_user(db_session)
    raw = create_reset_token(db_session, user)
    assert consume_reset_token(db_session, raw, "new-password-123") is True
    db_session.refresh(user)
    assert verify_password("new-password-123", user.hashed_password)
    stored = db_session.query(models.PasswordResetToken).filter_by(user_id=user.id).one()
    assert stored.used_at is not None


def test_consume_reset_token_rejects_reuse(db_session):
    user = _make_user(db_session)
    raw = create_reset_token(db_session, user)
    assert consume_reset_token(db_session, raw, "first-password") is True
    assert consume_reset_token(db_session, raw, "second-password") is False


def test_consume_reset_token_rejects_expired(db_session):
    user = _make_user(db_session)
    raw = create_reset_token(db_session, user)
    stored = db_session.query(models.PasswordResetToken).filter_by(user_id=user.id).one()
    stored.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    assert consume_reset_token(db_session, raw, "new-password-123") is False


def test_consume_reset_token_rejects_unknown_token(db_session):
    assert consume_reset_token(db_session, "not-a-real-token", "new-password-123") is False


def test_create_reset_token_invalidates_prior_outstanding_tokens(db_session):
    user = _make_user(db_session)
    first = create_reset_token(db_session, user)
    create_reset_token(db_session, user)  # second, current token
    # the first token must no longer work once a new one is issued
    assert consume_reset_token(db_session, first, "new-password-123") is False
