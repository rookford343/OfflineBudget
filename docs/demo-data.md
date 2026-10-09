# Demo Data Guide

How to load realistic demo data for testing or screenshots, and how to fully wipe user data from the backend.

---

## Loading the Demo Account

The demo script creates a complete dual-income household with realistic 2024–2025 benchmark figures: two checking/savings accounts, two credit cards, 17 recurring items, 33 checking transactions, 35 credit card charges, and 11 budget allocations across April–May 2026.

**Login after seeding:** `username: demo` / `password: demo123`

### Steps

```bash
# 1. Navigate to the project root
cd /path/to/OfflineBudget

# 2. Activate the Python virtual environment
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# 3. Run the seed script
python scripts/seed_demo.py
```

The script is safe to re-run. If a `demo` user already exists it will delete it and all associated data first, then re-seed from scratch.

### What Gets Created

| Item | Detail |
|------|--------|
| User | `demo` / `demo123` |
| Main Checking | $4,847.33 balance |
| High-Yield Savings | $11,200.00 balance |
| Chase Sapphire Preferred | $1,423.87 balance, $15k limit |
| Apple Card | $143.22 balance, $5k limit |
| Recurring items | 17 items: 2 paychecks, mortgage, car payments, utilities, subscriptions, giving |
| Checking transactions | 33 entries across April and May 2026 |
| Credit card transactions | 35 entries: Kroger, Target, Amazon, Costco, dining, gas, Apple |
| Budget allocations | 11 category budgets for 2026 |

### Monthly Budget Summary (Demo)

```
Net income:         $7,200.00 / month
Committed expenses: $4,674.93 / month (fixed recurring bills)
Discretionary:      $2,525.07 / month (groceries, dining, gas, etc.)
```

### Troubleshooting

**`ModuleNotFoundError: No module named 'backend'`**

The script must be run from the project root so Python can find the `backend` package. Make sure you are inside the `OfflineBudget` directory:

```bash
# Correct
cd /path/to/OfflineBudget
python scripts/seed_demo.py

# Wrong — backend package not on sys.path
cd /path/to
python OfflineBudget/scripts/seed_demo.py
```

**`ModuleNotFoundError: No module named 'apscheduler'` or similar**

The virtual environment is not activated, or dependencies are not installed:

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
```

**`sqlite3.OperationalError: no such table`**

Start the backend once first so `create_tables()` runs, then re-run the seed:

```bash
uvicorn backend.main:app --reload &
# wait a moment, then Ctrl+C and run:
python scripts/seed_demo.py
```

Alternatively, the seed script calls `create_tables()` itself, so a plain run should work as long as the `data/` directory exists. Create it if needed: `mkdir -p data`.

---

## Removing User Data

### Option 1: Delete a user via the Settings UI

1. Log in as an admin account.
2. Go to **Settings → Users**.
3. Click the trash icon next to the user you want to remove.

This deletes the user record. SQLite foreign-key cascades remove all associated accounts, transactions, recurring items, categories, budgets, and credit cards automatically.

> **Note:** You cannot delete yourself this way — only other users. To delete your own account, use **Settings → Profile → Danger Zone → Delete my account**.

### Option 2: Delete via the API (admin)

```bash
# Replace <ID> with the user's numeric ID
curl -X DELETE http://localhost:8000/admin/users/<ID> \
  -H "Authorization: Bearer <your-admin-token>"
```

### Option 3: Delete the demo user directly in SQLite

Useful when the backend is not running, or you want to script a full reset.

```bash
# Activate the virtual environment first
source .venv/bin/activate

sqlite3 data/budget.db "DELETE FROM users WHERE username = 'demo';"
```

SQLite foreign-key cascades handle all child records. If cascades are not enabled in your SQLite build, delete in this order:

```sql
DELETE FROM transactions          WHERE user_id = (SELECT id FROM users WHERE username = 'demo');
DELETE FROM credit_card_transactions WHERE user_id = (SELECT id FROM users WHERE username = 'demo');
DELETE FROM recurring_items       WHERE user_id = (SELECT id FROM users WHERE username = 'demo');
DELETE FROM budget_allocations    WHERE user_id = (SELECT id FROM users WHERE username = 'demo');
DELETE FROM credit_cards          WHERE user_id = (SELECT id FROM users WHERE username = 'demo');
DELETE FROM accounts              WHERE user_id = (SELECT id FROM users WHERE username = 'demo');
DELETE FROM categories            WHERE user_id = (SELECT id FROM users WHERE username = 'demo');
DELETE FROM users                 WHERE username = 'demo';
```

### Option 4: Wipe the entire database

This deletes all users and all data. The database will be recreated fresh on the next server start.

```bash
# Stop the backend first if it is running
rm data/budget.db data/budget.db-shm data/budget.db-wal 2>/dev/null; true
```

The next time the backend starts, `create_tables()` and `upgrade_schema()` will recreate all tables. Then re-run the seed script if you want demo data back.

---

## Updating the Demo Script

The seed script is at [scripts/seed_demo.py](../scripts/seed_demo.py). To change figures or add more transactions, edit the `actuals`, `card_txns`, or `recurring_items` lists directly — the file is self-contained and well-commented. After editing, re-run it:

```bash
python scripts/seed_demo.py
```

Because the script deletes the existing `demo` user before re-seeding, changes take effect immediately on the next run.

---

## Loading the demo

```bash
source .venv/bin/activate
DATABASE_URL="sqlite:///./data/demo.db" python scripts/seed_demo.py
```

Pointing `DATABASE_URL` at a separate file keeps the demo entirely away from
your real `budget.db`. To run the app against it:

```bash
DATABASE_URL="sqlite:///./data/demo.db" \
  ALLOWED_ORIGINS="http://127.0.0.1:5174,http://localhost:5174" \
  uvicorn backend.main:app --host 127.0.0.1 --port 8001

# in another terminal
cd frontend && VITE_API_URL="http://127.0.0.1:8001" bun run dev --port 5174
```

Sign in with **demo / demo123**.

Transaction dates are generated relative to today — last month and this month
— so every page that defaults to the current month has data in it. Seeding it
in December works the same as seeding it in August.

Every screenshot in the README and on the docs site is captured from exactly
this dataset.
