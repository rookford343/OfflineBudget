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
