# Parallel Ops Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Dan flag a specific number on Forecast, Transactions, or Household Snapshot as wrong, right where he sees it, with what he expected instead — captured in a queue for later review and fixing.

**Architecture:** A new `verification_flags` table + CRUD router on the backend. A localStorage-backed "Parallel Ops" toggle on the frontend gates a reusable `VerificationFlagButton` component dropped onto the three target surfaces (Dashboard's Household Snapshot card, Forecast's risk banner, Transactions' row tables). A new Settings tab lists and resolves flags.

**Tech Stack:** FastAPI + SQLAlchemy (raw `ALTER`/`CREATE TABLE IF NOT EXISTS` migrations, no Alembic) on the backend; React + TypeScript + `@tanstack/react-query` + axios on the frontend, matching every existing router/page in this codebase.

## Global Constraints

- Backend routers use the shared `backend.dependencies.get_db` / `get_current_user` (NOT the older per-router local `get_db` pattern still present in `day_checkpoints.py` — do not copy that file).
- `get_current_user` resolves to the *data owner* (follows `linked_to_user_id`), so a linked household member's flags land on the same owner's queue automatically — no extra code needed for that.
- All new SQLite schema changes go in `backend/database.py`'s `upgrade_schema()` `stmts` list as `CREATE TABLE IF NOT EXISTS`, appended at the end of the existing list. Never edit or reorder existing entries.
- Money fields are `Decimal` / `Numeric(14, 2)` throughout, matching every other table.
- Frontend localStorage settings (dark mode, pinned nav) follow the pattern in `frontend/src/store/theme.ts`: a tiny module with `get`/`set` functions, no framework state. The Parallel Ops toggle follows the same pattern.
- Frontend API calls live in `frontend/src/api/index.ts` as one `xApi` object per feature, calling `api.get/post/patch/delete` and returning `r.data` — never call axios directly from a page component.
- Tailwind utility classes `card`, `input`, `btn-primary`, `btn-secondary` are global (defined once, used everywhere) — reuse them, don't invent new ad hoc styles.
- Every new/modified `.tsx` file must keep `cd frontend && npx tsc -b` from introducing new errors (check the current baseline count before and after each task).

---

## File Structure

- `backend/models.py` — add `VerificationFeature`, `VerificationFlagStatus` enums and `VerificationFlag` model (Task 1).
- `backend/database.py` — add the `verification_flags` table creation statement (Task 1).
- `backend/schemas.py` — add `VerificationFlagCreate`, `VerificationFlagOut`, `VerificationFlagResolve` (Task 1).
- `backend/routers/verification_flags.py` — new CRUD router (Task 2).
- `backend/main.py` — register the new router (Task 2).
- `backend/tests/test_verification_flags_model.py` — model round-trip test (Task 1).
- `backend/tests/test_verification_flags_router.py` — router tests (Task 2).
- `frontend/src/store/parallelOps.ts` — localStorage toggle + `useParallelOpsEnabled()` hook (Task 3).
- `frontend/src/api/index.ts` — add `verificationFlagsApi` (Task 3).
- `frontend/src/components/VerificationFlagButton.tsx` — new reusable flag-icon-and-form component (Task 3).
- `frontend/src/pages/settings/PreferencesTab.tsx` — add the Parallel Ops toggle (Task 3).
- `frontend/src/pages/Dashboard.tsx` — flag button on the Household Snapshot card (Task 4).
- `frontend/src/components/RiskBanner.tsx`, `frontend/src/pages/Forecast.tsx` — flag button on the balance-risk alert (Task 5).
- `frontend/src/pages/Transactions.tsx` — flag button per transaction row, checking and card tables (Task 6).
- `frontend/src/pages/settings/VerificationFeedbackTab.tsx` — new review tab (Task 7).
- `frontend/src/pages/Settings.tsx` — wire in the new tab (Task 7).

---

### Task 1: Backend data model, schema, and migration

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/database.py`
- Modify: `backend/schemas.py`
- Test: `backend/tests/test_verification_flags_model.py`

**Interfaces:**
- Produces: `models.VerificationFeature` (str enum: `forecast`, `transactions`, `household_snapshot`), `models.VerificationFlagStatus` (str enum: `open`, `resolved`), `models.VerificationFlag` (columns: `id`, `user_id`, `feature`, `reference_type: str | None`, `reference_id: int | None`, `observed_json: str`, `expected_value: Decimal | None`, `note: str | None`, `status`, `created_at`, `resolved_at: datetime | None`).
- Produces: `schemas.VerificationFlagCreate` (`feature`, `reference_type: Optional[str]`, `reference_id: Optional[int]`, `observed: dict`, `expected_value: Optional[Decimal]`, `note: Optional[str]`), `schemas.VerificationFlagOut` (all model fields, `observed_json` returned as the raw JSON string — NOT parsed into `observed`), `schemas.VerificationFlagResolve` (`status: VerificationFlagStatus`).

- [ ] **Step 1: Add the enums and model to `backend/models.py`**

Add near the other small enums at the top of the file (after `RecurringFrequency`, matching the existing grouping of short enums):

```python
class VerificationFeature(str, PyEnum):
    forecast = "forecast"
    transactions = "transactions"
    household_snapshot = "household_snapshot"


class VerificationFlagStatus(str, PyEnum):
    open = "open"
    resolved = "resolved"
```

Add the model at the end of the file (after the last class, following the `# ── Section ──` comment-header convention already used throughout this file):

```python
# ── Verification Flags ────────────────────────────────────────────────────────

class VerificationFlag(Base):
    __tablename__ = "verification_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    feature: Mapped[VerificationFeature] = mapped_column(Enum(VerificationFeature), nullable=False)
    # What `reference_id` points at, e.g. "account", "transaction",
    # "card_transaction" -- loose by design, each feature picks its own.
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_id: Mapped[int | None] = mapped_column(Integer)
    # JSON snapshot of exactly what the app displayed at flag time (values,
    # not just ids, so the entry stays meaningful after the underlying data
    # changes). Stored as TEXT and (de)serialized at the API layer -- this
    # codebase has no precedent for a native JSON column type.
    observed_json: Mapped[str] = mapped_column(Text, nullable=False)
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[VerificationFlagStatus] = mapped_column(
        Enum(VerificationFlagStatus), default=VerificationFlagStatus.open, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User"] = relationship()
```

- [ ] **Step 2: Add the table creation statement to `backend/database.py`**

Append to the end of the `stmts` list in `upgrade_schema()` (after the `planned_transfers` `CREATE TABLE`, keeping every earlier entry untouched):

```python
        """CREATE TABLE IF NOT EXISTS verification_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            feature VARCHAR(20) NOT NULL,
            reference_type VARCHAR(32),
            reference_id INTEGER,
            observed_json TEXT NOT NULL,
            expected_value NUMERIC(14,2),
            note TEXT,
            status VARCHAR(10) NOT NULL DEFAULT 'open',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME
        )""",
```

- [ ] **Step 3: Add the schemas to `backend/schemas.py`**

Add `VerificationFeature` and `VerificationFlagStatus` to the existing `from backend.models import (...)` line at the top of the file (it already imports several enums the same way — add these two to that same import list, don't add a second import line).

Append near the end of the file, before the final section if one exists, otherwise at the end:

```python
# ── Verification Flags ────────────────────────────────────────────────────────

class VerificationFlagCreate(BaseModel):
    feature: VerificationFeature
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    observed: dict
    expected_value: Optional[Decimal] = None
    note: Optional[str] = None


class VerificationFlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    feature: VerificationFeature
    reference_type: Optional[str]
    reference_id: Optional[int]
    observed_json: str
    expected_value: Optional[Decimal]
    note: Optional[str]
    status: VerificationFlagStatus
    created_at: datetime
    resolved_at: Optional[datetime]


class VerificationFlagResolve(BaseModel):
    status: VerificationFlagStatus
```

- [ ] **Step 4: Write the model round-trip test**

Create `backend/tests/test_verification_flags_model.py`:

```python
import json
from decimal import Decimal
from backend import models


def test_verification_flag_round_trips_observed_json(db_session):
    user = models.User(username="t", hashed_password="x", display_name="T")
    db_session.add(user)
    db_session.flush()

    flag = models.VerificationFlag(
        user_id=user.id,
        feature=models.VerificationFeature.household_snapshot,
        reference_type="account",
        reference_id=3,
        observed_json=json.dumps({"left_to_spend": "945.85", "flagged_field": "left_to_spend"}),
        expected_value=Decimal("945.85"),
        note="Spreadsheet says this",
    )
    db_session.add(flag)
    db_session.commit()
    db_session.refresh(flag)

    assert flag.status == models.VerificationFlagStatus.open
    assert flag.resolved_at is None
    assert json.loads(flag.observed_json) == {"left_to_spend": "945.85", "flagged_field": "left_to_spend"}
```

- [ ] **Step 5: Run the test**

Run: `source .venv/bin/activate && python -m pytest backend/tests/test_verification_flags_model.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/database.py backend/schemas.py backend/tests/test_verification_flags_model.py
git commit -m "Add VerificationFlag model, schema, and migration"
```

---

### Task 2: Backend router

**Files:**
- Create: `backend/routers/verification_flags.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_verification_flags_router.py`

**Interfaces:**
- Consumes: `models.VerificationFlag`, `models.VerificationFeature`, `models.VerificationFlagStatus`, `schemas.VerificationFlagCreate`, `schemas.VerificationFlagOut`, `schemas.VerificationFlagResolve` (Task 1). `backend.dependencies.get_db`, `backend.dependencies.get_current_user`.
- Produces: `GET /verification-flags` (query params `feature`, `status`, both optional), `POST /verification-flags`, `PATCH /verification-flags/{flag_id}` — all mounted at prefix `/verification-flags`.

- [ ] **Step 1: Write the router**

Create `backend/routers/verification_flags.py`:

```python
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend import models, schemas
from backend.dependencies import get_db, get_current_user

router = APIRouter(prefix="/verification-flags", tags=["verification-flags"])


def _get_owned(db: Session, user: models.User, flag_id: int) -> models.VerificationFlag:
    flag = db.query(models.VerificationFlag).filter(
        models.VerificationFlag.id == flag_id,
        models.VerificationFlag.user_id == user.id,
    ).first()
    if not flag:
        raise HTTPException(status_code=404, detail="Verification flag not found")
    return flag


@router.get("", response_model=list[schemas.VerificationFlagOut])
def list_verification_flags(
    feature: models.VerificationFeature | None = None,
    status: models.VerificationFlagStatus | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = db.query(models.VerificationFlag).filter(models.VerificationFlag.user_id == user.id)
    if feature is not None:
        query = query.filter(models.VerificationFlag.feature == feature)
    if status is not None:
        query = query.filter(models.VerificationFlag.status == status)
    return query.order_by(models.VerificationFlag.created_at.desc()).all()


@router.post("", response_model=schemas.VerificationFlagOut, status_code=status.HTTP_201_CREATED)
def create_verification_flag(
    body: schemas.VerificationFlagCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    flag = models.VerificationFlag(
        user_id=user.id,
        feature=body.feature,
        reference_type=body.reference_type,
        reference_id=body.reference_id,
        observed_json=json.dumps(body.observed),
        expected_value=body.expected_value,
        note=body.note,
    )
    db.add(flag)
    db.commit()
    db.refresh(flag)
    return flag


@router.patch("/{flag_id}", response_model=schemas.VerificationFlagOut)
def update_verification_flag_status(
    flag_id: int,
    body: schemas.VerificationFlagResolve,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    flag = _get_owned(db, user, flag_id)
    flag.status = body.status
    flag.resolved_at = datetime.utcnow() if body.status == models.VerificationFlagStatus.resolved else None
    db.commit()
    db.refresh(flag)
    return flag
```

- [ ] **Step 2: Register the router in `backend/main.py`**

Add the import alongside the other `from backend.routers import x as x_router_module` lines:

```python
from backend.routers import verification_flags as verification_flags_router_module
```

Add the include alongside the other `app.include_router(...)` calls:

```python
app.include_router(verification_flags_router_module.router)
```

- [ ] **Step 3: Write the router tests**

Create `backend/tests/test_verification_flags_router.py`:

```python
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import verification_flags as verification_flags_router_module
from backend.dependencies import get_db, get_current_user


@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    app = FastAPI()
    app.include_router(verification_flags_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user


def test_create_and_list_a_flag(client):
    test_client, user = client
    resp = test_client.post("/verification-flags", json={
        "feature": "household_snapshot",
        "reference_type": "account",
        "reference_id": 3,
        "observed": {"left_to_spend": "-6999.59", "flagged_field": "left_to_spend"},
        "expected_value": 945.85,
        "note": "Spreadsheet says $945.85",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["feature"] == "household_snapshot"
    assert body["status"] == "open"
    assert Decimal(str(body["expected_value"])) == Decimal("945.85")

    resp = test_client.get("/verification-flags")
    listed = resp.json()
    assert len(listed) == 1
    assert listed[0]["note"] == "Spreadsheet says $945.85"


def test_list_filters_by_feature_and_status(client):
    test_client, user = client
    test_client.post("/verification-flags", json={"feature": "forecast", "observed": {"a": 1}})
    test_client.post("/verification-flags", json={"feature": "transactions", "observed": {"b": 2}})

    resp = test_client.get("/verification-flags", params={"feature": "forecast"})
    assert [f["feature"] for f in resp.json()] == ["forecast"]


def test_resolve_sets_status_and_resolved_at(client):
    test_client, user = client
    created = test_client.post("/verification-flags", json={"feature": "transactions", "observed": {"amount": "5.00"}}).json()

    resp = test_client.patch(f"/verification-flags/{created['id']}", json={"status": "resolved"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    assert resp.json()["resolved_at"] is not None

    resp = test_client.get("/verification-flags", params={"status": "open"})
    assert resp.json() == []


def test_a_user_cannot_see_or_resolve_another_users_flag(client, db_session):
    test_client, user = client
    other = models.User(username="other", hashed_password="x", display_name="Other")
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    other_flag = models.VerificationFlag(
        user_id=other.id, feature=models.VerificationFeature.forecast,
        observed_json="{}",
    )
    db_session.add(other_flag)
    db_session.commit()
    db_session.refresh(other_flag)

    resp = test_client.get("/verification-flags")
    assert resp.json() == []

    resp = test_client.patch(f"/verification-flags/{other_flag.id}", json={"status": "resolved"})
    assert resp.status_code == 404
```

- [ ] **Step 4: Run the tests**

Run: `source .venv/bin/activate && python -m pytest backend/tests/test_verification_flags_router.py backend/tests/test_verification_flags_model.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run the full backend suite to confirm nothing else broke**

Run: `source .venv/bin/activate && python -m pytest backend/tests -q`
Expected: all passing, count is the prior total + 5.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/verification_flags.py backend/main.py backend/tests/test_verification_flags_router.py
git commit -m "Add verification-flags CRUD router"
```

---

### Task 3: Frontend foundation — toggle, API client, shared flag button

**Files:**
- Create: `frontend/src/store/parallelOps.ts`
- Modify: `frontend/src/api/index.ts`
- Create: `frontend/src/components/VerificationFlagButton.tsx`
- Modify: `frontend/src/pages/settings/PreferencesTab.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks except the HTTP contract from Task 2 (`POST /verification-flags` body shape).
- Produces: `isParallelOpsEnabled(): boolean`, `setParallelOpsEnabled(enabled: boolean): void`, `useParallelOpsEnabled(): boolean` (all from `store/parallelOps.ts`). `verificationFlagsApi.{list, create, resolve}` (from `api/index.ts`). `<VerificationFlagButton feature reference_type? reference_id? observed expectedFields className? />` (from `components/VerificationFlagButton.tsx`) — Tasks 4, 5, 6, 7 consume all of these.

- [ ] **Step 1: Write the localStorage store and hook**

Create `frontend/src/store/parallelOps.ts`:

```ts
import { useEffect, useState } from "react";

const KEY = "parallelOpsEnabled";

export function isParallelOpsEnabled(): boolean {
  return localStorage.getItem(KEY) === "1";
}

export function setParallelOpsEnabled(enabled: boolean): void {
  localStorage.setItem(KEY, enabled ? "1" : "0");
  window.dispatchEvent(new Event("parallel-ops-changed"));
}

export function useParallelOpsEnabled(): boolean {
  const [enabled, setEnabled] = useState(isParallelOpsEnabled());
  useEffect(() => {
    const handler = () => setEnabled(isParallelOpsEnabled());
    window.addEventListener("parallel-ops-changed", handler);
    return () => window.removeEventListener("parallel-ops-changed", handler);
  }, []);
  return enabled;
}
```

- [ ] **Step 2: Add the API client**

Append to `frontend/src/api/index.ts` (matching the `// ── Section ──` header convention already used for every other group in that file):

```ts
// ── Verification Flags ──────────────────────────────────────────────────────
export const verificationFlagsApi = {
  list: (params?: { feature?: string; status?: string }) =>
    api.get("/verification-flags", { params }).then((r) => r.data),
  create: (data: {
    feature: string;
    reference_type?: string;
    reference_id?: number;
    observed: object;
    expected_value?: number;
    note?: string;
  }) => api.post("/verification-flags", data).then((r) => r.data),
  resolve: (id: number, newStatus: "open" | "resolved") =>
    api.patch(`/verification-flags/${id}`, { status: newStatus }).then((r) => r.data),
};
```

- [ ] **Step 3: Write the shared flag button component**

Create `frontend/src/components/VerificationFlagButton.tsx`:

```tsx
import { useState } from "react";
import { Flag } from "lucide-react";
import { verificationFlagsApi } from "../api";
import { useParallelOpsEnabled } from "../store/parallelOps";

interface ExpectedField {
  key: string;
  label: string;
}

export function VerificationFlagButton({
  feature,
  referenceType,
  referenceId,
  observed,
  expectedFields,
  className = "",
}: {
  feature: "forecast" | "transactions" | "household_snapshot";
  referenceType?: string;
  referenceId?: number;
  observed: Record<string, unknown>;
  expectedFields: ExpectedField[];
  className?: string;
}) {
  const enabled = useParallelOpsEnabled();
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  if (!enabled) return null;

  async function submit() {
    const filled = expectedFields.filter((f) => values[f.key]?.trim());
    if (filled.length === 0 && !note.trim()) return;
    setSubmitting(true);
    try {
      const submissions = filled.length > 0 ? filled : [null];
      for (const field of submissions) {
        await verificationFlagsApi.create({
          feature,
          reference_type: referenceType,
          reference_id: referenceId,
          observed: field ? { ...observed, flagged_field: field.key } : observed,
          expected_value: field ? parseFloat(values[field.key]) : undefined,
          note: note.trim() || undefined,
        });
      }
      setDone(true);
      setValues({});
      setNote("");
      setTimeout(() => {
        setDone(false);
        setOpen(false);
      }, 1500);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={`relative inline-block ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title="Flag this as wrong"
        className="text-gray-300 hover:text-red-500 dark:text-gray-600 dark:hover:text-red-400"
      >
        <Flag size={14} />
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-64 card p-3 shadow-lg text-left">
          {done ? (
            <p className="text-sm text-emerald-600 dark:text-emerald-400">Flagged — thanks, I'll look into it.</p>
          ) : (
            <>
              <p className="text-xs font-medium text-gray-700 dark:text-gray-300 mb-2">What should this be?</p>
              {expectedFields.map((f) => (
                <label key={f.key} className="block mb-2 text-xs text-gray-500 dark:text-gray-400">
                  {f.label}
                  <input
                    type="number"
                    step="0.01"
                    className="input w-full text-sm mt-0.5"
                    value={values[f.key] ?? ""}
                    onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  />
                </label>
              ))}
              <label className="block mb-2 text-xs text-gray-500 dark:text-gray-400">
                Note
                <textarea
                  className="input w-full text-sm mt-0.5"
                  rows={2}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setOpen(false)} className="btn-secondary text-xs px-2 py-1">
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={submit}
                  disabled={submitting}
                  className="btn-primary text-xs px-2 py-1 disabled:opacity-50"
                >
                  {submitting ? "Saving…" : "Flag it"}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
```

Each entry in `expectedFields` with a value filled in submits its own flag row (`expected_value` set to that field's number, `observed` tagged with `flagged_field`); if none are filled but a note was written, one flag row goes out with `expected_value` unset. This keeps the backend's `expected_value` column a single `Decimal` (Task 1) while still letting a form like Household Snapshot's ask about two numbers in one interaction.

- [ ] **Step 4: Add the Parallel Ops toggle to Preferences**

In `frontend/src/pages/settings/PreferencesTab.tsx`, add to the existing lucide-react import line (currently `import { Moon, Sun, Wand2 } from "lucide-react";`):

```tsx
import { Moon, Sun, Wand2, Flag } from "lucide-react";
```

Add this import alongside the other local imports:

```tsx
import { isParallelOpsEnabled, setParallelOpsEnabled } from "../../store/parallelOps";
```

Add state next to the existing `dark` state (right after the `const [dark, setDark] = useState(...)` / `toggleDark` pair):

```tsx
const [parallelOps, setParallelOpsState] = useState(isParallelOpsEnabled());
function toggleParallelOps() {
  const next = !parallelOps;
  setParallelOpsState(next);
  setParallelOpsEnabled(next);
}
```

Add a new toggle row immediately after the existing Dark Mode `<div className="flex items-center justify-between py-2">...</div>` block and before the Setup Wizard block:

```tsx
<div className="flex items-center justify-between py-2 border-t border-gray-100 dark:border-gray-700">
  <div className="flex items-center gap-3">
    <Flag size={16} className="text-red-400" />
    <div>
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Parallel Ops</span>
      <p className="text-xs text-gray-400">Show a flag icon on Forecast, Transactions, and Household Snapshot to report numbers that look wrong</p>
    </div>
  </div>
  <button
    onClick={toggleParallelOps}
    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${parallelOps ? "bg-indigo-600" : "bg-gray-200"}`}
  >
    <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${parallelOps ? "translate-x-6" : "translate-x-1"}`} />
  </button>
</div>
```

- [ ] **Step 5: Type-check**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: same count as the pre-task baseline (check with `git stash` beforehand if unsure — no new errors from these 4 files).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/store/parallelOps.ts frontend/src/api/index.ts frontend/src/components/VerificationFlagButton.tsx frontend/src/pages/settings/PreferencesTab.tsx
git commit -m "Add Parallel Ops toggle and reusable VerificationFlagButton"
```

---

### Task 4: Household Snapshot flag (Dashboard)

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

**Interfaces:**
- Consumes: `<VerificationFlagButton>` (Task 3), the existing `snapshot` and `primaryChecking` variables already in scope in `Dashboard.tsx` (from its existing `useQuery` calls — do not add new queries).

- [ ] **Step 1: Import the component**

Add to `Dashboard.tsx`'s imports:

```tsx
import { VerificationFlagButton } from "../components/VerificationFlagButton";
```

- [ ] **Step 2: Add the button to the Household Snapshot card header**

Find this block (the Household Snapshot card's header row):

```tsx
<div className="flex items-center gap-2 mb-3">
  <Wallet size={16} className="text-emerald-600" />
  <h3 className="font-semibold text-gray-900 dark:text-white">Household Snapshot</h3>
</div>
```

Replace it with:

```tsx
<div className="flex items-center gap-2 mb-3">
  <Wallet size={16} className="text-emerald-600" />
  <h3 className="font-semibold text-gray-900 dark:text-white">Household Snapshot</h3>
  <VerificationFlagButton
    feature="household_snapshot"
    referenceType="account"
    referenceId={primaryChecking?.id}
    observed={{
      left_to_spend: snapshot.left_to_spend,
      left_to_spend_weekly: snapshot.left_to_spend_weekly,
      not_saving: snapshot.not_saving,
      not_saving_weekly: snapshot.not_saving_weekly,
    }}
    expectedFields={[
      { key: "left_to_spend", label: "Left to Spend (monthly)" },
      { key: "not_saving", label: "Not Saving (monthly)" },
    ]}
    className="ml-auto"
  />
</div>
```

(This block sits inside `{snapshot && (...)}`, so `snapshot` is guaranteed non-null at this point — no extra null check needed.)

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: same as Task 3's ending count.

- [ ] **Step 4: Manual smoke check**

Since Interceptor isn't set up yet in this environment, verify by reading the rendered diff carefully: confirm `primaryChecking` and `snapshot` are indeed the exact variable names already in scope at this point in the file (do not guess — grep the file first if unsure) before considering this step done.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "Add verification flag button to Household Snapshot card"
```

---

### Task 5: Forecast flag (RiskBanner)

**Files:**
- Modify: `frontend/src/components/RiskBanner.tsx`
- Modify: `frontend/src/pages/Forecast.tsx`

**Interfaces:**
- Consumes: `<VerificationFlagButton>` (Task 3).
- Produces: `RiskBanner` gains a new optional `accountId?: number` prop — Forecast.tsx must pass it.

- [ ] **Step 1: Import the component in RiskBanner.tsx**

Add to `RiskBanner.tsx`'s imports:

```tsx
import { VerificationFlagButton } from "./VerificationFlagButton";
```

- [ ] **Step 2: Add the `accountId` prop**

Change the component signature:

```tsx
export function RiskBanner({
  risk,
  accountId,
  sourceAccounts = [],
  onAcceptSuggestion,
}: {
  risk: Risk | undefined;
  accountId?: number;
  sourceAccounts?: SourceAccount[];
  onAcceptSuggestion?: (amount: string, date: string, fromAccountId: number) => void;
}) {
```

- [ ] **Step 3: Add the flag button to the risk alert block**

Find this block:

```tsx
      {showAlert && (
        <div className="card border-red-200 dark:border-red-700 bg-red-50/60 dark:bg-red-900/20">
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} className="text-red-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-red-900 dark:text-red-200 text-sm">
                {parseFloat(risk.threshold) > 0
                  ? `Projected to drop below ${fmt(parseFloat(risk.threshold))} on ${formatDate(risk.date!)}`
                  : `Projected to go negative on ${formatDate(risk.date!)}`}
              </p>
              <p className="text-xs text-red-700 dark:text-red-400 mt-0.5">
                Projected balance: <strong>{fmt(parseFloat(risk.amount!))}</strong>
              </p>
            </div>
          </div>
        </div>
      )}
```

Replace it with:

```tsx
      {showAlert && (
        <div className="card border-red-200 dark:border-red-700 bg-red-50/60 dark:bg-red-900/20">
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} className="text-red-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-2">
                <p className="font-semibold text-red-900 dark:text-red-200 text-sm">
                  {parseFloat(risk.threshold) > 0
                    ? `Projected to drop below ${fmt(parseFloat(risk.threshold))} on ${formatDate(risk.date!)}`
                    : `Projected to go negative on ${formatDate(risk.date!)}`}
                </p>
                <VerificationFlagButton
                  feature="forecast"
                  referenceType="account"
                  referenceId={accountId}
                  observed={{ projected_balance: risk.amount, risk_date: risk.date, threshold: risk.threshold }}
                  expectedFields={[{ key: "projected_balance", label: "Projected Balance" }]}
                />
              </div>
              <p className="text-xs text-red-700 dark:text-red-400 mt-0.5">
                Projected balance: <strong>{fmt(parseFloat(risk.amount!))}</strong>
              </p>
            </div>
          </div>
        </div>
      )}
```

- [ ] **Step 4: Pass `accountId` from Forecast.tsx**

Find:

```tsx
      {activeAccountId && (
        <RiskBanner
          risk={risk}
          sourceAccounts={accounts.filter((a: any) => a.id !== activeAccountId).map((a: any) => ({ id: a.id, name: a.name }))}
          onAcceptSuggestion={(amount, targetDate, fromAccountId) =>
            acceptSuggestionMut.mutate({ to_account_id: activeAccountId, from_account_id: fromAccountId, amount, target_date: targetDate, suggested: true })
          }
        />
```

Add `accountId={activeAccountId}`:

```tsx
      {activeAccountId && (
        <RiskBanner
          risk={risk}
          accountId={activeAccountId}
          sourceAccounts={accounts.filter((a: any) => a.id !== activeAccountId).map((a: any) => ({ id: a.id, name: a.name }))}
          onAcceptSuggestion={(amount, targetDate, fromAccountId) =>
            acceptSuggestionMut.mutate({ to_account_id: activeAccountId, from_account_id: fromAccountId, amount, target_date: targetDate, suggested: true })
          }
        />
```

- [ ] **Step 5: Type-check**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: same as Task 4's ending count.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/RiskBanner.tsx frontend/src/pages/Forecast.tsx
git commit -m "Add verification flag button to the Forecast balance-risk alert"
```

---

### Task 6: Transactions flag (per row)

**Files:**
- Modify: `frontend/src/pages/Transactions.tsx`

**Interfaces:**
- Consumes: `<VerificationFlagButton>` (Task 3).

- [ ] **Step 1: Import the component**

Add to `Transactions.tsx`'s imports:

```tsx
import { VerificationFlagButton } from "../components/VerificationFlagButton";
```

- [ ] **Step 2: Add the flag button to the checking-transactions row**

Find this block (the trailing cell in the checking transactions table, next to the delete button):

```tsx
                      <td className="px-4 py-3">
                        <button onClick={() => setDeleteId(t.id)} className="text-gray-300 hover:text-red-500"><Trash2 size={14} /></button>
                      </td>
```

Replace it with:

```tsx
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <VerificationFlagButton
                            feature="transactions"
                            referenceType="transaction"
                            referenceId={t.id}
                            observed={{ date: t.date, amount: t.amount, description: t.description, category_id: t.category_id }}
                            expectedFields={[{ key: "amount", label: "Amount" }]}
                          />
                          <button onClick={() => setDeleteId(t.id)} className="text-gray-300 hover:text-red-500"><Trash2 size={14} /></button>
                        </div>
                      </td>
```

- [ ] **Step 3: Add a trailing column to the card-transactions table header**

Find the card table's header row:

```tsx
                <thead className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-700">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Merchant</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Category</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                  </tr>
                </thead>
```

Add a trailing empty header cell, matching the checking table's `<th className="px-4 py-3 w-10"></th>`:

```tsx
                <thead className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-700">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Merchant</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Category</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                    <th className="px-4 py-3 w-10"></th>
                  </tr>
                </thead>
```

- [ ] **Step 4: Add the flag button to the card-transactions row**

Find the card row's amount cell (the last cell in that row today):

```tsx
                      <td className="px-4 py-3 text-right font-semibold tabular-nums text-red-600">
                        {fmt(t.amount)}
                      </td>
```

Add a new trailing cell immediately after it (inside the same `<tr>...</tr>`):

```tsx
                      <td className="px-4 py-3 text-right font-semibold tabular-nums text-red-600">
                        {fmt(t.amount)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <VerificationFlagButton
                          feature="transactions"
                          referenceType="card_transaction"
                          referenceId={t.id}
                          observed={{ date: t.date, amount: t.amount, merchant: t.merchant, category_id: t.category_id }}
                          expectedFields={[{ key: "amount", label: "Amount" }]}
                        />
                      </td>
```

- [ ] **Step 5: Type-check**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: same as Task 5's ending count.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Transactions.tsx
git commit -m "Add verification flag button to Transactions rows (checking and card)"
```

---

### Task 7: Verification Feedback review tab

**Files:**
- Create: `frontend/src/pages/settings/VerificationFeedbackTab.tsx`
- Modify: `frontend/src/pages/Settings.tsx`

**Interfaces:**
- Consumes: `verificationFlagsApi` (Task 3).

- [ ] **Step 1: Write the review tab**

Create `frontend/src/pages/settings/VerificationFeedbackTab.tsx`:

```tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { verificationFlagsApi } from "../../api";
import { CheckCircle2, Circle } from "lucide-react";

const FEATURE_LABELS: Record<string, string> = {
  forecast: "Forecast",
  transactions: "Transactions",
  household_snapshot: "Household Snapshot",
};

export default function VerificationFeedbackTab() {
  const qc = useQueryClient();
  const [showResolved, setShowResolved] = useState(false);
  const { data: flags = [] } = useQuery({
    queryKey: ["verification-flags", showResolved],
    queryFn: () => verificationFlagsApi.list(showResolved ? {} : { status: "open" }),
  });
  const resolveMut = useMutation({
    mutationFn: ({ id, newStatus }: { id: number; newStatus: "open" | "resolved" }) =>
      verificationFlagsApi.resolve(id, newStatus),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["verification-flags"] }),
  });

  // Grouped by feature (Forecast / Transactions / Household Snapshot) rather
  // than one flat chronological list -- each feature is its own review
  // queue, and grouping keeps a burst of transaction flags from burying a
  // single forecast flag underneath them.
  const groups: Record<string, any[]> = { forecast: [], transactions: [], household_snapshot: [] };
  for (const flag of flags) {
    (groups[flag.feature] ??= []).push(flag);
  }

  function renderFlag(flag: any) {
    let observed: Record<string, unknown> = {};
    try {
      observed = JSON.parse(flag.observed_json);
    } catch {
      // malformed row -- fall through, the raw fields below still render
    }
    return (
      <div key={flag.id} className="p-3 rounded-lg border border-gray-100 dark:border-gray-700">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs text-gray-400">{new Date(flag.created_at).toLocaleString()}</p>
            {flag.expected_value != null && (
              <p className="text-sm text-gray-700 dark:text-gray-300 mt-1">
                Expected: <strong>{flag.expected_value}</strong>
              </p>
            )}
            {flag.note && <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{flag.note}</p>}
            <pre className="text-[10px] text-gray-400 dark:text-gray-500 mt-1 whitespace-pre-wrap break-words">
              {JSON.stringify(observed)}
            </pre>
          </div>
          <button
            onClick={() => resolveMut.mutate({ id: flag.id, newStatus: flag.status === "open" ? "resolved" : "open" })}
            className="shrink-0 text-gray-300 hover:text-emerald-500"
            title={flag.status === "open" ? "Mark resolved" : "Reopen"}
          >
            {flag.status === "open" ? <Circle size={16} /> : <CheckCircle2 size={16} className="text-emerald-500" />}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Verification Feedback</h3>
          <p className="text-xs text-gray-400">Numbers flagged as wrong while Parallel Ops was on</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          <input
            type="checkbox"
            className="w-3.5 h-3.5 rounded accent-indigo-600"
            checked={showResolved}
            onChange={(e) => setShowResolved(e.target.checked)}
          />
          Show resolved
        </label>
      </div>
      {flags.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No flags yet</p>}
      <div className="space-y-5">
        {Object.entries(groups).map(([feature, featureFlags]) =>
          featureFlags.length === 0 ? null : (
            <div key={feature}>
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase mb-2">
                {FEATURE_LABELS[feature] ?? feature}
              </p>
              <div className="space-y-2">{featureFlags.map(renderFlag)}</div>
            </div>
          )
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire the tab into Settings.tsx**

Add `Flag` to the existing lucide-react import line in `Settings.tsx` (currently `import { User, SlidersHorizontal, Link, Tags, Receipt, Users as UsersIcon, AlertTriangle } from "lucide-react";`):

```tsx
import { User, SlidersHorizontal, Link, Tags, Receipt, Users as UsersIcon, AlertTriangle, Flag } from "lucide-react";
```

Add the import for the new tab component alongside the other `settings/*Tab` imports:

```tsx
import VerificationFeedbackTab from "./settings/VerificationFeedbackTab";
```

Add a new entry to the `TABS` array (after `danger`, so it stays visually last and doesn't disturb the existing tab order):

```tsx
const TABS = [
  { to: "/settings/profile", label: "Profile & Security", icon: User },
  { to: "/settings/preferences", label: "Preferences", icon: SlidersHorizontal },
  { to: "/settings/accounts", label: "Accounts & Bank Sync", icon: Link },
  { to: "/settings/categories", label: "Categories & Rules", icon: Tags },
  { to: "/settings/tax", label: "Tax", icon: Receipt },
  { to: "/settings/household", label: "Household", icon: UsersIcon },
  { to: "/settings/danger", label: "Danger Zone", icon: AlertTriangle, danger: true },
  { to: "/settings/verification", label: "Verification Feedback", icon: Flag },
];
```

Add the route inside the inner `<Routes>` block (after the `danger` route):

```tsx
<Route path="danger" element={<DangerZoneTab />} />
<Route path="verification" element={<VerificationFeedbackTab />} />
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"`
Expected: same as Task 6's ending count.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/settings/VerificationFeedbackTab.tsx frontend/src/pages/Settings.tsx
git commit -m "Add Verification Feedback Settings tab"
```

---

## Final Verification

After all 7 tasks:

- [ ] `source .venv/bin/activate && python -m pytest backend/tests -q` — all green.
- [ ] `cd frontend && npx tsc -b 2>&1 | grep -c "error TS"` — matches the pre-plan baseline exactly (no new errors across the whole plan).
- [ ] Toggle Parallel Ops on in Preferences, confirm a flag icon appears on the Household Snapshot card, the Forecast risk banner (when one account is actually at risk), and Transactions rows (both tabs) — and disappears when the toggle is off.
- [ ] Submit one flag from Household Snapshot, confirm it shows up in Settings → Verification Feedback with the expected value and note, and that "Mark resolved" hides it from the default (open-only) view.
