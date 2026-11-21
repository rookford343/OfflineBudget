# Split one-off installments — duplicate refund-watch fix

Small follow-up fix for a gap a final whole-branch review found after the split one-off
installments feature (see `2026-11-20-split-one-off-installments-plan.md`) had already
merged and had its SDD workspace cleaned up. This gets its own report instead.

## The bug

`cancel_installment_group` (`backend/services/installment_plan.py`) always created a new
refund-watch row for every currently-cleared sibling in the group, with no check for
whether one already existed. Because any non-"fully resolved" cancel call re-sweeps every
currently-uncleared sibling of the group and re-creates a refund-watch for every currently-
cleared one, a sibling that was already being watched from an earlier partial cancel of the
same group got a second, identically-named refund-watch row the next time any cascade ran
against that group — double-counting the expected refund inflow in the forecast.

## Reproduction (no fabricated state — real endpoints only)

1. Create a 3-leg installment group: anchor `Z`, legs `X` and `Y`.
2. Settle `X` and `Y` (both cleared); `Z` stays uncleared.
3. `DELETE /planned-expenses/{Z.id}` — `Z` is the uncleared anchor, so this is a real
   cascade. It sweeps `Z` and opens one refund-watch each for `X` and `Y` (both now cleared
   survivors), retargeted onto a new anchor.
4. `POST /planned-expenses/{Y.id}/unsettle` — `Y` goes back to uncleared. `X` and its
   refund-watch from step 3 are untouched.
5. `DELETE /planned-expenses/{Y.id}` again — `Y` is uncleared again, so this is a genuine
   second cascade (not the "fully resolved" branch). `X` is still cleared and still carries
   its refund-watch from step 3.

Without a fix, step 5's cascade re-adds `X` to the `cleared` list and creates a second,
identically-named `"{X.name} — refund expected"` row for it — two refund-watches for the
same sibling, nothing about `X` having changed since step 3.

This sequence doesn't require fabricating unreachable DB state (unlike one existing test in
this file that plants a sentinel row): every step is a real `create_installment_group`
call plus the app's own settle/delete/unsettle endpoints. The key realization driving the
3-leg shape: any single, non-"fully resolved" cancel call sweeps *every* currently-uncleared
sibling of the group in one shot (not just the row the caller targeted), so the only way to
get a second cascade to re-process an already-watched cleared sibling is to have a *second*
cleared sibling that gets unsettled and re-deleted afterward — a 2-leg group always
collapses to the "fully resolved" branch (no refund-watch created there at all) once only
one non-refund-watch row is left.

## The fix

In `cancel_installment_group`, right before the loop that creates refund-watch rows for
`cleared` siblings, the current refund-watch set for the group (post-retarget, via the
existing `_refund_watches` helper and `new_group_id`) is collected into a name set. The loop
now skips creating a refund-watch for a sibling if a refund-watch with that sibling's exact
expected name (`f"{sibling.name} — refund expected"`) is already in that set, adding each
newly-created name to the set as it goes so two cleared siblings with coincidentally
identical names in the same call can't double up on each other either.

Nothing else about the cascade (sweeping uncleared legs, retargeting onto a new anchor,
anchor-last deletion ordering) changed — this is a narrow, additive guard at the point
refund-watches get created, exactly as scoped.

Diff is ~15 lines in `backend/services/installment_plan.py`.

## Regression test

Added `test_re_cancelling_a_group_does_not_double_the_same_refund_watch` to
`backend/tests/test_installment_cancellation.py`, implementing the reproduction above and
asserting exactly one refund-watch named `"{X.name} — refund expected"` exists after step 5
(not two).

**Proved the test fails without the fix**: temporarily short-circuited the new guard
(`if False and refund_name in existing_names:`) and ran just the new test — it failed with
`assert 2 == 1`, finding two `PlannedExpense` rows with the identical refund-watch name.
Restored the guard afterward and re-ran; it passes.

## Verification

- `backend/tests/test_installment_cancellation.py` — 11 passed (10 pre-existing + 1 new).
- Full backend suite: `uv run --locked python -m pytest -q --cov --cov-report=term:skip-covered`
  — **1952 passed**, coverage **89.42%** (floor 85.0%, unchanged/untouched).
- `uv run --locked ruff check .` — all checks passed.
- Import smoke test: `uv run --locked python -c "import backend.main, cli.budget"` — clean.

## Commit

Committed directly to `main` per repo convention (no feature branch). One commit.
