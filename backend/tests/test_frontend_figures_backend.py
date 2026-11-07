"""Budget, Spending, Recurring and Forecast figures the frontend used to compute.

Each figure below moved from a React page onto the backend (Plan 2, Task 6):
Track Budgets totals, a parent category's direct spend, a category's monthly
average, a recurring item's monthly equivalent, and whether a day checkpoint
moved the forecast. Synthetic round numbers only.
"""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import models, schemas
from backend.dependencies import get_current_user, get_db
from backend.routers import recurring as recurring_router_module
from backend.routers import spending as spending_router_module
from backend.services.budget_plan import compute_budget_plan
from backend.services.budget_track import line_available, track_totals
from backend.services.forecast_engine import build_forecast
from backend.tests.test_budget_plan import _seed as seed_plan

D = Decimal


def _line(cid, budget, actual, *, rollover=False, balance="0") -> schemas.PlanTrackLine:
    return schemas.PlanTrackLine(
        category_id=cid, category_name=f"C{cid}", is_group=False, committed=D("0"),
        flexible=D(budget), budget=D(budget), actual_total=D(actual),
        rollover_enabled=rollover, rollover_balance=D(balance),
    )


def _client(db, user, *routers) -> TestClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


# ── Track Budgets totals ──────────────────────────────────────────────────────

def test_track_totals_match_legacy_rule():
    t = track_totals([_line(1, "3000.00", "2050.00"), _line(2, "500.00", "600.00"), _line(3, "140.10", "0")])
    assert t.budgeted == D("3640.10")
    assert t.available == D("3640.10")
    assert t.spent == D("2650.00")
    assert t.left == D("990.10")
    assert t.over_count == 1
    assert t.pct == D("2650.00") / D("3640.10") * 100


def test_track_totals_rollover_only_counts_when_enabled():
    on = _line(1, "100.00", "0", rollover=True, balance="50.00")
    off = _line(2, "100.00", "0", rollover=False, balance="50.00")
    assert line_available(on) == D("150.00")
    assert line_available(off) == D("100.00")
    t = track_totals([on, off])
    assert (t.budgeted, t.available) == (D("200.00"), D("250.00"))


def test_track_totals_no_lines_is_zero_without_dividing():
    t = track_totals([])
    assert (t.available, t.pct, t.over_count) == (D("0"), D("0"), 0)


def test_plan_carries_track_totals_and_visible_footers(db_session):
    user, _, _ = seed_plan(db_session)
    out = compute_budget_plan(db_session, user, 2026, 10)
    assert out.track_totals == track_totals(out.lines)
    assert out.track_totals.budgeted == out.category_budget_total
    # The footer row sums the groups the page lists: everything but "Not in a category".
    shown = [g for g in out.groups if g.kind != "uncategorized"]
    assert out.committed_visible_total == sum((g.committed for g in shown), D("0"))
    assert out.flexible_visible_total == sum((g.flexible for g in shown), D("0"))
    assert out.committed_visible_total == out.committed_total - D("310.00")
    assert out.flexible_visible_total == out.flexible_total
    for ln in out.lines:
        assert ln.available == line_available(ln)
        assert ln.left == ln.available - ln.actual_total


# ── Spending ──────────────────────────────────────────────────────────────────

def _spend_user(db):
    user = models.User(username="sp", hashed_password="x", display_name="S")
    db.add(user)
    db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                          current_balance=D("1000.00"))
    db.add(acct)
    db.flush()
    return user, acct


def _cat(db, user, name, parent=None):
    c = models.Category(user_id=user.id, name=name, type=models.CategoryType.expense,
                        color="#888888", parent_id=parent.id if parent else None)
    db.add(c)
    db.flush()
    return c


def _spend(db, user, acct, cat, amount, when):
    db.add(models.Transaction(user_id=user.id, account_id=acct.id, date=when, amount=D(amount),
                              description="x", is_actual=True, category_id=cat.id))
    db.flush()


def test_direct_actual_is_parent_minus_children(db_session):
    user, acct = _spend_user(db_session)
    wants = _cat(db_session, user, "Wants")
    dining = _cat(db_session, user, "Dining", wants)
    _spend(db_session, user, acct, dining, "-30.00", date(2026, 3, 5))
    _spend(db_session, user, acct, wants, "-12.50", date(2026, 3, 6))  # filed on the parent itself
    body = _client(db_session, user, spending_router_module).get(
        "/spending/by-category", params={"start": "2026-03-01", "end": "2026-03-31"}).json()
    parent = next(c for c in body["categories"] if c["category_name"] == "Wants")
    kids = sum(D(str(k["actual"])) for k in parent["children"])
    assert D(str(parent["actual"])) == D("42.50")
    assert D(str(parent["direct_actual"])) == D(str(parent["actual"])) - kids == D("12.50")


def test_direct_actual_is_zero_when_nothing_is_filed_on_the_parent(db_session):
    user, acct = _spend_user(db_session)
    wants = _cat(db_session, user, "Wants")
    _spend(db_session, user, acct, _cat(db_session, user, "Dining", wants), "-30.00", date(2026, 3, 5))
    body = _client(db_session, user, spending_router_module).get(
        "/spending/by-category", params={"start": "2026-03-01", "end": "2026-03-31"}).json()
    assert D(str(body["categories"][0]["direct_actual"])) == D("0")


def test_monthly_average_excludes_current_month(db_session, monkeypatch):
    user, acct = _spend_user(db_session)
    dining = _cat(db_session, user, "Dining")
    _spend(db_session, user, acct, dining, "-100.00", date(2026, 1, 10))
    _spend(db_session, user, acct, dining, "-50.00", date(2026, 2, 10))
    _spend(db_session, user, acct, dining, "-900.00", date(2026, 3, 10))  # the partial, current month

    class _Fixed(date):
        @classmethod
        def today(cls):
            return date(2026, 3, 15)
    monkeypatch.setattr("backend.routers.spending.date", _Fixed)

    rows = _client(db_session, user, spending_router_module).get(
        "/spending/monthly-by-category", params={"start": "2026-01-01", "end": "2026-03-31"}).json()
    assert [r["month"] for r in rows] == ["2026-01", "2026-02", "2026-03"]
    for r in rows:
        assert D(str(r["categories"][0]["monthly_average"])) == D("75.00")


def test_monthly_average_counts_a_zero_month_and_is_null_with_no_full_month(db_session, monkeypatch):
    user, acct = _spend_user(db_session)
    dining = _cat(db_session, user, "Dining")
    fun = _cat(db_session, user, "Fun")
    _spend(db_session, user, acct, dining, "-100.00", date(2026, 1, 10))
    _spend(db_session, user, acct, fun, "-60.00", date(2026, 2, 10))

    class _Fixed(date):
        @classmethod
        def today(cls):
            return date(2026, 3, 15)
    monkeypatch.setattr("backend.routers.spending.date", _Fixed)
    c = _client(db_session, user, spending_router_module)
    rows = c.get("/spending/monthly-by-category", params={"start": "2026-01-01", "end": "2026-02-28"}).json()
    avg = {x["category_name"]: D(str(x["monthly_average"])) for r in rows for x in r["categories"]}
    assert avg == {"Dining": D("50.00"), "Fun": D("30.00")}  # a $0 month still counts

    class _FixedJan(date):
        @classmethod
        def today(cls):
            return date(2026, 1, 20)
    monkeypatch.setattr("backend.routers.spending.date", _FixedJan)
    only = c.get("/spending/monthly-by-category", params={"start": "2026-01-01", "end": "2026-01-31"}).json()
    assert only[0]["categories"][0]["monthly_average"] is None


# ── Recurring ─────────────────────────────────────────────────────────────────

def test_breakdown_covers_inactive_items(db_session):
    user, acct = _spend_user(db_session)

    def item(name, amount, freq, active):
        db_session.add(models.RecurringItem(
            user_id=user.id, account_id=acct.id, name=name, amount=D(amount),
            type=models.RecurringType.expense, frequency=freq, day_of_month=5,
            start_date=date(2026, 1, 1), is_active=active))

    item("Paused weekly", "100.00", models.RecurringFrequency.weekly, False)
    item("Live biweekly", "100.00", models.RecurringFrequency.biweekly, True)
    db_session.commit()
    body = _client(db_session, user, recurring_router_module).get("/recurring/breakdown").json()
    everyone = body["ongoing"] + body["ending"] + body["inactive"]
    by_name = {i["name"]: D(str(i["monthly_equivalent"])) for i in everyone}
    assert set(by_name) == {"Paused weekly", "Live biweekly"}
    assert by_name["Paused weekly"] != D("100.00")  # not amount / 1
    assert by_name["Paused weekly"] > D("400.00")
    # Inactive items never feed the totals.
    assert [i["name"] for i in body["inactive"]] == ["Paused weekly"]
    assert D(str(body["ongoing_monthly"])) == by_name["Live biweekly"]


# ── Forecast ──────────────────────────────────────────────────────────────────

TODAY = date(2026, 4, 22)


def _freeze_today(monkeypatch, fixed: date) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed
    monkeypatch.setattr("backend.services.forecast_engine.date", _FixedDate)


def test_anchor_moved_flag(db_session, monkeypatch):
    _freeze_today(monkeypatch, TODAY)
    user = models.User(username="fc", hashed_password="x", display_name="F")
    db_session.add(user)
    db_session.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                          current_balance=D("1000.00"))
    db_session.add(acct)
    db_session.flush()
    start = TODAY + timedelta(days=1)
    day1, day2, day3 = start, start + timedelta(days=1), start + timedelta(days=2)
    base = build_forecast(db_session, user.id, acct.id, start, day3 + timedelta(days=1))
    bal = {e.date: e.projected_balance for e in base}
    assert not any(e.anchor_moved for e in base)  # no checkpoint, nothing moved

    def cp(when, value):
        db_session.add(models.ForecastDayCheckpoint(user_id=user.id, account_id=acct.id, date=when,
                                                actual_balance=value))

    cp(day1, bal[day1])                      # first day of the window: always listed
    cp(day2, bal[day2])                      # lands exactly where the walk did
    cp(day3, bal[day3] + D("25.00"))         # moves the balance
    db_session.commit()
    out = {e.date: e for e in build_forecast(db_session, user.id, acct.id, start, day3 + timedelta(days=1))}
    assert out[day1].anchor_moved is True and out[day1].anchor_delta is None
    assert out[day2].anchor_moved is False and out[day2].anchor_delta == D("0")
    assert out[day3].anchor_moved is True and out[day3].anchor_delta == D("25.00")
    after = out[day3 + timedelta(days=1)]
    assert after.anchor_moved is False and after.anchor_delta is None  # no checkpoint that day


def test_monthly_bars_carry_their_average(db_session):
    user, acct = _spend_user(db_session)
    dining = _cat(db_session, user, "Dining")
    _spend(db_session, user, acct, dining, "-100.00", date(2026, 1, 10))
    c = _client(db_session, user, spending_router_module)
    one = c.get("/spending/monthly", params={"start": "2026-01-01", "end": "2026-01-31"}).json()
    assert one[0]["monthly_average"] is None  # one bar has no average line
    _spend(db_session, user, acct, dining, "-50.00", date(2026, 2, 10))
    two = c.get("/spending/monthly", params={"start": "2026-01-01", "end": "2026-02-28"}).json()
    assert [D(str(e["monthly_average"])) for e in two] == [D("75.00"), D("75.00")]


# ── Discretionary left, bill variance, checkpoint conflict (Plan 2, Task 7) ───

def test_discretionary_left_is_budget_minus_spend_and_goes_negative(db_session):
    user, acct = _spend_user(db_session)
    fun = _cat(db_session, user, "Fun")
    fun.is_discretionary = True
    db_session.add(models.BudgetAllocation(user_id=user.id, category_id=fun.id, year=2026, month=3,
                                           budgeted_amount=D("100.00")))
    _spend(db_session, user, acct, fun, "-40.00", date(2026, 3, 5))
    db_session.commit()
    c = _client(db_session, user, spending_router_module)
    params = {"start": "2026-03-01", "end": "2026-03-31"}
    body = c.get("/spending/by-category", params=params).json()
    assert D(str(body["discretionary_budgeted"])) == D("100.00")
    assert D(str(body["discretionary_actual"])) == D("40.00")
    assert D(str(body["discretionary_left"])) == D("60.00")
    _spend(db_session, user, acct, fun, "-85.00", date(2026, 3, 9))
    db_session.commit()
    over = c.get("/spending/by-category", params=params).json()
    assert D(str(over["discretionary_left"])) == D("-25.00")


def test_bill_override_carries_its_variance(db_session):
    from backend.routers import bill_overrides as overrides_router_module
    from backend.tests.test_month_leftover_parity import _expense, _seed

    user, acct = _seed(db_session, "variance", remaining=D("0"))
    item = _expense(db_session, user, acct, "Water", "80.00")
    db_session.commit()
    c = _client(db_session, user, overrides_router_module)
    high = c.post("/bill-overrides", json={
        "recurring_item_id": item.id, "due_date": "2027-02-10", "actual_amount": "92.50"})
    assert high.status_code == 201
    assert D(str(high.json()["variance"])) == D("12.50")
    low = c.post("/bill-overrides", json={
        "recurring_item_id": item.id, "due_date": "2027-02-10", "actual_amount": "75.00"})
    assert D(str(low.json()["variance"])) == D("-5.00")
    listed = c.get("/bill-overrides", params={"upcoming_only": False}).json()
    assert [D(str(o["variance"])) for o in listed] == [D("-5.00")]


def test_quarter_checkpoint_delta_and_conflict(db_session, monkeypatch):
    from backend.routers import forecast as forecast_router_module

    _freeze_today(monkeypatch, TODAY)
    user, acct = _spend_user(db_session)
    c = _client(db_session, user, forecast_router_module)

    def quarters():
        resp = c.get("/forecast/quarters", params={"account_id": acct.id, "year": TODAY.year})
        assert resp.status_code == 200
        return {q["quarter"]: q for q in resp.json()}

    none = quarters()[2]
    assert none["quarter_end_checkpoint"] is None
    assert none["checkpoint_delta"] is None and none["checkpoint_conflict"] is False

    # A checkpoint a few days before quarter end re-anchors the walk; bills that
    # fall after it move the close away from the saved figure.
    from backend.tests.test_month_leftover_parity import _expense

    year = TODAY.year
    db_session.add(models.ForecastDayCheckpoint(
        user_id=user.id, account_id=acct.id, date=date(year, 6, 26), actual_balance=D("1000.00")))
    _expense(db_session, user, acct, "Small", "0.50", day_of_month=29)
    db_session.commit()
    near = quarters()[2]
    assert D(str(near["quarter_end_checkpoint"])) == D("1000.00")
    assert D(str(near["checkpoint_delta"])) == D("1000.00") - D(str(near["close_balance"])) == D("0.50")
    assert near["checkpoint_conflict"] is False  # within a dollar

    _expense(db_session, user, acct, "Large", "40.00", day_of_month=30)
    db_session.commit()
    far = quarters()[2]
    assert D(str(far["checkpoint_delta"])) == D("40.50")
    assert far["checkpoint_conflict"] is True


# ── Balance Flow headline (Plan 2, Task 7 fix round 2) ────────────────────────

def _flow_setup(db, monkeypatch, *, baseline_today):
    """Walk through Nov 5 climbing 10 a day from 1000 (Nov 1) to 1040; a saved
    baseline (when given) says the balance for Nov 5 was `baseline_today`."""
    import json
    from backend.schemas import ForecastEntry

    def fake(db_, user_id, account_id, start, end, **kw):
        return [ForecastEntry(date=start + timedelta(days=i),
                              projected_balance=D("1000.00") + 10 * i, transactions=[])
                for i in range((end - start).days + 1)]

    monkeypatch.setattr("backend.services.forecast_engine.build_forecast", fake)
    monkeypatch.setattr("backend.routers.forecast._today", lambda: date(2026, 11, 5))
    user, acct = _spend_user(db)
    if baseline_today is not None:
        points = [{"date": f"2026-11-0{d}", "projected_balance": f"{900 + 5 * d:.2f}"} for d in range(1, 6)]
        points[-1]["projected_balance"] = baseline_today
        db.add(models.MonthlyForecastSnapshot(
            user_id=user.id, account_id=acct.id, year=2026, month=11, forecasted_open=D("900"),
            forecasted_close=D("900"), taken_on=date(2026, 11, 1), daily_points=json.dumps(points)))
    db.commit()
    return user, acct


def test_balance_flow_month_to_date_and_drift(db_session, monkeypatch):
    from backend.routers import forecast as forecast_router_module
    user, acct = _flow_setup(db_session, monkeypatch, baseline_today="1015.50")
    body = _client(db_session, user, forecast_router_module).get(
        "/forecast/balance-flow", params={"account_id": acct.id}).json()
    assert D(str(body["month_to_date_change"])) == D("40.00")   # 1040 - 1000
    assert D(str(body["drift_from_forecast"])) == D("24.50")    # 1040 - 1015.50


def test_balance_flow_drift_is_negative_and_absent_without_baseline(db_session, monkeypatch):
    from backend.routers import forecast as forecast_router_module
    user, acct = _flow_setup(db_session, monkeypatch, baseline_today="1100.00")
    c = _client(db_session, user, forecast_router_module)
    assert D(str(c.get("/forecast/balance-flow", params={"account_id": acct.id}).json()["drift_from_forecast"])) == D("-60.00")
    db_session.query(models.MonthlyForecastSnapshot).delete()
    db_session.commit()
    body = c.get("/forecast/balance-flow", params={"account_id": acct.id}).json()
    assert body["drift_from_forecast"] is None and D(str(body["month_to_date_change"])) == D("40.00")


def test_balance_flow_404_for_another_users_account(db_session, monkeypatch):
    from backend.routers import forecast as forecast_router_module
    user, acct = _flow_setup(db_session, monkeypatch, baseline_today=None)
    other = models.User(username="other", hashed_password="x", display_name="O")
    db_session.add(other)
    db_session.commit()
    resp = _client(db_session, other, forecast_router_module).get(
        "/forecast/balance-flow", params={"account_id": acct.id})
    assert resp.status_code == 404


# ── Source splits and combined savings (Plan 2 fix wave) ──────────────────────

def test_overview_splits_spend_by_source_and_the_parts_match_the_headlines(db_session):
    user, acct = _spend_user(db_session)
    card = models.CreditCard(user_id=user.id, name="Visa", credit_limit=D("5000"),
                             statement_day=28, due_day=15)
    db_session.add(card)
    db_session.flush()
    fun = _cat(db_session, user, "Fun")
    fun.is_discretionary = True
    rent = _cat(db_session, user, "Housing")
    _spend(db_session, user, acct, fun, "-40.00", date(2026, 3, 5))
    _spend(db_session, user, acct, rent, "-100.00", date(2026, 3, 6))
    db_session.add(models.CreditCardTransaction(
        card_id=card.id, user_id=user.id, date=date(2026, 3, 7), amount=D("25.00"),
        merchant="Shop", category_id=fun.id))
    db_session.commit()
    body = _client(db_session, user, spending_router_module).get(
        "/spending/by-category", params={"start": "2026-03-01", "end": "2026-03-31"}).json()

    def split(key):
        return {k: D(str(v)) for k, v in body[key].items()}

    assert split("discretionary_by_source") == {"Checking": D("40.00"), "Visa": D("25.00")}
    assert split("fixed_by_source") == {"Checking": D("100.00")}
    assert split("total_by_source") == {"Checking": D("140.00"), "Visa": D("25.00")}
    assert sum(split("discretionary_by_source").values()) == D(str(body["discretionary_actual"]))
    assert sum(split("fixed_by_source").values()) == D(str(body["fixed_actual"]))
    assert sum(split("total_by_source").values()) == D(str(body["total_actual"]))


def test_combined_savings_adds_active_savings_accounts_per_day(db_session, monkeypatch):
    from backend.routers import forecast as forecast_router_module

    _freeze_today(monkeypatch, TODAY)
    user, _ = _spend_user(db_session)
    for name, bal, kind, active in [
        ("S1", "100.00", models.AccountType.savings, True),
        ("S2", "250.00", models.AccountType.savings, True),
        ("Old", "999.00", models.AccountType.savings, False),
        ("MM", "777.00", models.AccountType.money_market, True),
    ]:
        db_session.add(models.Account(user_id=user.id, name=name, type=kind,
                                      current_balance=D(bal), is_active=active))
    db_session.commit()
    c = _client(db_session, user, forecast_router_module)
    body = c.get("/forecast/combined-savings", params={"year": TODAY.year, "years": 1}).json()
    by_date = {r["date"]: D(str(r["balance"])) for r in body}
    assert by_date[TODAY.isoformat()] == D("350.00")
    assert len(by_date) >= 365
    multi = c.get("/forecast/combined-savings", params={"year": TODAY.year, "years": 2}).json()
    assert len(multi) >= 730
    assert {r["date"]: D(str(r["balance"])) for r in multi}[TODAY.isoformat()] == D("350.00")
