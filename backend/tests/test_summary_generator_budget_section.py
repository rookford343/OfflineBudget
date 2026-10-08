"""The daily email's "Budget this month" section, added 2026-10-07 directly
after the Household Snapshot -- mirrors the Dashboard's category bars using
the same `compute_overview` the Budget page reads, so the email can never
disagree with the app about a category's numbers.

compute_overview rolls child actuals up into the parent row (actual_total)
but does NOT roll up budgeted -- a parent only carries its own direct
allocation there, if any. The group header total below must sum the
children's budgeted amounts itself while using the parent's own (already
rolled-up) actual_total as-is, or it either misses the budgeted side or
double-counts the actual side.
"""
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.summary_generator import generate_daily_summary


def _make_user_account(db, username="budgetuser"):
    user = models.User(username=username, hashed_password="x", display_name="Budget")
    db.add(user)
    db.flush()
    account = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("1000.00"),
    )
    db.add(account)
    db.flush()
    return user, account


def _category(db, user, name, *, type=models.CategoryType.expense, parent_id=None):
    cat = models.Category(user_id=user.id, name=name, type=type, parent_id=parent_id)
    db.add(cat)
    db.flush()
    return cat


def _allocate(db, user, category, amount, today):
    db.add(models.BudgetAllocation(
        user_id=user.id, category_id=category.id,
        year=today.year, month=today.month, budgeted_amount=Decimal(amount),
    ))


def _spend(db, user, account, category, amount, today):
    db.add(models.Transaction(
        user_id=user.id, account_id=account.id, category_id=category.id,
        date=today, amount=Decimal(amount), description="Test spend",
        is_actual=True,
    ))


def _seed_budget_scenario(db):
    """Needs/Food (500 budget, 120 spent), Needs/Fuel (100 budget, 150 spent
    -- over), Fun/Toys (0 budget, 40 spent -- no budget set), plus an income
    category with its own budget that must never show up in this section."""
    today = date.today()
    user, account = _make_user_account(db)

    needs = _category(db, user, "Needs")
    food = _category(db, user, "Food", parent_id=needs.id)
    fuel = _category(db, user, "Fuel", parent_id=needs.id)
    fun = _category(db, user, "Fun")
    toys = _category(db, user, "Toys", parent_id=fun.id)
    income = _category(db, user, "Paycheck", type=models.CategoryType.income)

    _allocate(db, user, food, "500.00", today)
    _allocate(db, user, fuel, "100.00", today)
    _allocate(db, user, income, "5000.00", today)

    _spend(db, user, account, food, "-120.00", today)
    _spend(db, user, account, fuel, "-150.00", today)
    _spend(db, user, account, toys, "-40.00", today)

    db.commit()
    return user, account


def test_budget_section_title_present(db_session):
    user, account = _seed_budget_scenario(db_session)
    html, text = generate_daily_summary(db_session, user)
    assert "Budget this month" in html


def test_budget_section_shows_food_spent_of_budget_and_left(db_session):
    user, account = _seed_budget_scenario(db_session)
    html, text = generate_daily_summary(db_session, user)
    assert "$120.00 of $500.00" in html
    assert "$380.00 left" in html
    assert "Food: $120.00 of $500.00" in text


def test_budget_section_flags_fuel_as_over(db_session):
    user, account = _seed_budget_scenario(db_session)
    html, _ = generate_daily_summary(db_session, user)
    assert "$50.00 over" in html


def test_budget_section_shows_no_budget_set_for_toys(db_session):
    user, account = _seed_budget_scenario(db_session)
    html, _ = generate_daily_summary(db_session, user)
    assert "no budget set" in html


def test_budget_section_excludes_income_category(db_session):
    user, account = _seed_budget_scenario(db_session)
    html, _ = generate_daily_summary(db_session, user)
    budget_section = html.split("Budget this month", 1)[1].split("Checking Accounts", 1)[0]
    assert "Paycheck" not in budget_section


def test_budget_section_parent_header_rolls_up_children_without_double_counting(db_session):
    """Needs' header must show $270.00 of $600.00 -- the sum of Food's and
    Fuel's budgets (500+100) against the sum of their actuals (120+150).
    compute_overview already rolls the children's actual_total into the
    parent row, so summing the children's actuals again here as well as
    reading them off the parent would double them to $540.00."""
    user, account = _seed_budget_scenario(db_session)
    html, _ = generate_daily_summary(db_session, user)
    assert "$270.00 of $600.00" in html
