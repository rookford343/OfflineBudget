"""Net worth has one recipe (services/net_worth.py), shared by the live view and the
stored snapshots. All figures are invented; the repo is public."""
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import networth as networth_router
from backend.services.explain import children_consistent, replay
from backend.services.net_worth import net_worth_totals


def _client(db, user):
    app = FastAPI()
    app.include_router(networth_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db, checking="1000.00", savings="500.00"):
    user = models.User(username="nwowner", hashed_password="x", display_name="the user")
    db.add(user)
    db.flush()
    db.add_all([
        models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                       current_balance=Decimal(checking)),
        models.Account(user_id=user.id, name="Sav", type=models.AccountType.savings,
                       current_balance=Decimal(savings)),
        models.Account(user_id=user.id, name="Old", type=models.AccountType.checking,
                       current_balance=Decimal("9999.00"), is_active=False),
        models.CreditCard(user_id=user.id, name="Card A", credit_limit=Decimal("5000"),
                          statement_day=1, due_day=20, current_balance=Decimal("300.00")),
        models.ManualAsset(user_id=user.id, name="Car", asset_type="vehicle",
                           current_value=Decimal("4000.00"), as_of_date=date(2027, 3, 1)),
        models.ManualLiability(user_id=user.id, name="Loan", liability_type="loan",
                                current_balance=Decimal("2000.00"), as_of_date=date(2027, 3, 1)),
    ])
    db.commit()
    return user


def test_live_and_snapshot_agree(db_session):
    user = _seed(db_session)
    c = _client(db_session, user)
    live = c.get("/net-worth").json()
    snap = c.post("/net-worth/snapshot").json()
    for f in ("total_assets", "total_liabilities", "net_worth"):
        assert Decimal(live[f]) == Decimal(snap[f]), f
    assert Decimal(live["manual_assets"]) == Decimal("4000.00")
    assert Decimal(live["account_balances"]) == Decimal("1500.00")
    assert Decimal(live["total_assets"]) == Decimal("5500.00")
    assert Decimal(live["manual_liabilities"]) == Decimal("2000.00")
    assert Decimal(live["card_balances"]) == Decimal("300.00")
    assert Decimal(live["total_liabilities"]) == Decimal("2300.00")
    assert Decimal(live["net_worth"]) == Decimal("3200.00")


def test_overdrawn_checking_reduces_assets(db_session):
    user = _seed(db_session, checking="-250.00", savings="500.00")
    c = _client(db_session, user)
    live = c.get("/net-worth").json()
    snap = c.post("/net-worth/snapshot").json()
    # 4000 manual + (-250 + 500) accounts
    assert Decimal(live["account_balances"]) == Decimal("250.00")
    assert Decimal(live["total_assets"]) == Decimal("4250.00")
    assert Decimal(snap["total_assets"]) == Decimal("4250.00")
    assert Decimal(live["net_worth"]) == Decimal(snap["net_worth"]) == Decimal("1950.00")


def test_explain_replays_to_net_worth(db_session):
    user = _seed(db_session)
    totals = net_worth_totals(db_session, user.id)
    assert replay(totals.explain) == totals.net_worth == totals.explain.result
    assert children_consistent(totals.explain)
    labels = [r.label for r in totals.explain.rows]
    assert "Account balances" in labels and "Card balances" in labels
