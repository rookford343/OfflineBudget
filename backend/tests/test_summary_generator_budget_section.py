"""The daily email's "Budget this month" section, added 2026-10-07 directly
after the Household Snapshot -- mirrors the Dashboard's category bars using
the same `compute_overview` the Budget page reads, so the email can never
disagree with the app about a category's numbers.

compute_overview rolls child actuals up into the parent row (actual_total)
but does NOT roll up budgeted -- a parent's `budgeted` is its OWN direct
allocation, entirely separate from its children's. The group header's
budget must therefore be the parent's own budgeted when it has one
(>0), falling back to summing the children's budgeted only when the
parent carries no allocation of its own -- matching what the Budget page
shows for that parent. Adding the two together double-counts whenever a
parent happens to carry both (found in the real preview: "Necessities"
showed its own $5,395.03 plus its children's $5,622.98 as $11,017.30).
Header actual stays the parent's already-rolled-up actual_total either
way -- re-summing the children's actuals on top of that would double
them instead.
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
    """Needs (own allocation 600) / Food (500 budget, 120 spent) / Fuel (100
    budget, 150 spent -- over), Fun/Toys (0 budget, 40 spent -- no budget
    set), plus an income category with its own budget that must never show
    up in this section.

    Needs carries its own direct allocation of 600 *in addition to* its
    children's 500+100 -- the header must use the parent's own 600, not
    600+600=1200."""
    today = date.today()
    user, account = _make_user_account(db)

    needs = _category(db, user, "Needs")
    food = _category(db, user, "Food", parent_id=needs.id)
    fuel = _category(db, user, "Fuel", parent_id=needs.id)
    fun = _category(db, user, "Fun")
    toys = _category(db, user, "Toys", parent_id=fun.id)
    income = _category(db, user, "Paycheck", type=models.CategoryType.income)

    _allocate(db, user, needs, "600.00", today)
    _allocate(db, user, food, "500.00", today)
    _allocate(db, user, fuel, "100.00", today)
    _allocate(db, user, income, "5000.00", today)

    _spend(db, user, account, food, "-120.00", today)
    _spend(db, user, account, fuel, "-150.00", today)
    _spend(db, user, account, toys, "-40.00", today)

    db.commit()
    return user, account


def _seed_header_sum_scenario(db):
    """"Extras" carries NO allocation of its own -- only its children
    (Games 30 budget/10 spent, Hobbies 20 budget/5 spent) do. The header
    must fall back to summing the children: $15.00 of $50.00."""
    today = date.today()
    user, account = _make_user_account(db, username="headersumuser")

    extras = _category(db, user, "Extras")
    games = _category(db, user, "Games", parent_id=extras.id)
    hobbies = _category(db, user, "Hobbies", parent_id=extras.id)

    _allocate(db, user, games, "30.00", today)
    _allocate(db, user, hobbies, "20.00", today)

    _spend(db, user, account, games, "-10.00", today)
    _spend(db, user, account, hobbies, "-5.00", today)

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


def test_budget_section_parent_header_uses_its_own_allocation_not_double_counted(db_session):
    """Needs carries its own 600 allocation AND has children totaling
    500+100=600. The header must show $270.00 of $600.00 (the parent's own
    budgeted) -- not $1,200.00 (own + children summed), and not $540.00
    (children's actuals summed on top of the parent's already-rolled-up
    actual_total)."""
    user, account = _seed_budget_scenario(db_session)
    html, _ = generate_daily_summary(db_session, user)
    assert "$270.00 of $600.00" in html
    assert "$1,200.00" not in html
    assert "$540.00" not in html


def test_budget_section_header_sums_children_when_parent_has_no_own_allocation(db_session):
    """Extras has no allocation of its own, so the header falls back to
    summing its children's budgets (30+20=50) against their actuals
    (10+5=15)."""
    user, account = _seed_header_sum_scenario(db_session)
    html, _ = generate_daily_summary(db_session, user)
    assert "$15.00 of $50.00" in html
