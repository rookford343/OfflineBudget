# Second-Hop Credit Card Carry-Forward Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the forecast engine's existing one-cycle carried-balance derivation one hop further, seeded by a freshened `pending_charges` value, so the cycle right after `derived_due` uses real data instead of jumping straight to the flat `monthly_spend_estimate`.

**Architecture:** Backend-only. A new `pending_charges_updated_at` timestamp column tracks how recently `pending_charges` was set by hand. `routers/credit_cards.py` stamps it on change; `bank_sync_service.py` clears it (and the value) the moment fresher real data arrives from a sync. `forecast_engine.py` reads it through a freshness helper and, only when fresh and nonzero, injects one additional projected cycle immediately after the existing `derived_due` cycle.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (idempotent `ALTER TABLE` migrations, no Alembic), pytest, TDD red/green.

**Spec:** `docs/superpowers/specs/2026-08-28-second-hop-cc-carry-forward-design.md`

## Global Constraints

- `pending_charges_updated_at` is read-only from the API's perspective — never accepted in `CreditCardCreate`/`CreditCardUpdate` request bodies, only ever set by the two write paths in Tasks 1 and 2.
- The second-hop amount is `pending_charges` alone when fresh — never blended with `monthly_spend_estimate`, never combined with an "upcoming subscriptions" term.
- A `pending_charges` of `0`, or older than 7 days, or with no timestamp at all, means the second hop is skipped entirely for that card — that month falls through to the existing flat-estimate path, unchanged.
- The existing first-cycle `derived_due`/`derived_amount` calculation is not touched — it keeps reading `card.pending_charges` directly, with no freshness check.
- Do not regress `backend/tests/test_forecast_spreadsheet_gaps_20260814.py`, `backend/tests/test_cc_payment_injection.py`, or `backend/tests/test_bank_sync_service.py`. Run each after every task in this plan.
- All values in code/tests are illustrative (`$2,000`, `$500`, etc.) — never copy Dan's real account figures from earlier debugging into commit messages or comments.

---

### Task 1: Data model + freshness stamping on manual edits

**Files:**
- Modify: `backend/database.py:182` (append one line to the `upgrade_schema()` statement list)
- Modify: `backend/models.py:342` (add field to `CreditCard`)
- Modify: `backend/schemas.py:571` (add field to `CreditCardOut`)
- Modify: `backend/routers/credit_cards.py:13-19` (new helper), `:89-102` (`update_card`)
- Test: `backend/tests/test_pending_charges_freshness.py` (new file)

**Interfaces:**
- Produces: `models.CreditCard.pending_charges_updated_at: datetime | None`, stamped by `routers/credit_cards.py:update_card` whenever a `PATCH` changes `pending_charges`. Task 3 (`forecast_engine.py`) reads this field directly off the ORM object — no service-layer function needed to expose it.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_pending_charges_freshness.py`. This mirrors the `client` fixture pattern already established in `backend/tests/test_pending_payment_marker_endpoints.py`.

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
        statement_day=28, due_day=25, pending_charges=Decimal("0"),
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    app = FastAPI()
    app.include_router(credit_cards_router_module.router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), user, card


def test_patching_pending_charges_stamps_the_freshness_timestamp(client, db_session):
    test_client, user, card = client
    assert card.pending_charges_updated_at is None

    resp = test_client.patch(f"/credit-cards/{card.id}", json={"pending_charges": "134.31"})
    assert resp.status_code == 200
    assert resp.json()["pending_charges_updated_at"] is not None

    db_session.refresh(card)
    assert card.pending_charges_updated_at is not None


def test_patching_pending_charges_back_to_zero_clears_the_timestamp(client, db_session):
    test_client, user, card = client
    card.pending_charges = Decimal("134.31")
    from datetime import datetime
    card.pending_charges_updated_at = datetime.utcnow()
    db_session.commit()

    resp = test_client.patch(f"/credit-cards/{card.id}", json={"pending_charges": "0"})
    assert resp.status_code == 200
    assert resp.json()["pending_charges_updated_at"] is None

    db_session.refresh(card)
    assert card.pending_charges_updated_at is None


def test_patching_an_unrelated_field_does_not_stamp_pending_charges(client, db_session):
    test_client, user, card = client
    resp = test_client.patch(f"/credit-cards/{card.id}", json={"notes": "updated"})
    assert resp.status_code == 200

    db_session.refresh(card)
    assert card.pending_charges_updated_at is None


def test_repatching_the_same_pending_charges_value_does_not_restamp(client, db_session):
    """Re-sending the same value (a no-op edit) is not a fresh signal --
    only a real change updates the timestamp."""
    test_client, user, card = client
    card.pending_charges = Decimal("134.31")
    from datetime import datetime, timedelta
    old_stamp = datetime.utcnow() - timedelta(days=3)
    card.pending_charges_updated_at = old_stamp
    db_session.commit()

    resp = test_client.patch(f"/credit-cards/{card.id}", json={"pending_charges": "134.31"})
    assert resp.status_code == 200

    db_session.refresh(card)
    assert abs((card.pending_charges_updated_at - old_stamp).total_seconds()) < 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_pending_charges_freshness.py -v`
Expected: FAIL — `AttributeError: 'CreditCard' object has no attribute 'pending_charges_updated_at'` (or a `KeyError`/`None` mismatch on the response body, since the schema field doesn't exist yet either).

- [ ] **Step 3: Add the database migration**

In `backend/database.py`, immediately after line 182 (`"ALTER TABLE credit_cards ADD COLUMN payment_sent_amount NUMERIC(14,2)",`), add:

```python
        "ALTER TABLE credit_cards ADD COLUMN pending_charges_updated_at DATETIME",
```

- [ ] **Step 4: Add the model field**

In `backend/models.py`, in the `CreditCard` class, immediately after line 342 (`payment_sent_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))`), add:

```python
    pending_charges_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
```

(`datetime` and `DateTime` are already imported at the top of `backend/models.py` — every other model in this file uses them for `created_at`/`updated_at`.)

- [ ] **Step 5: Add the schema field**

In `backend/schemas.py`, in `CreditCardOut`, immediately after line 571 (`payment_sent_amount: Optional[Decimal] = None`), add:

```python
    pending_charges_updated_at: Optional[datetime] = None
```

Do **not** add this field to `CreditCardCreate` or `CreditCardUpdate` — it is never accepted directly from a request body, matching how `payment_sent_pending_sync`/`payment_sent_amount` are handled.

- [ ] **Step 6: Add the stamping helper and wire it into `update_card`**

In `backend/routers/credit_cards.py`, immediately after the existing `_clear_pending_if_balance_due_changed` function (lines 13-19), add:

```python
def _stamp_pending_charges_freshness(card: models.CreditCard, previous_pending_charges: Decimal) -> None:
    """A real change to pending_charges is a fresh, hand-entered signal --
    stamp when it happened so the forecast can later decide how much to
    trust it. Setting it back to 0 means nothing is pending anymore, so
    there is nothing to date."""
    if card.pending_charges == previous_pending_charges:
        return
    if card.pending_charges and card.pending_charges > 0:
        card.pending_charges_updated_at = datetime.utcnow()
    else:
        card.pending_charges_updated_at = None
```

Then modify `update_card` (lines 89-102) to capture the previous value and call the new helper, following the exact pattern `previous_balance_due`/`_clear_pending_if_balance_due_changed` already establishes:

```python
def update_card(
    card_id: int,
    body: schemas.CreditCardUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    card = _get_or_404(db, user.id, card_id)
    previous_balance_due = Decimal(str(card.balance_due))
    previous_pending_charges = Decimal(str(card.pending_charges))
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(card, field, value)
    _clear_pending_if_balance_due_changed(card, previous_balance_due)
    _stamp_pending_charges_freshness(card, previous_pending_charges)
    db.commit()
    db.refresh(card)
    return _enrich(card)
```

Confirm `datetime` is imported at the top of `backend/routers/credit_cards.py` (it is used by `card.pending_charges_updated_at = datetime.utcnow()`); if not already present, add `from datetime import datetime` to its imports.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_pending_charges_freshness.py -v`
Expected: PASS (4 tests)

- [ ] **Step 8: Run the full backend suite to check for regressions**

Run: `cd backend && python -m pytest -q`
Expected: same pass/fail counts as before this task (4 known pre-existing wall-clock-dependent failures, unrelated to this change — compare with `git stash` if any new failure appears).

- [ ] **Step 9: Commit**

```bash
git add backend/database.py backend/models.py backend/schemas.py backend/routers/credit_cards.py backend/tests/test_pending_charges_freshness.py
git commit -m "feat: stamp pending_charges freshness timestamp on manual edit"
```

---

### Task 2: Auto-clear pending_charges on bank sync

**Files:**
- Modify: `backend/services/bank_sync_service.py:146-160`
- Test: `backend/tests/test_bank_sync_service.py`

**Interfaces:**
- Consumes: `models.CreditCard.pending_charges_updated_at` (produced by Task 1).
- Produces: nothing new consumed by later tasks — Task 3 reads `pending_charges`/`pending_charges_updated_at` directly off the `CreditCard` row regardless of which code path last touched them.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_bank_sync_service.py`, immediately after the existing `test_a_bank_sync_clears_a_pending_marker` test:

```python
def test_a_bank_sync_clears_stale_pending_charges(db_session):
    """current_balance from a real sync is fresher and more authoritative
    than a hand-typed pending-charges guess -- the guess is stale the
    moment real data arrives, the same reasoning already applied to the
    payment-sent marker above."""
    user, card, connection, link = _make_card_connection(db_session)
    card.pending_charges = Decimal("134.31")
    card.pending_charges_updated_at = datetime(2026, 8, 27, 9, 0, 0)
    db_session.commit()

    with patch("backend.services.bank_sync_service.decrypt", return_value="https://access.url"), \
         patch("backend.services.bank_sync_service.fetch_transactions", return_value=([], Decimal("-300.00"))):
        sync_connection(db_session, connection)

    db_session.refresh(card)
    assert card.pending_charges == Decimal("0")
    assert card.pending_charges_updated_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_bank_sync_service.py::test_a_bank_sync_clears_stale_pending_charges -v`
Expected: FAIL — `assert Decimal('134.31') == Decimal('0')`

- [ ] **Step 3: Implement the auto-clear**

In `backend/services/bank_sync_service.py`, in the credit-card-link branch (currently lines 139-160), immediately after the existing `payment_sent_pending_sync` clear block (after line 160, still inside the `if card:` block), add:

```python
            if card.pending_charges and card.pending_charges > 0:
                # Same reasoning as the payment-sent marker just above:
                # current_balance now reflects everything the bank knows
                # as of this sync, so a hand-typed "extra, not-yet-synced"
                # pending figure is stale the instant fresher real data
                # lands -- there is nothing left for it to represent.
                card.pending_charges = Decimal("0")
                card.pending_charges_updated_at = None
```

`Decimal` is already imported at the top of `bank_sync_service.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_bank_sync_service.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `cd backend && python -m pytest -q`
Expected: same pass/fail counts as Task 1's Step 8.

- [ ] **Step 6: Commit**

```bash
git add backend/services/bank_sync_service.py backend/tests/test_bank_sync_service.py
git commit -m "feat: clear stale pending_charges on a real bank sync"
```

---

### Task 3: Second-hop projection in the forecast engine

**Files:**
- Modify: `backend/services/forecast_engine.py` (the per-card loop, around lines 436-544 — read the full block and its accumulated comments before editing; this file has had five prior fixes today and the injection logic is delicate)
- Test: `backend/tests/test_forecast_spreadsheet_gaps_20260814.py`

**Interfaces:**
- Consumes: `card.pending_charges: Decimal`, `card.pending_charges_updated_at: datetime | None` (produced by Task 1, kept fresh by Task 2). `_next_occurrence_on_or_after(day: int, on_or_after: date) -> date` (existing helper, already used by the `derived_due` calculation right above this block).
- Produces: nothing consumed by a later task — this is the last task in the plan.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_forecast_spreadsheet_gaps_20260814.py`, at the end of the file:

```python
# --- Second-hop carry-forward, seeded by fresh pending_charges ------------

def test_the_cycle_after_the_carried_cycle_uses_fresh_pending_charges(db_session):
    """Dan's spreadsheet edit, 2026-08-28: the cycle right after the locked
    payoff's own carried cycle should use live pending-charges data instead
    of jumping straight to the flat monthly estimate, the same way the
    first carried cycle already does. Fresh and nonzero pending_charges
    replaces the estimate outright for that one cycle only."""
    user = _user(db_session, username="secondhop")
    account = _checking(db_session, user, balance="60000.00")
    card = _card(
        db_session, user, name="Chase", statement_day=28, due_day=25,
        current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("2000.00"),
        pending_charges_updated_at=datetime.utcnow(),
        next_payment_date=date(2026, 8, 25),
        monthly_spend_estimate=Decimal("15000.00"),
    )
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 14), date(2026, 12, 31))
    estimates = dict(_named(entries, "CC Estimate: Chase"))

    sept = [amt for d, amt in estimates.items() if d.month == 9]
    assert sept == [Decimal("-1000.00")], (
        f"first carried cycle unaffected by this feature, got {sept}"
    )
    oct_ = [amt for d, amt in estimates.items() if d.month == 10]
    assert oct_ == [Decimal("-2000.00")], (
        f"second hop must use fresh pending_charges instead of the flat estimate, got {oct_}"
    )
    later = [amt for d, amt in estimates.items() if d.month >= 11]
    assert later, "cycles beyond the second hop must still be projected"
    assert all(a == Decimal("-15000.00") for a in later), (
        f"cycles beyond the second hop keep the flat estimate, got {later}"
    )


def test_zero_pending_charges_skips_the_second_hop(db_session):
    """No pending charges means no real second-hop signal -- that month
    falls through to the flat estimate exactly as it did before this
    feature existed."""
    user = _user(db_session, username="secondhopzero")
    account = _checking(db_session, user, balance="60000.00")
    _card(
        db_session, user, name="Chase", statement_day=28, due_day=25,
        current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("0"),
        next_payment_date=date(2026, 8, 25),
        monthly_spend_estimate=Decimal("15000.00"),
    )
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 14), date(2026, 11, 30))
    estimates = dict(_named(entries, "CC Estimate: Chase"))

    oct_ = [amt for d, amt in estimates.items() if d.month == 10]
    assert oct_ == [Decimal("-15000.00")], (
        f"zero pending_charges must fall through to the flat estimate, got {oct_}"
    )


def test_stale_pending_charges_skips_the_second_hop(db_session):
    """A pending-charges figure older than 7 days is not trusted -- it
    falls through to the flat estimate the same as a zero value."""
    user = _user(db_session, username="secondhopstale")
    account = _checking(db_session, user, balance="60000.00")
    _card(
        db_session, user, name="Chase", statement_day=28, due_day=25,
        current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("2000.00"),
        pending_charges_updated_at=datetime.utcnow() - timedelta(days=10),
        next_payment_date=date(2026, 8, 25),
        monthly_spend_estimate=Decimal("15000.00"),
    )
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 14), date(2026, 11, 30))
    estimates = dict(_named(entries, "CC Estimate: Chase"))

    oct_ = [amt for d, amt in estimates.items() if d.month == 10]
    assert oct_ == [Decimal("-15000.00")], (
        f"stale pending_charges must fall through to the flat estimate, got {oct_}"
    )


def test_pending_charges_with_no_timestamp_skips_the_second_hop(db_session):
    """A nonzero pending_charges with no recorded timestamp (a pre-existing
    row from before this feature shipped, or one a sync just cleared) is
    treated as already stale rather than silently trusted."""
    user = _user(db_session, username="secondhopnostamp")
    account = _checking(db_session, user, balance="60000.00")
    _card(
        db_session, user, name="Chase", statement_day=28, due_day=25,
        current_balance=Decimal("4000.00"), balance_due=Decimal("3000.00"),
        pending_charges=Decimal("2000.00"),
        pending_charges_updated_at=None,
        next_payment_date=date(2026, 8, 25),
        monthly_spend_estimate=Decimal("15000.00"),
    )
    db_session.commit()

    entries = build_forecast(db_session, user.id, account.id, date(2026, 8, 14), date(2026, 11, 30))
    estimates = dict(_named(entries, "CC Estimate: Chase"))

    oct_ = [amt for d, amt in estimates.items() if d.month == 10]
    assert oct_ == [Decimal("-15000.00")], (
        f"a nonzero value with no timestamp must fall through to the flat estimate, got {oct_}"
    )
```

Add `datetime` to this test file's existing `from datetime import date, timedelta` import line, making it `from datetime import date, datetime, timedelta`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_forecast_spreadsheet_gaps_20260814.py -k second_hop -v`
Expected: FAIL — `test_the_cycle_after_the_carried_cycle_uses_fresh_pending_charges` fails because October currently projects `-15000.00` (the flat estimate), not `-2000.00`. The other three tests currently PASS by coincidence (today's behavior already falls through to the flat estimate in every case) — that is expected and fine; they exist to pin the fallback behavior in place once Step 3 changes the code around them, not to prove a new failure.

- [ ] **Step 3: Implement the second-hop computation**

In `backend/services/forecast_engine.py`, add the freshness helper near the top of the file, immediately after the existing `_card_payoff_date_for_charge` function (which ends around line 58, just before the blank line preceding the file's next top-level function):

```python
def _fresh_pending_charges(card: "models.CreditCard", today: date) -> Decimal:
    """pending_charges is a hand-typed, point-in-time figure -- trustworthy
    right after Dan enters it, increasingly not as days pass without a real
    sync confirming it. A stale or absent timestamp is treated the same as
    nothing pending at all, never silently carried forward."""
    if not card.pending_charges or card.pending_charges <= 0:
        return Decimal("0")
    if card.pending_charges_updated_at is None:
        return Decimal("0")
    if (today - card.pending_charges_updated_at.date()).days > 7:
        return Decimal("0")
    return Decimal(str(card.pending_charges))
```

Then, in the per-card loop, immediately after the existing `derived_due`/`derived_amount` block ends (immediately after the line `derived_amount = carried + upcoming` and before the comment block starting `# A stale next_payment_date rolled forward...`, i.e., right after what is currently line 472), insert:

```python
        # Second hop: the cycle right after the one just derived above.
        # There is no "carried" real balance signal for it yet -- that
        # window has not started accruing real spend as of today -- but a
        # fresh pending_charges figure (Dan's own hand-tracked read of what
        # is already posting toward it, per his spreadsheet, 2026-08-28) is
        # still better than jumping straight to the flat monthly estimate.
        # Only one hop: cycles beyond this one have no real signal at all
        # and keep the flat estimate, matching Dan's own unedited
        # spreadsheet cells for every month past this one.
        second_close: date | None = None
        second_due: date | None = None
        second_amount = Decimal("0")
        if derived_due is not None:
            second_close = _next_occurrence_on_or_after(card.statement_day, derived_due + timedelta(days=1))
            second_due = _next_occurrence_on_or_after(card.due_day, second_close + timedelta(days=1))
            second_amount = _fresh_pending_charges(card, today)
```

Next, extend `_covered_by_real_payment` (currently at lines 521-533) to also suppress the flat estimate for `second_due`'s month, but only when there is actually a second-hop amount to replace it with:

```python
        def _covered_by_real_payment(when: date) -> bool:
            """Something better than an estimate already lands in this month --
            either the locked balance_due payoff, or the carried-balance figure
            derived above. A flat estimate on top of either would charge the
            same statement twice."""
            if derived_due is not None and (derived_due.year, derived_due.month) == (when.year, when.month):
                return True
            if second_due is not None and second_amount > 0 and (second_due.year, second_due.month) == (when.year, when.month):
                return True
            return (
                next_payment is not None
                and next_payment.year == when.year
                and next_payment.month == when.month
                and bool(card.balance_due and card.balance_due > 0)
            )
```

Finally, immediately after the existing `derived_due` injection block (currently lines 538-544, the `if (not payment_double_counts_derived and derived_due is not None ...)` block that appends to `cc_estimates_by_date`), add the second-hop injection:

```python
        if (
            second_due is not None
            and start_date <= second_due <= end_date
            and second_amount > 0
        ):
            cc_estimates_by_date.setdefault(second_due, []).append((card.name, second_amount))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_forecast_spreadsheet_gaps_20260814.py -v`
Expected: PASS (all tests in the file, including the four new ones)

- [ ] **Step 5: Run the full backend suite to check for regressions**

Run: `cd backend && python -m pytest -q`
Expected: same pass/fail counts as Task 2's Step 5 — specifically confirm `test_cc_payment_injection.py` and `test_bank_sync_service.py` are still fully green, and that the 4 pre-existing wall-clock-dependent failures (if present at this time of year) are the only failures.

- [ ] **Step 6: Commit**

```bash
git add backend/services/forecast_engine.py backend/tests/test_forecast_spreadsheet_gaps_20260814.py
git commit -m "feat: seed the second forecast cycle from fresh pending_charges"
```
