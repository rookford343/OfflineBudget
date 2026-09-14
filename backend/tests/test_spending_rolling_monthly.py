from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import spending as spending_router_module
from backend.dependencies import get_db, get_current_user


def _make_user(db):
    user = models.User(username="roller", hashed_password="x", display_name="Roller")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _client(db, user):
    app = FastAPI()
    app.include_router(spending_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_rolling_monthly_splits_checking_and_cards(db_session):
    user = _make_user(db_session)
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db_session.add(account)
    db_session.flush()
    card = models.CreditCard(
        user_id=user.id, name="Visa", credit_limit=Decimal("5000.00"),
        statement_day=1, due_day=15, current_balance=Decimal("0.00"),
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 5),
        amount=Decimal("-100.00"), description="Mortgage", is_actual=True,
    ))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 6),
        amount=Decimal("40.00"), merchant="Coffee Shop",
    ))
    db_session.commit()

    c = _client(db_session, user)
    resp = c.get("/spending/rolling-monthly", params={"months": 2})

    assert resp.status_code == 200
    rows = {r["month"]: r for r in resp.json()}
    row = rows["2026-08"]
    assert Decimal(row["checking"]) == Decimal("100.00")
    assert Decimal(row["cards"]) == Decimal("40.00")
    assert Decimal(row["total"]) == Decimal("140.00")
