"""Turning a stored scenario into something the forecast can walk, and into
real rows when it is accepted.

Kept out of routers/scenarios.py because commit, uncommit and impact are
business logic with real failure modes worth testing without HTTP in the way.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models
from backend.services.forecast_engine import ScenarioProposal


def _transient_item(p: models.ScenarioProposedItem, user_id: int) -> models.RecurringItem:
    """A RecurringItem that is never added to the session.

    is_active and include_in_forecast are forced True: _fires_on returns False
    for an inactive item, so a proposal that stored them could silently do
    nothing. A proposal that exists is by definition meant to be forecast.
    """
    return models.RecurringItem(
        id=-p.id,
        user_id=user_id,
        name=p.name,
        amount=p.amount,
        type=p.type,
        frequency=p.frequency,
        day_of_month=p.day_of_month,
        month_of_year=p.month_of_year,
        start_date=p.start_date,
        end_date=p.end_date,
        account_id=p.account_id,
        card_id=p.card_id,
        category_id=p.category_id,
        is_active=True,
        include_in_forecast=True,
    )


def _transient_expense(p: models.ScenarioProposedExpense, user_id: int) -> models.PlannedExpense:
    return models.PlannedExpense(
        id=-p.id,
        user_id=user_id,
        name=p.name,
        amount=p.amount,
        expected_date=p.expected_date,
        direction=p.direction,
        account_id=p.account_id,
        card_id=p.card_id,
        funding_account_id=p.funding_account_id,
        category_id=p.category_id,
    )


def get_scenario(db: Session, user_id: int, scenario_id: int) -> models.ForecastScenario | None:
    return db.query(models.ForecastScenario).filter(
        models.ForecastScenario.id == scenario_id,
        models.ForecastScenario.user_id == user_id,
    ).first()


def resolve_scenario(
    db: Session, user_id: int, scenario_id: int,
) -> tuple[list[dict], ScenarioProposal] | None:
    """(overrides, proposal) for build_forecast, or None if no such scenario.

    A COMMITTED scenario resolves to nothing at all. Its proposals are already
    real rows and its amount tweaks are already applied to real items, so
    resolving them again would count the same money twice on any chart that
    draws it.
    """
    scenario = get_scenario(db, user_id, scenario_id)
    if scenario is None:
        return None
    if scenario.status == "committed":
        return [], ScenarioProposal()

    overrides = [
        {"recurring_item_id": o.recurring_item_id, "amount_delta": o.amount_delta}
        for o in scenario.overrides
    ]
    proposal = ScenarioProposal(
        items=tuple(_transient_item(p, user_id) for p in scenario.proposed_items),
        expenses=tuple(_transient_expense(p, user_id) for p in scenario.proposed_expenses),
    )
    return overrides, proposal


class ScenarioAlreadyCommitted(Exception):
    pass


class ScenarioNotCommitted(Exception):
    pass


def commit_scenario(db: Session, user_id: int, scenario_id: int) -> dict:
    """Materialize a scenario into real rows, recording what it created.

    One transaction: a half-committed scenario would leave proposals whose
    committed_* links point at rows that may or may not exist, which uncommit
    cannot reason about.
    """
    scenario = get_scenario(db, user_id, scenario_id)
    if scenario is None:
        raise LookupError("Scenario not found")
    if scenario.status == "committed":
        raise ScenarioAlreadyCommitted(scenario_id)

    items_created = 0
    for p in scenario.proposed_items:
        item = models.RecurringItem(
            user_id=user_id,
            name=p.name,
            amount=p.amount,
            type=p.type,
            frequency=p.frequency,
            day_of_month=p.day_of_month,
            month_of_year=p.month_of_year,
            start_date=p.start_date,
            end_date=p.end_date,
            account_id=p.account_id,
            card_id=p.card_id,
            category_id=p.category_id,
            is_active=True,
            include_in_forecast=True,
        )
        db.add(item)
        db.flush()
        p.committed_recurring_item_id = item.id
        items_created += 1

    expenses_created = 0
    for p in scenario.proposed_expenses:
        expense = models.PlannedExpense(
            user_id=user_id,
            name=p.name,
            amount=p.amount,
            expected_date=p.expected_date,
            direction=p.direction,
            account_id=p.account_id,
            card_id=p.card_id,
            funding_account_id=p.funding_account_id,
            category_id=p.category_id,
        )
        db.add(expense)
        db.flush()
        p.committed_planned_expense_id = expense.id
        expenses_created += 1

    overrides_applied = 0
    for o in scenario.overrides:
        item = db.query(models.RecurringItem).filter(
            models.RecurringItem.id == o.recurring_item_id,
            models.RecurringItem.user_id == user_id,
        ).first()
        if item is None:
            # The item the tweak referred to is gone. Nothing to apply, and
            # nothing for uncommit to restore -- skipped rather than failing
            # the whole commit over one stale reference.
            continue
        o.committed_previous_amount = item.amount
        item.amount = item.amount + o.amount_delta
        overrides_applied += 1

    scenario.status = "committed"
    scenario.committed_at = datetime.utcnow()
    db.commit()
    return {
        "items_created": items_created,
        "expenses_created": expenses_created,
        "overrides_applied": overrides_applied,
    }


def uncommit_scenario(db: Session, user_id: int, scenario_id: int) -> dict:
    """Reverse a commit: delete the rows it created, restore the amounts it
    changed, clear the links, return the scenario to draft.

    Idempotent about rows already gone -- a row deleted by hand is skipped,
    not an error. Edits made to a created row after commit are LOST: the row
    is deleted regardless. Refusing instead would mean fingerprinting every
    created row and surfacing a refusal the user cannot resolve.
    """
    scenario = get_scenario(db, user_id, scenario_id)
    if scenario is None:
        raise LookupError("Scenario not found")
    if scenario.status != "committed":
        raise ScenarioNotCommitted(scenario_id)

    items_removed = 0
    for p in scenario.proposed_items:
        if p.committed_recurring_item_id is None:
            continue
        item = db.query(models.RecurringItem).filter(
            models.RecurringItem.id == p.committed_recurring_item_id,
            models.RecurringItem.user_id == user_id,
        ).first()
        if item is not None:
            db.delete(item)
            items_removed += 1
        p.committed_recurring_item_id = None

    expenses_removed = 0
    for p in scenario.proposed_expenses:
        if p.committed_planned_expense_id is None:
            continue
        expense = db.query(models.PlannedExpense).filter(
            models.PlannedExpense.id == p.committed_planned_expense_id,
            models.PlannedExpense.user_id == user_id,
        ).first()
        if expense is not None:
            db.delete(expense)
            expenses_removed += 1
        p.committed_planned_expense_id = None

    overrides_restored = 0
    for o in scenario.overrides:
        if o.committed_previous_amount is None:
            continue
        item = db.query(models.RecurringItem).filter(
            models.RecurringItem.id == o.recurring_item_id,
            models.RecurringItem.user_id == user_id,
        ).first()
        if item is not None:
            item.amount = o.committed_previous_amount
            overrides_restored += 1
        o.committed_previous_amount = None

    scenario.status = "draft"
    scenario.committed_at = None
    db.commit()
    return {
        "items_removed": items_removed,
        "expenses_removed": expenses_removed,
        "overrides_restored": overrides_restored,
    }
