from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import networth as networth_router_module


def _client(db_session, user):
    app = FastAPI()
    app.include_router(networth_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db):
    user = models.User(username="n", hashed_password="x", display_name="N")
    db.add(user); db.flush()
    db.add(models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                          current_balance=Decimal("1000.00")))
    db.commit()
    return user


def test_capturing_twice_in_a_day_replaces_rather_than_duplicates(db_session):
    """Two rows for one date is never a meaningful state -- it puts a vertical
    step in the trend line and doubles the row in history. Re-capturing is
    also the natural way to correct a figure."""
    user = _seed(db_session)
    c = _client(db_session, user)

    first = c.post("/net-worth/snapshot").json()
    acct = db_session.query(models.Account).filter_by(user_id=user.id).first()
    acct.current_balance = Decimal("2500.00")
    db_session.commit()
    second = c.post("/net-worth/snapshot").json()

    assert second["id"] == first["id"]
    history = c.get("/net-worth/history").json()
    assert len(history) == 1
    assert Decimal(history[0]["net_worth"]) == Decimal("2500.00")


def test_a_snapshot_can_be_deleted(db_session):
    """A wrong snapshot distorted the trend line permanently -- there was no
    way to take one back."""
    user = _seed(db_session)
    c = _client(db_session, user)
    snap = c.post("/net-worth/snapshot").json()

    assert c.delete(f"/net-worth/snapshot/{snap['id']}").status_code == 204
    assert c.get("/net-worth/history").json() == []


def test_cannot_delete_another_users_snapshot(db_session):
    user = _seed(db_session)
    other = models.User(username="n2", hashed_password="x", display_name="N2")
    db_session.add(other); db_session.flush()
    snap = models.NetWorthSnapshot(user_id=other.id, snapshot_date=date.today(),
                                   total_assets=Decimal("1"), total_liabilities=Decimal("0"),
                                   net_worth=Decimal("1"))
    db_session.add(snap); db_session.commit()

    assert _client(db_session, user).delete(f"/net-worth/snapshot/{snap.id}").status_code == 404


def test_earlier_days_keep_their_own_snapshots(db_session):
    """Replacement is scoped to today; history must not collapse."""
    user = _seed(db_session)
    db_session.add(models.NetWorthSnapshot(
        user_id=user.id, snapshot_date=date.today() - timedelta(days=30),
        total_assets=Decimal("500"), total_liabilities=Decimal("0"), net_worth=Decimal("500")))
    db_session.commit()
    c = _client(db_session, user)

    c.post("/net-worth/snapshot")
    c.post("/net-worth/snapshot")
    assert len(c.get("/net-worth/history").json()) == 2
