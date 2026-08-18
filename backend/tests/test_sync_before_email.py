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
