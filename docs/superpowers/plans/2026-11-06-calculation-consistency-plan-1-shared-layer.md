# Calculation Consistency — Plan 1: Architecture Doc and Shared Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every core money quantity is calculated in exactly one backend place, and `docs/architecture.md` maps each number to that place.

**Architecture:**
- `backend/services/month_base.py` already models one month: income, bills, the Social Security boost, and one-offs.
- This plan adds four sibling modules: the real-spending rule, pending charges, the forecast walk policy, and the card-payment model.
- It merges the three cushions into one.
- It adds parity tests (every surface shows the same value) and a guard test (no money sums outside the shared layer).
- Behavior is kept except where the spec decided otherwise.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, SQLite, pytest (via uv). The frontend is not touched in this plan.

**Spec:** `docs/superpowers/specs/2026-11-06-calculation-consistency-design.md`.

**Follow-on plans, written after this one ships:**
- **Plan 2:** frontend money math moves to the backend, and Available to Spend is rebuilt.
- **Plan 3:** change history (snapshot store, diff, "what changed" view, email line).

## Global Constraints

- Public repo: synthetic figures only in code, tests, docs, and commit messages. Never copy numbers from the live DB or screenshots.
- Python only through `uv run --locked …`. Run tests as the pre-push hook does: `cd backend && uv run --locked python -m pytest` (plain `pytest` fails on `from tests.` imports). Coverage floor is 85 (`backend/.coveragerc`); never lower it.
- Lint: `uv run --locked ruff check .`. Import smoke test: `uv run --locked python -c "import backend.main, cli.budget"`.
- Commit directly to `main`. Do not push; pushing waits for Dan's OK.
- The live backend runs `uvicorn --reload` from this tree.
  - Before any schema or data migration, back up with `backup_database('data/budget.db', 'data/backups/budget-pre-<task>-<yyyymmdd>.db')`.
  - Keep migrations additive and nullable.
  - Data migrations that rewrite live values stay behind a flag until Dan approves.
- Any task that changes a visible number must, before its commit, run the before/after script (Task 1) on a `backup_database()` copy and paste the diff into the task report.
- Settled rules from the spec, verbatim:
  - Quarterly bills land whole in their due month.
  - Savings-funded one-offs net to zero.
  - Income excluded from the forecast is excluded from Leftover.
  - Refunds net against spending.
  - Transfers to savings and between own accounts are not spending.
  - A debit under an income category reduces income.
  - One cushion (default $1,000): amber below it, red below $0.
  - Overrides are keyed by the item's natural due date.
- `CALC_VERSION` is a hand-bumped integer. Bump it in any commit that changes a calculation's meaning, and add a changelog line to `docs/architecture.md`.

## Review Focus

1. **Refunds exceeding charges** in a category for the month: totals go negative for that category. They are not dropped and not clamped. *Task 2 test.*
2. **A Zelle/transfer description that is not an own-account transfer** (e.g. "Zelle payment to <person>") stays spending. Only own-account patterns are transfers. *Task 2 test.*
3. **Pending charge older than the freshness window** (hand-typed `pending_charges` with `pending_charges_updated_at` > 7 days old): ignored everywhere, the same way. *Task 3 test.*
4. **Statement or override amount on a bill whose due date is a Saturday:** the forecast posts it on the shifted Friday at the override amount. Month model, upcoming bills and forecast agree. *Task 4 test.*
5. **Card with no transaction feed** (balance-only, like a SimpleFIN Apple card): spend totals don't crash or count it as $0 spend twice. The card-payment model uses its balance fallback. *Task 5 test.*

---

### Task 1: Architecture doc, CALC_VERSION, before/after tool

**Files:**
- Create: `docs/architecture.md`
- Create: `backend/services/calc_version.py`
- Create: `scripts/calc_before_after.py`
- Modify: `CLAUDE.md` (add pointer), `README.md` and `docs/technical-guide.md` (link)
- Test: `backend/tests/test_calc_version.py`

**Interfaces:**
- Produces: `CALC_VERSION: int` (start at `1`) in `backend/services/calc_version.py`.
- Produces: `scripts/calc_before_after.py --db <copy.db> --user <id> --ref <git-ref>`. It prints a table of headline metrics computed by the current tree vs `<git-ref>` on the same DB copy:
  - leftover, left_to_spend, safety_margin;
  - next_month_minimum, lookahead_minimum;
  - each card's next payment;
  - spend total for the last full month.

  It uses `git worktree add --detach` into a temp dir, as done manually on 2026-11-06, and removes the worktree after.

- [ ] **Step 1:** Write `test_calc_version.py`:

```python
from pathlib import Path
from backend.services.calc_version import CALC_VERSION

def test_calc_version_is_positive_int():
    assert isinstance(CALC_VERSION, int) and CALC_VERSION >= 1

def test_architecture_changelog_has_current_version():
    doc = (Path(__file__).resolve().parents[2] / "docs" / "architecture.md").read_text()
    assert f"- v{CALC_VERSION}:" in doc
```

- [ ] **Step 2:** Run `cd backend && uv run --locked python -m pytest tests/test_calc_version.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3:** Create `calc_version.py` and `docs/architecture.md` with these sections:
  - **System overview:** bank sync → DB → shared layer → API → screens/email.
  - **Number provenance table:** one row per user-visible figure, with columns *figure | plain-English definition | function (file) | surfaces*. Fill it from the current code; the 2026-11-06 map in the spec's "Why" is the starting checklist.
  - **Shared primitives:** filled as Tasks 2–6 land; stub headings now.
  - **Decisions log:** copy the spec's "Decisions already made".
  - **Tracing a mismatch:** step by step, including `scripts/calc_before_after.py`.
  - **Rules for contributors and AI agents**, from the spec.
  - **Calculation changelog,** starting with `- v1: baseline after 2026-11-06 fixes.`

  Also add one line to `CLAUDE.md`: "Before touching any money calculation, read docs/architecture.md."
- [ ] **Step 4:** Write `scripts/calc_before_after.py` (stdlib + app imports, no new deps). Smoke-run it on a `backup_database()` copy against `HEAD` vs `HEAD`. Expected: every row's delta is 0.00.
- [ ] **Step 5:** Run tests, ruff, and the import check. All pass.
- [ ] **Step 6:** Commit `docs: architecture map, CALC_VERSION and before/after tool`.

### Task 2: Real-spending rule

**Files:**
- Create: `backend/services/real_spend.py`
- Modify (callers):
  - `backend/services/spending_helpers.py` (`merchant_totals`, `category_totals_for_range`, `filter_real_spend` delegate)
  - `backend/services/budget_calculator.py` (`compute_overview`)
  - `backend/services/summary_generator.py` (`_month_spending_by_category`)
  - `backend/routers/spending.py` (`/monthly`, `/transactions`, `/by-category`, `/by-card`, `/yearly-trends`, `/rolling-monthly`, `/sankey`)
  - `backend/services/spendable_pacer.py` (discretionary spend)
  - `backend/services/budget_snapshot.py` (`_card_spending_this_month`)
- Test: `backend/tests/test_real_spend.py`

**Interfaces:**
- Produces:

```python
SpendKind = Literal["spend", "income", "transfer", "card_payment"]

@dataclass(frozen=True)
class Verdict:
    kind: SpendKind
    amount: Decimal       # positive = spend/income magnitude; refunds are negative spend

def classify_checking(txn: models.Transaction, active_cards: list[models.CreditCard]) -> Verdict
def classify_card(txn: models.CreditCardTransaction) -> Verdict

@dataclass(frozen=True)
class SpendTotals:
    by_category: dict[int | None, Decimal]   # net of refunds; may be negative
    spend: Decimal
    income: Decimal

def spend_totals(db: Session, user_id: int, start: date, end: date) -> SpendTotals
```

- Rules, from the spec:
  - Card payments (`is_card_payment`, `match_payment_card`, `looks_like_card_autopay`) → `card_payment`.
  - Own-account transfers (`looks_like_internal_transfer`) → `transfer`.
  - Savings-category debits → `transfer`.
  - Card refunds → negative `spend`.
  - A debit under an income-type category → `income` with a negative amount.
  - Otherwise checking debits and card charges → `spend`, and checking credits → `income`.
  - Only actual (`is_actual`) checking rows count.

- [ ] **Step 1:** Write the tests, all on synthetic rows:
  - `test_card_autopay_is_card_payment`
  - `test_own_account_transfer_is_transfer_both_directions`
  - `test_zelle_to_person_is_spend` (Review Focus 2)
  - `test_card_refund_nets_spend`
  - `test_refunds_exceeding_charges_go_negative` (Review Focus 1: category total == −20.00 for a 30.00 refund on a 10.00 charge)
  - `test_income_category_debit_reduces_income`
  - `test_savings_category_debit_is_transfer`
  - `test_balance_only_card_has_no_rows_and_no_crash` (Review Focus 5)
  - `test_spend_totals_one_month`: card charges 400 + checking spend 50, autopay 1000 excluded, transfer 500 excluded, paycheck 3000. Expect spend == 450 and income == 3000.
- [ ] **Step 2:** Run `uv run --locked python -m pytest tests/test_real_spend.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `real_spend.py` and route every listed caller through `classify_*` / `spend_totals`. Delete the per-caller filtering it replaces. `filter_real_spend` becomes a thin wrapper or is removed if unused.
- [ ] **Step 4:** Add `test_all_spend_surfaces_agree`. On one fixture month, assert equal totals from:
  - `spend_totals`;
  - `category_totals_for_range`;
  - `compute_overview` actuals;
  - `_month_spending_by_category`;
  - the `/spending/by-category` and `/spending/sankey` endpoints.
- [ ] **Step 5:** Run the full suite. Update only assertions that encoded a superseded rule, and list each one with old→new in the report.
- [ ] **Step 6:** Run `scripts/calc_before_after.py` on a DB copy. Paste the diff in the report. Bump `CALC_VERSION` to 2 with the changelog line "v2: one real-spending rule; refunds net everywhere". Fill the "Real-spending rule" section in `docs/architecture.md`.
- [ ] **Step 7:** Commit `feat(calc): one real-spending rule for every spending and income total`.

### Task 3: Pending charges accessor

**Files:**
- Create: `backend/services/pending.py`
- Modify:
  - `backend/services/forecast_engine.py` (`_fresh_pending_charges` moves here; cycle estimate ~`fe:1087` and second hop use it)
  - `backend/services/budget_snapshot.py` (Left to Spend uses it)
  - `backend/routers/spending.py` (`available_to_spend`)
- Test: `backend/tests/test_pending_accessor.py`

**Interfaces:**
- Produces:
  - `PENDING_FRESH_DAYS = 7`
  - `card_pending(card: models.CreditCard, today: date) -> Decimal`: the sum of `CardPendingTransaction` rows when the card has any sync rows; else `pending_charges` only if `pending_charges_updated_at` is within `PENDING_FRESH_DAYS`; else 0.
  - `checking_pending_debits(db, account: models.Account, today: date, *, card_payments_only: bool) -> list[models.AccountPendingTransaction]`
  - `checking_balance_with_pending(db, account, today) -> Decimal`: posted balance minus **all** pending debits. Plan 2 points the sidebar here.

- [ ] **Step 1:** Write the tests:
  - `test_stale_hand_typed_pending_ignored` (Review Focus 3: updated 8 days ago → 0)
  - `test_fresh_hand_typed_pending_used`
  - `test_synced_rows_win_over_field`
  - `test_checking_pending_card_only_filter`
  - `test_balance_with_pending_subtracts_all_debits`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement the accessor. Replace every direct read of `card.pending_charges` in `backend/` with `card_pending(...)`. Enforce with a grep-based assertion in Task 7's guard test.
- [ ] **Step 4:** Run the full suite, then run before/after on a DB copy. Bump `CALC_VERSION` (v3: one pending freshness rule) and update the docs.
- [ ] **Step 5:** Commit `feat(calc): one pending-charges accessor with one freshness rule`.

### Task 4: Forecast walk policy and weekend override rule

**Files:**
- Create: `backend/services/forecast_walk.py`
- Modify (`build_forecast` callers):
  - `backend/routers/forecast.py` (`/`, `/risk`, `/multi-year`, `/monthly-summary`)
  - `backend/services/budget_snapshot.py` (`_lookahead_window`)
  - `backend/services/wish_plan.py`
  - `backend/services/summary_generator.py` (weekly digest risk)
  - `backend/services/upcoming_bills.py`
  - `backend/services/forecast_baseline.py`
- Modify: `backend/services/forecast_engine.py`
  - the override lookup at ~`fe:1744` uses the natural due date;
  - the bridges at ~`fe:1504/1546` pass `include_unbilled_card_bills` through.
- Test: `backend/tests/test_forecast_walk_policy.py`

**Interfaces:**
- Produces:

```python
WalkPurpose = Literal["display", "safety"]   # display: include_unbilled_card_bills=True; safety: False
WALK_LOOKBACK_DAYS = 45

def standard_walk(db, user_id: int, account_id: int, as_of: date, end: date,
                  purpose: WalkPurpose = "display", **extra) -> list[ForecastEntry]
```

  It starts at `as_of - WALK_LOOKBACK_DAYS`. Callers that need history before that (Forecast tab ranges, `/multi-year`, `/monthly-summary`) build their own range. They must produce identical balances for every day ≥ `as_of`, and the parity test enforces it. `**extra` passes `overrides`/`proposal` through.

- [ ] **Step 1:** Write the tests:
  - `test_tab_and_standard_walk_agree_from_today`: a Jan 1 walk vs `standard_walk` hold equal balances for every day ≥ as_of, on a fixture with an old unmatched projection.
  - `test_risk_and_display_lows_agree`.
  - `test_bridge_keeps_unbilled_flag`.
  - `test_weekend_override_applies_on_shifted_day` (Review Focus 4): a bill due Saturday with an override of 123.45 posts on Friday at 123.45 in the forecast; `build_month_base` and `upcoming_bills` show 123.45 too.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement `standard_walk`. Migrate every listed caller. Any caller that keeps a custom walk gets a one-line comment saying why. Fix the override lookup and the bridge flag.
- [ ] **Step 4:** Run the full suite and before/after. Bump `CALC_VERSION` (v4: one walk policy; weekend overrides) and update the docs.
- [ ] **Step 5:** Commit `feat(calc): standard forecast walk and natural-date overrides`.

### Task 5: Card-payment model

**Files:**
- Create: `backend/services/card_payment_model.py`
- Modify:
  - `backend/services/forecast_engine.py`: the locked-payoff, cycle-estimate, second-hop, flat-estimate and subscription-fallback blocks (~`fe:1052-1420`) move out. `build_forecast` calls the model.
  - `backend/services/budget_snapshot.py`:
    - `_cc_basis_note` reads `CardPayment.basis`;
    - `cc_budget_total` adds a scenario's proposed card-bill occurrences (the deferred gap from 2026-11-06).
- Test: `backend/tests/test_card_payment_model.py`

**Interfaces:**
- Consumes: `card_pending` (Task 3), `build_month_base` (existing).
- Produces:

```python
@dataclass(frozen=True)
class CardPayment:
    card_id: int
    due: date
    amount: Decimal
    locked: bool
    basis: dict          # same keys as today's ForecastTransaction.basis

def card_payments(db, user: models.User, account: models.Account, start: date, end: date, *,
                  include_unbilled_card_bills: bool, proposal=None, today: date | None = None) -> list[CardPayment]
```

- [ ] **Step 1:** Write the golden test `test_forecast_unchanged_by_extraction`. Take three existing fixture scenarios (locked statement, second hop, flat estimate, balance-only card per Review Focus 5) and snapshot `build_forecast` output (date, name, amount, basis) **before** the refactor into the test as literal expectations.
- [ ] **Step 2:** Write `test_scenario_proposed_card_bill_in_cc_budget`. A proposed weekly $50 card bill from Nov 6 reduces Safety Margin by the remaining occurrences ($200 in the fixture month).
- [ ] **Step 3:** Run both. The golden test PASSES (it was captured from current code). The scenario test FAILS.
- [ ] **Step 4:** Extract the model. The golden test must still pass unchanged. Fix the scenario gap.
- [ ] **Step 5:** Run the full suite and before/after (only the scenario path should differ). Bump `CALC_VERSION` (v5) and update the docs.
- [ ] **Step 6:** Commit `refactor(calc): card-payment model shared by forecast and snapshot`.

### Task 6: One cushion

**Files:**
- Modify:
  - `backend/services/budget_snapshot.py`
  - `backend/services/wish_plan.py` (`effective_cushion` → delegate)
  - `backend/routers/forecast.py` (`/risk` threshold and status)
  - `backend/database.py` (data migration, flagged)
  - `backend/models.py` comments only
- Create: `backend/services/cushion.py`
- Test: `backend/tests/test_single_cushion.py`

**Interfaces:**
- Produces:
  - `DEFAULT_CUSHION = Decimal("1000")`
  - `cushion_for(user: models.User) -> Decimal`: `user.safety_cushion`, else the default.
  - `cushion_status(value: Decimal, cushion: Decimal) -> Literal["ok", "warning", "danger"]`: `danger` if < 0; `warning` if < cushion; else `ok`. Exactly at the cushion → ok.
- `/risk` returns `status` from `cushion_status`. `ForecastRisk.threshold` becomes the cushion.
- Migration `migrate_cushions(db, apply: bool)`:
  - For each user with `safety_cushion IS NULL`, copy the first non-null, non-zero value of `wish_settings.cushion`, then the account `low_balance_threshold` of their primary checking account.
  - Log what it would change.
  - Runs at startup only when the env flag `CUSHION_MIGRATION_APPLY=1` is set. Dan approves before it's set.
  - The `low_balance_threshold` and `wish_settings.cushion` columns stay (additive rule) but are no longer read.

- [ ] **Step 1:** Write the tests:
  - `test_status_boundaries` (−0.01 danger, 0 warning with cushion 1000, 999.99 warning, 1000 ok)
  - `test_risk_banner_uses_cushion`
  - `test_wish_uses_cushion`
  - `test_migration_dry_run_changes_nothing`
  - `test_migration_apply_copies_wish_then_account_value`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Back up the DB first (Global Constraints) even though no schema changes, because the migration code ships in this commit.
- [ ] **Step 4:** Run the full suite. Run before/after; expected: the risk banner status changes only. Paste the dry-run log of `migrate_cushions(apply=False)` from a DB copy into the report. Bump `CALC_VERSION` (v6) and update the docs.
- [ ] **Step 5:** Commit `feat(calc): one cushion for safety, risk and wish list`.

### Task 7: Parity and guard tests, docs final pass

**Files:**
- Create: `backend/tests/test_parity_headline.py`, `backend/tests/test_calc_guard.py`
- Modify: `docs/architecture.md` (provenance table final), `docs/technical-guide.md`

**Interfaces:** Consumes everything above.

- [ ] **Step 1:** Write `test_parity_headline.py`, with one fixture user and month covering a paycheck past the Social Security base, a weekly card bill, a quarterly bill, a funded one-off, a refund and a pending charge:
  - Leftover is equal across `build_month_base(...).left_over`, `/recurring/month-summary` `left_over`, and the snapshot `leftover`.
  - The lowest point is equal across the snapshot `lookahead_minimum` and the minimum from the `/forecast` endpoint over the same window, with the floor mask applied.
  - Each card's next payment is equal across the forecast line, the snapshot explain, and `card_payments`.
  - Last month's spend is equal across Month in Review, Sankey, the Budget overview and the weekly digest.
- [ ] **Step 2:** Write `test_calc_guard.py`, an AST scan of `backend/routers/*.py` and `backend/services/*.py`. Two checks:
  - Fail on `sum(` or `+=` / `-=` over attributes named `amount`, `pending_charges`, `balance_due` or `current_balance`, outside an allowlist of the shared-layer modules (`month_base`, `real_spend`, `pending`, `forecast_walk`, `card_payment_model`, `forecast_engine`, `cushion`, `tax_service`, `bank_sync_service`, `plaid_sync_service`, `import_service`, `planned_auto_settle`).
  - Fail on any read of `.pending_charges` outside `pending.py` and the sync services.

  The allowlist lives at the top of the test with a comment: "Adding a module here needs a line in docs/architecture.md."
- [ ] **Step 3:** Run both. Fix any violation by routing it through the shared layer, not by allowlisting. If a violation is purely presentational, allowlist that line with a reason and note it in the report.
- [ ] **Step 4:** Finish `docs/architecture.md`. Every provenance row must point at a shared-layer function, and the changelog must run v1…v6.
- [ ] **Step 5:** Run the full suite, ruff and the import check.
- [ ] **Step 6:** Commit `test(calc): parity across surfaces and a guard against duplicate money math`.
