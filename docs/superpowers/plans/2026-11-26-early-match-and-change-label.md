# Early-Match Suppression + Scheduled-Change Label Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** These are the owner's requests from 2026-11-26.
1. A monthly recurring item that was already paid earlier this month must not be projected again later in the month. The live case is House Cleaning: it is floating, due on the last day, and was matched on Nov 12, but the Forecast still projects it on Nov 30.
2. In the recurring form, make it obvious that the "Scheduled Change" field means a future change to the payment amount.

**Root cause (verified on live data, read-only):** `build_forecast` (`backend/services/forecast_engine.py`) builds `actual_by_ri` from `all_actuals`, which is queried from `start_date` onward (line ~1044). With `start_date` = today (Nov 26), the Nov 12 linked actual is invisible, so the "any actual this calendar month" suppression (line ~1350) doesn't fire.
- Forecast starting 2026-11-01: the item appears only as the Nov 12 actual.
- Forecast starting 2026-11-26: it is projected again on Nov 30.
- The same blind spot hits weekly and biweekly items whose ±3-day actual posted within 3 days before `start_date`.

**Architecture:** Widen only the reach of the `actual_by_ri` lookup. It needs its own query over `[min(start_date.replace(day=1), start_date - 3 days), end_date]`, with the same filters as `all_actuals`. Leave `all_actuals` and `actuals_by_date` unchanged, because they drive balance sums and on-date actual lines.

**Tech Stack:** FastAPI + SQLAlchemy + pytest (uv); React 19 + TS + Tailwind 3 (bun).

**Spec:** the owner's words: "When adding a new recurring expense it is not easy to do know what the first text box is going to do so make it easier to identify as a change payment. Also I noticed that house cleaning is still projected in Forecast but in recurring it was matched on 11/12". The money rules are in `docs/architecture.md`.

## Global Constraints

**Money changes (Task 1 only)**
- Read `docs/architecture.md` first.
- Bump `CALC_VERSION` in `backend/services/calc_version.py` from 13 to 14, and add a `CALC_CHANGELOG` entry: "A monthly bill already paid earlier this month is no longer projected again later in the month."
- Add one bullet on this rule to `docs/architecture.md` §2 or the closest recurring-projection section.

**Copy (Task 2)**

| Element | Text |
|---|---|
| Left label | `Upcoming amount change` + the existing muted `(optional)` |
| Left placeholder | `New amount, e.g. 225.00` |
| Right label | `New amount starts` |
| Helper line (full width, under both fields, muted 13px) | `Use this when the payment amount will change on a future date, like a price increase. Leave blank if it stays the same.` |

**Repo rules**
- uv only and bun only. Never touch `.db` files.
- Commit to `main` and do not push.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Use made-up amounts and names in tests; no real balances in commit messages.
- Frontend verification builds use `bunx vite build --outDir /tmp/ob-verify-build`, never the default outDir: the default ships to the live app.
- Run backend tests the gate's way: `cd backend && uv run --locked python -m pytest …`.

## Review Focus

1. **Early-month match, later due date.** The item is not projected later in the month, and the balance is not reduced twice. Pinned in Task 1.
2. **Last month's actual.** A match in the previous month must not suppress this month's projection; the widened window starts at the 1st. Pinned in Task 1.
3. **Biweekly item with an actual 2 days before `start_date`.** Its projection within ±3 days is suppressed. Pinned in Task 1.
4. **Balances unchanged.** A pre-`start_date` actual must not be added into the walk's balance or appear as an actual line. Pinned in Task 1.
5. **Copy.** The new labels render and the old text is gone. Pinned in Task 2 by grep.

---

### Task 1: Suppress projections already paid before the forecast start

**Files:**
- `backend/services/forecast_engine.py`: modify only the `actual_by_ri` construction (~line 1290).
- `backend/services/calc_version.py`.
- `docs/architecture.md`.
- `backend/tests/test_forecast_early_match.py`: new.

- [ ] **Step 1: Write the failing tests.** Build fixtures the way existing forecast tests do (e.g. `backend/tests/test_payment_in_transit.py`), with a monthly expense item and `day_of_month=0`, `is_floating=True`.
  - `test_floating_matched_earlier_in_month_not_reprojected`:
    - Setup: a linked actual on 2026-11-12, `build_forecast(start=2026-11-26, end=2026-12-05)`.
    - Assert: no projected (`is_actual=False`) line for the item on 2026-11-30, and the December projection (Dec 31 is outside the range, so use `end=2027-01-02`) still appears.
  - `test_fixed_day_paid_early_not_reprojected`: same, with `is_floating=False` and `day_of_month=28`.
  - `test_previous_month_actual_does_not_suppress`:
    - Setup: the actual is on 2026-10-30, start is 2026-11-26.
    - Assert: the Nov 30 projection is present.
  - `test_pre_start_actual_not_added_to_balance`: the walk's balances equal those of the same forecast with the projection simply absent. No extra line, and the Nov 12 actual does not appear in the output.
  - `test_biweekly_actual_just_before_start_suppressed`:
    - Setup: a biweekly item due 2026-11-27 and a linked actual on 2026-11-25, start 2026-11-26.
    - Assert: no projection on 11-27.
- [ ] **Step 2: Run and confirm the first, second and fifth tests fail.**
- [ ] **Step 3: Implement** per Architecture, then do the version bump, the changelog entry and the doc bullet.
- [ ] **Step 4: Verify.** Run `cd backend && uv run --locked python -m pytest -q`, `uv run --locked ruff check .` and `uv run --locked python -c "import backend.main, cli.budget"`. Expected: all pass. Fix only tests that pinned the old double-projection, and list each in the report with the reason.
- [ ] **Step 5: Prove the guard can fail.** Revert the query window to `start_date`, confirm the first test fails, then restore.
- [ ] **Step 6: Commit** with the message `fix: a bill already paid earlier this month is not projected again`.

### Task 2: Clearer upcoming-amount-change fields

**Files:**
- `frontend/src/pages/Recurring.tsx` (~lines 751-760): the copy only, per the Global Constraints table. Add the helper line as a `<p>` spanning both columns.

- [ ] **Step 1: Implement** the copy change.
- [ ] **Step 2: Verify.**
  - Run `cd frontend && bun test && bunx vite build --outDir /tmp/ob-verify-build`. Expected: pass.
  - `grep -c "Scheduled Change" src/pages/Recurring.tsx` returns 0.
  - `grep -c "Upcoming amount change" src/pages/Recurring.tsx` returns 1.
- [ ] **Step 3: Commit** with the message `feat: label the scheduled amount change field plainly`.
