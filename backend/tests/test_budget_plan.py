"""Set Budgets' merged list: Committed (from Recurring) + Flexible = Budget.

Every figure here is a made-up round number. The seeded month is Oct 2026:

  Income        Pay 5,000 + a 50 one-off refund               = 5,050
  Committed     Mortgage 2,000 | Subscriptions 20 + 120 (yearly, due Oct)
                Shopping 100 (one-off gift) | Charity 500
                no category: Mystery 10 + Trip 300 one-off    = 3,050
  Flexible      Necessities line 3,000 is the GROUP total: 3,000 - 2,000
                committed = 1,000 (Groceries 600 + 400 rest)
                Shopping 400 | Savings 500                    = 1,900
  Left to assign 5,050 - 3,050 - 1,900                        =   100
"""
from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import budget as budget_router_module
from backend.services.budget_plan import compute_budget_plan
from backend.services.explain import replay, children_consistent
from backend.services.month_summary import build_month_summary

E = models.CategoryType.expense
D = Decimal


def _seed(db, *, carry_forward=True):
    user = models.User(username="p", hashed_password="x", display_name="P",
                       budget_carry_forward=carry_forward)
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking)
    db.add(acct); db.flush()

    def cat(name, parent=None, typ=E, disc=False):
        c = models.Category(user_id=user.id, name=name, type=typ, is_discretionary=disc,
                            parent_id=parent.id if parent else None)
        db.add(c); db.flush()
        return c

    nec = cat("Necessities")
    mortgage = cat("Mortgage", nec)
    groceries = cat("Groceries", nec, disc=True)
    wants = cat("Wants")
    subs = cat("Subscriptions", wants, disc=True)
    shopping = cat("Shopping", wants, disc=True)
    charity = cat("Charity")
    savings = cat("Savings", typ=models.CategoryType.savings)
    salary = cat("Salary", typ=models.CategoryType.income)

    def item(name, amount, c, typ=models.RecurringType.expense,
             freq=models.RecurringFrequency.monthly, moy=None):
        db.add(models.RecurringItem(
            user_id=user.id, account_id=acct.id, category_id=c.id if c else None, name=name,
            amount=D(amount), type=typ, frequency=freq, day_of_month=5, month_of_year=moy,
            start_date=date(2026, 1, 1),
        ))

    item("Pay", "5000.00", salary, typ=models.RecurringType.income)
    item("Home loan", "2000.00", mortgage)
    item("Streamer", "20.00", subs)
    item("Annual app", "120.00", subs, freq=models.RecurringFrequency.yearly, moy=10)
    item("Not this month", "240.00", subs, freq=models.RecurringFrequency.yearly, moy=3)
    item("Tithe", "500.00", charity)
    item("Mystery", "10.00", None)
    item("Card payoff", "999.00", None, typ=models.RecurringType.credit_card_payment)

    def one_off(name, amount, day, c=None, direction=models.PlannedDirection.outflow):
        db.add(models.PlannedExpense(
            user_id=user.id, account_id=acct.id, category_id=c.id if c else None, name=name,
            amount=D(amount), expected_date=date(2026, 10, day), direction=direction,
        ))

    one_off("Gift", "100.00", 12, shopping)
    one_off("Refund", "50.00", 20, direction=models.PlannedDirection.inflow)
    one_off("Trip", "300.00", 25)

    def alloc(c, amount, month=0):
        db.add(models.BudgetAllocation(user_id=user.id, category_id=c.id, year=2026,
                                       month=month, budgeted_amount=D(amount)))

    alloc(nec, "3000.00")
    alloc(groceries, "600.00")
    alloc(shopping, "400.00", month=10)
    alloc(savings, "500.00")
    alloc(salary, "5000.00")  # an income "budget" is a forecasting input, never Flexible
    db.commit()
    cats = dict(nec=nec, mortgage=mortgage, groceries=groceries, wants=wants, subs=subs,
                shopping=shopping, charity=charity, savings=savings, salary=salary)
    return user, acct, cats


def _groups(out):
    return {g.group_name: g for g in out.groups}


def _rows(out):
    return {r.category_name: r for g in out.groups for r in g.rows}


def test_headline_identity_income_minus_committed_minus_flexible(db_session):
    user, _, _ = _seed(db_session)
    out = compute_budget_plan(db_session, user, 2026, 10)
    assert out.income_total == D("5050.00")
    assert out.committed_total == D("3050.00")
    assert out.flexible_total == D("1900.00")
    assert out.left_to_assign == D("100.00")
    assert out.left_to_assign == out.income_total - out.committed_total - out.flexible_total
    assert out.budget_total == out.committed_total + out.flexible_total


def test_income_minus_committed_is_the_recurring_tabs_left_over(db_session):
    user, _, _ = _seed(db_session)
    out = compute_budget_plan(db_session, user, 2026, 10)
    summary = build_month_summary(db_session, user.id, 2026, 10)
    assert out.recurring_left_over == summary.left_over
    assert out.income_total - out.committed_total == summary.left_over


def test_committed_per_category_is_the_months_recurring_amounts(db_session):
    user, _, _ = _seed(db_session)
    rows = _rows(compute_budget_plan(db_session, user, 2026, 10))
    assert rows["Mortgage"].committed == D("2000.00")
    assert rows["Subscriptions"].committed == D("140.00")  # 20 + yearly 120 due in Oct
    assert {i.name for i in rows["Subscriptions"].items} == {"Streamer", "Annual app"}
    assert rows["Shopping"].committed == D("100.00")       # the categorized one-off
    assert rows["Charity"].committed == D("500.00")
    # Committed is never typed: no allocation exists on any of these.
    assert rows["Subscriptions"].flexible == D("0")
    assert rows["Subscriptions"].budget == D("140.00")
    assert rows["Shopping"].budget == D("500.00")          # 100 committed + 400 flexible


def test_uncategorized_committed_is_its_own_group(db_session):
    user, _, _ = _seed(db_session)
    out = compute_budget_plan(db_session, user, 2026, 10)
    g = _groups(out)["Not in a category"]
    assert g.kind == "uncategorized"
    assert g.committed == D("310.00")                      # Mystery 10 + Trip 300
    assert g.flexible == D("0")
    assert out.unclassified_count == 1                      # Mystery (a recurring item)


def test_parent_line_is_the_group_total_and_never_double_counts(db_session):
    user, _, _ = _seed(db_session)
    g = _groups(compute_budget_plan(db_session, user, 2026, 10))["Necessities"]
    assert g.parent_line == D("3000.00")
    assert g.committed == D("2000.00")
    # NOT 3,000 + 2,000 + 600: the 3,000 line already covers what's beneath it.
    assert g.budget == D("3000.00")
    assert g.flexible == D("1000.00")
    assert g.rest == D("400.00")                            # 3,000 - 2,000 - 600
    assert g.parent_line_short == D("0")


def test_parent_line_below_its_children_is_flagged_not_trusted(db_session):
    user, _, cats = _seed(db_session)
    a = db_session.query(models.BudgetAllocation).filter_by(category_id=cats["nec"].id).one()
    a.budgeted_amount = D("1500.00")
    db_session.commit()
    g = _groups(compute_budget_plan(db_session, user, 2026, 10))["Necessities"]
    assert g.budget == D("2600.00")                         # bills can't be budgeted under
    assert g.rest == D("0")
    assert g.parent_line_short == D("1100.00")


def test_group_without_parent_line_sums_its_rows(db_session):
    user, _, _ = _seed(db_session)
    g = _groups(compute_budget_plan(db_session, user, 2026, 10))["Wants"]
    assert g.parent_line is None
    assert g.committed == D("240.00")
    assert g.flexible == D("400.00")
    assert g.budget == D("640.00")


def test_childless_top_level_categories_group_under_other(db_session):
    user, _, _ = _seed(db_session)
    out = compute_budget_plan(db_session, user, 2026, 10)
    other = _groups(out)["Other"]
    assert {r.category_name for r in other.rows} == {"Charity", "Savings"}
    assert "Salary" not in _rows(out)


def test_track_lines_total_equals_set_view_category_budget(db_session):
    user, _, _ = _seed(db_session)
    out = compute_budget_plan(db_session, user, 2026, 10)
    lines = {l.category_name: l for l in out.lines}
    assert set(lines) == {"Necessities", "Subscriptions", "Shopping", "Charity", "Savings"}
    assert lines["Necessities"].budget == D("3000.00")
    total = sum((l.budget for l in out.lines), D("0"))
    category_groups = [g for g in out.groups if g.kind != "uncategorized"]
    assert total == sum((g.budget for g in category_groups), D("0"))
    assert total == out.category_budget_total == D("4640.00")
    assert out.budget_total == out.category_budget_total + D("310.00")


def test_track_line_actuals_roll_up_into_a_parent_line(db_session):
    user, acct, cats = _seed(db_session)
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=acct.id, date=date(2026, 10, 5),
                           amount=D("-2000.00"), is_actual=True, description="Home loan",
                           category_id=cats["mortgage"].id),
        models.Transaction(user_id=user.id, account_id=acct.id, date=date(2026, 10, 9),
                           amount=D("-50.00"), is_actual=True, description="Grocer",
                           category_id=cats["groceries"].id),
        models.Transaction(user_id=user.id, account_id=acct.id, date=date(2026, 10, 9),
                           amount=D("-30.00"), is_actual=True, description="Store",
                           category_id=cats["shopping"].id),
    ])
    db_session.commit()
    lines = {l.category_name: l for l in compute_budget_plan(db_session, user, 2026, 10).lines}
    assert lines["Necessities"].actual_total == D("2050.00")
    assert lines["Necessities"].is_group is True
    assert lines["Shopping"].actual_total == D("30.00")


def test_parent_with_own_bills_and_no_parent_line_gets_an_own_row(db_session):
    user, acct, cats = _seed(db_session)
    db_session.add(models.RecurringItem(
        user_id=user.id, account_id=acct.id, category_id=cats["wants"].id, name="Club",
        amount=D("50.00"), type=models.RecurringType.expense,
        frequency=models.RecurringFrequency.monthly, day_of_month=5, start_date=date(2026, 1, 1),
    ))
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, date=date(2026, 10, 5), amount=D("-50.00"),
        is_actual=True, description="Club", category_id=cats["wants"].id))
    db_session.add(models.Transaction(
        user_id=user.id, account_id=acct.id, date=date(2026, 10, 6), amount=D("-30.00"),
        is_actual=True, description="Store", category_id=cats["shopping"].id))
    db_session.commit()
    out = compute_budget_plan(db_session, user, 2026, 10)
    g = _groups(out)["Wants"]
    own = [r for r in g.rows if r.category_id == cats["wants"].id]
    assert len(own) == 1 and own[0].committed == D("50.00") and own[0].editable is False
    assert g.budget == D("690.00")
    line = next(l for l in out.lines if l.category_id == cats["wants"].id)
    assert line.actual_total == D("50.00")                  # its own spend, not Shopping's


def _add_dining(db_session, user, cats):
    dining = models.Category(user_id=user.id, name="Dining", type=E, is_discretionary=True,
                             parent_id=cats["wants"].id)
    db_session.add(dining); db_session.flush()
    db_session.add(models.BudgetAllocation(user_id=user.id, category_id=dining.id, year=2026,
                                           month=0, budgeted_amount=D("200.00")))
    db_session.commit()


def test_carry_forward_off_ignores_an_assignable_every_month_row(db_session):
    user, _, cats = _seed(db_session, carry_forward=False)
    _add_dining(db_session, user, cats)
    out = compute_budget_plan(db_session, user, 2026, 10)
    rows = _rows(out)
    assert "Dining" not in rows                             # its month=0 row doesn't govern
    assert rows["Shopping"].flexible == D("400.00")        # month-specific row still counts
    assert rows["Shopping"].is_assignable is True
    assert _groups(out)["Wants"].flexible == D("400.00")


def test_carry_forward_on_honours_the_every_month_row(db_session):
    user, _, cats = _seed(db_session, carry_forward=True)
    _add_dining(db_session, user, cats)
    rows = _rows(compute_budget_plan(db_session, user, 2026, 10))
    assert rows["Dining"].flexible == D("200.00") and rows["Dining"].is_set is True


def test_explanation_replays_to_left_to_assign(db_session):
    user, _, _ = _seed(db_session)
    out = compute_budget_plan(db_session, user, 2026, 10)
    ex = out.explain_left_to_assign
    assert replay(ex) == out.left_to_assign == ex.result
    assert children_consistent(ex)


def test_plan_never_writes_budget_data(db_session):
    user, _, _ = _seed(db_session)
    before = sorted((a.category_id, a.month, a.budgeted_amount)
                    for a in db_session.query(models.BudgetAllocation).all())
    compute_budget_plan(db_session, user, 2026, 10)
    db_session.expire_all()
    after = sorted((a.category_id, a.month, a.budgeted_amount)
                   for a in db_session.query(models.BudgetAllocation).all())
    assert before == after


def _client(db_session, user):
    app = FastAPI()
    app.include_router(budget_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_endpoint_returns_plan(db_session):
    user, _, _ = _seed(db_session)
    r = _client(db_session, user).get("/budget/plan", params={"year": 2026, "month": 10})
    assert r.status_code == 200
    assert D(r.json()["left_to_assign"]) == D("100.00")


def test_endpoint_rejects_out_of_range(db_session):
    user, _, _ = _seed(db_session)
    c = _client(db_session, user)
    assert c.get("/budget/plan", params={"year": 2026, "month": 13}).status_code == 400
    assert c.get("/budget/plan", params={"year": 0, "month": 10}).status_code == 400


def test_spending_page_budgeted_equals_the_plan(db_session):
    """Spending's "of $Y budgeted" reads the plan, so it can't double-count a
    parent line plus its children and always agrees with Track/Set."""
    from backend.routers import spending as spending_router_module
    user, _, cats = _seed(db_session)
    _add_dining(db_session, user, cats)
    plan = compute_budget_plan(db_session, user, 2026, 10)
    app = FastAPI()
    app.include_router(spending_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    r = TestClient(app).get("/spending/by-category", params={"start": "2026-10-01", "end": "2026-10-31"})
    assert r.status_code == 200
    body = r.json()
    tops = {c["category_name"]: c for c in body["categories"]}
    groups = _groups(plan)
    assert D(tops["Necessities"]["budgeted"]) == groups["Necessities"].budget == D("3000.00")
    assert D(tops["Wants"]["budgeted"]) == groups["Wants"].budget == D("840.00")
    rows = _rows(plan)
    kids = {k["category_name"]: D(k["budgeted"]) for k in tops["Wants"]["children"]}
    assert kids["Subscriptions"] == rows["Subscriptions"].budget
    assert D(tops["Charity"]["budgeted"]) == rows["Charity"].budget
    # Spending leaves savings-type categories out; everything else matches Track.
    expense_lines = sum((l.budget for l in plan.lines if l.category_name != "Savings"), D("0"))
    assert D(body["total_budgeted"]) == expense_lines == D("4340.00")


def test_spending_page_scales_the_plan_to_a_partial_month(db_session):
    from backend.routers import spending as spending_router_module
    user, _, _ = _seed(db_session)
    app = FastAPI()
    app.include_router(spending_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    r = TestClient(app).get("/spending/by-category", params={"start": "2026-10-01", "end": "2026-10-15"})
    tops = {c["category_name"]: D(c["budgeted"]) for c in r.json()["categories"]}
    assert tops["Necessities"].quantize(D("0.01")) == (D("3000.00") * 15 / 31).quantize(D("0.01"))


def test_guard_dashboard_leftover_unchanged_by_classification_and_setting(db_session):
    """Ported from the retired left_to_budget tests: classifying bills and
    flipping carry-forward must not move the Dashboard's figures, and building
    the plan must not either."""
    from unittest.mock import patch
    from backend.services.budget_snapshot import compute_budget_snapshot, leftover_parts
    from backend.tests.test_budget_snapshot import _seed_spreadsheet_scenario, _fake_quarter_min
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
    compute_budget_plan(db_session, user, 2026, 8)

    with patch("backend.services.budget_snapshot.build_forecast", return_value=_fake_quarter_min("5120.66")):
        after = compute_budget_snapshot(db_session, user, checking.id, as_of=as_of)
    assert after.leftover == before.leftover
    assert after.left_to_spend == before.left_to_spend
    assert after.safety_margin == before.safety_margin
    assert leftover_parts(db_session, user, as_of).leftover == before.leftover
