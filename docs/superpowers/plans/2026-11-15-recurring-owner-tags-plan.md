# Recurring Item Owner Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each recurring item carry an owner — Family by default, or a named household member — so spending can be broken down by who it belongs to.

**Architecture:** A new `household_members` table of free-text names per user, with a `linked_user_id` column reserved for a future real login link (unused this round — Dan's wife has no login today). `RecurringItem.owner_id` (nullable FK, null = Family) is the tag. A new rollup groups monthly totals by owner, same collapse/expand shape as the existing category rollup.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite (backend), React + TypeScript + TanStack Query (frontend). `uv` for Python, `bun` for JS.

**Spec:** `docs/superpowers/specs/2026-11-15-floating-recurring-expenses-design.md` (§4 Owner tags)

## Global Constraints

- No real names in commits, test fixtures, or this plan — invented placeholders only (e.g. "Test Member").
- Backend: `uv run --locked`; ruff clean; coverage floor never lowered.
- Frontend: `bun`; `bunx vite build`; no new client-side money arithmetic (`frontend/tests/moneyGuard.test.ts` stays green) — the owner rollup sums server-returned `monthly_equivalent` figures only.
- `household_members` is a brand-new table — declaring the SQLAlchemy model is enough, no `upgrade_schema()` entry needed. `RecurringItem.owner_id` is a new column on an existing table and does need an `ALTER TABLE` entry.
- `linked_user_id` exists in the schema this round but nothing reads or writes it yet beyond allowing it to be null — wiring it to the app's real login-linking feature (`User.linked_to_user_id`) is explicitly out of scope.
- Live UI changes verified via Interceptor before calling the work done.
- Commits go directly to `main` — no feature branches for this repo.

## Review Focus

- **Deleting a `HouseholdMember` that recurring items still reference.** A reasonable person expects deleting a person from the household list not to silently orphan or crash on items tagged to them. Decide and test: block the delete while items reference it (mirrors how categories likely behave — check `backend/routers/categories.py`'s delete behavior for the existing convention and follow it), or null out `owner_id` on delete. Pick whichever matches the existing pattern for an analogous FK (e.g. what happens today when a `Category` referenced by a `RecurringItem` is deleted) and follow it, don't invent a third behavior.
- **A duplicate name for the same user.** `HouseholdMember.name` unique per `user_id` — test that creating "Test Member" twice for the same user fails cleanly (400, not a raw 500 from a DB constraint violation).
- **The existing `by_category` rollup must not change shape.** This is purely additive; no existing `GET /recurring/breakdown` consumer should see any difference unless it specifically asks for the new owner data.
- **`owner_id` null (Family) must behave identically to how items behave today**, since every existing item has no owner yet. The rollup's Family bucket must include every item with no explicit owner, not just items explicitly tagged "Family".
- **Two users on the same install never see each other's household members.** `household_members` is scoped by `user_id` the same way `categories` is — test that user A's members don't leak into user B's owner picker or rollup.

---

### Task 1: `HouseholdMember` model, CRUD endpoint, `RecurringItem.owner_id`

**Files:**
- Modify: `backend/models.py` (new `HouseholdMember` class near `RecurringItem`; add `owner_id` to `RecurringItem`, line ~288)
- Modify: `backend/database.py` (`upgrade_schema()` list)
- Create: `backend/routers/household_members.py`
- Modify: `backend/main.py` (register the new router)
- Modify: `backend/schemas.py` (new `HouseholdMemberCreate`/`HouseholdMemberOut`; add `owner_id` to `RecurringCreate`/`RecurringUpdate`/`RecurringOut`)
- Test: `backend/tests/test_household_members.py` (new)

**Interfaces:**
- Produces: `models.HouseholdMember` (`id`, `user_id`, `name` unique per user, `linked_user_id: int | None` FK to `users.id` nullable unique, `created_at`). `RecurringItem.owner_id: int | None` FK to `household_members.id`. `GET/POST /household-members`, `PATCH/DELETE /household-members/{id}`. `schemas.RecurringCreate.owner_id: Optional[int] = None`, same on `RecurringUpdate`/`RecurringOut`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_household_members.py
def test_create_and_list_household_member(client, auth_headers):
    r = client.post("/household-members", json={"name": "Test Member"}, headers=auth_headers)
    assert r.status_code == 201
    member_id = r.json()["id"]

    r2 = client.get("/household-members", headers=auth_headers)
    assert any(m["id"] == member_id for m in r2.json())

def test_duplicate_name_rejected(client, auth_headers):
    client.post("/household-members", json={"name": "Test Member"}, headers=auth_headers)
    r = client.post("/household-members", json={"name": "Test Member"}, headers=auth_headers)
    assert r.status_code == 400

def test_recurring_item_owner_id_defaults_null(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    assert item.owner_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_household_members.py -v`
Expected: FAIL — route and column don't exist.

- [ ] **Step 3: Add the model, column, and router**

In `backend/models.py`: new `HouseholdMember(Base)`, `__tablename__ = "household_members"`: `id`, `user_id` (FK users, not null), `name: Mapped[str]` (String(64), not null), `linked_user_id: Mapped[int | None]` (FK users.id, nullable), `created_at`. `__table_args__ = (UniqueConstraint("user_id", "name"),)`. Add `RecurringItem.owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("household_members.id"))` near `category_id` (line ~294).

In `backend/database.py`'s `upgrade_schema()`, append: `"ALTER TABLE recurring_items ADD COLUMN owner_id INTEGER REFERENCES household_members(id)"`. (`household_members` itself is new — no entry needed, `create_tables()` makes it.)

In `backend/schemas.py`: `HouseholdMemberCreate(BaseModel): name: str`, `HouseholdMemberOut(BaseModel): id: int; name: str` (`model_config = ConfigDict(from_attributes=True)`). Add `owner_id: Optional[int] = None` to `RecurringCreate`, `RecurringUpdate`, `RecurringOut` (mirroring how `category_id` is already declared on each).

Create `backend/routers/household_members.py`, mirroring `backend/routers/categories.py`'s CRUD shape exactly (list/create/patch/delete, `_get_or_404` helper, user-scoped queries). On create, catch the unique-constraint violation and return 400 "A household member with this name already exists" instead of letting it surface as a raw 500 (check how `categories.py` or another router already handles an analogous unique-constraint case, if one exists, and follow that pattern; otherwise a plain `try/except IntegrityError` around the insert is sufficient).

Register in `backend/main.py`: `api_router.include_router(household_members.router)` alongside the other routers (~line 501), with the matching import at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_household_members.py -v`
Expected: PASS

- [ ] **Step 5: Decide and test the delete-while-referenced behavior**

First check `backend/routers/categories.py`'s `delete_category` (line ~60) for how it handles a category still referenced by a `RecurringItem` — follow that exact convention for `delete_household_member`. Add a test proving the chosen behavior (either the delete is blocked with a 400 while referenced, or `owner_id` is nulled out on delete — whichever matches categories).

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/models.py backend/database.py backend/routers/household_members.py backend/main.py backend/schemas.py backend/tests/test_household_members.py
git commit -m "feat: household members and RecurringItem.owner_id"
```

---

### Task 2: Owner rollup + frontend picker

**Files:**
- Modify: `backend/schemas.py` (new `RecurringOwnerGroup`; add `by_owner: list[RecurringOwnerGroup]` to `RecurringBreakdown`)
- Modify: `backend/routers/recurring.py` (`get_breakdown`, lines ~126-250 — add the owner grouping alongside the existing category grouping)
- Create: `frontend/src/components/RecurringOwnerRollup.tsx`
- Modify: `frontend/src/pages/Recurring.tsx` (owner select in the item form; render `RecurringOwnerRollup`; "+ Add person" flow)
- Modify: `frontend/src/api.ts` (household member CRUD calls)
- Test: `backend/tests/test_recurring_breakdown_owner.py` (new)

**Interfaces:**
- Consumes: `models.HouseholdMember`, `RecurringItem.owner_id` (Task 1).
- Produces: `RecurringBreakdown.by_owner: list[RecurringOwnerGroup]`, each `{owner_id: int | None, owner_name: str, monthly: Decimal, items: list[RecurringBreakdownItem]}` (`owner_id = None` is the Family bucket, `owner_name = "Family"`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_recurring_breakdown_owner.py
def test_unassigned_items_fall_in_family_bucket(client, auth_headers, test_recurring_item):
    r = client.get("/recurring/breakdown", headers=auth_headers)
    by_owner = r.json()["by_owner"]
    family = next(g for g in by_owner if g["owner_id"] is None)
    assert family["owner_name"] == "Family"
    assert any(i["id"] == test_recurring_item.id for i in family["items"])

def test_owned_item_falls_in_its_owner_bucket(client, auth_headers, db_session, test_user, test_account):
    member = models.HouseholdMember(user_id=test_user.id, name="Test Member")
    db_session.add(member)
    db_session.commit()
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Haircut",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1), owner_id=member.id,
    )
    db_session.add(item)
    db_session.commit()

    r = client.get("/recurring/breakdown", headers=auth_headers)
    by_owner = r.json()["by_owner"]
    group = next(g for g in by_owner if g["owner_id"] == member.id)
    assert group["owner_name"] == "Test Member"
    assert any(i["id"] == item.id for i in group["items"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run --locked python -m pytest tests/test_recurring_breakdown_owner.py -v`
Expected: FAIL — `by_owner` key doesn't exist in the response.

- [ ] **Step 3: Add `by_owner` to `get_breakdown`**

In `backend/schemas.py`: `RecurringOwnerGroup(BaseModel): owner_id: Optional[int]; owner_name: str; monthly: Decimal; items: list[RecurringBreakdownItem]`. Add `by_owner: list[RecurringOwnerGroup]` to `RecurringBreakdown`.

In `backend/routers/recurring.py`'s `get_breakdown` (lines ~137-240): alongside the existing `groups: dict[...]` used for `by_category`, build a second `owner_groups: dict[int | None, dict]` the same way, keyed by `item.owner_id` (not `item.category_id`'s parent). Only expense-type items count (mirror the existing `is_expense` check at line ~174, excluding `credit_card_payment` the same way `by_category` already does, per this plan's Review Focus and the design doc's §5 cross-reference). Look up each `household_members` row once (same pattern as the existing `categories` dict at line ~145-149) to resolve `owner_name`; `owner_id is None` always resolves to `"Family"`. Sort `by_owner` the same way `by_category` is sorted (largest `monthly` first), Family last or first — match whichever the design doc implies is more useful; no stated preference, so pick one and note it as your call.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run --locked python -m pytest tests/test_recurring_breakdown_owner.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run --locked python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Frontend — owner picker and rollup**

Create `frontend/src/components/RecurringOwnerRollup.tsx`, structurally identical to `frontend/src/components/RecurringCategoryRollup.tsx` but one level deep (owner → items, no nested category level) and fed by `breakdown.by_owner` instead of `breakdown.by_category`.

In `frontend/src/pages/Recurring.tsx`: add `owner_id` to `emptyForm`/`openEdit`/the submit payload (same pattern as `category_id`). Add an "Owner" select in the item form (near the category select, line ~545): options are "Family" (value null), every fetched `HouseholdMember`, and "+ Add person" — selecting "+ Add person" prompts a name (a simple `prompt()` or small inline input, whichever matches this file's existing UX conventions for an inline create — check how the file already handles any similar "create related entity inline" flow, if one exists, before introducing a new pattern), calls `POST /household-members`, then selects the new member. Render `<RecurringOwnerRollup groups={breakdown?.by_owner ?? []} />` next to the existing `<RecurringCategoryRollup .../>` (line ~313).

- [ ] **Step 7: Run frontend checks**

Run: `cd frontend && bun test && bunx vite build`
Expected: all pass, build succeeds

- [ ] **Step 8: Live-verify via Interceptor**

Open the Recurring page, confirm: the owner select renders with Family as default, "+ Add person" creates a new member and selects it, the new owner rollup renders with correct totals, and an item tagged to a person shows up under that person's bucket (not Family) after a refresh.

- [ ] **Step 9: Tag Dan's Haircut with its owner**

Through the running app's UI, set the "Haircut" item created in the floating-expenses plan's Task 5 to owner "Dan" (creating that household member if it doesn't exist yet).

- [ ] **Step 10: Commit**

```bash
git add backend/schemas.py backend/routers/recurring.py frontend/src/components/RecurringOwnerRollup.tsx frontend/src/pages/Recurring.tsx frontend/src/api.ts backend/tests/test_recurring_breakdown_owner.py
git commit -m "feat: owner rollup and picker on the Recurring page"
```
