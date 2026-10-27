"""GET /accounts/{id}/pending-transactions: checking's bank-pending rows
for the Transactions page, under the same rule the forecast uses -- only a
checking account an ACTIVE Plaid link keeps fresh. Owner-scoped.

All figures are invented; the repo is public."""
from datetime import date, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import accounts as accounts_router


def _user(db, username):
    user = models.User(username=username, hashed_password="x", display_name="the user")
    db.add(user)
    db.flush()
    return user


def _account(db, user, kind=models.AccountType.checking):
    account = models.Account(user_id=user.id, name="Checking", type=kind, current_balance=Decimal("100.00"))
    db.add(account)
    db.flush()
    return account


def _link(db, user, account, *, provider="plaid", active=True):
    connection = models.BankConnection(user_id=user.id, provider=provider, access_url_encrypted="tok",
                                       plaid_item_id=f"item-{account.id}-{provider}-{active}")
    db.add(connection)
    db.flush()
    db.add(models.BankConnectionAccountLink(connection_id=connection.id, simplefin_account_id=f"a-{account.id}",
                                            simplefin_account_name="Checking", local_account_id=account.id,
                                            is_active=active))
    db.flush()


def _row(db, user, account, amount, description, ext):
    db.add(models.AccountPendingTransaction(
        user_id=user.id, account_id=account.id, external_id=ext, date=date(2027, 3, 26),
        amount=Decimal(amount), description=description, synced_at=datetime(2027, 1, 1),
    ))
    db.flush()


def _get(db, user, account_id):
    app = FastAPI()
    app.include_router(accounts_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app).get(f"/accounts/{account_id}/pending-transactions")


def test_lists_the_plaid_fed_checking_snapshot(db_session):
    user = _user(db_session, "pendingowner")
    account = _account(db_session, user)
    _link(db_session, user, account)
    _row(db_session, user, account, "-120.00", "CHASE CREDIT CRD AUTOPAY", "p1")
    _row(db_session, user, account, "-15.00", "COFFEE", "p2")
    db_session.commit()

    response = _get(db_session, user, account.id)
    assert response.status_code == 200
    assert sorted((r["description"], r["amount"], r["account_id"]) for r in response.json()) == [
        ("CHASE CREDIT CRD AUTOPAY", "-120.00", account.id),
        ("COFFEE", "-15.00", account.id),
    ]


def test_empty_without_an_active_plaid_link(db_session):
    user = _user(db_session, "pendingstale")
    inactive = _account(db_session, user)
    _link(db_session, user, inactive, active=False)
    _row(db_session, user, inactive, "-120.00", "CHASE CREDIT CRD AUTOPAY", "p1")
    simplefin = _account(db_session, user)
    _link(db_session, user, simplefin, provider="simplefin")
    _row(db_session, user, simplefin, "-120.00", "CHASE CREDIT CRD AUTOPAY", "p2")
    db_session.commit()

    assert _get(db_session, user, inactive.id).json() == []
    assert _get(db_session, user, simplefin.id).json() == []


def test_empty_for_a_non_checking_account(db_session):
    user = _user(db_session, "pendingsavings")
    savings = _account(db_session, user, kind=models.AccountType.savings)
    _link(db_session, user, savings)
    _row(db_session, user, savings, "-120.00", "TRANSFER", "p1")
    db_session.commit()

    assert _get(db_session, user, savings.id).json() == []


def test_another_users_account_is_not_found(db_session):
    owner = _user(db_session, "pendingrealowner")
    account = _account(db_session, owner)
    _link(db_session, owner, account)
    _row(db_session, owner, account, "-120.00", "CHASE CREDIT CRD AUTOPAY", "p1")
    intruder = _user(db_session, "pendingintruder")
    db_session.commit()

    assert _get(db_session, intruder, account.id).status_code == 404
