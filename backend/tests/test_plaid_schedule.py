"""Plaid syncs four times a day (7, 11, 15, 19); SimpleFIN stays on the 7am
run only. Replaces the old 15:17 cards-only refresh (see
test_scheduler_job_locks.py's history) -- Plaid doesn't need a separate
cards-only pass because its Link covers both checking and credit-card
accounts through the same connection.

_run_plaid_sync shares _bank_sync_lock with the full 7am sync and manual Sync
Now (same double-insert race job_locks.py guards against), but -- like the
old card refresh it replaces -- has no missed-run retry: a skipped run is
simply picked up by the next scheduled Plaid sync or the next 7am full sync.
"""
from unittest.mock import patch

from apscheduler.triggers.cron import CronTrigger

from backend.services import job_locks
import backend.main as main


def test_jobs_registered():
    """A Plaid-only job exists for each of 11, 15 and 19, and nothing fires
    at the old 15:17 cards-only slot."""
    jobs = [j for j in main._scheduler.get_jobs() if j.func is main._run_plaid_sync]
    assert len(jobs) == 1
    fields = {f.name: str(f) for f in jobs[0].trigger.fields}
    assert fields["hour"] == "11,15,19"
    assert fields["minute"] == "0"

    cron_jobs = [j for j in main._scheduler.get_jobs() if isinstance(j.trigger, CronTrigger)]
    assert not any(
        {f.name: str(f) for f in j.trigger.fields}.get("hour") == "15"
        and {f.name: str(f) for f in j.trigger.fields}.get("minute") == "17"
        for j in cron_jobs
    )
    assert not hasattr(main, "_run_card_refresh")


def test_plaid_job_skips_when_locked():
    """The loser of the race against a concurrent full sync / Sync Now must
    return immediately without touching sync_all or opening a session."""
    assert job_locks._bank_sync_lock.acquire(blocking=False)
    try:
        with patch("backend.services.bank_sync_service.sync_all") as sync_spy, \
             patch("backend.database.SessionLocal") as session_spy:
            main._run_plaid_sync()
        sync_spy.assert_not_called()
        session_spy.assert_not_called()
    finally:
        job_locks._bank_sync_lock.release()


def test_plaid_job_only_plaid_provider():
    with patch("backend.services.bank_sync_service.sync_all") as sync_spy, \
         patch("backend.database.SessionLocal"):
        main._run_plaid_sync()
    assert sync_spy.call_args.kwargs == {"providers": {"plaid"}}
    assert job_locks._bank_sync_lock.acquire(blocking=False), "must release the lock after finishing"
    job_locks._bank_sync_lock.release()


def _bank_sync_job_run(db_session, monkeypatch):
    """Runs main._run_bank_sync_locked against `db_session` with sync_all
    stubbed out, so the connection statuses seeded by the test are what the
    job reads back. Returns the bank_sync SchedulerRun row."""
    from backend import models
    monkeypatch.setattr("backend.database.SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    with patch("backend.services.bank_sync_service.sync_all"):
        main._run_bank_sync_locked()
    return db_session.query(models.SchedulerRun).filter_by(job_name="bank_sync").one()


def _seed_connection(db_session, provider, status, last_error=None, username=None):
    from backend import models
    user = models.User(username=username or provider, hashed_password="x", display_name="u",
                       is_active=False)
    db_session.add(user)
    db_session.flush()
    db_session.add(models.BankConnection(
        user_id=user.id, access_url_encrypted="x", provider=provider, status=status, last_error=last_error,
        sync_cursor="cur-0" if provider == "plaid" else None,
    ))
    db_session.commit()


def test_errored_plaid_connection_does_not_fail_bank_sync(db_session, monkeypatch, caplog):
    """An errored Plaid connection (a bank needing a re-login) must not mark
    the 07:00 bank_sync failed: the sweep would then re-run the full sync,
    SimpleFIN included, about three times an hour all day. Plaid already has
    three more runs a day plus the Reconnect button."""
    from backend import models
    _seed_connection(db_session, "plaid", models.BankConnectionStatus.error, "needs login")
    _seed_connection(db_session, "simplefin", models.BankConnectionStatus.active)

    with caplog.at_level("WARNING"):
        run = _bank_sync_job_run(db_session, monkeypatch)

    assert run.last_success_at is not None
    assert run.last_error is None
    assert "needs login" in caplog.text


def test_errored_simplefin_connection_still_fails_bank_sync(db_session, monkeypatch):
    from backend import models
    _seed_connection(db_session, "plaid", models.BankConnectionStatus.active)
    _seed_connection(db_session, "simplefin", models.BankConnectionStatus.error, "bridge down")

    run = _bank_sync_job_run(db_session, monkeypatch)

    assert run.last_success_at is None
    assert "bridge down" in run.last_error


def test_plaid_job_logs_and_releases_lock_when_sync_all_raises(caplog):
    with patch("backend.services.bank_sync_service.sync_all", side_effect=RuntimeError("boom")), \
         patch("backend.database.SessionLocal"), caplog.at_level("ERROR"):
        main._run_plaid_sync()  # must not raise
    assert "Plaid sync failed: boom" in caplog.text
    assert job_locks._bank_sync_lock.acquire(blocking=False), "must release the lock after a failure"
    job_locks._bank_sync_lock.release()
