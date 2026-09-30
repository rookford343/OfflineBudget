from datetime import date
from decimal import Decimal
from backend import models
from backend.services.left_to_budget import compute_left_to_budget
from backend.services.month_summary import build_month_summary
from backend.services.explain import replay, children_consistent
from backend.tests.test_left_to_budget import _seed as seed_ltb


def test_unassigned_explanation_replays(db_session):
    user, cats = seed_ltb(db_session)
    out = compute_left_to_budget(db_session, user, 2026, 10)
    ex = out.explain_unassigned
    assert ex.result == out.unassigned
    assert replay(ex) == out.unassigned
    assert children_consistent(ex)
    assert ex.rows[0].amount == out.leftover
    subtracted = [r for r in ex.rows if r.op == "subtract"]
    assert sum((r.amount for r in subtracted), Decimal("0")) == out.assigned_total


def _month_seed(db):
    user = models.User(username="mx", hashed_password="x", display_name="MX")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    db.add(acct); db.flush()

    def item(name, amount, typ, freq, day, moy=None):
        db.add(models.RecurringItem(
            user_id=user.id, account_id=acct.id, name=name, amount=Decimal(amount),
            type=typ, frequency=freq, day_of_month=day, month_of_year=moy,
            start_date=date(2026, 1, 1),
        ))

    E, I = models.RecurringType.expense, models.RecurringType.income
    M, Y = models.RecurringFrequency.monthly, models.RecurringFrequency.yearly
    item("Pay", "3000.00", I, M, 15)
    item("Rent", "1200.00", E, M, 1)
    item("Power Co", "90.00", E, M, 8)
    item("Annual plan", "120.00", E, Y, 10, moy=10)
    db.add(models.PlannedExpense(
        user_id=user.id, account_id=acct.id, name="Couch", amount=Decimal("400.00"),
        expected_date=date(2026, 10, 20),
    ))
    db.commit()
    return user


def test_month_summary_explanations_replay(db_session):
    user = _month_seed(db_session)
    out = build_month_summary(db_session, user.id, 2026, 10)
    for key, field in {"expense_total": "expense_total", "left_over": "left_over"}.items():
        ex = out.explain[key]
        shown = getattr(out, field)
        assert ex.result == shown, key
        assert replay(ex) == shown, key
        assert children_consistent(ex), key
    assert any(r.label.startswith("Annual plan") for r in out.explain["expense_total"].rows)
    assert any(r.label.startswith("Couch") and r.op == "subtract" for r in out.explain["left_over"].rows)


def _month_seed_with_inflow(db):
    user = models.User(username="mi", hashed_password="x", display_name="MI")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    db.add(acct); db.flush()

    def item(name, amount, typ, freq, day, moy=None):
        db.add(models.RecurringItem(
            user_id=user.id, account_id=acct.id, name=name, amount=Decimal(amount),
            type=typ, frequency=freq, day_of_month=day, month_of_year=moy,
            start_date=date(2026, 1, 1),
        ))

    E, I = models.RecurringType.expense, models.RecurringType.income
    M = models.RecurringFrequency.monthly
    item("Pay", "3000.00", I, M, 15)
    item("Rent", "1200.00", E, M, 1)
    db.add(models.PlannedExpense(
        user_id=user.id, account_id=acct.id, name="Couch", amount=Decimal("400.00"),
        expected_date=date(2026, 10, 20),
    ))
    db.add(models.PlannedExpense(
        user_id=user.id, account_id=acct.id, name="Refund", amount=Decimal("150.00"),
        expected_date=date(2026, 10, 22), direction=models.PlannedDirection.inflow,
    ))
    db.commit()
    return user


def test_left_over_explanation_handles_inflow_one_off(db_session):
    user = _month_seed_with_inflow(db_session)
    out = build_month_summary(db_session, user.id, 2026, 10)
    ex = out.explain["left_over"]
    assert ex.result == out.left_over
    assert replay(ex) == out.left_over
    assert children_consistent(ex)

    inflow_rows = [r for r in ex.rows if r.label.startswith("Refund")]
    outflow_rows = [r for r in ex.rows if r.label.startswith("Couch")]
    assert len(inflow_rows) == 1 and inflow_rows[0].op == "add"
    assert len(outflow_rows) == 1 and outflow_rows[0].op == "subtract"
