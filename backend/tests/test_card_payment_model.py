"""The card-payment model: the one place a card's next payments are estimated
(locked statement payoff, cycle estimate, second hop, flat estimate,
subscription fallback), read by the forecast and the Household Snapshot.

Invented figures throughout, never the user's real account data.
"""
import os
from datetime import date, datetime
from decimal import Decimal

from backend import models
from backend.services.forecast_engine import build_forecast, ScenarioProposal
from backend.tests.test_forecast_spreadsheet_gaps_20260814 import _user, _checking, _card

TODAY = date(2026, 11, 3)


def _freeze_today(monkeypatch, fixed: date = TODAY) -> date:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)
    try:  # the model reads the clock too, once it exists
        monkeypatch.setattr("backend.services.card_payment_model.date", _FixedDate)
    except (AttributeError, ImportError):
        pass
    return fixed


def _fixture(db):
    """Six cards, one per estimate path, on one checking account."""
    user = _user(db, username="cardmodel")
    account = _checking(db, user, balance="20000.00")
    fresh = datetime(2026, 11, 2, 9, 0)
    # Locked statement due 11/17; the cycle after it carried from the balance.
    locked = _card(db, user, name="Locked Card", statement_day=20, due_day=17,
                   balance_due=Decimal("1200.00"), current_balance=Decimal("1500.00"),
                   next_payment_date=date(2026, 11, 17))
    # A card bill still to charge this month: the safety walk leaves it out of
    # the cycle estimate (Safety Margin subtracts it itself), the display walk keeps it.
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, card_id=locked.id, name="Gym",
        amount=Decimal("40.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=10,
        start_date=date(2026, 1, 1),
    ))
    # Second hop: manual estimate + fresh pending + a card-routed one-off.
    hop = _card(db, user, name="Hop Card", statement_day=28, due_day=25,
                balance_due=Decimal("500.00"), current_balance=Decimal("900.00"),
                pending_charges=Decimal("100.00"), pending_charges_updated_at=fresh,
                next_payment_date=date(2026, 11, 25),
                monthly_spend_estimate=Decimal("800.00"))
    db.add(models.PlannedExpense(
        user_id=user.id, account_id=account.id, card_id=hop.id, name="Trip",
        amount=Decimal("90.00"), expected_date=date(2026, 11, 10),
    ))
    # Flat estimate only: nothing known about the card.
    _card(db, user, name="Flat Card", statement_day=12, due_day=9,
          balance_due=Decimal("0"), current_balance=Decimal("0"),
          next_payment_date=None, monthly_spend_estimate=Decimal("250.00"))
    # Subscription fallback: no estimate, no balance, one subscription.
    sub = _card(db, user, name="Sub Card", statement_day=14, due_day=11,
                balance_due=Decimal("0"), current_balance=Decimal("0"))
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, card_id=sub.id, name="Streaming",
        amount=Decimal("30.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=5,
        start_date=date(2026, 1, 1),
    ))
    # Balance-only card (no transaction feed), stale due date: rolls forward and
    # merges the statement with the carried cycle into one locked line.
    _card(db, user, name="Balance Only", statement_day=22, due_day=19,
          balance_due=Decimal("250.00"), current_balance=Decimal("250.00"),
          next_payment_date=date(2026, 9, 19))
    # Due three days ago and unpaid: re-planned onto today after the auto anchor.
    _card(db, user, name="Overdue Card", statement_day=2, due_day=31,
          balance_due=Decimal("300.00"), current_balance=Decimal("300.00"),
          next_payment_date=date(2026, 10, 31))
    db.add(models.ForecastDayCheckpoint(
        user_id=user.id, account_id=account.id, date=TODAY,
        actual_balance=Decimal("20000.00"), note="Auto (bank sync)",
    ))
    db.commit()
    return user, account


def _norm(value):
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}={_norm(v)}" for k, v in sorted(value.items())) + "}"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _lines(entries):
    return [
        (e.date.isoformat(), t.name, str(t.amount), _norm(t.basis) if t.basis else "")
        for e in entries for t in e.transactions
        if t.is_cc_payment
    ]


def _walks(db, user, account):
    start = date(2026, 9, 19)
    end = date(2027, 2, 28)
    return {
        "display": build_forecast(db, user.id, account.id, start, end),
        "safety": build_forecast(db, user.id, account.id, start, end,
                                 include_unbilled_card_bills=False),
        "from_today": build_forecast(db, user.id, account.id, TODAY, end),
    }


def test_forecast_unchanged_by_extraction(db_session, monkeypatch):
    """Golden: build_forecast's card lines (date, name, amount, basis), captured
    from the code before the card-payment model was extracted. The extraction
    must not move any of them."""
    _freeze_today(monkeypatch)
    user, account = _fixture(db_session)
    walks = _walks(db_session, user, account)
    if os.environ.get("DUMP_GOLDEN"):
        for name, entries in walks.items():
            print(f"GOLDEN {name} = [")
            for line in _lines(entries):
                print(f"    {line!r},")
            print(f"    # final balance {entries[-1].projected_balance}")
            print("]")
    for name, entries in walks.items():
        assert _lines(entries) == GOLDEN[name], name
        assert str(entries[-1].projected_balance) == GOLDEN_FINAL[name], name


GOLDEN = {
    "display": [
        ('2026-11-03', 'CC Payment: Overdue Card', '-300.00', '{due_date=2026-10-31, kind=locked}'),
        ('2026-11-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2026-11-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2026-11-17', 'CC Payment: Locked Card', '-1200.00', '{due_date=2026-11-17, kind=locked}'),
        ('2026-11-19', 'CC Payment: Balance Only', '-250.00', '{due_date=2026-11-19, kind=locked}'),
        ('2026-11-25', 'CC Payment: Hop Card', '-500.00', '{due_date=2026-11-25, kind=locked}'),
        ('2026-12-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2026-12-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2026-12-17', 'CC Estimate: Locked Card', '-340.00', '{close_date=2026-11-20, kind=cycle_estimate, one_offs=0, pending=0, spent_since_statement=300.00, statement_date=2026-10-20, subscriptions_before_close=40.00}'),
        ('2026-12-25', 'Trip (via Hop Card)', '-90.00', ''),
        ('2026-12-25', 'CC Estimate: Hop Card', '-500.00', '{close_date=2026-11-28, kind=cycle_estimate, one_offs=90.00, pending=100.00, spent_since_statement=400.00, statement_date=2026-10-28, subscriptions_before_close=0}'),
        ('2027-01-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2027-01-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2027-01-17', 'CC Estimate: Locked Card', '-40.00', '{kind=subscription_flat, monthly_amount=40.00}'),
        ('2027-01-25', 'CC Estimate: Hop Card', '-100.00', '{close_date=2026-12-28, kind=cycle_estimate, one_offs=0, pending=100.00, spent_since_statement=0, statement_date=None, subscriptions_before_close=0}'),
        ('2027-02-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2027-02-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2027-02-17', 'CC Estimate: Locked Card', '-40.00', '{kind=subscription_flat, monthly_amount=40.00}'),
        ('2027-02-25', 'CC Estimate: Hop Card', '-800.00', '{kind=flat, monthly_amount=800.00}'),
    ],
    "safety": [
        ('2026-11-03', 'CC Payment: Overdue Card', '-300.00', '{due_date=2026-10-31, kind=locked}'),
        ('2026-11-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2026-11-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2026-11-17', 'CC Payment: Locked Card', '-1200.00', '{due_date=2026-11-17, kind=locked}'),
        ('2026-11-19', 'CC Payment: Balance Only', '-250.00', '{due_date=2026-11-19, kind=locked}'),
        ('2026-11-25', 'CC Payment: Hop Card', '-500.00', '{due_date=2026-11-25, kind=locked}'),
        ('2026-12-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2026-12-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2026-12-17', 'CC Estimate: Locked Card', '-300.00', '{close_date=2026-11-20, kind=cycle_estimate, one_offs=0, pending=0, spent_since_statement=300.00, statement_date=2026-10-20, subscriptions_before_close=0}'),
        ('2026-12-25', 'Trip (via Hop Card)', '-90.00', ''),
        ('2026-12-25', 'CC Estimate: Hop Card', '-500.00', '{close_date=2026-11-28, kind=cycle_estimate, one_offs=90.00, pending=100.00, spent_since_statement=400.00, statement_date=2026-10-28, subscriptions_before_close=0}'),
        ('2027-01-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2027-01-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2027-01-17', 'CC Estimate: Locked Card', '-40.00', '{kind=subscription_flat, monthly_amount=40.00}'),
        ('2027-01-25', 'CC Estimate: Hop Card', '-100.00', '{close_date=2026-12-28, kind=cycle_estimate, one_offs=0, pending=100.00, spent_since_statement=0, statement_date=None, subscriptions_before_close=0}'),
        ('2027-02-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2027-02-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2027-02-17', 'CC Estimate: Locked Card', '-40.00', '{kind=subscription_flat, monthly_amount=40.00}'),
        ('2027-02-25', 'CC Estimate: Hop Card', '-800.00', '{kind=flat, monthly_amount=800.00}'),
    ],
    "from_today": [
        ('2026-11-03', 'CC Payment: Overdue Card', '-300.00', '{due_date=2026-10-31, kind=locked}'),
        ('2026-11-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2026-11-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2026-11-17', 'CC Payment: Locked Card', '-1200.00', '{due_date=2026-11-17, kind=locked}'),
        ('2026-11-19', 'CC Payment: Balance Only', '-250.00', '{due_date=2026-11-19, kind=locked}'),
        ('2026-11-25', 'CC Payment: Hop Card', '-500.00', '{due_date=2026-11-25, kind=locked}'),
        ('2026-12-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2026-12-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2026-12-17', 'CC Estimate: Locked Card', '-340.00', '{close_date=2026-11-20, kind=cycle_estimate, one_offs=0, pending=0, spent_since_statement=300.00, statement_date=2026-10-20, subscriptions_before_close=40.00}'),
        ('2026-12-25', 'Trip (via Hop Card)', '-90.00', ''),
        ('2026-12-25', 'CC Estimate: Hop Card', '-500.00', '{close_date=2026-11-28, kind=cycle_estimate, one_offs=90.00, pending=100.00, spent_since_statement=400.00, statement_date=2026-10-28, subscriptions_before_close=0}'),
        ('2027-01-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2027-01-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2027-01-17', 'CC Estimate: Locked Card', '-40.00', '{kind=subscription_flat, monthly_amount=40.00}'),
        ('2027-01-25', 'CC Estimate: Hop Card', '-100.00', '{close_date=2026-12-28, kind=cycle_estimate, one_offs=0, pending=100.00, spent_since_statement=0, statement_date=None, subscriptions_before_close=0}'),
        ('2027-02-09', 'CC Estimate: Flat Card', '-250.00', '{kind=flat, monthly_amount=250.00}'),
        ('2027-02-11', 'CC Estimate: Sub Card', '-30.00', '{kind=subscription_flat, monthly_amount=30.00}'),
        ('2027-02-17', 'CC Estimate: Locked Card', '-40.00', '{kind=subscription_flat, monthly_amount=40.00}'),
        ('2027-02-25', 'CC Estimate: Hop Card', '-800.00', '{kind=flat, monthly_amount=800.00}'),
    ],
}
GOLDEN_FINAL = {"display": "14720.00", "safety": "14760.00", "from_today": "14720.00"}


def test_scenario_proposed_card_bill_in_cc_budget(db_session, monkeypatch):
    """A scenario proposing a weekly $50 card bill from Nov 6 (Fridays: 6, 13,
    20, 27) must lower Safety Margin by every occurrence this month. The
    safety walk already leaves the proposal out of the card payment, so before
    the fix nothing subtracted it anywhere. Left to Spend is not touched by an
    add-back: a proposal is not in posted card spending."""
    from backend.services.budget_snapshot import compute_budget_snapshot
    as_of = _freeze_today(monkeypatch, date(2026, 11, 6))
    user = _user(db_session, username="scenariocard")
    account = _checking(db_session, user, balance="9000.00")
    card = _card(db_session, user, name="Scenario Card", statement_day=28, due_day=25,
                 balance_due=Decimal("0"), current_balance=Decimal("0"),
                 monthly_spend_estimate=Decimal("300.00"))
    db_session.commit()
    proposed = models.RecurringItem(
        id=-1, user_id=user.id, account_id=account.id, card_id=card.id, name="Proposed gym",
        amount=Decimal("50.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.weekly, day_of_month=0,
        start_date=date(2026, 11, 6), is_active=True, include_in_forecast=True,
    )

    baseline = compute_budget_snapshot(db_session, user, account.id, as_of=as_of)
    scenario = compute_budget_snapshot(
        db_session, user, account.id, as_of=as_of, proposal=ScenarioProposal(items=(proposed,)),
    )

    assert scenario.safety_margin == baseline.safety_margin - Decimal("200.00")


def test_basis_note_reads_a_card_payment_and_its_basis_alike():
    """The explain note is the same text whether it is handed the model's
    CardPayment or the basis dict the forecast line carries."""
    from backend.services.budget_snapshot import _cc_basis_note
    from backend.services.card_payment_model import CardPayment
    basis = {"kind": "locked", "due_date": date(2026, 11, 17)}
    payment = CardPayment(card_id=1, due=date(2026, 11, 17), amount=Decimal("1200.00"),
                          locked=True, basis=basis)
    assert _cc_basis_note(payment) == _cc_basis_note(basis) == "Statement balance, due Nov 17."
    assert _cc_basis_note(None) is None


def test_balance_only_card_uses_its_balance_and_the_snapshot_does_not_double_count(db_session, monkeypatch):
    """A card with no transaction feed (balance-only, like a SimpleFIN card):
    the model pays its statement and carries the rest of the balance into the
    next cycle, and the snapshot's spend totals count it once, off its balance."""
    from backend.services.budget_snapshot import compute_budget_snapshot
    from backend.services.card_payment_model import card_payments
    as_of = _freeze_today(monkeypatch)
    user = _user(db_session, username="balanceonly")
    account = _checking(db_session, user, balance="9000.00")
    card = _card(db_session, user, name="Balance Card", statement_day=20, due_day=17,
                 balance_due=Decimal("400.00"), current_balance=Decimal("650.00"),
                 next_payment_date=date(2026, 11, 17))
    db_session.commit()

    payments = card_payments(
        db_session, user, account, as_of, date(2027, 1, 31),
        include_unbilled_card_bills=True, today=as_of,
    )

    assert [(p.card_id, p.due, p.amount, p.locked, p.basis["kind"]) for p in payments] == [
        (card.id, date(2026, 11, 17), Decimal("400.00"), True, "locked"),
        (card.id, date(2026, 12, 17), Decimal("250.00"), False, "cycle_estimate"),
    ]
    snapshot = compute_budget_snapshot(db_session, user, account.id, as_of=as_of)
    assert snapshot.left_to_spend == Decimal("-250.00")  # spent since the statement, once


def test_a_savings_account_draws_no_card_payments(db_session, monkeypatch):
    from backend.services.card_payment_model import card_payments
    as_of = _freeze_today(monkeypatch)
    user = _user(db_session, username="savingsnocards")
    savings = models.Account(
        user_id=user.id, name="Savings", type=models.AccountType.savings,
        current_balance=Decimal("5000.00"),
    )
    db_session.add(savings)
    _card(db_session, user, balance_due=Decimal("100.00"), current_balance=Decimal("100.00"),
          next_payment_date=date(2026, 11, 25))
    db_session.commit()

    assert card_payments(
        db_session, user, savings, as_of, date(2027, 1, 31),
        include_unbilled_card_bills=True, today=as_of,
    ) == []
