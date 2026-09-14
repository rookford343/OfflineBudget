from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import spending as spending_router_module
from backend.routers.spending import _MAX_STACK_CATEGORIES
from backend.dependencies import get_db, get_current_user


def _make_user(db):
    user = models.User(username="flow", hashed_password="x", display_name="Flow")
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


def test_small_categories_collapse_into_other_uncategorized_stays_separate(db_session):
    user = _make_user(db_session)
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db_session.add(account)
    db_session.flush()

    # Add some income so the sankey diagram has a flow
    income_cat = models.Category(
        user_id=user.id, name="Salary", type=models.CategoryType.income,
        color="#00FF00", sort_order=0,
    )
    db_session.add(income_cat)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 1),
        amount=Decimal("5000.00"), description="Paycheck", is_actual=True,
        category_id=income_cat.id,
    ))

    # More distinct expense categories than _MAX_STACK_CATEGORIES, each a
    # small, uniquely-named amount so ranking is deterministic.
    num_categories = _MAX_STACK_CATEGORIES + 3
    for i in range(num_categories):
        cat = models.Category(
            user_id=user.id, name=f"Small Cat {i}", type=models.CategoryType.expense,
            color="#888888", sort_order=i,
        )
        db_session.add(cat)
        db_session.flush()
        # Later categories get a larger amount so ranking is unambiguous:
        # the first `_MAX_STACK_CATEGORIES` by descending amount survive named.
        amount = Decimal("10.00") * (num_categories - i)
        db_session.add(models.Transaction(
            user_id=user.id, account_id=account.id, date=date(2026, 8, 10),
            amount=-amount, description=f"Purchase {i}", is_actual=True,
            category_id=cat.id,
        ))

    # One uncategorized transaction, smaller than everything above -- must
    # still get its own node, never merged into "Other".
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 11),
        amount=Decimal("-1.00"), description="Mystery charge", is_actual=True,
    ))
    db_session.commit()

    c = _client(db_session, user)
    resp = c.get(f"/spending/sankey/2026/8")

    assert resp.status_code == 200
    body = resp.json()
    expense_names = {n["name"] for n in body["nodes"] if n["type"] == "expense"}

    assert "Uncategorized" in expense_names, "Uncategorized must never collapse into Other"
    assert "Other" in expense_names, "categories beyond the cap must collapse into Other"
    # named categories + Other + Uncategorized, not one node per category
    assert len(expense_names) == _MAX_STACK_CATEGORIES + 2

    other_link = next(l for l in body["links"] if l["target"] == "expense:Other")
    expected_other_total = sum(
        Decimal("10.00") * (num_categories - i)
        for i in range(_MAX_STACK_CATEGORIES, num_categories)
    )
    assert Decimal(other_link["value"]) == expected_other_total
