# Recurring Per-Account Category Totals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show, at a glance, category totals per account/card on the Recurring page — today's "By Category" rollup mixes every account together.

**Architecture:** Extend `GET /recurring/breakdown`'s existing category-grouping logic with a second, parallel grouping keyed by account/card instead of parent category, reusing the same `RecurringCategoryGroup`/`RecurringCategoryNode` nesting shape. A new frontend component mirrors the existing category rollup's collapse/expand UI.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), React + TypeScript + TanStack Query (frontend). `uv` for Python, `bun` for JS.

**Spec:** `docs/superpowers/specs/2026-11-15-floating-recurring-expenses-design.md` (§5 Per-account category totals)

## Global Constraints

- No real account/card names, balances, or amounts in commits or test fixtures — invented placeholders only.
- Backend: `uv run --locked`; ruff clean; coverage floor never lowered.
- Frontend: `bun`; `bunx vite build`; no new client-side money arithmetic.
- This is additive to `GET /recurring/breakdown` — the existing `by_category`/`ongoing`/`ending` response fields must not change shape or value.
- Live UI changes verified via Interceptor before calling the work done.
- Commits go directly to `main` — no feature branches for this repo.

## Review Focus

- **`credit_card_payment`-type items must be excluded from `by_account` the same way `by_category` already excludes them** (line ~186-190 of `backend/routers/recurring.py`, "credit_card_payment falls through neither branch... would double-count"). A reasonable person would not expect a card's own payoff to appear as spending under that card's bucket on top of the real charges it's paying off.
- **An item with no `account_id` and no `card_id` is impossible by the schema (`account_id` is required on every `RecurringItem`), but a card-charged item's "account" for this view is its card, not the checking account tied to its `account_id`.** Test that a card-linked expense groups under the card's name, not the checking account it's nominally attached to.
- **Inactive items must not appear in `by_account`**, matching how `by_category` only considers `items = [i for i in all_items if i.is_active]` (line ~140).
- **An account/card with zero recurring items should not produce an empty bucket.** Only accounts/cards that actually have at least one qualifying item should appear in `by_account`.

---

### Task 1: `by_account` grouping

**Files:**
- Modify: `backend/schemas.py` (add `by_account: list[RecurringCategoryGroup]` to `RecurringBreakdown`)
- Modify: `backend/routers/recurring.py` (`get_breakdown`, lines ~126-250)
- Test: `backend/tests/test_recurring_breakdown_account.py` (new)

**Interfaces:**
- Consumes: nothing new — reuses `RecurringItem.account_id`/`card_id`/`category_id`, already present.
- Produces: `RecurringBreakdown.by_account: list[RecurringCategoryGroup]`, each group's `group_id`/`group_name` being an `account.id`/`account.name` or `card.id`/`card.name` instead of a parent category, with the same `categories`/`items` nesting as `by_category`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_recurring_breakdown_account.py
def test_checking_item_groups_under_its_account(client, auth_headers, test_recurring_item, test_account):
    r = client.get("/recurring/breakdown", headers=auth_headers)
    by_account = r.json()["by_account"]
    group = next(g for g in by_account if g["group_id"] == test_account.id and g["group_name"] == test_account.name)
    assert any(i["id"] == test_recurring_item.id for i in group["items"] or any(
        i["id"] == test_recurring_item.id for c in group["categories"] for i in c["items"]
    ))

def test_card_item_groups_under_the_card_not_its_account(client, auth_headers, db_session, test_user, test_account, test_card):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=test_card.id,
        name="Test Haircut", amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()

    r = client.get("/recurring/breakdown", headers=auth_headers)
    by_account = r.json()["by_account"]
    card_group = next(g for g in by_account if g["group_id"] == test_card.id and g["group_name"] == test_card.name)
    found = any(i["id"] == item.id for i in card_group["items"]) or any(
        i["id"] == item.id for c in card_group["categories"] for i in c["items"]
    )
    assert found
    account_group = next((g for g in by_account if g["group_id"] == test_account.id), None)
    if account_group:
        assert not any(i["id"] == item.id for i in account_group["items"])

def test_credit_card_payment_type_excluded_from_by_account(client, auth_headers, db_session, test_user, test_account, test_card):
    payment_item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, card_id=test_card.id,
        name="Test CC Payment", amount=Decimal("500.00"), type=models.RecurringType.credit_card_payment,
        day_of_month=20, start_date=date(2026, 1, 1),
    )
    db_session.add(payment_item)
    db_session.commit()

    r = client.get("/recurring/breakdown", headers=auth_headers)
    by_account = r.json()["by_account"]
    for g in by_account:
        all_items = list(g["items"]) + [i for c in g["categories"] for i in c["items"]]
        assert not any(i["id"] == payment_item.id for i in all_items)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_recurring_breakdown_account.py -v`
Expected: FAIL — `by_account` key doesn't exist.

- [ ] **Step 3: Add `by_account` to `get_breakdown`**

In `backend/schemas.py`: add `by_account: list[RecurringCategoryGroup]` to `RecurringBreakdown`.

In `backend/routers/recurring.py`'s `get_breakdown`: build a second `account_groups: dict[int, dict]` dict alongside the existing `groups` dict (lines ~158-214), reusing the same `_group`-style helper and the same `is_expense`/`credit_card_payment`-exclusion check already there (line ~186-190). For each qualifying item, resolve its bucket key to `item.card_id` when set, else `item.account_id` — look up the `CreditCard`/`Account` name the same way `categories` is pre-loaded as a dict (line ~145-149; add two more such dicts for cards and accounts, scoped to `user.id`). Nest by `category_id` under each account/card bucket exactly like `by_category` nests by child category under parent (reuse the same `RecurringCategoryNode` construction code — factor it into a small shared helper if duplicating it verbatim would violate this codebase's existing DRY conventions, otherwise duplicating the ~15-line nesting block once is acceptable for a first pass). Only emit a bucket that ends up with at least one item (Review Focus: no empty buckets).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_recurring_breakdown_account.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass, and every existing `by_category`/`ongoing`/`ending` assertion in `backend/tests/test_recurring*.py` still passes unchanged

- [ ] **Step 6: Commit**

```bash
git add backend/schemas.py backend/routers/recurring.py backend/tests/test_recurring_breakdown_account.py
git commit -m "feat: per-account category totals in the recurring breakdown"
```

---

### Task 2: Frontend rollup component

**Files:**
- Create: `frontend/src/components/RecurringAccountRollup.tsx`
- Modify: `frontend/src/pages/Recurring.tsx` (render the new component)

**Interfaces:**
- Consumes: `RecurringBreakdown.by_account` (Task 1).
- Produces: nothing consumed elsewhere.

- [ ] **Step 1: Create `RecurringAccountRollup.tsx`**

Copy the structure of `frontend/src/components/RecurringCategoryRollup.tsx` verbatim, renaming the component and swapping its header text from "By Category" to "By Account" (keep the `ListTree`-style icon or pick a more fitting one, e.g. a wallet/card icon already used elsewhere in this codebase for accounts — check `frontend/src/pages/Dashboard.tsx` or the sidebar for the icon this app already uses for accounts/cards and reuse it for consistency). The data shape (`group_id`/`group_name`/`monthly`/`categories`/`items`) is identical to what `RecurringCategoryRollup` already consumes, so no new type definitions are needed beyond the prop name.

- [ ] **Step 2: Render it on the Recurring page**

In `frontend/src/pages/Recurring.tsx`, render `<RecurringAccountRollup groups={breakdown?.by_account ?? []} />` next to the existing `<RecurringCategoryRollup groups={breakdown?.by_category ?? []} />` (line ~313) — side by side if the existing layout's grid/flex container allows it without crowding, stacked otherwise; match whatever the surrounding layout already does for placing two cards near each other elsewhere on this page.

- [ ] **Step 3: Run frontend checks**

Run: `cd frontend && bun test && bunx vite build`
Expected: all pass, build succeeds

- [ ] **Step 4: Live-verify via Interceptor**

Open the Recurring page, confirm the new "By Account" rollup renders, expands/collapses correctly, and its totals are visibly consistent with the existing "By Category" rollup (the same items should sum to the same grand total across both views, since they're two groupings of the same underlying set).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/RecurringAccountRollup.tsx frontend/src/pages/Recurring.tsx
git commit -m "feat: per-account category totals rollup on the Recurring page"
```
