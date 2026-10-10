"""Concurrent bank syncs double-inserting transactions (the user, found live
2026-10-04 -- see .superpowers/sdd/sync-race/brief.md): the Mac sleeps
through the 5am cron, and on wake both the missed cron trigger
(misfire_grace_time) and the periodic sweep's own due_for_retry catch-up
call `_run_bank_sync` at the same moment. Both threads call `sync_all` at
once; each one's duplicate check only sees committed rows, so both insert
the same transactions. The daily-summary job has the identical shape via
the sweep's own retry of `_send_daily_summaries`.

Fix: a non-blocking `threading.Lock` per job (backend/services/job_locks.py).
A concurrent caller that finds the lock already held returns immediately
without doing any real work. These tests simulate "already held" the same
way a second racing thread would produce it -- by acquiring the lock in the
test itself before calling the guarded function.
"""
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.services import job_locks
import backend.main as main


def test_run_bank_sync_is_a_no_op_while_the_lock_is_held():
    """Whichever of the cron trigger / sweep retry gets there first holds
    _bank_sync_lock; the loser must return immediately without calling
    sync_all or even opening a database session."""
    assert job_locks._bank_sync_lock.acquire(blocking=False)
    try:
        with patch("backend.services.bank_sync_service.sync_all") as sync_spy, \
             patch("backend.database.SessionLocal") as session_spy:
            main._run_bank_sync()
        sync_spy.assert_not_called()
        session_spy.assert_not_called()
    finally:
        job_locks._bank_sync_lock.release()


def test_run_bank_sync_still_runs_when_the_lock_is_free():
    """Sanity check for the test above: with the lock free, the guarded body
    does run and does call sync_all."""
    with patch("backend.services.bank_sync_service.sync_all") as sync_spy, \
         patch("backend.services.transfer_verification.verify_scheduled_transfers"), \
         patch("backend.database.SessionLocal") as session_spy:
        session_spy.return_value.query.return_value.filter.return_value.all.return_value = []
        main._run_bank_sync()
    sync_spy.assert_called_once()
    assert not job_locks._bank_sync_lock.locked(), "must release the lock after finishing"


def test_send_daily_summaries_is_a_no_op_while_the_lock_is_held():
    """Same race, same fix, for the daily-summary email job."""
    assert job_locks._daily_summary_lock.acquire(blocking=False)
    try:
        with patch("backend.services.summary_generator.generate_daily_summary") as summary_spy, \
             patch("backend.database.SessionLocal") as session_spy:
            main._send_daily_summaries()
        summary_spy.assert_not_called()
        session_spy.assert_not_called()
    finally:
        job_locks._daily_summary_lock.release()


def _sync_now_client(db_session, user):
    from backend.routers import bank_sync as bank_sync_router_module
    app = FastAPI()
    app.include_router(bank_sync_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_sync_now_returns_409_while_the_bank_sync_lock_is_held(db_session):
    """A click on "Sync Now" during a scheduled sync must not race it --
    sync-now goes through the same _bank_sync_lock as the scheduled job."""
    user = models.User(username="dan", hashed_password="x", display_name="the user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    client = _sync_now_client(db_session, user)

    assert job_locks._bank_sync_lock.acquire(blocking=False)
    try:
        with patch("backend.routers.bank_sync.sync_connection") as spy:
            resp = client.post("/bank-sync/sync-now")
        spy.assert_not_called()
    finally:
        job_locks._bank_sync_lock.release()

    assert resp.status_code == 409
    assert resp.json()["detail"] == "A sync is already running"


def test_sync_now_still_works_when_the_lock_is_free(db_session):
    user = models.User(username="dan2", hashed_password="x", display_name="Dan2")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    client = _sync_now_client(db_session, user)

    resp = client.post("/bank-sync/sync-now")

    assert resp.status_code == 200
    assert not job_locks._bank_sync_lock.locked(), "must release the lock after finishing"


def test_bank_sync_runs_at_seven_and_the_email_waits_until_quarter_past():
    """the user, 2026-10-04: the Mac sleeps through 5am (lid closed), so the sync
    moved to 7. The email shares that hour, so it fires at :15 to land after
    the sync instead of racing it with yesterday's data."""
    assert main._BANK_SYNC_HOUR == 7
    jobs = {j.func.__name__: j for j in main._scheduler.get_jobs()}
    summary_fields = {f.name: str(f) for f in jobs["_send_daily_summaries"].trigger.fields}
    assert summary_fields["minute"] == "15"


def test_sweep_holds_the_email_while_a_sync_is_running():
    """A sweep that lands mid-sync (the cron sync is in another thread) must
    not send the day's email from pre-sync data; it retries next sweep."""
    sent = []
    assert job_locks._bank_sync_lock.acquire(blocking=False)
    try:
        with patch("backend.database.SessionLocal"), \
             patch("backend.services.app_settings.get_effective", return_value=7), \
             patch("backend.services.forecast_baseline.ensure_baselines_for_all"), \
             patch("backend.services.scheduler_state.due_for_retry", return_value=True), \
             patch.object(main, "_run_bank_sync", lambda: None), \
             patch.object(main, "_send_daily_summaries", lambda: sent.append(1)):
            main._scheduler_sweep()
    finally:
        job_locks._bank_sync_lock.release()
    assert sent == []


def test_card_refresh_is_a_no_op_while_a_bank_sync_holds_the_lock():
    """The afternoon cards-only refresh shares _bank_sync_lock: overlapping
    the full sync or a manual Sync Now would reopen the double-insert race."""
    assert job_locks._bank_sync_lock.acquire(blocking=False)
    try:
        with patch("backend.services.bank_sync_service.sync_all") as sync_spy:
            main._run_card_refresh()
        sync_spy.assert_not_called()
    finally:
        job_locks._bank_sync_lock.release()


def test_card_refresh_syncs_cards_only_and_releases_the_lock():
    with patch("backend.services.bank_sync_service.sync_all") as sync_spy, \
         patch("backend.database.SessionLocal"):
        main._run_card_refresh()
    assert sync_spy.call_args.kwargs == {"cards_only": True}
    assert job_locks._bank_sync_lock.acquire(blocking=False)
    job_locks._bank_sync_lock.release()


def test_card_refresh_is_scheduled_off_the_hour_in_the_afternoon():
    job = next(j for j in main._scheduler.get_jobs() if j.func is main._run_card_refresh)
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("15", "17")
