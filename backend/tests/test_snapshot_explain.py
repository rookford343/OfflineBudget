from datetime import date
from unittest.mock import patch
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.explain import replay, children_consistent
from backend.tests.test_budget_snapshot import _seed_spreadsheet_scenario, _fake_quarter_min

FIELD = {
    "left_to_spend": "left_to_spend",
    "spendable_week": "left_to_spend_weekly",
    "spendable_today": "spendable_today",
    "safety_margin": "safety_margin",
    "safety_margin_week": "safety_margin_weekly",
    "lookahead_minimum": "lookahead_minimum",
}


def _snapshot(db, as_of):
    user, checking, _card = _seed_spreadsheet_scenario(db)
    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("5120.66")):
        return compute_budget_snapshot(db, user, checking.id, as_of=as_of)


def test_every_explanation_replays_to_its_displayed_value(db_session):
    snap = _snapshot(db_session, date(2026, 8, 7))
    assert set(snap.explain) == set(FIELD)
    for key, field in FIELD.items():
        ex = snap.explain[key]
        shown = getattr(snap, field)
        assert ex.result == shown, key
        assert replay(ex) == shown, key
        assert children_consistent(ex), key


def test_left_to_spend_steps(db_session):
    snap = _snapshot(db_session, date(2026, 8, 7))
    ex = snap.explain["left_to_spend"]
    assert [r.op for r in ex.rows] == ["start", "subtract", "add", "result"]
    assert ex.rows[0].amount == snap.leftover
    assert len(ex.rows[0].children) == 4          # income, bills, savings, groceries
    assert len(ex.rows[1].children) >= 1          # one per active card


def test_last_week_of_month_is_a_single_step(db_session):
    snap = _snapshot(db_session, date(2026, 8, 27))   # 5 days remain
    ex = snap.explain["spendable_week"]
    assert [r.op for r in ex.rows] == ["start", "result"]
    assert replay(ex) == snap.left_to_spend_weekly == snap.left_to_spend


def test_safety_margin_starts_at_the_lowest_point(db_session):
    snap = _snapshot(db_session, date(2026, 8, 7))
    ex = snap.explain["safety_margin"]
    assert ex.rows[0].amount == snap.lookahead_minimum
    assert [r.op for r in ex.rows] == ["start", "subtract", "add", "result"]
