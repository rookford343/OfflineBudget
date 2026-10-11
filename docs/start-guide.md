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
3. Enter a username, a password (at least 6 characters), and your name
4. Click **Create Account**. You'll land on the Dashboard with a Quick Start
   wizard. This first account is the admin.

**Sign-up closes after the first account.** The app listens on your whole home
network, so once one account exists, **Create Account** is refused for
everyone. Add the rest of your household yourself in **Settings → Household**:

| Role | Can do |
|------|--------|
| **Admin** | Everything, including adding household members and resetting their passwords |
| **View Only** | See every page, but change nothing. They can still change their own password |

Link a household member to your account and they see *your* budget; leave
them unlinked and they get a budget of their own.

> More than ten sign-in attempts in 15 minutes locks that username out of signing in from
> that device for 15 minutes.

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
- Enter the current balance, statement day and due day for each card
- **Statement balance (balance due)**: the last statement's total, which the
  forecast pays on the due date
- **Pending Charges**: charges that haven't posted yet. Bank sync fills this
  in for issuers that report pending charges; otherwise type it yourself

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

After saving, go to **Tax** (Money → Tax in the sidebar) to see your full estimated tax liability for any year.

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

## 11. Adventures (trip planning with points)

Use Adventures to plan and track trips that you're paying for with a mix of cash and loyalty points. Track each item's cost (cash + points), set transfer hints for when you're short on points, and forecast the trip as part of your budget.

### The points wallet

Enter your current loyalty-program balances by hand under **Settings → Adventures → Points Wallet**. Each balance shows "updated N days ago" in gray; the label turns amber if a balance hasn't been updated in 30 days.

Loyalty programs you don't actively use are collapsed by default under "Other programs" — expand to add or remove any program.

### Partners and bonuses

Each loyalty program can have a transfer ratio and optional bonuses:

- **Ratio** — how many points of Program A equal 1 point in Program B (e.g., 1:1.25).
- **Bonus** — an optional percent boost that applies through a specific end date (e.g., "+25% until Dec 31"). Once the date passes, the bonus no longer applies. Bonuses with no end date stay active until you manually remove them.

Edit these under **Settings → Adventures → Partners & Bonuses**.

### Starting a new adventure

When you create a new trip, it starts with a copy of your Adventure checklist template:

1. Go to **Adventures → Create Trip**
2. Enter the trip name, start and end dates, and your travelers
3. The template checklist populates automatically with items like "Flights", "Hotel", "Ground transport", and a Buffer for incidentals

**Editing the checklist:**

- Remove an item from the trip only — click the item's delete icon
- Remove from both the trip *and* the template for future trips — the app asks which you mean

**Scaling:** per-day items (e.g., meals) and per-person items (e.g., park tickets) scale automatically based on your trip dates and number of travelers.

### The Buffer item

The Buffer is an automatic line item that covers incidentals:

- By default, it's **10% of the cash owed on all your trip's other items**
- It's always **paid in cash** — the payment toggle (cash / points / mix) is disabled for Buffer
- To use a different amount, type a custom value in the cash field — this replaces the automatic 10%

### Paying for items with cash, points, or a mix

Each item can be split between cash and loyalty points:

- Enter the total cash price and the points you want to spend
- **Taxes and fees on award bookings count as cash**, not points — if an award flight costs 50,000 points plus $75 in taxes, enter 50,000 points and $75 cash
- The **¢/pt ratio** (cost per point) is calculated as: `(cash price − taxes) ÷ points × 100`

### Transfer suggestions

When you're short on points for an item:

1. The app shows a suggestion for the cheapest transfer — it picks the source program and uses any active bonus to minimize the cost
2. Click **Attach** to lock in that transfer as part of your trip plan
3. The transfer count and bonus details appear on the item

### Committing to your forecast

**Commit to Forecast** turns each unpaid item that still owes cash into a Planned One-Off on the app's forecast. The one-off:

- Lands on the **trip start date**, charged to the **card** you selected for the trip
- Appears on your Forecast and daily balance projection

**Editing a committed trip:** changes to item amounts, dates, or cards automatically update the corresponding one-offs.

**Back to Planning:** removes all unpaid one-offs, letting you edit the trip without affecting your forecast.

### Marking items as paid

Once you've paid for an item (swiped your card, confirmed a bank transaction), check the **paid** checkbox. This:

- Marks the item as paid
- Settles its planned one-off in the Forecast, removing it from your daily balance projection

Points balances do not change when marking paid — they update only when you click **Done**.

### Done with your trip

Click **Done** once the trip is committed. The app shows a summary of how many points you spent from each program. Confirm, and:

- Points balances update permanently
- The trip moves to your history

If you delete a trip, only the unpaid one-offs are removed; paid items stay as history.

### Trip fund (optional)

Set up an optional Goal for trip savings. When you create or edit a trip:

1. Choose a Goal to track trip savings
2. The app targets it to **7 days before the trip start** — the final payment date
3. Click **Update Fund Target** to sync the goal's target amount with your trip's remaining balance

This works best if the Goal already exists — create it first under **Money → Goals**, then link it when you set up the trip.

---

## 12. Wish List

Use Wish List to plan purchases — from a new laptop to home renovations — and see when you can safely afford them without dipping below your safety net.

### Setting a safety cushion

The **cushion** is your financial safety net — the minimum balance you want to maintain in your checking account. It's per-user and has a fallback chain:

- If you enter a cushion in the **Cushion** field at the top of the Wish List page, that's used.
- Otherwise, the app falls back to your checking account's low-balance threshold (if set).
- If neither is set, the default is $1,000.

Leave the cushion field blank to use the fallback.

Wishes are only considered "safe to buy" if, from the buy date forward through the end of the 12-month window, your lowest projected balance stays at or above the cushion.

### Adding a wish and its cost

Click **Create Wish** and enter:

- **Name** — what you're buying
- **Price** — the full cost (before trade-in credit)
- **Trade-in value** — money you'll get for a trade-in, optional
  - **Now:** credited immediately at purchase, lowering the price you pay
  - **Later:** credited on a date you set (you pay full price today, get credit back later)
- **Extra costs:** optional items like taxes, shipping, or installation. Each has its own date. Add as many as needed — they're accounted for separately in the forecast.

### Choosing how to pay

Each wish can have multiple payment options. Add one or more:

- **Full price from checking:** one payment on the buy date, pulled from checking
- **Full price on a card:** one payment charged to the card you pick; the money leaves checking on that card's payoff date
- **Financed:** split into monthly payments
  - **Down payment (optional):** money paid upfront
  - **Card (optional):** if you pick a card, payments land on that card's payoff date; without a card, they're drawn from checking
  - **Months:** 1 to 84
  - **APR:** any rate, including 0% (zero interest). The monthly payment is calculated as principal ÷ months at 0%, or using standard amortization at higher rates. The final payment absorbs any rounding.

Cards come from your **Credit Cards** page; add one there first before selecting it here.

### When can you buy?

The **earliest safe date** is the first day in the next 12 months where your lowest projected balance (from that day forward) stays at or above your cushion. It accounts for:

- Your income and bills
- All wishes ranked above this one (which will already be bought by then)
- Your chosen payment option and its schedule

If nothing fits within the next 12 months, the page shows "doesn't fit" with the closest date and by how much you'd fall short.

**Using your own date:** you can set a custom "I want it on" date instead. If it's in the past, it's ignored (and the page falls back to the earliest safe date). If it's a valid future date, the page shows whether it stays above the cushion and by how much.

### Ranking and stacking

Wishes are stacked — each one assumes all the wishes ranked above it are already bought on their planned dates. Drag wishes to reorder them. Committing a wish doesn't change the ranks of others, but the forecast updates to assume that purchase is done.

### Committing a wish

Once you've chosen a payment option and a buy date (automatic or custom), click **Commit**. This turns your choice into real items in the forecast:

- **Full from checking:** adds one Planned One-Off on the buy date
- **Full on a card:** adds one Planned One-Off on the buy date, charged to the card; the money leaves checking on that card's payoff date
- **Financed from checking:** adds a down payment one-off (if any), then a monthly Recurring Payment, then a final one-off for the last payment
- **Financed on a card:** adds one Planned One-Off per payment, each dated on its payment date and charged to the card; the money leaves checking on that card's payoff date
- **Trade-in (later):** adds a credit (inflow) on the date you set

### Uncommitting a wish

Click the **Uncommit** button on a committed wish. This removes exactly the rows that commitment created. You can only uncommit if no payments have posted yet — once a bank transaction is linked to the created payment, you'll need to edit or delete it on the Recurring page instead.

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

Password-reset emails and the **Send test email** button on your Profile use
these same settings, so one SMTP setup covers every email the app sends.

### What the daily email contains

The daily report arrives at 7:15am by default, right after the morning bank sync, so it
reports fresh numbers:

- **Household Snapshot**: Spendable this week, Safety Margin, and the lowest
  projected balance in the next three months.
- **Spending this month**: total spent since the 1st, spending by category
  (highest first) and your top merchants. These are the same numbers as the
  Dashboard's digest card, just over the month instead of the week.
- **Checking Accounts**: each balance and when its last transaction posted.
- **Upcoming (next 7 days)**: bills and income due this week, using a real
  bill amount when you've entered one.
- **Credit Cards**: balance, the statement payoff coming up, and spending
  since the statement closed.
- **Weekly Digest**: on your chosen digest day only, the past seven days'
  spending plus a warning if the balance is projected to dip below your
  threshold.

### Connect your bank (optional)

Bank sync uses [SimpleFIN Bridge](https://beta-bridge.simplefin.org/)
(about $15/year, read-only). SimpleFIN only reads your accounts; it can't
move money.

1. Sign up at SimpleFIN Bridge, connect your bank there, and copy a
   **setup token**.
2. In **Settings → Accounts & Bank Sync → Bank Connections**, paste the token.
3. Link each SimpleFIN account to the matching account or credit card in the
   app.

After that, everything is automatic:

| When | What syncs |
|------|-----------|
| **7:00am** | Every linked account and card: posted transactions, balances, and card pending charges |
| **3:17pm** | Credit cards only, to refresh pending charges |
| **Sync Now** | Everything, whenever you press it |

SimpleFIN asks apps to stay under **24 requests a day**. Each linked account
or card costs one request per sync, so the schedule above uses about six a day
for a typical household (checking, savings and two cards). That leaves room
for a few **Sync Now** presses. SimpleFIN itself refreshes from your bank
roughly once a day, so syncing more often rarely finds anything new.

Imported transactions are categorized by your rules and linked to the
recurring bill they pay, so the forecast stops projecting that bill.

### Pending card charges

Card issuers that report pending charges (Chase does) send them along with
each sync:

- They appear in **Transactions** (the All and Credit Cards tabs) with a
  **pending** badge. They can't be edited or categorized yet.
- Every sync replaces the whole pending list. When a charge posts, it drops
  off the list and comes in as a normal transaction, so nothing is ever
  counted twice.
- The card's **Pending Charges** figure fills in automatically from that list,
  and the forecast and Safety Margin plan for it.
- Pending charges are never counted as spending in Spending, budgets or the
  emails until they post.

Some issuers never report pending charges (Apple Card doesn't). For those
cards, type the figure on the **Credit Cards** page; it clears itself once
new posted activity syncs.

> SimpleFIN can lag your card app by a few hours to a day, so the pending total
> in OfflineBudget may trail what your issuer's app shows.

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
