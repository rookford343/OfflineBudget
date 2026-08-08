# OfflineBudget

A forecasting-first household budget tracker built for people who want full control of their financial data. Runs entirely on your home network — no subscriptions, no cloud sync, no third-party access to your finances.

Built with **FastAPI + SQLite** on the backend, **React + TypeScript** on the frontend.

---

## Features at a Glance

| Area | Highlights |
|------|-----------|
| [Forecast](#forecasting) | Day-by-day balance projection; quarterly and multi-year views; scenario planning |
| [Spending Analysis](#spending-analysis) | Monthly trends, year-over-year, merchant ranking, income flow diagram |
| [Tax Estimator](#tax-estimator) | Full 2025 federal + state estimate; itemized vs. standard deduction; bracket ladder |
| [Transaction Import](#transaction-import) | CSV and OFX/QFX upload; auto-categorization; custom rules engine; optional automated bank sync via SimpleFIN |
| [Credit Cards](#credit-cards) | Balance tracking, due-date reminders, payment recording, per-card spending |
| [Budget Tracking](#budget-tracking) | Monthly category budgets with rollover; actual vs. budgeted variance |
| [Reconciliation](#reconciliation) | Link transactions to recurring items; quarterly balance checkpoints |
| [Net Worth](#net-worth) | Assets and liabilities with historical snapshots |
| [Savings Goals](#savings-goals) | Track named goals with target amounts and target dates |
| [CLI](#cli) | All core operations available from the terminal without running the server |

---

## Quick Start

```bash
# 1. Set up Python environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# 2. Install frontend dependencies
cd frontend && npm install && cd ..

# 3. Configure environment
cp .env.example .env
# Edit .env — set JWT_SECRET to a random string:
python3 -c "import secrets; print(secrets.token_hex(32))"

# 4. Start the app
./scripts/start.sh
```

Open **http://localhost:5173** → Create an account → Run through the Quick Start wizard.

> **HTTPS on LAN:** Run `./scripts/setup-ssl.sh` to generate a self-signed certificate for your local IP, then restart. The start script detects the certs automatically.

---

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/start-guide.md) | First-time setup, LAN access, initial budget configuration |
| [Technical Guide](docs/technical-guide.md) | Architecture, data model, forecast engine, adding new features |
| [Security](SECURITY.md) | Threat model, password storage, JWT, HTTPS, backup strategy |

---

## Project Structure

```
OfflineBudget/
├── backend/
│   ├── routers/          One file per resource
│   │   ├── accounts.py, auth.py, budget.py, categories.py
│   │   ├── checkpoints.py, credit_cards.py, data.py, exports.py
│   │   ├── forecast.py, goals.py, imports.py, networth.py
│   │   ├── planned_expenses.py, reconciliation.py, recurring.py
│   │   ├── rules.py, scenarios.py, spending.py, transactions.py
│   │   └── admin.py
│   ├── services/         Business logic shared by API + CLI
│   │   ├── forecast_engine.py     Day-by-day balance projection
│   │   ├── import_service.py      Shared import pipeline (preview + confirm)
│   │   ├── auto_categorizer.py    Keyword + history-based categorization
│   │   ├── rules_engine.py        User-defined transaction rules
│   │   ├── csv_parser.py          CSV format detection and parsing
│   │   ├── ofx_parser.py          OFX/QFX bank file parsing
│   │   ├── tax_service.py         2025 federal + state tax estimation
│   │   ├── budget_calculator.py   Budget vs. actual aggregation
│   │   ├── recurring_detector.py  Auto-detect recurring patterns
│   │   ├── email_service.py       SMTP send helper
│   │   └── summary_generator.py   Daily email narrative
│   ├── models.py         SQLAlchemy ORM models
│   ├── schemas.py        Pydantic request/response schemas
│   ├── database.py       Engine, session, idempotent migrations
│   ├── auth.py           JWT + bcrypt helpers
│   └── middleware.py     Audit logging for all write requests
├── frontend/
│   └── src/
│       ├── api/           Typed axios client
│       ├── pages/         Dashboard, Forecast, Spending, Transactions,
│       │                  Import, Budget, CreditCards, Recurring,
│       │                  NetWorth, Goals, Settings, Login
│       ├── components/    Layout, HelpPanel, QuickStartWizard
│       └── lib/           Formatting utilities, date helpers
├── cli/                   Typer CLI (direct DB access, no HTTP)
├── scripts/
│   ├── start.sh           Launcher (detects SSL certs, starts both servers)
│   └── setup-ssl.sh       Self-signed cert generator for LAN HTTPS
├── data/                  SQLite database (gitignored — back this up)
├── docs/                  Detailed guides
├── docker-compose.yml     Container stack for cloud deploy
├── .env.example           Environment variable template
└── SECURITY.md            Security model
```

---

## Forecasting

The **Forecast** page answers: *"If I keep paying what I'm paying, what will my balance be on any given day?"*

- **Day-by-day view** — Select a date range and account to see the projected balance for every day, with each recurring item shown as a line item.
- **Quarterly view** — Q1–Q4 open/close balances at a glance; quarters below the low-balance threshold are highlighted in amber.
- **Multi-year view** — Extend the forecast 1, 2, 3, or 5 years to model long-term financial health.
- **Scenario planning** — Create named scenarios with per-item overrides (e.g., "What if I refinance?"). The scenario and baseline traces appear side-by-side on the chart.
- **Quarterly checkpoints** — Record actual end-of-quarter balances to calibrate future projections.

The forecast engine generates projections on-the-fly from recurring items each time you load the page — no stale cached data.

---

## Spending Analysis

The **Spending** page has five tabs:

| Tab | Description |
|-----|-------------|
| **Overview** | Total spent vs. budgeted; monthly bar chart; stacked category chart; donut chart; expandable category drill-down |
| **Trends** | Year-over-year monthly comparison (up to 3 years); 24-month rolling spending area chart |
| **Merchants** | Ranked table of spending by merchant/description — sortable by name, transaction count, or total |
| **Flow** | Sankey diagram showing income sources flowing into expense categories for any month |
| **Tax Export** | Full tax estimate and CSV export of deductible transactions |

Spending totals exclude savings-type categories and account transfers so CC payments don't inflate your numbers.

Quick-filter buttons (**This Month / 3 Months / YTD / Last Year**) appear above the date inputs on both Spending and Transactions pages.

---

## Tax Estimator

Configure your tax profile under **Settings → Profile → Tax Profile**. The estimator calculates:

- **2025 federal income tax** using official brackets for all four filing statuses
- **State income tax** using approximate effective rates for all 50 states + DC
- **FICA** — Social Security (6.2% up to the $176,100 wage base) + Medicare (1.45% + 0.9% additional above threshold)
- **Itemized vs. standard deduction** — whichever is higher is used automatically

Enter your known itemized deductions directly in the Tax Profile:

| Deduction | Where it comes from |
|-----------|-------------------|
| Mortgage Interest | Form 1098 from your lender |
| Charitable Donations | Receipts / bank records |
| State & Local Taxes (SALT) | State tax return + pay stubs |
| Property Taxes | County tax statement |
| Other (vehicle registration, etc.) | DMV / local statements |

Transactions in categories tagged **Tax Deductible** are also included automatically.

The estimator returns a full breakdown: refund or amount owed (federal and state separately), effective rate, and a per-bracket ladder.

> All estimates are for planning purposes only — consult a tax professional for filing.

---

## Transaction Import

Navigate to **Import** → choose Checking or Credit Card → upload a file.

### Supported formats

| Format | How detected |
|--------|-------------|
| Chase checking CSV | `Details`, `Posting Date` header columns |
| Chase credit card CSV | `Transaction Date`, `Category` columns |
| Apple Card CSV | `Transaction Date`, `Merchant` columns |
| Generic CSV | Date, description, amount fallback |
| OFX / QFX | File extension (`.ofx` / `.qfx`) |

### Auto-categorization pipeline

New transactions are categorized in this priority order:

1. **Transaction rules** — user-defined rules (contains / starts-with / regex) applied first
2. **Import history** — same description was categorized before → reuse that category
3. **Keyword rules** — built-in merchant keyword list

Rows that can't be matched are flagged for manual review before import is confirmed. A "Skip auto-categorization" toggle imports all rows uncategorized for manual assignment.

### Transaction Rules Engine

Add rules under **Settings → Transaction Rules**:

- Match by `contains`, `startswith`, or `regex` on the transaction description
- Actions: `set_category` or `mark_transfer`
- Priority ordering — first match wins
- Live test input in the rule modal to verify a pattern before saving

### Import grouping

The import preview groups similar transactions by normalizing descriptions (stripping reference codes, ACH identifiers, store numbers, and TLD suffixes) so recurring charges at the same merchant batch together for bulk categorization.

---

## Credit Cards

- Add cards with current balance, credit limit, minimum payment, and due date
- Record payments — automatically deducts from the linked checking account
- Per-card transaction log with category assignment
- Utilization percentage and upcoming due-date alerts on the dashboard
- Import transactions from CSV or OFX/QFX

---

## Budget Tracking

- Set monthly budgets per sub-category from **Settings → Categories**
- Budget amounts apply to all months (month=0) unless overridden
- Rollover: enable per-category rollover so unspent budget carries forward
- **Budget overview** — side-by-side actual vs. budgeted with variance for every category in the current month

---

## Reconciliation

The **Transactions → Reconcile** tab helps you match records against bank statements:

- **Link** — match an imported transaction to its recurring item
- **Mark Reconciled** — enter the statement closing balance; recorded as a quarterly checkpoint
- Unmatched recurring items shown separately with one-click "Add Transaction" to create the entry

---

## Net Worth

- Add assets (bank accounts, brokerage, real estate) and liabilities (loans, credit cards)
- Take point-in-time snapshots to build a history
- Historical net worth chart

---

## Savings Goals

- Create named goals with a target amount and optional target date
- Track progress as a percentage toward the goal

---

## Settings Overview

| Section | What you can configure |
|---------|----------------------|
| **Preferences** | Dark mode toggle; navigation sidebar order (click arrows to reorder) |
| **Accounts** | Add / edit / delete accounts; low-balance alert threshold; interest rate; click any balance to correct it |
| **Categories** | Hierarchical CRUD; budget amounts (inline edit); color; type (income / expense / savings); tax-deductible flag |
| **Transaction Rules** | Auto-categorization rules with live pattern testing |
| **Profile** | Display name; email address for daily summaries; password change |
| **Tax Profile** | Filing status, state, salary, withholding, itemized deductions, Social Security tracker |
| **Users** *(admin)* | Create admin or view-only users; toggle active status; reset passwords |
| **Activity Log** *(admin)* | Browse all write operations with timestamp, user, method, path, and status |
| **Danger Zone** | Clear checking transactions; clear CC transactions; delete account |

---

## CLI

The CLI shares the same database and service layer as the web app — no server required.

```bash
source .venv/bin/activate

# User management
python cli/budget.py users create

# Accounts
python cli/budget.py accounts list --username alice

# Recurring items
python cli/budget.py recurring list --username alice

# Forecast
python cli/budget.py forecast quarters --username alice --account "Main Checking"
python cli/budget.py forecast show   --username alice --account "Main Checking" --quarter Q2-2026

# Credit cards
python cli/budget.py cards list --username alice
```

---

## Multi-User

- **Admin** users manage accounts from Settings → Users
- **View-only** users can read data but cannot create, edit, or delete anything
- All write operations are logged in the audit log
- Password reset: Settings → Users → reset icon, or via `python scripts/reset_password.py <username> <new_password>`

---

## Email Notifications

Configure SMTP in `.env` to enable daily summary emails:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=<app-password>
SMTP_FROM=OfflineBudget <you@gmail.com>
DAILY_SUMMARY_HOUR=7
```

Each user sets their own email address in **Settings → Profile** and can send a test email to verify delivery. The summary includes checking balances, upcoming bills (7-day window), month-to-date expenses, and credit card balances.

> For Gmail: enable 2FA → Google Account → Security → App Passwords → generate a password for "Mail".

---

## HTTPS on LAN

```bash
./scripts/setup-ssl.sh   # generates ssl/cert.pem and ssl/key.pem for your LAN IP
./scripts/start.sh       # automatically picks up the certs
```

`setup-ssl.sh` generates a self-signed certificate with a Subject Alternative Name for both `localhost` and your current LAN IP. For CA-signed certificates with no browser warnings, use `mkcert` — see [SECURITY.md](SECURITY.md).

---

## Backup

All data lives in a single file:

```bash
# Manual backup
cp data/budget.db data/budget_$(date +%Y%m%d).db

# Automated daily backup via cron
crontab -e
# 0 2 * * * cp /path/to/OfflineBudget/data/budget.db /path/to/backups/budget_$(date +\%Y\%m\%d).db
```

---

## Cloud Deploy

1. Update `DATABASE_URL` in `.env` to a PostgreSQL connection string
2. `docker-compose up` — no code changes required
3. Set `ALLOWED_ORIGINS` to your production domain
4. See [SECURITY.md](SECURITY.md) for the full hardening checklist

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/budget.db` | SQLAlchemy database URL |
| `JWT_SECRET` | *(required)* | JWT signing key — generate with `secrets.token_hex(32)` |
| `JWT_EXPIRE_DAYS` | `7` | Token lifetime in days |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | CORS allowed origins (comma-separated) |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | API port |
| `SMTP_HOST` | *(unset)* | SMTP server — email disabled if unset |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | *(unset)* | SMTP username |
| `SMTP_PASS` | *(unset)* | SMTP password / app password |
| `SMTP_FROM` | *(unset)* | From address |
| `DAILY_SUMMARY_HOUR` | `7` | Hour (0–23) to send daily summary emails |

---

## License

See [LICENSE](LICENSE).
