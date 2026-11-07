"""One forecast walk policy, and overrides keyed by the natural due date.

Every consumer reads the same standard walk (forecast_walk.standard_walk):
it starts WALK_LOOKBACK_DAYS before as_of, and its purpose picks the
include_unbilled_card_bills flag. Callers that need an earlier start (the
Forecast tab's year views, /monthly-summary) keep their own range, but every
start must give the same balance on every day from today on.

The weekend rule: a BillAmountOverride is keyed by the item's natural due
date. The weekend shift moves only the day it posts.

Synthetic figures throughout; "today" is pinned.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from backend import models
from backend.routers import forecast as forecast_router
from backend.services.forecast_engine import build_forecast, find_balance_risk
from backend.services.forecast_walk import WALK_LOOKBACK_DAYS, standard_walk
from backend.services.month_base import build_month_base
from backend.services.upcoming_bills import upcoming_bills

TODAY = date(2026, 4, 22)  # a Wednesday
HORIZON = TODAY - timedelta(days=WALK_LOOKBACK_DAYS)
END = TODAY + timedelta(days=120)


def _freeze_today(monkeypatch, fixed: date) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)
    monkeypatch.setattr("backend.services.budget_snapshot.date", _FixedDate)
    monkeypatch.setattr(forecast_router, "_today", lambda: fixed)


def _user_and_checking(db, name: str, balance: str = "5000.00", **user_fields):
    user = models.User(username=name, hashed_password="x", display_name="W", **user_fields)
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal(balance),
    )
    db.add(account)
    db.flush()
    return user, account


def _monthly(db, user, account, name, amount, day, kind=models.RecurringType.expense, **extra):
    item = models.RecurringItem(
        user_id=user.id, account_id=account.id, name=name, amount=Decimal(amount),
        type=kind, frequency=models.RecurringFrequency.monthly, day_of_month=day,
        start_date=date(2026, 1, 1), **extra,
    )
    db.add(item)
    db.flush()
    return item


def _actual(db, user, account, when, amount, description, item=None):
    db.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=when, amount=Decimal(amount),
        description=description, is_actual=True,
        recurring_item_id=item.id if item else None,
        source=models.TransactionSource.bank_sync,
    ))


def _parity_scenario(db, monkeypatch):
    """Paycheck (15th) and rent (3rd) matched in March and April but never in
    January or February: old unmatched projections from before the horizon.
    A gym bill (20th) never matched: one projection 33 days back, inside the
    horizon but outside the old 7-day bridge, and one 2 days back. An
    unlinked purchase posted today. One card with a locked statement and a
    flat monthly estimate."""
    _freeze_today(monkeypatch, TODAY)
    user, account = _user_and_checking(db, "walkparity")
    pay = _monthly(db, user, account, "Paycheck", "2000.00", 15, models.RecurringType.income)
    rent = _monthly(db, user, account, "Rent", "1200.00", 3)
    _monthly(db, user, account, "Gym", "50.00", 20)
    _actual(db, user, account, date(2026, 3, 3), "-1200.00", "Rent", rent)
    _actual(db, user, account, date(2026, 3, 13), "2000.00", "Paycheck", pay)
    _actual(db, user, account, date(2026, 4, 3), "-1200.00", "Rent", rent)
    _actual(db, user, account, date(2026, 4, 15), "2000.00", "Paycheck", pay)
    _actual(db, user, account, TODAY, "-10.00", "Coffee")
    db.add(models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=25, is_active=True,
        current_balance=Decimal("1300.00"), balance_due=Decimal("800.00"),
        pending_charges=Decimal("0"), next_payment_date=date(2026, 4, 25),
        monthly_spend_estimate=Decimal("300.00"),
    ))
    db.commit()
    return user, account


def _balances(entries, since: date) -> dict[date, Decimal]:
    return {e.date: e.projected_balance for e in entries if e.date >= since}


@pytest.mark.parametrize("include_unbilled", [True, False])
@pytest.mark.parametrize("start", [
    pytest.param(date(2026, 1, 1), id="jan1_tab"),
    pytest.param(date(2026, 4, 1), id="month_start"),
    pytest.param(TODAY, id="today"),
    pytest.param(date(2026, 5, 1), id="future_month"),
])
def test_tab_and_standard_walk_agree_from_today(db_session, monkeypatch, start, include_unbilled):
    user, account = _parity_scenario(db_session, monkeypatch)
    purpose = "display" if include_unbilled else "safety"
    standard = _balances(
        standard_walk(db_session, user.id, account.id, TODAY, END, purpose=purpose), TODAY,
    )
    walk = build_forecast(db_session, user.id, account.id, start, END,
                          include_unbilled_card_bills=include_unbilled)
    since = max(start, TODAY)
    other = _balances(walk, since)
    assert other == {d: b for d, b in standard.items() if d >= since}


def test_standard_walk_starts_at_the_horizon_and_counts_recent_unmatched(db_session, monkeypatch):
    user, account = _parity_scenario(db_session, monkeypatch)
    days = standard_walk(db_session, user.id, account.id, TODAY, END)
    assert days[0].date == HORIZON
    # Today's balance: the bank's 5000.00 (which already has today's coffee
    # in it) less the two unmatched gym projections in the horizon.
    today_entry = next(e for e in days if e.date == TODAY)
    assert today_entry.projected_balance == Decimal("4900.00")


def test_risk_and_display_lows_agree(db_session, monkeypatch):
    user, account = _parity_scenario(db_session, monkeypatch)
    user.safety_cushion = Decimal("4950.00")
    db_session.commit()

    risk = forecast_router.get_forecast_risk(account_id=account.id, days=90, db=db_session, user=user)

    display = [e for e in build_forecast(db_session, user.id, account.id, date(2026, 1, 1), TODAY + timedelta(days=90))
               if e.date >= TODAY]
    expected = find_balance_risk(display, Decimal("4950.00"))
    assert expected["at_risk"] is True
    assert (risk.at_risk, risk.date, risk.amount) == (True, expected["date"], expected["amount"])
    assert risk.date >= TODAY


def _bridge_scenario(db, monkeypatch):
    """Today 2026-03-20. Card closes the 28th, due the 25th, $1,500.00 locked
    for 3/25. A $40.00 card subscription charged the 25th is this month's and
    not yet charged, so it rides the 4/25 cycle only in the display walk."""
    today = date(2026, 3, 20)
    _freeze_today(monkeypatch, today)
    user, account = _user_and_checking(db, "walkbridge", balance="3000.00")
    card = models.CreditCard(
        user_id=user.id, name="Chase", credit_limit=Decimal("10000.00"),
        statement_day=28, due_day=25, is_active=True,
        current_balance=Decimal("2000.00"), balance_due=Decimal("1500.00"),
        pending_charges=Decimal("0"), next_payment_date=date(2026, 3, 25),
        monthly_spend_estimate=Decimal("1.00"),
    )
    db.add(card)
    db.flush()
    _monthly(db, user, account, "Late", "40.00", 25, card_id=card.id)
    _monthly(db, user, account, "Paycheck", "100.00", 15, models.RecurringType.income)
    db.commit()
    return user, account, today


def test_bridge_keeps_unbilled_flag(db_session, monkeypatch):
    user, account, today = _bridge_scenario(db_session, monkeypatch)
    start, end = date(2026, 5, 1), date(2026, 7, 31)
    safety = _balances(standard_walk(db_session, user.id, account.id, today, end, purpose="safety"), start)
    display = _balances(standard_walk(db_session, user.id, account.id, today, end, purpose="display"), start)
    # The flag really matters on these days: the 4/25 payoff carries "Late".
    assert display[start] == safety[start] - Decimal("40.00")

    future_safety = build_forecast(db_session, user.id, account.id, start, end,
                                   include_unbilled_card_bills=False)
    assert _balances(future_safety, start) == safety


SS_FIELDS = dict(
    ss_gross_per_paycheck=Decimal("7000.00"),
    ss_wage_base=Decimal("1000.00"),
    ss_bonus_ytd=Decimal("2000.00"),  # base already met: every check is boosted
)
BOOST = Decimal("434.00")  # 7000.00 * 6.2%


def _override(db, user, item, due, amount):
    db.add(models.BillAmountOverride(
        user_id=user.id, recurring_item_id=item.id, due_date=due, actual_amount=Decimal(amount),
    ))


def test_weekend_override_applies_on_shifted_day(db_session, monkeypatch):
    _freeze_today(monkeypatch, TODAY)
    user, account = _user_and_checking(db_session, "walkweekend")
    electric = _monthly(db_session, user, account, "Electric", "100.00", 9)
    saturday, friday = date(2026, 5, 9), date(2026, 5, 8)
    assert saturday.weekday() == 5
    _override(db_session, user, electric, saturday, "123.45")
    db_session.commit()

    # Forecast: posts on the Friday, at the override amount. A window that
    # ends on that Friday still finds the Saturday override.
    for end in (date(2026, 5, 31), friday):
        days = {e.date: e for e in build_forecast(db_session, user.id, account.id, TODAY, end)}
        lines = [t for t in days[friday].transactions if t.name == "Electric"]
        assert [t.amount for t in lines] == [Decimal("-123.45")]
    days = {e.date: e for e in build_forecast(db_session, user.id, account.id, TODAY, date(2026, 5, 31))}
    assert not any(t.name == "Electric" for t in days[saturday].transactions)

    base = build_month_base(db_session, user, 2026, 5)
    assert [(o.date, o.amount) for o in base.monthly_bills if o.name == "Electric"] == [
        (saturday, Decimal("123.45")),
    ]

    bills = [b for b in upcoming_bills(db_session, user.id, TODAY, 30) if b.name == "Electric"]
    assert [(b.due_date, b.amount, b.is_actual) for b in bills] == [(saturday, Decimal("123.45"), True)]


def test_paycheck_override_keeps_its_ss_boost(db_session, monkeypatch):
    """An override replaces a paycheck's base amount; the Social Security
    boost still applies on top. One payday falls on a Saturday (posts
    Friday), one on a weekday."""
    _freeze_today(monkeypatch, TODAY)
    user, account = _user_and_checking(db_session, "walkpay", **SS_FIELDS)
    weekend_pay = _monthly(db_session, user, account, "Pay A", "5000.00", 9, models.RecurringType.income)
    weekday_pay = _monthly(db_session, user, account, "Pay B", "5000.00", 15, models.RecurringType.income)
    _override(db_session, user, weekend_pay, date(2026, 5, 9), "5100.00")
    _override(db_session, user, weekday_pay, date(2026, 5, 15), "5200.00")
    db_session.commit()

    days = {e.date: e for e in build_forecast(db_session, user.id, account.id, TODAY, date(2026, 5, 31))}
    assert [t.amount for t in days[date(2026, 5, 8)].transactions if t.name == "Pay A"] == [
        Decimal("5100.00") + BOOST,
    ]
    assert [t.amount for t in days[date(2026, 5, 15)].transactions if t.name == "Pay B"] == [
        Decimal("5200.00") + BOOST,
    ]

    bills = {b.name: b for b in upcoming_bills(db_session, user.id, TODAY, 30)}
    assert (bills["Pay A"].amount, bills["Pay A"].is_actual) == (Decimal("5100.00") + BOOST, True)
    assert (bills["Pay B"].amount, bills["Pay B"].is_actual) == (Decimal("5200.00") + BOOST, True)


def test_standard_walk_rejects_an_unknown_purpose(db_session):
    with pytest.raises(ValueError):
        standard_walk(db_session, 1, 1, TODAY, END, purpose="lows")
