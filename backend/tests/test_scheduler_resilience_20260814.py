"""Scheduler resilience for a laptop that sleeps overnight (Dan, 2026-08-14):
run at a scheduled time, and if that was missed, catch up when the machine
is next available. Two distinct failure shapes, covered separately --
misfire_grace_time (main.py, not exercised here -- it's an APScheduler
config value, not app logic) for "never fired," and scheduler_state's
due_for_retry for "fired but failed, or never fired at all and it's now
later in the day."
"""
from datetime import date, datetime, timedelta
from backend import models
from backend.services import scheduler_state


def test_due_for_retry_is_false_before_the_scheduled_hour(db_session):
    """Not due yet at 3am for a 5am job -- there's nothing to catch up on."""
    assert scheduler_state.due_for_retry(
        db_session, "bank_sync", target_hour=5, now=datetime(2026, 8, 14, 3, 0),
    ) is False


def test_due_for_retry_is_true_with_no_prior_run_at_all(db_session):
    """A job that has never once succeeded (fresh install, or every prior
    attempt failed) is due as soon as its hour arrives."""
    assert scheduler_state.due_for_retry(
        db_session, "bank_sync", target_hour=5, now=datetime(2026, 8, 14, 9, 0),
    ) is True


def test_due_for_retry_is_false_after_a_success_today(db_session):
    scheduler_state.record_success(db_session, "bank_sync")
    assert scheduler_state.due_for_retry(
        db_session, "bank_sync", target_hour=5, now=datetime.now().replace(hour=23, minute=0),
    ) is False


def test_due_for_retry_is_true_when_the_last_success_was_yesterday(db_session):
    """The exact scenario this exists for: the job succeeded yesterday
    morning, then last night's run was missed (asleep through it) -- today,
    past the scheduled hour, it must be retried."""
    run = models.SchedulerRun(job_name="bank_sync", last_success_at=datetime.now() - timedelta(days=1))
    db_session.add(run)
    db_session.commit()

    assert scheduler_state.due_for_retry(
        db_session, "bank_sync", target_hour=5, now=datetime.now().replace(hour=9, minute=0),
    ) is True


def test_record_failure_does_not_clear_a_prior_success_timestamp(db_session):
    """A failed retry attempt must not erase evidence that the job succeeded
    earlier today -- due_for_retry keys on last_success_at, not last_error."""
    scheduler_state.record_success(db_session, "bank_sync")
    scheduler_state.record_failure(db_session, "bank_sync", "network blip")

    run = db_session.query(models.SchedulerRun).filter_by(job_name="bank_sync").first()
    assert run.last_success_at is not None
    assert run.last_error == "network blip"


def test_record_success_clears_a_prior_error(db_session):
    scheduler_state.record_failure(db_session, "bank_sync", "no network")
    scheduler_state.record_success(db_session, "bank_sync")

    run = db_session.query(models.SchedulerRun).filter_by(job_name="bank_sync").first()
    assert run.last_error is None
    assert run.last_success_at is not None


def test_a_broken_session_does_not_raise():
    """Status tracking must never be able to take down the job it's only
    observing -- a locked DB file or a session that can't write must fail
    silently here, not propagate into the sync/email job."""
    class BrokenSession:
        def query(self, *a, **kw):
            raise RuntimeError("db is locked")

    scheduler_state.record_attempt(BrokenSession(), "bank_sync")  # must not raise
    scheduler_state.record_success(BrokenSession(), "bank_sync")  # must not raise
    scheduler_state.record_failure(BrokenSession(), "bank_sync", "x")  # must not raise
    assert scheduler_state.due_for_retry(BrokenSession(), "bank_sync", target_hour=0) is False


# --- Raw bank-data debug capture (Dan, 2026-08-14) -----------------------

def test_raw_snapshot_is_captured_only_when_the_debug_flag_is_on(db_session):
    from decimal import Decimal
    from backend.services.bank_sync_service import _capture_raw_snapshots
    from backend.services.simplefin_client import SimpleFinTransaction

    user = models.User(username="raw1", hashed_password="x", display_name="Raw",
                        debug_capture_raw_bank_data=True)
    db_session.add(user)
    db_session.flush()

    txns = [SimpleFinTransaction(
        id="sf-raw-1", posted=datetime(2026, 8, 14), amount=Decimal("-12.34"),
        description="Coffee", raw={"id": "sf-raw-1", "payee": "Coffee Shop", "pending": False},
    )]
    _capture_raw_snapshots(db_session, user.id, txns)
    db_session.commit()

    snap = db_session.query(models.BankSyncRawSnapshot).filter_by(external_id="sf-raw-1").first()
    assert snap is not None
    assert "Coffee Shop" in snap.raw_json


def test_raw_snapshot_overwrites_in_place_on_resync(db_session):
    """_OVERLAP_DAYS re-fetches a few days of overlap on every sync -- the
    snapshot must update in place, not accumulate a duplicate row per sync."""
    from decimal import Decimal
    from backend.services.bank_sync_service import _capture_raw_snapshots
    from backend.services.simplefin_client import SimpleFinTransaction

    user = models.User(username="raw2", hashed_password="x", display_name="Raw2")
    db_session.add(user)
    db_session.flush()

    first = [SimpleFinTransaction(id="sf-raw-2", posted=datetime(2026, 8, 14), amount=Decimal("-1"),
                                   description="A", raw={"pending": True})]
    _capture_raw_snapshots(db_session, user.id, first)
    db_session.commit()

    second = [SimpleFinTransaction(id="sf-raw-2", posted=datetime(2026, 8, 14), amount=Decimal("-1"),
                                    description="A", raw={"pending": False})]
    _capture_raw_snapshots(db_session, user.id, second)
    db_session.commit()

    rows = db_session.query(models.BankSyncRawSnapshot).filter_by(external_id="sf-raw-2").all()
    assert len(rows) == 1, "must overwrite, not accumulate"
    assert "false" in rows[0].raw_json.lower()


# --- Timezone correctness (found in the 2026-08-14 cleanup audit) --------

def test_due_for_retry_compares_the_stored_utc_timestamp_against_local_date():
    """last_success_at is stored UTC-naive; target_hour is an APScheduler cron
    hour, which means LOCAL wall clock. Comparing the raw UTC .date() against
    a local date() gets the answer wrong for the whole UTC-offset window each
    night -- in EDT (UTC-4), a job that succeeded at 21:00 local Monday is
    stored as 01:00 UTC Tuesday, so a naive comparison on Monday night would
    call it "already succeeded today" a full day early.

    Verified against the real function rather than a reimplementation: a
    success 30 minutes ago must never read as due, whatever the offset.
    """
    from datetime import datetime as dt

    class _Run:
        last_success_at = dt.utcnow() - timedelta(minutes=30)

    class _FakeSession:
        def query(self, *a, **kw):
            class _Q:
                def filter_by(self, **kw): return self
                def first(self): return _Run()
            return _Q()

    assert scheduler_state.due_for_retry(
        _FakeSession(), "bank_sync", target_hour=0, now=datetime.now(),
    ) is False, "a success 30 minutes ago must not be considered missed"


# --- The sweep actually runs (2026-08-15) --------------------------------

def test_scheduler_sweep_runs_without_raising(monkeypatch):
    """Regression: _scheduler_sweep called app_settings.get_effective but its
    local import block only pulled in scheduler_state, so every 20-minute
    tick died with NameError: name 'app_settings' is not defined -- silently,
    inside APScheduler, taking the whole catch-up mechanism down with it.

    No test had ever invoked the sweep; the pieces underneath it were all
    covered individually, which is exactly how a missing import in the glue
    survives a green suite. This calls the real function with the real
    imports.
    """
    import backend.main as main_module

    calls = []
    monkeypatch.setattr(main_module, "_run_bank_sync", lambda: calls.append("bank_sync"))
    monkeypatch.setattr(main_module, "_send_daily_summaries", lambda: calls.append("daily_summary"))

    main_module._scheduler_sweep()  # must not raise
