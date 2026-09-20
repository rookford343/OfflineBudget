"""A card-routed proposal hits the card, not checking.

build_forecast deliberately excludes card-linked expenses from the checking
walk (forecast_engine.py:296-306 -- "CC charges (expense + card_id) hit the
card, not the checking account"). They reach checking through the card's
statement payoff instead. A proposal must take the same path, or a scenario
would show the user a charge leaving checking a month before it really does.

Card shape here is the user's real Chase: closes the 28th, due the 25th of the
FOLLOWING month. So a charge on 10/23 belongs to the statement closing 10/28
and is not paid off until 11/25.
"""
from datetime import date
from decimal import Decimal

from backend import models
from backend.services import scenario_service
from backend.services.forecast_engine import build_forecast


def _seed(db, *, monthly_spend_estimate=None):
    user = models.User(username="propcard", hashed_password="x", display_name="PropCard")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Apple Card", credit_limit=Decimal("10000.00"),
        statement_day=28, due_day=25,
        monthly_spend_estimate=monthly_spend_estimate,
    )
    db.add_all([account, card])
    db.flush()
    scenario = models.ForecastScenario(user_id=user.id, name="iPhone Duo")
    db.add(scenario)
    db.commit()
    return user, account, card, scenario


def _propose_trade_in(db, scenario, account, card):
    db.add(models.ScenarioProposedItem(
        scenario_id=scenario.id, name="iPhone Trade-In", amount=Decimal("57.87"),
        type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=23,
        start_date=date(2026, 10, 23), end_date=date(2028, 10, 23),
        account_id=account.id, card_id=card.id,
    ))
    db.commit()


def _txn_names(entries, d: date) -> list[str]:
    return [t.name for e in entries if e.date == d for t in e.transactions]


def _balance_on(entries, d: date) -> Decimal:
    return next(e.projected_balance for e in entries if e.date == d)


def test_a_card_routed_proposal_never_appears_in_the_checking_walk(db_session):
    user, account, card, scenario = _seed(db_session)
    _propose_trade_in(db_session, scenario, account, card)

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    entries = build_forecast(
        db_session, user.id, account.id, date(2026, 10, 1), date(2026, 11, 30),
        proposal=proposal,
    )

    assert _txn_names(entries, date(2026, 10, 23)) == [], "the charge date must not touch checking"
    assert "iPhone Trade-In" not in [t.name for e in entries for t in e.transactions]


def test_it_reaches_checking_on_the_cards_payoff_date(db_session):
    """Charged 10/23 -> statement closes 10/28 -> due 11/25."""
    user, account, card, scenario = _seed(db_session)
    _propose_trade_in(db_session, scenario, account, card)

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    entries = build_forecast(
        db_session, user.id, account.id, date(2026, 10, 1), date(2026, 11, 30),
        proposal=proposal,
    )

    assert _txn_names(entries, date(2026, 11, 25)) == ["CC Estimate: Apple Card"]
    assert _balance_on(entries, date(2026, 11, 25)) == Decimal("4942.13")


def test_a_card_with_a_manual_estimate_swallows_the_proposal_entirely(db_session):
    """A manually-set monthly_spend_estimate wins over subscriptions
    (forecast_engine.py:691-701). So the identical proposal routed to such a
    card changes NOTHING. That is correct existing behavior, but it is
    invisible -- it reads as "the scenario doesn't work" -- which is why the
    proposal form warns about it. This test pins the behavior so the warning
    cannot quietly become untrue."""
    user, account, card, scenario = _seed(db_session, monthly_spend_estimate=Decimal("5500.00"))
    _propose_trade_in(db_session, scenario, account, card)

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    window = (date(2026, 10, 1), date(2026, 11, 30))
    with_proposal = build_forecast(db_session, user.id, account.id, *window, proposal=proposal)
    baseline = build_forecast(db_session, user.id, account.id, *window)

    assert [(e.date, e.projected_balance) for e in with_proposal] == \
           [(e.date, e.projected_balance) for e in baseline]


def test_a_card_routed_proposal_persists_nothing(db_session):
    user, account, card, scenario = _seed(db_session)
    _propose_trade_in(db_session, scenario, account, card)
    before = db_session.query(models.RecurringItem).count()

    _overrides, proposal = scenario_service.resolve_scenario(db_session, user.id, scenario.id)
    build_forecast(
        db_session, user.id, account.id, date(2026, 10, 1), date(2026, 11, 30),
        proposal=proposal,
    )

    assert db_session.query(models.RecurringItem).count() == before
