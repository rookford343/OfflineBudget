# Subscription Rollups, Triage Inbox & Left to Budget — Design

Dan wants recurring bills to roll up into a few meaningful groups instead of
a flat, half-labelled list: house bills (electric, gas, internet, water,
trash, HOA) under **Home**, and non-essential services (Netflix, Hulu, HBO,
fitness apps) under **Subscriptions**. Unknown recurring charges need a quick
way to be classified, and that classification has to feed reporting.
Whatever is left each month after those commitments is then assigned out to
a handful of high-level buckets.

What exists today, and why it falls short:

- The category tree is already two levels (`Category.parent_id`,
  `backend/models.py:202`), e.g. Necessities → Utilities. Nothing is wrong
  with the structure; the data in it is.
- Roughly half of the active expense recurring items have **no category**,
  so they are invisible to any category-based report.
- The "Subscriptions" category mixes streaming with lawn care, pest control
  and a vet plan, and carries a manual budget allocation **on top of** bills
  that already sit inside `leftover` — a double count.
- Some recurring items look duplicated (same merchant entered twice under
  different names).
- `budget_snapshot.py:331` already computes `leftover` (income − recurring
  expenses − committed savings − groceries), but nothing lets the user split
  it into buckets or see what is still unassigned.

Approach chosen (from brainstorming, over a three-level tree and a separate
"groups" layer): **keep the two-level tree, and get three-level reporting by
drilling a category into its recurring items.** See
[Alternatives considered](#alternatives-considered).

## Scope

In:

1. Category restructure: Utilities → **Home**; Subscriptions narrowed to
   non-essential services. Seed data updated.
2. A **"Needs a home" triage inbox** on the Recurring page with best-guess
   classification, merchant-rule learning, dismissals and duplicate marking.
3. A **Left to budget** bar and committed/assignable breakdown on the Budget
   page, with three-level drill-down (group → category → bill).
4. A per-user **carry-forward** setting for assignable budgets, default off.

Out (deliberately):

- A third level in the category tree.
- Auto-merging duplicates or auto-deleting anything.
- Percentage-based or rule-based auto-allocation of the leftover.
- Any change to `leftover`, Left to Spend, Safety Margin or the forecast.

## 1. Categories and data

### Restructure

- **Necessities → Home.** The existing Utilities category is **renamed** to
  Home (same row, same id), so every existing link — recurring items,
  transactions, rules, allocations — keeps working. House-related items
  (trash, stormwater, HOA, lawn, pest control) are assigned to Home through
  the triage inbox, not by a migration.
- **Wants → Subscriptions** keeps its name and row but is narrowed to
  non-essential services: streaming, music, fitness and wellness apps,
  software. Items that are not that (e.g. a vet wellness plan) are moved out
  via the inbox.
- `backend/seed.py` creates Home (not Utilities) and Subscriptions for new
  installs, so a fresh database starts with the new shape.

The rename is the only direct data change. It ships as an idempotent
step in `database.upgrade_categories()`: rename a category named
`Utilities` whose parent is `Necessities` to `Home`, once, per user; skip if
a `Home` sibling already exists.

### No new category columns

- `Category.is_discretionary` still means "steerable this month" and still
  drives the Spending page's Fixed/Discretionary split.
- Which buckets are **assignable** from the leftover is derived, not stored
  (section 3).
- Merchant learning reuses `TransactionRule` with
  `action = set_category`, `field = merchant`, `pattern_type = contains`.

### Three-level reporting without a third level

The Budget page's committed list drills **group → category → bill** over
`RecurringItem` rows: each committed category expands into the bills that
make it up, with each bill's amount for that month.

This is a **planned** view, not an actual-spend view. An actual-spend
drill-down by bill is out of scope: `CreditCardTransaction` has no
`recurring_item_id` column, so card-paid bills (most subscriptions) could
not be attributed to a bill without a new linking mechanism. The existing
merchant breakdown (`/budget/category-breakdown`) remains the actual-spend
view per category.

## 2. "Needs a home" triage inbox

Lives at the top of the Recurring page, collapsed to a badge when empty.

### Row sources

1. **Uncategorized items** — active `RecurringItem` rows of type `expense`
   with `category_id IS NULL`.
2. **Untracked patterns** — `recurring_detector.detect_patterns()`
   suggestions not yet tracked and not dismissed.
3. **Possible duplicates** — pairs of active expense recurring items whose
   normalized merchant (`merchant_normalizer`) matches, or whose names match
   after normalization, with amounts within 10% and the same frequency.

### Best guess

Resolved in order, first hit wins:

1. An active `TransactionRule` (`set_category`) matching the item's name or
   a linked transaction's merchant.
2. The `auto_categorizer` keyword table, with every existing `Utilities`
   target retargeted to **Home** and specific home keywords added
   (electric, natural gas, water & sewer, stormwater, waste management,
   republic services, hoa fee, hoa dues, homeowners assoc, metronet, lawn,
   landscap, pest, greenix, terminix). Bare words such as "gas", "water" or
   "hoa" are deliberately excluded — the same table categorizes every
   imported transaction, and those would catch gas stations and "hoagie".
   The
   existing streaming keywords remapped from the old Subscriptions meaning
   to the narrowed one (they still land in Subscriptions).
3. No match → the picker is shown **blank**. No low-confidence guess.

### Actions per row

| Action | Effect |
|---|---|
| **Confirm** guess / **Pick** category | Set `category_id`; create merchant rule if none matches; backfill (below). For an untracked pattern, create the `RecurringItem` via the existing create path with that category. |
| **Not recurring** | Insert a `RecurringDismissal` row so the pattern never reappears. Untracked patterns only. |
| **Duplicate of…** | Set `is_active = False` on the chosen item. Never deletes. Re-link its transactions' `recurring_item_id` to the kept item. |
| **Not a duplicate** | Insert a `RecurringDismissal` with key `dup:<low_id>:<high_id>` so that pair is never flagged again. |

Duplicate detection is a heuristic flag only: two active expense items with
the same frequency, amounts within 10%, and the same first significant word
(≥ 4 letters) of their normalized name.

**Backfill rule:** after classifying an item, set `category_id` on its linked
transactions (`recurring_item_id = item.id`) **only where `category_id` is
NULL**. A category set by hand or by an earlier rule is never overwritten.

### New table

```
recurring_dismissals
  id           int pk
  user_id      int fk users.id
  pattern_key  str(256)   -- the detector's normalized description key
  created_at   datetime
  UNIQUE (user_id, pattern_key)
```

`detect_patterns()` filters out any suggestion whose key is dismissed.

### API

- `GET  /api/recurring/triage` → `{ uncategorized[], untracked[], duplicates[], unclassified_count, unclassified_monthly_total }`
- `POST /api/recurring/triage/classify` → `{ recurring_item_id | pattern_key, category_id }`
- `POST /api/recurring/triage/dismiss` → `{ pattern_key }`
- `POST /api/recurring/triage/duplicate` → `{ keep_id, deactivate_id }`

### Visibility

A badge — "N unclassified · $X/mo" (smoothed monthly cost via
`recurring_math.monthly_equivalent`, so a yearly bill reads as 1/12 of
itself every month rather than spiking once a year) — on the
Recurring nav item and on the Budget page's committed list, so unknowns are
never silently missing from rollup totals.

## 3. Left to budget

Top of the Budget page.

### The number

`leftover` from `budget_snapshot`, **unchanged**. It already subtracts every
active expense recurring item regardless of category, so classifying items
changes how the committed total is **broken down**, never the total itself.

### Committed (read-only)

- Every category with active expense recurring items, amount = sum of each
  item's **leftover share** for the month — exactly what `_monthly_expenses`
  counts for it (monthly in full, quarterly ÷ 3, yearly in full only in its
  due month). Using the same per-item rule is what makes committed +
  leftover reconcile to income to the cent. Expandable to the individual
  bills.
- An **Unclassified** row for recurring items with no category (links to the
  inbox).
- **Savings** and **Groceries** at their allocation amounts, resolved exactly
  as today (`_budget_allocation_total`, month-specific over month=0). These
  are already subtracted in `leftover`.

Because Subscriptions' amount now comes from its bills, its old manual
allocation is no longer read by this page. The row is left in place, not
deleted.

### Assignable buckets

A category is assignable when **all** hold:

- expense type, `is_discretionary = True`
- a leaf (no child categories — excludes group rows like Wants)
- no active expense recurring items
- not Savings or Groceries (already subtracted in `leftover`)

For the current data this is Food & Drinks, Shopping, Entertainment, Travel,
Other. The rule is what prevents the Subscriptions double count.

### The bar

`leftover` → assigned (sum of assignable allocations for the month) →
**unassigned**. Green at $0.00, amber when positive, red when negative
(over-assigned). Editing a bucket writes a month-specific `BudgetAllocation`
row (`month = 1..12`).

### Carry-forward setting

- New `User.budget_carry_forward: bool`, default **False** (added via an
  `ALTER TABLE users ADD COLUMN budget_carry_forward BOOLEAN DEFAULT 0` line
  in `database.upgrade_schema()`), surfaced in
  Settings as "Carry budget amounts into the next month".
- **Off:** assignable buckets resolve from the month-specific row **only**.
  No row → $0 / "not assigned yet". Existing month=0 rows are ignored for
  assignable buckets but **kept** in the database.
- **On:** month-specific row, else month=0 row — today's behaviour.
- Committed categories, Savings and Groceries are **unaffected** either way.

One helper, `budget_buckets.drop_uncarried_defaults(allocations, user,
assignable_ids)`, applies this rule to an already-fetched allocation list and
is used by `budget_calculator.compute_overview`, `routers/spending.py`
budget-vs-actual, and the new Budget page endpoint, so
the Spending page and weekly email show "not assigned yet" consistently
rather than each re-implementing the fallback.

Consequence, accepted: with the setting off, on the 1st of each month the
Spending page and weekly email show assignable buckets as not assigned until
the user assigns them.

### API

- `GET /api/budget/left-to-budget?year&month` →
  `{ leftover, committed[{category, amount, items[]}], unclassified{count, amount}, assignable[{category, assigned}], assigned_total, unassigned }`
- Existing allocation create/update endpoints handle bucket edits.

## Error handling

- Classify with a category that belongs to another user or is income type →
  400.
- Duplicate with `keep_id == deactivate_id`, or either inactive → 400.
- Dismiss is idempotent (unique constraint; repeat returns 200).
- Rename migration is idempotent and a no-op when `Home` already exists.
- Left-to-budget with no income items still returns a valid payload (negative
  unassigned, red bar), not an error.

## Testing

Backend (pytest, TDD):

- **Guard:** `leftover`, `left_to_spend` and Safety Margin are byte-identical
  before and after classifying items and toggling carry-forward.
- Assignable rule: a discretionary category with a recurring item is not
  assignable; Savings and Groceries are never assignable.
- Carry-forward off: month=0 row ignored for assignable, still honoured for
  Savings/Groceries. On: month=0 fallback works.
- Classify: sets category, creates one rule (not a duplicate rule on repeat),
  backfills only NULL-category transactions.
- Dismiss hides the suggestion from `detect_patterns()`.
- Duplicate: deactivates, re-links transactions, never deletes.
- Best guess: rule beats keyword; no match returns no guess.
- Rename migration: idempotent; skips when Home exists.

Frontend: verified in real Chrome with Interceptor — inbox classify flow,
badge counts, Budget page bar colours, drill-down, Settings toggle.

## Alternatives considered

- **Three-level tree** (Necessities → Home → Electric as real
  sub-categories). Finer native reporting, but budget calculator, Spending
  page, auto-categorizer and email reports all assume two levels. Recurring
  items already carry per-bill identity, so the drill-down gets the same view
  for a fraction of the blast radius. Dan preferred the three-level reporting
  view, which the drill-down provides.
- **Separate "Groups" layer** over categories. Most flexible, but duplicates
  what the tree already does. Rejected under YAGNI.
- **Carry-forward always on.** Rejected at Dan's request; it is a per-user
  choice, default off.
