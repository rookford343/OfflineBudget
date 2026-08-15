"""PlannedExpense.card_id -- a one-off purchase charged to a card doesn't hit
checking on expected_date, only when the card's statement covering it gets
paid off.

Found live 2026-08-13: reconciling a forecast gap against Dan's spreadsheet
traced partly to "Holland Vacation" ($917.04), a real planned purchase Dan
actually puts on his Chase card -- the app was subtracting it from checking
on the day of the trip, while in reality checking isn't touched until Chase's
statement gets paid, roughly a month later.

The routing went through two versions. v1 matched only on due_day and got
corrected same-day: a charge posting one day before a nearby due_day (Chase:
due the 25th) was routed there directly, but with statement_day=28 and
due_day=25, EVERY due date pays off the cycle that closed a full month
earlier -- a charge anywhere in the 7/29-8/28 window (the whole of the
currently-open cycle) is due 9/25, not 8/25. v2 (tested here) finds the
statement close first, then the first due_day strictly after that close.
"""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.forecast_engine import (
    build_forecast, _card_payoff_date_for_charge, _next_occurrence_on_or_after,
)


def _seed(db, *, statement_day: int = 28, due_day: int = 25):
    user = models.User(username="cardpe", hashed_password="x", display_name="CardPE")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("5000.00"),
    )
    card = models.CreditCard(
        user_id=user.id, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=statement_day, due_day=due_day,
    )
    db.add_all([account, card])
    db.commit()
    return user, account, card


def _balance_on(entries, d: date) -> Decimal:
    return next(e.projected_balance for e in entries if e.date == d)


def _txn_names(entries, d: date) -> list[str]:
    return [t.name for e in entries if e.date == d for t in e.transactions]


def test_charge_the_day_before_a_due_date_still_rolls_to_next_cycle(db_session):
    """The exact bug Dan caught: statement_day=28, due_day=25. A charge on
    8/24 -- one day before the 8/25 due date -- must NOT be paid off on
    8/25, because that statement closed back on 7/28. It belongs to the
    statement closing 8/28, due 9/25."""
    user, account, card = _seed(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, card_id=card.id, name="Holland Vacation",
        amount=Decimal("917.04"), expected_date=date(2026, 8, 24),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 1), date(2026, 9, 30))

    assert _balance_on(entries, date(2026, 8, 25)) == Decimal("5000.00"), "must not be paid off on the imminent due date"
    assert _balance_on(entries, date(2026, 9, 25)) == Decimal("4082.96"), "belongs to the following cycle instead"
    assert _txn_names(entries, date(2026, 9, 25)) == ["Holland Vacation (via Chase Sapphire)"]


def test_the_entire_open_cycle_pays_off_on_the_same_far_due_date(db_session):
    """With a 28-day close-to-due gap, EVERY charge in the 7/29-8/28 window
    -- early, middle, or right at the close -- is due 9/25. There is no
    "next upcoming due date" (8/25) for a charge made today; that due date
    already belongs to the PRIOR, already-closed cycle."""
    user, account, card = _seed(db_session)
    for name, d in [("Early", date(2026, 8, 1)), ("Middle", date(2026, 8, 15)), ("At close", date(2026, 8, 28))]:
        db_session.add(models.PlannedExpense(
            user_id=user.id, card_id=card.id, name=name,
            amount=Decimal("10.00"), expected_date=d,
        ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 1), date(2026, 9, 30))

    assert _txn_names(entries, date(2026, 8, 25)) == [], "the imminent due date belongs to the prior, already-closed cycle"
    assert set(_txn_names(entries, date(2026, 9, 25))) == {
        "Early (via Chase Sapphire)", "Middle (via Chase Sapphire)", "At close (via Chase Sapphire)",
    }
    assert _balance_on(entries, date(2026, 9, 25)) == Decimal("4970.00")


def test_charge_the_day_after_close_pushes_a_full_cycle_further(db_session):
    """8/29 is one day past the 8/28 close, so it's captured by the NEXT
    cycle (closing 9/28), due 10/25 -- a full cycle later than a charge on
    8/28 itself."""
    user, account, card = _seed(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, card_id=card.id, name="Just missed the close",
        amount=Decimal("100.00"), expected_date=date(2026, 8, 29),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 1), date(2026, 10, 31))

    assert _txn_names(entries, date(2026, 9, 25)) == []
    assert _balance_on(entries, date(2026, 10, 25)) == Decimal("4900.00")


def test_card_linked_inflow_still_credits_on_the_computed_payoff_date(db_session):
    """A card-linked refund/credit uses the same routing, just signed positive."""
    user, account, card = _seed(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, card_id=card.id, name="Return Credit",
        amount=Decimal("150.00"), expected_date=date(2026, 8, 1),
        direction=models.PlannedDirection.inflow,
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 1), date(2026, 9, 30))

    assert _balance_on(entries, date(2026, 9, 25)) == Decimal("5150.00")


def test_unlinked_planned_expense_is_unaffected(db_session):
    """No card_id -- behaves exactly as before this feature existed."""
    user, account, _card = _seed(db_session)
    db_session.add(models.PlannedExpense(
        user_id=user.id, name="Cash gift", amount=Decimal("100.00"),
        expected_date=date(2026, 8, 10),
    ))
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 9), date(2026, 8, 11))

    assert _balance_on(entries, date(2026, 8, 10)) == Decimal("4900.00")


# ── Unit coverage of the two helpers directly ────────────────────────────────

def test_next_occurrence_on_or_after_handles_rollover_and_short_months():
    assert _next_occurrence_on_or_after(25, date(2026, 8, 23)) == date(2026, 8, 25)
    assert _next_occurrence_on_or_after(25, date(2026, 8, 26)) == date(2026, 9, 25)
    # 0 means "last day of month", same convention RecurringItem uses.
    assert _next_occurrence_on_or_after(0, date(2026, 2, 10)) == date(2026, 2, 28)
    # A day-of-month beyond a short month's length clamps to that month's last day.
    assert _next_occurrence_on_or_after(31, date(2026, 2, 10)) == date(2026, 2, 28)


def test_card_payoff_date_matches_dans_real_card():
    card = models.CreditCard(
        user_id=1, name="Chase Sapphire", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25,
    )
    # Entire 7/29-8/28 cycle -> due 9/25, regardless of where in it.
    assert _card_payoff_date_for_charge(card, date(2026, 7, 29)) == date(2026, 9, 25)
    assert _card_payoff_date_for_charge(card, date(2026, 8, 1)) == date(2026, 9, 25)
    assert _card_payoff_date_for_charge(card, date(2026, 8, 24)) == date(2026, 9, 25)
    assert _card_payoff_date_for_charge(card, date(2026, 8, 28)) == date(2026, 9, 25)
    # One day later -> pushed a full cycle further, to 10/25.
    assert _card_payoff_date_for_charge(card, date(2026, 8, 29)) == date(2026, 10, 25)


def test_card_payoff_date_when_due_day_is_after_statement_day():
    """The less common shape -- due_day numerically greater than
    statement_day, e.g. closes the 5th, due the 25th of the SAME month.
    "Strictly after" the close still resolves this correctly without any
    special-casing, and here the close-to-due gap is short enough that a
    charge early in the cycle IS paid off in the same calendar month."""
    card = models.CreditCard(
        user_id=1, name="Same-month card", credit_limit=Decimal("5000.00"),
        statement_day=5, due_day=25,
    )
    assert _card_payoff_date_for_charge(card, date(2026, 8, 1)) == date(2026, 8, 25)
    assert _card_payoff_date_for_charge(card, date(2026, 8, 5)) == date(2026, 8, 25)
    assert _card_payoff_date_for_charge(card, date(2026, 8, 6)) == date(2026, 9, 25)
