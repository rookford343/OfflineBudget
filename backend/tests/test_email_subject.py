"""The daily email subject leads with the answer and carries no amounts."""
import re
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.services.summary_generator import email_subject

TODAY = date(2026, 11, 26)
TAIL = "Daily Budget Summary — November 26, 2026"


def _snap(pull="0.00", status="ok", move="0.00", nm_date=None):
    return SimpleNamespace(
        savings_pull_needed=Decimal(pull), lookahead_status=status,
        move_to_checking_needed=Decimal(move), next_month_minimum_date=nm_date,
    )


CASES = [
    ("covered", _snap(), "Covered this week"),
    ("pull", _snap(pull="123.45", status="danger"), "Action needed: pull from savings"),
    ("warning", _snap(status="warning"), "Heads up: low point ahead"),
    ("danger", _snap(status="danger"), "Heads up: low point ahead"),
    ("move", _snap(move="80.00", nm_date=date(2026, 12, 9)), "Heads up: low point ahead"),
]


@pytest.mark.parametrize("weekly", [False, True])
@pytest.mark.parametrize("name,snap,lead", CASES)
def test_subject_states(name, snap, lead, weekly):
    s = email_subject(snap, TODAY, weekly)
    assert s == f"{lead} · {TAIL}" + (" + Weekly Digest" if weekly else "")
    stripped = re.sub(r"[A-Z][a-z]+ \d{1,2}, \d{4}", "", s)
    assert "$" not in stripped and not re.search(r"\d", stripped)


def test_pull_needed_wins_even_when_lookahead_status_is_ok():
    assert email_subject(_snap(pull="10.00", status="ok"), TODAY, False) == f"Action needed: pull from savings · {TAIL}"


def test_move_line_needs_date_and_amount():
    assert email_subject(_snap(move="80.00"), TODAY, False).startswith("Covered")


def test_no_snapshot_falls_back_to_plain_subject():
    assert email_subject(None, TODAY, False) == TAIL


def test_settings_send_now_path_uses_the_same_subject(db_session):
    """The Settings "send now" route builds its subject from email_subject over
    the body's own snapshot, exactly like the scheduled send."""
    from unittest.mock import patch
    from backend.routers import settings as settings_router
    from backend.tests.test_summary_generator_next_month_low import _blank_snapshot, _user_and_checking

    user = _user_and_checking(db_session, "sendnow")
    user.email = "reader@example.com"
    db_session.commit()
    sent = []

    def _capture(db, recipient, subject, html, text):
        sent.append(subject)
        return True, None

    snap = _blank_snapshot(savings_pull_needed=Decimal("250.00"))
    with patch("backend.services.summary_generator.compute_budget_snapshot", return_value=snap), \
         patch("backend.services.scheduler_state.succeeded_today", return_value=True), \
         patch.object(settings_router.app_settings, "get_effective", return_value="smtp.example.com"), \
         patch.object(settings_router.app_settings, "get_recipients", return_value=["reader@example.com"]), \
         patch("backend.services.email_service.send_email_via", _capture):
        result = settings_router.run_daily_summary_now(to_self_only=True, include_digest=False, db=db_session, user=user)
    assert sent and sent[0].startswith("Action needed: pull from savings · Daily Budget Summary")
    assert result["subject"] == sent[0]
    assert "$" not in result["subject"]
