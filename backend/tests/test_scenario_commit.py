"""Committing a scenario materializes it; uncommitting reverses it.

Uncommit deletes a created row even if it was edited afterward, and those
edits are lost -- decided with Dan 2026-09-20. The alternative (refusing to
uncommit a diverged row) means fingerprinting every created row and explaining
a refusal the user cannot easily resolve. The UI names this on the confirm
dialog.
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


@pytest.fixture()
def seeded(db_session):
    user = models.User(username="commit", hashed_password="x", display_name="Commit")
    db_session.add(user)
    db_session.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    db_session.add(account)
    db_session.flush()
    dining = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Dining",
        amount=Decimal("400.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1),
    )
    db_session.add(dining)
    db_session.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="iPhone Duo")
    db_session.add(scenario)
    db_session.flush()
    db_session.add_all([
        models.ScenarioProposedItem(
            scenario_id=scenario.id, name="iPhone Trade-In", amount=Decimal("57.87"),
            type=models.RecurringType.expense,
            frequency=models.RecurringFrequency.monthly, day_of_month=23,
            start_date=date(2026, 10, 23), end_date=date(2028, 10, 23),
            account_id=account.id,
        ),
        models.ScenarioProposedExpense(
            scenario_id=scenario.id, name="Setup fee", amount=Decimal("35.00"),
            expected_date=date(2026, 10, 23), account_id=account.id,
        ),
        models.ScenarioOverride(
            scenario_id=scenario.id, recurring_item_id=dining.id,
            amount_delta=Decimal("-100.00"),
        ),
    ])
    db_session.commit()
    return db_session, user, account, scenario, dining


def test_commit_creates_real_rows_and_records_the_links(seeded):
    db, user, _account, scenario, _dining = seeded
    result = scenario_service.commit_scenario(db, user.id, scenario.id)

    assert result == {"items_created": 1, "expenses_created": 1, "overrides_applied": 1}

    created = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).one()
    assert created.end_date == date(2028, 10, 23)
    assert created.is_active is True

    proposal = db.query(models.ScenarioProposedItem).one()
    assert proposal.committed_recurring_item_id == created.id

    db.refresh(scenario)
    assert scenario.status == "committed"
    assert scenario.committed_at is not None


def test_commit_applies_an_amount_tweak_and_remembers_the_old_amount(seeded):
    db, user, _account, scenario, dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)

    db.refresh(dining)
    assert dining.amount == Decimal("300.00")
    override = db.query(models.ScenarioOverride).one()
    assert override.committed_previous_amount == Decimal("400.00")


def test_committing_twice_is_refused(seeded):
    db, user, _account, scenario, _dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)

    with pytest.raises(scenario_service.ScenarioAlreadyCommitted):
        scenario_service.commit_scenario(db, user.id, scenario.id)

    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).count() == 1


def test_uncommit_removes_exactly_what_it_created(seeded):
    db, user, _account, scenario, dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)

    result = scenario_service.uncommit_scenario(db, user.id, scenario.id)

    assert result == {"items_removed": 1, "expenses_removed": 1, "overrides_restored": 1}
    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).count() == 0
    assert db.query(models.PlannedExpense).count() == 0
    # The pre-existing item survives, restored to its original amount.
    db.refresh(dining)
    assert dining.amount == Decimal("400.00")
    proposal = db.query(models.ScenarioProposedItem).one()
    assert proposal.committed_recurring_item_id is None
    db.refresh(scenario)
    assert scenario.status == "draft"
    assert scenario.committed_at is None


def test_uncommit_tolerates_a_row_already_deleted_by_hand(seeded):
    db, user, _account, scenario, _dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)
    created = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).one()
    db.delete(created)
    db.commit()

    result = scenario_service.uncommit_scenario(db, user.id, scenario.id)

    assert result["items_removed"] == 0
    db.refresh(scenario)
    assert scenario.status == "draft"


def test_uncommit_discards_later_edits_to_a_created_row(seeded):
    """Named behavior, not an accident: the row goes even though it changed."""
    db, user, _account, scenario, _dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)
    created = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).one()
    created.amount = Decimal("61.00")
    db.commit()

    scenario_service.uncommit_scenario(db, user.id, scenario.id)

    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).count() == 0


def test_uncommitting_a_draft_is_refused(seeded):
    db, user, _account, scenario, _dining = seeded
    with pytest.raises(scenario_service.ScenarioNotCommitted):
        scenario_service.uncommit_scenario(db, user.id, scenario.id)


def test_commit_route_returns_409_on_a_second_call(seeded):
    db, user, _account, scenario, _dining = seeded
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    c = TestClient(app)

    assert c.post(f"/scenarios/{scenario.id}/commit").status_code == 200
    assert c.post(f"/scenarios/{scenario.id}/commit").status_code == 409
    assert c.post(f"/scenarios/{scenario.id}/uncommit").status_code == 200
    assert c.post(f"/scenarios/{scenario.id}/uncommit").status_code == 409
