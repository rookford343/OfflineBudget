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
│   ├── dependencies.py  get_db(), get_current_user(), require_admin()
│   ├── seed.py       Default category seeding on registration
│   ├── middleware.py AuditMiddleware — logs all mutating requests
│   ├── routers/      One file per resource
│   │   ├── accounts.py, auth.py, budget.py, categories.py
│   │   ├── checkpoints.py, credit_cards.py, data.py, exports.py
│   │   ├── forecast.py, goals.py, imports.py, networth.py
│   │   ├── planned_expenses.py, reconciliation.py, recurring.py
│   │   ├── rules.py, scenarios.py, spending.py, transactions.py
│   │   └── admin.py
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
│       ├── email_service.py       SMTP send helper
│       └── summary_generator.py   Daily email narrative
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

- Pattern types: `contains` (case-insensitive substring), `startswith`, `regex`
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

- `POST /auth/register` → creates user, seeds categories, returns JWT
- `POST /auth/login` → verifies bcrypt hash, returns JWT
- All other endpoints require `Authorization: Bearer <token>` header
- FastAPI dependency `get_current_user()` decodes JWT and loads user from DB
- Token expiry: 7 days (configurable via `JWT_EXPIRE_DAYS`)
- Admin-only endpoints use the `require_admin()` dependency — non-admin requests get 403

### Password Reset

**Via the UI (admin):** Settings → Users → click the reset icon next to any user.

**Via the CLI (emergency):**
```bash
source .venv/bin/activate
python scripts/reset_password.py <username> <new_password>
```

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

---

## Cloud Migration (SQLite → PostgreSQL)

1. Install PostgreSQL driver: `pip install psycopg2-binary`
2. Update `.env`: `DATABASE_URL=postgresql://user:pass@host:5432/budget`
3. Run the app — SQLAlchemy auto-creates tables on startup
4. Migrate existing data with `sqlite3` export + `psql` import if needed

No code changes are required — SQLAlchemy abstracts the dialect.

---

## Running Tests

```bash
# Backend
source .venv/bin/activate
PYTHONPATH=. pytest tests/ -v

# Frontend type check
cd frontend && npx tsc --noEmit

# Frontend build (catches all import/type errors)
cd frontend && npm run build
```
