# Payment Sent, Pending Sync Marker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Dan flag a credit card payment as "sent, pending sync" so the forecast and today's balance reflect it immediately, without creating a real ledger `Transaction` that can silently duplicate against whatever amount the real bank sync eventually posts.

**Architecture:** Two new columns on `CreditCard` (a boolean flag + a snapshot amount). One injection point in the forecast's balance seed subtracts flagged cards' snapshot amounts from checking's opening balance. The flag self-clears the moment `balance_due` changes from the snapshot — no transaction matching, no amount-matching fragility.

**Tech Stack:** FastAPI + SQLAlchemy backend (Python, pytest), React + TypeScript frontend (no test framework — `tsc` + manual verification).

**Spec:** `docs/superpowers/specs/2026-08-28-pending-cc-payment-marker-design.md`

## Global Constraints

- Repo convention: commit directly to `main` after each task. No branches, no worktrees.
- Backend: TDD (red/green) for every claim, following `backend/tests/test_forecast_spreadsheet_gaps_20260814.py` and `backend/tests/test_recurring_router.py`'s established patterns.
- Frontend: no test framework exists — verification is `cd frontend && npx tsc --noEmit` (must exit 0) + a manual browser check description, not TDD.
- Schema changes go through the existing idempotent `ALTER TABLE` list in `backend/database.py`'s `upgrade_schema()` — no Alembic migration.
- `payment_sent_pending_sync`/`payment_sent_amount` are only ever set via the two new dedicated endpoints, never through the generic `PATCH /credit-cards/{id}` body.
- License boundary: entirely original code, no external references.
- Run the full backend suite (`.venv/bin/pytest backend/tests -q`) before each commit — this repo currently has 4 pre-existing, unrelated wall-clock-dependent failures (confirmed via git-stash comparison in prior sessions); a passing run means "same 4, nothing new," not "0 failures."

---

### Task 1: Data model, schema, and forecast seed injection

**Files:**
- Modify: `backend/models.py` (`CreditCard` class, around line 326-344)
- Modify: `backend/database.py` (`upgrade_schema()`, around line 180)
- Modify: `backend/schemas.py` (`CreditCardOut`, around line 553-569)
- Modify: `backend/services/forecast_engine.py:592` (the `current_balance` seed line)
- Test: `backend/tests/test_forecast_spreadsheet_gaps_20260814.py`

**Interfaces:**
- Produces: `CreditCard.payment_sent_pending_sync: bool` (default `False`), `CreditCard.payment_sent_amount: Decimal | None` — consumed by Task 2 (endpoints) and Task 3 (auto-clear).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_forecast_spreadsheet_gaps_20260814.py`, near the other card-scenario tests (after `test_a_real_recorded_payoff_is_also_not_the_safety_floor`):

```python
def test_pending_payment_marker_reduces_opening_balance(db_session):
    """A card flagged payment_sent_pending_sync=True subtracts its snapshot
    amount from checking's opening balance immediately -- before any real
    sync has confirmed the payment happened. This is what a Record Payment
    workaround used to do by creating a real (and sometimes duplicate)
    Transaction; the marker gets the same immediate effect without one."""
    user = _user(db_session, username="pendingmarker")
    account = _checking(db_session, user, balance="1000.00")
    _card(db_session, user, name="Chase", balance_due=Decimal("500.00"),
          current_balance=Decimal("500.00"),
          payment_sent_pending_sync=True, payment_sent_amount=Decimal("500.00"))
    db_session.commit()

    today = date.today()
    entries = build_forecast(db_session, user.id, account.id, today, today)
    assert entries[0].projected_balance == Decimal("500.00"), (
        f"opening balance must be reduced by the pending amount, got "
        f"{entries[0].projected_balance}"
    )


def test_unflagged_cards_do_not_affect_the_opening_balance(db_session):
    """Regression guard: a card with payment_sent_pending_sync left at its
    default (False) must not touch the opening balance at all -- this is
    what every existing card in every other test in this file already
    assumes."""
    user = _user(db_session, username="notpending")
    account = _checking(db_session, user, balance="1000.00")
    _card(db_session, user, name="Chase", balance_due=Decimal("500.00"),
          current_balance=Decimal("500.00"))
    db_session.commit()

    today = date.today()
    entries = build_forecast(db_session, user.id, account.id, today, today)
    assert entries[0].projected_balance == Decimal("1000.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/bin/pytest tests/test_forecast_spreadsheet_gaps_20260814.py::test_pending_payment_marker_reduces_opening_balance -v`
Expected: FAIL with `TypeError: 'payment_sent_pending_sync' is an invalid keyword argument for CreditCard` (the field doesn't exist yet).

- [ ] **Step 3: Add the model fields**

In `backend/models.py`, inside the `CreditCard` class, add after the `pending_charges` line (line 340):

```python
    payment_sent_pending_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_sent_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
```

- [ ] **Step 4: Add the schema migration**

In `backend/database.py`'s `upgrade_schema()`, add after the `is_discretionary` line (line 180):

```python
        "ALTER TABLE credit_cards ADD COLUMN payment_sent_pending_sync BOOLEAN DEFAULT 0",
        "ALTER TABLE credit_cards ADD COLUMN payment_sent_amount NUMERIC(14,2)",
```

- [ ] **Step 5: Add the schema fields to CreditCardOut**

In `backend/schemas.py`, inside `CreditCardOut` (around line 553), add after `updated_at`:

```python
    payment_sent_pending_sync: bool = False
    payment_sent_amount: Optional[Decimal] = None
```

- [ ] **Step 6: Add the forecast seed injection**

In `backend/services/forecast_engine.py`, replace line 592:

```python
    current_balance = Decimal(str(account.current_balance))
```

with:

```python
    current_balance = Decimal(str(account.current_balance))
    if account.type == models.AccountType.checking:
        pending_sent = db.query(models.CreditCard).filter(
            models.CreditCard.user_id == user_id,
            models.CreditCard.is_active == True,
            models.CreditCard.payment_sent_pending_sync == True,
        ).all()
        for card in pending_sent:
            current_balance -= Decimal(str(card.payment_sent_amount or 0))
```

- [ ] **Step 7: Run the local dev database's schema upgrade**

Run: `cd backend && ../.venv/bin/python3 -c "from backend.database import upgrade_schema; upgrade_schema()"`
Expected: exits with no error (idempotent — safe to run even if columns already exist, per the existing `try/except` in `upgrade_schema()`).

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/test_forecast_spreadsheet_gaps_20260814.py::test_pending_payment_marker_reduces_opening_balance tests/test_forecast_spreadsheet_gaps_20260814.py::test_unflagged_cards_do_not_affect_the_opening_balance -v`
Expected: both PASS

- [ ] **Step 9: Run the full backend suite**

Run: `cd .. && .venv/bin/pytest backend/tests -q`
Expected: same pass count as before plus 2, same 4 pre-existing unrelated failures (per Global Constraints), no new failures.

- [ ] **Step 10: Commit**

```bash
git add backend/models.py backend/database.py backend/schemas.py backend/services/forecast_engine.py backend/tests/test_forecast_spreadsheet_gaps_20260814.py
git commit -m "Add payment_sent_pending_sync marker fields and forecast seed injection"
```

---

### Task 2: Mark/clear endpoints

**Files:**
- Modify: `backend/routers/credit_cards.py`
- Test: `backend/tests/test_pending_payment_marker_endpoints.py` (new file)

**Interfaces:**
- Consumes: `CreditCard.payment_sent_pending_sync`, `CreditCard.payment_sent_amount` from Task 1.
- Produces: `POST /credit-cards/{id}/mark-payment-sent`, `POST /credit-cards/{id}/clear-payment-sent` — consumed by Task 4 (frontend).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_pending_payment_marker_endpoints.py`:

```python
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import models
from backend.routers import credit_cards as credit_cards_router_module
from backend.dependencies import get_db, get_current_user


@pytest.fixture()
def client(db_session):
    user = models.User(username="dan", hashed_password="x", display_name="Dan")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    card = models.CreditCard(
        user_id=user.id, name="Chase", credit_limit=Decimal("29000.00"),
        statement_day=28, due_day=25, balance_due=Decimal("9098.94"),
        current_balance=Decimal("9098.94"),
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    app = FastAPI()
    app.include_router(credit_cards_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, card


def test_mark_payment_sent_snapshots_balance_due(client, db_session):
    test_client, user, card = client

    resp = test_client.post(f"/credit-cards/{card.id}/mark-payment-sent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["payment_sent_pending_sync"] is True
    assert Decimal(str(body["payment_sent_amount"])) == Decimal("9098.94")

    db_session.refresh(card)
    assert card.payment_sent_pending_sync is True
    assert card.payment_sent_amount == Decimal("9098.94")


def test_mark_payment_sent_rejects_zero_balance_due(client, db_session):
    test_client, user, card = client
    card.balance_due = Decimal("0")
    db_session.commit()

    resp = test_client.post(f"/credit-cards/{card.id}/mark-payment-sent")
    assert resp.status_code == 400


def test_mark_payment_sent_rejects_already_pending(client, db_session):
    test_client, user, card = client
    card.payment_sent_pending_sync = True
    card.payment_sent_amount = Decimal("9098.94")
    db_session.commit()

    resp = test_client.post(f"/credit-cards/{card.id}/mark-payment-sent")
    assert resp.status_code == 400


def test_clear_payment_sent(client, db_session):
    test_client, user, card = client
    card.payment_sent_pending_sync = True
    card.payment_sent_amount = Decimal("9098.94")
    db_session.commit()

    resp = test_client.post(f"/credit-cards/{card.id}/clear-payment-sent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["payment_sent_pending_sync"] is False
    assert body["payment_sent_amount"] is None

    db_session.refresh(card)
    assert card.payment_sent_pending_sync is False
    assert card.payment_sent_amount is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/bin/pytest tests/test_pending_payment_marker_endpoints.py -v`
Expected: FAIL with 404s (the endpoints don't exist yet).

- [ ] **Step 3: Add the endpoints**

In `backend/routers/credit_cards.py`, add after the existing `delete_card` function (which ends around line 101):

```python
@router.post("/{card_id}/mark-payment-sent", response_model=schemas.CreditCardOut)
def mark_payment_sent(
    card_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = _get_or_404(db, user.id, card_id)
    if not card.balance_due or card.balance_due <= 0:
        raise HTTPException(status_code=400, detail="No balance due to mark as sent")
    if card.payment_sent_pending_sync:
        raise HTTPException(status_code=400, detail="Payment already marked as sent")
    card.payment_sent_pending_sync = True
    card.payment_sent_amount = card.balance_due
    db.commit()
    db.refresh(card)
    return _enrich(card)


@router.post("/{card_id}/clear-payment-sent", response_model=schemas.CreditCardOut)
def clear_payment_sent(
    card_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = _get_or_404(db, user.id, card_id)
    card.payment_sent_pending_sync = False
    card.payment_sent_amount = None
    db.commit()
    db.refresh(card)
    return _enrich(card)
```

This uses the existing `_get_or_404` (line 217) and `_enrich` (line 227) helpers already present in this file — `_enrich` computes `utilization_pct` for the response, used by every other endpoint in this router that returns a card.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/test_pending_payment_marker_endpoints.py -v`
Expected: all 4 PASS

- [ ] **Step 5: Run the full backend suite**

Run: `cd .. && .venv/bin/pytest backend/tests -q`
Expected: same pass count as after Task 1 plus 4, same 4 pre-existing unrelated failures, no new failures.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/credit_cards.py backend/tests/test_pending_payment_marker_endpoints.py
git commit -m "Add mark-payment-sent/clear-payment-sent endpoints"
```

---

### Task 3: Auto-clear on balance_due change

**Files:**
- Modify: `backend/routers/credit_cards.py` (`record_payment` around line 129, `update_card` around line 79-91)
- Test: `backend/tests/test_pending_payment_marker_endpoints.py`

**Interfaces:**
- Consumes: `mark-payment-sent`/`clear-payment-sent` from Task 2, `record_payment`/`update_card` (pre-existing).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_pending_payment_marker_endpoints.py`:

```python
def test_record_payment_clears_a_pending_flag(client, db_session):
    """The flag exists to bridge the gap until the real payment posts.
    record_payment posting a DIFFERENT amount than the snapshot (matching
    2026-08-27's real case: $9,273.76 guessed vs $9,098.94 real autopay)
    must still clear it -- the whole point is not needing exact-amount
    agreement."""
    test_client, user, card = client
    card.payment_sent_pending_sync = True
    card.payment_sent_amount = Decimal("9273.76")
    db_session.commit()

    checking = models.Account(
        user_id=user.id, name="Checking", type=models.AccountType.checking,
        current_balance=Decimal("691.47"),
    )
    db_session.add(checking)
    db_session.commit()
    db_session.refresh(checking)

    resp = test_client.post(f"/credit-cards/{card.id}/payment", json={
        "checking_account_id": checking.id,
        "date": "2026-08-26",
        "amount": "9098.94",
        "notes": "",
    })
    assert resp.status_code == 201

    db_session.refresh(card)
    assert card.payment_sent_pending_sync is False
    assert card.payment_sent_amount is None


def test_editing_balance_due_directly_clears_a_pending_flag(client, db_session):
    """A manual PATCH to balance_due (Dan correcting a card by hand) is the
    other real code path that changes balance_due, and must clear the flag
    the same way record_payment does."""
    test_client, user, card = client
    card.payment_sent_pending_sync = True
    card.payment_sent_amount = card.balance_due
    db_session.commit()

    resp = test_client.patch(f"/credit-cards/{card.id}", json={"balance_due": "500.00"})
    assert resp.status_code == 200

    db_session.refresh(card)
    assert card.payment_sent_pending_sync is False
    assert card.payment_sent_amount is None


def test_patching_an_unrelated_field_does_not_clear_a_pending_flag(client, db_session):
    """The clear condition is specifically balance_due changing -- editing
    the card's name or notes must not disturb a pending flag."""
    test_client, user, card = client
    card.payment_sent_pending_sync = True
    card.payment_sent_amount = card.balance_due
    db_session.commit()

    resp = test_client.patch(f"/credit-cards/{card.id}", json={"notes": "updated"})
    assert resp.status_code == 200

    db_session.refresh(card)
    assert card.payment_sent_pending_sync is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/bin/pytest tests/test_pending_payment_marker_endpoints.py::test_record_payment_clears_a_pending_flag tests/test_pending_payment_marker_endpoints.py::test_editing_balance_due_directly_clears_a_pending_flag -v`
Expected: FAIL — `payment_sent_pending_sync` still `True` after both calls (nothing clears it yet).

- [ ] **Step 3: Add the auto-clear helper and wire it into both endpoints**

In `backend/routers/credit_cards.py`, add near the top of the file (after the router setup, before the first endpoint):

```python
def _clear_pending_if_balance_due_changed(card: models.CreditCard, previous_balance_due: Decimal) -> None:
    """A changed balance_due can only mean fresher data arrived -- whatever
    the new value now is, it makes the manual payment_sent_amount snapshot
    stale. No exact-amount agreement required, unlike transaction dedup."""
    if card.payment_sent_pending_sync and card.balance_due != previous_balance_due:
        card.payment_sent_pending_sync = False
        card.payment_sent_amount = None
```

In `record_payment`, immediately after the existing line (around 129):

```python
    card.balance_due = max(Decimal("0"), Decimal(str(card.balance_due)) - body.amount)
```

add:

```python
    _clear_pending_if_balance_due_changed(card, Decimal(str(card.balance_due)) + body.amount)
```

(the "previous" value is reconstructible as the post-update value plus what was just subtracted, avoiding a second variable capture before the mutation).

In `update_card` (around line 79-91), capture the value before the `setattr` loop and check after:

```python
@router.patch("/{card_id}", response_model=schemas.CreditCardOut)
def update_card(
    card_id: int,
    body: schemas.CreditCardUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = _get_or_404(db, user.id, card_id)
    previous_balance_due = Decimal(str(card.balance_due))
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(card, field, value)
    _clear_pending_if_balance_due_changed(card, previous_balance_due)
    db.commit()
    db.refresh(card)
    return _enrich(card)
```

This is the exact current body of `update_card` (confirmed at
`backend/routers/credit_cards.py:79-91`), with only the two new lines added
(`previous_balance_due` capture, `_clear_pending_if_balance_due_changed`
call) — no other change to its structure.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/bin/pytest tests/test_pending_payment_marker_endpoints.py -v`
Expected: all 7 tests in this file PASS (4 from Task 2, 3 new).

- [ ] **Step 5: Run the full backend suite**

Run: `cd .. && .venv/bin/pytest backend/tests -q`
Expected: same pass count as after Task 2 plus 3, same 4 pre-existing unrelated failures, no new failures.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/credit_cards.py backend/tests/test_pending_payment_marker_endpoints.py
git commit -m "Auto-clear the pending marker when balance_due changes via either code path"
```

---

### Task 4: Frontend UI toggle

**Files:**
- Modify: `frontend/src/api/index.ts` (`cardsApi`, around line 138-151)
- Modify: `frontend/src/pages/CreditCards.tsx`

**Interfaces:**
- Consumes: `POST /credit-cards/{id}/mark-payment-sent`, `POST /credit-cards/{id}/clear-payment-sent` from Task 2/3.

- [ ] **Step 1: Add the API client methods**

In `frontend/src/api/index.ts`, in the `cardsApi` block, add after the `pay` line (140-143):

```ts
  markPaymentSent: (id: number) => api.post(`/credit-cards/${id}/mark-payment-sent`).then((r) => r.data),
  clearPaymentSent: (id: number) => api.post(`/credit-cards/${id}/clear-payment-sent`).then((r) => r.data),
```

- [ ] **Step 2: Add the fields to the Card interface**

In `frontend/src/pages/CreditCards.tsx`, in the `Card` interface, add after `utilization_pct: number;`:

```ts
  payment_sent_pending_sync?: boolean; payment_sent_amount?: string;
```

- [ ] **Step 3: Add the mutation**

Alongside the existing `payMut` mutation (around line 34), add:

```tsx
const markSentMut = useMutation({
  mutationFn: cardsApi.markPaymentSent,
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ["credit-cards"] });
    qc.invalidateQueries({ queryKey: ["accounts"] });
    qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
    qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
  },
});
const clearSentMut = useMutation({
  mutationFn: cardsApi.clearPaymentSent,
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ["credit-cards"] });
    qc.invalidateQueries({ queryKey: ["accounts"] });
    qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
    qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
  },
});
```

- [ ] **Step 4: Add the toggle button**

Next to the existing `$` Record Payment button (around line 94), add:

```tsx
{c.payment_sent_pending_sync ? (
  <button
    onClick={() => clearSentMut.mutate(c.id)}
    className="btn-ghost p-1.5 text-amber-600"
    title="Payment sent — awaiting sync (click to undo)"
  >
    <Clock size={15} />
  </button>
) : (
  <button
    onClick={() => markSentMut.mutate(c.id)}
    className="btn-ghost p-1.5"
    title="Mark payment as sent"
  >
    <Send size={15} />
  </button>
)}
```

Add `Clock, Send` to the existing `lucide-react` import line (currently `Plus, Pencil, Trash2, CreditCard as CardIcon, DollarSign, X, HelpCircle`).

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0

- [ ] **Step 6: Manual check**

Load `/credit-cards`. Confirm: clicking "Mark payment as sent" on a card with a balance due changes the button to the amber clock icon, and the Household Snapshot / Forecast numbers update immediately (no page refresh needed) to reflect the reduced balance. Click the clock icon to undo — button reverts, numbers revert. Try marking a card with `balance_due` already at $0 — should fail silently or show a disabled state (backend returns 400; confirm the frontend doesn't crash on that response, just leaves the button as-is or surfaces a brief error).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/index.ts frontend/src/pages/CreditCards.tsx
git commit -m "CreditCards: add mark/clear payment-sent toggle"
```

## Final Verification

- [ ] Run `.venv/bin/pytest backend/tests -q` one more time from a clean state — same 4 pre-existing failures, everything else passing
- [ ] Run `cd frontend && npx tsc --noEmit` one more time — exit 0
- [ ] Run `git log --oneline -4` and confirm all four commits are present on `main`, unpushed
- [ ] Manual pass through the full flow in the browser: mark a real card's payment as sent, confirm the Household Snapshot and Forecast page both update immediately, confirm the flag auto-clears once `balance_due` is edited to a different value (simulating what a real sync would do)
