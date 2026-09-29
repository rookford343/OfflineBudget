# Balance Flow vs. Forecast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Dashboard's Balance Flow card compares this month's actual balance against the forecast saved at the start of the month, looking exactly as it does today.

**Architecture:** Reuse the unused `MonthlyForecastSnapshot` table with two new columns. A new `forecast_baseline` service saves each account's day-by-day forecast once per month, only in the first 7 days. It is triggered by the scheduler sweep and by a new `GET /forecast/baseline` endpoint. The card swaps its dashed "last month" line for the saved forecast when one exists and otherwise renders unchanged.

**Tech Stack:** FastAPI + SQLAlchemy (SQLite) + pytest; React + TypeScript + TanStack Query + Recharts.

**Spec:** `docs/superpowers/specs/2026-09-28-balance-flow-vs-forecast-design.md`

## Global Constraints

- `BASELINE_SAVE_WINDOW_DAYS = 7`. A baseline is only created when `as_of.day <= 7`.
- A saved baseline is never updated or overwritten.
- No change to `build_forecast`, Left to Spend, Safety Margin or any other Dashboard card.
- The live database is never seeded with a fake baseline.
- **The live backend runs `uvicorn --reload`, so saving backend files migrates the user's real DB immediately.** Before the first backend edit, the controller takes a backup: `cd <repo> && .venv/bin/python -c "from backend.services.db_backup import backup_database; print(backup_database('data/budget.db','data/backups/budget_pre_balance_flow_baseline.db'))"`. Implementers never touch `data/` or `backend/*.db`.
- Commits go directly to `main`. Messages describe app behavior only (public repo: no balances, amounts, dates from live data, or place names). End with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` trailer.
- Backend tests: `cd backend && python3 -m pytest ...`. The full suite must stay at 0 failures.
- Frontend gate: `cd frontend && bunx tsc -b --force`. The error set must stay identical to base (39 errors / 11 files, pre-existing), with 0 errors in touched files that had 0. Use bun, never npm.

---

### Task 1: Baseline storage and `ensure_month_baseline`

**Files:**
- Modify: `backend/models.py` (`MonthlyForecastSnapshot`, add two columns after `forecasted_close`)
- Modify: `backend/database.py` (`upgrade_schema` ALTER list)
- Create: `backend/services/forecast_baseline.py`
- Test: `backend/tests/test_forecast_baseline.py` (create)

**Interfaces:**
- Produces:
  - `models.MonthlyForecastSnapshot.taken_on: date | None`, `.daily_points: str | None`
  - `forecast_baseline.BASELINE_SAVE_WINDOW_DAYS = 7`
  - `forecast_baseline.ensure_month_baseline(db, user_id: int, account_id: int, as_of: date) -> models.MonthlyForecastSnapshot | None`
  - `forecast_baseline.get_month_baseline(db, user_id: int, account_id: int, year: int, month: int) -> models.MonthlyForecastSnapshot | None`
  - `forecast_baseline.baseline_points(row) -> list[dict] | None`. It returns `[{"date": "YYYY-MM-DD", "projected_balance": "1074.64"}, ...]`, or `None` if the column is missing or malformed.
  - `forecast_baseline.ensure_baselines_for_all(db, as_of: date) -> int`. It returns the number of accounts that have a baseline after the call; one account's failure is logged and skipped.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_forecast_baseline.py
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from backend import models
from backend.schemas import ForecastEntry
from backend.services.forecast_baseline import (
    ensure_month_baseline, get_month_baseline, baseline_points, ensure_baselines_for_all,
)

ENGINE = "backend.services.forecast_baseline.build_forecast"


def _seed(db, username="fb"):
    user = models.User(username=username, hashed_password="x", display_name="FB")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                          current_balance=Decimal("1000.00"))
    db.add(acct); db.commit()
    return user, acct


def _fake(start: date, end: date, base="1000.00"):
    out, d, n = [], start, 0
    while d <= end:
        out.append(ForecastEntry(date=d, projected_balance=Decimal(base) - n, transactions=[]))
        d += timedelta(days=1); n += 1
    return out


def test_saves_one_point_per_day_of_the_month(db_session):
    user, acct = _seed(db_session)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)) as eng:
        row = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    assert eng.call_args.args[3:5] == (date(2026, 10, 1), date(2026, 10, 31))
    pts = baseline_points(row)
    assert len(pts) == 31
    assert pts[0] == {"date": "2026-10-01", "projected_balance": "1000.00"}
    assert pts[-1]["date"] == "2026-10-31"
    assert row.taken_on == date(2026, 10, 1)
    assert row.forecasted_open == Decimal("1000.00")
    assert row.forecasted_close == Decimal("970.00")


def test_second_call_returns_the_same_row_unchanged(db_session):
    user, acct = _seed(db_session)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)):
        first = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e, base="5.00")) as eng:
        second = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 3))
    assert eng.call_count == 0
    assert second.id == first.id
    assert baseline_points(second)[0]["projected_balance"] == "1000.00"
    assert second.taken_on == date(2026, 10, 1)
    assert db_session.query(models.MonthlyForecastSnapshot).count() == 1


def test_save_window_day_7_creates_day_8_does_not(db_session):
    user, acct = _seed(db_session)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)):
        assert ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 7)) is not None
        assert ensure_month_baseline(db_session, user.id, acct.id, date(2026, 11, 8)) is None
    assert get_month_baseline(db_session, user.id, acct.id, 2026, 11) is None


def test_existing_row_is_returned_even_after_the_window(db_session):
    user, acct = _seed(db_session)
    with patch(ENGINE, side_effect=lambda db, u, a, s, e, **kw: _fake(s, e)):
        ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 2))
        assert ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 20)) is not None


def test_real_engine_produces_a_full_month(db_session):
    user, acct = _seed(db_session)
    row = ensure_month_baseline(db_session, user.id, acct.id, date(2026, 10, 1))
    assert [p["date"] for p in baseline_points(row)][:2] == ["2026-10-01", "2026-10-02"]
    assert len(baseline_points(row)) == 31


def test_malformed_points_read_as_none(db_session):
    user, acct = _seed(db_session)
    row = models.MonthlyForecastSnapshot(user_id=user.id, account_id=acct.id, year=2026, month=10,
                                         forecasted_open=Decimal("0"), forecasted_close=Decimal("0"),
                                         daily_points="not json")
    db_session.add(row); db_session.commit()
    assert baseline_points(row) is None
    assert baseline_points(None) is None


def test_ensure_for_all_covers_active_checking_only_and_survives_a_failure(db_session):
    user, acct = _seed(db_session)
    other_user, other_acct = _seed(db_session, username="fb2")
    savings = models.Account(user_id=user.id, name="Sav", type=models.AccountType.savings)
    closed = models.Account(user_id=user.id, name="Old", type=models.AccountType.checking, is_active=False)
    db_session.add_all([savings, closed]); db_session.commit()

    def engine(db, u, a, s, e, **kw):
        if a == other_acct.id:
            raise RuntimeError("boom")
        return _fake(s, e)

    with patch(ENGINE, side_effect=engine):
        assert ensure_baselines_for_all(db_session, date(2026, 10, 1)) == 1
    saved = {r.account_id for r in db_session.query(models.MonthlyForecastSnapshot).all()}
    assert saved == {acct.id}
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && python3 -m pytest tests/test_forecast_baseline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.forecast_baseline'`.

- [ ] **Step 3: Add the columns**

In `backend/models.py`, inside `MonthlyForecastSnapshot` directly after `forecasted_close`:

```python
    # The month's day-by-day forecast as it stood when first saved (see
    # services/forecast_baseline.py). JSON list of {"date", "projected_balance"}.
    # Never rewritten, so the Dashboard can show how far the month drifted
    # from what was expected rather than from a line that moves with every edit.
    taken_on: Mapped[date | None] = mapped_column(Date)
    daily_points: Mapped[str | None] = mapped_column(Text)
```

In `backend/database.py` `upgrade_schema`, append to the ALTER list:

```python
        "ALTER TABLE monthly_forecast_snapshots ADD COLUMN taken_on DATE",
        "ALTER TABLE monthly_forecast_snapshots ADD COLUMN daily_points TEXT",
```

- [ ] **Step 4: Create the service**

```python
# backend/services/forecast_baseline.py
"""The forecast as it stood at the start of the month, saved once.

The Dashboard's Balance Flow card measures how far the month is drifting from
plan. A forecast recomputed on demand would move every time a recurring item
is edited and quietly absorb the drift, so the day-by-day projection is saved
the first time it's asked for in a month and never rewritten.
"""
from __future__ import annotations
import calendar
import json
import logging
from datetime import date
from sqlalchemy.orm import Session
from backend import models
from backend.services.forecast_engine import build_forecast

logger = logging.getLogger(__name__)

# Only save in the first week. A forecast saved late is mostly actuals and
# would report almost no deviation, which misleads; a week still covers a Mac
# that slept through the 1st.
BASELINE_SAVE_WINDOW_DAYS = 7


def get_month_baseline(db: Session, user_id: int, account_id: int, year: int, month: int):
    return db.query(models.MonthlyForecastSnapshot).filter(
        models.MonthlyForecastSnapshot.user_id == user_id,
        models.MonthlyForecastSnapshot.account_id == account_id,
        models.MonthlyForecastSnapshot.year == year,
        models.MonthlyForecastSnapshot.month == month,
    ).first()


def ensure_month_baseline(db: Session, user_id: int, account_id: int, as_of: date):
    existing = get_month_baseline(db, user_id, account_id, as_of.year, as_of.month)
    if existing is not None:
        return existing
    if as_of.day > BASELINE_SAVE_WINDOW_DAYS:
        return None

    start = date(as_of.year, as_of.month, 1)
    end = date(as_of.year, as_of.month, calendar.monthrange(as_of.year, as_of.month)[1])
    entries = build_forecast(db, user_id, account_id, start, end)
    points = [
        {"date": e.date.isoformat(), "projected_balance": f"{e.projected_balance:.2f}"}
        for e in entries
    ]
    row = models.MonthlyForecastSnapshot(
        user_id=user_id, account_id=account_id, year=as_of.year, month=as_of.month,
        forecasted_open=entries[0].projected_balance if entries else 0,
        forecasted_close=entries[-1].projected_balance if entries else 0,
        taken_on=as_of,
        daily_points=json.dumps(points),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def baseline_points(row) -> list[dict] | None:
    if row is None or not row.daily_points:
        return None
    try:
        points = json.loads(row.daily_points)
    except (TypeError, ValueError):
        return None
    return points if isinstance(points, list) and points else None


def ensure_baselines_for_all(db: Session, as_of: date) -> int:
    """Every active checking account, one at a time; a failure on one is
    logged and never stops the others (or the scheduler sweep calling this)."""
    accounts = db.query(models.Account).filter(
        models.Account.type == models.AccountType.checking,
        models.Account.is_active == True,
    ).all()
    saved = 0
    for acct in accounts:
        try:
            if ensure_month_baseline(db, acct.user_id, acct.id, as_of) is not None:
                saved += 1
        except Exception:
            db.rollback()
            logger.exception("Could not save forecast baseline for account %s", acct.id)
    return saved
```

- [ ] **Step 5: Run the tests and confirm they pass, then run the full suite**

Run: `cd backend && python3 -m pytest tests/test_forecast_baseline.py -v`, which should pass all 7.
Run: `cd backend && python3 -m pytest -q`, which should show 0 failures.

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/database.py backend/services/forecast_baseline.py backend/tests/test_forecast_baseline.py
git commit -m "feat: save each month's day-by-day forecast once, in the first week"
```

---

### Task 2: Baseline endpoint and scheduler wiring

**Files:**
- Modify: `backend/schemas.py` (append)
- Modify: `backend/routers/forecast.py` (new route directly after `get_forecast`)
- Modify: `backend/main.py` (`_scheduler_sweep`)
- Test: `backend/tests/test_forecast_baseline_endpoint.py` (create)

**Interfaces:**
- Consumes: `ensure_month_baseline`, `get_month_baseline`, `baseline_points` (Task 1).
- Produces: `GET /forecast/baseline?account_id=&year=&month=` → `schemas.ForecastBaselineOut {year, month, taken_on: date, points: [{date: date, projected_balance: Decimal}]}`. It returns 404 when there's no baseline or the account isn't the user's, and 503 if the engine fails while saving.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_forecast_baseline_endpoint.py
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.dependencies import get_db, get_current_user
from backend.routers import forecast as forecast_router_module
from backend.schemas import ForecastEntry

ENGINE = "backend.services.forecast_baseline.build_forecast"
TODAY = "backend.routers.forecast._today"


def _client(db, user):
    app = FastAPI()
    app.include_router(forecast_router_module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _seed(db, username="ep"):
    user = models.User(username=username, hashed_password="x", display_name="EP")
    db.add(user); db.flush()
    acct = models.Account(user_id=user.id, name="Chk", type=models.AccountType.checking,
                          current_balance=Decimal("500.00"))
    db.add(acct); db.commit()
    return user, acct


def _fake(db, u, a, s, e, **kw):
    out, d = [], s
    while d <= e:
        out.append(ForecastEntry(date=d, projected_balance=Decimal("500.00"), transactions=[]))
        d += timedelta(days=1)
    return out


def test_current_month_creates_and_returns_points(db_session):
    user, acct = _seed(db_session)
    with patch(TODAY, return_value=date(2026, 10, 2)), patch(ENGINE, side_effect=_fake):
        r = _client(db_session, user).get("/forecast/baseline", params={"account_id": acct.id, "year": 2026, "month": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["taken_on"] == "2026-10-02"
    assert len(body["points"]) == 31
    assert body["points"][0] == {"date": "2026-10-01", "projected_balance": "500.00"}


def test_current_month_after_the_window_is_404(db_session):
    user, acct = _seed(db_session)
    with patch(TODAY, return_value=date(2026, 9, 28)), patch(ENGINE, side_effect=_fake) as eng:
        r = _client(db_session, user).get("/forecast/baseline", params={"account_id": acct.id, "year": 2026, "month": 9})
    assert r.status_code == 404
    assert eng.call_count == 0


def test_past_month_without_a_row_is_404_and_never_created(db_session):
    user, acct = _seed(db_session)
    with patch(TODAY, return_value=date(2026, 10, 2)), patch(ENGINE, side_effect=_fake) as eng:
        r = _client(db_session, user).get("/forecast/baseline", params={"account_id": acct.id, "year": 2026, "month": 9})
    assert r.status_code == 404
    assert eng.call_count == 0


def test_other_users_account_is_404(db_session):
    user, _ = _seed(db_session)
    _, theirs = _seed(db_session, username="other")
    with patch(TODAY, return_value=date(2026, 10, 2)), patch(ENGINE, side_effect=_fake):
        r = _client(db_session, user).get("/forecast/baseline", params={"account_id": theirs.id, "year": 2026, "month": 10})
    assert r.status_code == 404


def test_engine_failure_is_503(db_session):
    user, acct = _seed(db_session)
    with patch(TODAY, return_value=date(2026, 10, 2)), patch(ENGINE, side_effect=RuntimeError("boom")):
        r = _client(db_session, user).get("/forecast/baseline", params={"account_id": acct.id, "year": 2026, "month": 10})
    assert r.status_code == 503
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && python3 -m pytest tests/test_forecast_baseline_endpoint.py -v`
Expected: FAIL. The route is missing, so requests 404/422, and patching `backend.routers.forecast._today` raises `AttributeError`.

- [ ] **Step 3: Add the schemas**

Append to `backend/schemas.py`:

```python
class ForecastBaselinePoint(BaseModel):
    date: date
    projected_balance: Decimal


class ForecastBaselineOut(BaseModel):
    year: int
    month: int
    taken_on: date
    points: list[ForecastBaselinePoint]
```

- [ ] **Step 4: Add the route**

In `backend/routers/forecast.py`, add a module-level helper under the `router = ...` line:

```python
def _today() -> date:
    # Indirection so tests can pin "today" without patching the date class.
    return date.today()
```

Directly after `get_forecast` (before `/risk`):

```python
@router.get("/baseline", response_model=schemas.ForecastBaselineOut)
def get_forecast_baseline(
    account_id: int,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """The month's forecast as saved at the start of the month (see
    services/forecast_baseline.py). Only the current month can be created,
    and only in its first week; anything else is read-only."""
    from backend.services.forecast_baseline import ensure_month_baseline, get_month_baseline, baseline_points
    if not db.query(models.Account).filter(
        models.Account.id == account_id, models.Account.user_id == user.id,
    ).first():
        raise HTTPException(status_code=404, detail="Account not found")

    today = _today()
    if (year, month) == (today.year, today.month):
        try:
            row = ensure_month_baseline(db, user.id, account_id, today)
        except Exception:
            db.rollback()
            raise HTTPException(status_code=503, detail="Forecast baseline unavailable")
    else:
        row = get_month_baseline(db, user.id, account_id, year, month)

    points = baseline_points(row)
    if row is None or points is None or row.taken_on is None:
        raise HTTPException(status_code=404, detail="No forecast baseline for this month")
    return schemas.ForecastBaselineOut(year=row.year, month=row.month, taken_on=row.taken_on, points=points)
```

- [ ] **Step 5: Wire the scheduler sweep**

In `backend/main.py` `_scheduler_sweep`, inside the `try:` block after the `daily_summary` retry block (before `finally:`):

```python
        # Start-of-month forecast for the Dashboard's Balance Flow card. Cheap
        # no-op once saved; guarded so a failure can't block the jobs above.
        try:
            from backend.services.forecast_baseline import ensure_baselines_for_all
            ensure_baselines_for_all(db, date.today())
        except Exception:
            logger.exception("Scheduler sweep: forecast baseline step failed")
```

Add `from datetime import date` to `main.py`'s imports if it isn't already there.

- [ ] **Step 6: Run the tests and the full suite**

Run: `cd backend && python3 -m pytest tests/test_forecast_baseline_endpoint.py tests/test_forecast_baseline.py -v`, which should pass all of them.
Run: `cd backend && python3 -m pytest -q`, which should show 0 failures.

- [ ] **Step 7: Commit**

```bash
git add backend/schemas.py backend/routers/forecast.py backend/main.py backend/tests/test_forecast_baseline_endpoint.py
git commit -m "feat: forecast baseline endpoint, saved by the scheduler sweep too"
```

---

### Task 3: Balance Flow card compares against the saved forecast

**Files:**
- Modify: `frontend/src/api/index.ts` (`forecastApi`, ~line 103)
- Modify: `frontend/src/pages/Dashboard.tsx` (queries ~83-107; card ~342-420)

**Interfaces:**
- Consumes: `GET /forecast/baseline` (Task 2); decimals and dates arrive as strings.
- Produces: `forecastApi.baseline(accountId, year, month)`, which returns the payload or `null` on 404; React Query key `["forecast-baseline", accountId, year, month]`.

- [ ] **Step 1: API client**

Inside `forecastApi` in `frontend/src/api/index.ts`:

```ts
  // null when the month has no saved start-of-month forecast (404).
  baseline: (accountId: number, year: number, month: number) =>
    api.get("/forecast/baseline", { params: { account_id: accountId, year, month } })
      .then((r) => r.data)
      .catch((e) => (e?.response?.status === 404 ? null : Promise.reject(e))),
```

- [ ] **Step 2: Query in Dashboard**

In `frontend/src/pages/Dashboard.tsx`, directly after the `lastMonthFlow` query:

```tsx
  // The forecast as saved at the start of this month. When present, the
  // Balance Flow card measures drift from plan instead of comparing against
  // last month (the user, 2026-09-28). Absent (e.g. the month before this shipped,
  // or first opened after day 7), the card keeps its last-month view.
  const [baseYear, baseMonth] = monthStart.split("-").map(Number);
  const { data: baseline = null } = useQuery<any>({
    queryKey: ["forecast-baseline", primaryChecking?.id, baseYear, baseMonth],
    queryFn: () => forecastApi.baseline(primaryChecking.id, baseYear, baseMonth),
    enabled: !!primaryChecking,
    retry: false,
  });
```

- [ ] **Step 3: Card body**

In the Balance Flow card IIFE, replace everything from `const byDay = new Map...` through the `sameDayPct` block with:

```tsx
        // Reference line: the saved start-of-month forecast when there is
        // one, otherwise last month's actuals. Keyed by day-of-month either
        // way so both lines share an X position.
        const reference: any[] = baseline?.points ?? lastMonthFlow;
        const refIsForecast = !!baseline?.points;
        const byDay = new Map<number, { day: number; thisMonth?: number; reference?: number }>();
        for (const e of reference) {
          const day = parseInt(e.date.slice(-2), 10);
          byDay.set(day, { day, reference: parseFloat(e.projected_balance) });
        }
        for (const e of balanceFlow) {
          const day = parseInt(e.date.slice(-2), 10);
          const row = byDay.get(day) ?? { day };
          row.thisMonth = parseFloat(e.projected_balance);
          byDay.set(day, row);
        }
        const chartData = [...byDay.values()].sort((a, b) => a.day - b.day);

        const first = balanceFlow.length ? parseFloat(balanceFlow[0].projected_balance) : null;
        const last = balanceFlow.length ? parseFloat(balanceFlow[balanceFlow.length - 1].projected_balance) : null;

        const lastMonthName = new Date(lastMonthRange.start + "T12:00:00").toLocaleDateString("en-US", { month: "long" });
        const thisMonthName = new Date(monthStart + "T12:00:00").toLocaleDateString("en-US", { month: "long" });
        const todayDay = parseInt(todayStr.slice(-2), 10);
        const sameDayRef = reference.find((e: any) => parseInt(e.date.slice(-2), 10) === todayDay);
        const refToday = sameDayRef ? parseFloat(sameDayRef.projected_balance) : null;

        // Headline: drift from forecast when there's a baseline, otherwise
        // the month-to-date change it has always shown.
        const delta = refIsForecast
          ? (last != null && refToday != null ? last - refToday : null)
          : (first != null && last != null ? last - first : null);
        const sameDayPct = refToday != null && last != null && refToday !== 0
          ? ((last - refToday) / Math.abs(refToday)) * 100
          : null;
        const refName = refIsForecast ? "Forecast" : lastMonthName;
        const savedOn = refIsForecast
          ? new Date(baseline.taken_on + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })
          : null;
```

Then in the JSX of the same card:

- Subtitle becomes:
```tsx
                  {refIsForecast
                    ? <>{thisMonthName} so far, vs. forecast from {savedOn}</>
                    : <>{thisMonthName} so far, vs. all of {lastMonthName}</>}
```
- Tooltip formatter's name mapping becomes `name === "thisMonth" ? thisMonthName : refName`.
- The dashed `<Line>` changes only `dataKey="lastMonth"` → `dataKey="reference"`. Stroke, width, dash and animation stay the same.
- Footer becomes:
```tsx
            {sameDayRef && sameDayPct != null && (
              <p className="text-xs text-gray-400 mt-2">
                {refIsForecast ? <>Forecast for day {todayDay}: </> : <>In {lastMonthName} on day {todayDay}: </>}
                {maskIfHidden(balancesHidden, fmt(refToday!))}
                {" "}({sameDayPct >= 0 ? "+" : ""}{sameDayPct.toFixed(1)}%)
              </p>
            )}
```
- The card's render guard becomes `(balanceFlow.length > 0 || reference-bearing data)`. Change `{(balanceFlow.length > 0 || lastMonthFlow.length > 0) && (() => {` to `{(balanceFlow.length > 0 || lastMonthFlow.length > 0 || !!baseline?.points) && (() => {`.

Everything else in the card (container, header layout, gradient, grid, axes, heights, colors) is unchanged.

- [ ] **Step 4: Type-check**

Run: `cd frontend && bunx tsc -b --force 2>&1 | grep -oE "^src/[^(]+" | sort | uniq -c`
Expected: identical per-file counts to base, with `src/pages/Dashboard.tsx` still at 2 and `src/api/index.ts` absent.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/pages/Dashboard.tsx
git commit -m "feat: Balance Flow compares the month against its saved start-of-month forecast"
```

---

### Task 4: Verification (controller)

- [ ] Full backend suite: `cd backend && python3 -m pytest -q` shows 0 failures.
- [ ] `graphify update .`
- [ ] Interceptor (test profile): the Dashboard Balance Flow card renders exactly as before (fallback view, since September has no baseline), with 0 console errors, and `GET /forecast/baseline` for September returns 404.
- [ ] Leave a note to re-verify on or after 2026-10-01: dashed forecast line, headline, "vs. forecast from Oct N" subtitle and "Forecast for day N" footer.
