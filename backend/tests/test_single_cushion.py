"""One cushion for the Safety Margin warning, the risk banner and the Wish
List (Calculation changelog v6). Synthetic figures only.

Guards: the status split is amber below the cushion / red below $0 with the
boundary exactly at the cushion being ok; /risk and the Wish List read
`User.safety_cushion` (not the per-account threshold or the wish setting); the
migration copies an old non-default value into the single setting only when
applied.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from backend import models
from backend.database import migrate_cushions
from backend.routers import forecast as forecast_router
from backend.schemas import ForecastEntry
from backend.services import wish_plan
from backend.services.cushion import DEFAULT_CUSHION, cushion_for, cushion_status
from backend.services.forecast_engine import risk_status


def _user(db, name="cush", **fields):
    u = models.User(username=name, hashed_password="x", display_name=name, **fields)
    db.add(u); db.flush()
    return u


def _checking(db, user, balance="500.00", **fields):
    a = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                       current_balance=Decimal(balance), **fields)
    db.add(a); db.flush()
    return a


@pytest.mark.parametrize("value,expected", [
    ("-0.01", "danger"), ("0", "warning"), ("999.99", "warning"), ("1000", "ok"), ("1000.01", "ok"),
])
def test_status_boundaries(value, expected):
    assert cushion_status(Decimal(value), Decimal("1000")) == expected


def test_zero_cushion_leaves_only_the_below_zero_signal():
    assert cushion_status(Decimal("0"), Decimal("0")) == "ok"
    assert cushion_status(Decimal("-1"), Decimal("0")) == "danger"


def test_cushion_for_defaults_and_honors_setting(db_session):
    u = _user(db_session)
    assert cushion_for(u) == DEFAULT_CUSHION == Decimal("1000")
    u.safety_cushion = Decimal("250.00")
    assert cushion_for(u) == Decimal("250.00")
    u.safety_cushion = Decimal("0")
    assert cushion_for(u) == Decimal("0")


def test_risk_status_uses_window_minimum():
    d = date(2026, 3, 1)

    def mk(i, b):
        return ForecastEntry(date=d + timedelta(days=i), projected_balance=Decimal(b), transactions=[])

    assert risk_status([], Decimal("1000")) == "ok"
    assert risk_status([mk(0, "1500"), mk(1, "900")], Decimal("1000")) == "warning"
    assert risk_status([mk(0, "900"), mk(1, "-5")], Decimal("1000")) == "danger"


def test_risk_banner_uses_cushion(db_session):
    db = db_session
    # The account threshold is retired: a stale value must not move the banner.
    u = _user(db, safety_cushion=Decimal("400.00"))
    acct = _checking(db, u, balance="500.00", low_balance_threshold=Decimal("5000.00"))
    db.commit()

    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=30, db=db, user=u)
    assert risk.threshold == Decimal("400.00")
    assert risk.at_risk is False
    assert risk.status == "ok"

    u.safety_cushion = Decimal("600.00")
    db.commit()
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=30, db=db, user=u)
    assert risk.threshold == Decimal("600.00")
    assert risk.at_risk is True
    assert risk.status == "warning"

    acct.current_balance = Decimal("-20.00")
    db.commit()
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=30, db=db, user=u)
    assert risk.status == "danger"


def test_risk_banner_defaults_to_one_thousand(db_session):
    db = db_session
    u = _user(db)
    acct = _checking(db, u, balance="500.00")
    db.commit()
    risk = forecast_router.get_forecast_risk(account_id=acct.id, days=30, db=db, user=u)
    assert risk.threshold == Decimal("1000")
    assert risk.status == "warning"


def test_wish_uses_cushion(db_session):
    db = db_session
    u = _user(db, safety_cushion=Decimal("750.00"))
    acct = _checking(db, u, low_balance_threshold=Decimal("3000.00"))
    db.add(models.WishSettings(user_id=u.id, cushion=Decimal("2000.00")))
    db.commit()
    assert wish_plan.effective_cushion(db, u, acct.id) == Decimal("750.00")
    u.safety_cushion = None
    assert wish_plan.effective_cushion(db, u, acct.id) == Decimal("1000")


def test_migration_dry_run_changes_nothing(db_session):
    db = db_session
    u = _user(db, "mig")
    _checking(db, u, low_balance_threshold=Decimal("1500.00"))
    db.add(models.WishSettings(user_id=u.id, cushion=Decimal("2000.00")))
    db.commit()
    log = migrate_cushions(db, apply=False)
    db.refresh(u)
    assert u.safety_cushion is None
    assert len(log) == 1 and "wish_settings" in log[0]


def test_migration_apply_copies_wish_then_account_value(db_session):
    db = db_session
    # Account value only -> copied from the primary checking account.
    u = _user(db, "mig")
    _checking(db, u, low_balance_threshold=Decimal("1500.00"))
    # Wish value wins over the account value.
    u2 = _user(db, "mig2")
    _checking(db, u2, low_balance_threshold=Decimal("1500.00"))
    db.add(models.WishSettings(user_id=u2.id, cushion=Decimal("2000.00")))
    # Zero and null are skipped; an existing setting is never overwritten.
    u3 = _user(db, "mig3")
    _checking(db, u3, low_balance_threshold=Decimal("0"))
    db.add(models.WishSettings(user_id=u3.id, cushion=Decimal("0")))
    u4 = _user(db, "mig4", safety_cushion=Decimal("300.00"))
    _checking(db, u4, low_balance_threshold=Decimal("1500.00"))
    db.commit()

    migrate_cushions(db, apply=True)
    for u_ in (u, u2, u3, u4):
        db.refresh(u_)
    assert u.safety_cushion == Decimal("1500.00")
    assert u2.safety_cushion == Decimal("2000.00")
    assert u3.safety_cushion is None
    assert u4.safety_cushion == Decimal("300.00")


def test_user_out_exposes_resolved_cushion_and_raw_setting(db_session):
    from backend.schemas import UserOut
    u = _user(db_session, "res")
    out = UserOut.model_validate(u).model_dump()
    assert out["safety_cushion"] is None                      # raw setting stays nullable
    assert out["safety_cushion_effective"] == Decimal("1000")  # server-resolved default
    u.safety_cushion = Decimal("250.00")
    out = UserOut.model_validate(u).model_dump()
    assert out["safety_cushion"] == Decimal("250.00")
    assert out["safety_cushion_effective"] == Decimal("250.00")


def test_snapshot_cushion_is_always_resolved(db_session):
    from backend.services.budget_snapshot import compute_budget_snapshot
    u = _user(db_session, "snapres")
    acct = _checking(db_session, u)
    db_session.commit()
    assert compute_budget_snapshot(db_session, u, acct.id).safety_cushion == Decimal("1000")
