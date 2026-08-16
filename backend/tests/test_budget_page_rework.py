from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import budget as budget_router_module
from backend.services.budget_calculator import compute_overview


def _client(db_session, user):
    app = FastAPI()
    app.include_router(budget_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db):
    user = models.User(username="b", hashed_password="x", display_name="B")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=Decimal("5000"),
                             statement_day=28, due_day=15)
    wants = models.Category(user_id=user.id, name="Wants", type=models.CategoryType.expense)
    db.add_all([acct, card, wants]); db.flush()
    subs = models.Category(user_id=user.id, name="Subscriptions",
                           type=models.CategoryType.expense, parent_id=wants.id)
    db.add(subs); db.flush()
    return user, acct, card, wants, subs


def test_internal_transfer_is_not_counted_as_budget_spend(db_session):
    """Budget and Spending must agree on the same month. Without the shared
    predicates a categorized savings transfer showed as $1,000.00 of spend on
    this page and nothing on the Spending page."""
    user, acct, card, wants, subs = _seed(db_session)
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=acct.id, date=date(2026, 8, 3),
                           amount=Decimal("-1000.00"), is_actual=True,
                           description="Online Transfer to CHK ...0054", category_id=subs.id),
        models.Transaction(user_id=user.id, account_id=acct.id, date=date(2026, 8, 4),
                           amount=Decimal("-25.00"), is_actual=True,
                           description="Netflix", category_id=subs.id),
    ])
    db_session.commit()

    rows = {r.category_id: r for r in compute_overview(db_session, user.id, 2026, 8)}
    assert rows[subs.id].actual_total == Decimal("25.00")


def test_card_payoff_is_not_counted_as_budget_spend(db_session):
    user, acct, card, wants, subs = _seed(db_session)
    db_session.add_all([
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 8, 5),
                                     amount=Decimal("900.00"), merchant="AUTOMATIC PAYMENT - THANK YOU",
                                     category_id=subs.id),
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 8, 6),
                                     amount=Decimal("19.99"), merchant="Netflix", category_id=subs.id),
    ])
    db_session.commit()

    rows = {r.category_id: r for r in compute_overview(db_session, user.id, 2026, 8)}
    assert rows[subs.id].actual_total == Decimal("19.99")


def test_category_breakdown_lists_the_merchants_behind_a_budget_line(db_session):
    """"What is actually in my $800 Subscriptions?" answered without leaving
    the Budget page."""
    user, acct, card, wants, subs = _seed(db_session)
    db_session.add_all([
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 8, 6),
                                     amount=Decimal("19.99"), merchant="Netflix", category_id=subs.id),
        models.CreditCardTransaction(card_id=card.id, user_id=user.id, date=date(2026, 8, 7),
                                     amount=Decimal("10.99"), merchant="Spotify", category_id=subs.id),
    ])
    db_session.commit()
    c = _client(db_session, user)

    rows = c.get("/budget/category-breakdown",
                 params={"category_id": subs.id, "year": 2026, "month": 8}).json()
    names = [r["name"] for r in rows]
    assert "Netflix" in names and "Spotify" in names
    assert Decimal(rows[0]["total"]) == Decimal("19.99")  # sorted by total desc


def test_breakdown_of_a_parent_includes_its_children(db_session):
    """A budget set on a parent is measured against everything beneath it, so
    the breakdown has to reach into children too."""
    user, acct, card, wants, subs = _seed(db_session)
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 8, 6),
        amount=Decimal("19.99"), merchant="Netflix", category_id=subs.id))
    db_session.commit()
    c = _client(db_session, user)

    rows = c.get("/budget/category-breakdown",
                 params={"category_id": wants.id, "year": 2026, "month": 8}).json()
    assert [r["name"] for r in rows] == ["Netflix"]


def test_deleting_an_allocation_removes_the_line_rather_than_zeroing_it(db_session):
    """Zero means "spend nothing here" and reports every dollar as an overage;
    removed means the category isn't budgeted and isn't scored at all."""
    user, acct, card, wants, subs = _seed(db_session)
    alloc = models.BudgetAllocation(user_id=user.id, category_id=subs.id,
                                    year=2026, month=0, budgeted_amount=Decimal("800.00"))
    db_session.add(alloc); db_session.commit()
    c = _client(db_session, user)

    assert c.get("/budget", params={"year": 2026}).json() != []
    assert c.delete(f"/budget/{alloc.id}").status_code == 204
    assert c.get("/budget", params={"year": 2026}).json() == []
    rows = {r.category_id: r for r in compute_overview(db_session, user.id, 2026, 8)}
    assert rows[subs.id].budgeted == Decimal("0")


def test_cannot_delete_another_users_allocation(db_session):
    user, acct, card, wants, subs = _seed(db_session)
    other = models.User(username="o", hashed_password="x", display_name="O")
    db_session.add(other); db_session.flush()
    alloc = models.BudgetAllocation(user_id=other.id, category_id=subs.id,
                                    year=2026, month=0, budgeted_amount=Decimal("50.00"))
    db_session.add(alloc); db_session.commit()

    assert _client(db_session, user).delete(f"/budget/{alloc.id}").status_code == 404


def test_overview_reports_category_type_so_income_rows_can_be_dropped(db_session):
    """The Budget page must be able to tell income apart from expense. Dan's
    "Income" and "Salary / Wages" carry $12,133.26 allocations that are
    forecasting inputs, not spending limits, and they wrecked the totals."""
    user, acct, card, wants, subs = _seed(db_session)
    income = models.Category(user_id=user.id, name="Salary", type=models.CategoryType.income)
    db_session.add(income); db_session.commit()

    rows = {r.category_name: r for r in compute_overview(db_session, user.id, 2026, 8)}
    assert rows["Salary"].category_type == "income"
    assert rows["Subscriptions"].category_type == "expense"
