"""The card payments standing behind the 3-month lowest point, surfaced as
informational children on "lookahead_minimum" and "safety_margin" -- the
user's ask (2026-10-29): his Chase estimate jumped when the statement
closed, and the ⓘ panel should say why.

Invented figures throughout, never the user's real account data.
"""
from datetime import date, timedelta
from decimal import Decimal
from backend import models
from backend.services.budget_snapshot import compute_budget_snapshot


def _user_checking(db, username: str, balance="10000.00"):
    user = models.User(username=username, hashed_password="x", display_name="D")
    db.add(user)
    db.flush()
    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal(balance),
    )
    db.add(checking)
    db.flush()
    return user, checking


def test_lookahead_and_safety_margin_list_the_card_lines_up_to_the_low_date(db_session):
    """One locked card payoff, then a small income event a few days later
    (so the floor_mask's locked-dip exclusion lifts and the post-payoff
    balance becomes eligible to be the reported low -- floor_mask excludes
    everything from a payoff through the NEXT income event, never forever).
    The low lands on the income day, which is after the payoff, so the
    payoff falls inside [as_of, low date] and must be listed on both
    "lookahead_minimum" and "safety_margin"."""
    today = date.today()
    as_of = today
    due = today + timedelta(days=10)
    income_date = due + timedelta(days=5)
    user, checking = _user_checking(db_session, "lowline")
    db_session.add(models.CreditCard(
        user_id=user.id, name="TestCard", credit_limit=Decimal("10000.00"),
        statement_day=(due - timedelta(days=28)).day, due_day=due.day,
        current_balance=Decimal("3000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("0"), next_payment_date=due, is_active=True,
    ))
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=checking.id, name="Income", amount=Decimal("1.00"),
        type=models.RecurringType.income, frequency=models.RecurringFrequency.monthly,
        day_of_month=income_date.day, start_date=date(2020, 1, 1),
    ))
    db_session.commit()

    snap = compute_budget_snapshot(db_session, user, checking.id, as_of=as_of)

    # The income may shift a day earlier if income_date lands on a weekend
    # (recurring items shift Sat/Sun onto the preceding Friday), so pin the
    # low to the right neighborhood rather than one exact day.
    assert due <= snap.lookahead_minimum_date <= income_date, (
        f"the low ({snap.lookahead_minimum_date}) must land on/after the payoff ({due}) "
        f"and no later than the income day ({income_date})"
    )

    for key in ("lookahead_minimum", "safety_margin"):
        kids = snap.explain[key].rows[0].informational_children
        matching = [c for c in kids if "CC Payment: TestCard" in c.label]
        assert len(matching) == 1, f"{key}: expected exactly one TestCard line, got {kids}"
        child = matching[0]
        assert child.amount == Decimal("-3000.00")
        assert child.note == f"Statement balance, due {due:%b %-d}."
        assert f"{due:%b %-d}" in child.label, "label carries the date the line falls on"


def test_recent_close_line_appears_within_seven_days_and_not_after(db_session):
    """A card whose statement closed 7 days ago (inclusive) gets the
    heads-up line on "lookahead_minimum"; a card whose close was 8 days ago
    does not."""
    as_of = date(2026, 3, 15)
    close_within = as_of - timedelta(days=7)
    close_outside = as_of - timedelta(days=8)
    user, checking = _user_checking(db_session, "recentclose")
    db_session.add(models.CreditCard(
        user_id=user.id, name="WithinSeven", credit_limit=Decimal("5000.00"),
        statement_day=close_within.day, due_day=25,
        current_balance=Decimal("500.00"), balance_due=Decimal("500.00"),
        pending_charges=Decimal("0"), is_active=True,
    ))
    db_session.add(models.CreditCard(
        user_id=user.id, name="OutsideSeven", credit_limit=Decimal("5000.00"),
        statement_day=close_outside.day, due_day=25,
        current_balance=Decimal("500.00"), balance_due=Decimal("500.00"),
        pending_charges=Decimal("0"), is_active=True,
    ))
    db_session.commit()

    snap = compute_budget_snapshot(db_session, user, checking.id, as_of=as_of)
    kids = snap.explain["lookahead_minimum"].rows[0].informational_children
    labels = [c.label for c in kids]

    assert any(l.startswith("WithinSeven's statement closed") for l in labels), labels
    assert not any(l.startswith("OutsideSeven's statement closed") for l in labels), labels
