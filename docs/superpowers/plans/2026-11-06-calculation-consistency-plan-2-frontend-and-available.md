# Calculation Consistency — Plan 2: Frontend Math to Backend, Available to Spend, Net Worth

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The frontend shows only backend-computed money figures.
- Available to Spend is rebuilt "before budgets" on the shared layer.
- Net worth has one recipe.
- Every pending-adjusted balance comes from the server.

**Architecture:**
- Each client-side money computation found by the 2026-11-06 survey moves behind a backend field or endpoint built from the Plan 1 primitives: `month_base`, `real_spend`, `pending`, `forecast_walk`, `card_payment_model` and `cushion`.
- Tasks 1–6 move or rebuild calculations behind tested endpoints and swap the frontend to them.
- Task 7 adds a frontend guard and extends parity, so the browser can't quietly grow a second recipe again.

**Tech Stack:**
- Backend: FastAPI, SQLAlchemy, SQLite, pytest via uv.
- Frontend: React + TypeScript + TanStack Query, built with `bunx vite build`. Frontend unit tests run on `bun test` (`frontend/tests/*.test.ts`, `bun:test`).

**Spec:** `docs/superpowers/specs/2026-11-06-calculation-consistency-design.md` (see the sections "Frontend", "Available to Spend rebuild", "Decisions already made"). Also read `docs/architecture.md` before any task.

## Global Constraints

- **Public repo:** synthetic figures only in code, tests, docs and commit messages.
- **Tooling:** uv for Python and bun for the frontend. Backend tests run as `cd backend && uv run --locked python -m pytest`, with a coverage floor of 85. Lint is `uv run --locked ruff check .`. Import smoke test: `uv run --locked python -c "import backend.main, cli.budget"`. Frontend checks are `cd frontend && bunx vite build` and `cd frontend && bun test`.
- **Commits:** commit to `main`. Never push; pushing waits for Dan's OK.
- **Live backend:** it runs `uvicorn --reload` from this tree.
  - Back up with `backup_database()` before any schema change, and keep migrations additive and nullable.
  - Any step that moves a visible number runs `scripts/calc_before_after.py --db <copy> --user 2 --ref <base>` on a `backup_database()` copy. Exact figures go only into the git-ignored report.
- **Shared layer only:**
  - New money math lives in a shared-layer module listed in `backend/tests/test_calc_guard.py` `SHARED_LAYER`, with a line in `docs/architecture.md`.
  - When a function is rewritten onto the shared layer, delete its `PRESENTATIONAL_OR_WRITER` allowlist entry; the stale-entry test enforces this.
- **Versioning:** when a figure's meaning changes, bump `CALC_VERSION` (currently 9) with a changelog line.
- **Settled rules from the spec, verbatim:**
  - "Available to Spend (rebuilt) = 'before budgets': this month's income − bills − one-offs − real spending so far, without the groceries/savings budgets … Its ⓘ walks from it to Left to Spend."
  - "The frontend displays backend figures and does no money math."
  - "Pure formatting and chart sampling may stay."
- **Plan-level decisions** (Iris's calls, recorded in `docs/architecture.md`'s decisions log):
  - **(a)** A pending-adjusted checking balance is posted + every pending row, credits and debits alike. It only applies while the pending snapshot is live; otherwise it equals the posted balance. This matches what the UI shows today.
  - **(b)** Net worth uses the snapshot's definition everywhere: assets = manual assets + account balances, and liabilities = manual liabilities + card current balances. Stored history already uses it.
  - **(c)** Percent-of-total and share-of-pie ratios over figures the backend already sent are presentational and may stay in the frontend.

## Review Focus

1. **A pending deposit (credit) on checking** raises the after-pending balance; it is not dropped. *Task 1 test.*
2. **A checking account with no live pending snapshot** (SimpleFIN/manual): after-pending equals posted, and the pending count is 0. *Task 1 test.*
3. **An overdrawn checking account** (negative balance) reduces assets, the same way in the live net-worth view and in the stored snapshot. *Task 4 test.*
4. **A card whose hand-typed pending is more than 7 days stale**: "spent this cycle" and "after pending" ignore it, by `card_pending`, not the raw field. *Task 3 test.*
5. **Available to Spend on the 1st with nothing spent** equals income − bills − one-offs. A refund later that month lowers "spent so far" rather than adding income. *Task 5 test.*

---

### Task 1: Account balances with pending, served by the backend

**Files:**
- Create: `backend/services/account_balances.py`
- Modify:
  - `backend/services/pending.py` (`checking_balance_with_pending`, per decision (a))
  - `backend/routers/accounts.py` (new route)
  - `backend/schemas.py`
  - `frontend/src/lib/usePendingBalances.ts`
  - `frontend/src/components/Layout.tsx` (~113, ~123)
  - `frontend/src/components/CheckingBalancesCard.tsx`
  - `frontend/src/api/index.ts`
- Test: `backend/tests/test_account_balances.py`

**Interfaces:**
- Produces:

```python
class AccountBalanceOut(BaseModel):
    account_id: int
    posted: Decimal
    pending_total: Decimal        # signed sum of live pending rows (0 when not live)
    pending_count: int
    after_pending: Decimal        # posted + pending_total
    month_start_balance: Decimal  # after_pending − this month's posted + pending flow on the account
    month_change_pct: Decimal | None  # (after_pending − month_start_balance) / |month_start_balance|; None when start is 0

class AccountBalancesOut(BaseModel):
    accounts: list[AccountBalanceOut]   # every active account, sidebar order unchanged
    total_after_pending: Decimal        # Σ after_pending over the list (what the sidebar total shows)

def account_balances(db, user_id: int, today: date) -> AccountBalancesOut   # services/account_balances.py
```
- Route: `GET /accounts/balances` returns `AccountBalancesOut`. It is declared before `/accounts/{id}` so it isn't parsed as an id.

- [ ] **Step 1:** Write the tests, all on synthetic fixtures:
  - `test_after_pending_includes_debits_and_credits`: posted 1000.00, live pending −200.00 and +50.00 → after 850.00, count 2. *(Review Focus 1)*
  - `test_not_live_snapshot_means_posted` *(Review Focus 2)*
  - `test_total_is_sum_over_active_accounts`
  - `test_month_change_pct_uses_month_flows`
  - `test_month_change_pct_none_when_start_zero`
  - `test_endpoint_shape`
- [ ] **Step 2:** Run `cd backend && uv run --locked python -m pytest tests/test_account_balances.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement on `pending.checking_pending_debits`/`pending_snapshot_is_live`. Change `checking_balance_with_pending` to decision (a), with all live rows of both signs, and update its existing tests and docstring. Add `services/account_balances.py` to `SHARED_LAYER` with a reason.
- [ ] **Step 4:** Point the frontend at the new endpoint:
  - `usePendingBalances` reads `/accounts/balances` with one query, returning `{pending, posted, afterPending}` from it. Its per-account `useQueries` go away.
  - `Layout.tsx` total uses `total_after_pending`, and pct change uses `month_change_pct`.
  - `CheckingBalancesCard` is unchanged apart from the hook source.
  - Delete the client-side `flowByAccount` math.
- [ ] **Step 5:** Run the backend suite, `cd frontend && bunx vite build`, and before/after on a DB copy. Expect zero headline deltas; the sidebar isn't in the script. Note any live account whose pending changed under decision (a).
- [ ] **Step 6:** Commit `feat(calc): account balances with pending come from the backend`.

### Task 2: Transactions running balance from the backend

**Files:**
- Modify:
  - `backend/services/account_balances.py`
  - `backend/routers/accounts.py`
  - `backend/schemas.py`
  - `frontend/src/pages/Transactions.tsx` (~353-380, ~805, ~835)
  - `frontend/src/api/index.ts`
- Test: `backend/tests/test_running_balance.py`

**Interfaces:**
- Consumes: `account_balances` internals from Task 1 (same posted and pending sources).
- Produces:

```python
class RunningBalanceRow(BaseModel):
    kind: Literal["pending", "posted"]
    id: int                    # AccountPendingTransaction.id or Transaction.id
    date: date
    balance_after: Decimal

def running_balance(db, user_id: int, account_id: int, start: date, today: date) -> list[RunningBalanceRow]
```
- Route: `GET /accounts/{id}/running-balance?start=YYYY-MM-DD` returns `list[RunningBalanceRow]`.
- Ordering, kept the same as today's UI:
  - Pending rows walk forward from posted, oldest first, ending at `after_pending`.
  - Posted rows walk backward from posted (newest first), so a posted row's `balance_after` is the balance right after it posted.

- [ ] **Step 1:** Write the tests:
  - `test_posted_rows_walk_backward_from_posted`: posted 1000.00; transactions −100.00 (newest) and +300.00 → balance_after 1000.00 and 1100.00.
  - `test_pending_rows_walk_forward_to_after_pending`
  - `test_only_requested_account`
  - `test_start_bounds_posted_rows`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement the function and route. `Transactions.tsx` reads `balance_after` keyed by `(kind, id)` and deletes its client walk, including the `["transactions-balance-walk"]` query.
- [ ] **Step 4:** Run the backend suite and `bunx vite build`.
- [ ] **Step 5:** Commit `feat(calc): transactions running balance computed by the backend`.

### Task 3: Net Position and card cycle figures from the backend

**Files:**
- Create: `backend/services/net_position.py`
- Modify:
  - `backend/schemas.py` (`CreditCardOut`)
  - `backend/routers/credit_cards.py` (populate the new fields)
  - A new route in `backend/routers/accounts.py`, or a dashboard router if one exists; pick the existing pattern
  - `frontend/src/pages/Dashboard.tsx` (~184-220, ~646)
- Test: `backend/tests/test_net_position.py`

**Interfaces:**
- Consumes: `pending.card_pending(card, today)`.
- Produces:

```python
# CreditCardOut gains (raw pending_charges stays, for the edit form only):
pending_effective: Decimal     # card_pending(card, today)
spent_this_cycle: Decimal      # max(0, current_balance − balance_due + pending_effective)
after_pending: Decimal         # current_balance + pending_effective

class NetPositionOut(BaseModel):
    checking_total: Decimal
    cards_due_total: Decimal
    net_position: Decimal        # checking_total − cards_due_total
    explain: Explanation         # start "Checking" (children per account), subtract "Card statements due" (children per card)

def net_position(db, user_id: int) -> NetPositionOut   # services/net_position.py
```
- Route: `GET /accounts/net-position` returns `NetPositionOut`.

- [ ] **Step 1:** Write the tests:
  - `test_net_position_and_explain_replay` (`explain.replay` result == `net_position`; `children_consistent` true)
  - `test_spent_this_cycle_uses_card_pending`
  - `test_stale_hand_typed_pending_ignored_in_cycle_figures`: updated 8 days ago → `pending_effective` 0. *(Review Focus 4)*
  - `test_spent_this_cycle_floors_at_zero`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Add `services/net_position.py` to `SHARED_LAYER`. `Dashboard.tsx` renders `net_position` and its `explain` through `HowCalculated`, and the card rows read `spent_this_cycle`/`after_pending`/`pending_effective`. Delete the client sums and the hand-built `netPositionExplain`. Remove the `generate_daily_summary` `PENDING_READ_ALLOWED` entry if it no longer reads the raw field.
- [ ] **Step 4:** Run the backend suite, `bunx vite build`, and before/after (a cycle-figure change is expected only for a card with stale hand-typed pending).
- [ ] **Step 5:** Commit `feat(calc): net position and card cycle figures computed by the backend`.

### Task 4: Net worth — one recipe

**Files:**
- Create: `backend/services/net_worth.py`
- Modify:
  - `backend/routers/networth.py` (`get_totals`, `capture_snapshot`)
  - `backend/schemas.py` (`NetWorthTotals`)
  - the Net Worth page (`frontend/src/pages/NetWorth.tsx`, or wherever `NetWorthTotals` is rendered), for labels
  - `backend/tests/test_calc_guard.py` (delete the two networth entries)
- Test: `backend/tests/test_net_worth_recipe.py`

**Interfaces:**
- Produces:

```python
class NetWorthTotals(BaseModel):
    manual_assets: Decimal
    account_balances: Decimal
    total_assets: Decimal          # manual_assets + account_balances   (decision b)
    manual_liabilities: Decimal
    card_balances: Decimal
    total_liabilities: Decimal     # manual_liabilities + card_balances
    net_worth: Decimal             # total_assets − total_liabilities
    explain: Explanation

def net_worth_totals(db, user_id: int) -> NetWorthTotals   # services/net_worth.py; both routes call it
```

- [ ] **Step 1:** Write the tests:
  - `test_live_and_snapshot_agree`: the stored snapshot's `total_assets`, `total_liabilities` and `net_worth` equal `net_worth_totals` for the same data.
  - `test_overdrawn_checking_reduces_assets` *(Review Focus 3)*
  - `test_explain_replays_to_net_worth`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Both routes call `net_worth_totals`. Delete the networth allowlist entries and add `services/net_worth.py` to `SHARED_LAYER`. The Net Worth page shows assets and liabilities under the new definitions, with the breakdown fields as sub-lines and no client math. `net_worth` itself is numerically unchanged.
- [ ] **Step 4:** Run the backend suite, `bunx vite build`, and before/after. Bump `CALC_VERSION` to 10 with "v10: net worth has one recipe; assets include account balances".
- [ ] **Step 5:** Commit `feat(calc): one net-worth recipe for the live view and snapshots`.

### Task 5: Available to Spend rebuilt "before budgets"

**Files:**
- Create: `backend/services/available_to_spend.py`
- Modify:
  - `backend/routers/spending.py`: `available_to_spend` becomes a thin route, and `_committed_card_bills_fired` is deleted.
  - `backend/schemas.py` (`AvailableToSpend`)
  - `backend/tests/test_calc_guard.py`: delete both "rebuilt in Plan 2" entries.
  - `frontend/src/pages/Dashboard.tsx` (~254-281)
  - `docs/architecture.md`
- Test: `backend/tests/test_available_to_spend.py`

**Interfaces:**
- Consumes: `build_month_base` (income with the Social Security boost, bills, one-offs including funded netting), `real_spend.spend_totals`/`classified_rows`, `pending.card_pending`, and `compute_budget_snapshot(...).left_to_spend`.
- Produces:

```python
class AvailableToSpend(BaseModel):
    monthly_income: Decimal       # month_base income_total (all frequencies, SS boost, include_in_forecast filter)
    committed_expenses: Decimal   # month_base expense_total (bills incl. card-linked, overrides, quarterly in due month)
    one_offs_net: Decimal         # month_base one-offs out − in (funded netting already applied)
    spent_this_month: Decimal     # real spending so far this month not already in bills or one-offs, + card pending
    available: Decimal            # monthly_income − committed_expenses − one_offs_net − spent_this_month
    explain: Explanation          # the four rows above
    to_left_to_spend: Explanation # starts at `available`, rows to the snapshot's left_to_spend; result == left_to_spend

def available_to_spend(db, user: models.User, as_of: date) -> AvailableToSpend   # services/available_to_spend.py
```
- **"Spent so far" rule:**
  - Count `spend` verdicts for the month to date (checking and card, refunds netted).
  - Exclude rows linked to a recurring item, since they're already in bills.
  - Exclude spend matched to a settled one-off, since it's already in one-offs.
  - Exclude card payments and transfers; `real_spend` already does this.
  - Add `card_pending` for active cards.
- **`to_left_to_spend` rows:** derive them so the replay ends exactly at `left_to_spend`. Expected rows:
  - groceries budget;
  - savings set aside;
  - checking discretionary spend added back, because Left to Spend counts card spend only;
  - charged-so-far and settled-on-card adjustments.

  Name each row in plain language.

- [ ] **Step 1:** Write the tests:
  - `test_first_of_month_nothing_spent`: available == income − bills − one-offs. *(Review Focus 5)*
  - `test_refund_lowers_spent_not_income` *(Review Focus 5)*
  - `test_recurring_linked_spend_not_double_counted`
  - `test_settled_one_off_not_double_counted`
  - `test_card_pending_counted`
  - `test_ss_boost_in_income`
  - `test_explain_replays_to_available`
  - `test_walk_to_left_to_spend_ends_at_snapshot_value`: on the parity fixture, `replay(to_left_to_spend) == compute_budget_snapshot(...).left_to_spend`, and `children_consistent`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement and add to `SHARED_LAYER`. The route returns the new schema. The Dashboard card keeps its four rows (now including "One-offs") and adds `HowCalculated` with `explain` and an informational "From here to Left to Spend" panel from `to_left_to_spend`.
- [ ] **Step 4:** Run the backend suite and `bunx vite build`. Run before/after; this card isn't in the script, so add an `available` row to `scripts/calc_before_after.py` (old ref: legacy endpoint value) and paste the diff in the report. Bump `CALC_VERSION` to 11 with "v11: Available to Spend rebuilt before budgets on the shared layer".
- [ ] **Step 5:** Commit `feat(calc): Available to Spend rebuilt before budgets on the shared layer`.

### Task 6: Budget, Spending, Recurring and Forecast figures from the backend

**Files:**
- Modify:
  - `backend/services/budget_plan.py`, `backend/schemas.py` (`BudgetPlanOut`)
  - the spending overview and monthly-by-category endpoints in `backend/routers/spending.py`
  - `backend/routers/recurring.py` (breakdown)
  - `backend/services/forecast_engine.py` (`ForecastEntry`)
  - `frontend/src/lib/budgetPlan.ts`
  - `frontend/src/pages/Budget.tsx` (~158, ~571-574)
  - `frontend/src/pages/Spending.tsx` (~42, ~200)
  - `frontend/src/pages/Recurring.tsx` (~169)
  - `frontend/src/pages/Forecast.tsx` (~1247-1257)
  - `frontend/tests/budgetPlan.test.ts`
- Test: `backend/tests/test_frontend_figures_backend.py`

**Interfaces — new backend fields, one per moved computation:**
- `BudgetPlanOut.track_totals: TrackTotals {budgeted, available, spent, left, pct, over_count}`. These are the same figures `trackTotals()` computes today, in cents-exact Decimal. Also `BudgetPlanOut` group rows' `committed`/`flexible` footers sum to the existing `committed_total`/`flexible_total`. If the visible groups are filtered, add `committed_visible_total`/`flexible_visible_total`.
- Spending overview: each parent category gains `direct_actual: Decimal` (its own spend excluding children). The monthly-by-category response gains `monthly_average: Decimal` per category, averaging the completed months shown (the current month excluded), the same rule as `categoryMonthlyAverage`.
- `/recurring/breakdown` includes every item the page lists, including inactive ones, with `monthly_equivalent`, so the frontend fallback is deleted.
- `ForecastEntry.anchor_moved: bool` and `anchor_delta: Decimal | None`: true when a day checkpoint moved the walked balance by ≥ 0.005.

- [ ] **Step 1:** Write a backend test for each field:
  - `test_track_totals_match_legacy_rule` (port the cases from `frontend/tests/budgetPlan.test.ts`)
  - `test_direct_actual_is_parent_minus_children`
  - `test_monthly_average_excludes_current_month`
  - `test_breakdown_covers_inactive_items` (weekly item's monthly_equivalent is not amount/1)
  - `test_anchor_moved_flag`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement the fields. Swap the frontend to read them and delete `trackTotals`/`availableOf` money math, the Spending average and kid-sum math, the Recurring fallback and the Forecast `walked` computation. Trim `frontend/tests/budgetPlan.test.ts` to whatever pure filtering remains, or delete the file if nothing remains. Per-row cents formatting and percent-of-total ratios over backend figures may stay (decision c).
- [ ] **Step 4:** Run the backend suite, `bunx vite build` and `bun test`.
- [ ] **Step 5:** Commit `feat(calc): budget, spending, recurring and forecast figures come from the backend`.

### Task 7: Frontend money guard, parity extension, docs

**Files:**
- Create: `frontend/tests/moneyGuard.test.ts`
- Modify:
  - `backend/tests/test_parity_headline.py`
  - `docs/architecture.md`
  - `docs/technical-guide.md`
- Test: as above.

**Interfaces:**
- Consumes everything above.

- [ ] **Step 1:** Write `moneyGuard.test.ts` (`bun:test`, reads `frontend/src/**/*.{ts,tsx}` with `fs`).
  - It fails on a `.reduce(` whose callback adds or subtracts, or a `+`/`-` between `parseFloat(...)`/`Number(...)` results, when the line or callback references a money identifier: `amount`, `balance`, `current_balance`, `balance_due`, `pending`, `actual`, `budget`, `committed`, `flexible`, `income`, `spent`, `available`.
  - Excluded: `frontend/tests/`, and an allowlist at the top of the file in the form `{"path:snippet": reason}` for presentational ratios (decision c) and chart sampling. A stale-entry check matches the backend guard.
  - Include self-tests with an inline sample string showing one violation and one allowed ratio.
- [ ] **Step 2:** Run `cd frontend && bun test tests/moneyGuard.test.ts`. Fix any violation by moving it to the backend, not by allowlisting, unless it is a presentational ratio; list every allowlist entry in the report.
- [ ] **Step 3:** Extend `test_parity_headline.py`. On the existing fixture, add an `available` row from `/spending/available-to-spend` (its `to_left_to_spend` replay equals the snapshot's `left_to_spend`), Net Position from `/accounts/net-position` (equals checking posted − cards due), and the net worth live and snapshot figures being equal.
- [ ] **Step 4:** In `docs/architecture.md`:
  - Every Plan 2 provenance row points at its new backend function.
  - The "-> Plan 2" markers are gone.
  - Decisions (a), (b) and (c) are added to the decisions log.
  - The "Guards and parity tests" section names the frontend guard.

  Update `docs/technical-guide.md`.
- [ ] **Step 5:** Run the full backend suite, ruff, the import smoke test, `bunx vite build` and `bun test`.
- [ ] **Step 6:** Commit `test(calc): frontend money guard and Plan 2 parity`.
