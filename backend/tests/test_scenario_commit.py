"""Committing a scenario materializes it; uncommitting reverses it.

Uncommit deletes a created row even if it was edited afterward, and those
edits are lost -- decided with the user 2026-09-20. The alternative (refusing to
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
    assert db.query(models.PlannedExpense).filter(
        models.PlannedExpense.name == "Setup fee"
    ).count() == 1


def test_uncommit_removes_exactly_what_it_created(seeded):
    db, user, account, scenario, dining = seeded
    # A pre-existing item and expense that deliberately share the proposal's
    # name, amount and date. Proves uncommit deletes by the stored
    # committed_* link, not by matching name/shape -- a same-named,
    # same-amount, same-date survivor exists throughout.
    preexisting_item = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="iPhone Trade-In",
        amount=Decimal("57.87"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=23,
        start_date=date(2026, 10, 23), end_date=date(2028, 10, 23),
    )
    preexisting_expense = models.PlannedExpense(
        user_id=user.id, account_id=account.id, name="Setup fee",
        amount=Decimal("35.00"), expected_date=date(2026, 10, 23),
    )
    db.add_all([preexisting_item, preexisting_expense])
    db.commit()

    scenario_service.commit_scenario(db, user.id, scenario.id)
    result = scenario_service.uncommit_scenario(db, user.id, scenario.id)

    assert result == {"items_removed": 1, "expenses_removed": 1, "overrides_restored": 1}
    remaining_items = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).all()
    assert [i.id for i in remaining_items] == [preexisting_item.id]
    remaining_expenses = db.query(models.PlannedExpense).filter(
        models.PlannedExpense.name == "Setup fee"
    ).all()
    assert [e.id for e in remaining_expenses] == [preexisting_expense.id]
    # The pre-existing item survives, restored to its original amount.
    db.refresh(dining)
    assert dining.amount == Decimal("400.00")
    proposal = db.query(models.ScenarioProposedItem).one()
    assert proposal.committed_recurring_item_id is None
    db.refresh(scenario)
    assert scenario.status == "draft"
    assert scenario.committed_at is None


def test_uncommit_tolerates_a_proposal_whose_link_is_already_cleared(seeded):
    """Covers ONLY the case where committed_recurring_item_id is already None
    before uncommit_scenario runs -- e.g. a previous uncommit already cleared
    it, or the database was edited externally. uncommit_scenario's per-item
    loop short-circuits on that null link, so it never even looks up a row.

    This does NOT test (and cannot honestly claim to test) a link that still
    points at a since-deleted row: under enforced foreign keys that state
    can't be constructed through normal operation at all, since a live link
    blocks the row's deletion outright (see the C1 guard). See the comment at
    the `if item is not None` check in uncommit_scenario for that branch.
    """
    db, user, _account, scenario, _dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)
    proposal = db.query(models.ScenarioProposedItem).one()
    proposal.committed_recurring_item_id = None
    db.commit()

    result = scenario_service.uncommit_scenario(db, user.id, scenario.id)

    assert result["items_removed"] == 0
    db.refresh(scenario)
    assert scenario.status == "draft"
    # uncommit had no live link to this row, so it never touched it.
    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).count() == 1


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


def _client(db, user):
    app = FastAPI()
    app.include_router(scenarios_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_uncommit_blocked_by_another_scenarios_override(seeded):
    """C1: a second scenario's amount tweak on an item the first scenario
    created would make the delete violate a foreign key. Refused instead."""
    db, user, _account, scenario, _dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)
    created = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).one()

    blocker = models.ForecastScenario(user_id=user.id, name="Dining cuts")
    db.add(blocker)
    db.flush()
    db.add(models.ScenarioOverride(
        scenario_id=blocker.id, recurring_item_id=created.id,
        amount_delta=Decimal("-5.00"),
    ))
    db.commit()

    response = _client(db, user).post(f"/scenarios/{scenario.id}/uncommit")

    assert response.status_code == 409
    assert "Dining cuts" in response.json()["detail"]
    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.id == created.id
    ).count() == 1
    db.refresh(scenario)
    assert scenario.status == "committed"


def test_commit_refused_on_a_stacked_tweak(seeded):
    """I2: a different, already-committed scenario has already tweaked this
    same item. Stacking a second tweak would make the true original amount
    unrecoverable once both were later uncommitted."""
    db, user, _account, scenario, dining = seeded
    first = models.ForecastScenario(user_id=user.id, name="First cut")
    db.add(first)
    db.flush()
    db.add(models.ScenarioOverride(
        scenario_id=first.id, recurring_item_id=dining.id,
        amount_delta=Decimal("-100.00"),
    ))
    db.commit()
    scenario_service.commit_scenario(db, user.id, first.id)
    db.refresh(dining)
    assert dining.amount == Decimal("300.00")

    response = _client(db, user).post(f"/scenarios/{scenario.id}/commit")

    assert response.status_code == 409
    assert "First cut" in response.json()["detail"]
    db.refresh(dining)
    assert dining.amount == Decimal("300.00")  # untouched by the refused commit
    db.refresh(scenario)
    assert scenario.status == "draft"
    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).count() == 0


def test_delete_refused_on_a_committed_scenario(seeded):
    """I4: deleting a committed scenario (or one of its proposals) would
    orphan the real rows it created and destroy committed_previous_amount."""
    db, user, _account, scenario, _dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)
    created = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).one()
    proposed_item = db.query(models.ScenarioProposedItem).one()
    proposed_expense = db.query(models.ScenarioProposedExpense).one()
    c = _client(db, user)

    assert c.delete(f"/scenarios/{scenario.id}").status_code == 409
    assert c.delete(f"/scenarios/{scenario.id}/items/{proposed_item.id}").status_code == 409
    assert c.delete(f"/scenarios/{scenario.id}/expenses/{proposed_expense.id}").status_code == 409

    db.refresh(scenario)
    assert scenario.status == "committed"
    assert db.query(models.ForecastScenario).filter(
        models.ForecastScenario.id == scenario.id
    ).count() == 1
    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.id == created.id
    ).count() == 1
    assert db.query(models.ScenarioProposedItem).count() == 1
    assert db.query(models.ScenarioProposedExpense).count() == 1


def test_commit_refused_when_proposal_account_not_owned(seeded):
    """M7: a proposal's account_id must belong to the committing user, same
    as POST /recurring enforces -- otherwise commit creates a real row with a
    dangling cross-user reference."""
    db, user, _account, scenario, _dining = seeded
    other_user = models.User(username="intruder", hashed_password="x", display_name="Intruder")
    db.add(other_user)
    db.flush()
    other_account = models.Account(
        user_id=other_user.id, name="Their checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(other_account)
    db.flush()
    proposed_item = db.query(models.ScenarioProposedItem).one()
    proposed_item.account_id = other_account.id
    db.commit()

    with pytest.raises(scenario_service.ScenarioAccountNotOwned):
        scenario_service.commit_scenario(db, user.id, scenario.id)

    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).count() == 0
    db.refresh(scenario)
    assert scenario.status == "draft"


def test_uncommit_blocked_by_its_own_override(seeded):
    """N1: a scenario tweaking an item IT created reproduces the identical FK
    crash C1 exists to prevent -- the blocking query must not exclude this
    scenario's own overrides. Built directly at the ORM level since round 4's
    create_override guard now refuses to build this state via the API once
    the scenario is committed (see test_create_override_refused_on_a_committed_scenario);
    this test proves uncommit's own guard remains the backstop for the state
    if it's ever reached some other way (a database predating the guard, or
    edited directly)."""
    db, user, _account, scenario, _dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)
    created = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).one()

    db.add(models.ScenarioOverride(
        scenario_id=scenario.id, recurring_item_id=created.id,
        amount_delta=Decimal("-5.00"),
    ))
    db.commit()

    response = _client(db, user).post(f"/scenarios/{scenario.id}/uncommit")

    assert response.status_code == 409
    assert "an item it created" in response.json()["detail"]
    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.id == created.id
    ).count() == 1
    db.refresh(scenario)
    assert scenario.status == "committed"


def test_delete_override_refused_on_a_committed_scenario(seeded):
    """N2: deleting a committed override destroys committed_previous_amount,
    permanently stranding the real item at its tweaked amount with nothing
    left for uncommit to restore it from -- the one delete route I4 missed."""
    db, user, _account, scenario, dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)
    override = db.query(models.ScenarioOverride).one()
    assert override.committed_previous_amount == Decimal("400.00")

    response = _client(db, user).delete(f"/scenarios/{scenario.id}/overrides/{override.id}")

    assert response.status_code == 409
    db.refresh(override)
    assert override.committed_previous_amount == Decimal("400.00")
    assert db.query(models.ScenarioOverride).count() == 1
    db.refresh(dining)
    assert dining.amount == Decimal("300.00")
    db.refresh(scenario)
    assert scenario.status == "committed"


def test_commit_refused_on_two_overrides_targeting_the_same_item(seeded):
    """N3 (commit-side): each commit would record the PREVIOUS override's
    already-tweaked value as committed_previous_amount, permanently losing
    the true original amount. Outside I2's guard by construction, since I2
    only ever compares against OTHER scenarios. Built directly at the ORM
    level since create_override now refuses to build this state via the API
    -- commit must still catch it defensively."""
    db, user, _account, scenario, dining = seeded
    db.add(models.ScenarioOverride(
        scenario_id=scenario.id, recurring_item_id=dining.id,
        amount_delta=Decimal("-20.00"),
    ))
    db.commit()

    with pytest.raises(scenario_service.ScenarioDuplicateOverride):
        scenario_service.commit_scenario(db, user.id, scenario.id)

    db.refresh(dining)
    assert dining.amount == Decimal("400.00")
    db.refresh(scenario)
    assert scenario.status == "draft"
    assert db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).count() == 0


def test_create_override_refused_for_a_duplicate_item_within_one_scenario(seeded):
    """N3 (create-side): refusing at creation time means the bad state (two
    overrides on the same item in one scenario) can never be built through
    the API in the first place."""
    db, user, _account, scenario, dining = seeded

    response = _client(db, user).post(
        f"/scenarios/{scenario.id}/overrides",
        json={"recurring_item_id": dining.id, "amount_delta": "-20.00"},
    )

    assert response.status_code == 409
    assert db.query(models.ScenarioOverride).filter(
        models.ScenarioOverride.scenario_id == scenario.id,
        models.ScenarioOverride.recurring_item_id == dining.id,
    ).count() == 1


def test_create_override_refused_on_a_committed_scenario(seeded):
    """Round 4 fix: an override on an already-committed scenario is inert --
    resolve_scenario returns no overrides at all for a committed scenario --
    and if its target happens to be an item this same scenario created, it
    also permanently traps the scenario as 'committed' (see the third test
    below). Refused at the root instead of letting either happen."""
    db, user, _account, scenario, dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)

    response = _client(db, user).post(
        f"/scenarios/{scenario.id}/overrides",
        json={"recurring_item_id": dining.id, "amount_delta": "-20.00"},
    )

    assert response.status_code == 409
    assert "uncommit" in response.json()["detail"].lower()
    # No new override row was created -- only the one the fixture seeded.
    assert db.query(models.ScenarioOverride).count() == 1


def test_create_override_still_works_on_a_draft_scenario(seeded):
    """The guard must not touch the normal path: a draft scenario can still
    take a new amount tweak on a different item."""
    db, user, account, scenario, _dining = seeded
    other_item = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Streaming",
        amount=Decimal("15.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=5,
        start_date=date(2026, 1, 5),
    )
    db.add(other_item)
    db.commit()

    response = _client(db, user).post(
        f"/scenarios/{scenario.id}/overrides",
        json={"recurring_item_id": other_item.id, "amount_delta": "-5.00"},
    )

    assert response.status_code == 200
    assert db.query(models.ScenarioOverride).filter(
        models.ScenarioOverride.scenario_id == scenario.id,
        models.ScenarioOverride.recurring_item_id == other_item.id,
    ).count() == 1


def test_dead_end_is_closed_commit_then_blocked_override_then_uncommit_succeeds(seeded):
    """The one that matters: proves the trap described in the brief is gone
    end to end, not just that the new guard fires in isolation. Before this
    fix: commit, then POST an override on the item the scenario itself just
    created succeeded, and from there NO route could ever return the scenario
    to draft -- uncommit refused (an override targets a created item),
    deleting that override refused (scenario is committed), deleting the
    scenario refused (scenario is committed). After this fix: the POST itself
    is refused, so the trap is never built, and uncommit succeeds normally."""
    db, user, _account, scenario, dining = seeded
    scenario_service.commit_scenario(db, user.id, scenario.id)
    created = db.query(models.RecurringItem).filter(
        models.RecurringItem.name == "iPhone Trade-In"
    ).one()
    c = _client(db, user)

    blocked = c.post(
        f"/scenarios/{scenario.id}/overrides",
        json={"recurring_item_id": created.id, "amount_delta": "-5.00"},
    )
    assert blocked.status_code == 409

    response = c.post(f"/scenarios/{scenario.id}/uncommit")

    assert response.status_code == 200
    db.refresh(scenario)
    assert scenario.status == "draft"
    assert scenario.committed_at is None
