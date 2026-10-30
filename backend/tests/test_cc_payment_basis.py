"""The receipt behind a "CC Payment"/"CC Estimate" forecast line's own
amount -- `ForecastTransaction.basis`, set in build_forecast at the exact
point each amount is computed, so a caller (budget_snapshot's lowest-point
explain) can describe the figure without re-deriving it or re-running the
forecast. Covers all three shapes: a carried/second-hop cycle estimate, a
flat-fallback estimate, and a locked statement payoff.

Invented figures throughout, never the user's real account data.
"""
from datetime import date, timedelta
from decimal import Decimal
from backend import models
from backend.services.budget_snapshot import _cc_basis_note
from backend.services.forecast_engine import build_forecast, _most_recent_occurrence_on_or_before
from backend.tests.test_forecast_spreadsheet_gaps_20260814 import _user, _checking, _card


def _tx_named(entries, name):
    """(date, ForecastTransaction) for every projected line with this exact
    name -- unlike test_forecast_spreadsheet_gaps_20260814's `_named`, this
    keeps the whole transaction so `.basis` is reachable."""
    return [(e.date, t) for e in entries for t in e.transactions if t.name == name and not t.is_actual]


def test_carried_cycle_estimate_basis_sums_to_its_amount(db_session):
    """Chase-shaped card: $4,000 running balance, $3,000 already statemented
    (balance_due), $200 of that running balance is live pending_charges --
    so of the $1,200 carried, $200 is "pending now" and the other $1,000 is
    spending that already posted since the last statement but was never
    itself pending. Plus a $100 subscription posting before the statement
    closes -> the next cycle's CC Estimate is $1,300.00. The basis attached
    to that line must break the $1,300.00 into exactly those three parts
    (no planned one-offs land on this card's due date, so that fourth part
    is 0) -- matching the user's real Chase case, where the one-offs slice
    was also 0."""
    today = date.today()
    close_date = today + timedelta(days=14)
    sub_date = today + timedelta(days=6)
    due_day = (close_date + timedelta(days=3)).day
    user = _user(db_session, username="basistest1")
    account = _checking(db_session, user, balance="60000.00")
    card = _card(
        db_session, user, name="Chase", statement_day=close_date.day, due_day=due_day,
        current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("200.00"),
        next_payment_date=today + timedelta(days=200),  # comfortably non-stale
        monthly_spend_estimate=Decimal("15000.00"),
    )
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, card_id=card.id, name="Sub",
        amount=Decimal("100.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly,
        day_of_month=sub_date.day, start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, today, today + timedelta(days=120))
    next_cycle = [
        (d, t) for d, t in _tx_named(entries, "CC Estimate: Chase")
        if close_date <= d < close_date + timedelta(days=32)
    ]
    assert len(next_cycle) == 1, next_cycle
    _d, tx = next_cycle[0]
    assert tx.amount == Decimal("-1300.00")
    assert tx.basis is not None, "a cycle estimate must carry its breakdown"
    assert tx.basis["kind"] == "cycle_estimate"
    assert tx.basis["pending"] == Decimal("200.00"), "only the LIVE pending_charges slice, not the whole carried figure"
    assert tx.basis["spent_since_statement"] == Decimal("1000.00"), "carried spend beyond pending_charges"
    assert tx.basis["statement_date"] == _most_recent_occurrence_on_or_before(card.statement_day, today)
    assert tx.basis["subscriptions_before_close"] == Decimal("100.00")
    assert tx.basis["one_offs"] == Decimal("0")
    total = (
        tx.basis["pending"] + tx.basis["spent_since_statement"]
        + tx.basis["subscriptions_before_close"] + tx.basis["one_offs"]
    )
    assert total == abs(tx.amount), f"basis parts must sum to the line's own amount, got {total} vs {abs(tx.amount)}"


def test_carried_spending_with_no_pending_is_labeled_spent_since_statement(db_session):
    """Reproduces the user's real Apple Card, 2026-10-30: $0 live pending,
    all $145.30 of the carried figure is spending that already posted since
    the last statement. The note must say "Spent since the ... statement",
    never "Pending now" -- that label implies money the bank has flagged as
    pending, which this isn't."""
    basis = {
        "kind": "cycle_estimate",
        "pending": Decimal("0"),
        "spent_since_statement": Decimal("145.30"),
        "statement_date": date(2026, 10, 1),
        "subscriptions_before_close": Decimal("0"),
        "one_offs": Decimal("0"),
        "close_date": None,
    }
    note = _cc_basis_note(basis)
    assert note == (
        "Spent since the Oct 1 statement $145.30. This is spending so far; it grows as you spend."
    )
    assert "Pending now" not in note


def test_carried_note_shows_both_parts_when_both_exist(db_session):
    """When a cycle has both live pending and carried-but-not-pending
    spending, the note names both, pending first."""
    basis = {
        "kind": "cycle_estimate",
        "pending": Decimal("200.00"),
        "spent_since_statement": Decimal("1000.00"),
        "statement_date": date(2026, 10, 14),
        "subscriptions_before_close": Decimal("100.00"),
        "one_offs": Decimal("0"),
        "close_date": date(2026, 11, 14),
    }
    note = _cc_basis_note(basis)
    assert note == (
        "Pending now $200.00 + spent since the Oct 14 statement $1,000.00 + "
        "subscriptions billing before the Nov 14 close $100.00. "
        "This is spending so far; it grows as you spend."
    )


def test_flat_fallback_estimate_carries_a_flat_basis(db_session):
    """A card with no balance_due/current_balance signal at all (never
    carried, never statemented) falls all the way back to the manual
    monthly_spend_estimate -- its basis must say exactly that, with the
    flat amount, not a cycle breakdown."""
    today = date.today()
    user = _user(db_session, username="basistest2")
    account = _checking(db_session, user)
    _card(
        db_session, user, name="Flat Card", statement_day=28, due_day=25,
        current_balance=Decimal("0"), balance_due=Decimal("0"),
        pending_charges=Decimal("0"), next_payment_date=None,
        monthly_spend_estimate=Decimal("250.00"),
    )
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, today, today + timedelta(days=95))
    estimates = _tx_named(entries, "CC Estimate: Flat Card")
    assert estimates, "the flat fallback must still project something"
    _d, tx = estimates[0]
    assert tx.amount == Decimal("-250.00")
    assert tx.basis == {"kind": "flat", "monthly_amount": Decimal("250.00")}


def test_locked_payoff_carries_a_statement_basis(db_session):
    """A real, already-statemented balance due inside the forecast window is
    a locked payoff -- its basis must say so and carry the due date, not a
    cycle breakdown."""
    today = date.today()
    due = today + timedelta(days=10)
    user = _user(db_session, username="basistest3")
    account = _checking(db_session, user, balance="20000.00")
    _card(
        db_session, user, name="Locked Card", statement_day=(due - timedelta(days=28)).day,
        due_day=due.day, current_balance=Decimal("3000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("0"), next_payment_date=due,
    )
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, today, today + timedelta(days=30))
    payoffs = _tx_named(entries, "CC Payment: Locked Card")
    assert payoffs, "a real balance_due must still produce a locked payoff"
    d, tx = payoffs[0]
    assert tx.amount == Decimal("-3000.00")
    assert tx.basis == {"kind": "locked", "due_date": d}
