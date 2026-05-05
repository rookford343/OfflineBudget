# OfflineBudget

A forecasting-first household budget tracker. Runs fully offline on your home network — no cloud required. Built with FastAPI + SQLite on the backend and React on the frontend.

---

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt && pip install typer rich
cd frontend && npm install && cd ..
cp .env.example .env   # then set JWT_SECRET to a random string
./scripts/start.sh
```

Open `http://localhost:5173` → Create an account → Add accounts, income, and bills → view your Forecast.

---

## What It Does

| Feature | Description |
|---------|-------------|
| **Forecast** | Day-by-day checking account balance projection, up to 2 years ahead; low-balance threshold warnings |
| **Quarterly view** | Q1–Q4 open/close balances matching your Excel workflow |
| **Recurring** | Monthly and yearly recurring income and bills; yearly items annualized in monthly totals |
| **Credit cards** | Track balances, due dates, utilization, and record payments |
| **Spending analysis** | Filter by account or card; monthly bar chart + category breakdown with progress bars |
| **Budget tracking** | Set monthly category budgets, see actual vs. budgeted with variance |
| **CSV Import** | Upload Chase checking, Chase card, Apple Card, or generic CSV; auto-categorizes known merchants; manual assign for the rest; deduplicates on re-import |
| **Dark mode** | Toggle in Settings → Preferences; persists across sessions |
| **Multi-user** | Admin and view-only roles; admins manage users from the Settings page |
| **Audit log** | Admin-only activity log of all write operations viewable in Settings |
| **CLI** | All core operations available from the terminal |
| **Cloud-ready** | Swap `DATABASE_URL` to PostgreSQL and deploy anywhere |

---

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/start-guide.md) | First-time setup, account creation, LAN access, initial budget configuration |
| [Technical Guide](docs/technical-guide.md) | Architecture, data model, forecast engine, adding new features |
| [Future Work](docs/future-work.md) | Roadmap: CSV import, reconciliation, cloud deploy, known limitations |
| [Security](SECURITY.md) | Threat model, password storage, JWT, backup strategy, cloud hardening |

---

## Project Structure

```
OfflineBudget/
├── backend/          FastAPI API (Python 3.11+)
│   ├── routers/      accounts, categories, budget, forecast, recurring,
│   │                 spending, transactions, credit-cards, imports, admin
│   ├── services/     forecast_engine, csv_parser, auto_categorizer
│   ├── models.py     SQLAlchemy ORM (Account, Category, RecurringItem,
│   │                 Transaction, Budget, CreditCard, AuditLog, User)
│   └── middleware.py AuditMiddleware — logs all write requests
├── frontend/         React + TypeScript UI (Node 20+)
│   └── src/pages/    Dashboard, Forecast, Recurring, Spending, Transactions,
│                     Budget, CreditCards, Import, Settings, Login
├── cli/              Typer CLI (shares backend service layer)
├── data/             SQLite database — gitignored, back this up
├── docs/             Documentation guides
├── scripts/          start.sh launcher, seed_demo.py
├── docker-compose.yml  Container stack for cloud or portable deploy
├── .env.example      Environment variable template
└── SECURITY.md       Security model
```

---

## Settings Overview

The Settings page is the hub for all configuration:

| Section | What you can do |
|---------|----------------|
| **Preferences** | Toggle dark mode |
| **Accounts** | Add / edit / delete checking and savings accounts; set a low-balance warning threshold |
| **Categories** | Full tree CRUD — add/rename/recolor top-level and sub-categories; set monthly budget amounts inline; move sub-categories between parents |
| **Users** *(admin only)* | Create accounts with Admin or View Only role; toggle active status |
| **Activity Log** *(admin only)* | Browse all write operations with timestamp, user, method, path, status, and duration; filter by method |

---

## CSV Import

Navigate to **Import** in the sidebar.

1. Choose **Checking Account** or **Credit Card** and select the target account.
2. Drop a CSV file onto the upload area (or click to browse).
3. Review the preview — auto-categorized rows show a green badge; amber rows need a category assigned.
4. Click **Import** — duplicates (same date + description + amount already in the database) are skipped automatically.

Supported formats detected automatically from CSV headers:
- Chase checking (`Details`, `Posting Date` columns)
- Chase credit card (`Transaction Date`, `Category` columns)
- Apple Card (`Transaction Date`, `Merchant` columns)
- Generic fallback (date, description, amount)

---

## CLI Quick Reference

```bash
source .venv/bin/activate

python cli/budget.py users create
python cli/budget.py accounts list --username alice
python cli/budget.py recurring list --username alice
python cli/budget.py forecast quarters --username alice --account "Main Checking"
python cli/budget.py forecast show --username alice --account "Main Checking" --quarter Q2-2026
python cli/budget.py cards list --username alice
```

---

## Backup

```bash
cp data/budget.db data/budget_$(date +%Y%m%d).db
```

All data lives in `data/budget.db`. Copy it anywhere to back it up or restore it.

---

## Migration Path to Cloud

1. Change `DATABASE_URL` in `.env` to a PostgreSQL connection string
2. `docker-compose up` — no code changes required
3. Point CORS origins to your domain
4. See [SECURITY.md](SECURITY.md) for cloud hardening steps

---

## Original OfflineBudget

The previous version of the app is preserved in `old_version/` inside this directory.
