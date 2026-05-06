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

## Phase 5 — Reconciliation ✓ Shipped

Match imported actual transactions against forecast recurring items:

- Auto-link `transaction.recurring_item_id` on import when day ± 3 and amount within 10%
- Reconciliation view in Transactions → Reconcile tab: matched, unmatched recurring, and unlinked transactions
- Variance report: actual vs. expected per recurring item

---

## Phase 6 — Enhanced Forecasting ✓ Shipped (partial)

### Money Market Interest Projection ✓
- Annual interest rate field on accounts (Settings → Accounts → Edit)
- Forecast engine applies monthly interest credit on last day of each month
- Interest appears as a projected "Interest Credit" transaction in the forecast

### Budget Scenario Planning ✓
- Named forecast scenarios with per-recurring-item amount overrides
- Side-by-side comparison: baseline vs. scenario traces on Forecast page

### Savings Transfer Automation (future)
- Define a quarterly savings target
- Forecast engine includes the transfer on day 1 of each quarter

### Multi-Year Forecast (future)
- Extend forecast beyond current year
- Annual budget copy

---

## Phase 7 — Reporting & Notifications ✓ Shipped

### Annual Tax Summary ✓
- Per-category `tax_deductible` flag (Settings → Categories → Edit)
- Export a year's deductible transactions as CSV — Spending → Tax Export tab

### Daily Email Summary ✓
- Scheduler sends a daily summary at a configurable hour (DAILY_SUMMARY_HOUR env var, default 7am)
- User sets email address in Settings → Profile → Email Notifications
- Test email button to verify SMTP config
- Summary includes: checking balances, upcoming bills (7-day window), MTD expenses, credit cards
- Requires SMTP server config in `.env` (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS)

### Spending Trend Analysis ✓
- Month-over-month and year-over-year charts — Spending → Trends tab

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
| Reconciliation | Built — Transactions → Reconcile tab | — |
| Month-specific budgets | month=0 applies to all months | Set per-month via API directly |
| HTTPS on LAN | Not configured by default | Use mkcert (see SECURITY.md) |
| Notifications | Daily email summary (requires SMTP config) | Check app manually |
| Savings interest | Projected when interest_rate set on account | — |
| Budget.xlsx import | Not built | Re-enter data in the UI |

---

## Technical Debt to Address

- Add Alembic migrations (`alembic revision --autogenerate`) once the schema stabilizes — currently `create_tables()` handles first-run
- Add a proper test suite: `pytest tests/` with fixtures covering forecast engine edge cases
- Add `pytest-httpx` integration tests for the API routers
- Implement bundle splitting in Vite config to reduce the 747KB JS bundle
- Add error boundaries in React so one broken component doesn't crash the whole page
