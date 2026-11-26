"""weekly_lows: rolling 7-day buckets over the DISPLAY window.

The lowest bucket must equal `lookahead_minimum` ("Lowest in the next 3
months"), because the chart is a slice of the same masked walk. Unit tests
use made-up amounts; the integration scenario is the display-low one.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from backend import models
from backend.services.budget_snapshot import (
    LookaheadWindow, _weekly_lows, compute_budget_snapshot,
)

TODAY = date(2026, 3, 20)
CUSHION = Decimal("1000")
LATE = Decimal("40.00")


def _window(balances, mask=None, start=TODAY):
    days = [
        SimpleNamespace(date=start + timedelta(days=i), projected_balance=Decimal(str(b)))
        for i, b in enumerate(balances)
    ]
    mask = mask if mask is not None else [True] * len(days)
    return LookaheadWindow(minimum=Decimal("0"), minimum_date=None, days=days, mask=mask)


def test_buckets_are_rolling_weeks_from_as_of():
    out = _weekly_lows(_window([5000] * 20), TODAY, CUSHION)
    assert [w.start for w in out] == [date(2026, 3, 20), date(2026, 3, 27), date(2026, 4, 3)]
    assert [w.end for w in out] == [date(2026, 3, 26), date(2026, 4, 2), date(2026, 4, 8)]


def test_short_last_bucket():
    out = _weekly_lows(_window([5000] * 9), TODAY, CUSHION)
    assert len(out) == 2
    assert out[1].end == TODAY + timedelta(days=8)


def test_empty_window_gives_no_buckets():
    assert _weekly_lows(_window([]), TODAY, CUSHION) == []


def test_days_before_as_of_ignored():
    w = _window([-999] + [5000] * 7, start=TODAY - timedelta(days=1))
    out = _weekly_lows(w, TODAY, CUSHION)
    assert len(out) == 1
    assert out[0].start == TODAY
    assert out[0].amount == Decimal("5000")


def test_masked_days_excluded():
    balances = [3000, 100, 2000, 2500, 2600, 2700, 2800] + [4000] * 7
    mask = [True, False] + [True] * 12
    out = _weekly_lows(_window(balances, mask), TODAY, CUSHION)
    assert out[0].amount == Decimal("2000")
    assert out[0].date == TODAY + timedelta(days=2)


def test_all_masked_bucket_is_gap():
    balances = [3000] * 7 + [10] * 7
    mask = [True] * 7 + [False] * 7
    out = _weekly_lows(_window(balances, mask), TODAY, CUSHION)
    assert out[1].amount is None
    assert out[1].date is None
    assert out[1].status == "ok"


def test_status_uses_cushion_status():
    lows = ["1000.00", "999.99", "-0.01", "0.00"]
    balances = []
    for low in lows:
        balances += [low] + ["9000"] * 6
    out = _weekly_lows(_window(balances), TODAY, CUSHION)
    assert [w.status for w in out] == ["ok", "warning", "danger", "warning"]


def test_tie_goes_to_earliest_day():
    balances = [5000, 1200, 5000, 1200, 5000, 5000, 5000]
    out = _weekly_lows(_window(balances), TODAY, CUSHION)
    assert out[0].date == TODAY + timedelta(days=1)


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


def test_min_of_buckets_equals_lookahead_minimum(db_session, monkeypatch):
    user, account = _scenario(db_session, monkeypatch)
    snap = compute_budget_snapshot(db_session, user, account.id, as_of=TODAY)

    non_null = [w for w in snap.weekly_lows if w.amount is not None]
    assert non_null
    assert min(w.amount for w in non_null) == snap.lookahead_minimum
    first = next(w for w in non_null if w.amount == snap.lookahead_minimum)
    assert first.date == snap.lookahead_minimum_date
    assert snap.weekly_lows[0].start == TODAY
