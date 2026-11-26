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


def test_move_line_needs_date_and_amount():
    assert email_subject(_snap(move="80.00"), TODAY, False).startswith("Covered")


def test_no_snapshot_falls_back_to_plain_subject():
    assert email_subject(None, TODAY, False) == TAIL
