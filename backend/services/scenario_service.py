"""Turning a stored scenario into something the forecast can walk, and into
real rows when it is accepted.

Kept out of routers/scenarios.py because commit, uncommit and impact are
business logic with real failure modes worth testing without HTTP in the way.
"""
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
