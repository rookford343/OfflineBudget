"""Turning a stored scenario into something the forecast can walk, and into
real rows when it is accepted.

Kept out of routers/scenarios.py because commit, uncommit and impact are
business logic with real failure modes worth testing without HTTP in the way.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import update
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


class ScenarioUncommitBlocked(Exception):
    """Another scenario's amount tweak still targets a row this scenario
    created. Deleting that row would violate the FK constraint on
    ScenarioOverride.recurring_item_id (nullable=False, no ondelete) and crash
    mid-uncommit, stranding this scenario as committed forever -- so it is
    detected and refused before the first delete instead."""

    def __init__(self, blocking_scenario_name: str, recurring_item_id: int):
        self.blocking_scenario_name = blocking_scenario_name
        self.recurring_item_id = recurring_item_id
        super().__init__(
            f"recurring item {recurring_item_id} still has a tweak from scenario "
            f"{blocking_scenario_name!r}"
        )


class ScenarioCommitConflict(Exception):
    """A different, already-committed scenario already tweaked this item.
    Stacking a second tweak on top would leave only room to remember one
    committed_previous_amount, permanently losing the true original amount
    the moment both scenarios were uncommitted in sequence."""

    def __init__(self, conflicting_scenario_name: str, item_name: str, recurring_item_id: int):
        self.conflicting_scenario_name = conflicting_scenario_name
        self.item_name = item_name
        self.recurring_item_id = recurring_item_id
        super().__init__(
            f"item {item_name!r} (id {recurring_item_id}) is already tweaked by "
            f"committed scenario {conflicting_scenario_name!r}"
        )


class ScenarioAccountNotOwned(Exception):
    def __init__(self, account_id: int):
        self.account_id = account_id
        super().__init__(f"account {account_id} is not owned by this user")


def _assert_account_owned(db: Session, user_id: int, account_id: int | None) -> None:
    """Mirrors routers/recurring.py's _assert_account_owned: commit creates
    real RecurringItem/PlannedExpense rows from proposal data that was never
    itself validated against the committing user's accounts."""
    if account_id is None:
        return
    owned = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user_id,
    ).first()
    if owned is None:
        raise ScenarioAccountNotOwned(account_id)


def commit_scenario(db: Session, user_id: int, scenario_id: int) -> dict:
    """Materialize a scenario into real rows, recording what it created.

    One transaction: a half-committed scenario would leave proposals whose
    committed_* links point at rows that may or may not exist, which uncommit
    cannot reason about. Every guard below is checked in full before any row
    is created or mutated, so a refusal never leaves partial work behind.
    """
    scenario = get_scenario(db, user_id, scenario_id)
    if scenario is None:
        raise LookupError("Scenario not found")

    for p in scenario.proposed_items:
        _assert_account_owned(db, user_id, p.account_id)
    for p in scenario.proposed_expenses:
        _assert_account_owned(db, user_id, p.account_id)

    for o in scenario.overrides:
        conflict = (
            db.query(models.ScenarioOverride)
            .join(models.ScenarioOverride.scenario)
            .filter(
                models.ScenarioOverride.recurring_item_id == o.recurring_item_id,
                models.ScenarioOverride.scenario_id != scenario.id,
                models.ForecastScenario.status == "committed",
                models.ScenarioOverride.committed_previous_amount.isnot(None),
            )
            .first()
        )
        if conflict is not None:
            item = db.query(models.RecurringItem).filter(
                models.RecurringItem.id == o.recurring_item_id,
            ).first()
            raise ScenarioCommitConflict(
                conflicting_scenario_name=conflict.scenario.name,
                item_name=item.name if item is not None else f"item {o.recurring_item_id}",
                recurring_item_id=o.recurring_item_id,
            )

    # The write itself is the concurrency guard, not a prior read: two
    # requests can both read status=="draft" before either writes, so the
    # authoritative check is this UPDATE's rowcount. Only one request's
    # conditional UPDATE can ever flip draft -> committed; the other affects
    # zero rows and is refused before it creates anything.
    now = datetime.utcnow()
    result = db.execute(
        update(models.ForecastScenario)
        .where(
            models.ForecastScenario.id == scenario_id,
            models.ForecastScenario.status == "draft",
        )
        .values(status="committed", committed_at=now)
    )
    if result.rowcount == 0:
        db.rollback()
        raise ScenarioAlreadyCommitted(scenario_id)
    scenario.status = "committed"
    scenario.committed_at = now

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

    One case IS refused, up front, before any delete: if another scenario's
    amount tweak still points at an item this scenario created, deleting that
    item would violate the FK constraint on
    ScenarioOverride.recurring_item_id and crash mid-uncommit, stranding this
    scenario as committed forever. That is checked in one query covering
    every row this scenario created, before the first delete, so the refusal
    is atomic and partial work is impossible.
    """
    scenario = get_scenario(db, user_id, scenario_id)
    if scenario is None:
        raise LookupError("Scenario not found")
    if scenario.status != "committed":
        raise ScenarioNotCommitted(scenario_id)

    committed_item_ids = [
        p.committed_recurring_item_id
        for p in scenario.proposed_items
        if p.committed_recurring_item_id is not None
    ]
    if committed_item_ids:
        blocking = (
            db.query(models.ScenarioOverride)
            .filter(
                models.ScenarioOverride.recurring_item_id.in_(committed_item_ids),
                models.ScenarioOverride.scenario_id != scenario.id,
            )
            .order_by(models.ScenarioOverride.id.asc())
            .first()
        )
        if blocking is not None:
            raise ScenarioUncommitBlocked(
                blocking_scenario_name=blocking.scenario.name,
                recurring_item_id=blocking.recurring_item_id,
            )

    # Clear each back-link and flush it BEFORE deleting the row it points at.
    # committed_recurring_item_id/committed_planned_expense_id are plain FK
    # columns with no relationship() mapping, so the ORM's unit-of-work has no
    # dependency information telling it the UPDATE must precede the DELETE --
    # left to its own ordering, it can (and did) emit the DELETE first and hit
    # the same FK constraint C1 refuses for the ScenarioOverride case.
    items_removed = 0
    for p in scenario.proposed_items:
        if p.committed_recurring_item_id is None:
            continue
        item_id = p.committed_recurring_item_id
        p.committed_recurring_item_id = None
        db.flush()
        item = db.query(models.RecurringItem).filter(
            models.RecurringItem.id == item_id,
            models.RecurringItem.user_id == user_id,
        ).first()
        if item is not None:
            db.delete(item)
            items_removed += 1

    expenses_removed = 0
    for p in scenario.proposed_expenses:
        if p.committed_planned_expense_id is None:
            continue
        expense_id = p.committed_planned_expense_id
        p.committed_planned_expense_id = None
        db.flush()
        expense = db.query(models.PlannedExpense).filter(
            models.PlannedExpense.id == expense_id,
            models.PlannedExpense.user_id == user_id,
        ).first()
        if expense is not None:
            db.delete(expense)
            expenses_removed += 1

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
