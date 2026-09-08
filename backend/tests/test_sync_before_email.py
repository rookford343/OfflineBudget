from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from backend import models
from backend.services import scheduler_state


def _mark_success(db, job, when):
    db.add(models.SchedulerRun(job_name=job, last_success_at=when))
    db.commit()


def test_summary_syncs_first_when_the_day_has_no_successful_sync(db_session):
    """The report quotes balances and month-to-date spend, so sending before
    the day's sync mails yesterday's numbers."""
    import backend.main as main
    calls = []
    with patch.object(main, "_run_bank_sync", side_effect=lambda: calls.append("sync")), \
         patch("backend.database.SessionLocal", return_value=db_session), \
         patch.object(db_session, "close", lambda: None), \
         patch("backend.services.scheduler_state.succeeded_today", return_value=False):
        main._send_daily_summaries()
    assert calls == ["sync"]


def test_summary_skips_the_sync_when_it_already_succeeded_today(db_session):
    """The normal 5am-then-7am path must not pay for a second sync."""
    import backend.main as main
    calls = []
    with patch.object(main, "_run_bank_sync", side_effect=lambda: calls.append("sync")), \
         patch("backend.database.SessionLocal", return_value=db_session), \
         patch.object(db_session, "close", lambda: None), \
         patch("backend.services.scheduler_state.succeeded_today", return_value=True):
        main._send_daily_summaries()
    assert calls == []


def test_a_failing_sync_still_lets_the_report_go_out(db_session):
    """Stale numbers beat no report: a bank outage should degrade the email,
    not cancel it."""
    import backend.main as main
    def boom():
        raise RuntimeError("bank unreachable")
    with patch.object(main, "_run_bank_sync", side_effect=boom), \
         patch("backend.database.SessionLocal", return_value=db_session), \
         patch.object(db_session, "close", lambda: None), \
         patch("backend.services.scheduler_state.succeeded_today", return_value=False):
        main._send_daily_summaries()  # must not raise


def test_succeeded_today_converts_utc_storage_to_local(db_session):
    """last_success_at is stored UTC-naive; comparing its raw .date() against
    a local date is wrong for the whole UTC-offset window each night."""
    now_local = datetime.now()
    _mark_success(db_session, "bank_sync", datetime.utcnow())
    assert scheduler_state.succeeded_today(db_session, "bank_sync", now=now_local) is True


def test_succeeded_today_is_false_for_a_stale_success(db_session):
    _mark_success(db_session, "bank_sync", datetime.utcnow() - timedelta(days=2))
    assert scheduler_state.succeeded_today(db_session, "bank_sync") is False


def test_succeeded_today_fails_closed_when_never_run(db_session):
    """"Not sure" must mean "hasn't run" -- that costs one redundant sync
    instead of a report built on stale balances."""
    assert scheduler_state.succeeded_today(db_session, "bank_sync") is False


# ── Dedupe by recipient across multiple active users ──────────────────────

def test_a_second_active_user_resolving_to_the_same_recipient_is_not_emailed_twice(db_session):
    """Real incident, 2026-09-08: get_recipients() returns the SAME global
    list for every active user (it isn't scoped per-user at all -- see its
    own docstring), so a second active User row -- however it got there --
    sends a second, independently-generated report to the identical inbox.
    Two stray test-fixture users left active in the production database
    from an earlier debugging session sent Dan two extra, garbage-data
    copies of his real morning report. Each unique recipient must get at
    most one email per run, regardless of how many User rows resolve to it."""
    import backend.main as main
    from decimal import Decimal

    real = models.User(username="dan", hashed_password="x", display_name="Dan", email="dan@example.com")
    stray = models.User(username="trace1", hashed_password="x", display_name="Trace")
    db_session.add_all([real, stray])
    db_session.flush()
    db_session.add(models.Account(user_id=real.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("100.00")))
    db_session.add(models.Account(user_id=stray.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("60000.00")))
    # The one setting that makes both users resolve to the same inbox --
    # this is exactly how the real incident happened (REPORT_RECIPIENTS is
    # global, not per-user).
    db_session.add(models.AppSetting(key="REPORT_RECIPIENTS", value="dan@example.com"))
    db_session.commit()

    generated_for: list[str] = []

    def _fake_generate(db, u, **kw):
        generated_for.append(u.username)
        return ("<html>", "text")

    sent_to: list[str] = []

    def _capture(db, to, *a, **kw):
        sent_to.append(to)
        return (True, None)

    with patch("backend.database.SessionLocal", return_value=db_session), \
         patch.object(db_session, "close", lambda: None), \
         patch("backend.services.scheduler_state.succeeded_today", return_value=True), \
         patch("backend.services.summary_generator.generate_daily_summary", _fake_generate), \
         patch("backend.services.email_service.send_email_via", _capture):
        main._send_daily_summaries()

    assert sent_to == ["dan@example.com"], (
        f"the same recipient must never get two separate reports in one run, got {sent_to}"
    )
    assert generated_for == ["dan"], (
        f"a report should not even be generated for a user whose only recipient "
        f"is already served, got {generated_for}"
    )
