# Monthly Digest + Strip Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** These are the owner's requests from 2026-11-26.
1. On very wide windows, move the "Needs attention" strip into the left column under the Household Snapshot, so the left column has no empty space.
2. Add a **Monthly Digest** (this month so far) beside the Weekly Digest. The pair is narrower and all of the info fits.

**Architecture:**
- **Backend:** one new read-only endpoint, `GET /spending/monthly-digest?account_id=`. It uses the existing `spending_breakdown` over `[first of this month, today]`. No money logic changes.
- **Frontend:** the Weekly Digest card is extracted into a shared `DigestCard`. The Weekly and Monthly digests sit side by side at `2xl`. Inside each card, the category list and the merchant list stack vertically instead of sitting side by side.

**Tech Stack:** FastAPI + Pydantic + pytest (uv); React 19 + TS + Tailwind 3 + bun:test.

**Spec:** the owner's words: "lets move the 'Nothing needs your attention today' to the bottom left so there is no white space. Also for weekly digest lets have a monthly digest next to it so it is not as wide and get to see all the info." The owner chose "This month so far". Base spec: `docs/superpowers/specs/2026-11-25-dashboard-redesign-design.md` (masking, palette, no money-logic changes).

## Global Constraints

**Data and money**
- No money calculation changes. The monthly totals come from `spending_breakdown` (`backend/services/budget_snapshot.py:392`), the same function behind the weekly categories.
- The over-budget flag is unchanged. It already compares monthly `budgetByCategory` actual vs budgeted, so both digest cards use the same `budgetByCategory` logic.

**Masking**
- When balances are hidden, every amount goes through `maskIfHidden` / `maskMoneyText`.
- No amounts in `title` or `aria-label`.

**Layout**
- Very wide (`isXWide`, `useMinWidth(1700)`, already in `Dashboard.tsx`):
  - Left column: `SnapshotHero`, then `NeedsAttention`, in a `space-y-6` stack.
  - Right column: `BalanceFlowCard` only.
- Below 1700px and on phone: the strip placement is unchanged.
- Digest row:
  - At `2xl` and up: `grid 2xl:grid-cols-2 gap-6`, Weekly on the left and Monthly on the right.
  - Below `2xl`: stacked.
- When `isXWide`, Balance Flow is no longer in the digest row (it's in the right column), so that row holds only the two digests.
- When not `isXWide`, Balance Flow keeps its current spot. The two digests go in their own row directly below it.
- Inside each digest card: "By category" (top 5, with the sort toggle on both) sits above "Top merchants" (top 5), each full card width.

**Tooling and repo**
- bun only and uv only.
- `cd frontend && bun test` and `bunx vite build` must pass.
- `uv run --locked pytest`, ruff and the import check must pass.

**Repo rules**
- **Live data:** the live :8443 app serves `frontend/dist`, so a build changes the live UI. Use `bunx vite build --outDir /tmp/ob-verify-build` for verification builds, never the default outDir.
- **Database:** never touch `.db` files.
- **Commits:** commit to `main` and do not push. End each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Test data:** use made-up amounts.

## Review Focus

1. **The 1st of the month.** The monthly window is a single day, and the endpoint returns that day's spending. It must not error or return last month's spending. Pinned in Task 1.
2. **A month with no spending yet.** `total_spent` is 0, and both lists are empty. The card shows "No spending yet this month." with no empty lists. Pinned in Tasks 1 and 2.
3. **Hidden balances in the new Monthly card.** No digits from amounts appear. Pinned in Task 2.
4. **An active strip in the left column at 1700px and up.** It renders exactly once. Pinned by the Task 2 grep and Chrome.
5. **Sort toggle.** A–Z versus "Highest first" works independently on each card. Pinned in Task 2.

---

### Task 1: Backend `GET /spending/monthly-digest`

**Files:**
- `backend/schemas.py`: add `MonthlyDigest`.
- `backend/services/summary_generator.py`: add `generate_monthly_digest`, next to `generate_weekly_digest` (~line 1057).
- `backend/routers/spending.py`: add a route next to `/weekly-digest` (~line 549).
- `backend/tests/test_monthly_digest.py`: new test file.

**Interfaces:**
- `class MonthlyDigest(BaseModel)` has these fields:
  - `month_start: date`
  - `month_end: date` (today)
  - `total_spent: Decimal`
  - `categories: list[WeeklyDigestCategory]`
  - `top_merchants: list[MerchantSpendingEntry]`
- `generate_monthly_digest(db, user, account_id: int) -> MonthlyDigest`:
  - `start = today.replace(day=1)`, `end = today`.
  - It calls `spending_breakdown(db, user.id, start, end, merchant_limit=10)`.
  - `total_spent` is the sum of the category totals, the same rule as weekly.
  - `account_id` is accepted for parity with weekly and API symmetry. Scope the query exactly as weekly does. Read how `compute_budget_snapshot` calls `spending_breakdown` and mirror it.
- Route: `GET /spending/monthly-digest?account_id=…`, with `response_model=schemas.MonthlyDigest` and the same auth dependency as weekly.

- [ ] **Step 1: Write the failing tests.** Pin today with the `_freeze_today` pattern from `backend/tests/test_snapshot_display_low_matches_forecast.py`, applied to every module that calls `date.today()` on this path.
  - `test_month_to_date_window`: today pinned to 2026-03-18. Transactions on 02-28, 03-01 and 03-18 (made-up amounts). Only the March ones are counted, `month_start == 2026-03-01` and `month_end == 2026-03-18`.
  - `test_first_of_month_single_day`: today pinned to 2026-03-01. Only that day is counted.
  - `test_empty_month`: no March transactions. `total_spent == 0` and both lists are empty.
  - `test_total_equals_category_sum`.
  - `test_route_requires_auth_and_returns_shape`: use the router test pattern from an existing router test.
- [ ] **Step 2: Run and confirm failure.** Run `uv run --locked pytest backend/tests/test_monthly_digest.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run and confirm green.** Run `uv run --locked pytest backend/tests/test_monthly_digest.py backend/tests/test_budget_snapshot.py -q && uv run --locked ruff check . && uv run --locked python -c "import backend.main, cli.budget"`. Expected: all pass.
- [ ] **Step 5: Prove the guard can fail.** Temporarily use `start = today - timedelta(days=30)`, confirm `test_month_to_date_window` fails, then restore.
- [ ] **Step 6: Commit** with the message `feat: month-to-date spending digest endpoint`.

### Task 2: Frontend: `DigestCard`, Monthly beside Weekly, strip into the left column

**Files:**
- `frontend/src/api/index.ts`: add `analyticsApi.monthlyDigest(accountId)` next to `weeklyDigest`.
- `frontend/src/components/dashboard/DigestCard.tsx`: new. Move the Weekly Digest card JSX out of `frontend/src/pages/Dashboard.tsx` (~lines 520-590, "Weekly Digest — …" through the merchants list) verbatim, then restack it as described below.
- `frontend/src/components/dashboard/DigestCard.test.tsx`: new.
- `frontend/src/pages/Dashboard.tsx`: modified.

**Interfaces:**
- `DigestCard({ title, digest, budgetByCategory, hidden, emptyText }: { title: string; digest: { total_spent: string; categories: any[]; top_merchants: any[] } | undefined; budgetByCategory: Map<number, any>; hidden: boolean; emptyText: string })`.
  - It owns its own A–Z / "Highest first" sort state, so each card sorts on its own.
  - Layout: header, "Total spent", "By category" (top 5, with the existing over-budget styling and flags unchanged), then "Top merchants" (top 5), stacked.
  - When `categories` is empty, it renders `emptyText`.
- `Dashboard.tsx`:
  - Add the query `["monthly-digest", primaryChecking?.id]`, `enabled` exactly like weekly.
  - Weekly title: `Weekly Digest — {week_start} – {week_end}`, the existing format.
  - Monthly title: `Monthly Digest — {Month} 1 – {today}`, for example "Monthly Digest — Nov 1 – Nov 26".
  - Monthly `emptyText`: "No spending yet this month." Weekly keeps its existing empty behavior.
  - Layout per Global Constraints:
    - At `isXWide`, the left column becomes `SnapshotHero` + `NeedsAttention`, and the right column holds only `BalanceFlowCard`.
    - The digest row is `grid 2xl:grid-cols-2 gap-6` with Weekly, then Monthly.

- [ ] **Step 1: Write the failing tests** in `DigestCard.test.tsx` (static render; see `SnapshotHero.test.tsx` for the pattern):
  - Shown: the title, the total, and each category and merchant name appear.
  - "Top merchants" appears after "By category" in the markup.
  - Empty categories: the markup contains `emptyText` and does not contain "Top merchants".
  - Hidden: with classes stripped, the markup contains `BALANCE_MASK`, no `$`, and no fixture amount digits.
  - Over-budget: a category whose `budgetByCategory` entry has `actual_total` greater than `budgeted` renders the existing over-budget marker class.
- [ ] **Step 2: Run and confirm failure.** Expected: module not found.
- [ ] **Step 3: Implement** the extraction, the API method, the query and the layout.
- [ ] **Step 4: Verify.**
  - Run `cd frontend && bun test && bunx vite build --outDir /tmp/ob-verify-build`. Expected: pass.
  - Run `grep -c "<NeedsAttention" src/pages/Dashboard.tsx`. Expected: 3 (phone, xwide left column, non-xwide desktop), in mutually exclusive branches.
  - Run `grep -c "<DigestCard" src/pages/Dashboard.tsx`. Expected: 2.
  - Run `grep -c "<BalanceFlowCard" src/pages/Dashboard.tsx`. Expected: 2, mutually exclusive.
- [ ] **Step 5: Commit** with the message `feat: Monthly Digest beside Weekly; attention strip under the Snapshot on wide windows`.
