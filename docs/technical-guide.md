# Technical Guide

## Architecture Overview

```
OfflineBudget/
├── backend/          FastAPI + SQLAlchemy 2 + SQLite
│   ├── main.py       App entry point, CORS, scheduler, router registration
│   ├── config.py     Pydantic settings (reads .env)
│   ├── database.py   SQLAlchemy engine + SessionLocal + schema migrations
│   ├── models.py     All ORM models
│   ├── schemas.py    All Pydantic request/response models
│   ├── auth.py       JWT creation/verification, bcrypt helpers
│   ├── dependencies.py  get_db(), get_current_user() (also enforces View Only), require_admin()
│   ├── seed.py       Default category seeding on registration
│   ├── middleware.py AuditMiddleware — logs all mutating requests
│   ├── routers/      One file per resource
│   │   ├── accounts.py, auth.py, budget.py, categories.py
│   │   ├── checkpoints.py, credit_cards.py, data.py, exports.py
│   │   ├── forecast.py, goals.py, imports.py, networth.py
│   │   ├── planned_expenses.py, reconciliation.py, recurring.py
│   │   ├── rules.py, scenarios.py, spending.py, transactions.py
│   │   ├── bank_sync.py (both providers), adventures.py, wish_list.py, settings.py
│   │   ├── admin.py
│   │   └── _shared.py  owned_or_404() and reject_nulls(), used by every router
│   └── services/     Business logic shared by API + CLI
│       ├── forecast_engine.py     Day-by-day balance projection
│       ├── import_service.py      Shared import pipeline (preview + confirm)
│       ├── auto_categorizer.py    Keyword + history-based categorization
│       ├── rules_engine.py        User-defined transaction rules
│       ├── csv_parser.py          CSV format detection and parsing
│       ├── ofx_parser.py          OFX/QFX bank file parsing
│       ├── tax_service.py         2025 federal + state tax estimation
│       ├── budget_calculator.py   Budget vs. actual aggregation
│       ├── recurring_detector.py  Auto-detect recurring transaction patterns
│       ├── email_service.py       SMTP send (one config: Settings page over .env)
│       ├── summary_generator.py   Daily email (Spending this month, weekly digest)
│       ├── budget_snapshot.py     Household Snapshot; spending_breakdown(start, end)
│       ├── bank_sync_service.py   SimpleFIN sync, card pending snapshot
│       ├── simplefin_client.py    SimpleFIN protocol client (pending=1 for cards)
│       ├── plaid_client.py        Thin httpx client for Plaid's API (no SDK)
│       ├── plaid_sync_service.py  Plaid sync: transactions, balances, statements
│       ├── cutover_match.py       Cross-provider matching for a provider switch
│       ├── card_matching.py       Card name matcher + looks_like_card_autopay()
│       ├── primary_account.py     primary_checking(): the account forecasts walk
│       ├── wish_math.py, wish_plan.py, wish_lifecycle.py   Wish List
│       └── adventures.py, adventures_lifecycle.py          Adventures
├── frontend/         React 18 + TypeScript + Vite + Tailwind
│   ├── src/
│   │   ├── api/      Typed API client (axios) — all endpoints in api/index.ts
│   │   ├── store/    JWT auth state (localStorage)
│   │   ├── lib/      Utilities (formatting, color helpers, date helpers)
│   │   ├── components/  Layout, HelpPanel, QuickStartWizard
│   │   └── pages/    Dashboard, Forecast, Spending, Transactions, Import,
│   │                 Budget, CreditCards, Recurring, NetWorth, Goals,
│   │                 Settings, Login
├── cli/              Typer CLI (imports services directly, no HTTP)
├── data/             SQLite database file (gitignored)
├── docs/             This documentation
├── scripts/
│   ├── start.sh      Launcher — detects ssl/ certs, starts both servers
│   └── setup-ssl.sh  Self-signed cert generator for LAN HTTPS
└── docker-compose.yml  Container stack for cloud deploy
```

---

## Data Model

### Entity Relationship Summary

```
User ──< Account
User ──< Category (self-referential parent/child, type: income/expense/savings)
User ──< RecurringItem >── Account, Category
User ──< Transaction >── Account, Category, RecurringItem?
User ──< CreditCard ──< CreditCardPayment >── Account
                    ──< CreditCardTransaction >── Category
                    ──< CreditCardImport
User ──< SavingsTransfer >── Account (from), Account (to)
User ──< BudgetAllocation >── Category
User ──< TransactionRule
User ──< Scenario ──< ScenarioOverride >── RecurringItem
User ──< QuarterlyCheckpoint >── Account
User ──< SavingsGoal
User ──< NetWorthAsset
User ──< NetWorthLiability
User ──< NetWorthSnapshot
User ──< PlannedExpense
```

### User Model — Tax and SS Fields

The `User` model carries the full tax profile directly to avoid a separate table:

| Field | Type | Purpose |
|-------|------|---------|
| `tax_filing_status` | VARCHAR(32) | single / married_jointly / married_separately / head_of_household |
| `tax_state` | VARCHAR(2) | 2-letter state code |
| `annual_salary` | NUMERIC(14,2) | Gross W-2 salary |
| `other_income` | NUMERIC(14,2) | 1099 / dividends / other |
| `federal_withholding_ytd` | NUMERIC(14,2) | YTD federal tax withheld |
| `state_withholding_ytd` | NUMERIC(14,2) | YTD state tax withheld |
| `itemized_mortgage_interest` | NUMERIC(14,2) | Form 1098 interest |
| `itemized_donations` | NUMERIC(14,2) | Charitable donations |
| `itemized_salt` | NUMERIC(14,2) | State & local taxes paid |
| `itemized_property_tax` | NUMERIC(14,2) | Property taxes |
| `itemized_other` | NUMERIC(14,2) | Other deductible expenses |
| `ss_gross_per_paycheck` | NUMERIC(14,2) | Gross wages per pay period |
| `ss_wage_base` | NUMERIC(14,2) | SS wage base (default $176,100) |
| `ss_bonus_ytd` | NUMERIC(14,2) | YTD bonus subject to SS tax |

### Key Design Decisions

**Single SQLite file** — `data/budget.db` is the entire app's state. Portable, backupable with `cp`, upgradeable to PostgreSQL by changing one `.env` line.

**Soft deletes** — Accounts and credit cards use `is_active=False` instead of hard delete. History is preserved.

**Recurring items drive forecasting** — The forecast engine does not store projected transactions; it generates them on-the-fly from `recurring_items`. Only `is_actual=True` transactions are stored as real events.

**Two-level category hierarchy** — `categories.parent_id` is self-referential. Top-level: Wants, Necessities, Savings, Charity, Income. Sub-categories nest underneath. Three `type` values: `income`, `expense`, `savings`. Spending analysis excludes savings-type categories.

**Decimal precision** — All monetary values use `Numeric(14, 2)` in SQLAlchemy and `Decimal` in Python — never floats. Frontend receives them as strings and parses with `parseFloat()`.

**Idempotent schema migrations** — `upgrade_schema()` in `database.py` runs `ALTER TABLE` statements inside `try/except` blocks so they silently skip on re-runs. No Alembic required for additive column changes.

---

## Forecast Engine (`backend/services/forecast_engine.py`)

The core algorithm:

1. Load all active `RecurringItem` records for the account
2. Load all `is_actual=True` transactions in the date range
3. Walk day-by-day from `start_date` to `end_date`:
   - For each day, find recurring items whose `day_of_month` fires (handling last-day-of-month edge cases)
   - If an actual transaction exists for a recurring item (`recurring_item_id` matches), use the actual amount
   - Otherwise, use the projected amount from the recurring item
   - Apply manual actual transactions (no recurring link) as-is
   - On the last day of each month, apply a monthly interest credit if `account.interest_rate > 0`
4. Return `List[ForecastEntry]` with running balance

**Edge cases handled:**
- `day_of_month = 0` → last day of each calendar month
- Months shorter than the target day (e.g., Feb 30) → clamped to last day of month
- `start_date` / `end_date` on recurring items enable modeling salary changes, bill end dates
- Weekend shifting: items due on Saturday/Sunday shift to the preceding Friday in projections; actual transactions always appear on their real date

### Multi-Year Forecast

`GET /forecast/multi-year?account_id=&start_year=&years=` loops `build_quarters()` over N years (1, 2, 3, or 5). The frontend renders quarter cards with `year-quarter` composite keys.

---

## Import Pipeline (`backend/services/import_service.py`)

The import pipeline is split into two phases shared by both the web API and CLI:

```
build_preview(db, user, parsed_rows) → list[ImportPreviewRow]
  1. Load transaction history map (description → category_id)
  2. Apply user-defined transaction rules (rules_engine.apply_rules)
  3. Apply keyword-based auto-categorizer
  4. Flag needs_review rows (no match found)

run_import(db, user, parsed_rows, account_id, ...) → ImportConfirmResponse
  1. Deduplicate against existing transactions (date + amount + description hash)
  2. Try auto-match to recurring items (day ±3, amount within 10%)
  3. Insert Transaction records
  4. Update account.current_balance
  5. Commit + return summary counts
```

### OFX/QFX Support

`ofx_parser.py` uses `ofxparse>=0.21` to parse bank-exported OFX and QFX files. The format is auto-detected by file extension before routing to the CSV or OFX parser.

### Transaction Rules Engine (`backend/services/rules_engine.py`)

```python
apply_rules(description: str, rules: list[TransactionRule]) -> RuleMatch | None
```

- Pattern types: `contains` (case-insensitive substring), `startswith`, and wildcard (stored as `regex`; `*` matches anything, everything else is literal, so no pattern can backtrack catastrophically)
- First match by `priority` wins
- Actions: `set_category` (assigns `category_id`) or `mark_transfer` (sets `is_transfer=True`)
- Rules are applied in the `build_preview` phase before history and keyword matching

---

## Tax Service (`backend/services/tax_service.py`)

```python
estimate_taxes(
    filing_status, state, gross_income, other_income,
    deductible_expenses, federal_withheld, state_withheld
) -> dict
```

The function:
1. Sums `gross_income + other_income`
2. Computes itemized total from `deductible_expenses` (already summed by the endpoint: user profile fields + tagged transactions)
3. Picks `max(standard_deduction, itemized)` and sets `used_itemized` flag
4. Applies 2025 federal brackets to `total_income - deduction`
5. Applies approximate flat state rate to `total_income - standard_deduction`
6. Computes FICA: SS on `min(gross_income, wage_base)` + Medicare with additional threshold
7. Returns bracket ladder, refund/owed per federal/state, effective rate

State rates are approximate effective rates for middle-income earners (not marginal). They are sufficient for planning but not for filing.

---

## API Authentication

- `POST /auth/register` → only works on an empty install: creates the first
  user as admin, seeds categories, returns JWT. Once any user exists it
  returns 403; admins add everyone else via `POST /admin/users`
- `POST /auth/login` → verifies bcrypt hash, returns JWT. Limited to 10
  attempts per client and username per 15 minutes (429 after that)
- Passwords: one rule, `auth.check_new_password()` (minimum 6 characters),
  applied by register, change password, both reset flows, and admin
  create/reset
- All other endpoints require `Authorization: Bearer <token>` header
- FastAPI dependency `get_current_user()` decodes JWT and loads user from DB
- Token expiry: 7 days (configurable via `JWT_EXPIRE_DAYS`)
- Admin-only endpoints use the `require_admin()` dependency — non-admin requests get 403
- **View Only** is enforced in `get_current_user()`: a viewer's POST, PUT,
  PATCH or DELETE on any data endpoint gets 403. `/auth/me` endpoints use
  `get_requester()` instead, so viewers can still change their own password

### Password Reset

**Via the UI (admin):** Settings → Household → click the reset icon next to any user.

**Via the CLI (emergency):**
```bash
uv run python scripts/reset_password.py <username> <new_password>
```

---

## Dependencies and supply chain

Python dependencies are managed with [uv](https://docs.astral.sh/uv/):

- `pyproject.toml` pins every direct dependency exactly; `uv.lock` pins every
  transitive one and records a SHA-256 for each file. An install whose files
  don't match the recorded hashes fails.
- `[tool.uv] exclude-newer = "7 days"` is a cooldown: resolution ignores any
  release younger than a week, so a hijacked upload has time to be caught
  before it can reach this project.
- Install with `uv sync --locked` (refuses a lockfile that doesn't match
  `pyproject.toml`). Run anything with `uv run --locked`, never bare `pip`.
- Add or upgrade a package with `uv add name==X.Y.Z`, then commit both files.
  The pre-commit hook refuses a `pyproject.toml` change without its lockfile.
- `.githooks/pre-push` runs `uv audit` and blocks the push if any locked
  package has a known vulnerability or has been abandoned.
- `Dockerfile.backend` pins both base images by digest and installs from the
  lockfile with `uv sync --locked --no-dev`.

`python-jose` was replaced by `PyJWT` on 2026-10-10. jose had an unpatched
algorithm-confusion flaw (CVE-2026-85394) and pulled in `ecdsa` (an unpatched
timing attack) and `rsa` (archived). Unused `plaid-python`, `alembic` and
`aiosqlite` were removed at the same time.

## Bank Sync and Scheduled Jobs

APScheduler jobs registered in `backend/main.py`:

| Job | When | What |
|-----|------|------|
| `_run_bank_sync` | 7:00 | `sync_all()`: every linked account and card, both providers |
| `_run_plaid_sync` | 11:00, 15:00, 19:00 (`_PLAID_EXTRA_HOURS`) | `sync_all(providers={"plaid"})`: Plaid links only |
| `_send_daily_summaries` | :15 past the send hour (default 7) | Daily email, after the 7:00 sync |
| `_scheduler_sweep` | every 20 min | Retries a job that hasn't succeeded today |

SimpleFIN only ever runs at 7:00, inside `_run_bank_sync`. The old
`_run_card_refresh` job (15:17, SimpleFIN cards only) is gone: Plaid's Link
already covers checking and cards through one connection, and its three
extra daily runs replace the need for a separate cards-only pass. Every job
above, plus **Sync Now**, shares `job_locks._bank_sync_lock` (a non-blocking
lock), so two syncs can never run at once; concurrent runs used to insert the
same transactions twice.

**SimpleFIN.** Each link costs one request. Card links pass
`include_pending=True`; pending records come back flagged `pending` and are
never imported. Instead `_replace_pending_snapshot()` deletes the card's
`card_pending_transactions` rows and inserts the current pending list, then
sets `CreditCard.pending_charges` to its total. A card whose issuer has
never sent pending data is left alone, so a hand-typed figure survives.
`GET /credit-cards/pending-transactions` serves the snapshot to the
Transactions page.

**Plaid** (`plaid_client.py`, `plaid_sync_service.py`). One run calls
`/transactions/sync` (paginated, cursor-based), `/accounts/get`,
`/liabilities/get` for card links, then `/transactions/refresh` last so the
*next* run's sync picks up whatever that refresh finds — no webhook, no
in-request waiting. Pending rows (`pending: true`) are never imported; they
replace the card's pending snapshot the same way SimpleFIN's do. Posted rows
go through the same `build_preview`/`run_import` pipeline as every other
source. Plaid transaction ids are stored as `plaid:<transaction_id>` on
`external_id`, so they can never collide with a SimpleFIN or CSV id.

**Pending card payments on checking.** `/transactions/sync` sends each
pending row once, as a delta, so it can't rebuild checking's pending list.
In its read phase each Plaid run also calls `/transactions/get` (today - 14
days through today, paged by `options.offset`) and keeps only the
`pending` rows. Before commit it replaces each active checking link's
`AccountPendingTransaction` rows with that snapshot. If the call fails
(429 included), the run logs the code, keeps the old snapshot and carries
on. The preview never calls it. `build_forecast` subtracts the pending
debits that `card_matches_description` ties to an active card from TODAY,
as "Pending: …" lines, and lowers that card's locked payoff by the same
amount. A card also marked `payment_sent_pending_sync` counts once, at the
larger of the two. Both are applied after today's `ForecastDayCheckpoint`,
because sync anchors today to the posted balance and the walk applies a
day's anchor last. The marker used to come off the opening seed, where
that anchor erased it.

**Card statement balances.** `/liabilities/get`'s per-card statement feeds
`_apply_statements` in `plaid_sync_service.py`, which runs after this run's
own card transactions are imported and committed, so credits posted in the
same sync count. On every sync -- not just when a new statement arrives --
it recomputes `CreditCard.balance_due` as the statement's own total
(`last_statement_balance`, clamped at >= 0, never the stored `balance_due`,
which `record_payment` may have hand-reduced) minus the sum of
`CreditCardTransaction` rows with `amount < 0` dated after the statement's
`last_statement_issue_date` (payments and returns alike -- the issuer's own
rule). Within `_FULL_COVERAGE_SLOP` ($1, `statement_reconcile.py`) of full
coverage it clears to 0; otherwise it's capped at the prior balance_due, so
it can only drop, never rise. A card's first-ever Plaid statement still
only *seeds* `last_statement_issue_date` (its balance predates Plaid), but
runs this same recompute against that freshly seeded date, so a statement
that's already fully paid off clears on that first sync too.

*No Plaid SDK.* `plaid_client.py` is a thin wrapper over `httpx` (already a
dependency) instead of `plaid-python`. The SDK's own code reviewed as
clean — no exec, eval, subprocess or pickle, TLS verified by default — but
it drags in four extra packages the lockfile doesn't have (including one
with a single maintainer and no release since 2018), ships as a source
archive with no wheel so `setup.py` runs at install time, and is roughly
2,300 generated files for the eight endpoints this app actually calls — all
to get typed response models, which targeted parsing plus tests against
recorded response shapes cover anyway.

**Switching a link from SimpleFIN to Plaid.** `cutover_match.py` handles
re-sent history: for posted rows dated from 10 days before the switch
through 3 days after, `find_match()` looks for an existing row with the
same amount, a date within 3 days, and a fuzzy description match, before
falling back to normal `external_id` dedup. A match keeps the existing row
as-is and records the Plaid id on it in a new `alt_external_id` column on
`Transaction`/`CreditCardTransaction`, so a later `modified` or `removed`
event from Plaid still finds the right row. Rows older than the window are
ignored outright; rows after it rely on `external_id` dedup only. See
`docs/superpowers/specs/2026-10-25-plaid-sync-design.md` for the full
cutover design.

## Shared Helpers (one place to fix)

| Helper | Use it for |
|--------|-----------|
| `routers/_shared.owned_or_404()` | Fetch a row and 404 unless it belongs to the user |
| `routers/_shared.reject_nulls()` | 422 an explicit null on a NOT NULL field |
| `services/primary_account.primary_checking()` | "The" checking account (frontend: `lib/accounts.primaryChecking`) |
| `services/card_matching.card_matches_description()` | Does a description name this card (word-bounded) |
| `services/card_matching.looks_like_card_autopay()` | Is a checking debit a card payoff |
| `services/budget_snapshot.spending_breakdown()` | Total, categories and merchants for any date range |
| `services/email_service.send_email_via()` / `deliver()` | Every email; never read SMTP settings yourself |
| `auth.check_new_password()` | Every place a password is set |

---

## Adding a New Resource (Backend)

1. Add SQLAlchemy model to `backend/models.py`
2. Add migration statement to `upgrade_schema()` in `backend/database.py`
3. Add Pydantic schemas to `backend/schemas.py`
4. Create `backend/routers/my_resource.py` with CRUD routes
5. Register in `backend/main.py`: `app.include_router(my_resource.router)`
6. Add API functions to `frontend/src/api/index.ts`
7. Create page in `frontend/src/pages/MyResource.tsx`
8. Add route to `frontend/src/App.tsx`
9. Add nav link to `frontend/src/components/Layout.tsx`

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/budget.db` | SQLAlchemy database URL |
| `JWT_SECRET` | `dev-secret-change-in-production` | JWT signing key — **change this** |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_EXPIRE_DAYS` | `7` | Token lifetime |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | CORS allowed origins |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | API port |
| `SMTP_HOST` | *(unset)* | SMTP server hostname — email disabled if unset |
| `SMTP_PORT` | `587` | SMTP port (STARTTLS) |
| `SMTP_USER` | *(unset)* | SMTP login username |
| `SMTP_PASS` | *(unset)* | SMTP login password / app password |
| `SMTP_FROM` | *(unset)* | From address |
| `DAILY_SUMMARY_HOUR` | `7` | Hour (0–23) to send daily summary emails |
| `PLAID_CLIENT_ID` | *(unset)* | Plaid client id — Plaid disabled if unset |
| `PLAID_SECRET` | *(unset)* | Plaid secret for `PLAID_ENV` |
| `PLAID_ENV` | `production` | Must be `sandbox` or `production`; anything else fails at startup |

---

## Cloud Migration (SQLite → PostgreSQL)

1. Add the PostgreSQL driver: `uv add psycopg2-binary` (pin it exactly, then commit `pyproject.toml` and `uv.lock`)
2. Update `.env`: `DATABASE_URL=postgresql://user:pass@host:5432/budget`
3. Run the app — SQLAlchemy auto-creates tables on startup
4. Migrate existing data with `sqlite3` export + `psql` import if needed

No code changes are required — SQLAlchemy abstracts the dialect.

---

## Running Tests

```bash
# Backend (from backend/, so tests can import their helpers)
cd backend && uv run --locked python -m pytest -q --cov && cd ..
uv run --locked ruff check .        # Bandit security + Pyflakes
uv audit --preview-features audit   # known-vulnerable or abandoned dependencies

# Frontend type check
cd frontend && npx tsc --noEmit

# Frontend build (catches all import/type errors)
cd frontend && bun run build
```
