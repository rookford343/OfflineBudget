"""A proposed item forecasts exactly as the same item created for real.

That parity is the whole justification for materializing proposals as
transient RecurringItem objects spliced into the lists build_forecast already
walks. The alternative -- a separate "project a proposed item" code path --
would be a second implementation of _fires_on, the weekend pull-forward and
end-date handling, and this repo has spent real time fixing bugs born of
exactly that kind of duplication.
"""
from datetime import date, timedelta
from decimal import Decimal

from backend import models
from backend.services import scenario_service
from backend.services.forecast_engine import ScenarioProposal, build_forecast


def _seed(db):
    user = models.User(username="prop2", hashed_password="x", display_name="Prop2")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    db.add(account)
    db.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="Test scenario")
    db.add(scenario)
    db.commit()
    return user, account, scenario


def _trace(entries):
    """(date, balance, [(txn name, txn amount)]) per day -- everything a chart
    or an impact figure reads, so an equal trace means an equal forecast."""
    return [
        (e.date, e.projected_balance, [(t.name, t.amount) for t in e.transactions])
        for e in entries
    ]


def test_a_proposal_forecasts_identically_to_the_real_item(db_session):
    """start_date (2026-06-01) is deliberately earlier than the forecast
    window (2026-11-01..) so the five pre-window occurrences (Jun-Oct) must be
    folded into the opening balance via build_forecast's own bridge recursion
    -- a proposal that dropped out of that recursion would seed a balance
    $225 richer than the real item's and this parity check would catch it."""
    user, account, scenario = _seed(db_session)
    fields = dict(
        name="Gym", amount=Decimal("45.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=10,
        start_date=date(2026, 6, 1), account_id=account.id,
    )
    db_session.add(models.ScenarioProposedItem(scenario_id=scenario.id, **fields))
    db_session.commit()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    with_proposal = build_forecast(
        db_session, user.id, account.id, date(2026, 11, 1), date(2027, 2, 28),
        proposal=proposal,
    )

    # Now make it real and forecast with no proposal at all.
    db_session.query(models.ScenarioProposedItem).delete()
    db_session.add(models.RecurringItem(user_id=user.id, **fields))
    db_session.commit()
    as_real = build_forecast(
        db_session, user.id, account.id, date(2026, 11, 1), date(2027, 2, 28),
    )

    assert _trace(with_proposal) == _trace(as_real)


def test_forecasting_a_proposal_persists_nothing(db_session):
    user, account, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="Gym", amount=Decimal("45.00"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=10,
        start_date=date(2026, 11, 1), account_id=account.id,
    ))
    db_session.commit()

    before_items = db_session.query(models.RecurringItem).count()
    before_planned = db_session.query(models.PlannedExpense).count()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    build_forecast(
        db_session, user.id, account.id, date(2026, 11, 1), date(2027, 2, 28),
        proposal=proposal,
    )

    assert db_session.query(models.RecurringItem).count() == before_items
    assert db_session.query(models.PlannedExpense).count() == before_planned


def test_a_proposals_end_date_stops_it(db_session):
    """A 24-month trade-in must not run forever. Occurrences are counted rather
    than date-matched because the weekend pull-forward moves a due date landing
    on a Sat/Sun back to the preceding Friday -- the count is what the end date
    governs, and it is stable regardless of which weekday each month lands on."""
    user, account, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="Trade-In", amount=Decimal("57.87"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 11, 15), end_date=date(2027, 1, 15),
        account_id=account.id,
    ))
    db_session.commit()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    entries = build_forecast(
        db_session, user.id, account.id, date(2026, 11, 1), date(2027, 3, 31),
        proposal=proposal,
    )

    hits = [e.date for e in entries for t in e.transactions if t.name == "Trade-In"]
    assert len(hits) == 3, f"Nov/Dec/Jan only, got {hits}"
    assert all(h < date(2027, 2, 1) for h in hits)


def test_a_proposals_id_cannot_collide_with_a_real_item(db_session):
    user, account, scenario = _seed(db_session)
    real = models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Real", amount=Decimal("10.00"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=5,
        start_date=date(2026, 11, 1),
    )
    db_session.add(real)
    db_session.flush()
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="Proposed", amount=Decimal("20.00"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=5,
        start_date=date(2026, 11, 1), account_id=account.id,
    ))
    db_session.commit()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    assert all(item.id < 0 for item in proposal.items)
    assert all(item.id != real.id for item in proposal.items)


def test_a_committed_scenario_resolves_to_nothing(db_session):
    """Its proposals are already real rows. Resolving them again would charge
    the same money twice on every chart that draws the scenario."""
    user, account, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="Gym", amount=Decimal("45.00"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=10,
        start_date=date(2026, 11, 1), account_id=account.id,
    ))
    scenario.status = "committed"
    db_session.commit()

    overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    assert proposal == ScenarioProposal()
    assert overrides == []


def test_resolving_another_users_scenario_returns_none(db_session):
    _user, _account, scenario = _seed(db_session)
    other = models.User(username="other", hashed_password="x", display_name="Other")
    db_session.add(other)
    db_session.commit()

    assert scenario_service.resolve_scenario(db_session, other.id, scenario.id) is None


def test_a_proposal_for_a_different_account_is_ignored(db_session):
    user, account, scenario = _seed(db_session)
    savings = models.Account(
        user_id=user.id, name="Savings", type=models.AccountType.savings,
        current_balance=Decimal("100.00"),
    )
    db_session.add(savings)
    db_session.flush()
    db_session.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="Savings-only bill", amount=Decimal("99.00"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=10,
        start_date=date(2026, 11, 1), account_id=savings.id,
    ))
    db_session.commit()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    entries = build_forecast(
        db_session, user.id, account.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=proposal,
    )

    names = [t.name for e in entries for t in e.transactions]
    assert "Savings-only bill" not in names


def test_a_proposals_buffer_transfer_fires_identically_to_the_real_item(db_session):
    """A proposal must feed the buffer-transfer dry run too, or a proposed
    draw-down that would trip a rule's action_threshold produces a different
    transaction SET than the real item it stands in for -- not merely a
    different balance. start_date == today so this exercises the dry-run
    threading independently of the opening-balance bridge recursion covered
    by test_a_proposal_forecasts_identically_to_the_real_item."""
    user, checking, scenario = _seed(db_session)
    savings = models.Account(
        user_id=user.id, name="Savings", type=models.AccountType.savings,
        current_balance=Decimal("10000.00"),
    )
    db_session.add(savings)
    db_session.flush()
    db_session.add(models.BufferTransferRule(
        user_id=user.id, from_account_id=savings.id, to_account_id=checking.id,
        action_threshold=Decimal("1000.00"), target_floor=Decimal("2000.00"),
        increment=Decimal("1000.00"), check_day=15,
    ))
    db_session.commit()

    today = date.today()
    window_end = today + timedelta(days=45)
    fields = dict(
        name="Big Draw", amount=Decimal("900.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.weekly, day_of_month=1,
        start_date=today, account_id=checking.id,
    )
    db_session.add(models.ScenarioProposedItem(scenario_id=scenario.id, **fields))
    db_session.commit()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    with_proposal = build_forecast(
        db_session, user.id, checking.id, today, window_end, proposal=proposal,
    )

    # Now make it real and forecast with no proposal at all.
    db_session.query(models.ScenarioProposedItem).delete()
    db_session.add(models.RecurringItem(user_id=user.id, **fields))
    db_session.commit()
    as_real = build_forecast(db_session, user.id, checking.id, today, window_end)

    transfer_names = [
        t.name for e in with_proposal for t in e.transactions if t.is_transfer
    ]
    assert "Transfer from Savings" in transfer_names, (
        "test setup did not actually trip the buffer rule -- strengthen the "
        "draw-down before trusting the parity assertion below"
    )
    assert _trace(with_proposal) == _trace(as_real)
