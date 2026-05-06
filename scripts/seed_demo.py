#!/usr/bin/env python3
"""
Demo seed: dual-income family of four, suburban US household.

Figures sourced from 2024-2025 benchmarks:
  - Income: ~$120k combined gross → ~$7,200/month net (Census P60-286, 2024)
  - Mortgage: $2,185/month (Census ACS 2024 median for recent buyers, slight discount for 2020 purchase)
  - Auto loans: $672 new SUV + $445 used sedan (Experian Q3 2025, adjusted for mid-life loans)
  - Auto insurance: $214/month two-vehicle (Bankrate 2025 with multi-car discount)
  - Utilities: Electric $145, Gas $78, Water $84, Internet $80, Cell $155 (Move.org 2025)
  - Groceries: ~$1,150/month (USDA Moderate-Cost Food Plan, Jan 2025)
  - Subscriptions: Netflix $22.99, Disney+/Hulu $12.99, Spotify $17.99, Prime $14.99

Run from project root:
    source .venv/bin/activate
    python scripts/seed_demo.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal
from datetime import date
from backend.database import SessionLocal, create_tables
from backend.auth import hash_password
from backend import models
from backend.seed import seed_default_categories

create_tables()
db = SessionLocal()

# ─── 1. User ──────────────────────────────────────────────────────────────────

existing = db.query(models.User).filter(models.User.username == "demo").first()
if existing:
    print("Demo user already exists — clearing and re-seeding...")
    db.delete(existing)
    db.commit()

user = models.User(
    username="demo",
    hashed_password=hash_password("demo123"),
    display_name="Demo User",
)
db.add(user)
db.commit()
db.refresh(user)
seed_default_categories(db, user)
print(f"✓ Created user 'demo' (id={user.id})")

# ─── 2. Accounts ──────────────────────────────────────────────────────────────
# Checking balance: mid-month after bills cleared, before next paycheck
# HYSA: ~1.5 months of committed expenses as emergency fund base

checking = models.Account(
    user_id=user.id,
    name="Main Checking",
    type="checking",
    current_balance=Decimal("4847.33"),
    currency="USD",
    notes="Primary household checking account",
)
db.add(checking)

hysa = models.Account(
    user_id=user.id,
    name="High-Yield Savings",
    type="money_market",
    current_balance=Decimal("11200.00"),
    currency="USD",
    notes="Emergency fund — 4.75% APY",
)
db.add(hysa)
db.commit()
db.refresh(checking)
db.refresh(hysa)
print(f"✓ Created accounts: checking (id={checking.id}), HYSA (id={hysa.id})")

# ─── 3. Credit Cards ──────────────────────────────────────────────────────────

chase = models.CreditCard(
    user_id=user.id,
    name="Chase Sapphire Preferred",
    last_four="4521",
    credit_limit=Decimal("15000"),
    statement_day=25,
    due_day=22,
    current_balance=Decimal("1423.87"),
    balance_due=Decimal("2109.44"),
    notes="Primary rewards card — travel + dining",
)
db.add(chase)

apple = models.CreditCard(
    user_id=user.id,
    name="Apple Card",
    last_four="8834",
    credit_limit=Decimal("5000"),
    statement_day=1,
    due_day=28,
    current_balance=Decimal("143.22"),
    balance_due=Decimal("143.22"),
    notes="Daily cash back via Apple Pay",
)
db.add(apple)
db.commit()
db.refresh(chase)
db.refresh(apple)
print(f"✓ Created credit cards (id={chase.id}, id={apple.id})")

# ─── 4. Category lookups ──────────────────────────────────────────────────────

def cat(name: str) -> int | None:
    c = db.query(models.Category).filter(
        models.Category.user_id == user.id,
        models.Category.name == name,
    ).first()
    return c.id if c else None

income_id       = cat("Salary / Wages")
necessities_id  = cat("Necessities")
utilities_id    = cat("Utilities")
insurance_id    = cat("Insurance")
transport_id    = cat("Transportation")
mortgage_id     = cat("Mortgage / Rent")
food_id         = cat("Food & Drinks")
shopping_id     = cat("Shopping")
entertainment_id = cat("Entertainment")
subscriptions_id = cat("Subscriptions")
savings_id      = cat("Savings")
charity_id      = cat("Church / Tithe")
other_id        = cat("Other")

# ─── 5. Recurring Items ───────────────────────────────────────────────────────
# Income: two semi-monthly paychecks representing combined household take-home
# Total net: $7,200/month ($3,600 × 2)

recurring_items = [
    # ── Income ────────────────────────────────────────────────────────────────
    dict(name="Paycheck 1",            amount="3600.00",  type="income",  day=15, cat=income_id),
    dict(name="Paycheck 2",            amount="3600.00",  type="income",  day=0,  cat=income_id),

    # ── Housing ───────────────────────────────────────────────────────────────
    # $2,185 includes P&I ($1,640 on $265k loan at 4.125% / 30yr, 2020 purchase)
    # + escrow for property tax ($370) + homeowner's insurance ($175)
    dict(name="Mortgage",              amount="2185.00",  type="expense", day=1,  cat=mortgage_id),
    dict(name="Savings Transfer",      amount="400.00",   type="expense", day=2,  cat=savings_id),

    # ── Transportation ────────────────────────────────────────────────────────
    # 2023 Honda CR-V: $32k financed at 6.9% / 60mo, 18 months in
    # 2020 Toyota Camry: $19k used, 5.4% / 60mo, 30 months in
    dict(name="Honda CR-V Payment",    amount="672.00",   type="expense", day=7,  cat=transport_id),
    dict(name="Toyota Camry Payment",  amount="445.00",   type="expense", day=20, cat=transport_id),
    dict(name="State Farm Auto",       amount="214.00",   type="expense", day=9,  cat=insurance_id),

    # ── Utilities ─────────────────────────────────────────────────────────────
    dict(name="Electric (Duke Energy)",amount="145.00",   type="expense", day=15, cat=utilities_id),
    dict(name="Natural Gas",           amount="78.00",    type="expense", day=22, cat=utilities_id),
    dict(name="Water & Sewer",         amount="84.00",    type="expense", day=19, cat=utilities_id),
    dict(name="Xfinity Internet",      amount="79.99",    type="expense", day=11, cat=utilities_id),
    dict(name="Verizon Family Plan",   amount="154.99",   type="expense", day=8,  cat=utilities_id),

    # ── Subscriptions ─────────────────────────────────────────────────────────
    dict(name="Netflix Standard",      amount="22.99",    type="expense", day=13, cat=subscriptions_id),
    dict(name="Disney+ / Hulu Bundle", amount="12.99",    type="expense", day=19, cat=subscriptions_id),
    dict(name="Spotify Family",        amount="17.99",    type="expense", day=6,  cat=subscriptions_id),
    dict(name="Amazon Prime",          amount="14.99",    type="expense", day=23, cat=subscriptions_id),

    # ── Giving ────────────────────────────────────────────────────────────────
    dict(name="Charitable Giving",     amount="125.00",   type="expense", day=5,  cat=charity_id),
]

ri_objects = []
for r in recurring_items:
    ri = models.RecurringItem(
        user_id=user.id,
        account_id=checking.id,
        category_id=r["cat"],
        name=r["name"],
        amount=Decimal(str(r["amount"])),
        type=r["type"],
        day_of_month=r["day"],
        start_date=date(2026, 1, 1),
    )
    db.add(ri)
    ri_objects.append(ri)

db.flush()   # ensure IDs are assigned before paycheck_ri lookup below
db.commit()
print(f"✓ Created {len(ri_objects)} recurring items")

# ─── 6. Past Actual Transactions — April & May 2026 ──────────────────────────

actuals = [
    # ── April 2026 ────────────────────────────────────────────────────────────
    (date(2026, 4, 1),  Decimal("-2185.00"), "Mortgage Payment",       checking.id, mortgage_id),
    (date(2026, 4, 2),  Decimal("-400.00"),  "Transfer to Savings",    checking.id, savings_id),
    (date(2026, 4, 5),  Decimal("-125.00"),  "Charitable Giving",      checking.id, charity_id),
    (date(2026, 4, 6),  Decimal("-17.99"),   "Spotify Family",         checking.id, subscriptions_id),
    (date(2026, 4, 7),  Decimal("-672.00"),  "Honda CR-V Payment",     checking.id, transport_id),
    (date(2026, 4, 8),  Decimal("-154.99"),  "Verizon Family Plan",    checking.id, utilities_id),
    (date(2026, 4, 9),  Decimal("-214.00"),  "State Farm Auto",        checking.id, insurance_id),
    (date(2026, 4, 11), Decimal("-79.99"),   "Xfinity Internet",       checking.id, utilities_id),
    (date(2026, 4, 13), Decimal("-22.99"),   "Netflix Standard",       checking.id, subscriptions_id),
    (date(2026, 4, 14), Decimal("-138.47"),  "Duke Energy Electric",   checking.id, utilities_id),
    (date(2026, 4, 15), Decimal("3600.00"),  "Paycheck 1",             checking.id, income_id),
    (date(2026, 4, 19), Decimal("-12.99"),   "Disney+ / Hulu Bundle",  checking.id, subscriptions_id),
    (date(2026, 4, 19), Decimal("-84.00"),   "Water & Sewer",          checking.id, utilities_id),
    (date(2026, 4, 20), Decimal("-445.00"),  "Toyota Camry Payment",   checking.id, transport_id),
    (date(2026, 4, 22), Decimal("-71.83"),   "Natural Gas",            checking.id, utilities_id),
    (date(2026, 4, 23), Decimal("-14.99"),   "Amazon Prime",           checking.id, subscriptions_id),
    (date(2026, 4, 30), Decimal("3600.00"),  "Paycheck 2",             checking.id, income_id),

    # ── May 2026 ──────────────────────────────────────────────────────────────
    (date(2026, 5, 1),  Decimal("-2185.00"), "Mortgage Payment",       checking.id, mortgage_id),
    (date(2026, 5, 2),  Decimal("-400.00"),  "Transfer to Savings",    checking.id, savings_id),
    (date(2026, 5, 5),  Decimal("-125.00"),  "Charitable Giving",      checking.id, charity_id),
    (date(2026, 5, 6),  Decimal("-17.99"),   "Spotify Family",         checking.id, subscriptions_id),
    (date(2026, 5, 7),  Decimal("-672.00"),  "Honda CR-V Payment",     checking.id, transport_id),
    (date(2026, 5, 8),  Decimal("-154.99"),  "Verizon Family Plan",    checking.id, utilities_id),
    (date(2026, 5, 9),  Decimal("-214.00"),  "State Farm Auto",        checking.id, insurance_id),
    (date(2026, 5, 11), Decimal("-79.99"),   "Xfinity Internet",       checking.id, utilities_id),
    (date(2026, 5, 13), Decimal("-22.99"),   "Netflix Standard",       checking.id, subscriptions_id),
    (date(2026, 5, 14), Decimal("-152.18"),  "Duke Energy Electric",   checking.id, utilities_id),
    (date(2026, 5, 15), Decimal("3600.00"),  "Paycheck 1",             checking.id, income_id),
    (date(2026, 5, 19), Decimal("-12.99"),   "Disney+ / Hulu Bundle",  checking.id, subscriptions_id),
    (date(2026, 5, 19), Decimal("-84.00"),   "Water & Sewer",          checking.id, utilities_id),
    (date(2026, 5, 20), Decimal("-445.00"),  "Toyota Camry Payment",   checking.id, transport_id),
    (date(2026, 5, 22), Decimal("-81.34"),   "Natural Gas",            checking.id, utilities_id),
    (date(2026, 5, 23), Decimal("-14.99"),   "Amazon Prime",           checking.id, subscriptions_id),
    (date(2026, 5, 31), Decimal("3600.00"),  "Paycheck 2",             checking.id, income_id),
]

# Map paycheck names to their recurring item objects for linking
paycheck_ri = {ri.name: ri for ri in ri_objects if ri.name.startswith("Paycheck")}

for dt, amount, desc, acc_id, cat_id in actuals:
    ri_id = paycheck_ri[desc].id if desc in paycheck_ri else None
    db.add(models.Transaction(
        user_id=user.id, account_id=acc_id, category_id=cat_id,
        date=dt, amount=amount, description=desc, is_actual=True, source="manual",
        recurring_item_id=ri_id,
    ))

db.commit()
print(f"✓ Created {len(actuals)} checking transactions (Apr–May 2026)")

# ─── 7. Credit Card Transactions ─────────────────────────────────────────────
# ~$2,200/month discretionary on Chase Sapphire (groceries, dining, gas, shopping)
# Apple Card: small Apple ecosystem charges

card_txns = [
    # ── Chase Sapphire — April ────────────────────────────────────────────────
    (chase.id, date(2026, 4, 3),  Decimal("187.43"),  "Kroger",                food_id),
    (chase.id, date(2026, 4, 5),  Decimal("67.82"),   "Chick-fil-A",           food_id),
    (chase.id, date(2026, 4, 8),  Decimal("91.40"),   "Shell Gas Station",     transport_id),
    (chase.id, date(2026, 4, 9),  Decimal("312.17"),  "Target",                shopping_id),
    (chase.id, date(2026, 4, 11), Decimal("54.19"),   "Panera Bread",          food_id),
    (chase.id, date(2026, 4, 14), Decimal("28.47"),   "McDonald's",            food_id),
    (chase.id, date(2026, 4, 16), Decimal("224.33"),  "Amazon",                shopping_id),
    (chase.id, date(2026, 4, 18), Decimal("163.55"),  "Kroger",                food_id),
    (chase.id, date(2026, 4, 19), Decimal("41.28"),   "Chipotle",              food_id),
    (chase.id, date(2026, 4, 21), Decimal("88.99"),   "BP Gas",                transport_id),
    (chase.id, date(2026, 4, 23), Decimal("193.40"),  "Costco",                food_id),
    (chase.id, date(2026, 4, 25), Decimal("34.99"),   "Regal Cinemas",         entertainment_id),
    (chase.id, date(2026, 4, 27), Decimal("78.55"),   "Old Navy",              shopping_id),
    (chase.id, date(2026, 4, 28), Decimal("114.72"),  "Kroger",                food_id),

    # ── Chase Sapphire — May ──────────────────────────────────────────────────
    (chase.id, date(2026, 5, 2),  Decimal("203.18"),  "Kroger",                food_id),
    (chase.id, date(2026, 5, 4),  Decimal("45.73"),   "Chick-fil-A",           food_id),
    (chase.id, date(2026, 5, 6),  Decimal("52.67"),   "Raising Cane's",        food_id),
    (chase.id, date(2026, 5, 7),  Decimal("92.99"),   "Shell Gas Station",     transport_id),
    (chase.id, date(2026, 5, 10), Decimal("178.44"),  "Target",                shopping_id),
    (chase.id, date(2026, 5, 12), Decimal("134.50"),  "Amazon",                shopping_id),
    (chase.id, date(2026, 5, 14), Decimal("61.27"),   "Olive Garden",          food_id),
    (chase.id, date(2026, 5, 17), Decimal("265.00"),  "Home Depot",            shopping_id),
    (chase.id, date(2026, 5, 18), Decimal("97.40"),   "BP Gas",                transport_id),
    (chase.id, date(2026, 5, 21), Decimal("189.33"),  "Costco",                food_id),
    (chase.id, date(2026, 5, 24), Decimal("47.89"),   "Chipotle",              food_id),
    (chase.id, date(2026, 5, 26), Decimal("112.40"),  "Kohl's",                shopping_id),
    (chase.id, date(2026, 5, 29), Decimal("33.50"),   "AMC Theaters",          entertainment_id),
    (chase.id, date(2026, 5, 31), Decimal("168.77"),  "Kroger",                food_id),

    # ── Apple Card — April & May ──────────────────────────────────────────────
    (apple.id, date(2026, 4, 6),  Decimal("12.99"),   "App Store",             entertainment_id),
    (apple.id, date(2026, 4, 15), Decimal("2.99"),    "iCloud+ 200GB",         subscriptions_id),
    (apple.id, date(2026, 4, 28), Decimal("9.99"),    "Apple TV+",             subscriptions_id),
    (apple.id, date(2026, 5, 3),  Decimal("8.49"),    "App Store",             entertainment_id),
    (apple.id, date(2026, 5, 15), Decimal("2.99"),    "iCloud+ 200GB",         subscriptions_id),
    (apple.id, date(2026, 5, 22), Decimal("29.99"),   "Apple Arcade Annual",   subscriptions_id),
]

for card_id, dt, amount, merchant, cat_id in card_txns:
    db.add(models.CreditCardTransaction(
        card_id=card_id, user_id=user.id, category_id=cat_id,
        date=dt, amount=amount, merchant=merchant, source="manual",
    ))

db.commit()
print(f"✓ Created {len(card_txns)} credit card transactions (Apr–May 2026)")

# ─── 8. Budget Allocations ────────────────────────────────────────────────────
# month=0 applies to all months; reflects committed + typical discretionary spend

budget_allocs = [
    (mortgage_id,      2_300),   # ~5% cushion over actual
    (transport_id,     1_400),   # car payments + gas (~$350/mo on card)
    (insurance_id,       250),
    (utilities_id,       600),   # all utility lines combined
    (food_id,          1_200),   # groceries + dining
    (shopping_id,        700),
    (entertainment_id,   150),
    (subscriptions_id,    90),
    (savings_id,         400),
    (charity_id,         125),
    (other_id,           200),
]

for cat_id, amount in budget_allocs:
    if cat_id is None:
        continue
    db.add(models.BudgetAllocation(
        user_id=user.id, category_id=cat_id,
        year=2026, month=0,
        budgeted_amount=Decimal(str(amount)),
    ))

db.commit()
print(f"✓ Created {len(budget_allocs)} budget allocations")

# ─── Done ─────────────────────────────────────────────────────────────────────

# Monthly snapshot summary
total_income  = Decimal("7200.00")
total_fixed   = sum(Decimal(str(r["amount"])) for r in recurring_items if r["type"] == "expense")
discretionary = total_income - total_fixed

print()
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  Demo data loaded — dual-income family of four")
print()
print("  Login:  username=demo  password=demo123")
print()
print("  Monthly budget summary:")
print(f"    Net income:          ${total_income:>8,.2f}")
print(f"    Committed expenses:  ${total_fixed:>8,.2f}")
print(f"    Discretionary:       ${discretionary:>8,.2f}  (groceries, dining, gas, etc.)")
print()
print("  Accounts:")
print("    Main Checking        $4,847.33")
print("    High-Yield Savings   $11,200.00")
print()
print("  Credit cards:")
print("    Chase Sapphire Preferred   $1,423.87 balance")
print("    Apple Card                   $143.22 balance")
print()
print("  Seeded: 17 recurring items, 33 checking txns,")
print("          35 card txns, 11 budget allocations")
print()
print("  Try: Forecast → select Main Checking → view year")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

db.close()
