"""A proposed one-off expense takes the same three paths a real one does:
straight to checking, via a card's payoff, or with a funding leg out of
savings. Splicing into `planned` BEFORE build_forecast's routing loop is what
buys all three at once -- routing into planned_by_date directly would
reimplement the loop and lose funding legs silently.
"""
from datetime import date
from decimal import Decimal

from backend import models
from backend.services import scenario_service
from backend.services.forecast_engine import build_forecast


def _seed(db):
    user = models.User(username="propoff", hashed_password="x", display_name="PropOff")
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    savings = models.Account(
        user_id=user.id, name="Savings", type=models.AccountType.savings,
        current_balance=Decimal("20000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Apple Card", credit_limit=Decimal("10000.00"),
        statement_day=28, due_day=25,
    )
    db.add_all([checking, savings, card])
    db.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="One-offs")
    db.add(scenario)
    db.commit()
    return user, checking, savings, card, scenario


def _resolve(db, user, scenario):
    _overrides, proposal = scenario_service.resolve_scenario(db, user.id, scenario.id)
    return proposal


def _balance_on(entries, d: date) -> Decimal:
    return next(e.projected_balance for e in entries if e.date == d)


def test_a_plain_proposed_one_off_hits_checking_on_its_own_date(db_session):
    user, checking, _savings, _card, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="New laptop", amount=Decimal("2400.00"),
        expected_date=date(2026, 11, 10), account_id=checking.id,
    ))
    db_session.commit()

    entries = build_forecast(
        db_session, user.id, checking.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=_resolve(db_session, user, scenario),
    )

    assert _balance_on(entries, date(2026, 11, 9)) == Decimal("5000.00")
    assert _balance_on(entries, date(2026, 11, 10)) == Decimal("2600.00")


def test_a_card_routed_proposed_one_off_waits_for_the_payoff(db_session):
    """Charged 11/10 -> statement closes 11/28 -> due 12/25."""
    user, checking, _savings, card, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="AppleCare up front", amount=Decimal("199.99"),
        expected_date=date(2026, 11, 10), account_id=checking.id, card_id=card.id,
    ))
    db_session.commit()

    entries = build_forecast(
        db_session, user.id, checking.id, date(2026, 11, 1), date(2026, 12, 31),
        proposal=_resolve(db_session, user, scenario),
    )

    assert _balance_on(entries, date(2026, 11, 10)) == Decimal("5000.00")
    names = [t.name for e in entries if e.date == date(2026, 12, 25) for t in e.transactions]
    assert names == ["AppleCare up front (via Apple Card)"]
    assert _balance_on(entries, date(2026, 12, 25)) == Decimal("4800.01")


def test_a_funded_proposed_one_off_brings_its_transfer_with_it(db_session):
    """funding_account_id implies money moving INTO checking before the
    purchase and OUT of savings -- derived by build_forecast from the expense
    itself, which a proposal gets for free by joining `planned`."""
    user, checking, savings, _card, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="Funded laptop", amount=Decimal("2400.00"),
        expected_date=date(2026, 11, 10), account_id=checking.id,
        funding_account_id=savings.id,
    ))
    db_session.commit()
    proposal = _resolve(db_session, user, scenario)

    checking_entries = build_forecast(
        db_session, user.id, checking.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=proposal,
    )
    savings_entries = build_forecast(
        db_session, user.id, savings.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=proposal,
    )

    # Funding arrives and the purchase leaves on the same day (lead 0), so
    # checking nets flat while savings drops.
    assert _balance_on(checking_entries, date(2026, 11, 10)) == Decimal("5000.00")
    assert _balance_on(savings_entries, date(2026, 11, 10)) == Decimal("17600.00")


def test_a_proposed_one_off_outside_the_window_is_ignored(db_session):
    """The real query filters expected_date to the window; a proposal must use
    the same filter or a scenario forecast would diverge from what committing
    it produces."""
    user, checking, _savings, _card, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="Way off", amount=Decimal("2400.00"),
        expected_date=date(2027, 6, 1), account_id=checking.id,
    ))
    db_session.commit()

    entries = build_forecast(
        db_session, user.id, checking.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=_resolve(db_session, user, scenario),
    )

    assert all(e.projected_balance == Decimal("5000.00") for e in entries)


def test_proposed_one_offs_persist_nothing(db_session):
    user, checking, _savings, _card, scenario = _seed(db_session)
    db_session.add(models.ScenarioProposedExpense(
        scenario_id=scenario.id, name="New laptop", amount=Decimal("2400.00"),
        expected_date=date(2026, 11, 10), account_id=checking.id,
    ))
    db_session.commit()
    before = db_session.query(models.PlannedExpense).count()

    build_forecast(
        db_session, user.id, checking.id, date(2026, 11, 1), date(2026, 11, 30),
        proposal=_resolve(db_session, user, scenario),
    )

    assert db_session.query(models.PlannedExpense).count() == before
