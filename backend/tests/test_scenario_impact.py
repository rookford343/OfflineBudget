"""Baseline vs scenario, in the three figures the user uses to decide.

The proposal is threaded all the way through compute_budget_snapshot rather
than only into the forecast walk. A half-aware safety margin -- forecast-based
quarter_min responding to the proposal while the flat monthly aggregates did
not -- would print a number that is wrong in a way nobody can see.
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


def test_impact_reports_a_lower_low_and_a_higher_burn_for_the_scenario(seeded):
    db, user, account, scenario = seeded
    result = scenario_service.scenario_impact(db, user, account.id, scenario.id)

    assert result["scenario"]["low"] < result["baseline"]["low"]
    assert result["scenario"]["monthly_burn"] - result["baseline"]["monthly_burn"] \
        == Decimal("57.87")


def test_the_baseline_half_matches_compute_budget_snapshot_exactly(seeded):
    """No second derivation of Safety Margin: the baseline column IS the
    snapshot the Dashboard shows, or the two screens would disagree."""
    db, user, account, scenario = seeded
    result = scenario_service.scenario_impact(db, user, account.id, scenario.id)
    snapshot = compute_budget_snapshot(db, user, account.id)

    assert result["baseline"]["safety_margin_weekly"] == snapshot.safety_margin_weekly


def test_a_proposal_changes_the_snapshots_safety_margin(seeded):
    db, user, account, scenario = seeded
    _overrides, proposal = scenario_service.resolve_scenario(db, user.id, scenario.id)

    baseline = compute_budget_snapshot(db, user, account.id)
    with_proposal = compute_budget_snapshot(db, user, account.id, proposal=proposal)

    assert with_proposal.safety_margin < baseline.safety_margin


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
        "low", "low_date", "safety_margin_weekly", "monthly_burn",
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
