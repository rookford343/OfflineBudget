# Future Work & Roadmap

## Shipped Features (Current Version)

### Core Budgeting
- ✅ Day-by-day forecast engine with recurring items
- ✅ Quarterly and multi-year (1/2/3/5 year) forecast views
- ✅ Budget scenario planning with named scenarios and per-item overrides
- ✅ Monthly category budgets with rollover support
- ✅ Savings-type category exclusion from spending totals

### Import & Categorization
- ✅ CSV import: Chase checking, Chase card, Apple Card, generic
- ✅ OFX/QFX import (bank-standard format)
- ✅ Auto-categorization: keyword matching + import history
- ✅ User-defined transaction rules engine (contains / startswith / regex)
- ✅ Import deduplication (same date + description + amount)
- ✅ Import grouping — normalizes descriptions to batch similar charges
- ✅ Skip auto-categorization toggle for manual review workflows

### Spending Analysis
- ✅ Monthly spending bar chart and stacked category chart
- ✅ Year-over-year trends (up to 3 years) and 24-month rolling chart
- ✅ Spending by merchant — sortable ranked table
- ✅ Sankey income-to-expense flow diagram
- ✅ Quick date filters (This Month / 3 Months / YTD / Last Year)

### Tax
- ✅ Full 2025 federal tax estimate with bracket ladder
- ✅ State income tax (approximate effective rates, all 50 states + DC)
- ✅ FICA — Social Security + Medicare with additional Medicare threshold
- ✅ Itemized deductions (mortgage interest, donations, SALT, property tax, other)
- ✅ Itemized vs. standard deduction comparison (automatic)
- ✅ Tax-deductible transaction tagging and CSV export
- ✅ Social Security wage base tracker (consolidated into Tax Profile)

### Reconciliation & Net Worth
- ✅ Transaction reconciliation with recurring item linking
- ✅ Quarterly balance checkpoints
- ✅ Net worth tracking with assets, liabilities, and historical snapshots

### Other
- ✅ Credit card tracking with due dates, utilization, and payment recording
- ✅ Savings goals with progress tracking
- ✅ Planned expenses
- ✅ Multi-user support (admin and view-only roles)
- ✅ Audit log for all write operations
- ✅ Daily email summary (requires SMTP config)
- ✅ HTTPS on LAN (self-signed cert via `scripts/setup-ssl.sh`)
- ✅ Data export (transactions CSV, budget report)
- ✅ Danger Zone: clear transactions, clear CC transactions, delete account
- ✅ Navigation order customization (per-browser localStorage)
- ✅ Account balance correction (click balance in Settings → Accounts)
- ✅ Docker compose for cloud / portable deploy

---

## Potential Next Features

### High Priority

**Automated Bank Sync (Plaid)**
Connect directly to 10,000+ financial institutions via Plaid API. New transactions would sync automatically — no more manual CSV exports. Would use cursor-based incremental fetches and run through the same import pipeline (deduplication, categorization, rules). Requires: `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` env vars; encrypted token storage (`cryptography` / Fernet).

**CLI Import Command**
```bash
python cli/budget.py import csv ./chase_may.csv --account-id 1 --username alice
python cli/budget.py import csv ./chase_may.csv --account-id 1 --username alice --auto-confirm
```
CLI import would show a Rich preview table and require explicit `--auto-confirm` for scripting/cron use. Would call the same `import_service.build_preview()` / `run_import()` functions.

**Split Transactions**
Divide a single charge into multiple categories (e.g., a Costco run split between Groceries and Household). Backend: `TransactionSplit` table linked to parent transaction with `sum(splits) == abs(amount)` validation. Frontend: expandable rows in the transaction list.

### Medium Priority

**Reconciliation: Per-Row Cleared Status**
Add a `cleared_at` timestamp column to `Transaction`. Show a checkmark toggle per row in the Reconcile tab so users can mark individual transactions as cleared against their bank statement.

**Budget Rollover Display**
The `rollover_enabled` and `rollover_balance` fields exist on `Category` but are not surfaced in the Budget UI. Add visible rollover balance indicators showing month-over-month carry-forward amounts.

**CC Payoff Import: Auto-Update Card Balance**
When a checking CSV import contains a transfer to a credit card (matched by card nickname or last-four), automatically reduce the card's balance. Best-effort fuzzy matching.

**CC Import: Mark as Recurring**
When reviewing imported CC transactions, add a recurring-item shortcut button per row. Pre-fills a "New Recurring" mini-modal with merchant name, amount, and day-of-month so the item can be added in one click without navigating to Settings.

### Lower Priority

**Import Watch Directory (CLI)**
```bash
python cli/budget.py import watch ~/Downloads --account-id 1 --username alice
```
Uses `watchdog` to monitor a directory. When a new `.csv`, `.ofx`, or `.qfx` file is detected, automatically triggers the import pipeline.

**Multi-Household Support**
Current model: all users in an instance share data. Future: `household_id` on all entities, allowing truly separate budgets for different families on the same server.

**Month-Specific Budgets**
Currently `month=0` applies a budget amount to all months. Allow per-month overrides (e.g., higher grocery budget in November/December).

---

## Technical Debt

- Add Alembic migrations (`alembic revision --autogenerate`) once schema stabilizes — currently `upgrade_schema()` handles additive changes with idempotent `ALTER TABLE` statements
- Add a proper test suite: `pytest tests/` with fixtures for forecast engine edge cases and import pipeline
- Add `pytest-httpx` integration tests for API routers
- Implement Vite bundle splitting to reduce the JS bundle size
- Add React error boundaries so one broken component doesn't crash the whole page
