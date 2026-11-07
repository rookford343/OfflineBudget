"""Account balances with pending (services/account_balances.py, GET /accounts/balances).

All figures are invented; the repo is public."""
from datetime import date, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import accounts as accounts_router
from backend.services.account_balances import account_balances

TODAY = date(2027, 3, 15)


def _user(db, name="balowner"):
    user = models.User(username=name, hashed_password="x", display_name="the user")
    db.add(user)
    db.flush()
    return user


def _account(db, user, balance="1000.00", name="Checking", kind=models.AccountType.checking, active=True):
    account = models.Account(user_id=user.id, name=name, type=kind,
                             current_balance=Decimal(balance), is_active=active)
    db.add(account)
    db.flush()
    return account


def _live(db, user, account):
    conn = models.BankConnection(user_id=user.id, provider="plaid", access_url_encrypted="tok",
                                 plaid_item_id=f"item-{account.id}")
    db.add(conn)
    db.flush()
    db.add(models.BankConnectionAccountLink(
        connection_id=conn.id, simplefin_account_id=f"a-{account.id}", simplefin_account_name="Checking",
        local_account_id=account.id, is_active=True))
    db.flush()


def _pending(db, user, account, amount, ext):
    db.add(models.AccountPendingTransaction(
        user_id=user.id, account_id=account.id, external_id=ext, date=TODAY,
        amount=Decimal(amount), description=f"pending {ext}", synced_at=datetime(2027, 3, 15)))
    db.flush()


def _txn(db, user, account, amount, day, actual=True):
    db.add(models.Transaction(user_id=user.id, account_id=account.id, date=day, amount=Decimal(amount),
                              description="row", is_actual=actual))
    db.flush()


def _only(result):
    assert len(result.accounts) == 1
    return result.accounts[0]


def test_after_pending_includes_debits_and_credits(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "1000.00")
    _live(db_session, user, acct)
    _pending(db_session, user, acct, "-200.00", "a")
    _pending(db_session, user, acct, "50.00", "b")
    row = _only(account_balances(db_session, user.id, TODAY))
    assert row.posted == Decimal("1000.00")
    assert row.pending_total == Decimal("-150.00")
    assert row.pending_count == 2
    assert row.after_pending == Decimal("850.00")
    assert sorted(p.amount for p in row.pending) == [Decimal("-200.00"), Decimal("50.00")]


def test_not_live_snapshot_means_posted(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "1000.00")  # no Plaid link: rows are stale
    _pending(db_session, user, acct, "-200.00", "a")
    row = _only(account_balances(db_session, user.id, TODAY))
    assert row.after_pending == Decimal("1000.00")
    assert row.pending_total == Decimal("0")
    assert row.pending_count == 0
    assert row.pending == []


def test_total_is_sum_over_active_accounts(db_session):
    user = _user(db_session)
    chk = _account(db_session, user, "1000.00")
    _live(db_session, user, chk)
    _pending(db_session, user, chk, "-100.00", "a")
    _account(db_session, user, "-250.00", name="Overdrawn")
    _account(db_session, user, "5000.00", name="Closed", active=False)
    other = _user(db_session, "someoneelse")
    _account(db_session, other, "9999.00", name="Not mine")
    result = account_balances(db_session, user.id, TODAY)
    assert len(result.accounts) == 2
    assert result.total_after_pending == Decimal("650.00")


def test_month_change_pct_uses_month_flows(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "1200.00")
    _live(db_session, user, acct)
    _pending(db_session, user, acct, "-100.00", "a")
    _txn(db_session, user, acct, "200.00", date(2027, 3, 3))          # this month, posted
    _txn(db_session, user, acct, "999.00", date(2027, 2, 27))         # last month: not in the flow
    _txn(db_session, user, acct, "-777.00", date(2027, 3, 20), actual=False)  # planned: not in the flow
    row = _only(account_balances(db_session, user.id, TODAY))
    assert row.month_start_balance == Decimal("1000.00")  # 1200 - 200
    assert row.after_pending == Decimal("1100.00")
    assert row.month_change_pct == Decimal("10.00")


def test_month_change_pct_none_when_start_zero(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "300.00")
    _txn(db_session, user, acct, "300.00", date(2027, 3, 2))
    row = _only(account_balances(db_session, user.id, TODAY))
    assert row.month_start_balance == Decimal("0.00")
    assert row.month_change_pct is None


def test_negative_start_uses_absolute_value(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "-50.00")
    _txn(db_session, user, acct, "50.00", date(2027, 3, 2))  # start = -100, now -50
    row = _only(account_balances(db_session, user.id, TODAY))
    assert row.month_change_pct == Decimal("50.00")


def test_endpoint_shape(db_session):
    user = _user(db_session)
    acct = _account(db_session, user, "1000.00")
    _live(db_session, user, acct)
    _pending(db_session, user, acct, "-200.00", "a")
    app = FastAPI()
    app.include_router(accounts_router.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    resp = TestClient(app).get("/accounts/balances")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"accounts", "total_after_pending"}
    assert Decimal(body["total_after_pending"]) == Decimal("800.00")
    row = body["accounts"][0]
    assert set(row) == {"account_id", "posted", "pending_total", "pending_count", "pending",
                        "after_pending", "month_start_balance", "month_change_pct"}
    assert row["account_id"] == acct.id and row["pending_count"] == 1
    assert row["pending"][0]["description"] == "pending a"
