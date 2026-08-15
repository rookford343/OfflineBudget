# Getting Started Guide

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| Node.js | 20+ | `node --version` |
| bun | 1.0+ | `bun --version` |

---

## 1. First-Time Setup

```bash
# Clone or copy the project
cd /path/to/OfflineBudget

# Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate           # macOS/Linux
# .venv\Scripts\activate            # Windows

# Install Python dependencies
pip install -r backend/requirements.txt

# Install frontend dependencies
cd frontend && bun install && cd ..

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
4. Click **Create Account** — you'll land on the Dashboard with a Quick Start wizard

> Other users can create their own accounts by visiting the same URL and clicking **Create Account**.

---

## Forgot Your Password?

1. From the login page, click **Forgot password?**
2. Enter your username. If you have an email address saved on your account
   **and** SMTP is configured in `.env`, a reset link is emailed to you
   (expires in 15 minutes).
3. No email configured, or don't have access to it? Use a **recovery code**
   instead — generate one ahead of time from **Settings → Profile →
   Generate Recovery Code**. Codes are single-use; generate a new one after
   each reset.

> Set `FRONTEND_URL` in `.env` if the emailed reset link should point
> somewhere other than the first `ALLOWED_ORIGINS` entry.

---

## 4. Access from Another Device on Your Home Network

1. Find your machine's local IP address:
   ```bash
   ipconfig getifaddr en0      # macOS
   hostname -I | awk '{print $1}'  # Linux
   # e.g., 192.168.1.42
   ```
2. In your `.env`, update `ALLOWED_ORIGINS`:
   ```
   ALLOWED_ORIGINS=http://localhost:5173,http://192.168.1.42:5173
   ```
3. Restart the app (`./scripts/start.sh`)
4. On another device, open `http://192.168.1.42:5173`

---

## 5. Enable HTTPS on LAN (Optional but Recommended)

For encrypted connections when accessing from other devices:

```bash
./scripts/setup-ssl.sh
```

This generates `ssl/cert.pem` and `ssl/key.pem` with your current LAN IP in the Subject Alternative Name. The start script detects these files automatically and enables HTTPS for both the API and frontend.

After setup, access the app at `https://localhost:5173` and `https://192.168.1.42:5173`.

> Browsers will show a security warning for self-signed certificates. To eliminate warnings, install `mkcert` and use CA-signed certs instead — see [SECURITY.md](../SECURITY.md).

---

## 6. Initial Budget Setup (Recommended Order)

### Step 1 — Add Accounts (Settings → Accounts)
- **Main Checking** — enter your current balance
- **Money Market** or savings account (optional)

### Step 2 — Add Categories (Settings → Categories)
- The Quick Start wizard seeds a default category tree on registration
- Add sub-categories under the default parents to match your budget
- Set the **type** to `savings` for any category used for savings transfers — these are excluded from spending totals

### Step 3 — Add Recurring Income (Recurring page)
- "Paycheck 1" — Income, your net amount, Day 15
- "Paycheck 2" — Income, your net amount, Day 0 (last day of month)
- Any bonus as a one-time or monthly averaged item

### Step 4 — Add Recurring Bills (Recurring page)
Add each bill with its day-of-month. Examples:

| Name | Amount | Day |
|------|--------|-----|
| Auto Insurance | $194 | 2 |
| Electric Utility | $180 | 8 |
| HOA Fees | $125 | 1 |
| Car Payment | $501 | 17 |

### Step 5 — Add Credit Cards (Credit Cards page)
- Enter current balance and minimum payment for each card

### Step 6 — View Your Forecast (Forecast page)
- Select your checking account
- Choose the current year
- See day-by-day projected balances and quarterly summaries

---

## 7. Importing Transactions

### From the web UI
1. Go to **Import** in the sidebar
2. Choose **Checking Account** or **Credit Card** and select the target account
3. Upload a CSV or OFX/QFX file
4. Review the preview — auto-categorized rows show a green badge; amber rows need a category assigned
5. Click **Import** — duplicates are skipped automatically

**Supported CSV formats:** Chase checking, Chase credit card, Apple Card, generic (date/description/amount).
**OFX/QFX:** Auto-detected by file extension — works with most bank "Download Transactions" exports.

### Speeding up categorization

1. **Transaction Rules** (Settings → Transaction Rules) — define rules like "any description containing SPOTIFY → Subscriptions". These run on every future import.
2. **Import history** — once you categorize a merchant, the same description is categorized automatically next time.

---

## 8. Tax Profile Setup

Configure your tax information under **Settings → Profile → Tax Profile**:

1. **Filing Status** — Single, Married Filing Jointly, Married Separately, or Head of Household
2. **State** — 2-letter code (e.g., TX, CA)
3. **Annual Gross Salary** — your W-2 gross wages
4. **Federal/State Withholding YTD** — from your pay stubs
5. **Itemized Deductions** — enter mortgage interest (Form 1098), charitable donations, SALT, property taxes, and other deductions
6. **Social Security Tracker** — enter your gross per paycheck and YTD bonus to track when you'll hit the wage base

After saving, go to **Spending → Tax Export** to see your full estimated tax liability for any year.

---

## 9. CLI Usage

The CLI uses the same database as the web app — no server required.

```bash
# Always run from the project root with the venv active
source .venv/bin/activate

# Create a user (if not using the web UI)
python cli/budget.py users create

# List accounts
python cli/budget.py accounts list --username alice

# See quarterly forecast
python cli/budget.py forecast quarters --username alice --account "Main Checking"

# See a specific quarter
python cli/budget.py forecast show --username alice --account "Main Checking" --quarter Q2-2026

# List credit cards
python cli/budget.py cards list --username alice
```

---

## 10. Backing Up Your Data

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
# Add: 0 2 * * * cp /path/to/OfflineBudget/data/budget.db /path/to/backups/budget_$(date +\%Y\%m\%d).db
```

---

## Troubleshooting

**Backend won't start — ImportError**
Make sure you're running from the project root with the venv active:
```bash
source .venv/bin/activate
./scripts/start.sh
```

**Frontend shows "Cannot connect to API"**
Check that `ALLOWED_ORIGINS` in `.env` includes the URL you're accessing from. Restart the backend after changing `.env`.

**"Invalid token" after restarting**
If you changed `JWT_SECRET` in `.env`, all existing tokens are invalidated. Log in again.

**HTTPS cert not trusted by browser**
Self-signed certificates from `setup-ssl.sh` will show a warning. Click "Advanced → Proceed" once per browser. For permanent trust, use `mkcert` — see [SECURITY.md](../SECURITY.md).

---

## Email reports and bank sync

Both are optional and both are configured in the app rather than in files.

### Set up email

1. **Settings → Notifications & Email** (admin only).
2. Fill in your SMTP host, port, username, password and from-address. For
   Gmail use an [app password](https://support.google.com/accounts/answer/185833),
   not your account password.
3. Add **Daily Report Recipients** — comma-separated. These people don't need
   accounts in the app; this is just who receives the report. Leave it blank
   and it falls back to your own account email.
4. Pick the send hour and, if you want the weekly digest, the day it rides
   along on.
5. Hit **Send test email**. A saved form proves nothing about whether mail
   actually leaves your machine.

> The SMTP password is encrypted before storage and is never sent back to the
> browser. That requires `APP_ENCRYPTION_KEY` in your `.env` — generate one
> with:
> ```bash
> python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
> ```
> Without it the app refuses to store the password rather than writing it in
> plaintext.

### If your machine sleeps

Scheduled jobs on a laptop are unreliable by nature. Two mechanisms cover it:

- A missed trigger fires as soon as the process resumes, within a 12-hour
  grace window.
- A sweep every 20 minutes retries any job that hasn't *succeeded* today.
  This catches the case the grace window can't: the trigger fired on time,
  but the network wasn't up yet after waking.

Check **Settings → Preferences → Background Jobs** to see when each job last
succeeded, or what it failed with.

---

## Making Spending useful

Two settings change how much the Spending page tells you:

**Mark your discretionary categories.** In Settings → Categories, flag the
ones that are a choice each month — Shopping, Food & Drinks, Entertainment,
Subscriptions, Groceries. Everything else (mortgage, insurance, tithe) counts
as a fixed commitment. Spending then leads with the discretionary number,
which is the only part you can act on.

**Fix any merchant grouping that looks wrong.** Merchant names are grouped
automatically from raw bank descriptors, which are noisy — store numbers,
transaction ids, payment references. Hover any row on the Merchants tab and
click the pencil to rename it, or type an existing merchant's name to merge
the two together.
