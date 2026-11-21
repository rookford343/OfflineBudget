"""Task 2 (Split One-Off Installments): the schema cap (0, 1, and 7+ legs
rejected; 2-6 accepted), create_installment_group's bulk-create behaviour --
numbered names baked in at creation, every leg linked to the first leg's id,
shared account/card/category, outflow-only, funding fields left at their
model defaults -- and two distinct atomicity properties:

  - pre-validation: a caller who doesn't own the account never reaches
    create_installment_group at all, so zero rows are written;
  - mid-batch rollback: even once create_installment_group's first flush has
    already written every leg to the DB, a failure before its second flush
    completes (the one that sets installment_group_id) leaves zero rows once
    the caller rolls back -- the whole group is one transaction, not legs
    trickling in one at a time.

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
from backend.services.budget_snapshot import compute_budget_snapshot
from backend.services.installment_plan import create_installment_group


def _legs(n, amount="50.00"):
    return [
        {"amount": amount, "expected_date": (date.today() + timedelta(days=i)).isoformat()}
        for i in range(n)
    ]


def test_rejects_zero_legs():
    with pytest.raises(ValidationError):
        schemas.PlannedExpenseInstallmentsCreate(name="X", legs=[])


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
    assert all(pe.funding_account_id is None for pe in legs)
    assert all(pe.funding_amount is None for pe in legs)
    assert all(pe.funding_lead_days == 0 for pe in legs)


def test_create_installment_group_rejects_an_account_the_caller_does_not_own(db_session):
    """Pre-validation atomicity only: `_require_owned` 404s before
    create_installment_group is ever called, so this proves "rejected before
    any write", not "rolled back after a partial write". See
    test_create_installment_group_rolls_back_a_partial_write below for the
    mid-batch rollback property."""
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


def test_create_installment_group_rolls_back_a_partial_write(db_session, monkeypatch):
    """create_installment_group flushes twice: the first flush inserts every
    leg (each already has a row/id in the DB); the second flush -- which
    sets installment_group_id on all of them -- is the only thing left that
    can still fail. Forces that second flush to raise, then rolls back the
    way a caller must, and confirms the first flush's legs don't survive --
    the group is one all-or-nothing transaction, not legs trickling in."""
    user, account = _seed(db_session)
    body = schemas.PlannedExpenseInstallmentsCreate(
        name="X", account_id=account.id, legs=[
            {"amount": "10.00", "expected_date": date.today().isoformat()},
            {"amount": "10.00", "expected_date": date.today().isoformat()},
        ],
    )

    real_flush = db_session.flush
    calls = {"n": 0}

    def _fail_on_second_flush(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated failure on the second flush")
        return real_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", _fail_on_second_flush)

    with pytest.raises(RuntimeError):
        create_installment_group(db_session, user, body)
    assert calls["n"] == 2  # confirms the first flush really did write legs first

    db_session.rollback()
    assert db_session.query(models.PlannedExpense).count() == 0


def test_preview_installments_matches_combined_commit(db_session):
    user, account = _seed(db_session)
    client = _client(db_session, user)
    body = {"name": "Leia dental", "account_id": account.id, "legs": [
        {"amount": "50.00", "expected_date": date.today().isoformat()},
        {"amount": "75.00", "expected_date": (date.today() + timedelta(days=30)).isoformat()},
    ]}
    base = compute_budget_snapshot(db_session, user, account.id)
    r = client.post(f"/planned-expenses/installments/preview?account_id={account.id}", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert client.post("/planned-expenses/installments", json=body).status_code == 201
    after = compute_budget_snapshot(db_session, user, account.id)
    assert Decimal(out["safety_margin"]["before"]) == base.safety_margin
    assert Decimal(out["safety_margin"]["after"]) == after.safety_margin
    assert Decimal(out["safety_margin"]["after"]) < Decimal(out["safety_margin"]["before"])


def test_preview_installments_writes_nothing(db_session):
    user, account = _seed(db_session)
    client = _client(db_session, user)
    before = db_session.query(models.PlannedExpense).count()
    body = {"name": "X", "account_id": account.id, "legs": [
        {"amount": "10.00", "expected_date": date.today().isoformat()},
        {"amount": "10.00", "expected_date": (date.today() + timedelta(days=5)).isoformat()},
    ]}
    r = client.post(f"/planned-expenses/installments/preview?account_id={account.id}", json=body)
    assert r.status_code == 200, r.text
    assert db_session.query(models.PlannedExpense).count() == before


def test_preview_installments_lists_one_card_payment_per_distinct_due_date(db_session):
    user, account = _seed(db_session)
    card = models.CreditCard(
        user_id=user.id, name="Test Card", credit_limit=Decimal("5000.00"),
        statement_day=28, due_day=25, balance_due=Decimal("0.00"),
        current_balance=Decimal("0.00"),
    )
    db_session.add(card)
    db_session.commit()
    client = _client(db_session, user)
    # One leg today, one leg ~90 days out -- far enough apart to land on two
    # different statement cycles for any statement_day/due_day combination.
    body = {"name": "Spread out", "card_id": card.id, "legs": [
        {"amount": "20.00", "expected_date": date.today().isoformat()},
        {"amount": "30.00", "expected_date": (date.today() + timedelta(days=90)).isoformat()},
    ]}
    r = client.post(f"/planned-expenses/installments/preview?account_id={account.id}", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    due_dates = {cp["due"] for cp in out["card_payments"]}
    assert len(due_dates) == 2
    assert {Decimal(cp["amount"]) for cp in out["card_payments"]} == {Decimal("20.00"), Decimal("30.00")}
