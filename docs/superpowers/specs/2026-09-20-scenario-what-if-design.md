# What-If Scenarios — Design

the user wants to test a change to his finances before it becomes real: "if I get
the iPhone Duo on 10/23 — $57.87/month for 24 months, plus AppleCare at
$174.13/year renewing the same day — what does that do to my forecast?" Then,
if the answer is acceptable, commit it so those become real recurring items
without retyping them.

A scenario system already exists and cannot express that. `ForecastScenario`
+ `ScenarioOverride` (`backend/models.py:529`, `:575`) model exactly one kind
of change: an `amount_delta` on a recurring item that **already exists**.
There is no way to propose an item that doesn't exist yet, propose a one-off,
set an end date, or turn a scenario into reality. Forecast.tsx already draws a
scenario line on its chart, and `/scenarios` already has full CRUD — so the
gap is the vocabulary of a scenario, not the plumbing around it.

Approach chosen (from brainstorming, over two alternatives): **extend the
existing tables**. The two rejected options are recorded under
[Alternatives considered](#alternatives-considered) because the reasoning
matters more than the choice.

## Scope

In:

1. A scenario can hold **proposed new recurring items** and **proposed
   one-off expenses**, alongside today's amount tweaks on existing items
2. Forecasting a scenario, including card-routed proposals
3. Committing a scenario into real rows, with links back and an undo
4. A new `/scenarios` tab: list, editor, chart, impact figures

Out (deliberately):

- Editing or removing *existing* recurring items within a scenario. Adds and
  amount tweaks cover the cases the user named; a full draft layer over every item
  was considered and rejected as disproportionate.
- Scheduling a scenario to auto-commit on a future date.
- Sharing or exporting scenarios.

## 1. Data model

`ForecastScenario` gains:

| Column | Type | Notes |
|---|---|---|
| `status` | `"draft" \| "committed"` | defaults `draft` |
| `committed_at` | `datetime \| None` | stamped by commit, cleared by uncommit |
| `notes` | `str \| None` | free text, e.g. "assumes trade-in credit applies" |

Two new tables. Each mirrors only the fields the forecast actually reads from
its real counterpart, plus a nullable FK recording what it created on commit:

```
ScenarioProposedItem              (a RecurringItem that doesn't exist yet)
  id, scenario_id -> forecast_scenarios.id (CASCADE)
  name, amount, type, frequency, day_of_month, month_of_year,
  start_date, end_date, account_id, card_id, category_id
  committed_recurring_item_id -> recurring_items.id, nullable

ScenarioProposedExpense           (a PlannedExpense that doesn't exist yet)
  id, scenario_id -> forecast_scenarios.id (CASCADE)
  name, amount, expected_date, direction, account_id, card_id,
  funding_account_id, category_id
  committed_planned_expense_id -> planned_expenses.id, nullable
```

`ScenarioOverride` keeps its shape and gains `committed_previous_amount`
(`Decimal | None`) — committing an amount tweak edits the real item, and undo
needs the value it replaced.

**the user's case in this model:** one scenario, "iPhone Duo + AppleCare", holding

- `ScenarioProposedItem`: iPhone Duo trade-in, 57.87, expense, monthly,
  day_of_month 23, start 2026-10-23, **end 2028-10-23**, `card_id` = Apple Card
- `ScenarioProposedItem`: AppleCare, 174.13, expense, yearly,
  month_of_year 10, day_of_month 23, start 2026-10-23, `card_id` = Apple Card

Both carry `card_id`, so they post to the card and reach checking only through
that card's statement payoff — the routing `build_forecast` already applies to
card-linked recurring items. The iPhone's end date makes it show up in the
Ongoing-vs-Temporary breakdown shipped in `89cf4b8` the moment it commits.

## 2. Forecast integration

**Proposals are materialized as transient SQLAlchemy objects that are never
added to the session,** then appended to the lists `build_forecast` already
walks — so `_fires_on`, the weekend pull-forward, end-date handling and
actual-vs-projected suppression apply to a proposal **because it is the same
object type walking the same loop**. A parallel "project a proposed item"
code path would be a second implementation of scheduling logic, and this repo
has spent the last week fixing bugs born of exactly that duplication (the
`perMonth` drift in `8f5f8ec`, the checkpoint guard that enumerated one model
type in `0692d97`).

**Which list depends on routing, and this is the part that is easy to get
wrong.** `build_forecast` deliberately *excludes* card-linked expenses from
the checking walk (`forecast_engine.py:296-306`: "CC charges (expense +
card_id) hit the card, not the checking account"). They reach the forecast
through the card's projected charge instead. So:

| Proposal | Appended to | Reaches checking via |
|---|---|---|
| expense, no `card_id` | `recurring_items` | its own due date |
| expense with `card_id` | `card_items_by_card[card_id]` | `_card_subscription_charges` → `_card_payoff_date_for_charge` → that card's payoff |
| income, or a one-off | `recurring_items` / `planned_by_date` | its own date |

```python
# inside build_forecast, after the real queries
for p in proposal.items:
    transient = models.RecurringItem(
        id=-p.id,  # negative: cannot collide with a real item's id
        user_id=user_id, name=p.name, amount=p.amount, type=p.type,
        frequency=p.frequency, day_of_month=p.day_of_month,
        month_of_year=p.month_of_year, start_date=p.start_date,
        end_date=p.end_date, account_id=p.account_id, card_id=p.card_id,
        category_id=p.category_id, is_active=True, include_in_forecast=True,
    )
    if p.type == models.RecurringType.expense and p.card_id:
        card_items_by_card.setdefault(p.card_id, []).append(transient)
    else:
        recurring_items.append(transient)
```

**A card with a manual `monthly_spend_estimate` ignores its subscriptions
entirely** (`forecast_engine.py:691-701`: "A manually-set estimate wins").
the user's Chase carries $5,500/mo; his Apple Card carries 0. So a proposal routed
to the Apple Card changes the forecast, and the identical proposal routed to
Chase changes **nothing** — it is swallowed by the manual estimate.

That is correct existing behavior, not a bug to fix here, but it is invisible
and would read as "the scenario doesn't work". Therefore: **the proposal form
must warn when a card-routed proposal is assigned to a card that has a manual
monthly estimate**, naming that the card's estimate governs instead. A test
pins the underlying behavior so the warning can't quietly become untrue.

(the user's own case is unaffected: both proposals go on the Apple Card.)

Two further constraints this imposes, both testable:

- **Nothing may persist.** The session runs `autoflush=False`
  (`backend/database.py:20`), and these objects are never `db.add()`ed, so
  they cannot reach the database. A test asserts that forecasting a scenario
  leaves `recurring_items` and `planned_expenses` row counts unchanged.
- **Negative ids.** `override_map` and `actual_by_ri` are keyed by item id;
  a proposal's id must not collide with a real one. Negating the proposal's
  own id gives a stable, collision-free key. A proposal can't have actuals
  matched against it, which is correct — it hasn't happened.

Entry point: `build_forecast` and `build_quarters` gain
`proposal: ScenarioProposal | None = None` — a frozen dataclass defined in
`backend/services/forecast_engine.py` beside the engine that consumes it,
holding the resolved proposed items and expenses. A resolver in
`backend/services/scenario_service.py` turns a `scenario_id` into one. The
existing `overrides` parameter is unchanged so today's callers keep working.

## 3. Commit and uncommit

`POST /scenarios/{id}/commit` — in one transaction:

1. Each `ScenarioProposedItem` → a real `RecurringItem`; store its id in
   `committed_recurring_item_id`
2. Each `ScenarioProposedExpense` → a real `PlannedExpense`; store its id
3. Each `ScenarioOverride` → record the item's current amount in
   `committed_previous_amount`, then apply the delta to the real item
4. `status = "committed"`, `committed_at = now()`

Committing an already-committed scenario is refused (409) rather than
creating duplicate rows.

`POST /scenarios/{id}/uncommit` — reverses it: deletes the rows named by the
stored FKs, restores each overridden amount, clears the links, returns the
scenario to `draft`. It is idempotent about rows that are already gone (a row
deleted by hand is skipped, not an error).

**Decided:** uncommit deletes a created row even if it was edited afterward,
and those edits are lost. The alternative — refusing to uncommit a row that
has diverged — means storing a fingerprint of every created row and
explaining a refusal the user can't easily resolve. Confirmed with the user
2026-09-20. The UI names this on the uncommit button's confirm dialog.

## 4. API

Under `/scenarios/{scenario_id}`:

| Method | Path | Purpose |
|---|---|---|
| POST / DELETE | `/items`, `/items/{id}` | proposed recurring items |
| POST / DELETE | `/expenses`, `/expenses/{id}` | proposed one-offs |
| POST | `/commit`, `/uncommit` | materialize / reverse |
| GET | `/impact?account_id=` | baseline vs scenario key figures |

`GET /scenarios` grows to return proposals alongside overrides, so the tab
loads a scenario in one request.

`/impact` returns, for baseline and scenario each: 3-month low and its date,
weekly safety margin, and ongoing monthly burn — reusing
`compute_budget_snapshot` and `_lookahead_minimum` rather than recomputing.
Burn reuses `/recurring/breakdown`'s `monthly_equivalent` helper, so a
scenario's burn figure and the Recurring page's agree by construction.

`POST /forecast/quarters-scenario` gains an optional `scenario_id`; when
present the server resolves the scenario itself. The current `overrides`
list stays supported — Forecast.tsx passes it today (`Forecast.tsx:343-354`)
and is not part of this spec's changes.

## 5. The Scenarios tab

New route `/scenarios`, new `frontend/src/pages/Scenarios.tsx`, nav entry in
the **Planning** group of `frontend/src/lib/navItems.ts` (alongside Budget,
Goals, Credit Cards, Forecast), using an icon not already in that file.

Layout, top to bottom:

- **Scenario list** — name, draft/committed badge, created date; buttons to
  create and delete. Selecting one loads it into the editor.
- **Editor** — three sections matching the three proposal types: proposed
  recurring items, proposed one-offs, amount tweaks on existing items. Each
  row is add/remove; the recurring form mirrors the fields of the Recurring
  page's own form, including end date and card routing, so the two feel like
  the same object.
- **Impact strip** — 3-month low, safety margin, monthly burn; baseline and
  scenario side by side with the delta, red/green by direction.
- **Chart** — baseline line plus the selected scenario. **Default is one
  scenario against baseline**; a multi-select adds further scenario lines for
  comparing options against each other, which the user asked for as available but
  not the default.
- **Commit button** — disabled on a committed scenario, which instead offers
  Uncommit behind a confirm dialog naming the lost-edits behavior above.

## 6. Testing

Backend, TDD:

- A proposed item forecasts **identically** to the same item created for
  real — the parity test that justifies the transient-object approach
- Forecasting a scenario persists nothing: row counts unchanged after
- A card-routed proposal reaches checking via the card's payoff, not on its
  own due date, and does **not** appear in the checking walk
- A card-routed proposal against a card with a manual `monthly_spend_estimate`
  changes nothing — pinning the behavior the form's warning describes
- A proposed item's `end_date` stops it, so a 24-month proposal doesn't run
  forever
- Commit creates rows and records links; a second commit is refused
- Uncommit removes exactly what it created, restores overridden amounts, and
  tolerates a row already deleted by hand
- `/impact` agrees with `compute_budget_snapshot` for the baseline case

Frontend: no test suite exists in this repo, so the bar is no new `tsc`
errors in touched files (measured before and after, since `bun run build`
does not exit 0 on this repo for unrelated pre-existing reasons). Live visual
verification is currently blocked — Interceptor's preflight fails on this
machine for want of a connected browser context — so it is explicitly not
claimed as done by this spec.

No migration tooling is used in this repo; new tables and columns are created
by `backend/database.py`'s startup DDL, matching how `forecast_day_checkpoints`
and `bill_amount_overrides` were added.

## Alternatives considered

**Proposals live in the real tables behind a `scenario_id` flag.** A proposal
would *be* a `RecurringItem` whose `scenario_id` is set; commit just nulls the
flag. Commit becomes trivial, but every existing query across
`forecast_engine`, `budget_snapshot`, `summary_generator`, `recurring.py` and
the spending routers must then filter `scenario_id IS NULL`, and any single
one missed leaks a hypothetical expense into real numbers — the daily email,
Left to Spend, Safety Margin. Rejected: the blast radius of a miss is the user's
real financial picture, and the failure is silent.

**The whole proposed delta as JSON on the scenario.** Fastest to build, but
unqueryable, no referential integrity, and the commit-link/undo story has
nowhere to live. Rejected.
