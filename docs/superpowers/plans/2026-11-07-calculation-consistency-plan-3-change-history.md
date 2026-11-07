# Calculation Consistency Plan 3: Change History ("what changed and why") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every headline figure at each bank sync, each daily email, on demand and on a `CALC_VERSION` change, then explain each change in plain language: in the app (a "what changed" control on every headline figure) and in the daily email (one "since last email" line per figure).

**Architecture:** Two new tables (`metric_snapshots`, `metric_readings`) hold each snapshot's figures, their existing `Explanation` trees, and a small "sources" record (pending rows plus high-water transaction ids). `services/metric_history.py` collects and records; `services/metric_diff.py` diffs two readings (explain-tree lines plus source events) into plain-language text. A `/history` router serves the app; `summary_generator` adds the email lines. Nothing changes what any figure means, so `CALC_VERSION` stays 12.

**Tech Stack:** FastAPI, SQLAlchemy 2 (SQLite), pydantic v2, pytest via `uv run --locked`; React + TypeScript, TanStack Query, Radix Dialog, lucide icons, `bun test`.

**Spec:** `docs/superpowers/specs/2026-11-06-calculation-consistency-design.md` (section "Change history"). Read `docs/architecture.md` first (project rule).

## Global Constraints

- Public repo: no real figures in code, tests, docs or commit messages. Synthetic numbers only.
- Python via `uv run --locked`; frontend via `bun`/`bunx` only. Never npm/pip.
- Commits go straight to `main`. Do not push; pushing waits for Dan's OK.
- The live backend runs `uvicorn --reload`: a model change creates tables in the live DB the moment it is saved. **Before Task 1 touches `models.py`**, take a copy: `uv run --locked python -c "from backend.services.db_backup import backup_database; backup_database('data/budget.db', '<path outside repo>/pre-plan3.db')"`. Never `cp` the DB.
- Migrations additive only: two new tables via `Base.metadata.create_all`; no `ALTER TABLE`, no change to existing tables.
- Snapshots stay in the local SQLite DB. Retention: 13 months (`RETENTION_DAYS = 396`), pruned on every record.
- `CALC_VERSION` stays 12: no task changes a figure. Task 1's new `next_month_minimum` explain is additive.
- Anti-goal: history text is plain language ("New pending Visa charge: Example Insurance Co. $250.00"), never raw rows, ids or field names.
- Money in UI text uses the app's shape: `$1,234.56`, negative with U+2212 `−`. Signed deltas: `+$50.00` / `−$400.00`.
- The frontend does no money math (`frontend/tests/moneyGuard.test.ts`); deltas come from the backend.
- Phone width ≈400px must work for the app view; the email line must fit a phone (≤ 120 characters).
- Gate before calling any task done: `uv run --locked ruff check .`, `uv run --locked pytest backend/tests -q`, and for frontend tasks `cd frontend && bun test && bunx vite build`. After the final task: `graphify update .`.

## Review Focus

1. **A pending charge that posts between two snapshots** (pending row gone, posted row with the same card and amount appears). Expect: not reported as new spending or a dropped charge; if the figure didn't move, no change entry at all. Test: Task 3 `test_pending_that_posted_is_not_a_cause`.
2. **No previous snapshot** (first sync after deploy, first email ever, a new card). Expect: no fabricated delta; the app lists no change, the email shows no "since" line. Tests: Task 4 `test_first_reading_has_no_change`, Task 5 `test_no_since_line_without_a_previous_email`.
3. **Month boundary** (Leftover resets on the 1st). Expect: one "new month (Dec)" cause, not a list of every bill that appeared. Test: Task 3 `test_new_month_is_one_cause`.
4. **Recording fails** (no primary checking account, a calculator raises). Expect: the sync or email still completes; nothing half-written; error logged. Tests: Task 2 `test_record_for_users_never_raises`, `test_user_without_checking_records_nothing`.
5. **Hide balances on** while the history dialog is open. Expect: every amount, including the `$` figures inside summary text, is masked. Test: Task 6 `maskMoneyText` tests.

---

### Task 1: Snapshot tables and the headline-metric collector

**Files:**
- Modify: `backend/models.py` (two new classes, after `MonthlyForecastSnapshot`)
- Modify: `backend/services/budget_snapshot.py` (add `explain["next_month_minimum"]`)
- Create: `backend/services/metric_history.py`
- Test: `backend/tests/test_metric_history.py`

**Interfaces:**
- Produces:
  - `models.MetricSnapshot`: `__tablename__ = "metric_snapshots"`; `id`; `user_id` (FK users.id, indexed); `taken_at: DateTime` (naive UTC, not null); `trigger: String(16)` (`"sync" | "email" | "manual" | "calc_change"`); `calc_version: Integer`; `as_of: Date`; `sources_json: Text`. Index on `(user_id, taken_at)`.
  - `models.MetricReading`: `__tablename__ = "metric_readings"`; `id`; `snapshot_id` (FK metric_snapshots.id, `ondelete="CASCADE"`, indexed); `metric_key: String(64)`; `label: String(128)`; `value: Numeric(14, 2)`; `explain_json: Text` (`Explanation.model_dump_json()`). Relationship `MetricSnapshot.readings`.
  - `metric_history.MetricReadingData` (frozen dataclass): `key: str`, `label: str`, `value: Decimal`, `explain: schemas.Explanation`.
  - `metric_history.collect_headline_metrics(db, user, as_of: date) -> list[MetricReadingData]` — `[]` when the user has no primary checking.
  - `metric_history.collect_sources(db, user, as_of: date) -> dict` — JSON-safe (amounts as strings).
  - `metric_history.METRIC_KEYS: tuple[str, ...]` — the fixed keys below, card keys excluded.

- [ ] **Step 1: Back up the live DB** (command in Global Constraints). Expected: the copy exists and is non-empty.

- [ ] **Step 2: Write the failing tests** in `backend/tests/test_metric_history.py`, reusing `_headline_fixture`, `_pin_today` and `TODAY` from `test_parity_headline.py` (import them):

```python
def test_collect_returns_every_headline_in_order(db_session, monkeypatch):
    # keys, in order: leftover, left_to_spend, spendable_week, spendable_today,
    # safety_margin, safety_margin_week, safety_margin_today, next_month_minimum,
    # lookahead_minimum, available_to_spend, checking_balance,
    # then card_payment:<id> per active card ordered by card id
    ...
def test_every_reading_replays_to_its_value(db_session, monkeypatch):
    for r in readings: assert explain.replay(r.explain) == r.value
def test_readings_equal_their_surfaces(db_session, monkeypatch):
    # leftover == build_month_summary(...).left_over == snap.leftover
    # left_to_spend/safety_margin/lookahead_minimum/next_month_minimum == snap fields
    # available_to_spend == available_to_spend(db, user, TODAY).available
    # checking_balance == checking_balance_with_pending(db, checking, TODAY)
    # card_payment:<visa id> == D("400.00"), card_payment:<mc id> == D("250.00")
def test_card_payment_reading_names_due_date_and_basis(db_session, monkeypatch):
    # rows[0].label == "Next payment, due Nov 5"; rows[0].note == _cc_basis_note(payment)
def test_inactive_card_has_no_reading(db_session, monkeypatch): ...
def test_no_primary_checking_collects_nothing(db_session): ...
def test_sources_list_pending_rows_and_high_water_ids(db_session, monkeypatch):
    # add a CardPendingTransaction (merchant "Example Insurance Co.", 250.00) on Test Visa
    # sources["card_pending"] == [{"card_id": visa.id, "card": "Test Visa",
    #   "external_id": ..., "merchant": "Example Insurance Co.", "amount": "250.00"}]
    # sources["max_txn_id"] / ["max_card_txn_id"] == current max ids for the user (0 when none)
    # sources["checking_pending"] == [] (no live Plaid link)
```

- [ ] **Step 3: Run them.** `uv run --locked pytest backend/tests/test_metric_history.py -q` → FAIL (`ModuleNotFoundError: backend.services.metric_history`).

- [ ] **Step 4: Add the two models**, then `explain["next_month_minimum"]` in `compute_budget_snapshot`: `ExplainBuilder(f"Lowest point in {next_month_label}")`, `.start("Lowest projected checking balance", next_month_min, note=<static, no figures: "Lowest projected checking balance next month, on Mon D. Excludes the already-scheduled card payoff.">, informational_children=_cc_line_children(display_window.days, as_of, next_month_min_date))`, `.build(next_month_min)`.

- [ ] **Step 5: Implement `metric_history.collect_headline_metrics`.** One `compute_budget_snapshot(db, user, account.id, as_of)` call; labels and sources:

| key | label | value / explain |
|---|---|---|
| `leftover` | Leftover | `build_month_summary(db, user.id, y, m)`: `.left_over` / `.explain["left_over"]` |
| `left_to_spend` | Left to Spend | snapshot field / `snap.explain["left_to_spend"]` |
| `spendable_week` | Spendable this week | `left_to_spend_weekly` / `explain["spendable_week"]` |
| `spendable_today` | Spendable today | `spendable_today` / `explain["spendable_today"]` |
| `safety_margin`, `safety_margin_week`, `safety_margin_today` | Safety Margin, Safety Margin (this week), Safety Margin today | matching fields / explain keys |
| `next_month_minimum` | Lowest next month | field / new explain key |
| `lookahead_minimum` | 3-month low | field / explain key |
| `available_to_spend` | Available to Spend | `available_to_spend(db, user, as_of)`: `.available` / `.explain` |
| `checking_balance` | Checking balance | `checking_balance_with_pending`; explain `start("Posted balance", account.current_balance)` then, when pending is non-zero, `add("Pending", after − posted, children=[one ExplainChild per checking_pending_rows row: label = description, amount = row amount])` |
| `card_payment:<card_id>` | `"{card.name} next payment"` | first `card_payments(db, user, account, as_of, as_of + timedelta(days=75), include_unbilled_card_bills=True, today=as_of)` for that card by `due`; amount `abs(p.amount)`; explain `start(f"Next payment, due {p.due:%b %-d}", amount, note=_cc_basis_note(p))`. No payment in the window: value 0, `start("No payment due in the next 75 days", 0)` |

`collect_sources` reads `CardPendingTransaction` for active cards, `checking_pending_rows` for the primary checking, and `max(id)` of `Transaction`/`CreditCardTransaction` for the user (`is_actual` rows only on Transaction). If `test_calc_guard.py` flags either new module, add it to `SHARED_LAYER` with a one-line reason and list it in architecture.md's shared-layer module list.

- [ ] **Step 6: Run the tests.** Same command → PASS. Then the full suite → PASS (parity and explain tests unaffected).

- [ ] **Step 7: Commit.** `git add backend/models.py backend/services/budget_snapshot.py backend/services/metric_history.py backend/tests/test_metric_history.py` · `git commit -m "feat(history): snapshot tables and headline-metric collector"`

---

### Task 2: Recording, triggers, dedup and retention

**Files:**
- Modify: `backend/services/metric_history.py`
- Modify: `backend/services/bank_sync_service.py` (`sync_all`), `backend/routers/bank_sync.py` (sync-now and Plaid first-import), `backend/main.py` (`_scheduler_sweep`)
- Modify: `docs/PRIVACY.md` ("What's stored, and where"; "Deleting your data")
- Test: `backend/tests/test_metric_history.py`

**Interfaces:**
- Consumes: Task 1's collector and models.
- Produces:
  - `record_snapshot(db, user, trigger: str, *, as_of: date | None = None, now: datetime | None = None, readings: list[MetricReadingData] | None = None) -> models.MetricSnapshot | None` — commits; returns `None` when nothing was stored.
  - `record_for_users(db, user_ids: Iterable[int], trigger: str) -> None` — never raises; logs and rolls back per user.
  - `record_if_calc_changed(db) -> None` — per active user whose latest snapshot has `calc_version != CALC_VERSION`, record with trigger `"calc_change"`. A user with no snapshots is skipped.
  - `prune_history(db, now: datetime) -> int` — deletes snapshots (and their readings, explicitly) with `taken_at < now − timedelta(days=RETENTION_DAYS)`; returns the count.
  - `latest_snapshot(db, user_id, trigger: str | None = None) -> models.MetricSnapshot | None`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_record_stores_every_reading(...)        # one snapshot, len(readings) == len(collect(...)), calc_version == CALC_VERSION
def test_identical_sync_is_not_stored_twice(...) # second record_snapshot(trigger="sync") returns None; count stays 1
def test_email_is_always_stored(...)             # identical data, trigger="email" -> stored
def test_changed_pending_is_stored(...)          # add a pending row, then sync -> second snapshot
def test_prune_keeps_thirteen_months(...)        # snapshots at now-397d and now-395d -> only the latter remains, its readings too
def test_record_for_users_never_raises(...)      # monkeypatch collect_headline_metrics to raise -> no exception, no rows
def test_user_without_checking_records_nothing(...)
def test_calc_change_records_once(...)           # latest at calc_version 11 -> one "calc_change"; second call stores nothing
def test_sync_all_records_after_settling(...)    # monkeypatch record_for_users; sync_all with no connections -> called with trigger "sync" after settle_after_sync
```

- [ ] **Step 2: Run them** → FAIL (`record_snapshot` not defined).

- [ ] **Step 3: Implement.** `now` defaults to `datetime.now(timezone.utc).replace(tzinfo=None)`. Dedup applies to `sync`/`manual`/`calc_change` only: skip when the latest snapshot's `calc_version`, `sources_json` and its `(metric_key, value, explain_json)` set all equal the new ones. Call `prune_history` after each stored snapshot. Wire `record_for_users(db, ids, "sync")` immediately after each of the three `settle_after_sync(...)` calls, and `record_if_calc_changed(db)` in `_scheduler_sweep` inside its own `try/except Exception` with `logger.exception` (a failure must not stop the sweep).

- [ ] **Step 4: Update `docs/PRIVACY.md`:** what's stored (each headline figure, its calculation steps, the names and amounts of pending charges at that moment, at each sync and email; 13 months; never leaves the machine), and how to delete it (Settings → "Clear change history", or deleting the database).

- [ ] **Step 5: Run tests** → PASS; full suite → PASS.

- [ ] **Step 6: Commit.** `git commit -m "feat(history): record headline figures at each sync, prune after 13 months"`

---

### Task 3: Diffing and plain-language causes

**Files:**
- Create: `backend/services/metric_diff.py`
- Modify: `backend/services/calc_version.py` (add `CALC_CHANGELOG`)
- Modify: `backend/tests/test_calc_version.py`
- Test: `backend/tests/test_metric_diff.py`

**Interfaces:**
- Consumes: `models.MetricSnapshot`/`MetricReading` (Task 1).
- Produces:
  - `calc_version.CALC_CHANGELOG: dict[int, str]` — v1..v12, text copied verbatim from architecture.md's "Calculation changelog".
  - `metric_diff.LineChange` (frozen dataclass): `label: str`, `old: Decimal | None`, `new: Decimal | None` (None = absent).
  - `metric_diff.diff_explanations(old: schemas.Explanation, new: schemas.Explanation) -> list[LineChange]`
  - `metric_diff.Cause` (frozen dataclass): `text: str`, `amount: Decimal | None`.
  - `metric_diff.explain_change(db, user_id: int, metric_key: str, prev: models.MetricReading, cur: models.MetricReading) -> list[Cause]`
  - `metric_diff.summarize(label: str, delta: Decimal, since_text: str, causes: list[Cause], *, max_items: int) -> str`
  - `metric_diff.signed_money(amount: Decimal) -> str` → `"+$50.00"` / `"−$400.00"`

Rules (the diff decisions the tests pin):
- **Line identity:** a row by `label`; a child or informational child by `(row label, child label)`. Report only the deepest level that differs: when a row's children explain its change, list the children, not the row. Skip `result` rows and `divide` rows. Ignore changes under $0.01.
- **New month:** when `prev.snapshot.as_of` and `cur.snapshot.as_of` fall in different months, the only line cause is `f"new month ({cur_as_of:%b})"`.
- **Calculation change:** when `calc_version` differs, the first cause is `f"calculation changed (v{old} → v{new}: {CALC_CHANGELOG[new]})"`.
- **Source events** between the two snapshots, only for metrics they feed (`SOURCE_METRICS` below):
  - new pending card rows (by `external_id`), minus any matched by a new posted card row with the same card and amount (that charge posted; drop both);
  - pending rows gone and not matched (dropped);
  - new posted rows: `id` in `(prev.max, cur.max]` for the user, still present.
  - Grouped per card/account: `"new pending Visa charges: Example Insurance Co. $250.00, Grocery Store $100.00"` (singular `charge` for one), `"new Visa transactions: …"`, `"pending Visa charges dropped: …"`; checking rows use the account name. Each item is `"{merchant or description} {money}"`.
- `SOURCE_METRICS`: card pending/posted → `left_to_spend`, `spendable_*`, `safety_margin*`, `next_month_minimum`, `lookahead_minimum`, `available_to_spend`, and that card's `card_payment:<id>` only; checking posted → `available_to_spend`, `checking_balance`, `safety_margin*`, both lows; checking pending → `checking_balance`, `safety_margin*`, both lows.
- Order: calculation change, source groups, then line changes by descending |delta|. Line text: `f"{label} {signed_money(new-old)}"`; appeared `f"{label} added ({money})"`; gone `f"{label} removed ({money})"`. No causes at all → `"inputs changed"`.
- `summarize`: `f"{label} {signed_money(delta)} {since_text}: {causes joined by '; '}"`, keeping the first `max_items` items across groups and appending `" and N more"`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_spec_example_reads_exactly(...):
    # prev: no pending. cur: three new pending Visa rows (Example Insurance Co. 250.00,
    # Grocery Store 100.00, Online Shop 50.00), Safety Margin down 400.00
    assert summarize("Safety Margin", D("-400.00"), "since 7:00 AM", causes, max_items=3) == (
        "Safety Margin −$400.00 since 7:00 AM: new pending Visa charges: "
        "Example Insurance Co. $250.00, Grocery Store $100.00, Online Shop $50.00")
def test_pending_that_posted_is_not_a_cause(...)
def test_new_month_is_one_cause(...)
def test_calc_change_is_named(...)                 # "calculation changed (v11 → v12: Available to Spend counts balance-only cards like Left to Spend)"
def test_child_lines_replace_their_row(...)        # a bill override changes "Recurring bills this month" child -> one child line, no row line
def test_card_source_only_feeds_its_own_card(...)  # Visa pending is not a cause on card_payment:<mastercard>
def test_causes_never_show_ids_or_field_names(...) # no "external_id", "card_id", digits-only ids in any Cause.text
def test_summarize_caps_items(...)                 # max_items=2 -> "..., Grocery Store $100.00 and 1 more"
```
In `test_calc_version.py`: `test_changelog_dict_matches_doc` — every `- vN: text` line in architecture.md equals `CALC_CHANGELOG[N]`, and `max(CALC_CHANGELOG) == CALC_VERSION`.

- [ ] **Step 2: Run them** → FAIL (module missing).

- [ ] **Step 3: Implement `metric_diff.py` and `CALC_CHANGELOG`.** Money formatting reuses `_money` in `budget_snapshot.py` if it produces `$1,234.56`; otherwise add the helper here.

- [ ] **Step 4: Run tests** → PASS; full suite → PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(history): explain a figure's change in plain language"`

---

### Task 4: History API

**Files:**
- Create: `backend/routers/history.py`
- Modify: `backend/main.py` (`app.include_router(history.router)`), `backend/schemas.py`
- Modify: `docs/architecture.md` (provenance row "Change history"; new section "How the change history works", placed before "Tracing a mismatch"; step "0. Open the figure's what-changed view" in "Tracing a mismatch")
- Test: `backend/tests/test_history_api.py`, `backend/tests/test_security_regressions.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces (schemas):
  - `HistoryCause(text: str, amount: Optional[Decimal])`
  - `MetricChangeOut(taken_at: datetime, previous_taken_at: datetime, trigger: str, old_value: Decimal, new_value: Decimal, delta: Decimal, summary: str, causes: list[HistoryCause], calc_changed: bool)`
  - `MetricHistoryOut(metric_key: str, label: str, current_value: Decimal, changes: list[MetricChangeOut])`
- Produces (service, in `metric_diff.py`): `changes_for(db, user_id: int, metric_key: str, limit: int) -> list[schemas.MetricChangeOut]` — consecutive readings of that key, newest first, only pairs whose value moved by ≥ $0.01. `summary` uses `max_items=3` and `since_text = "since " + local time of the previous snapshot` (`"%-I:%M %p"` when the same local day, else `"%a %-I:%M %p"`).
- Produces (routes, `APIRouter(prefix="/history", tags=["history"])`, all `Depends(get_current_user)`):
  - `GET /history/{metric_key}?limit=30` → `MetricHistoryOut`; `limit` 1–200; `metric_key` must match `^[a-z_]{1,40}(:\d{1,9})?$` else 422; 404 when the user has no reading for the key.
  - `POST /history/snapshot` → `{"recorded": bool}` (trigger `"manual"`).
  - `DELETE /history` → `{"deleted": int}` (the caller's snapshots only).

- [ ] **Step 1: Write the failing tests:** `test_history_lists_changes_newest_first`, `test_unchanged_readings_are_not_changes`, `test_first_reading_has_no_change` (`changes_for` over a single reading returns `[]`), `test_unknown_key_is_404`, `test_bad_key_is_422` (`"../x"`, `"leftover;drop"`), `test_manual_snapshot_records`, `test_delete_clears_only_my_history`. In `test_security_regressions.py`: `test_history_is_scoped_to_the_caller` — user B requesting user A's `card_payment:<A's card id>` gets 404 and A's rows survive B's `DELETE`.

- [ ] **Step 2: Run them** → FAIL (404 on `/history/...` route missing).

- [ ] **Step 3: Implement the router, schemas and `changes_for`.** Write the architecture.md section: what is recorded and when (four triggers, dedup, 13 months), the two tables, how a change is explained (line diff + source events + calc version), and that `CALC_CHANGELOG` must gain a line with every `CALC_VERSION` bump.

- [ ] **Step 4: Run tests** → PASS; full suite → PASS.

- [ ] **Step 5: Commit.** `git commit -m "feat(history): history API and architecture notes"`

---

### Task 5: "Since last email" lines

**Files:**
- Modify: `backend/services/summary_generator.py` (`generate_daily_summary`), `backend/main.py` (`_send_daily_summaries_locked`), `backend/services/metric_diff.py`
- Test: `backend/tests/test_email_since_lines.py`

**Interfaces:**
- Consumes: `collect_headline_metrics`, `record_snapshot(..., readings=...)`, `latest_snapshot(db, user_id, "email")`, `explain_change`, `summarize`.
- Produces:
  - `metric_diff.since_last_email(db, user, readings: list[MetricReadingData]) -> dict[str, str]` — metric key → short line, only for figures whose value moved since the last `"email"` snapshot; `{}` when there is none. Line: `summarize(label, delta, "since last email", causes, max_items=2)` without the leading label (the line sits under it), truncated at a word boundary to ≤ 120 characters.
  - `generate_daily_summary(db, user, *, weekly_digest=None, since_lines: dict[str, str] | None = None)`.

- [ ] **Step 1: Write the failing tests:** `test_since_line_under_a_moved_figure` (html and text both contain `"−$400.00 since last email: new pending Test Visa charges: …"` under Safety Margin (this week)), `test_no_line_for_an_unmoved_figure`, `test_no_since_line_without_a_previous_email`, `test_line_fits_a_phone` (≤ 120 chars with 6 pending rows), `test_email_snapshot_saved_only_after_a_send` (monkeypatch `send_email_via` to fail for every recipient → no `"email"` snapshot; succeed → one).

- [ ] **Step 2: Run them** → FAIL.

- [ ] **Step 3: Implement.** In `_send_daily_summaries_locked`, per user: `readings = collect_headline_metrics(db, user, date.today())`, `since = since_last_email(db, user, readings)`, pass `since_lines=since`, and after the recipient loop, if any send returned `ok`, `record_snapshot(db, user, "email", readings=readings)`. In the email, render the line under each headline it has a key for (Safety Margin week, Spendable this week, each lowest-balance row by its key, checking balance rows), in the HTML as muted 11px text with `word-break:break-word`, and indented in the text body. Escape with `html_lib.escape`.

- [ ] **Step 4: Run tests** → PASS; full suite → PASS. Then render one email from the `pre-plan3.db` copy (never the live DB) and check at 400px that the lines wrap cleanly. Use the Interceptor skill for the check; it must be no wider than the existing rows.

- [ ] **Step 5: Commit.** `git commit -m "feat(history): daily email says what changed since the last one"`

---

### Task 6: "What changed" control in the app

**Files:**
- Create: `frontend/src/components/WhatChanged.tsx`, `frontend/src/lib/maskMoney.ts`, `frontend/tests/maskMoney.test.ts`
- Modify: `frontend/src/api/index.ts` (`historyApi`), `frontend/src/components/HowCalculated.tsx` (use `maskMoneyText` in place of its local `maskNote`), `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/RecurringSummaryStrip.tsx`, `frontend/src/pages/CreditCards.tsx`, `frontend/src/pages/Settings.tsx`

**Interfaces:**
- Consumes: Task 4 routes.
- Produces:
  - `historyApi = { changes(key: string, limit?: number): Promise<MetricHistory>, snapshot(): Promise<{recorded: boolean}>, clear(): Promise<{deleted: number}> }`
  - `maskMoneyText(hidden: boolean, text: string): string` — the regex HowCalculated already uses (`/[−-]?\$[\d,]+(?:\.\d{1,2})?/g` → `"••••"`), plus a leading `+`.
  - `<WhatChanged metrics={{ key: string; title: string }[]} />` — a `History` (lucide, size 12) button beside the ⓘ, `aria-label="What changed in {title}?"`. Opens a Radix Dialog styled like HowCalculated (`max-w-md`, `max-h-[85vh] overflow-y-auto`, full width with `p-4` on a phone). Fetches with `useQuery({ queryKey: ["history", key], enabled: open })`. Per metric: newest-first list; each row shows local time, the trigger in words (sync → "bank sync", email → "email", manual → "refresh", calc_change → "app update"), the summary, and the signed delta; tapping a row expands its causes. Empty: "No changes recorded yet." 404 is treated as empty. Every amount and summary goes through `maskIfHidden` / `maskMoneyText`.

Placements (one control per headline figure, beside its existing ⓘ where there is one):
- Dashboard: Available to Spend (`available_to_spend`); Spendable this week block (`left_to_spend`, `spendable_week`, `spendable_today`); Safety Margin (`safety_margin`, `safety_margin_week`, `safety_margin_today`); 3-month low (`lookahead_minimum`); next-month low (`next_month_minimum`); Leftover in the Household Snapshot (`leftover`); Checking card (`checking_balance`).
- Recurring strip "Left over" (`leftover`), only when the strip shows the current month.
- Credit Cards page: each card's next payment estimate (`card_payment:<id>`).
- Settings: a "Clear change history" button using `ConfirmDialog`, calling `historyApi.clear()`, then invalidating `["history"]`.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/maskMoney.test.ts`: `"−$400.00 since 7:00 AM"` → `"•••• since 7:00 AM"`; `"+$50.00"` → `"••••"`; `"Example Insurance Co. $250.00, Grocery Store $1,100.00"` → both masked; `hidden=false` returns the text unchanged; `"7:00 AM"` and `"v12"` are untouched.

- [ ] **Step 2: Run** `cd frontend && bun test tests/maskMoney.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement `maskMoney.ts`, `historyApi`, `WhatChanged`, the placements and the Settings button.**

- [ ] **Step 4: Run** `bun test` (moneyGuard included) and `bunx vite build` → PASS.

- [ ] **Step 5: Verify in real Chrome with the Interceptor skill.** Against the live app (read-only: open the views, trigger no deletes), at desktop width and at 400px: open each placement's dialog. Expected: no console errors; the dialog fits without horizontal scroll; with Hide balances on, no `$` figure is visible anywhere in it. A fresh install may have one snapshot only, so "No changes recorded yet." is the expected text then. Do not click "Clear change history" on the live app.

- [ ] **Step 6: Commit.** `git commit -m "feat(history): what-changed view on every headline figure"`

---

## Out of scope

- Push: waits for Dan's OK after the final whole-branch review.
- No figure changes, so no `scripts/calc_before_after.py` run is required; Task 1's full-suite pass (parity tests) is the evidence.
