from datetime import date, datetime, timedelta
from decimal import Decimal
from backend import models
from backend.services.summary_generator import _stale_bank_connections, generate_daily_summary


def _make_user_account(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("0"))
    db.add(account)
    db.flush()
    return user, account


def _make_connection(db, user, **kwargs):
    defaults = dict(user_id=user.id, access_url_encrypted="encrypted", status=models.BankConnectionStatus.active)
    defaults.update(kwargs)
    conn = models.BankConnection(**defaults)
    db.add(conn)
    db.flush()
    return conn


def test_a_freshly_synced_connection_is_not_stale(db_session):
    user, account = _make_user_account(db_session)
    now = datetime(2026, 8, 10, 12, 0, 0)
    _make_connection(db_session, user, last_synced_at=now - timedelta(hours=2))
    db_session.commit()

    assert _stale_bank_connections(db_session, user.id, now=now) == []


def test_a_connection_with_no_sync_in_24_hours_is_stale(db_session):
    user, account = _make_user_account(db_session)
    now = datetime(2026, 8, 10, 12, 0, 0)
    conn = _make_connection(db_session, user, last_synced_at=now - timedelta(hours=25))
    db_session.commit()

    result = _stale_bank_connections(db_session, user.id, now=now)
    assert [c.id for c in result] == [conn.id]


def test_a_connection_that_has_never_synced_is_stale(db_session):
    user, account = _make_user_account(db_session)
    conn = _make_connection(db_session, user, last_synced_at=None)
    db_session.commit()

    result = _stale_bank_connections(db_session, user.id)
    assert [c.id for c in result] == [conn.id]


def test_an_errored_connection_is_stale_even_if_recently_synced(db_session):
    user, account = _make_user_account(db_session)
    now = datetime(2026, 8, 10, 12, 0, 0)
    conn = _make_connection(
        db_session, user, status=models.BankConnectionStatus.error,
        last_synced_at=now - timedelta(minutes=5), last_error="401 Unauthorized",
    )
    db_session.commit()

    result = _stale_bank_connections(db_session, user.id, now=now)
    assert [c.id for c in result] == [conn.id]


def test_a_disconnected_connection_is_never_flagged_as_stale(db_session):
    """A deliberate disconnect is a user action, not a failure -- it
    shouldn't nag the daily email forever after."""
    user, account = _make_user_account(db_session)
    _make_connection(db_session, user, status=models.BankConnectionStatus.disconnected, last_synced_at=None)
    db_session.commit()

    assert _stale_bank_connections(db_session, user.id) == []


def test_generate_daily_summary_includes_a_stale_warning(db_session):
    user, account = _make_user_account(db_session)
    conn = _make_connection(db_session, user, status=models.BankConnectionStatus.error, last_error="Connection refused")
    db_session.add(models.BankConnectionAccountLink(
        connection_id=conn.id, simplefin_account_id="abc123", simplefin_account_name="Chase Checking",
    ))
    db_session.commit()

    html, text = generate_daily_summary(db_session, user)
    assert "Stale bank data" in html
    assert "Chase Checking" in html
    assert "Connection refused" in html
    assert "STALE BANK DATA" in text
    assert "Chase Checking" in text


def test_generate_daily_summary_omits_the_warning_when_nothing_is_stale(db_session):
    user, account = _make_user_account(db_session)
    _make_connection(db_session, user, last_synced_at=datetime.utcnow())
    db_session.commit()

    html, text = generate_daily_summary(db_session, user)
    assert "Stale bank data" not in html
    assert "STALE BANK DATA" not in text
