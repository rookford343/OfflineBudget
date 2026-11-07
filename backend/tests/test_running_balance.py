"""Transactions running balance (services/account_balances.py,
GET /accounts/{id}/running-balance). All figures are invented; the repo is public."""
from datetime import date, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import accounts as accounts_router
from backend.services.account_balances import account_balances, running_balance

from backend.tests.test_account_balances import TODAY, _account, _live, _user


def _txn(db, user, account, amount, day):
    row = models.Transaction(user_id=user.id, account_id=account.id, date=day,
                             amount=Decimal(amount), description="row", is_actual=True)
    db.add(row)
    db.flush()
    return row


def _pend(db, user, account, amount, day, ext):
    row = models.AccountPendingTransaction(
        user_id=user.id, account_id=account.id, external_id=ext, date=day,
        amount=Decimal(amount), description=f"pending {ext}", synced_at=datetime(2027, 3, 15))
    db.add(row)
    db.flush()
    return row


def test_posted_rows_walk_backward_from_posted(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "1000.00")
    newest = _txn(db_session, user, acct, "-100.00", date(2027, 3, 14))
    older = _txn(db_session, user, acct, "300.00", date(2027, 3, 10))
    rows = running_balance(db_session, user.id, acct.id, date(2027, 3, 1), TODAY)
    assert [(r.kind, r.id, r.balance_after) for r in rows] == [
        ("posted", newest.id, Decimal("1000.00")),
        ("posted", older.id, Decimal("1100.00")),
    ]


def test_pending_rows_walk_forward_to_after_pending(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "1000.00")
    _live(db_session, user, acct)
    late = _pend(db_session, user, acct, "-50.00", date(2027, 3, 15), "late")
    early = _pend(db_session, user, acct, "200.00", date(2027, 3, 13), "early")
    rows = running_balance(db_session, user.id, acct.id, date(2027, 3, 1), TODAY)
    assert [(r.kind, r.id, r.balance_after) for r in rows] == [
        ("pending", early.id, Decimal("1200.00")),
        ("pending", late.id, Decimal("1150.00")),
    ]
    after = account_balances(db_session, user.id, TODAY).accounts[0].after_pending
    assert rows[-1].balance_after == after


def test_pending_rows_absent_when_snapshot_not_live(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "1000.00")
    _pend(db_session, user, acct, "-50.00", TODAY, "x")
    assert running_balance(db_session, user.id, acct.id, date(2027, 3, 1), TODAY) == []


def test_only_requested_account(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "1000.00")
    other = _account(db_session, user, "500.00", name="Other")
    mine = _txn(db_session, user, acct, "-10.00", date(2027, 3, 12))
    _txn(db_session, user, other, "-99.00", date(2027, 3, 12))
    rows = running_balance(db_session, user.id, acct.id, date(2027, 3, 1), TODAY)
    assert [r.id for r in rows] == [mine.id]


def test_start_bounds_posted_rows(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "1000.00")
    _txn(db_session, user, acct, "-10.00", date(2027, 2, 28))
    inside = _txn(db_session, user, acct, "-20.00", date(2027, 3, 1))
    rows = running_balance(db_session, user.id, acct.id, date(2027, 3, 1), TODAY)
    assert [r.id for r in rows] == [inside.id]


def test_endpoint_shape_and_ownership(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "1000.00")
    stranger = _user(db_session, "stranger")
    foreign = _account(db_session, stranger, "5.00", name="Theirs")
    txn = _txn(db_session, user, acct, "-10.00", date.today())
    app = FastAPI()
    app.include_router(accounts_router.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    resp = client.get(f"/accounts/{acct.id}/running-balance", params={"start": "2000-01-01"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body[0]) == {"kind", "id", "date", "balance_after"}
    assert body[0]["id"] == txn.id and Decimal(body[0]["balance_after"]) == Decimal("1000.00")
    assert client.get(f"/accounts/{foreign.id}/running-balance",
                      params={"start": "2000-01-01"}).status_code == 404
