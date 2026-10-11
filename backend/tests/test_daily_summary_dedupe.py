"""The daily email went out twice on 2026-10-11, about ten minutes apart.

The 20-minute sweep's retry check compared only the HOUR: once 7:00 passed
and the morning sync released its lock, a sweep tick at about 7:05 saw "no
email yet today" and sent it, before its 7:15 slot. The 7:15 cron trigger
then sent it again, because the scheduled path never asked whether today's
report had already gone out.
"""
from datetime import datetime
from unittest.mock import patch

import pytest

import backend.main as main
from backend.services import scheduler_state


@pytest.mark.parametrize("now,expected", [
    pytest.param(datetime(2026, 10, 11, 7, 5), False, id="after_the_hour_before_the_minute"),
    pytest.param(datetime(2026, 10, 11, 7, 15), True, id="at_the_scheduled_minute"),
    pytest.param(datetime(2026, 10, 11, 9, 2), True, id="later_hour_any_minute"),
])
def test_due_for_retry__respects_the_scheduled_minute(db_session, now, expected):
    assert scheduler_state.due_for_retry(
        db_session, "daily_summary", target_hour=7, target_minute=15, now=now,
    ) is expected


def test_sweep__checks_the_daily_summary_against_its_minute(monkeypatch, db_session):
    monkeypatch.setattr("backend.database.SessionLocal", lambda: db_session)
    calls = []

    def _spy(db, job_name, **kw):
        calls.append((job_name, kw))
        return False

    with patch.object(scheduler_state, "due_for_retry", side_effect=_spy), \
         patch("backend.services.forecast_baseline.ensure_baselines_for_all"):
        main._scheduler_sweep()
    summary = dict(calls)["daily_summary"]
    assert summary["target_minute"] == main._DAILY_SUMMARY_MINUTE


@pytest.mark.parametrize("already_sent,expect_send", [
    pytest.param(False, True, id="control_first_send_of_the_day_goes_out"),
    pytest.param(True, False, id="second_trigger_same_day_is_skipped"),
])
def test_scheduled_send__at_most_once_a_day(monkeypatch, db_session, already_sent, expect_send):
    from decimal import Decimal
    from backend import models
    user = models.User(username="mailer", hashed_password="x", display_name="M", email="m@example.com")
    db_session.add(user)
    db_session.flush()
    db_session.add(models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                                  current_balance=Decimal("100")))
    db_session.commit()
    scheduler_state.record_success(db_session, "bank_sync")
    if already_sent:
        scheduler_state.record_success(db_session, "daily_summary")
    monkeypatch.setattr("backend.database.SessionLocal", lambda: db_session)
    with patch.object(main, "_run_bank_sync"), \
         patch("backend.services.summary_generator.generate_daily_summary", return_value=("<p>x</p>", "x")), \
         patch("backend.services.email_service.send_email_via", return_value=(True, None)) as send:
        main._send_daily_summaries()
    assert send.called is expect_send
