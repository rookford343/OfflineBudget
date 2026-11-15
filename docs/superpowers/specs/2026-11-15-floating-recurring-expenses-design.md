# Floating Recurring Expenses, Owner Tags, and Per-Account Category Totals — Design

## Intent and why

Two expenses don't fit OfflineBudget's current recurring model: House Cleaning (budgeted, happens most months, but the exact day is unknown and some months it's skipped for scheduling or money) and Dan's haircut (not budgeted at all today — decided same-day, absorbed into discretionary spending). Both recur but don't have a fixed date, so pinning them to a `day_of_month` either misrepresents when the money actually moves or, for haircuts, isn't tracked at all.

While scoping this, two more gaps surfaced that Dan wants addressed on the same page: there's no way to see, at a glance, which household member an expense belongs to (so "what am I spending on myself vs. the family" has no answer), and no way to see category totals broken out per account/card on the Recurring page (today's "By Category" rollup mixes every account together).

## Goals

- A recurring expense can be marked **floating**: budgeted monthly, but the real charge can land on any day that month and still auto-match to the budget line (pattern + amount, not date-pinned).
- A floating item can be **skipped** for a specific month without deactivating it permanently.
- Each recurring item carries an **owner** (Family by default, or a named household member), for spending-by-person breakdowns.
- The Recurring page shows, at a glance, **category totals per account/card**.
- House Cleaning converts to floating. Dan's Haircut ($45/mo, credit card) is added as new, floating, owner = Dan.

## Non-goals (this round)

- Wife's haircut: owner infrastructure supports it, but it doesn't get created now — amount is unknown and it's quarterly, which this round's matching window doesn't cover. Future work.
- Floating support for quarterly/yearly items. The matching-window widening below is monthly-only; quarterly/yearly keep today's ±3-day matching.
- Changing *when* in the month a floating item's modelled cash-flow dip shows up in the day-by-day forecast (Dashboard lowest-balance, daily email). It keeps using `day_of_month` as today. Only *matching* (linking the real charge once it posts) changes.
- Redesigning the existing category-rollup hierarchy (parent/child categories) — separate, already-logged idea, not touched here.

## Current state (verified by reading the code, not assumed)

- `RecurringItem` (`backend/models.py:288`) already has everything needed except a floating flag and an owner: `day_of_month`, `account_id`, `card_id`, `category_id`, `is_active`.
- Checking-side auto-matching already exists and is sophisticated: `import_service.py:_best_recurring_match` scores a transaction against active recurring items using shared payee words + learned history (`_payee_history`) + amount tolerance (±15%, `_AMOUNT_RATIO`) + a date window — **±7 days around the item's `day_of_month` when the name matches, ±3 otherwise** (`_MATCH_WINDOW_DAYS = 7`, line 56). This window is the reason House Cleaning can fail to link today if the real charge doesn't land near the end of the month.
- Once a transaction links via `recurring_item_id`, `forecast_engine.py` (lines 1260–1270) suppresses the modelled placeholder for that item **for the rest of that calendar month** — this check is already month-wide for `monthly`/`yearly` frequency, not day-specific. So the only fix needed for checking-side floating is widening the *matcher's* window, not the forecast's suppression logic.
- Credit-card transactions have **no equivalent at all**. `CreditCardTransaction` (`backend/models.py:536`) has no `recurring_item_id` column, and the card-side import/sync path only assigns a `category_id` (via `auto_categorizer.py` / `rules_engine.py`), never links to a `RecurringItem`. This is new machinery, not a widened version of something that exists.
- This asymmetry is lower-risk than it sounds: `month_base.py:card_bills_from_base` already nets the *modelled* amount for any card-linked expense item out of real card spend every month, regardless of whether a transaction has linked to it (`o.card_id is not None and (include_proposed or (o.recurring_item_id or 0) > 0)`, line 168). So a card-side floating item (the haircut) is **not** at risk of double-counting in Leftover/Safety Margin today or after this change — the new card-side linkage is purely for the status/variance display Dan asked for, not a correctness fix.
- `RecurringCategoryRollup.tsx` groups by parent/child category only, with no account dimension — confirmed by reading `backend/routers/recurring.py:get_breakdown` (lines 127–240), which groups strictly by `category.parent_id`. A separate, unrelated per-source breakdown exists for *actual spending* on the Spending page (`breakdown_by_source`, `backend/schemas.py:1204`), keyed by account/card name — useful as a shape precedent, not reusable code (it's computed over transactions, not `RecurringItem`s).
- There is no existing "skip this occurrence" mechanism anywhere in the recurring/forecast code. `BillAmountOverride` records an *actual amount*, not an absence.

## Design

### 1. Floating expenses

- Add `RecurringItem.is_floating: bool`, default `False`. Existing items unaffected.
- `day_of_month` stays required and keeps driving the forecast's assumed placeholder day — unchanged for a floating item. (House Cleaning keeps `day_of_month = 0`; Dan's Haircut gets a placeholder day the builder can default sensibly, e.g. mid-month, since it's cosmetic for a floating item and editable like any other field.)
- **Checking-side matching** (`import_service.py:_best_recurring_match`): when `item.is_floating`, skip the `±window` day-of-month proximity check and instead require only that the item is due *somewhere* in the transaction's calendar month (reuse the existing active/frequency/start/end checks already present; monthly-only per Non-goals). Name/history evidence and the ±15% amount tolerance still apply unchanged — those are what keep a wrong match from happening once the date window is gone.
- **Forward-looking only, confirmed with Dan.** `_try_auto_match` only runs when a `Transaction` row is created (import/sync), so flipping `is_floating` does nothing for a transaction already imported under the old window. No backfill step is needed: Dan already reconciled this month's House Cleaning charge by hand via the existing `/recurring/{id}/link-pattern` fallback, so this round only needs to fix matching for charges that import *after* the flag is set.
- **Card-side matching (new)**: add `CreditCardTransaction.recurring_item_id: int | None` (FK to `recurring_items.id`, nullable). Build a card-side matcher parallel to `_best_recurring_match` — same evidence-token/amount-tolerance approach, scoped to `RecurringType.expense` items with `card_id` set — and run it wherever `CreditCardTransaction` rows are created (CSV import and card bank sync; the implementer locates the exact call sites). Only items with `is_floating = True` need this for now, since non-floating card items aren't in scope, but there's no reason to gate the matcher itself on the flag — it's the same shape of problem either way.
- Flag for review: ±15% amount tolerance may be too tight for a haircut (tip variance). Builder's call whether to parameterize this per-item or widen it specifically for floating+card items; either is acceptable, just don't silently reuse the untested checking-side constant without checking it against this case.

### 2. Skip this month

- New table `RecurringSkip`: `id`, `user_id`, `recurring_item_id` (FK), `year`, `month`, `created_at`. Unique on `(recurring_item_id, year, month)`.
- `month_base.py:build_month_base` excludes an item from `monthly_bills`/`periodic_due` for a `(year, month)` that has a matching `RecurringSkip` row — same shape as the existing `overrides` dict built from `BillAmountOverride` (lines 196–203). Because Leftover and Safety Margin both read off `build_month_base`'s output, skipping an item automatically frees up its budgeted amount with no separate change needed in `budget_snapshot.py`.
- `forecast_engine.py`'s day-walk needs the same skip-set consulted before an item fires, for the same `(item, year, month)` — this is the second place `RecurringItem` occurrences get generated, and it must agree with `month_base` or the cross-tab mismatch problem already logged in memory (dashboard vs. forecast vs. month-in-review disagreeing) recurs.
- New endpoints: `POST /recurring/{id}/skip` and `DELETE /recurring/{id}/skip`, body `{year, month}`.
- UI: a "Skip this month" toggle on the Recurring page, scoped to whichever month `RecurringSummaryStrip` is currently showing (it already tracks `year`/`month` state) — only shown for floating items.

### 3. Status display (floating items only)

For the month currently being viewed, each floating item shows one of:
- **Matched** — linked transaction's date, actual amount, and variance against the budgeted amount.
- **Pending** — no link yet, not skipped; still expected.
- **Skipped** — this month's `RecurringSkip` row exists.

Scoped to floating items only — non-floating items keep their current display (next due date / `overridden` "actual" tag) rather than redesigning the whole table.

**My call on skip/match precedence:** a match always wins. If a transaction links to an item for a month that already has a `RecurringSkip` row (money moved after all, or the skip was entered in error), the match overrides it — status shows Matched and the stale skip row is cleared, since a real linked charge is ground truth and a lingering "Skipped" status next to a Matched one would recreate the cross-tab disagreement problem this design is trying to avoid elsewhere.

### 4. Owner tags

- New table `HouseholdMember`: `id`, `user_id`, `name` (unique per user), `linked_user_id: int | None` (FK to `users.id`, nullable, unique), `created_at`. Nothing seeded — "Family" is a display-layer default/fallback label when an item's `owner_id` is null, not a row that could be deleted and orphan references.
- `linked_user_id` is the tie-in point for the app's existing login-linking feature (`User.linked_to_user_id`, Settings → Household). Dan's wife has no login today, so every `HouseholdMember` row starts with `linked_user_id = null` — a plain label. When she gets her own login later, her `HouseholdMember` row gets `linked_user_id` set to her new `users.id`, without a schema change. What that link is *used for* (e.g. restricting her view to her own tagged items) is explicitly out of scope for this round — the column exists so this round's data doesn't need re-keying later.
- `RecurringItem.owner_id: int | None`, FK to `household_members.id`, nullable, null = Family.
- Recurring page item form: an "Owner" select — Family, each existing `HouseholdMember`, and "+ Add person" (prompts a name, creates the row via a small new endpoint, selects it). Open-ended per Dan's answer — no fixed list of names.
- A rollup grouping monthly total by owner (Family bucket + each named person → items), same collapse/expand pattern as `RecurringCategoryRollup.tsx` but one level deep, not nested into categories too — this is a second independent axis on the same items, not a merge of the two breakdowns.

### 5. Per-account category totals

- Extend `GET /recurring/breakdown`'s response (`RecurringBreakdown` schema) with a second grouping, `by_account`, shaped identically to today's `by_category` (`RecurringCategoryGroup` list) but grouped by `account_id`/`card_id` → category → items, instead of by parent category. Reuses the same category-nesting logic already in `get_breakdown`, just keyed one level higher by account/card instead of by parent category.
- New frontend component `RecurringAccountRollup.tsx`, structurally identical to `RecurringCategoryRollup.tsx`, fed by `breakdown.by_account`, placed alongside it on the Recurring page.

## Data model changes (migrations)

- `recurring_items.is_floating BOOLEAN NOT NULL DEFAULT false`
- `recurring_items.owner_id INTEGER NULL REFERENCES household_members(id)`
- new table `household_members` (includes `linked_user_id INTEGER NULL UNIQUE REFERENCES users(id)`, unused until a second login exists)
- new table `recurring_skips`
- `credit_card_transactions.recurring_item_id INTEGER NULL REFERENCES recurring_items(id)`

## Constraints (carried from the project's standing rules)

- No real balances/amounts/dates/merchant names in commits, tests, or this document — only invented placeholders (already followed above).
- Backend: `uv run --locked`, ruff (Bandit `S` + Pyflakes `F`) clean, coverage floor never lowered.
- Frontend: `bun`, `bunx vite build`, no new client-side money arithmetic (`frontend/tests/moneyGuard.test.ts`) — variance display (`actual − budgeted`) must be computed server-side and returned as a field, the same pattern the dashboard parity work just used for `move_to_checking_needed`.
- Any UI change verified live via Interceptor before being called done.
- Commits go directly to `main`; no feature branches.

## Review focus (most likely to bite if missed)

1. A `RecurringSkip` consulted in `month_base.py` but not in `forecast_engine.py` (or vice versa) — reintroduces the exact "numbers disagree across tabs" failure mode already seen in this codebase (Dashboard vs. Forecast vs. Month-in-Review).
2. Checking-side floating match widening must be proven with a test where the actual lands *outside* the old ±7-day window and still suppresses the modelled placeholder for that month — this is the concrete bug Dan is hitting today.
3. Card-side matcher must not retroactively link historical card transactions to a newly-floating item in a way that changes past months' already-reported numbers — scope it to transactions from item-creation forward, or review why not.
4. `owner_id` defaulting to Family (null) must not break any existing rollup or export that assumes every item has a non-null grouping key.
5. The new `by_account` grouping must exclude `credit_card_payment`-type items the same way `by_category` already does (`get_breakdown` line 186-190 comment) — otherwise a card's payoff appears twice: once as the card's own "account" bucket and once double-counted against the spending it already pays off.

## What's left to the builder

- Exact placeholder `day_of_month` default for new floating items (any reasonable default is fine; not load-bearing).
- Exact amount-tolerance value for card-side floating matching (flagged above as worth checking against real data, not hard-coding the checking-side constant unexamined).
- Exact call sites where `CreditCardTransaction` rows are created (CSV import, bank sync) — locate and wire the new matcher into both.
- Frontend layout details for where the owner picker and skip toggle live in the existing item form/table (follow the form's existing patterns in `Recurring.tsx`).
