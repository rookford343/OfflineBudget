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
│   ├── routers/      One file per resource (auth, accounts, budget, etc.)
│   └── services/     Business logic shared by API + CLI
│       ├── forecast_engine.py     Day-by-day balance projection
│       ├── budget_calculator.py   Budget vs. actual aggregation
│       ├── summary_generator.py   Monthly narrative + daily email summary
│       ├── email_service.py       SMTP send helper (silent no-op if unconfigured)
│       ├── auto_categorizer.py    Keyword + history-based category matching
│       └── csv_parser.py          Chase / Apple Card / generic CSV parsing
├── frontend/         React 18 + TypeScript + Vite + Tailwind
│   ├── src/
│   │   ├── api/      Typed API client (axios)
│   │   ├── store/    JWT auth state (localStorage)
│   │   ├── lib/      Utilities (formatting, color helpers)
│   │   ├── components/  Layout, shared UI, QuickStartWizard
│   │   └── pages/    One file per route
├── cli/              Typer CLI (imports services directly, no HTTP)
├── data/             SQLite database file (gitignored)
├── docs/             This documentation
├── scripts/          seed_demo.py, reset_password.py, start.sh
└── docker-compose.yml  Container stack for cloud deploy
```

---

## Data Model

### Entity Relationship Summary

```
User ──< Account
User ──< Category (self-referential parent/child)
User ──< RecurringItem >── Account, Category
User ──< Transaction >── Account, Category, RecurringItem?
User ──< CreditCard ──< CreditCardPayment >── Account
                    ──< CreditCardTransaction >── Category
                    ──< CreditCardImport
User ──< SavingsTransfer >── Account (from), Account (to)
User ──< BudgetAllocation >── Category
```

### Key Design Decisions

**Single SQLite file** — `data/budget.db` is the entire app's state. Portable, backupable with `cp`, upgradeable to PostgreSQL by changing one `.env` line.

**Soft deletes** — Accounts and credit cards use `is_active=False` instead of hard delete. History is preserved.

**Recurring items drive forecasting** — The forecast engine does not store projected transactions; it generates them on-the-fly from `recurring_items`. Only `is_actual=True` transactions are stored as real events.

**Two-level category hierarchy** — `categories.parent_id` is self-referential. Top-level: Wants, Necessities, Savings, Charity, Income. Sub-categories nest underneath. The spending analysis aggregates at both levels.

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
- Weekend shifting: items due on Saturday/Sunday are moved to the preceding Friday in projections; actual transactions always appear on their real date

---

## API Authentication

- `POST /auth/register` → creates user, seeds categories, returns JWT
- `POST /auth/login` → verifies bcrypt hash, returns JWT
- All other endpoints require `Authorization: Bearer <token>` header
- FastAPI dependency `get_current_user()` decodes JWT and loads user from DB
- Token expiry: 7 days (configurable via `JWT_EXPIRE_DAYS`)
- Admin-only endpoints use the `require_admin()` dependency — non-admin requests get 403

### Password Reset

**Via the UI (admin):** Settings → Users → click the reset icon (↺) next to any user. Sets a new password without requiring the old one. The admin cannot reset their own password this way — use Settings → Profile → Change Password instead.

**Via the CLI (emergency — no admin can log in):**

```bash
source .venv/bin/activate
python scripts/reset_password.py <username> <new_password>
```

The script also re-activates the account if it was set to inactive. Run without arguments to see usage. If the username is not found, the script prints all existing usernames.

---

## Adding a New Resource (Backend)

1. Add SQLAlchemy model to `backend/models.py`
2. Add Pydantic schemas to `backend/schemas.py`
3. Create `backend/routers/my_resource.py` with CRUD routes
4. Register in `backend/main.py`: `app.include_router(my_resource.router)`
5. Add API functions to `frontend/src/api/index.ts`
6. Create page in `frontend/src/pages/MyResource.tsx`
7. Add route to `frontend/src/App.tsx`
8. Add nav link to `frontend/src/components/Layout.tsx`

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
| `SMTP_HOST` | *(unset)* | SMTP server hostname — daily emails disabled if unset |
| `SMTP_PORT` | `587` | SMTP port (STARTTLS) |
| `SMTP_USER` | *(unset)* | SMTP login username |
| `SMTP_PASS` | *(unset)* | SMTP login password / app password |
| `SMTP_FROM` | *(unset)* | From address, e.g. `OfflineBudget <you@gmail.com>` |
| `DAILY_SUMMARY_HOUR` | `7` | Hour (0–23, server local time) to send daily summary emails |

All SMTP variables must be set for email to work. If `SMTP_HOST` is unset, `email_service.send_email()` is a silent no-op — no error is raised.

### Gmail App Password Setup

1. Enable 2-Factor Authentication on the Google account
2. Go to **Google Account → Security → App Passwords**
3. Generate a password for "Mail"
4. Set `SMTP_HOST=smtp.gmail.com`, `SMTP_USER=you@gmail.com`, `SMTP_PASS=<app-password>`

Each user sets their own email address in **Settings → Profile → Email Notifications** and can send a test email to verify delivery.

---

## Cloud Migration (SQLite → PostgreSQL)

1. Install PostgreSQL driver: `pip install psycopg2-binary`
2. Update `.env`: `DATABASE_URL=postgresql://user:pass@host:5432/budget`
3. Run the app — SQLAlchemy auto-creates tables on startup
4. (Optional) Use `pg_dump` / `sqlite3` export to migrate existing data

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
