"""The Snapshot's displayed lowest points match the Forecast tab.

"Lowest next month", "Lowest in the next 3 months", their explain panels
and the email's "Move $Y into checking" line read a forecast walk that
keeps this month's not-yet-charged card subscriptions in the next card
payment -- the same balances the Forecast tab draws
(include_unbilled_card_bills=True, the build_forecast default).

Safety Margin is unchanged: it still reads the walk that leaves those bills
out (include_unbilled_card_bills=False), because it subtracts them itself.

Synthetic scenario, dates pinned: today is 2026-03-20. A card closes on
the 28th and is due the 25th. Its statemented $1,500.00 is due 3/25
(locked). The 3/28 cycle (carried $500.00 + "Late", a $40.00
subscription charged 3/25, this month and not yet charged) is paid 4/25,
inside next month. A paycheck on 4/15 ends the locked-payoff dip, so the
4/25 payment is both the next-month and the 3-month low.
"""
from datetime import date, timedelta
from decimal import Decimal

from backend import models
from backend.services import budget_snapshot
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.forecast_engine import build_forecast

TODAY = date(2026, 3, 20)
LATE = Decimal("40.00")


def _freeze_today(monkeypatch, fixed: date) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)
    monkeypatch.setattr("backend.services.budget_snapshot.date", _FixedDate)


def _scenario(db, monkeypatch):
    _freeze_today(monkeypatch, TODAY)
    user = models.User(username="displaylow", hashed_password="x", display_name="D")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("3000.00"),
    )
    db.add(account)
    db.flush()
    card = models.CreditCard(
        user_id=user.id, name="Chase", credit_limit=Decimal("10000.00"),
        statement_day=28, due_day=25, is_active=True,
        current_balance=Decimal("2000.00"), balance_due=Decimal("1500.00"),
        pending_charges=Decimal("0"), next_payment_date=date(2026, 3, 25),
        monthly_spend_estimate=Decimal("1.00"),
    )
    db.add(card)
    db.flush()
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, card_id=card.id, name="Late",
        amount=LATE, type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=25,
        start_date=date(2026, 1, 1),
    ))
    db.add(models.RecurringItem(
        user_id=user.id, account_id=account.id, name="Paycheck",
        amount=Decimal("100.00"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly, day_of_month=15,
        start_date=date(2026, 1, 1),
    ))
    db.commit()
    return user, account


def _walk_lows(db, user, account, *, include_unbilled: bool):
    """(3-month low, its date, next-month low, its date) from one walk, with
    the snapshot's window, start and floor_mask rules."""
    days = build_forecast(
        db, user.id, account.id, TODAY - timedelta(days=45),
        budget_snapshot._months_ahead_end(TODAY, 3),
        include_unbilled_card_bills=include_unbilled,
    )
    mask = budget_snapshot.floor_mask(days, db.query(models.CreditCard).all())
    low, low_date = budget_snapshot._floor_minimum(days, mask, TODAY)
    nm_start, nm_end, _ = budget_snapshot._next_calendar_month_bounds(TODAY)
    nm_low, nm_date = budget_snapshot._floor_minimum(days, mask, TODAY, start=nm_start, end=nm_end)
    return low, low_date, nm_low, nm_date


def test_displayed_lows_match_the_forecast_tab_walk(db_session, monkeypatch):
    user, account = _scenario(db_session, monkeypatch)
    snap = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)

    full_low, full_date, full_nm, full_nm_date = _walk_lows(db_session, user, account, include_unbilled=True)
    floor_low, floor_date, floor_nm, _ = _walk_lows(db_session, user, account, include_unbilled=False)

    # The scenario really does exercise the gap: same day, $40 apart.
    assert full_date == floor_date == date(2026, 4, 25)
    assert full_nm_date == date(2026, 4, 25)
    assert floor_low - full_low == LATE
    assert floor_nm - full_nm == LATE

    assert (snap.lookahead_minimum, snap.lookahead_minimum_date) == (full_low, full_date)
    assert (snap.next_month_minimum, snap.next_month_minimum_date) == (full_nm, full_nm_date)
    assert snap.explain["lookahead_minimum"].result == full_low


def test_safety_margin_still_reads_the_walk_without_this_months_card_bills(db_session, monkeypatch):
    user, account = _scenario(db_session, monkeypatch)
    snap = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)

    floor_low, _, _, _ = _walk_lows(db_session, user, account, include_unbilled=False)
    cc_budget_total = LATE  # "Late" is the only card bill this month
    charged_so_far = Decimal("0")  # and it hasn't been charged yet (3/25)
    assert snap.safety_margin == floor_low - cc_budget_total + charged_so_far
    assert snap.explain["safety_margin"].result == snap.safety_margin
    assert snap.explain["safety_margin"].rows[0].amount == floor_low
