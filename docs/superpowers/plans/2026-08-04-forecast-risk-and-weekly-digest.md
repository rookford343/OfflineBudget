# Forecast Risk Callout + Weekly Spending Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a proactive negative-balance risk callout to the Forecast page, and a Friday-morning weekly spending digest (category totals + top merchants + the risk callout) delivered by email with an in-app fallback.

**Architecture:** Two features sharing one piece of server-computed logic. The risk detection is a pure function added to `forecast_engine.py`, exposed via a new `GET /forecast/risk` endpoint, and consumed by both the Forecast page banner and the weekly digest generator. The digest reuses the existing daily-summary APScheduler + SMTP pattern in `main.py` / `email_service.py`, adding a sibling Friday job.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), React + TypeScript + `@tanstack/react-query` + Recharts (frontend), APScheduler for cron jobs, `smtplib` for email. pytest is added as a new dev dependency for the two pieces of new pure/query logic that warrant it.

## Global Constraints

- No Alembic migration — new settings are env-vars via `backend/config.py` (matching the existing `DAILY_SUMMARY_HOUR` pattern); no new database tables are needed.
- `npx tsc --noEmit` must exit 0 in `frontend/` after every frontend task.
- No new frontend test framework — frontend changes are verified by `tsc` + manual check via `curl`/browser, per the spec.
- Reuse `Decimal` for all money math on the backend (matches existing codebase convention — never `float` for currency).
- Every new backend money-math function takes explicit, already-fetched data or explicit date ranges — no hidden "today" defaults inside pure functions, so tests are deterministic.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `backend/services/forecast_engine.py` | Modify | Add `find_balance_risk()` — pure function, no DB access |
| `backend/schemas.py` | Modify | Add `ForecastRisk` and `WeeklyDigest` response schemas |
| `backend/routers/forecast.py` | Modify | Add `GET /forecast/risk` |
| `backend/services/spending_helpers.py` | Create | Shared `NOT_SAVINGS` filter + `merchant_totals()` + `category_totals_for_range()` — used by both the existing spending router and the new digest generator |
| `backend/routers/spending.py` | Modify | Import shared filter/helper instead of local copies; add `GET /spending/weekly-digest` |
| `backend/services/summary_generator.py` | Modify | Add `generate_weekly_digest()` |
| `backend/config.py` | Modify | Add `WEEKLY_DIGEST_DAY`, `WEEKLY_DIGEST_HOUR`, `DIGEST_RECIPIENTS` + `digest_recipients_list` property |
| `backend/main.py` | Modify | Add `_send_weekly_digest()` + scheduler job |
| `backend/requirements.txt` | Modify | Add `pytest` |
| `.env.example` | Modify | Document the three new settings |
| `backend/tests/conftest.py` | Create | In-memory SQLite session fixture |
| `backend/tests/test_forecast_risk.py` | Create | Tests for `find_balance_risk()` |
| `backend/tests/test_spending_helpers.py` | Create | Tests for `category_totals_for_range()` / `merchant_totals()` |
| `frontend/src/api/index.ts` | Modify | Add `forecastApi.risk()` and `analyticsApi.weeklyDigest()` |
| `frontend/src/components/RiskBanner.tsx` | Create | Renders the risk callout |
| `frontend/src/pages/Forecast.tsx` | Modify | Wire in `RiskBanner` |
| `frontend/src/pages/Dashboard.tsx` | Modify | Add weekly digest panel |

---

## Task 1: Risk detection pure function + test infra

**Files:**
- Modify: `backend/services/forecast_engine.py`
- Modify: `backend/requirements.txt`
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_forecast_risk.py`

**Interfaces:**
- Produces: `find_balance_risk(entries: list[ForecastEntry], threshold: Decimal) -> dict` — later tasks (Task 2) call this with `threshold` defaulting to `Decimal("0")` when the account has none set.

- [ ] **Step 1: Add pytest to requirements and install**

Edit `backend/requirements.txt`, add this line after `apscheduler>=3.10.0`:

```
pytest>=8.0.0
```

Run: `source .venv/bin/activate && pip install pytest>=8.0.0`
Expected: installs cleanly, no errors.

- [ ] **Step 2: Create the test package and DB fixture**

Create `backend/tests/__init__.py` (empty file, makes `backend/tests` a package).

Create `backend/tests/conftest.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base


@pytest.fixture()
def db_session():
    """Fresh in-memory SQLite session per test — no fixtures shared across tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
```

- [ ] **Step 3: Write the failing test for `find_balance_risk`**

Create `backend/tests/test_forecast_risk.py`:

```python
from datetime import date
from decimal import Decimal
from backend.schemas import ForecastEntry
from backend.services.forecast_engine import find_balance_risk


def _entry(d: date, balance: str) -> ForecastEntry:
    return ForecastEntry(date=d, projected_balance=Decimal(balance), transactions=[])


def test_no_risk_when_balance_stays_above_threshold():
    entries = [
        _entry(date(2026, 8, 1), "500.00"),
        _entry(date(2026, 8, 2), "480.00"),
        _entry(date(2026, 8, 3), "460.00"),
    ]
    result = find_balance_risk(entries, Decimal("0"))
    assert result == {"at_risk": False, "date": None, "amount": None, "threshold": Decimal("0")}


def test_flags_first_day_balance_drops_below_threshold():
    entries = [
        _entry(date(2026, 8, 1), "200.00"),
        _entry(date(2026, 8, 2), "50.00"),
        _entry(date(2026, 8, 3), "-30.00"),
        _entry(date(2026, 8, 4), "-80.00"),
    ]
    result = find_balance_risk(entries, Decimal("0"))
    assert result["at_risk"] is True
    assert result["date"] == date(2026, 8, 3)
    assert result["amount"] == Decimal("-30.00")
    assert result["threshold"] == Decimal("0")


def test_uses_custom_threshold_not_just_zero():
    entries = [
        _entry(date(2026, 8, 1), "200.00"),
        _entry(date(2026, 8, 2), "150.00"),
        _entry(date(2026, 8, 3), "80.00"),
    ]
    result = find_balance_risk(entries, Decimal("100"))
    assert result["at_risk"] is True
    assert result["date"] == date(2026, 8, 3)
    assert result["amount"] == Decimal("80.00")
    assert result["threshold"] == Decimal("100")


def test_empty_entries_returns_no_risk():
    result = find_balance_risk([], Decimal("0"))
    assert result["at_risk"] is False
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /Users/danford/Programming/Dev/OfflineBudget && source .venv/bin/activate && pytest backend/tests/test_forecast_risk.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_balance_risk'`

- [ ] **Step 5: Implement `find_balance_risk`**

In `backend/services/forecast_engine.py`, add after the `build_forecast` function (after line 427, before `build_quarters`):

```python
def find_balance_risk(entries: list[ForecastEntry], threshold: Decimal) -> dict:
    """Scan forecast entries in order and return the first day the balance drops
    below threshold. entries must already be sorted by date ascending (build_forecast
    returns them in that order).
    """
    for entry in entries:
        if entry.projected_balance < threshold:
            return {
                "at_risk": True,
                "date": entry.date,
                "amount": entry.projected_balance,
                "threshold": threshold,
            }
    return {"at_risk": False, "date": None, "amount": None, "threshold": threshold}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest backend/tests/test_forecast_risk.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
cd /Users/danford/Programming/Dev/OfflineBudget
git add backend/services/forecast_engine.py backend/requirements.txt backend/tests/__init__.py backend/tests/conftest.py backend/tests/test_forecast_risk.py
git commit -m "feat: add find_balance_risk pure function + pytest infra"
```

---

## Task 2: Risk API endpoint

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/routers/forecast.py`

**Interfaces:**
- Consumes: `find_balance_risk(entries, threshold)` from Task 1; `build_forecast(db, user_id, account_id, start, end)` (existing).
- Produces: `GET /forecast/risk?account_id=&days=` → `schemas.ForecastRisk` — Task 3 (frontend) calls this endpoint.

- [ ] **Step 1: Add the `ForecastRisk` schema**

In `backend/schemas.py`, add immediately after the `ForecastEntry` class (after line 289, before `class QuarterSummary`):

```python
class ForecastRisk(BaseModel):
    at_risk: bool
    date: Optional[date]
    amount: Optional[Decimal]
    threshold: Decimal
```

- [ ] **Step 2: Add the endpoint**

In `backend/routers/forecast.py`, add the import and new endpoint. Change the import line (line 11) from:

```python
from backend.services.forecast_engine import build_forecast, build_quarters
```

to:

```python
from backend.services.forecast_engine import build_forecast, build_quarters, find_balance_risk
```

Add this endpoint after `get_forecast` (after line 25, before `_attach_quarter_checkpoints`):

```python
@router.get("/risk", response_model=schemas.ForecastRisk)
def get_forecast_risk(
    account_id: int,
    days: int = Query(default=90, ge=1, le=730),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user.id,
    ).first()
    threshold = account.low_balance_threshold if account and account.low_balance_threshold is not None else Decimal("0")
    start = date.today()
    end = start + timedelta(days=days)
    entries = build_forecast(db, user.id, account_id, start, end)
    return find_balance_risk(entries, threshold)
```

- [ ] **Step 3: Verify it starts and responds**

Run:
```bash
cd /Users/danford/Programming/Dev/OfflineBudget
source .venv/bin/activate
uvicorn backend.main:app --port 8000 &
sleep 2
curl -s -H "Authorization: Bearer $(curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' -d '{"username":"danford","password":"<your password>"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")" "http://localhost:8000/forecast/risk?account_id=1&days=90"
kill %1
```
Expected: JSON body matching `ForecastRisk` shape (`at_risk`, `date`, `amount`, `threshold`), HTTP 200. Substitute your real login for the `<your password>` placeholder — this is a manual verification step, not a stored credential.

- [ ] **Step 4: Commit**

```bash
git add backend/schemas.py backend/routers/forecast.py
git commit -m "feat: add GET /forecast/risk endpoint"
```

---

## Task 3: Frontend RiskBanner on the Forecast page

**Files:**
- Modify: `frontend/src/api/index.ts`
- Create: `frontend/src/components/RiskBanner.tsx`
- Modify: `frontend/src/pages/Forecast.tsx`

**Interfaces:**
- Consumes: `GET /forecast/risk` from Task 2, response shape `{ at_risk: boolean, date: string | null, amount: string | null, threshold: string }` (FastAPI serializes `Decimal`/`date` to strings in JSON).
- Produces: `<RiskBanner risk={risk} />` component — self-contained, no other task depends on it.

- [ ] **Step 1: Add the API method**

In `frontend/src/api/index.ts`, in the `forecastApi` object (starts at line 46), add after the `monthlySummary` line (line 55):

```typescript
  risk: (accountId: number, days?: number) =>
    api.get("/forecast/risk", { params: { account_id: accountId, days } }).then((r) => r.data),
```

- [ ] **Step 2: Create the RiskBanner component**

Create `frontend/src/components/RiskBanner.tsx`:

```tsx
import { AlertTriangle } from "lucide-react";
import { fmt } from "../lib/utils";

interface Risk {
  at_risk: boolean;
  date: string | null;
  amount: string | null;
  threshold: string;
}

export function RiskBanner({ risk }: { risk: Risk | undefined }) {
  if (!risk || !risk.at_risk || !risk.date || risk.amount == null) return null;

  const dateLabel = new Date(risk.date + "T00:00:00").toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
  });
  const thresholdNum = parseFloat(risk.threshold);
  const label = thresholdNum > 0
    ? `Projected to drop below ${fmt(thresholdNum)} on ${dateLabel}`
    : `Projected to go negative on ${dateLabel}`;

  return (
    <div className="card border-red-200 dark:border-red-700 bg-red-50/60 dark:bg-red-900/20">
      <div className="flex items-start gap-3">
        <AlertTriangle size={18} className="text-red-500 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-red-900 dark:text-red-200 text-sm">{label}</p>
          <p className="text-xs text-red-700 dark:text-red-400 mt-0.5">
            Projected balance: <strong>{fmt(parseFloat(risk.amount))}</strong>
          </p>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Wire it into Forecast.tsx**

In `frontend/src/pages/Forecast.tsx`, add the import after line 9 (`import MonthlyAccuracyRow ...`):

```typescript
import { RiskBanner } from "../components/RiskBanner";
```

Add the query after the `dayCheckpoints` query block (after line 90's block ends — find the `useQuery<any[]>({ queryKey: ["day-checkpoints"...` block and add immediately after it):

```typescript
  const { data: risk } = useQuery({
    queryKey: ["forecast-risk", activeAccountId],
    queryFn: () => forecastApi.risk(activeAccountId),
    enabled: !!activeAccountId,
  });
```

Render it immediately before the existing chart card (insert right before line 415's `{!isLoading && chartData.length > 0 && (`):

```tsx
      {activeAccountId && <RiskBanner risk={risk} />}

```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd /Users/danford/Programming/Dev/OfflineBudget/frontend && npx tsc --noEmit`
Expected: exits 0, no errors.

- [ ] **Step 5: Manual verification**

Start the app (`./scripts/start.sh` from repo root), open `http://localhost:5173`, navigate to Forecast. Expected: no banner shown when the account isn't at risk (the common case); to verify the banner itself renders, temporarily set a checking account's `low_balance_threshold` above its current projected balance in Settings, reload, confirm the red banner appears with the correct date and amount, then revert the threshold change.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/components/RiskBanner.tsx frontend/src/pages/Forecast.tsx
git commit -m "feat: add RiskBanner to Forecast page"
```

---

## Task 4: Extract shared spending helpers (NOT_SAVINGS filter + merchant totals)

**Files:**
- Create: `backend/services/spending_helpers.py`
- Modify: `backend/routers/spending.py`
- Create: `backend/tests/test_spending_helpers.py` (merchant portion; category portion added in Task 5)

**Interfaces:**
- Produces: `NOT_SAVINGS` (SQLAlchemy filter expression), `merchant_totals(db, user_id, start, end, *, account_id=None, card_id=None, limit=50) -> list[tuple[str, Decimal, int]]` — Task 5's digest generator and this task's refactored router endpoint both consume it.

- [ ] **Step 1: Write the failing test for `merchant_totals`**

Create `backend/tests/test_spending_helpers.py`:

```python
from datetime import date
from decimal import Decimal
from backend import models
from backend.services.spending_helpers import merchant_totals


def _make_user_account(db):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db.add(user)
    db.flush()
    account = models.Account(user_id=user.id, name="Checking", type=models.AccountType.checking, current_balance=Decimal("0"))
    db.add(account)
    db.flush()
    return user, account


def test_merchant_totals_ranks_checking_transactions(db_session):
    user, account = _make_user_account(db_session)
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 1), amount=Decimal("-40.00"), description="Kroger"),
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 2), amount=Decimal("-15.00"), description="Kroger"),
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 3), amount=Decimal("-100.00"), description="Amazon"),
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 4), amount=Decimal("500.00"), description="Paycheck"),
    ])
    db_session.commit()

    result = merchant_totals(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7))

    assert result[0] == ("Amazon", Decimal("100.00"), 1)
    assert result[1] == ("Kroger", Decimal("55.00"), 2)
    assert len(result) == 2


def test_merchant_totals_respects_limit(db_session):
    user, account = _make_user_account(db_session)
    for i in range(5):
        db_session.add(models.Transaction(
            user_id=user.id, account_id=account.id, date=date(2026, 8, 1),
            amount=Decimal(f"-{i + 1}.00"), description=f"Merchant{i}",
        ))
    db_session.commit()

    result = merchant_totals(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7), limit=2)
    assert len(result) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/danford/Programming/Dev/OfflineBudget && source .venv/bin/activate && pytest backend/tests/test_spending_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.spending_helpers'`

- [ ] **Step 3: Create `spending_helpers.py`**

Create `backend/services/spending_helpers.py`:

```python
from datetime import date
from decimal import Decimal
from sqlalchemy import or_
from sqlalchemy.orm import Session
from backend import models

NOT_SAVINGS = or_(
    models.Transaction.category_id.is_(None),
    models.Category.type != models.CategoryType.savings,
)


def merchant_totals(
    db: Session,
    user_id: int,
    start: date,
    end: date,
    *,
    account_id: int | None = None,
    card_id: int | None = None,
    limit: int = 50,
) -> list[tuple[str, Decimal, int]]:
    """Returns [(name, total, count), ...] sorted by total descending.

    Combines checking-account expense transactions (keyed by description) and
    credit-card charges (keyed by merchant) — same behavior as the existing
    /spending/by-merchant endpoint.
    """
    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}

    checking_q = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount < 0,
            NOT_SAVINGS,
        )
    )
    if account_id:
        checking_q = checking_q.filter(models.Transaction.account_id == account_id)
    for t in checking_q.all():
        key = t.description or "Unknown"
        totals[key] = totals.get(key, Decimal("0")) + abs(t.amount)
        counts[key] = counts.get(key, 0) + 1

    card_q = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == user_id,
        models.CreditCardTransaction.date >= start,
        models.CreditCardTransaction.date <= end,
        models.CreditCardTransaction.amount > 0,
    )
    if card_id:
        card_q = card_q.filter(models.CreditCardTransaction.card_id == card_id)
    for t in card_q.all():
        key = t.merchant or "Unknown"
        totals[key] = totals.get(key, Decimal("0")) + t.amount
        counts[key] = counts.get(key, 0) + 1

    sorted_entries = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [(name, total, counts[name]) for name, total in sorted_entries]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_spending_helpers.py -v`
Expected: 2 passed

- [ ] **Step 5: Refactor `spending_by_merchant` to use the shared helper**

In `backend/routers/spending.py`:

Remove the local `_NOT_SAVINGS` definition (lines 14-17) and replace with an import. Change line 8-10 from:

```python
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
```

to:

```python
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
from backend.services.spending_helpers import NOT_SAVINGS, merchant_totals
```

Delete lines 14-17 (the `_NOT_SAVINGS = or_(...)` block).

Everywhere else in this file that references `_NOT_SAVINGS`, rename to `NOT_SAVINGS` (it's now imported, not locally defined). Use search-and-replace for the identifier `_NOT_SAVINGS` → `NOT_SAVINGS` across the whole file.

Replace the body of `spending_by_merchant` (the function at line 579, originally lines 588-628) with:

```python
@router.get("/by-merchant", response_model=list[schemas.MerchantSpendingEntry])
def spending_by_merchant(
    start: date = Query(...),
    end: date = Query(...),
    account_id: Optional[int] = None,
    card_id: Optional[int] = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    ranked = merchant_totals(db, user.id, start, end, account_id=account_id, card_id=card_id, limit=limit)
    return [schemas.MerchantSpendingEntry(name=name, total=total, count=count) for name, total, count in ranked]
```

- [ ] **Step 6: Verify the existing endpoint still behaves identically**

Run:
```bash
cd /Users/danford/Programming/Dev/OfflineBudget
source .venv/bin/activate
uvicorn backend.main:app --port 8000 &
sleep 2
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' -d '{"username":"danford","password":"<your password>"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/spending/by-merchant?start=2026-01-01&end=2026-12-31&limit=10"
kill %1
```
Expected: HTTP 200, a ranked list of merchants — compare against the same call before this refactor (via `git stash` if needed) to confirm identical output. Substitute your real password.

- [ ] **Step 7: Commit**

```bash
git add backend/services/spending_helpers.py backend/routers/spending.py backend/tests/test_spending_helpers.py
git commit -m "refactor: extract merchant_totals + NOT_SAVINGS into shared spending_helpers"
```

---

## Task 5: Weekly digest content generator

**Files:**
- Modify: `backend/services/spending_helpers.py`
- Modify: `backend/services/summary_generator.py`
- Modify: `backend/schemas.py`
- Modify: `backend/tests/test_spending_helpers.py`

**Interfaces:**
- Consumes: `merchant_totals()` and `NOT_SAVINGS` from Task 4; `find_balance_risk()` and `build_forecast()` from Task 1/existing code.
- Produces: `category_totals_for_range(db, user_id, start, end) -> dict[int, Decimal]` (spending_helpers.py); `generate_weekly_digest(db, user, account_id) -> WeeklyDigest` (summary_generator.py) — Task 6's endpoint and Task 7's scheduler job both call `generate_weekly_digest`.

- [ ] **Step 1: Write the failing test for `category_totals_for_range`**

Add to `backend/tests/test_spending_helpers.py`:

```python
from backend.services.spending_helpers import category_totals_for_range


def test_category_totals_for_range_groups_checking_and_card_spend(db_session):
    user, account = _make_user_account(db_session)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db_session.add(groceries)
    db_session.flush()
    db_session.add_all([
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 1), amount=Decimal("-60.00"), description="Kroger", category_id=groceries.id),
        models.Transaction(user_id=user.id, account_id=account.id, date=date(2026, 8, 15), amount=Decimal("-999.00"), description="Out of range", category_id=groceries.id),
    ])
    db_session.commit()

    totals = category_totals_for_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7))
    assert totals[groceries.id] == Decimal("60.00")


def test_category_totals_for_range_excludes_savings(db_session):
    user, account = _make_user_account(db_session)
    savings_cat = models.Category(user_id=user.id, name="Emergency Fund", type=models.CategoryType.savings)
    db_session.add(savings_cat)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date(2026, 8, 1),
        amount=Decimal("-200.00"), description="Transfer", category_id=savings_cat.id,
    ))
    db_session.commit()

    totals = category_totals_for_range(db_session, user.id, date(2026, 8, 1), date(2026, 8, 7))
    assert savings_cat.id not in totals
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_spending_helpers.py -v`
Expected: FAIL — `ImportError: cannot import name 'category_totals_for_range'`

- [ ] **Step 3: Implement `category_totals_for_range`**

Add to `backend/services/spending_helpers.py`, after `merchant_totals`:

```python
def category_totals_for_range(db: Session, user_id: int, start: date, end: date) -> dict[int, Decimal]:
    """Sum of expense spending per category_id across checking + credit-card
    transactions in [start, end]. Savings-type categories are excluded, matching
    the rest of the app's spending totals.
    """
    totals: dict[int, Decimal] = {}

    checking_q = (
        db.query(models.Transaction)
        .outerjoin(models.Category, models.Transaction.category_id == models.Category.id)
        .filter(
            models.Transaction.user_id == user_id,
            models.Transaction.is_actual == True,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
            models.Transaction.amount < 0,
            models.Transaction.category_id.isnot(None),
            NOT_SAVINGS,
        )
    )
    for t in checking_q.all():
        totals[t.category_id] = totals.get(t.category_id, Decimal("0")) + abs(t.amount)

    card_q = (
        db.query(models.CreditCardTransaction)
        .outerjoin(models.Category, models.CreditCardTransaction.category_id == models.Category.id)
        .filter(
            models.CreditCardTransaction.user_id == user_id,
            models.CreditCardTransaction.date >= start,
            models.CreditCardTransaction.date <= end,
            models.CreditCardTransaction.amount > 0,
            models.CreditCardTransaction.category_id.isnot(None),
            or_(
                models.CreditCardTransaction.category_id.is_(None),
                models.Category.type != models.CategoryType.savings,
            ),
        )
    )
    for t in card_q.all():
        totals[t.category_id] = totals.get(t.category_id, Decimal("0")) + t.amount

    return totals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_spending_helpers.py -v`
Expected: 4 passed

- [ ] **Step 5: Add the `WeeklyDigest` schema**

In `backend/schemas.py`, add after the `MerchantSpendingEntry` class (after line 816):

```python
class WeeklyDigestCategory(BaseModel):
    category_id: int
    category_name: str
    total: Decimal


class WeeklyDigest(BaseModel):
    week_start: date
    week_end: date
    total_spent: Decimal
    categories: list[WeeklyDigestCategory]
    top_merchants: list[MerchantSpendingEntry]
    risk: ForecastRisk
```

- [ ] **Step 6: Implement `generate_weekly_digest`**

In `backend/services/summary_generator.py`:

Change the existing top-of-file imports from:

```python
import calendar
from datetime import date, timedelta
from decimal import Decimal
from collections import defaultdict
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import MonthlySummary
```

to:

```python
import calendar
from datetime import date, timedelta
from decimal import Decimal
from collections import defaultdict
from sqlalchemy.orm import Session
from backend import models
from backend.schemas import MonthlySummary, WeeklyDigest, WeeklyDigestCategory, ForecastRisk, MerchantSpendingEntry
from backend.services.spending_helpers import category_totals_for_range, merchant_totals
from backend.services.forecast_engine import build_forecast, find_balance_risk
```

(Only two lines are new — the `backend.schemas` import gains four names, and two new `backend.services` imports are added. `date`/`timedelta`/`Decimal` are already imported.)

Add this function at the end of the file:

```python
def generate_weekly_digest(db: Session, user: models.User, account_id: int) -> WeeklyDigest:
    """Trailing 7 days of spending (category totals + top merchants) plus the
    forward-looking negative-balance risk for the given checking account.
    """
    today = date.today()
    week_start = today - timedelta(days=7)
    week_end = today

    cat_totals = category_totals_for_range(db, user.id, week_start, week_end)
    cat_map = {c.id: c.name for c in db.query(models.Category).filter(models.Category.user_id == user.id).all()}
    categories = sorted(
        [
            WeeklyDigestCategory(category_id=cid, category_name=cat_map.get(cid, "Unknown"), total=total)
            for cid, total in cat_totals.items()
        ],
        key=lambda c: c.total,
        reverse=True,
    )
    total_spent = sum(cat_totals.values(), Decimal("0"))

    merchants = merchant_totals(db, user.id, week_start, week_end, limit=10)
    top_merchants = [MerchantSpendingEntry(name=n, total=t, count=c) for n, t, c in merchants]

    account = db.query(models.Account).filter(
        models.Account.id == account_id, models.Account.user_id == user.id,
    ).first()
    threshold = account.low_balance_threshold if account and account.low_balance_threshold is not None else Decimal("0")
    forecast_entries = build_forecast(db, user.id, account_id, today, today + timedelta(days=90))
    risk_dict = find_balance_risk(forecast_entries, threshold)
    risk = ForecastRisk(**risk_dict)

    return WeeklyDigest(
        week_start=week_start,
        week_end=week_end,
        total_spent=total_spent,
        categories=categories,
        top_merchants=top_merchants,
        risk=risk,
    )
```

- [ ] **Step 7: Write and run a smoke test for `generate_weekly_digest`**

Add to `backend/tests/test_spending_helpers.py`:

```python
from backend.services.summary_generator import generate_weekly_digest


def test_generate_weekly_digest_smoke(db_session):
    user, account = _make_user_account(db_session)
    groceries = models.Category(user_id=user.id, name="Groceries", type=models.CategoryType.expense)
    db_session.add(groceries)
    db_session.flush()
    db_session.add(models.Transaction(
        user_id=user.id, account_id=account.id, date=date.today() - timedelta(days=1),
        amount=Decimal("-42.00"), description="Kroger", category_id=groceries.id,
    ))
    db_session.commit()

    digest = generate_weekly_digest(db_session, user, account.id)
    assert digest.total_spent == Decimal("42.00")
    assert digest.categories[0].category_name == "Groceries"
    assert digest.risk.at_risk is False
```

Add `from datetime import timedelta` to the top of `backend/tests/test_spending_helpers.py` if not already present (it is, via `date` import — add `timedelta` alongside it: `from datetime import date, timedelta`).

Run: `pytest backend/tests/test_spending_helpers.py -v`
Expected: 5 passed

- [ ] **Step 8: Commit**

```bash
git add backend/services/spending_helpers.py backend/services/summary_generator.py backend/schemas.py backend/tests/test_spending_helpers.py
git commit -m "feat: add generate_weekly_digest (category totals + top merchants + risk)"
```

---

## Task 6: Weekly digest API endpoint

**Files:**
- Modify: `backend/routers/spending.py`

**Interfaces:**
- Consumes: `generate_weekly_digest(db, user, account_id)` from Task 5.
- Produces: `GET /spending/weekly-digest?account_id=` → `schemas.WeeklyDigest` — Task 8 (frontend) calls this.

- [ ] **Step 1: Add the endpoint**

In `backend/routers/spending.py`, add the import (alongside the existing helper imports from Task 4):

```python
from backend.services.summary_generator import generate_weekly_digest
```

Add this endpoint near `spending_by_merchant` (after it):

```python
@router.get("/weekly-digest", response_model=schemas.WeeklyDigest)
def get_weekly_digest(
    account_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return generate_weekly_digest(db, user, account_id)
```

- [ ] **Step 2: Verify it responds**

Run:
```bash
cd /Users/danford/Programming/Dev/OfflineBudget
source .venv/bin/activate
uvicorn backend.main:app --port 8000 &
sleep 2
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' -d '{"username":"danford","password":"<your password>"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/spending/weekly-digest?account_id=1"
kill %1
```
Expected: HTTP 200, JSON matching `WeeklyDigest` shape (`week_start`, `week_end`, `total_spent`, `categories`, `top_merchants`, `risk`). Substitute your real password.

- [ ] **Step 3: Commit**

```bash
git add backend/routers/spending.py
git commit -m "feat: add GET /spending/weekly-digest endpoint"
```

---

## Task 7: Scheduler, settings, and email delivery

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/main.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `generate_weekly_digest(db, user, account_id)` from Task 5; `send_email(to, subject, html, text)` (existing, `backend/services/email_service.py`).
- Produces: `settings.digest_recipients_list: list[str]`, `settings.WEEKLY_DIGEST_DAY: str`, `settings.WEEKLY_DIGEST_HOUR: int` — used only within `main.py`, no other task depends on these.

- [ ] **Step 1: Add settings**

In `backend/config.py`, add after the `DAILY_SUMMARY_HOUR` line (line 19):

```python
    WEEKLY_DIGEST_DAY: str = "fri"    # APScheduler cron day_of_week value
    WEEKLY_DIGEST_HOUR: int = 7       # 24-hour local time
    DIGEST_RECIPIENTS: str = ""       # comma-separated email addresses
```

Add a property alongside `allowed_origins_list` (after line 25):

```python
    @property
    def digest_recipients_list(self) -> list[str]:
        return [e.strip() for e in self.DIGEST_RECIPIENTS.split(",") if e.strip()]
```

- [ ] **Step 2: Write the digest HTML/text builder and the scheduled job**

In `backend/main.py`, add after `_send_daily_summaries` (after line 58, before `_scheduler = BackgroundScheduler()`):

```python
def _digest_html(user: "models.User", digest) -> tuple[str, str]:
    def fmt(v) -> str:
        return f"${v:,.2f}"

    cat_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{c.category_name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(c.total)}</td></tr>"
        for c in digest.categories
    ) or "<tr><td style='color:#888'>No categorized spending this week</td></tr>"

    merchant_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{m.name}</td>"
        f"<td style='padding:4px 0;text-align:right'>{fmt(m.total)}</td></tr>"
        for m in digest.top_merchants[:10]
    ) or "<tr><td style='color:#888'>No merchant activity this week</td></tr>"

    risk_html = ""
    risk_text = ""
    if digest.risk.at_risk and digest.risk.date is not None:
        risk_html = (
            f"<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px;color:#dc2626'>Balance Risk</h3>"
            f"<p style='color:#991b1b'>Projected to drop to {fmt(digest.risk.amount)} on "
            f"{digest.risk.date.strftime('%B %-d, %Y')}.</p>"
        )
        risk_text = f"\nBALANCE RISK\n  Projected to drop to {fmt(digest.risk.amount)} on {digest.risk.date.strftime('%B %-d, %Y')}.\n"

    html = f"""<!DOCTYPE html>
<html><body style='font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1f2937'>
<h2 style='color:#4f46e5;margin-bottom:4px'>OfflineBudget Weekly Digest</h2>
<p style='color:#6b7280;margin-top:0'>{digest.week_start.strftime("%B %-d")} – {digest.week_end.strftime("%B %-d, %Y")}</p>

<p>Total spent this week: <b>{fmt(digest.total_spent)}</b></p>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Spending by Category</h3>
<table style='width:100%'>{cat_rows}</table>

<h3 style='border-bottom:1px solid #e5e7eb;padding-bottom:4px'>Top Merchants</h3>
<table style='width:100%'>{merchant_rows}</table>

{risk_html}

<p style='color:#9ca3af;font-size:12px;margin-top:24px'>Sent by OfflineBudget</p>
</body></html>"""

    cat_text = "\n".join(f"  {c.category_name}: {fmt(c.total)}" for c in digest.categories) or "  No categorized spending this week"
    merchant_text = "\n".join(f"  {m.name}: {fmt(m.total)}" for m in digest.top_merchants[:10]) or "  No merchant activity this week"

    text = f"""OfflineBudget Weekly Digest — {digest.week_start.strftime("%B %-d")} to {digest.week_end.strftime("%B %-d, %Y")}

Total spent this week: {fmt(digest.total_spent)}

SPENDING BY CATEGORY
{cat_text}

TOP MERCHANTS
{merchant_text}
{risk_text}"""
    return html, text


def _send_weekly_digest() -> None:
    from backend.database import SessionLocal
    from backend import models
    from backend.services.email_service import send_email
    from backend.services.summary_generator import generate_weekly_digest

    recipients = settings.digest_recipients_list
    if not recipients:
        return

    db = SessionLocal()
    try:
        users = db.query(models.User).filter(models.User.is_active == True).all()
        for user in users:
            account = db.query(models.Account).filter(
                models.Account.user_id == user.id,
                models.Account.type == models.AccountType.checking,
                models.Account.is_active == True,
            ).first()
            if not account:
                continue
            try:
                digest = generate_weekly_digest(db, user, account.id)
                html_body, text_body = _digest_html(user, digest)
                subject = f"Weekly Spending Digest — {digest.week_start.strftime('%b %-d')}–{digest.week_end.strftime('%b %-d, %Y')}"
                for recipient in recipients:
                    send_email(recipient, subject, html_body, text_body)
            except Exception as exc:
                logger.error("Weekly digest failed for %s: %s", user.username, exc)
    finally:
        db.close()
```

- [ ] **Step 3: Register the scheduler job**

In `backend/main.py`, change line 62 from:

```python
_scheduler.add_job(_send_daily_summaries, "cron", hour=settings.DAILY_SUMMARY_HOUR)
```

to:

```python
_scheduler.add_job(_send_daily_summaries, "cron", hour=settings.DAILY_SUMMARY_HOUR)
_scheduler.add_job(_send_weekly_digest, "cron", day_of_week=settings.WEEKLY_DIGEST_DAY, hour=settings.WEEKLY_DIGEST_HOUR)
```

- [ ] **Step 4: Document the new settings**

In `.env.example`, add after the `DAILY_SUMMARY_HOUR=7` line:

```
# Weekly Digest (optional — leave DIGEST_RECIPIENTS blank to disable)
# WEEKLY_DIGEST_DAY=fri        # APScheduler day_of_week: mon,tue,wed,thu,fri,sat,sun
# WEEKLY_DIGEST_HOUR=7         # 0-23, local server time
# DIGEST_RECIPIENTS=you@example.com,spouse@example.com
```

- [ ] **Step 5: Verify the app still starts cleanly and the job registers**

Run:
```bash
cd /Users/danford/Programming/Dev/OfflineBudget
source .venv/bin/activate
uvicorn backend.main:app --port 8000 &
sleep 2
curl -s http://localhost:8000/health
kill %1
```
Expected: `{"status":"ok","version":"2.0.0"}`, no startup errors in the terminal output (scheduler registers both jobs silently — there's no `/jobs` introspection endpoint, so a clean startup with no traceback is the signal).

- [ ] **Step 6: Manual end-to-end check of the digest content (optional, requires SMTP configured)**

If `SMTP_HOST` and `DIGEST_RECIPIENTS` are set in `.env`, call `_send_weekly_digest()` directly to confirm an email actually arrives, without waiting for Friday:

```bash
cd /Users/danford/Programming/Dev/OfflineBudget
source .venv/bin/activate
python3 -c "from backend.main import _send_weekly_digest; _send_weekly_digest()"
```

Expected: no exception; check the recipient inbox (or server logs if SMTP isn't configured — in that case this is a no-op per `send_email`'s existing silent-skip behavior).

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/main.py .env.example
git commit -m "feat: schedule weekly digest email (Friday morning, configurable)"
```

---

## Task 8: Frontend weekly digest panel on Dashboard

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/pages/Dashboard.tsx`

**Interfaces:**
- Consumes: `GET /spending/weekly-digest` from Task 6.
- Produces: nothing further downstream — this is the last task.

- [ ] **Step 1: Add the API method**

In `frontend/src/api/index.ts`, in the `analyticsApi` object (starts at line 138), add after `monthlySummary` (after line 143):

```typescript
  weeklyDigest: (accountId: number) =>
    api.get("/spending/weekly-digest", { params: { account_id: accountId } }).then((r) => r.data),
```

- [ ] **Step 2: Add the query and panel to Dashboard.tsx**

Add the import at the top of `frontend/src/pages/Dashboard.tsx` (alongside the existing `RiskBanner` usage — reuse it here too):

```typescript
import { RiskBanner } from "../components/RiskBanner";
```

Add the query after the existing `rollingRaw` query block (after line 39):

```typescript
  const primaryChecking = checkingAccounts[0];
  const { data: weeklyDigest } = useQuery<any>({
    queryKey: ["weekly-digest", primaryChecking?.id],
    queryFn: () => analyticsApi.weeklyDigest(primaryChecking.id),
    enabled: !!primaryChecking,
  });
```

(Note: `checkingAccounts` is defined at line 41 in the current file, before this query needs it — move the `checkingAccounts` derivation, currently at line 41, to immediately after the `accounts` query at line 28, so it's available here. `checkingAccounts` has no other dependency before its current use.)

Add the panel in the JSX, after the closing `)}` of the "Available to Spend widget" block (after line 120, before whatever section follows it):

```tsx
      {weeklyDigest && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-1">
            Weekly Digest — {new Date(weeklyDigest.week_start + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
            {" – "}
            {new Date(weeklyDigest.week_end + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
          </h3>
          <p className="text-sm text-gray-500 mb-3">Total spent: <span className="font-semibold text-gray-900 dark:text-gray-100">{fmt(parseFloat(weeklyDigest.total_spent))}</span></p>

          {weeklyDigest.categories.length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">By Category</p>
              <div className="space-y-1 text-sm">
                {weeklyDigest.categories.slice(0, 5).map((c: any) => (
                  <div key={c.category_id} className="flex justify-between text-gray-600 dark:text-gray-400">
                    <span>{c.category_name}</span>
                    <span className="tabular-nums">{fmt(parseFloat(c.total))}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {weeklyDigest.top_merchants.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Top Merchants</p>
              <div className="space-y-1 text-sm">
                {weeklyDigest.top_merchants.slice(0, 5).map((m: any) => (
                  <div key={m.name} className="flex justify-between text-gray-600 dark:text-gray-400">
                    <span>{m.name}</span>
                    <span className="tabular-nums">{fmt(parseFloat(m.total))}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {weeklyDigest?.risk && <RiskBanner risk={weeklyDigest.risk} />}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /Users/danford/Programming/Dev/OfflineBudget/frontend && npx tsc --noEmit`
Expected: exits 0, no errors.

- [ ] **Step 4: Manual verification**

Start the app, open `http://localhost:5173`, navigate to Dashboard. Expected: a "Weekly Digest" card showing total spent, up to 5 categories, up to 5 merchants for the trailing 7 days. If the account is at risk within the next 90 days, the same red `RiskBanner` from Task 3 also appears here.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/pages/Dashboard.tsx
git commit -m "feat: add weekly digest panel to Dashboard"
```

---

## Self-Review Notes

**Spec coverage:** Every spec requirement maps to a task — risk callout (Tasks 1-3), weekly category/merchant reporting (Tasks 4-6, 8), Friday email delivery (Task 7), in-app fallback (Task 8), narrow test coverage for the two new pure-logic pieces (Tasks 1, 4, 5), error handling via existing `send_email` no-op pattern and empty-week handling (Task 7's `_digest_html` renders "No … this week" rather than erroring).

**Type consistency:** `find_balance_risk()` (Task 1) returns a `dict` matching `ForecastRisk`'s fields exactly (`at_risk`, `date`, `amount`, `threshold`) — verified the dict is passed as `ForecastRisk(**risk_dict)` in Task 5 and returned directly as the Task 2 endpoint's `response_model=schemas.ForecastRisk` (FastAPI coerces the dict). `merchant_totals()` returns `list[tuple[str, Decimal, int]]` consistently used by both Task 4's refactored endpoint and Task 5's digest generator.

**Scope check:** Single cohesive plan, not decomposed further — Feature B (Tasks 4-8) depends on Feature A's `find_balance_risk` (Task 1), so this was correctly kept as one plan per the brainstorming skill's scope check, not split into independent sub-projects.
