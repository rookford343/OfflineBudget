"""GET /spending/monthly-digest: month-to-date spending (1st through today),
the same breakdown as the weekly digest over a different window.

All figures are invented; the repo is public."""
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models
from backend.dependencies import get_current_user, get_db
from backend.routers import spending as spending_router
from backend.services.summary_generator import generate_monthly_digest


def _freeze_today(monkeypatch, fixed: date) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.summary_generator.date", _FixedDate)


def _setup(db):
    user = models.User(username="digestowner", hashed_password="x", display_name="D")
    db.add(user)
    db.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking,
                             current_balance=Decimal("1000.00"))
    db.add(account)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    dining = models.Category(user_id=user.id, name="Dining", type=models.CategoryType.expense)
    db.add_all([groceries, dining])
    db.flush()
    return user, account, groceries, dining


def _spend(db, user, account, category, day, amount, description):
    db.add(models.Transaction(user_id=user.id, account_id=account.id, category_id=category.id,
                              date=day, amount=Decimal(amount), description=description, is_actual=True))
    db.flush()


def test_month_to_date_window(db_session, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 3, 18))
    user, account, groceries, dining = _setup(db_session)
    _spend(db_session, user, account, groceries, date(2026, 2, 28), "-11.00", "OLD MARKET")
    _spend(db_session, user, account, groceries, date(2026, 3, 1), "-22.00", "MARKET")
    _spend(db_session, user, account, dining, date(2026, 3, 18), "-33.00", "CAFE")
    db_session.commit()

    digest = generate_monthly_digest(db_session, user, account.id)

    assert digest.month_start == date(2026, 3, 1)
    assert digest.month_end == date(2026, 3, 18)
    assert digest.total_spent == Decimal("55.00")
    assert {c.category_name: c.total for c in digest.categories} == {
        "Groceries": Decimal("22.00"), "Dining": Decimal("33.00"),
    }


def test_first_of_month_single_day(db_session, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 3, 1))
    user, account, groceries, _ = _setup(db_session)
    _spend(db_session, user, account, groceries, date(2026, 2, 28), "-11.00", "OLD MARKET")
    _spend(db_session, user, account, groceries, date(2026, 3, 1), "-44.00", "MARKET")
    db_session.commit()

    digest = generate_monthly_digest(db_session, user, account.id)

    assert digest.month_start == digest.month_end == date(2026, 3, 1)
    assert digest.total_spent == Decimal("44.00")


def test_empty_month(db_session, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 3, 18))
    user, account, groceries, _ = _setup(db_session)
    _spend(db_session, user, account, groceries, date(2026, 2, 20), "-11.00", "OLD MARKET")
    db_session.commit()

    digest = generate_monthly_digest(db_session, user, account.id)

    assert digest.total_spent == Decimal("0")
    assert digest.categories == []
    assert digest.top_merchants == []


def test_total_equals_category_sum(db_session, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 3, 18))
    user, account, groceries, dining = _setup(db_session)
    _spend(db_session, user, account, groceries, date(2026, 3, 2), "-12.34", "MARKET")
    _spend(db_session, user, account, groceries, date(2026, 3, 9), "-5.66", "MARKET")
    _spend(db_session, user, account, dining, date(2026, 3, 10), "-7.00", "CAFE")
    db_session.commit()

    digest = generate_monthly_digest(db_session, user, account.id)

    assert digest.total_spent == sum((c.total for c in digest.categories), Decimal("0"))
    assert digest.total_spent == Decimal("25.00")


def _client(db, user):
    app = FastAPI()
    app.include_router(spending_router.router)
    app.dependency_overrides[get_db] = lambda: db
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_route_requires_auth_and_returns_shape(db_session, monkeypatch):
    _freeze_today(monkeypatch, date(2026, 3, 18))
    user, account, groceries, _ = _setup(db_session)
    _spend(db_session, user, account, groceries, date(2026, 3, 3), "-20.00", "MARKET")
    db_session.commit()

    # No auth override: the real dependency rejects the request.
    assert _client(db_session, None).get(
        "/spending/monthly-digest", params={"account_id": account.id}).status_code in (401, 403)

    response = _client(db_session, user).get("/spending/monthly-digest", params={"account_id": account.id})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"month_start", "month_end", "total_spent", "categories", "top_merchants"}
    assert body["month_start"] == "2026-03-01"
    assert body["month_end"] == "2026-03-18"
    assert body["total_spent"] == "20.00"
    assert body["categories"][0]["category_name"] == "Groceries"
    assert set(body["top_merchants"][0]) == {"name", "total", "count"}
