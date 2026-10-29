"""The daily email's "Lowest next month" figure (approved 2026-10-29):
the same rolling 3-month forecast walk `_lookahead_window` already builds
for `lookahead_minimum`, sliced down to the calendar month after `as_of`,
with the SAME floor_mask locked-card-payoff exclusion the 3-month figure
gets. See backend/services/budget_snapshot.py's `_lookahead_window`,
`_next_calendar_month_bounds`, and `_next_month_minimum`.
"""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.budget_snapshot import (
    compute_budget_snapshot,
    _next_calendar_month_bounds,
    _lookahead_minimum,
)


def _user(db, **kw):
    user = models.User(username=kw.pop("username", "nextmonth"), hashed_password="x", display_name="D", **kw)
    db.add(user)
    db.flush()
    return user


def _checking(db, user, balance="10000.00"):
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal(balance),
    )
    db.add(account)
    db.flush()
    return account


def test_next_calendar_month_bounds_is_plain_next_month():
    start, end, label = _next_calendar_month_bounds(date(2026, 10, 29))
    assert (start, end, label) == (date(2026, 11, 1), date(2026, 11, 30), "November")


def test_next_calendar_month_bounds_crosses_the_year_in_december():
    """December's "next month" is January of the FOLLOWING year, not month
    13 of the same one."""
    start, end, label = _next_calendar_month_bounds(date(2026, 12, 15))
    assert (start, end, label) == (date(2027, 1, 1), date(2027, 1, 31), "January")


def test_next_month_minimum_reads_only_days_inside_next_month(db_session):
    """A deeper dip landing AFTER next month must not leak into next
    month's reported low -- the figure has to come from days inside next
    month only, even when a later day in the 3-month window is lower."""
    user = _user(db_session, username="laterdeeper")
    account = _checking(db_session, user, balance="10000.00")
    db_session.add_all([
        # Shallow dip inside November (next month, relative to Oct 29).
        models.PlannedExpense(
            user_id=user.id, account_id=account.id, name="Nov dip",
            amount=Decimal("500.00"), expected_date=date(2026, 11, 10),
        ),
        # Deeper dip in December -- lower than the Nov dip, but not in next month.
        models.PlannedExpense(
            user_id=user.id, account_id=account.id, name="Dec dip",
            amount=Decimal("8000.00"), expected_date=date(2026, 12, 5),
        ),
    ])
    db_session.commit()

    snap = compute_budget_snapshot(db_session, user, account.id, as_of=date(2026, 10, 29))

    assert snap.next_month_minimum_date == date(2026, 11, 10)
    assert snap.next_month_minimum == Decimal("9500.00")
    assert snap.next_month_label == "November"
    # The 3-month figure DOES see the deeper December dip -- the two must
    # stay independently correct, not just "next month happens to win".
    assert snap.lookahead_minimum_date == date(2026, 12, 5)
    assert snap.lookahead_minimum == Decimal("1500.00")


def test_next_month_minimum_crosses_december_into_january(db_session):
    """Asked in December, a dip landing in January must be read as next
    month's low, not fall outside the window or get mis-dated."""
    user = _user(db_session, username="decjan")
    account = _checking(db_session, user, balance="10000.00")
    db_session.add(models.PlannedExpense(
        user_id=user.id, account_id=account.id, name="January dip",
        amount=Decimal("8000.00"), expected_date=date(2027, 1, 12),
    ))
    db_session.commit()

    snap = compute_budget_snapshot(db_session, user, account.id, as_of=date(2026, 12, 15))

    assert snap.next_month_minimum_date == date(2027, 1, 12)
    assert snap.next_month_minimum == Decimal("2000.00")
    assert snap.next_month_label == "January"


def test_next_month_minimum_excludes_the_locked_card_payoff_dip(db_session):
    """Same floor_mask locked-payoff exclusion the 3-month figure already
    gets must also apply to next month's figure: a statemented payoff dip
    inside next month is real money leaving (it still shows in the balance
    walk) but must not set the REPORTED next-month low -- the recovery
    balance after the following paycheck does, exactly like
    test_the_payoff_trough_is_not_the_safety_floor for the 3-month figure."""
    user = _user(db_session, username="nmlocked")
    account = _checking(db_session, user, balance="10000.00")
    db_session.add(models.CreditCard(
        user_id=user.id, name="Chase", credit_limit=Decimal("20000.00"),
        statement_day=28, due_day=5, is_active=True,
        balance_due=Decimal("9000.00"), current_balance=Decimal("9000.00"),
        next_payment_date=date(2026, 11, 5),
    ))
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=Decimal("6000.00"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly,
        # start_date set just after what would be the prior (Oct 20)
        # occurrence -- a Jan 2026 start would also fire historically within
        # the 45-day lookback (Sep 20, Oct 20), inflating the opening
        # balance before as_of and making the expected figures below wrong
        # for a reason unrelated to what this test checks.
        day_of_month=20, start_date=date(2026, 10, 21),
    ))
    db_session.commit()

    snap = compute_budget_snapshot(db_session, user, account.id, as_of=date(2026, 10, 29))

    assert snap.next_month_minimum_date is not None
    assert not (date(2026, 11, 5) <= snap.next_month_minimum_date <= date(2026, 11, 19)), (
        f"next month's reported low landed inside the masked payoff dip: {snap.next_month_minimum_date}"
    )
    assert snap.next_month_minimum == Decimal("7000.00")
    assert snap.next_month_minimum_date == date(2026, 11, 20)


def test_lookahead_minimum_direct_callers_still_get_a_plain_2_tuple(db_session):
    """_lookahead_minimum is called directly (not through compute_budget_snapshot)
    by other tests in this suite -- the refactor that split out
    _lookahead_window/_next_month_minimum must keep this exact (amount, date)
    contract working unchanged."""
    user = _user(db_session, username="directcaller")
    account = _checking(db_session, user, balance="5000.00")
    db_session.commit()

    floor, when = _lookahead_minimum(db_session, user.id, account.id, date(2026, 10, 29))
    assert floor == Decimal("5000.00")
    assert when is not None
