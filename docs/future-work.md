# Future Work & Roadmap

## Phase 4 — CSV Transaction Import ✓ Shipped

CSV import is complete. Supported features:

### Bank CSV Import (Checking Account) ✓
- Detects format from header row: Chase, Wells Fargo, BofA, Apple Card, generic
- Maps columns: date, description, amount
- Deduplicates against existing transactions (same date + amount + description)
- Drag-and-drop or click-to-browse upload on the Import page

### Credit Card CSV Import ✓
- Chase Sapphire and Apple Card formats detected automatically
- `CreditCardImport` table tracks imports to prevent double-import

### Auto-Categorization ✓
- Keyword matching rules (merchant → category mapping)
- History-based matching: past transaction descriptions are used to suggest categories for new imports
- Manual override for uncategorized rows before confirming import

---

## Phase 5 — Reconciliation

Match imported actual transactions against forecast recurring items:

- When an actual transaction is imported that matches a recurring item (same day ± 2 days, same approximate amount), auto-link `transaction.recurring_item_id`
- Reconciliation view: show month's forecast side-by-side with actuals
- "Mark as reconciled" workflow — hide matched items, surface unmatched
- Variance report: actual vs. forecast per category for closed months

---

## Phase 6 — Enhanced Forecasting

### Savings Transfer Automation
- Define a quarterly savings target (e.g., "transfer $2,000 to Money Market each Q")
- Forecast engine includes the transfer on day 1 of each quarter
- UI shows projected savings account balance over time

### Money Market Interest Projection
- Input annual interest rate on savings/money market accounts
- Forecast engine adds monthly interest credit automatically
- Net worth tracking view (checking + savings - card balances)

### Multi-Year Forecast
- Extend forecast beyond current year
- Model salary increases: create new `RecurringItem` with a `start_date` in the future
- Annual budget copy: clone current year's allocations to next year

### Budget Scenario Planning
- "What if I reduce Food & Drinks by $200/month?" — run a shadow forecast
- Side-by-side comparison: current plan vs. modified plan

---

## Phase 7 — Reporting & Notifications

### Annual Tax Summary
- Export a year's spending by category in CSV
- Highlight deductible categories (charitable giving, mortgage interest)

### Monthly Email/Push Summary
- Cron job that generates a spending summary
- "You're $342 over budget in Food & Drinks this month"
- Sent to configured email address or as a push notification

### Spending Trend Analysis
- Month-over-month and year-over-year charts by category
- Anomaly detection: "Shopping is 40% higher than your 3-month average"

---

## Phase 8 — Cloud / Multi-Device

### HTTPS on LAN
- Generate a self-signed cert with `mkcert` — see `SECURITY.md`
- Update Vite `server.https` config and backend to serve HTTPS

### Cloud Deployment
- Replace `sqlite:///./data/budget.db` with PostgreSQL connection string
- Deploy backend to Railway / Render / Fly.io (single `uvicorn` process)
- Build frontend: `npm run build` → serve static files from Nginx or Caddy
- See `docker-compose.yml` for the full container stack

### Optional: Multi-Household Support
- Current multi-user model: all users see all shared data
- Future: `household_id` on all entities; users belong to a household
- Allows truly separate budgets for different families using the same server

---

## Known Limitations (Current Version)

| Area | Limitation | Workaround |
|------|-----------|------------|
| CSV import | Built — Chase, Apple Card, generic | — |
| Reconciliation | Not yet built (Phase 5) | Visual comparison only |
| Month-specific budgets | month=0 applies to all months | Set per-month via API directly |
| HTTPS on LAN | Not configured by default | Use mkcert (see SECURITY.md) |
| Notifications | Not yet built | Check app manually |
| Savings interest | Not projected | Add as a recurring income item |
| Budget.xlsx import | Not built | Re-enter data in the UI |

---

## Technical Debt to Address

- Add Alembic migrations (`alembic revision --autogenerate`) once the schema stabilizes — currently `create_tables()` handles first-run
- Add a proper test suite: `pytest tests/` with fixtures covering forecast engine edge cases
- Add `pytest-httpx` integration tests for the API routers
- Implement bundle splitting in Vite config to reduce the 747KB JS bundle
- Add error boundaries in React so one broken component doesn't crash the whole page
