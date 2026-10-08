# Wish List: finding when a purchase fits the forecast — design

**Status:** approved in brainstorming on 2026-10-07. Waiting for the spec review.
**Replaces:** the Scenarios page, which becomes **Wish List** under Planning.

## Problem

Scenarios answers one question: what happens if I add X on a date I pick. What the user actually asks is different: *when* can I afford the new MacBook Pro, and is it better to pay in full or take 0% financing? Today the trade-in, the payment method and the card payoff timing all have to be worked out by hand. When several wishes compete for the same spare money, nothing shows a plan.

## Goals

- **Wish items in a ranked list.** Each item has a price, an optional trade-in, and optional extra costs that come with it (today's scenario pieces).
- **Several payment options per item, compared side by side:**
  - paid in full from checking
  - paid in full on a card, with the cost landing on that card's payoff date
  - financed: months, APR (0% allowed), a down payment, and the monthly payment from checking or a card
- **Earliest safe date for every option.** This is the first day in the next 12 months where the lowest projected checking balance from that day on stays at or above a **cushion**.
- **Stacking.** Each item's plan option is placed before lower-ranked items are evaluated, so the list reads as a plan.
- **Commit.** The plan option, on its date, becomes real forecast entries. Uncommit reverses it.

## Non-goals

- No online price or trade-in lookups. All values are typed in by hand.
- No changes to `forecast_engine.build_forecast`'s behaviour. The fit search overlays cash flows on one baseline walk.
- There are no promo-expiry or deferred-interest traps. A 0% plan is modelled as 0% for its whole term.
- There is no multi-account fit. Only the checking account that already drives the Forecast and Safety Margin counts.

## Approach

**Approach A, approved.** The existing `ForecastScenario` rows become wish items. The new data lives only in **new tables**: no ALTER on existing tables, and the tables are created by `create_all`.

The fit search computes the baseline forecast **once**. It then sweeps candidate dates by adding each option's cash-flow deltas to that baseline. It does not re-run `build_forecast` per date.

## Data model (new tables, scoped by `user_id`)

### `wish_items`
One row per scenario. The scenario stays the container for its existing building blocks.

| field | type | notes |
|---|---|---|
| id, user_id | | |
| scenario_id → forecast_scenarios | unique | |
| rank | int | 0 is the top item |
| price | Numeric(14,2), default 0 | 0 means a project defined only by its building blocks |
| trade_in_value | Numeric(14,2), default 0 | |
| trade_in_on | date, nullable | null means the credit applies at purchase and reduces the amount paid or financed. A date means it arrives later as a checking inflow on that date. |
| target_date | date, nullable | "I want it on". When set, it replaces the searched date for placement and stacking. |
| plan_option_id → wish_options, nullable | | The option used for stacking and commit. Null means the option with the earliest safe date, ties going to the lowest total cost. |

### `wish_options`

| field | type | notes |
|---|---|---|
| id, user_id, wish_item_id | | |
| label | str(64) | e.g. "Apple Card 0% / 12" |
| method | enum: `full_checking`, `full_card`, `financed` | |
| card_id → credit_cards, nullable | | Used by `full_card`. For `financed`, it means the monthly payment is charged to that card. |
| months | int, nullable | Required for `financed`, 1–84. |
| apr | Numeric(6,3), nullable | Required for `financed`. 0 is allowed. |
| down_payment | Numeric(14,2), default 0 | `financed` only. It leaves on the purchase date via the same route (checking, or the card's payoff date). |
| sort_order | int | |

### Setting
`WISH_CUSHION` is added to the `app_settings` registry as an int number of dollars. The default when it's unset is the checking account's `low_balance_threshold`, or **1000** if that is unset too.

### Existing scenarios
On first load of the Wish List, every scenario without a `wish_items` row gets one: price 0, rank after the existing items, no options. Its building blocks behave as before. With no options, the item is evaluated as a single implicit option that has no purchase cash flow.

## Rules (pure functions in `backend/services/wish_math.py`)

- **net_price** = max(price − trade_in_value, 0) when `trade_in_on` is null. Otherwise it is the price.
- **financed_principal** = max(net_price − down_payment, 0).
- **monthly_payment(principal, apr, months).** With apr = 0 it is principal ÷ months. Otherwise it is the standard amortization P·r / (1 − (1+r)^−n) with r = apr/12/100. The result is rounded to cents, and the **last** payment absorbs the rounding so the payments sum exactly to the amortized total.
- **total_cost** = down_payment + Σ payments (financed), or net_price (full). In both cases, minus a later trade-in credit if `trade_in_on` is set.
- **Cash-flow overlay** `option_flows(option, item, buy_date, cards) -> list[(date, Decimal)]`. Each entry is a signed checking delta: negative means money out.
  - `full_checking`: −net_price on buy_date.
  - `full_card`: −net_price on `forecast_engine._card_payoff_date_for_charge(card, buy_date)`.
  - `financed`:
    - The down payment is routed like a full purchase, through checking or the card.
    - Payment *k* (k = 1..months) falls on the buy-date day-of-month in month buy_date + k, clamped to the month's last day.
    - Payments from checking land on that date. When `card_id` is set, each payment lands on that card's payoff date for that charge date.
  - A later trade-in adds +trade_in_value on `trade_in_on`.
  - The item's **building blocks** (proposed recurring items, one-off costs, amount tweaks) keep the dates set in the scenario. They are **not** shifted by buy date, so they are a fixed overlay for the item whatever its placement. Their flows are computed once per item by running `build_forecast` with the item's proposal over the same window as the baseline and taking the day-by-day difference.
- **Low point** of a balance series over [d, horizon]: the same semantics as `budget_snapshot._lookahead_minimum`. A locked card payoff dip is not the floor.
- **earliest_safe_date(option, item, overlay_so_far, baseline, cushion, today, horizon=today+365).** This returns the first day d in [today, horizon − 30] for which low_point(baseline + overlay_so_far + option_flows(d)) over [d, horizon] ≥ cushion. If no day qualifies, it returns `None` together with the **best day**: the d that maximizes that low point, the low point itself, and the **shortfall** = cushion − low point.
- **Stacking.** Process items by rank:
  - An item's placement date is its `target_date` if set, otherwise its plan option's earliest safe date.
  - Add that option's flows at that date to `overlay_so_far` before evaluating the next item.
  - An item with no safe date and no target date is reported as "doesn't fit" and is **not** added to the overlay.
- **Committed scenarios** are part of the baseline, because they're real forecast rows. They are never re-placed.

## Lifecycle

- **Commit** (`POST /wish-list/items/{id}/commit`) happens at the placement date with the plan option. It reuses `scenario_service.commit_scenario` for the building blocks and adds the purchase:
  - full methods become one `PlannedExpense` on buy_date (with `card_id` for `full_card`), amount net_price
  - `financed` becomes a down-payment `PlannedExpense`, if non-zero, plus a monthly `RecurringItem` for the payment, with `start_date` buy_date + 1 month, `end_date` after the last payment, `card_id` if set, and amount = the regular payment, for months − 1 payments. The final payment, which carries the rounding adjustment, is a separate `PlannedExpense` on its date and routed the same way. If months = 1, there is only that one-off.
  - a later trade-in becomes an inflow `PlannedExpense` on `trade_in_on`

  The created ids are stored so that **uncommit** can delete exactly those rows, alongside the existing uncommit. Commit is refused if no safe date and no target date exist.
- **Delete item:** deletes the scenario (the existing cascade) plus its wish row and options. A committed item must be uncommitted first (409).

## API (`backend/routers/wish_list.py`, prefix `/wish-list`)

- `GET /plan`: ranked items, each with:
  - its options, and per option: earliest_safe_date, low point and date, monthly_payment, total_cost, best_day and shortfall when it doesn't fit
  - the placement date and the plan option
  - an explain receipt for the safe date (`ExplainBuilder` rows: baseline low, minus this option's flows, minus higher-ranked items, equals the low point vs the cushion)

  It also returns the cushion value. It creates missing `wish_items` rows for existing scenarios.
- `POST/PATCH/DELETE /items`, `POST /items/reorder` (`{ids: [...]}`).
- `POST/PATCH/DELETE /items/{id}/options`.
- `POST /items/{id}/commit`, `POST /items/{id}/uncommit`.
- `GET/PUT /cushion`.
- The existing `/scenarios/*` endpoints remain for the building-block editors.

Every endpoint checks ownership. Referenced card ids must belong to the user. Explicit null on required fields → 422.

## UI (`frontend/src/pages/WishList.tsx`)

- Nav: "Scenarios" becomes "Wish List" (route `/wish-list`). `/scenarios` redirects there.
- **Plan strip:** "MacBook Pro · Nov 3 → Grill · Jan 12", plus a cushion control.
- **Ranked item cards** with a drag handle, which calls reorder. Each card shows name, price, trade-in (value and timing) and an "I want it on" date. Option cards sit side by side, each showing:
  - label and method
  - earliest safe date, or "doesn't fit" with the shortfall and best day
  - monthly payment and total cost
  - the low point and its date
  - a "plan" radio
  - an ⓘ `HowCalculated` on the safe date

  An "Add option" control and an expand section hold the existing building-block editors and the existing projected-balance chart with the plan line. Commit and uncommit buttons are on the card.
- Every money value goes through `maskIfHidden`.

## Testing

- **Unit tests for `wish_math`:**
  - amortization at 0% and at a non-zero APR, where the payments sum exactly to the total
  - net price with a trade-in now vs later
  - flows for each method, including card payoff routing and month-end clamping
  - earliest safe date on a synthetic baseline: fits today, fits later, never fits with the correct best day and shortfall
  - stacking order changing the second item's date
  - target_date overriding the search
  - a locked payoff dip not counting as the floor
- **API tests:**
  - plan shape
  - existing scenarios become wish items
  - reorder
  - option validation, including financed with no months → 422
  - commit and uncommit create, then remove, exactly the right rows
  - user scoping
- tsc must stay at the baseline.
- **Interceptor run in the test profile:**
  1. Create "Interceptor test wish" with two options.
  2. Check that the safe dates render.
  3. Commit, then uncommit.
  4. Delete it.
  5. Confirm no rows are left behind.
  6. **Never** auto-accept `confirm()`.
- **Docs:** a Wish List section in docs/start-guide.md replacing the Scenarios text, and a line in docs/PRIVACY.md.

## Risks

- **Search cost.** 365 days × options × items over an in-memory series is cheap. The only expensive part is one baseline `build_forecast` plus one per item to capture its building-block flows. Results are cached per request.
- **Building-block deltas computed by diffing forecasts** can pick up unrelated noise if the forecast isn't deterministic. The engine is deterministic, so diff over the same window and engine call.
- **The live backend auto-reloads**, so back up before the implementers commit.
