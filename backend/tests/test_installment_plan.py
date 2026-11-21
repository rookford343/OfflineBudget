"""Task 2 (Split One-Off Installments): the schema cap (2-6 legs, positive
amounts) and create_installment_group's bulk-create behaviour -- numbered
names baked in at creation, every leg linked to the first leg's id, shared
account/card/category, outflow-only, funding fields left null, and the
all-or-nothing atomicity of the bulk-create route (a caller who doesn't own
the account gets zero rows, not a partial group).

All figures are invented; the repo is public."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import models, schemas
from backend.dependencies import get_current_user, get_db
from backend.routers import planned_expenses as pe_router
from backend.services.installment_plan import create_installment_group


def _legs(n, amount="50.00"):
    return [
        {"amount": amount, "expected_date": (date.today() + timedelta(days=i)).isoformat()}
        for i in range(n)
    ]


def test_rejects_fewer_than_two_legs():
    with pytest.raises(ValidationError):
        schemas.PlannedExpenseInstallmentsCreate(name="X", legs=_legs(1))


def test_rejects_more_than_six_legs():
    with pytest.raises(ValidationError):
        schemas.PlannedExpenseInstallmentsCreate(name="X", legs=_legs(7))


def test_accepts_two_to_six_legs():
    for n in (2, 6):
        schemas.PlannedExpenseInstallmentsCreate(name="X", legs=_legs(n))


def test_rejects_a_non_positive_leg_amount():
    with pytest.raises(ValidationError):
        schemas.PlannedExpenseInstallmentsCreate(name="X", legs=_legs(2, amount="0.00"))


def _seed(db):
    user = models.User(username="inst", hashed_password="x", display_name="Inst")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.commit()
    return user, account


def _client(db, user):
    app = FastAPI()
    app.include_router(pe_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_create_installment_group_makes_n_linked_legs_with_numbered_names(db_session):
    user, account = _seed(db_session)
    legs = create_installment_group(db_session, user, schemas.PlannedExpenseInstallmentsCreate(
        name="Leia dental", account_id=account.id, legs=[
            {"amount": "50.00", "expected_date": date.today().isoformat()},
            {"amount": "75.00", "expected_date": (date.today() + timedelta(days=30)).isoformat()},
        ],
    ))
    db_session.commit()
    assert len(legs) == 2
    assert legs[0].name == "Leia dental (1 of 2)"
    assert legs[1].name == "Leia dental (2 of 2)"
    assert legs[0].installment_group_id == legs[0].id
    assert legs[1].installment_group_id == legs[0].id
    assert all(pe.account_id == account.id for pe in legs)
    assert all(pe.direction == models.PlannedDirection.outflow for pe in legs)
    assert all(not pe.is_refund_watch for pe in legs)


def test_create_installment_group_rejects_an_account_the_caller_does_not_own(db_session):
    user, account = _seed(db_session)
    other = models.User(username="other-inst", hashed_password="x", display_name="O")
    db_session.add(other)
    db_session.commit()
    client = _client(db_session, other)
    body = {"name": "X", "account_id": account.id, "legs": [
        {"amount": "10.00", "expected_date": date.today().isoformat()},
        {"amount": "10.00", "expected_date": date.today().isoformat()},
    ]}
    before = db_session.query(models.PlannedExpense).count()
    r = client.post("/planned-expenses/installments", json=body)
    assert r.status_code == 404
    assert db_session.query(models.PlannedExpense).count() == before
