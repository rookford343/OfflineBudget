# Plan: drop vague amount-less causes from the email's "What changed" section

**Repo convention:** commit directly to `main`, no branches/worktrees. Pre-push hook re-runs the backend test suite.

## Context

The daily email's closing "What changed since last email" section
(`backend/services/summary_generator.py`, `_reasons()` / `_changes_section()`,
around lines 719-740) renders every `Cause` attached to each `EmailChange`,
unfiltered.

`metric_diff.explain_change` sets `Cause.short` on every line-level cause as a
generic headline form (e.g. "X changed"). `_inherited()` — used when a derived
figure (e.g. `safety_margin_week`) inherits a cause from its parent
(`safety_margin`) — goes further: it replaces `.text` with that same generic
`.short` form, dropping the dollar amount, because the parent's amount does not
apply 1:1 in the child's units. Result: the email shows vague, information-free
bullets like "Test Visa changed" and "Card bills already charged changed" —
text identical to the cause's own `.short` field, naming nothing beyond what the
figure's own top-line delta already said.

The in-app history popup (`backend/routers/history.py` `statement_for`, frontend
`WhatChanged.tsx`, built 2026-11-10) already solved this in its own context: its
`events` list filters out every cause with `.short` truthy, relying on a
separate "How the number moved" math-lines table to show real numbers instead.
The email has no such math-lines fallback (by earlier explicit decision —
"email line = amount only, per Dan" — see
`docs/superpowers/plans/2026-11-07-calculation-consistency-plan-3-change-history.md`),
so copying that same strict filter would silently delete real information:
some causes carry `.short` AND still have a real amount in `.text` (a figure's
own directly-computed line cause, as opposed to one inherited from a parent) —
e.g. `short="Jan 15 — CC Estimate: Test Visa changed"` but
`text="Jan 15 — CC Estimate: Test Visa −$40.00"`. That one must be KEPT.

Verified by hand against the real snapshot pair (ids 16→20, 2026-11-10→
2026-11-11 email snapshots) in the diagnosing session: the fix below cuts that
morning's 8 rendered reasons down to 4, all substantive, zero information lost.

## Global Constraints

- Pure backend text-rendering change. No money-math implications, no DB
  migration, no frontend change. Do not touch `WhatChanged.tsx`,
  `metric_diff.statement_for`, or `statement_headline` — those are already
  correct and intentionally out of scope.
- `uv run --locked pytest backend/` and `uv run --locked ruff check .` must
  both pass before the task is reported done.
- Commit directly to `main` (no branch) once the task review is clean.

## Task 1 — Filter vague inherited causes out of the email's reason list

**Files:** `backend/services/summary_generator.py`,
`backend/tests/test_email_since_lines.py`

1. In `_reasons()` (`backend/services/summary_generator.py`, the loop
   `for c in causes_of(ch):`), skip a cause when it is **not** a grouped/head
   cause **and** its `.text` equals its `.short` — i.e.:

   ```python
   if not c.head and c.text == c.short:
       continue
   ```

   Place this check as the first line inside the `for c in causes_of(ch):`
   loop, before the `ident = ...` line. Add a short inline comment explaining
   *why* this condition is more lenient than `statement_for`'s `not c.short`
   filter: the popup has a math-lines fallback table for every line cause;
   the email does not, so the email only drops causes that are purely vague
   (text identical to their own short form), not every line cause. This
   comment exists to stop a future reader from "fixing" the two filters to
   match each other — they are deliberately different because the two
   surfaces have different fallbacks.

2. Keep everything else unchanged: grouped head-causes are always kept (they
   never have `.short` equal to `.text` since head-causes don't set `.short`
   at all), and any line cause that still carries a real amount in `.text`
   (even though `.short` is also set) is kept.

3. In `backend/tests/test_email_since_lines.py`, extend the existing test
   helper (around line 353):

   ```python
   def _cause(head="", text="a cause", rows=()):
       from backend.services.metric_diff import Cause
       return Cause(text=text, amount=None, head=head, items=tuple(n for n, _ in rows), rows=tuple(rows))
   ```

   to accept an optional `short=""` parameter (default `""`, so every
   existing call site is unaffected) and pass it through to `Cause(...)`.

4. Add a new test (same file, near the other `_reasons`/`_changes_section`
   tests such as `test_a_partial_reason_names_the_figures_it_moved`) that:
   - Builds one `EmailChange` (via the existing `_chg` helper) carrying two
     causes:
     - a vague inherited one: `_cause(text="Card bills already charged changed", short="Card bills already charged changed")`
     - a substantive one with a real amount: `_cause(text="Jan 15 — CC Estimate: Test Visa −$40.00", short="Jan 15 — CC Estimate: Test Visa changed")`
   - Renders via `generate_daily_summary(db_session, user, since_changes=[...])`
     following the exact pattern already used in
     `test_a_partial_reason_names_the_figures_it_moved` (same file) for how to
     build the `user`/`since_changes` arguments and where to slice the
     `CHANGES_TITLE` section out of `html`/`text`.
   - Asserts `"Card bills already charged changed"` is **absent** from both
     the `html` and `text` bodies.
   - Asserts `"Jan 15 — CC Estimate: Test Visa −$40.00"` **is present**
     in both bodies.

5. Add a second new test (or extend the one above) confirming a grouped
   head-cause is never dropped by this filter: build an `EmailChange` with a
   `_cause(head="New pending charges", rows=[("Some Merchant", Decimal("12.34"))])`
   cause and assert `"New pending charges"` and `"Some Merchant"` both still
   render in `html`/`text`. This guards against a future edit making the
   condition too aggressive (e.g. someone changing it to drop all `.short`-
   truthy causes, which would silently delete grouped causes too if the
   `not c.head` guard were ever removed).

**Verification:** `uv run --locked pytest backend/tests/test_email_since_lines.py -q`
must show the two new tests passing alongside all existing ones in that file
(no existing test's expected output should change — the filter only removes
causes that were previously pure noise). Then
`uv run --locked pytest backend/ -q` for the full suite, and
`uv run --locked ruff check .`.

**Commit message:** describe the behavior change (the email's "what changed"
section no longer shows vague, amount-less restatement bullets like "X
changed" when nothing new is actually being said) — no real balances, amounts,
or dates from Dan's own data in the message (public repo).
