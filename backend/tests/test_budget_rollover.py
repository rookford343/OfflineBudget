"""apply_rollover must roll over the full Budget (Committed + Flexible), not
just the stored Flexible line.

Before T4, rollover compared the stored BudgetAllocation alone against actual
spend. Actual spend includes bill payments, so a category with bills rolled
over far too little -- a category with Flexible 100, bills 2,000, and spend
2,050 is 50 under its Budget but used to roll over 0. These tests use the
same Committed + Flexible = Budget figure `compute_budget_plan` shows,
including the parent-line max() rule for a group.

Every figure here is a made-up round number.
"""
from datetime import date
from decimal import Decimal as D
from backend import models
from backend.services.budget_calculator import apply_rollover

E = models.CategoryType.expense


def _user(db, *, carry_forward=True):
    user = models.User(username="r", hashed_password="x", display_name="R",
                       budget_carry_forward=carry_forward)
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    db.add(acct); db.flush()
    return user, acct


def _cat(db, user, name, parent=None):
    c = models.Category(user_id=user.id, name=name, type=E,
                        parent_id=parent.id if parent else None)
    db.add(c); db.flush()
    return c


def _bill(db, user, acct, name, amount, category):
    db.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, category_id=category.id, name=name,
        amount=D(amount), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=5,
        start_date=date(2026, 1, 1),
    ))


def _alloc(db, user, category, amount, month=0, year=2026):
    db.add(models.BudgetAllocation(user_id=user.id, category_id=category.id, year=year,
                                   month=month, budgeted_amount=D(amount)))


def _spend(db, user, acct, amount, category, day=15, month=10, year=2026):
    db.add(models.Transaction(
        user_id=user.id, account_id=acct.id, date=date(year, month, day),
        amount=-D(amount), is_actual=True, description=f"{category.name} spend",
        category_id=category.id,
    ))


def test_bills_count_against_the_rollover_budget_not_just_flexible(db_session):
    """Required test 1: bills 2,000 + Flexible 100, spend 2,050 -> rolls over
    50. Budget = 2,000 committed + 100 flexible = 2,100; 2,100 - 2,050 = 50.
    The old stored-only formula computed 100 - 2,050 = -1,950 -> clamped to 0,
    which is the bug this task fixes (proven to fail against the old code --
    see t4-report.md)."""
    user, acct = _user(db_session)
    subs = _cat(db_session, user, "Subscriptions")
    _bill(db_session, user, acct, "Streaming bundle", "2000.00", subs)
    _alloc(db_session, user, subs, "100.00")
    subs.rollover_enabled = True
    db_session.commit()
    _spend(db_session, user, acct, "2050.00", subs)
    db_session.commit()

    updated = apply_rollover(db_session, user.id, 2026, 10)

    assert updated == 1
    assert subs.rollover_balance == D("50.00")


def test_no_bills_category_rolls_over_exactly_as_before(db_session):
    """Required test 2: a category with no bills -- Budget is just the
    stored Flexible line, same as the old formula. Flexible 100, spend 80 ->
    rolls over 20 either way."""
    user, acct = _user(db_session)
    fun = _cat(db_session, user, "Entertainment")
    _alloc(db_session, user, fun, "100.00")
    fun.rollover_enabled = True
    db_session.commit()
    _spend(db_session, user, acct, "80.00", fun)
    db_session.commit()

    updated = apply_rollover(db_session, user.id, 2026, 10)

    assert updated == 1
    assert fun.rollover_balance == D("20.00")


def test_parent_line_group_follows_the_max_rule(db_session):
    """Required test 3: a parent-line group's rollover Budget is the plan's
    group Budget -- max(parent_line, committed + rows' flexible) -- not the
    stored parent line alone. Necessities' own line is 1,500, but Mortgage
    (bill 2,000) + Groceries (flexible 600) already add up to 2,600, so bills
    can't be budgeted under and the rows win: Budget = 2,600. Actual spend
    2,500 (2,000 + 500) rolls over 100.

    The old stored-only formula read the parent's own allocation (1,500)
    against the same rolled-up actual (2,500) and floored at 0."""
    user, acct = _user(db_session)
    necessities = _cat(db_session, user, "Necessities")
    mortgage = _cat(db_session, user, "Mortgage", necessities)
    groceries = _cat(db_session, user, "Groceries", necessities)
    _bill(db_session, user, acct, "Home loan", "2000.00", mortgage)
    _alloc(db_session, user, necessities, "1500.00")   # parent line, short of its rows
    _alloc(db_session, user, groceries, "600.00")        # child's flexible
    necessities.rollover_enabled = True
    db_session.commit()
    _spend(db_session, user, acct, "2000.00", mortgage)
    _spend(db_session, user, acct, "500.00", groceries)
    db_session.commit()

    updated = apply_rollover(db_session, user.id, 2026, 10)

    assert updated == 1
    assert necessities.rollover_balance == D("100.00")


def test_rollover_never_goes_negative(db_session):
    """Overspend still floors at 0, same as before this change."""
    user, acct = _user(db_session)
    fun = _cat(db_session, user, "Entertainment")
    _alloc(db_session, user, fun, "50.00")
    fun.rollover_enabled = True
    db_session.commit()
    _spend(db_session, user, acct, "200.00", fun)
    db_session.commit()

    apply_rollover(db_session, user.id, 2026, 10)

    assert fun.rollover_balance == D("0")


def test_rollover_is_opt_in_per_category(db_session):
    """A category with rollover_enabled left off is never touched, even
    though it has an unspent Budget."""
    user, acct = _user(db_session)
    fun = _cat(db_session, user, "Entertainment")
    _alloc(db_session, user, fun, "100.00")
    db_session.commit()
    _spend(db_session, user, acct, "10.00", fun)
    db_session.commit()

    updated = apply_rollover(db_session, user.id, 2026, 10)

    assert updated == 0
    assert fun.rollover_balance == D("0")


def test_apply_rollover_is_idempotent(db_session):
    """Re-running rollover for the same month recomputes from Budget minus
    actual rather than accumulating -- calling it twice gives the same
    balance, not double."""
    user, acct = _user(db_session)
    subs = _cat(db_session, user, "Subscriptions")
    _bill(db_session, user, acct, "Streaming bundle", "2000.00", subs)
    _alloc(db_session, user, subs, "100.00")
    subs.rollover_enabled = True
    db_session.commit()
    _spend(db_session, user, acct, "2050.00", subs)
    db_session.commit()

    apply_rollover(db_session, user.id, 2026, 10)
    first = subs.rollover_balance
    apply_rollover(db_session, user.id, 2026, 10)

    assert first == D("50.00")
    assert subs.rollover_balance == D("50.00")
