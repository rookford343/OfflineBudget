from datetime import date
from decimal import Decimal
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import budget as budget_router_module
from backend.services.budget_snapshot import compute_budget_snapshot, leftover_parts
from backend.services.left_to_budget import compute_left_to_budget
from backend.tests.test_budget_snapshot import _seed_spreadsheet_scenario, _fake_quarter_min

E = models.CategoryType.expense


def _seed(db):
    user = models.User(username="t", hashed_password="x", display_name="T", savings_strategy="save_monthly")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    db.add(acct); db.flush()
    home = models.Category(user_id=user.id, name="Home", type=E)
    subs = models.Category(user_id=user.id, name="Subscriptions", type=E, is_discretionary=True)
    shopping = models.Category(user_id=user.id, name="Shopping", type=E, is_discretionary=True)
    food = models.Category(user_id=user.id, name="Food & Drinks", type=E, is_discretionary=True)
    groceries = models.Category(user_id=user.id, name="Groceries", type=E, is_discretionary=True)
    savings = models.Category(user_id=user.id, name="Savings", type=models.CategoryType.savings)
    db.add_all([home, subs, shopping, food, groceries, savings]); db.flush()

    def item(name, amount, cat, freq=models.RecurringFrequency.monthly, moy=None, typ=models.RecurringType.expense):
        db.add(models.RecurringItem(
            user_id=user.id, account_id=acct.id, category_id=cat.id if cat else None, name=name,
            amount=Decimal(amount), type=typ, frequency=freq, day_of_month=5, month_of_year=moy,
            start_date=date(2026, 1, 1),
        ))

    item("Pay", "5000.00", None, typ=models.RecurringType.income)
    item("Electric", "150.00", home)
    item("Stormwater", "30.00", home, freq=models.RecurringFrequency.quarterly)
    item("Streamer", "20.00", subs)
    item("Mystery", "12.00", None)
    item("Annual app", "120.00", None, freq=models.RecurringFrequency.yearly, moy=3)
    db.add_all([
        models.BudgetAllocation(user_id=user.id, category_id=savings.id, year=2026, month=0, budgeted_amount=Decimal("1000.00")),
        models.BudgetAllocation(user_id=user.id, category_id=groceries.id, year=2026, month=0, budgeted_amount=Decimal("600.00")),
        models.BudgetAllocation(user_id=user.id, category_id=shopping.id, year=2026, month=0, budgeted_amount=Decimal("700.00")),
        models.BudgetAllocation(user_id=user.id, category_id=food.id, year=2026, month=10, budgeted_amount=Decimal("800.00")),
        models.BudgetAllocation(user_id=user.id, category_id=subs.id, year=2026, month=0, budgeted_amount=Decimal("300.00")),
    ])
    db.commit()
    return user, {"home": home, "subs": subs, "shopping": shopping, "food": food}


def test_committed_rows_and_leftover_reconcile_to_income(db_session):
    user, _ = _seed(db_session)
    out = compute_left_to_budget(db_session, user, 2026, 10)
    committed_total = sum((r.amount for r in out.committed), Decimal("0"))
    assert out.leftover + committed_total == Decimal("5000.00")


def test_committed_rows_break_down_by_category_with_bills(db_session):
    user, _ = _seed(db_session)
    rows = {r.category_name: r for r in compute_left_to_budget(db_session, user, 2026, 10).committed}
    assert rows["Home"].amount == Decimal("160.00")          # 150 + 30/3
    assert {b.name for b in rows["Home"].items} == {"Electric", "Stormwater"}
    assert rows["Subscriptions"].amount == Decimal("20.00")  # from bills, NOT the 300 allocation
    assert rows["Unclassified"].amount == Decimal("12.00")   # yearly item not due in October
    assert rows["Savings"].amount == Decimal("1000.00")
    assert rows["Groceries"].amount == Decimal("600.00")


def test_unclassified_badge_counts_every_uncategorized_bill_smoothed(db_session):
    user, _ = _seed(db_session)
    out = compute_left_to_budget(db_session, user, 2026, 10)
    assert out.unclassified_count == 2
    assert out.unclassified_amount == Decimal("22.00")       # 12 + 120/12


def test_assignable_uses_month_row_only_when_carry_forward_off(db_session):
    user, cats = _seed(db_session)
    out = compute_left_to_budget(db_session, user, 2026, 10)
    assigned = {r.category_name: r for r in out.assignable}
    assert set(assigned) == {"Shopping", "Food & Drinks"}
    assert assigned["Shopping"].assigned == Decimal("0") and assigned["Shopping"].is_set is False
    assert assigned["Food & Drinks"].assigned == Decimal("800.00") and assigned["Food & Drinks"].is_set is True
    assert out.assigned_total == Decimal("800.00")
    assert out.unassigned == out.leftover - Decimal("800.00")
    assert out.carry_forward is False


def test_assignable_falls_back_to_month0_when_carry_forward_on(db_session):
    user, _ = _seed(db_session)
    user.budget_carry_forward = True
    db_session.commit()
    out = compute_left_to_budget(db_session, user, 2026, 10)
    assert {r.category_name: r.assigned for r in out.assignable}["Shopping"] == Decimal("700.00")


def test_endpoint_returns_payload(db_session):
    user, _ = _seed(db_session)
    app = FastAPI()
    app.include_router(budget_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    r = TestClient(app).get("/budget/left-to-budget", params={"year": 2026, "month": 10})
    assert r.status_code == 200
    assert r.json()["unclassified_count"] == 2


def test_guard_leftover_and_left_to_spend_unchanged_by_classification_and_setting(db_session):
    user, checking, _card = _seed_spreadsheet_scenario(db_session)
    as_of = date(2026, 8, 7)
    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("5120.66")):
        before = compute_budget_snapshot(db_session, user, checking.id, as_of=as_of)

    home = models.Category(user_id=user.id, name="Home", type=E)
    db_session.add(home); db_session.flush()
    for item in db_session.query(models.RecurringItem).filter(models.RecurringItem.type == models.RecurringType.expense):
        item.category_id = home.id
    user.budget_carry_forward = True
    db_session.commit()
    compute_left_to_budget(db_session, user, 2026, 8)

    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("5120.66")):
        after = compute_budget_snapshot(db_session, user, checking.id, as_of=as_of)
    assert after.leftover == before.leftover
    assert after.left_to_spend == before.left_to_spend
    assert after.safety_margin == before.safety_margin
    assert leftover_parts(db_session, user, as_of).leftover == before.leftover
