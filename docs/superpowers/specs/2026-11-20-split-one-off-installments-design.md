# Split One-Off Installments — Design

## Intent and why

A one-off (`PlannedExpense`) today models a single amount on a single
date. Some real one-offs don't work that way: Dan's dentist bill for Leia
was half due as a deposit today, the other half due at the appointment on
12/18. There is currently no way to enter that ahead of time without
either lumping both halves into one wrong-dated number or creating two
unrelated one-offs by hand with no connection between them.

This adds the ability to split a one-off into 2–6 dated installments,
each behaving like today's one-off (forecasted until bank sync clears
it), with one combined delete behavior that treats the installments as
one plan: cancelling before everything is paid cancels what's left, and
cancelling after part of it is paid opens a refund expectation instead of
erasing history.

Six is the cap. Past six payments, Dan's call: that's a recurring
expense, not a one-off, and belongs in `RecurringItem` instead.

## Goals

- Create a one-off as 2–6 installments, each with its own amount and
  date, under one name and one payment method.
- Two entry modes: type each installment's amount by hand, or ask the
  app to split the total evenly across chosen dates. Both must exist;
  neither replaces the other.
- Each installment is forecasted independently and clears independently,
  exactly like a `PlannedExpense` does today (settled by the existing
  bank-sync auto-settle matcher, or by hand).
- Each installment shows as its own row in the one-off list, named so its
  place in the group is obvious — e.g. "Leia dental (1 of 2)".
- Deleting any installment while the plan isn't fully paid cancels the
  whole plan: every still-unpaid installment in the group is removed.
- Deleting an installment that has already cleared never erases that
  history. Instead it opens a refund-watch: a reverse (inflow) entry that
  waits for a matching credit via the same auto-settle matching that
  already exists, and that Dan can cancel himself at any time (by
  deleting it, the same way he'd delete any other one-off).
- Editing a single installment's amount or date (not deleting it) stays
  a plain, independent edit — no cascade, no group-wide effect.

## Non-goals

- A general "payment plan" product feature (interest, fees, number of
  remaining payments shown as a countdown, etc.) — this is just dated
  installments under one one-off.
- Changing `RecurringItem` or `BillAmountOverride` in any way.
- More than 6 installments. The cap is enforced, not softened into a
  warning — push the user toward a recurring item instead.
- Per-installment payment methods. One account or card covers the whole
  group, decided once at creation.
- Any new "manually mark paid" state. "Paid" still means exactly what it
  means for every other one-off today: `settled_on` is set, whether by
  the auto-settle matcher after a bank sync or by the existing manual
  settle endpoint.
- Any change to how an existing money figure is computed. This feature
  only adds new rows and a new delete/lifecycle path; it does not touch
  a forecast formula, Safety Margin, or any other provenance-table
  figure. Per `docs/architecture.md`'s "Rules for contributors and AI
  agents": no `CALC_VERSION` bump, no `scripts/calc_before_after.py` run,
  and no calculation-changelog entry are needed for this work — only a
  Decisions log entry (see below) recording the new lifecycle behavior.

## Anti-goals (would be a failure even if it technically works)

- A refund-watch that can't be told apart from a normal one-off in the
  list — Dan must be able to see at a glance which rows are "waiting for
  money back" versus a normal planned inflow or outflow.
- Deleting one installment silently deleting *only* that row while its
  unpaid siblings linger in the forecast forever uncancelled — that's the
  exact bug this feature exists to prevent (a dentist appointment that
  gets cancelled but still forecasts a balance due).
- A refund-watch that re-triggers the whole-group cancel behavior when
  *it* gets deleted. Cancelling the refund-watch is just removing that
  one row.

## Constraints

- No Alembic in this repo. New columns on `planned_expenses` go through
  the existing idempotent `ALTER TABLE ... ADD COLUMN` list in
  `upgrade_schema()` (`backend/database.py`), following the same pattern
  already used for that table's `account_id` column (around line 129).
- `backend/tests/test_calc_guard.py` fails on new money sums computed
  outside `backend/services`. No new money arithmetic should be needed
  here (splitting a total into N legs is either literal user input or a
  division done once at the point of creation, not a recurring
  calculation) — if the even-split arithmetic ends up in a service
  function, check whether it needs the guard's allowlist the way
  `metric_diff.py`'s `_group`/`_total` do, and justify it the same way:
  only if it's never read back for display math.
- Every security fix pattern from `backend/tests/test_security_regressions.py`
  and the repo's standing security gates apply as usual: this feature adds
  a new creation path and should not introduce new unbounded loops,
  unvalidated foreign keys, or unparameterized queries.
- Direct commits to `main` (repo convention, no feature branches).
- Use synthetic numbers in any new tests, docs, or commit messages — this
  repo is public.

## Decided (as decided, not left open)

- **Scope**: general capability for any one-off, not special-cased to
  dentist bills or any other category. Cap: 6 installments; above that,
  reject and point at `RecurringItem`.
- **Entry modes**: both "type each installment yourself" and "split the
  total evenly across dates I pick" must exist. The builder decides the
  exact UI interaction (e.g. a mode toggle vs. a button that pre-fills
  even amounts into editable fields) — either is fine as long as both
  paths are reachable and the even-split one actually divides the total
  across the chosen dates rather than requiring the user to compute it.
- **Payment method**: one `account_id` or `card_id` for the whole group,
  set once, applied to every installment and the eventual refund-watch
  row. No per-installment override.
- **Naming**: one name typed once; each installment's stored `name` gets
  a baked-in "(k of N)" suffix at creation time (e.g. "Leia dental (1 of
  2)", "Leia dental (2 of 2)"). This label is written once and never
  recomputed — because of the delete rule below, a group can never end up
  with some unpaid installments still showing stale "(k of N)" text next
  to deleted siblings; the unpaid ones all disappear together.
- **Clearing**: unchanged. Each installment is a normal `PlannedExpense`
  row and is settled exactly the way one is today — the existing
  `backend/services/planned_auto_settle.py` matcher (same card/account,
  same direction, amount tolerance, date window) or the manual settle
  endpoint. Nothing about matching changes.
- **Delete / cancel, the core new rule**: deleting *any* installment in a
  group is "cancel this one-off." The effect:
  - Every installment in that group with `settled_on IS NULL` (still
    unpaid/unmatched) is deleted — including the one the user clicked
    delete on, if it was unpaid.
  - Every installment in that group with `settled_on IS NOT NULL`
    (already cleared) is left untouched as history, and a refund-watch
    row is created for it (see below). It is never deleted by this
    cascade.
  - Editing an installment's amount or date (not deleting it) has none
    of this — it's an ordinary single-row `PATCH`, same as any one-off
    today.
- **Refund-watch row**: for each settled installment swept up by a
  group-cancel, create one new `PlannedExpense`:
  - `direction = inflow`.
  - `amount` = that installment's `actual_amount` if set, else its
    original `amount` (the best-known real figure).
  - Same `account_id`/`card_id` as the group.
  - `expected_date` = today (the cancellation happened now; there's no
    other known date to anchor it to).
  - Belongs to the same group for lookup/labeling purposes, but is
    *not* itself subject to the group-cancel cascade — deleting the
    refund-watch row is always a plain single-row delete. This is how
    Dan cancels the refund-watch himself, with no new UI verb: he just
    deletes that row like he'd delete any other one-off.
  - Name: the group's name plus a marker that makes it visually obvious
    this is a refund expectation and not a normal inflow (builder's
    exact wording; e.g. "Leia dental — refund expected").
  - It settles exactly like any other inflow one-off: the existing
    auto-settle matcher already matches an inflow `PlannedExpense`
    against a real credit by account/card, amount tolerance, and date
    window — nothing new to build there.
- **Preview**: the Safety Margin before/after preview shown while
  creating a split one-off should reflect all installments together (the
  combined effect of adding every leg at once), not one leg at a time.
  `backend/services/one_off_preview.py`'s `preview_one_off` already
  builds a `ScenarioProposal(expenses=(pe,))` from a single draft;
  extend the proposal to carry every installment's transient
  `PlannedExpense` at once (`ScenarioProposal` already takes a tuple).

## Resolved during builder-check (my call, not Dan's)

A fresh-eyes review of this doc raised five implementation gaps. None of
them change what Dan asked for, so I ruled on them rather than taking them
back to him:

- **"Paid" for cascade purposes excludes a reconciled no-op.** `PlannedExpenseSettle`
  already lets a row be settled with `actual_amount = None`, meaning "this
  didn't happen" (the auto-settle matcher itself skips those when matching
  real money). An installment in that state must be treated as *unpaid* for
  the delete-cascade rule above — swept away like any other unpaid leg, no
  refund-watch — not as "already cleared." Otherwise a dentist leg marked
  "didn't happen" because the appointment moved would spawn a refund-watch
  for money that was never paid. Precisely: "already cleared" for this
  feature's cascade means `settled_on IS NOT NULL AND actual_amount IS NOT NULL`.
- **Group creation is one atomic call, not a client-side loop.** A new,
  dedicated bulk-create endpoint takes the shared name/account/card/category
  plus the list of 2–6 `{amount, expected_date}` legs and creates them in one
  DB transaction — all legs or none. A loop of N calls to the existing
  single-row `POST /planned-expenses` risks a partial group on a mid-loop
  failure, which breaks the "one plan, one cancel" promise this whole
  feature exists to keep.
- **Multi-cycle card preview gets its own response shape, not a patched
  existing one.** `OneOffPreviewOut.card_payment` stays exactly as it is
  today (one optional impact) for the existing single one-off create/preview
  flow — untouched. The new bulk-preview endpoint (paired with the bulk-create
  endpoint above) returns its own response carrying a list of card impacts,
  one per distinct payoff due date the installments land on, so two
  installments on the same card that cross a statement boundary both show up
  rather than only the first.
- **Funding fields are out of scope for split installments.** Savings-funded
  one-offs (`funding_account_id`/`funding_amount`/`funding_lead_days`) are
  never auto-settled by `planned_auto_settle.py` — that's by design for a
  single funded one-off, but it would silently break this feature's promise
  that every installment clears on its own via the existing matcher. The
  bulk-create endpoint does not accept funding fields; an installment and
  its refund-watch row are always created with them null. A one-off that
  needs savings funding stays a plain, single `PlannedExpense`, unsplit.
- **Refund-watch reads its payment method off the leg it's refunding.**
  Not off a separate group-level value — so if a sibling installment's
  account/card is later edited independently (the single-row `PATCH`
  endpoint is unchanged and allows this), the refund-watch for a *different*,
  already-settled leg in the same group still points at the right place.

## What's left to the builder

- Exact new column name(s) on `planned_expenses` for the group link and
  for telling an installment apart from a refund-watch row (e.g.
  `installment_group_id` + `is_refund_watch`, or an equivalent scheme).
  Any correct, idempotent scheme that supports the decided delete
  behavior is fine.
- Exact new endpoint shape(s) for creating a group of installments and
  previewing one (new routes under `backend/routers/planned_expenses.py`,
  or an extension of the existing single-row routes — builder's call,
  but the existing single-installment create/preview/delete/settle
  endpoints must keep working unchanged for a plain one-off).
- Exact UI home: extending `frontend/src/components/phone/PlanOneOffSheet.tsx`
  with a "split into payments" path, or a new sibling component reached
  from the same place. Should reuse the existing preview query and
  account/card picker rather than duplicating them.
- Exact visual treatment distinguishing a refund-watch row in the one-off
  list from a normal inflow.
- Validation wording for the >6 case and for a sum-of-installments
  mismatch in manual-entry mode (if the builder's UI allows entering
  installments that don't sum to a stated total; the design does not
  require a "total" field to exist at all — each installment's amount is
  independently real money, there is no derived total to reconcile
  against unless the builder's UI chooses to show one).
- Test coverage for: cap enforcement (6 is fine, 7 is rejected); both
  entry modes; independent single-installment edit; the two delete
  branches (all-unpaid cancel, and partially-paid cancel-plus-refund-watch);
  refund-watch settling via the existing auto-settle matcher; and the
  combined preview reflecting every installment. Per the standing project
  rule, any test asserting a fix must first be shown to fail without it.
