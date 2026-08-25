# Navigation Shell Uplift — Design

Sub-project 1 of 2 in the Securo-inspired frontend uplift (re-scoped
2026-08-24 after the first Phase 1 attempt was reverted for landing poorly —
see `ISA.md` Decisions log and `docs/securo-comparison.md`). Sub-project 2
(Dashboard & Component Polish — the original F1–F8 plus the transaction
modal redesign, donut/legend pattern, and hide-balances toggle) is a
separate spec, scoped after this one ships.

## Why this one first

This sub-project touches `Layout.tsx`, which every page in the app renders
inside. Landing its shape before polishing individual pages avoids
restyling twice. It's also the concrete thing Dan opened with (account
balances in the sidebar), so it's the highest-confidence starting point.

## Scope

Four parts, all frontend-only, all reusing existing backend endpoints:

1. Account list in the left sidebar
2. New Account Detail page (`/accounts/:id`)
3. Regrouped Settings tabs
4. Month/year popover picker on the Budget page

**Explicitly deferred (not this pass):** a balance-history trend chart on
the Account Detail page — would need new backend history data; flagged as
a fast-follow candidate, confirmed with Dan as out of scope for v1.

## 1. Account list in the sidebar

**Where:** `frontend/src/components/Layout.tsx`, in the sidebar, below the
existing nav groups (matches the reference pattern's sidebar-footer
placement).

**Data:** `useQuery(["accounts"], accountsApi.list)` — this query already
exists and is used elsewhere in the app (Dashboard, Forecast, etc.); Layout
gains its own instance. React Query dedupes identical in-flight/cached
queries by key, so this doesn't double-fetch if another mounted page
already holds the same query.

**Render:** account name + `current_balance` (formatted per existing
currency-formatting convention used elsewhere in the app), one row per
account, sorted by `type` then `name` (checking/savings before credit
cards — matches how accounts are already grouped in `AccountsTab.tsx`,
confirm exact order against that file during implementation rather than
inventing a new order).

**Overflow:** cap visible rows at 4, "+N more" link expands the rest
in-place (no navigation) — same overflow idiom as the donut/legend pattern
in sub-project 2, so the app uses one overflow convention throughout rather
than two.

**Interaction:** each row is a `<Link>` to `/accounts/:id`. No filtering
side-effect on the current page — confirmed with Dan this is direct
navigation, not a global account-scope filter.

**Dark/light:** must use the same `dark:` variant convention as the rest of
`Layout.tsx` — no new color tokens introduced without a paired dark variant.

## 2. Account Detail page

**Route:** `/accounts/:id`, new `frontend/src/pages/AccountDetail.tsx`,
registered in the app's router alongside the other page routes.

**Data — zero new backend endpoints:**
- Account header: `GET /accounts/{account_id}` — confirmed to already
  exist (`backend/routers/accounts.py:34-35`). Use this directly rather
  than filtering the full `accountsApi.list()` result client-side; add the
  matching `accountsApi.get(id)` client method alongside the existing
  `list`/`create`/etc. in `api/index.ts`.
- Recent transactions: `transactionsApi.list({ account_id })` — the
  backend already supports `account_id` filtering (confirmed in
  `backend/routers/transactions.py:34-46`), so this is a parameter this
  page passes, not new server work. Cap to the 25 most recent
  (`expected_date`/transaction date descending — match existing
  Transactions page's default sort).

**Render:**
- Header: account name, type (checking/savings/credit card/etc.), current
  balance — balance stays visually large/headline-styled, consistent with
  the app's existing progressive-disclosure identity (one dominant number,
  detail below).
- Body: recent-transactions list. Reuse the existing transaction row
  rendering from `Transactions.tsx` if it's already a separable
  component; if it isn't, extract the row markup into a small shared
  component as part of this work rather than duplicating the JSX (matches
  the "extract on second use" pattern already established with
  `CategoryProgressBar` from the reverted attempt).
- Footer: "View all in Transactions →" link to `/transactions` (plain
  navigation — Transactions.tsx does not currently support a URL-param
  account pre-filter, and adding one is out of scope here; confirm with
  Dan separately if that link should pre-filter in a later pass).

**Error handling:** invalid/nonexistent `:id` (e.g. direct URL entry, or an
account deleted after the sidebar link was rendered) shows a not-found
state with a link back to the dashboard, rather than a blank page or an
unhandled query error.

## 3. Regrouped Settings tabs

**Where:** `frontend/src/pages/Settings.tsx` — currently nine flat tabs
(`profile`, `preferences`, `accounts`, `notifications`, `categories`,
`tax`, `household`, `danger`, `verification`).

**Grouping** (matches the reference pattern's who-it-affects logic, applied
to OfflineBudget's actual tab set rather than copied verbatim):

- **Profile** — Profile, Preferences, Notifications
- **Money** — Accounts, Categories, Tax, Household
- **Data & Trust** — Verification
- **Danger Zone** — Danger Zone (own section, red/destructive styling
  preserved, own divider above it — matches the reference pattern's
  treatment of its own destructive action)

No routes change — this is purely how the tab list is labeled/grouped
visually, not a restructuring of what each tab does.

## 4. Month/year popover picker

**Where:** `frontend/src/pages/Budget.tsx` only — confirmed via grep that
this is the only page with its own month/year `useState` today (`year`,
`month` at `Budget.tsx:48-49`). Dashboard has no month-nav state to modify.

**Component:** new `frontend/src/components/MonthYearPicker.tsx`, built as
a standalone reusable component (not inlined into Budget.tsx) so any page
that adds month-nav later gets this for free rather than duplicating it.

**Behavior:** existing prev/next arrow buttons stay (cheap to keep,
matches the reference pattern which also keeps them alongside the
popover). Clicking the center month/year label opens a popover: a year
stepper (‹ 2026 ›) above a 4×3 grid of month abbreviations, selected month
visually distinct (solid fill, not just a border), clicking a month closes
the popover and updates `month`/`year` state via the same setters
Budget.tsx already has.

**Props:** `{ year: number; month: number; onChange: (year: number, month: number) => void }`
— stateless/controlled, so Budget.tsx keeps owning the actual state.

## Testing

No frontend test framework exists in this repo (confirmed during the
forecast-bug fix on 2026-08-24 — zero `.test.*` files, no test script in
`package.json`). Verification for this sub-project follows the same
grep/build/manual pattern the reverted ISA already used:

- `npx tsc --noEmit` exits 0
- Grep-verified: sidebar renders account rows, `/accounts/:id` route
  exists, Settings tab groups render with dividers, `MonthYearPicker`
  has no import from Budget.tsx's own state logic (stays a pure
  controlled component)
- Manual: visual check in both dark and light mode; manual check that
  the account-detail page's not-found state renders for a bad `:id`

## Out of scope for this sub-project

- Balance-history trend chart on Account Detail (deferred, needs new
  backend work)
- URL-param account pre-filter on the Transactions page
- Sub-project 2 items (F1–F8 re-execution, transaction modal redesign,
  donut/legend pattern, hide-balances toggle) — separate spec, sequenced
  after this one ships and is reviewed
- Any Phase 2 feature work from `docs/securo-comparison.md` (household
  splitting, investment tracking, etc.)

## License note

Every component here is original OfflineBudget code built from the written
pattern descriptions in `docs/securo-comparison.md`. No source, CSS, or
asset from `github.com/securo-finance/securo` (AGPL-3.0) is referenced or
copied — same constraint as the reverted attempt, carried forward
unchanged.
