# Calculation Consistency and "Why Did This Change" — Design

**Date:** 2026-11-06
**Status:** Draft for approval

## Why

On 2026-11-06 alone, five mismatches surfaced, and each came from two places doing the "same" math differently:

- A planned one-off counted twice (planned one-off + real pending charge).
- Dashboard lowest points vs. the Forecast tab (different forecast walk flags).
- Recurring "Left over" vs. Dashboard "Leftover" (different bill amounts, groceries, no Social Security boost).
- Month in Review double-counted the prior month (card autopay + card charges both counted).
- Safety Margin moved by several hundred dollars with no visible reason (new pending charges).

Finding each cause meant copying the database, re-running old code, and diffing line by line. The app should do that work itself.

A read-only map of the codebase (same date) found:
- four separate "how much is left" figures;
- six different rules for totaling spending;
- three warning thresholds;
- forecasts started on three different dates;
- money math in the frontend.

## Goals

1. **One recipe per base quantity.** Each core number is calculated in exactly one place. Every screen, email, and endpoint reads it from there. Two screens showing the same concept can't disagree.
2. **Trace every change.** For every headline number, the user can see each time it changed, when, and which lines moved it.
3. **Explain it where the user looks.**
   - In the daily email, a short "since last email" line under each headline number.
   - In the app, a "what changed" view on every headline figure, on every screen, usable on a phone.
4. **Architecture docs** that let a new developer, or an AI agent, find where any number comes from without reading the code first.
5. **Rebuild the "Available to Spend" card** on the shared math. The principal chose rebuild over retire.

## Non-goals

- Remote/phone access itself (Tailscale/passkeys). That's a separate paused plan. This design must work well on a phone once remote access exists.
- Changing what any figure *means*, beyond the decisions recorded below. This is consolidation, not redesign of the metrics.
- An audit log of user edits. Edits matter only as one cause of a number change.

## Anti-goals (would be a failure even if it technically works)

- A "why" view that lists raw database rows instead of plain-language lines ("New pending Visa charge: Example Insurance Co. $250.00").
- Consolidation that silently shifts numbers without the change being visible. Every behavior change ships with a before/after note.
- A history store that grows without bound or leaks figures outside the user's machine.

## Decisions already made by the principal

- **Quarterly bills** land whole in their due month, everywhere. No ÷3 spreading.
- **Savings-funded one-offs** net to zero in Leftover, matching the forecast.
- **Income items excluded from the forecast** are excluded from Leftover too.
- **Displayed lowest points** (dashboard, email) equal the Forecast tab's balances. Locked statement-payoff dips are still not treated as the floor.
- **Safety Margin** covers today through the end of next month.
- **The 3-month low is a warning:** amber below the user's cushion, red below $0. The cushion is a user setting, default $1,000.
- **Planned expenses auto-settle** when a matching real charge (pending or posted) appears at sync.
- **"Available to Spend" is rebuilt, not retired.** Where possible, streamline where numbers are calculated.
- **History is recorded at each bank sync and each email.** The "why" view is available everywhere in the app; the dashboard is the primary place.
- **Architecture documentation** for new people and AI is required.

## The shared calculation layer

The work already started: `backend/services/month_base.py` (`build_month_base`) is now the single month model for income, bills and one-offs, used by Recurring and the dashboard Leftover.

Complete it with four canonical primitives. Everything else is composed from them.

1. **Month model** (`month_base`). It owns:
   - every income and bill occurrence in a month;
   - amounts (override/statement amount wins, keyed by natural due date);
   - the Social Security boost per paycheck (shared tracker);
   - the `include_in_forecast` filter;
   - planned one-offs (settled/unsettled, funded netting);
   - the card-linked vs checking split.

   Card bills charged so far, this month's card budget, and pacer add-backs all read from it.
2. **Card payment model.** Extract it from `build_forecast`. It owns:
   - locked payoff and statement paydown;
   - cycle estimate (pending + spent since statement + subscriptions before close + one-offs);
   - the second-hop rule;
   - the flat estimate;
   - the subscription fallback.

   It returns a basis object (already exists as `ForecastTransaction.basis`). The forecast, Safety Margin and the ⓘ notes all read it.
3. **Real-spending rule.** One function decides whether a transaction is real spending or income, and its signed amount. That covers:
   - card payments;
   - own-account transfers;
   - income-category debits;
   - refunds (netted);
   - savings categories.

   Every total uses it: Spending page charts, Budget overview, weekly digest, monthly email, Month in Review, Sankey, Left to Spend, pacer.
4. **Pending and thresholds.**
   - **Pending:** one pending-charges accessor with one freshness rule, used by every consumer.
   - **Thresholds:** one cushion setting feeds Safety Margin's warning, the risk banner, and the Wish List. The separate Wish List cushion and the `low_balance_threshold` default merge into it. The builder decides the migration path; defaults must not change visible behavior without a note.

**Forecast walk policy.** One function builds the standard walk: start date, bridge rules, and the `include_unbilled_card_bills` flag. Every consumer uses it. That covers:
- Forecast tab;
- lows;
- risk banner;
- weekly digest;
- upcoming bills;
- Wish List;
- baseline snapshots.

The bridge walks must propagate the flag (known bug: they drop it today). Consumers that need a different walk say so explicitly, with a comment explaining why.

**Weekend rule.** An override or statement amount is keyed by the item's natural due date. The weekend shift moves only the posting day. This applies in the forecast, month model and upcoming bills alike.

**Frontend.** The frontend displays backend figures and does no money math. Each existing client-side computation moves to the backend:
- Net Position;
- cycle spend;
- pending-adjusted balances;
- Budget track totals;
- Spending averages.

Pure formatting and chart sampling may stay.

**Enforcement.** Two kinds of test:
- **Parity tests:** for each headline concept, every surface that shows it returns the identical value from one fixture. That covers dashboard, email, Recurring, Budget, Forecast tab, Available to Spend and the API.
- **A guard test:** it fails if a router or the frontend sums money fields directly, so new code can't quietly add a second recipe. The builder chooses the mechanism, for example an import-boundary check or an allowlist.

## "Available to Spend" rebuild

Rebuild the card entirely from the primitives above. Today it uses:
- monthly income only, with no boost;
- monthly/yearly bills only, with no overrides;
- dropped refunds.

After the rebuild, it must reconcile visibly with the Household Snapshot. Its ⓘ shows how it relates to Leftover / Left to Spend. If, once rebuilt, it duplicates Left to Spend exactly, the builder proposes merging the two and asks before removing either.

## Change history ("why did this change")

**What's recorded.** At each bank sync, each email send, and on demand, the app saves a snapshot of every headline metric. Each snapshot holds:
- the value;
- the as-of time;
- the trigger (sync / email / manual / code change);
- the explain tree that produced the value, which the existing ⓘ `Explanation` machinery already builds.

The headline metrics are:
- Leftover, Left to Spend, Spendable week/today;
- Safety Margin;
- next-month low and 3-month low;
- each card payment estimate;
- Available to Spend;
- checking balance (with pending).

**Diffing.** A change between two snapshots is explained by diffing their explain trees: which lines appeared, disappeared, or changed amount. The result is rendered as plain-language lines, for example:

> "Safety Margin −$400.00 since 7:00 AM: new pending Visa charges: Example Insurance Co. $250.00, Grocery Store $100.00, Online Shop $50.00"

When code changes the math (not data), record the app version with each snapshot. The "why" can then say "calculation changed in version X" instead of inventing a data cause.

**Surfaces.**
- **Email:** one "since last email" line under each headline number. Show it only when the change is non-zero; keep it short for a phone screen.
- **App:** every headline figure on every screen gets a "what changed" control that opens its history: a list of changes, each expandable to the lines that moved it. It must work on a phone (≈400px). The dashboard is the primary entry point.

**Retention and privacy.** Snapshots stay in the local SQLite database, like all other data. Keep 13 months (my call), then prune. Update `docs/PRIVACY.md`: what's stored, and how to delete it.

## Architecture documentation

Add `docs/architecture.md`, linked from README and `docs/technical-guide.md`, containing:
- **A system overview:** bank sync → database → shared calculation layer → API → screens/email.
- **A number provenance table.** Each user-visible figure maps to its primitive, its function and file, the screens and emails that show it, and its definition in plain English.
- **The four primitives and the forecast walk policy:** rules, edge cases (weekends, pending freshness, quarterly bills, Social Security boost, funded one-offs), and the decisions log above.
- **How the change history works,** and how to trace a reported mismatch, step by step.
- **"Rules for contributors and AI agents":** never compute a money figure outside the shared layer; add a parity test for any new surface; record behavior changes in the decisions log.

Add a short pointer in the project `CLAUDE.md` so AI sessions read `docs/architecture.md` before touching calculations.

## Constraints

- **Repo and tooling:**
  - Public repo: no real figures in code, tests, docs, or commit messages.
  - Python via uv, frontend via bun; existing pre-push gate (lint, audit, import check, coverage floor, CodeQL, bun audit, vite build).
  - Commits go straight to `main`, and pushing waits for the principal's OK.
- **Live database:**
  - The live backend runs `uvicorn --reload`, so schema changes apply immediately.
  - Back up via `backup_database()` before any schema change, and keep migrations additive and nullable.
- **Behavior changes:** each consolidation step that changes a visible number needs a before/after on the principal's data, run on a database copy, and his OK before it's pushed.

## Suggested order (builder may refine)

1. **Architecture doc and provenance table** first, written from the current code. It doubles as the consolidation checklist.
2. **Primitives**, one per step with parity tests:
   - real-spending rule;
   - pending accessor;
   - forecast walk policy plus the weekend rule;
   - card payment model;
   - month model completion (card add-backs, pacer);
   - thresholds merge.
3. **Frontend money math** moved to the backend.
4. **Available to Spend** rebuilt.
5. **Change history:** store, diff, app view, then the email line.

## Left to the builder

- Module and table names.
- Snapshot schema details.
- How the guard test is implemented.
- Diff rendering wording, within the anti-goals above.
- The migration path for merging thresholds.
- Splitting the work into plans and phases.

## My calls (not yet confirmed by the principal)

- Thirteen months of snapshot retention.
- Refunds are netted against spending everywhere, because that reflects true spending.
- Overrides keyed by natural due date.
- Snapshots also taken on demand and on code-version change.
