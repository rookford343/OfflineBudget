"""The daily email's "Bank data updated ..." line: same source as the
Dashboard (last_success_at from active links), per-connection labels from
the linked account/card names, and a warning for a failing connection."""
from datetime import datetime
from decimal import Decimal
from backend import models
from backend.services.summary_generator import _last_pull_line, generate_daily_summary

NOW = datetime(2026, 8, 10, 9, 0)


def _identity(d):
    return d


def _user(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    checking = models.Account(user_id=user.id, name="Main Checking", type=models.AccountType.checking, current_balance=Decimal("0"))
    card = models.CreditCard(user_id=user.id, name="Travel Card", credit_limit=Decimal("1000"), statement_day=10, due_day=5)
    db.add_all([checking, card])
    db.flush()
    return user, checking, card


def _connection(db, user, provider, link_kwargs, **kwargs):
    conn = models.BankConnection(user_id=user.id, provider=provider, access_url_encrypted="x", **kwargs)
    db.add(conn)
    db.flush()
    db.add(models.BankConnectionAccountLink(connection_id=conn.id, simplefin_account_id=f"a{conn.id}", simplefin_account_name="Bank name", **link_kwargs))
    db.flush()
    return conn


def test_success_lists_each_connection_with_a_check(db_session):
    user, checking, card = _user(db_session)
    _connection(db_session, user, "plaid", dict(local_account_id=checking.id, last_synced_at=datetime(2026, 8, 10, 7, 0)))
    _connection(db_session, user, "simplefin", dict(local_credit_card_id=card.id, last_synced_at=datetime(2026, 8, 10, 6, 30)))
    db_session.commit()

    line = _last_pull_line(db_session, user.id, now_local=NOW, to_local=_identity)

    assert line == "Bank data updated today 7:00 AM · Main Checking (Plaid) ✓ · Travel Card (SimpleFIN) ✓"


def test_failing_connection_shows_last_good_time_not_failed_run_stamp(db_session):
    user, checking, card = _user(db_session)
    _connection(
        db_session, user, "simplefin", dict(local_credit_card_id=card.id, last_synced_at=datetime(2026, 8, 9, 15, 0)),
        status=models.BankConnectionStatus.error, last_error="boom", last_synced_at=datetime(2026, 8, 10, 8, 0),
    )
    db_session.commit()

    line = _last_pull_line(db_session, user.id, now_local=NOW, to_local=_identity)

    assert line == "Bank data updated yesterday 3:00 PM · Travel Card (SimpleFIN) ⚠ last good: yesterday 3:00 PM"


def test_no_connections_means_no_line_in_either_body(db_session):
    user, checking, card = _user(db_session)
    db_session.commit()

    assert _last_pull_line(db_session, user.id, now_local=NOW, to_local=_identity) is None
    html, text = generate_daily_summary(db_session, user)
    assert "Bank data" not in html
    assert "Bank data" not in text


def test_line_appears_in_html_and_plain_text(db_session):
    user, checking, card = _user(db_session)
    _connection(db_session, user, "plaid", dict(local_account_id=checking.id, last_synced_at=datetime.utcnow()))
    db_session.commit()

    html, text = generate_daily_summary(db_session, user)

    assert "Bank data updated today" in html and "Main Checking (Plaid)&nbsp;✓" in html
    assert text.splitlines()[1].startswith("Bank data updated today")
