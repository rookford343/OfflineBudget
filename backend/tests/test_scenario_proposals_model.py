"""The two proposal tables and the columns commit/uncommit need.

A proposal is deliberately NOT a real RecurringItem with a scenario_id flag:
every existing query in forecast_engine, budget_snapshot, summary_generator and
the spending routers would then have to filter `scenario_id IS NULL`, and one
missed filter leaks a hypothetical expense into the daily email and Safety
Margin. Separate tables make that failure impossible rather than unlikely.
"""
from datetime import date
from decimal import Decimal

from backend import models


def _scenario(db):
    user = models.User(username="prop", hashed_password="x", display_name="Prop")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="iPhone + AppleCare")
    db.add(scenario)
    db.commit()
    return user, account, scenario


def test_new_scenario_defaults_to_draft(db_session):
    _user, _account, scenario = _scenario(db_session)
    assert scenario.status == "draft"
    assert scenario.committed_at is None
    assert scenario.notes is None


def test_proposed_item_round_trips_every_field_the_forecast_reads(db_session):
    user, account, scenario = _scenario(db_session)
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="iPhone Trade-In",
        amount=Decimal("57.87"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=23,
        start_date=date(2026, 10, 23), end_date=date(2028, 10, 23),
        account_id=account.id,
    ))
    db_session.commit()
    db_session.refresh(scenario)

    item = scenario.proposed_items[0]
    assert item.amount == Decimal("57.87")
    assert item.end_date == date(2028, 10, 23)
    assert item.committed_recurring_item_id is None


def test_proposed_expense_round_trips(db_session):
    user, account, scenario = _scenario(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="New laptop",
        amount=Decimal("2400.00"), expected_date=date(2026, 12, 1),
        account_id=account.id,
    ))
    db_session.commit()
    db_session.refresh(scenario)

    expense = scenario.proposed_expenses[0]
    assert expense.direction == models.PlannedDirection.outflow
    assert expense.committed_planned_expense_id is None


def test_deleting_a_scenario_takes_its_proposals_with_it(db_session):
    user, account, scenario = _scenario(db_session)
    db_session.add_all([
        models.ScenarioProposedItem(
            scenario_id=scenario.id, name="AppleCare", amount=Decimal("174.13"),
            type=models.RecurringType.expense,
            frequency=models.RecurringFrequency.yearly, month_of_year=10,
            day_of_month=23, start_date=date(2026, 10, 23), account_id=account.id,
        ),
        models.ScenarioProposedExpense(
            scenario_id=scenario.id, name="Deposit", amount=Decimal("50.00"),
            expected_date=date(2026, 11, 1), account_id=account.id,
        ),
    ])
    db_session.commit()

    db_session.delete(scenario)
    db_session.commit()

    assert db_session.query(models.ScenarioProposedItem).count() == 0
    assert db_session.query(models.ScenarioProposedExpense).count() == 0


def test_override_can_record_the_amount_it_replaced(db_session):
    user, account, scenario = _scenario(db_session)
    item = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Dining",
        amount=Decimal("400.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.flush()
    override = models.ScenarioOverride(
        scenario_id=scenario.id, recurring_item_id=item.id,
        amount_delta=Decimal("-200.00"),
        committed_previous_amount=Decimal("400.00"),
    )
    db_session.add(override)
    db_session.commit()
    db_session.refresh(override)

    assert override.committed_previous_amount == Decimal("400.00")
