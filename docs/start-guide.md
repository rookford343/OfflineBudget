# Getting Started Guide

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| Node.js | 20+ | `node --version` |
| npm | 9+ | `npm --version` |

---

## 1. First-Time Setup

```bash
# Clone or copy the project
cd /path/to/OfflineBudgetv2

# Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate           # macOS/Linux
# .venv\Scripts\activate            # Windows

# Install Python dependencies
pip install -r backend/requirements.txt
pip install typer rich               # CLI extras

# Install frontend dependencies
cd frontend && npm install && cd ..

# Copy the environment file
cp .env.example .env
```

### Generate a secure JWT secret

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output into `.env` as the value for `JWT_SECRET`.

---

## 2. Start the App

```bash
# From the project root:
./scripts/start.sh
```

This starts:
- **Backend API** at `http://localhost:8000`
- **Frontend UI** at `http://localhost:5173`
- **API docs** at `http://localhost:8000/docs`

---

## 3. Create Your Account

1. Open `http://localhost:5173` in your browser
2. Click **Create Account**
3. Enter a username, password, and your name
4. Click **Create Account** — you'll land on the Dashboard

> Your wife can create her own account by visiting the same URL and clicking **Create Account**.

---

## 4. Access from Another Device on Your Home Network

1. Find your Mac's local IP address:
   ```bash
   ipconfig getifaddr en0
   # e.g., 192.168.1.42
   ```
2. In your `.env`, update `ALLOWED_ORIGINS`:
   ```
   ALLOWED_ORIGINS=http://localhost:5173,http://192.168.1.42:5173
   ```
3. Restart the app (`./scripts/start.sh`)
4. On your wife's phone or laptop, open `http://192.168.1.42:5173`

---

## 5. Initial Budget Setup (Recommended Order)

### Step 1 — Add Accounts (Settings page)
- **Main Checking** — enter your current balance
- **Money Market** or savings account (optional)

### Step 2 — Add Recurring Income (Recurring page)
- "Danny Paycheck 1" — Income, $6,066.63, Day 15
- "Danny Paycheck 2" — Income, $6,066.63, Day 0 (last day)
- Any bonus as a one-time or monthly averaged item

### Step 3 — Add Recurring Bills (Recurring page)
Add each bill with its day-of-month. Examples:
| Name | Amount | Day |
|------|--------|-----|
| Chevy Insurance | $194 | 2 |
| Duke Electric | $180 | 8 |
| HOA | $xxx | 1 |
| Rivian R1T | $500.89 | 17 |

### Step 4 — Add Credit Cards (Credit Cards page)
- Chase Sapphire, Apple Card, Amex, etc.
- Enter current balance and balance due

### Step 5 — View Your Forecast (Forecast page)
- Select your checking account
- Choose the current year
- See day-by-day projected balances

---

## 6. Recording Transactions

**Manual entry:** Go to **Transactions → Add** and fill in the date, amount (negative for expenses), and category.

**Credit card charges:** Go to **Credit Cards → [card name] → Add Transaction**.

**Credit card payments:** Go to **Credit Cards → [card name] → Record Payment** — this automatically deducts from checking.

---

## 7. CLI Usage

The CLI uses the same database as the web app — no server required.

```bash
# Always run from the project root with the venv active
source .venv/bin/activate

# Create a user (if not using the web UI)
python cli/budget.py users create

# List accounts
python cli/budget.py accounts list --username danford

# See quarterly forecast
python cli/budget.py forecast quarters --username danford --account "Main Checking"

# See a specific quarter
python cli/budget.py forecast show --username danford --account "Main Checking" --quarter Q2-2026

# List credit cards
python cli/budget.py cards list --username danford
```

---

## 8. Backing Up Your Data

All data lives in one file: `data/budget.db`

```bash
# Quick backup
cp data/budget.db data/budget_$(date +%Y%m%d).db

# Restore a backup
cp data/budget_20260428.db data/budget.db
```

Set up a daily cron backup:
```bash
crontab -e
# Add: 0 2 * * * cp /path/to/OfflineBudgetv2/data/budget.db /path/to/backups/budget_$(date +\%Y\%m\%d).db
```
