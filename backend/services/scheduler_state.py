"""Tracks whether each scheduled job (daily summary email, bank sync)
actually succeeded today, independent of whether its APScheduler trigger
fired -- see models.SchedulerRun's docstring for why both matter separately.

Two distinct ways a scheduled run goes missing on a laptop that sleeps
overnight, each needing its own fix:

  1. The process is suspended straight through the trigger time and only
     resumes later. APScheduler's own `misfire_grace_time` handles this --
     on resume it compares wall-clock time against the missed fire time and,
     if within the grace window, fires the job immediately. Configured on
     the jobs themselves in main.py.
  2. The trigger DOES fire on time (the process was running) but the job
     fails -- most commonly no network yet in the few minutes right after a
     scheduled wake. misfire_grace_time can't help here; nothing was missed
     from APScheduler's point of view. This module's `due_for_retry` is what
     a periodic sweep (main.py's `_scheduler_sweep`) consults to notice "the
     job hasn't succeeded today" and retry.
"""
from __future__ import annotations
import logging
from datetime import date, datetime
from sqlalchemy.orm import Session
from backend import models

logger = logging.getLogger(__name__)


def _write(db: Session, job_name: str, mutate) -> None:
    """Every record_* call goes through here so a failure to persist status
    (a locked SQLite file, a session that doesn't support writes) can never
    take down the job it's only supposed to be observing -- this is pure
    visibility, not something the actual sync/email logic depends on."""
    try:
        run = db.query(models.SchedulerRun).filter_by(job_name=job_name).first()
        if not run:
            run = models.SchedulerRun(job_name=job_name)
            db.add(run)
        mutate(run)
        db.commit()
    except Exception:
        logger.warning("scheduler_state write failed for %s", job_name, exc_info=True)


def record_attempt(db: Session, job_name: str) -> None:
    _write(db, job_name, lambda run: setattr(run, "last_attempt_at", datetime.now()))


def record_success(db: Session, job_name: str) -> None:
    def mutate(run):
        run.last_success_at = datetime.now()
        run.last_error = None
    _write(db, job_name, mutate)


def record_failure(db: Session, job_name: str, error: str) -> None:
    # Truncated -- this is a status line for a Settings card, not a log.
    _write(db, job_name, lambda run: setattr(run, "last_error", error[:500]))


def due_for_retry(db: Session, job_name: str, *, target_hour: int, now: datetime | None = None) -> bool:
    """True when this job has not succeeded today AND today's scheduled hour
    has already passed -- the condition the sweep retries on.

    Deliberately does not also require a prior attempt: a job whose trigger
    never fired at all (process asleep past misfire_grace_time's window, or
    the app simply wasn't running yet) looks identical here to one that fired
    and failed -- both need the same retry, and both are equally "missed"
    from Dan's perspective."""
    # Local time, matching APScheduler's own default: main.py never passes a
    # timezone to BackgroundScheduler(), so its cron `hour=` fields (and this
    # function's target_hour) are already the system's local hour -- Dan's
    # Mac, Eastern. Using UTC here would misalign both the hour comparison
    # and the date() comparison against local wall-clock reality by the UTC
    # offset.
    now = now or datetime.now()
    if now.hour < target_hour:
        return False
    try:
        run = db.query(models.SchedulerRun).filter_by(job_name=job_name).first()
    except Exception:
        logger.warning("scheduler_state read failed for %s", job_name, exc_info=True)
        return False
    if not run or not run.last_success_at:
        return True
    return run.last_success_at.date() < date.today()
