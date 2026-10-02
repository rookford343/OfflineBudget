# Adventures: trip planning with points — design

**Status:** approved in brainstorming (2026-10-01). Waiting for the spec review.
**Where:** a new page, `/adventures`, under the **Planning** nav group.

## Problem

Trips get budgeted ad hoc. Each one is a single Planned One-Off, like the Holland vacation, so no checklist exists and costs get forgotten. There is also no record of credit-card and loyalty points. A trip's real cost depends on whether a flight or hotel is paid in cash or in points. Points can come from a bank program such as Chase Ultimate Rewards, either directly or transferred (often with a bonus) to an airline or hotel partner. An award such as "70,000 Virgin points + taxes" is points *and* a cash copay.

## Goals

- Plan a trip from a reusable checklist so nothing is forgotten. Items can be removed per trip and from the template.
- Track points balances by hand, per program, with a "last updated" age.
- For each item, compare cash against points, show the redemption value (¢/pt), and support a mix of the two.
- Model transfer partners (ratio plus an optional time-limited bonus) and suggest the cheapest way to cover a points shortfall.
- Planning a trip never touches the Forecast. **Committing** it feeds its remaining cash cost into the Forecast.
- An optional per-trip savings fund.

## Non-goals

- No online lookups. Award prices, partner lists and bonuses are typed in by the user, and the app stays offline.
- No automatic matching of bank transactions to trip items. Marking an item paid is a manual step, as it is for Planned One-Offs today.
- No changes to `forecast_engine.py`.
- Points valuation targets ("is 1.6¢ good?") are left out for now. The app shows ¢/pt only.

## Approach

**Approach A, approved.** A committed trip materialises as ordinary `PlannedExpense` rows, which the Forecast already understands: card routing, statement-cycle payoff, and settled rows dropping out. Every link lives on the **new** tables, so **no existing table is altered**. The new tables are created by `create_all`, and there are no `ALTER TABLE` statements on live data. The trip fund reuses `SavingsGoal`.

## Data model (all new tables, all scoped by `user_id`)

### `loyalty_programs`
| field | type | notes |
|---|---|---|
| id, user_id | | |
| name | str(64) | "Chase Ultimate Rewards", "Virgin Atlantic Flying Club" |
| kind | enum: bank, airline, hotel, other | |
| balance | int ≥ 0 | entered by hand |
| balance_updated_at | datetime, nullable | stamped whenever `balance` is written |
| is_active | bool | hidden from the wallet when false |
| sort_order | int | |

### `transfer_partners`
| field | type | notes |
|---|---|---|
| id, user_id | | |
| from_program_id → loyalty_programs | | |
| to_program_id → loyalty_programs | | from ≠ to; (from, to) unique per user |
| ratio | Numeric(8,4), default 1 | partner points received per source point |
| bonus_pct | Numeric(6,2), nullable | e.g. 30 for +30% |
| bonus_ends_on | date, nullable | the bonus is ignored after this date; with no end date it is active until removed |

### `trips`
| field | type | notes |
|---|---|---|
| id, user_id, name, destination | | |
| start_date, end_date | date | end ≥ start. nights = end − start; days = nights + 1 |
| travelers | int ≥ 1 | |
| status | enum: planning, committed, done | |
| default_card_id → credit_cards, nullable | | null means checking |
| fund_goal_id → savings_goals, nullable | | set when the optional fund is created |
| notes | text | |

### `trip_items`
| field | type | notes |
|---|---|---|
| id, trip_id, user_id | | |
| category | enum: getting_there, staying, daily, before, while_there | |
| name | str | |
| pricing | enum: flat, per_day, per_night, per_person, per_person_day | |
| unit_cash | Numeric(14,2) | the cash price per unit; **cash_price** is derived as unit × multiplier |
| payment | enum: cash, points, mix | |
| points_program_id → loyalty_programs, nullable | | required for points/mix |
| points_price | int, nullable | flat, entered as the total for the item |
| cash_copay | Numeric(14,2), default 0 | taxes and fees that are still cash on a points booking |
| mix_cash | Numeric(14,2), nullable | the cash part of a `mix` payment, on top of the points |
| charge_date | date, nullable | defaults to the trip's start_date when null |
| card_id → credit_cards, nullable | | overrides the trip's default card |
| transfer_from_program_id → loyalty_programs, nullable | | attached transfer plan |
| transfer_points | int, nullable | source points to transfer |
| is_paid | bool | |
| planned_expense_id → planned_expenses, nullable | | set while the trip is committed and the item owes cash |
| sort_order | int | |

The pricing multiplier is: flat = 1, per_day = days, per_night = nights, per_person = travelers, per_person_day = travelers × days.

### `checklist_template_items`
These are user-scoped. Each has category, name, pricing, default unit_cash (nullable) and sort_order. The starter set is seeded on first visit (see **Seeding** below):

- **Getting there:** Flights (per_person); Airport parking or rides; Checked bags (per_person); Rental car or trains; Gas & tolls
- **Staying:** Lodging (per_night); Resort / city taxes (per_night)
- **Daily:** Food (per_person_day); Local transport (per_day); Tips (per_day)
- **Before you go:** Passports / visas (per_person); Travel insurance; International phone plan; Dog boarding (per_night); Kid gear rental
- **While there:** Activities & tickets; Souvenirs; Buffer (flat, 10% of the trip's other cash; see Rules)

Removing a template item deletes the row, so it is gone for future trips. "Reset to starter list" re-seeds.

**Seeding.** On the first visit, an idempotent `ensure_adventures_seeded(db, user)` creates the template rows and the starter programs if the user has none:

- Chase Ultimate Rewards (bank)
- **Airlines:** Aer Lingus, Air Canada Aeroplan, Air France/KLM Flying Blue, British Airways, Emirates, Iberia, JetBlue, Singapore KrisFlyer, Southwest, United MileagePlus, Virgin Atlantic Flying Club
- **Hotels:** World of Hyatt, Marriott Bonvoy, IHG One Rewards

Each one has balance 0, and there is a 1:1 Chase → partner `transfer_partners` row for each. Programs whose balance is 0 and that are not in use are listed in a collapsed "Other programs" group in the wallet. Programs and template are seeded independently, each only when the user has zero rows of that kind. That makes seeding idempotent with no flag column, so `users` is not altered.

## Rules (pure functions in `backend/services/adventures.py`, unit-tested)

- **cash_price(item)** = unit_cash × multiplier.
- **cash_owed(item)**:
  - cash → cash_price
  - points → cash_copay
  - mix → mix_cash + cash_copay
- **points_used(item)** = points_price for points or mix, otherwise 0.
- **value_cpp(item)** = (cash_price − cash_copay) ÷ points_price × 100, rounded to 2 decimals.
  - Applies to points/mix items with points_price > 0.
  - For mix, it uses (cash_price − mix_cash − cash_copay).
  - It is None when the numerator is ≤ 0.
- **Buffer item.** A template item named Buffer with pricing flat and a null unit_cash is computed as 10% of the sum of cash_owed of the trip's other items, rounded to cents. If the user sets unit_cash, that wins.
- **effective_ratio(partner, today)** = ratio × (1 + bonus_pct/100) when bonus_pct is set and (bonus_ends_on is null or today ≤ bonus_ends_on); otherwise ratio.
- **source_points_needed(partner, target_points, today)** = ceil(target_points ÷ effective_ratio). It rounds **up**, so you are never short.
- **Reserved points per program** = sum over trips in planning or committed of:
  - points_used, where points_program_id = the program
  - transfer_points, where transfer_from_program_id = the program, which also **adds** the partner points to that partner's side for that item
- **available(program)** = balance − reserved.
- **Shortfall per program** for one trip = that trip's points_used for the program − (balance − points reserved by *other* trips) − partner points arriving from attached transfers.
- **suggest_transfer(item)**: when the item's program is short, look at every partner row with to = that program and an active source program. Pick the one needing the fewest source points that the source's available balance covers. Return (from_program, source_points, partner_points, bonus_applied) or None. The suggestion is advisory; "Attach" writes transfer_from_program_id and transfer_points.

## Lifecycle (`backend/services/adventures.py`, transactional)

- **planning → committed (`commit_trip`).** For each item with cash_owed > 0 and not is_paid, create a `PlannedExpense` with:
  - name: "<trip>: <item>"
  - amount: cash_owed
  - expected_date: charge_date or start_date
  - card_id: item.card_id or trip.default_card_id
  - direction: outflow

  Store its id on the item.
- **Editing a committed trip.** `sync_trip_planned_expenses(trip)` runs after every item or trip write. It reconciles one-to-one:
  - creates a missing row
  - updates amount, date and card on the linked row
  - deletes the linked row when cash_owed drops to 0 or the item is deleted

  Running it twice changes nothing (it is idempotent).
- **committed → planning.** Delete all linked PlannedExpense rows that are not settled, and null the links.
- **Mark paid (`is_paid=true`).** Set `settled_on=today` and `actual_amount=amount` on the linked PlannedExpense, so the forecast's existing `settled_on IS NULL` filter drops it. Marking it paid again is a no-op. Unmarking clears settled_on.
- **committed → done (`finish_trip`).** The request carries the confirmed points per program, prefilled from points_used plus transfers.
  - Apply the confirmed amounts per item:
    - The source program loses `transfer_points`.
    - The partner program gains the partner points received (source points × effective ratio on the finish date, floored).
    - The item's program loses the confirmed points used.
  - Refuse if any balance would go negative unless `force=true` (the UI asks).
  - Status becomes done, and reservations release because done trips aren't counted.
- **Deleting a trip.** Delete its unsettled linked PlannedExpenses first. Settled ones are left alone as history, with the link nulled.
- **Trip fund (`create_trip_fund`).**
  - Creates a SavingsGoal named "<trip> fund", target = the sum of cash_owed, target_date = start_date − 7 days, and sets fund_goal_id.
  - The target is recomputed only when the user presses "Update fund target"; it never silently changes a goal.
  - Removing the fund unlinks it and, if asked, deletes the goal.

## API (`backend/routers/adventures.py`, prefix `/adventures`)

| Endpoints | Purpose |
|---|---|
| `GET/POST/PATCH/DELETE /programs`, `/partners`, `/template` | Wallet and template CRUD. A PATCH on `balance` stamps balance_updated_at. |
| `GET /wallet` | Programs with balance, reserved, available and age in days. |
| `GET/POST /trips`, `GET/PATCH/DELETE /trips/{id}` | The trip detail returns items with the derived fields (cash_price, cash_owed, points_used, value_cpp, suggestion) plus totals: cash, points per program, shortfalls, paid vs remaining. |
| `POST /trips/{id}/items`, `PATCH/DELETE /trips/{id}/items/{item_id}` | Item CRUD. |
| `POST /trips/{id}/commit`, `/uncommit`, `/finish` | Lifecycle. |
| `POST /trips/{id}/fund`, `DELETE /trips/{id}/fund` | The optional fund. |

Creating a trip copies the template into items. Per-day and per-person items keep their pricing, so they follow later date and traveler edits. Every endpoint checks `user_id` ownership.

## UI (`frontend/src/pages/Adventures.tsx` plus components)

- Nav: add "Adventures" (Plane icon) under Planning in `lib/navItems.ts`, plus the route in `App.tsx`.
- **Wallet strip.** One chip per active, in-use program, showing balance, "N available" when reserved > 0, and an "updated Nd ago" age that turns amber after 30 days. Balances can be edited inline. A "Partners & bonuses" dialog lists partner rows with editable ratio, bonus % and end date; expired bonuses show struck through. "Other programs" is collapsed.
- **Trip list.** Cards with name, destination, dates, a status pill, cash remaining, points by program, and fund progress if there is a fund. A "New adventure" button.
- **Trip detail.**
  - The header holds name, dates, travelers, default card and status actions.
  - Items are grouped by the five categories. Each row has name, pricing hint, a cash/points/mix segmented control, the fields that apply, a ¢/pt badge, an attached or suggested transfer line, a paid checkbox (once committed) and a remove (×) button.
  - "Add item" sits per category, and "Remove from template too" is offered on remove.
  - A sticky totals bar shows cash owed, points per program and shortfalls in red.
  - "Commit to forecast" carries an explainer that says it will add N one-offs to the Forecast.
- Masking: all money **and points** values go through `maskIfHidden(useBalancesHidden(), …)`.
- Explain affordance: the totals bar's cash figure gets an ⓘ `HowCalculated` listing each item's cash_owed.

## Testing

- **Backend.** A new file, `tests/test_adventures.py`, with generic data because the repo is public:
  - multipliers
  - cash_owed for each payment mode
  - value_cpp, including the None cases
  - effective_ratio with and without an expired bonus, and on the end date itself
  - ceil rounding
  - reserved and available across two trips
  - shortfall net of attached transfers
  - suggest_transfer picking the fewest source points and skipping sources that can't cover it
  - the buffer at 10%
  - commit creating the exact PlannedExpenses (amount, date, card)
  - sync after edit, idempotent
  - uncommit removing unsettled rows only
  - mark paid settling the linked row, plus the forecast dropping it, through `build_forecast` on a tiny fixture
  - finish deducting points, refusing to go negative without force
  - delete cleaning up
  - fund creation and target
  - seeding being idempotent
  - user scoping on every router
- **Frontend.** The tsc gate stays at baseline, and new files add 0 errors.
- **Interceptor run in the test profile.** Create a trip, toggle an item to points, attach a transfer, commit (the one-offs appear on the Forecast), mark one paid, uncommit, and confirm there are no console errors.
- **Docs.** `docs/USER_GUIDE.md` gets an Adventures section, and `docs/PRIVACY.md` gets "points balances and trips are stored locally only".

## Risks

- **The live backend auto-reloads.** New tables are created against the live DB as soon as models land. They are additive, but back up before the implementers commit (memory: uvicorn --reload auto-migrates).
- **Stale points balances** are a known trade-off of manual entry. The age badge exists to surface them.
- **The partner list drifts** as Chase changes partners. It is fully editable, and nothing depends on it being current.
