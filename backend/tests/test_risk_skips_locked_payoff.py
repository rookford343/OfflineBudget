"""The risk banner skips locked statement-payment dips, like the 3-month low
(Calculation changelog v9). Synthetic figures only, today pinned to 2026-03-20.

Guards: a dip below the cushion caused only by a locked card payoff leaves
/risk ok; a dip from an ordinary bill still warns; /risk's lowest balance over
its window equals the snapshot's floor-masked minimum over the same window.
"""
from datetime import date, timedelta
from decimal import Decimal

from backend import models
from backend.routers import forecast as forecast_router
from backend.services import budget_snapshot
from backend.services.forecast_engine import build_forecast
from backend.services.summary_generator import generate_weekly_digest

TODAY = date(2026, 3, 20)


def _freeze(monkeypatch, today=TODAY):
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return today
    for mod in ("forecast_engine", "budget_snapshot", "summary_generator"):
        monkeypatch.setattr(f"backend.services.{mod}.date", _FixedDate)
    monkeypatch.setattr(forecast_router, "_today", lambda: today)


def _scenario(db, monkeypatch, *, balance, with_card, bill=None, today=TODAY, payday=date(2026, 4, 1), bill_day=25):
    _freeze(monkeypatch, today)
    user = models.User(username="riskmask", hashed_password="x", display_name="R")
    db.add(user); db.flush()
    acct = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal(balance),
    )
    db.add(acct); db.flush()
    if with_card:
        db.add(models.CreditCard(
            user_id=user.id, name="Chase", credit_limit=Decimal("10000.00"),
            statement_day=28, due_day=25, is_active=True,
            current_balance=Decimal("1500.00"), balance_due=Decimal("1500.00"),
            pending_charges=Decimal("0"), next_payment_date=date(2026, 3, 25),
            monthly_spend_estimate=Decimal("1.00"),
        ))
    if bill:
        db.add(models.RecurringItem(
            user_id=user.id, account_id=acct.id, name="Big bill",
            amount=Decimal(bill), type=models.RecurringType.expense,
            frequency=models.RecurringFrequency.monthly, day_of_month=bill_day,
            start_date=date(2026, 1, 1),
        ))
    db.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, name="Paycheck",
        amount=Decimal("5000.00"), type=models.RecurringType.income,
        frequency=models.RecurringFrequency.monthly, day_of_month=1,
        start_date=payday,
    ))
    db.commit()
    return user, acct


def test_locked_payoff_dip_alone_is_not_a_risk(db_session, monkeypatch):
    # 2000 - 1500 locked payoff = 500, below the 1000 cushion until the 4/1 payday.
    user, acct = _scenario(db_session, monkeypatch, balance="2000.00", with_card=True)
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=20, db=db_session, user=user)
    assert risk.status == "ok"
    assert risk.at_risk is False


def test_ordinary_dip_below_cushion_still_warns(db_session, monkeypatch):
    user, acct = _scenario(db_session, monkeypatch, balance="2000.00", with_card=False, bill="600.00")
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=20, db=db_session, user=user)
    assert risk.status == "warning"
    assert risk.at_risk is True
    assert risk.date == date(2026, 3, 25)
    assert risk.amount == Decimal("800.00")


def test_weekly_digest_skips_locked_payoff_too(db_session, monkeypatch):
    user, acct = _scenario(db_session, monkeypatch, balance="2000.00", with_card=True)
    digest = generate_weekly_digest(db_session, user, acct.id)
    # The payoff dip is skipped; only a later, non-locked low could flag.
    assert digest.risk.at_risk is False
    assert digest.risk.status == "ok"


def test_risk_minimum_matches_snapshot_floor(db_session, monkeypatch):
    user, acct = _scenario(db_session, monkeypatch, balance="2000.00", with_card=True)
    end = TODAY + timedelta(days=90)
    days = build_forecast(db_session, user.id, acct.id, TODAY - timedelta(days=45), end)
    mask = budget_snapshot.floor_mask(days, db_session.query(models.CreditCard).all())
    snap_min, _ = budget_snapshot._floor_minimum(days, mask, TODAY, end=end)

    # Set the cushion just above the snapshot floor: /risk must report that
    # exact minimum as its first breach, so it is the lowest the banner sees.
    user.safety_cushion = snap_min + Decimal("0.01")
    db_session.commit()
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=90, db=db_session, user=user)
    assert risk.at_risk is True
    assert risk.amount == snap_min
    assert risk.status == "warning"




def test_start_inside_a_locked_dip_matches_the_dashboard_floor(db_session, monkeypatch):
    # Today (3/27) sits inside the dip that began with the 3/25 payoff and ends
    # at the 4/1 payday: /risk must mask it just as the Dashboard does.
    today = date(2026, 3, 27)
    user, acct = _scenario(db_session, monkeypatch, balance="2000.00", with_card=True, today=today)
    window = budget_snapshot._lookahead_window(db_session, user.id, acct.id, today, 1, include_unbilled_card_bills=True)
    user.safety_cushion = window.minimum + Decimal("0.01")
    db_session.commit()
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=20, db=db_session, user=user)
    assert risk.at_risk is True
    assert risk.amount == window.minimum
    assert risk.date >= date(2026, 4, 1)
    user.safety_cushion = Decimal("1000")
    db_session.commit()
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=20, db=db_session, user=user)
    assert risk.status == "ok" and risk.at_risk is False


def test_suggestion_is_sized_from_the_unmasked_walk(db_session, monkeypatch):
    # An ordinary 3/22 bill dips below the cushion; the locked 1500 payoff on
    # 3/25 is still money leaving checking, so the transfer must cover it.
    user, acct = _scenario(db_session, monkeypatch, balance="2100.00", with_card=True,
                           bill="600.00", bill_day=22)
    days = build_forecast(db_session, user.id, acct.id, TODAY, TODAY + timedelta(days=20))
    raw_min = min(d.projected_balance for d in days)
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=20, db=db_session, user=user)
    assert risk.at_risk is True
    masked_dip = Decimal("900.00")  # the 3/22 bill alone
    assert raw_min < masked_dip
    expected = ((Decimal("1000") - raw_min) / Decimal("1000")).to_integral_value(rounding="ROUND_CEILING") * Decimal("1000")
    assert risk.suggested_transfer_amount == expected
    assert expected > (Decimal("1000") - masked_dip)


def test_locked_only_overdraft_is_danger_with_the_negative_day(db_session, monkeypatch):
    # 1200 - 1500 locked payoff = -300 on 3/25: an actual overdraft still warns.
    user, acct = _scenario(db_session, monkeypatch, balance="1200.00", with_card=True)
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=20, db=db_session, user=user)
    assert risk.status == "danger"
    assert risk.at_risk is True
    assert risk.date == date(2026, 3, 25)
    assert risk.amount == Decimal("-300.00")
    digest = generate_weekly_digest(db_session, user, acct.id)
    assert digest.risk.status == "danger" and digest.risk.date == date(2026, 3, 25)


def test_all_masked_window_falls_back_to_the_raw_walk(db_session, monkeypatch):
    # No payday inside the window: every day from the payoff on is masked, so
    # the banner reads the raw dip rather than reporting nothing.
    user, acct = _scenario(db_session, monkeypatch, balance="2000.00", with_card=True,
                           today=date(2026, 3, 27), payday=date(2026, 6, 1))
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=10, db=db_session, user=user)
    assert risk.at_risk is True
    assert risk.amount == Decimal("500.00")
