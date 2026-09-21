"""Baseline vs scenario, in the figures Dan uses to decide.

Two independent threading paths meet here, and they cover different figures.
`_lookahead_minimum` threads the proposal into `build_forecast`'s day-by-day
walk, so `quarter_min` -- and therefore `safety_margin` -- responds to a
scenario's items. Separately, `_monthly_income`/`_monthly_expenses` thread
the proposal into the flat monthly aggregates that feed `leftover`, and
everything derived from it (`left_to_spend`, `weekly_spendable`,
`reserve_needed`). `safety_margin` does NOT read those flat aggregates --
`budget_snapshot.py` computes it as
`quarter_min - cc_budget_total + charged_so_far`, none of which derives from
`_monthly_income`/`_monthly_expenses` -- so proving `safety_margin` changes
says nothing about that second path. Both paths are threaded; both are
exercised below, separately, so each has its own coverage.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import scenarios as scenarios_router
from backend.services import scenario_service
from backend.services.budget_snapshot import compute_budget_snapshot


@pytest.fixture()
def seeded(db_session):
    user = models.User(username="impact", hashed_password="x", display_name="Impact")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    db_session.add(account)
    db_session.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="iPhone Duo")
    db_session.add(scenario)
    db_session.flush()
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="iPhone Trade-In", amount=Decimal("57.87"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 15), account_id=account.id,
    ))
    db_session.commit()
    return db_session, user, account, scenario


def test_impact_reports_a_lower_low_and_higher_commitments_for_the_scenario(seeded):
    db, user, account, scenario = seeded
    result = scenario_service.scenario_impact(db, user, account.id, scenario.id)

    assert result["scenario"]["low"] < result["baseline"]["low"]
    assert result["scenario"]["total_monthly_commitments"] \
        - result["baseline"]["total_monthly_commitments"] == Decimal("57.87")


def test_the_baseline_half_matches_compute_budget_snapshot_exactly(seeded):
    """No second derivation of any of these four figures: the baseline column
    reads the same snapshot fields the Dashboard shows for three of them, and
    the same commitments helper /recurring/breakdown reuses for the fourth --
    or the screens could silently disagree."""
    db, user, account, scenario = seeded
    result = scenario_service.scenario_impact(db, user, account.id, scenario.id)
    snapshot = compute_budget_snapshot(db, user, account.id)

    assert result["baseline"]["low"] == snapshot.lookahead_minimum
    assert result["baseline"]["low_date"] == snapshot.lookahead_minimum_date
    assert result["baseline"]["safety_margin_weekly"] == snapshot.safety_margin_weekly
    assert result["baseline"]["total_monthly_commitments"] == \
        scenario_service._total_monthly_commitments(db, user.id, [])


def test_a_proposal_changes_the_snapshots_safety_margin(seeded):
    """Exercises the quarter_min path only: `_lookahead_minimum`'s proposal
    kwarg into `build_forecast`. `safety_margin` never reads
    `_monthly_income`/`_monthly_expenses`, so this test says nothing about
    that separate flat-aggregate path -- see
    test_a_proposal_changes_the_snapshots_leftover below for that one."""
    db, user, account, scenario = seeded
    _overrides, proposal = scenario_service.resolve_scenario(db, user.id, scenario.id)

    baseline = compute_budget_snapshot(db, user, account.id)
    with_proposal = compute_budget_snapshot(db, user, account.id, proposal=proposal)

    assert with_proposal.safety_margin < baseline.safety_margin


def test_a_proposal_changes_the_snapshots_leftover(seeded):
    """Exercises the flat-aggregate path: `_monthly_expenses`'s proposal
    kwarg. `left_to_spend` derives from `leftover`, which derives from
    `_monthly_income`/`_monthly_expenses` -- the path `safety_margin` does
    not touch (see the test above). The scenario adds a $57.87/mo expense
    with no card attached, so nothing else in the formula moves and
    left_to_spend should drop by exactly that amount."""
    db, user, account, scenario = seeded
    _overrides, proposal = scenario_service.resolve_scenario(db, user.id, scenario.id)

    baseline = compute_budget_snapshot(db, user, account.id)
    with_proposal = compute_budget_snapshot(db, user, account.id, proposal=proposal)

    assert baseline.left_to_spend - with_proposal.left_to_spend == Decimal("57.87")


def test_impact_does_not_persist_the_proposal(seeded):
    db, user, account, scenario = seeded
    before = db.query(models.RecurringItem).count()
    scenario_service.scenario_impact(db, user, account.id, scenario.id)
    assert db.query(models.RecurringItem).count() == before


def test_impact_route_returns_both_columns(seeded):
    db, user, account, scenario = seeded
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    r = c.get(f"/scenarios/{scenario.id}/impact", params={"account_id": account.id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"baseline", "scenario"}
    assert set(body["baseline"]) == {
        "low", "low_date", "safety_margin_weekly", "total_monthly_commitments",
    }


def test_impact_on_an_unknown_scenario_is_404(seeded):
    db, user, account, _scenario = seeded
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    r = c.get("/scenarios/9999/impact", params={"account_id": account.id})
    assert r.status_code == 404


def test_impact_with_an_unknown_account_is_404(seeded):
    db, user, account, scenario = seeded
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    r = c.get(f"/scenarios/{scenario.id}/impact", params={"account_id": 999999})
    assert r.status_code == 404


def test_impact_with_a_foreign_account_is_404(seeded):
    """A real account that belongs to a different user must 404, not
    silently return a plausible-looking zeroed-out column."""
    db, user, account, scenario = seeded
    other = models.User(username="impact-other", hashed_password="x", display_name="Other")
    db.add(other)
    db.flush()
    other_account = models.Account(
        user_id=other.id, name="Other Checking", type=models.AccountType.checking,
        current_balance=Decimal("100.00"),
    )
    db.add(other_account)
    db.commit()

    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    r = c.get(f"/scenarios/{scenario.id}/impact", params={"account_id": other_account.id})
    assert r.status_code == 404
