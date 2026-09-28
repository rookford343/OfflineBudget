from datetime import date
from decimal import Decimal
from backend import models
from backend.services.budget_buckets import assignable_category_ids, drop_uncarried_defaults
from backend.services.budget_calculator import compute_overview


def _seed(db, carry_forward=False):
    user = models.User(username="b", hashed_password="x", display_name="B", budget_carry_forward=carry_forward)
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    wants = models.Category(user_id=user.id, name="Wants", type=models.CategoryType.expense, is_discretionary=True)
    db.add_all([acct, wants]); db.flush()
    E = models.CategoryType.expense
    cats = {
        "Shopping": models.Category(user_id=user.id, parent_id=wants.id, name="Shopping", type=E, is_discretionary=True),
        "Subscriptions": models.Category(user_id=user.id, parent_id=wants.id, name="Subscriptions", type=E, is_discretionary=True),
        "Groceries": models.Category(user_id=user.id, name="Groceries", type=E, is_discretionary=True),
        "Home": models.Category(user_id=user.id, name="Home", type=E, is_discretionary=False),
    }
    db.add_all(cats.values()); db.flush()
    cats["Wants"] = wants
    db.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, category_id=cats["Subscriptions"].id, name="Streamer",
        amount=Decimal("15.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=3, start_date=date(2026, 1, 1),
    ))
    db.add_all([
        models.BudgetAllocation(user_id=user.id, category_id=cats["Shopping"].id, year=2026, month=0, budgeted_amount=Decimal("500.00")),
        models.BudgetAllocation(user_id=user.id, category_id=cats["Groceries"].id, year=2026, month=0, budgeted_amount=Decimal("400.00")),
        models.BudgetAllocation(user_id=user.id, category_id=cats["Home"].id, year=2026, month=0, budgeted_amount=Decimal("300.00")),
    ])
    db.commit()
    return user, cats


def test_only_leaf_discretionary_unbilled_non_committed_lines_are_assignable(db_session):
    user, cats = _seed(db_session)
    assert assignable_category_ids(db_session, user.id) == {cats["Shopping"].id}


def test_carry_forward_off_drops_month0_rows_for_assignable_only(db_session):
    user, cats = _seed(db_session)
    rows = db_session.query(models.BudgetAllocation).all()
    kept = drop_uncarried_defaults(rows, user, assignable_category_ids(db_session, user.id))
    kept_cats = {a.category_id for a in kept}
    assert cats["Shopping"].id not in kept_cats
    assert cats["Groceries"].id in kept_cats
    assert cats["Home"].id in kept_cats


def test_carry_forward_on_keeps_everything(db_session):
    user, _ = _seed(db_session, carry_forward=True)
    rows = db_session.query(models.BudgetAllocation).all()
    assert len(drop_uncarried_defaults(rows, user, assignable_category_ids(db_session, user.id))) == 3


def test_month_specific_row_survives_carry_forward_off(db_session):
    user, cats = _seed(db_session)
    db_session.add(models.BudgetAllocation(user_id=user.id, category_id=cats["Shopping"].id, year=2026, month=10, budgeted_amount=Decimal("450.00")))
    db_session.commit()
    rows = db_session.query(models.BudgetAllocation).all()
    kept = drop_uncarried_defaults(rows, user, assignable_category_ids(db_session, user.id))
    assert [a.budgeted_amount for a in kept if a.category_id == cats["Shopping"].id] == [Decimal("450.00")]


def test_overview_shows_unassigned_bucket_as_zero_when_carry_forward_off(db_session):
    user, cats = _seed(db_session)
    rows = {r.category_id: r for r in compute_overview(db_session, user.id, 2026, 10)}
    assert rows[cats["Shopping"].id].budgeted == Decimal("0")
    assert rows[cats["Groceries"].id].budgeted == Decimal("400.00")


def test_overview_carries_forward_when_enabled(db_session):
    user, cats = _seed(db_session, carry_forward=True)
    rows = {r.category_id: r for r in compute_overview(db_session, user.id, 2026, 10)}
    assert rows[cats["Shopping"].id].budgeted == Decimal("500.00")


def test_overview_flags_assignable_rows(db_session):
    user, cats = _seed(db_session)
    rows = {r.category_id: r for r in compute_overview(db_session, user.id, 2026, 10)}
    assert rows[cats["Shopping"].id].is_assignable is True
    assert rows[cats["Groceries"].id].is_assignable is False
    assert rows[cats["Subscriptions"].id].is_assignable is False
    assert rows[cats["Wants"].id].is_assignable is False
