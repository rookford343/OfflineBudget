#!/usr/bin/env python3
"""
Loads demo data for a sample household budget.
Run from project root:
    source .venv/bin/activate
    python scripts/seed_demo.py

Creates:
  • User: demo / demo123
  • Main Checking + Money Market accounts
  • Chase Sapphire + Apple Card credit cards
  • Recurring income (two paychecks + annual bonus)
  • Recurring bills (utilities, insurance, mortgage, subscriptions)
  • 2 months of past transactions (April, May 2026 actuals)
  • Budget allocations matching actual spending patterns
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal
from datetime import date
from OfflineBudget.backend.database import SessionLocal, create_tables
from OfflineBudget.backend.auth import hash_password
from OfflineBudget.backend import models
from OfflineBudget.backend.seed import seed_default_categories

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

checking = models.Account(
    user_id=user.id,
    name="Main Checking (Chase)",
    type="checking",
    current_balance=Decimal("9_148.78"),
    currency="USD",
    notes="Primary household checking account",
)
db.add(checking)

money_market = models.Account(
    user_id=user.id,
    name="Money Market (High-Yield)",
    type="money_market",
    current_balance=Decimal("12_000.00"),
    currency="USD",
    notes="4.16% APY — quarterly savings transfers",
)
db.add(money_market)
db.commit()
db.refresh(checking)
db.refresh(money_market)
print(f"✓ Created accounts: checking (id={checking.id}), money_market (id={money_market.id})")

# ─── 3. Credit Cards ──────────────────────────────────────────────────────────

chase_sapphire = models.CreditCard(
    user_id=user.id,
    name="Chase Sapphire",
    last_four="4521",
    credit_limit=Decimal("20_000"),
    statement_day=26,
    due_day=23,
    current_balance=Decimal("1_847.33"),
    balance_due=Decimal("2_986.89"),
    notes="Primary rewards card",
)
db.add(chase_sapphire)

apple_card = models.CreditCard(
    user_id=user.id,
    name="Apple Card",
    last_four="8834",
    credit_limit=Decimal("5_000"),
    statement_day=1,
    due_day=28,
    current_balance=Decimal("66.24"),
    balance_due=Decimal("66.24"),
    notes="Apple Pay daily use",
)
db.add(apple_card)
db.commit()
db.refresh(chase_sapphire)
db.refresh(apple_card)
print(f"✓ Created credit cards: Chase Sapphire (id={chase_sapphire.id}), Apple Card (id={apple_card.id})")

# ─── 4. Categories (look up seeded ones) ──────────────────────────────────────

def cat(name: str) -> int | None:
    c = db.query(models.Category).filter(
        models.Category.user_id == user.id,
        models.Category.name == name,
    ).first()
    return c.id if c else None

income_id = cat("Salary / Wages")
bonus_id = cat("Bonus")
necessities_id = cat("Necessities")
utilities_id = cat("Utilities")
insurance_id = cat("Insurance")
transport_id = cat("Transportation")
mortgage_id = cat("Mortgage / Rent")
food_id = cat("Food & Drinks")
shopping_id = cat("Shopping")
entertainment_id = cat("Entertainment")
subscriptions_id = cat("Subscriptions")
savings_id = cat("Savings")
emergency_id = cat("Emergency Fund")
charity_id = cat("Church / Tithe")
other_id = cat("Other")

# ─── 5. Recurring Items ───────────────────────────────────────────────────────

recurring_items = [
    # Income
    dict(name="Paycheck 1",         amount="6066.63", type="income",  day=15, cat=income_id),
    dict(name="Paycheck 2",         amount="6066.63", type="income",  day=0,  cat=income_id),
    dict(name="Annual Bonus /12",   amount="1599.04", type="income",  day=15, cat=bonus_id),
    # Necessities
    dict(name="Auto Insurance",     amount="194.00",  type="expense", day=2,  cat=insurance_id),
    dict(name="Electric Utility",   amount="180.00",  type="expense", day=8,  cat=utilities_id),
    dict(name="HOA Fees",           amount="125.00",  type="expense", day=1,  cat=necessities_id),
    dict(name="Car Payment",        amount="500.89",  type="expense", day=17, cat=transport_id),
    dict(name="Home Internet",      amount="79.99",   type="expense", day=12, cat=utilities_id),
    dict(name="Natural Gas",        amount="45.00",   type="expense", day=20, cat=utilities_id),
    dict(name="Stormwater",         amount="22.00",   type="expense", day=15, cat=utilities_id),
    dict(name="Mortgage",           amount="2_412.00", type="expense", day=1, cat=mortgage_id),
    # Savings
    dict(name="Savings Transfer",   amount="1_000.00", type="expense", day=1, cat=savings_id),
    # Charity
    dict(name="Charitable Giving",  amount="1_000.00", type="expense", day=5, cat=charity_id),
    # Subscriptions
    dict(name="Netflix",            amount="22.99",   type="expense", day=18, cat=subscriptions_id),
    dict(name="Spotify",            amount="16.99",   type="expense", day=22, cat=subscriptions_id),
    dict(name="iCloud Storage",     amount="2.99",    type="expense", day=15, cat=subscriptions_id),
]

ri_objects = []
for r in recurring_items:
    ri = models.RecurringItem(
        user_id=user.id,
        account_id=checking.id,
        category_id=r["cat"],
        name=r["name"],
        amount=Decimal(str(r["amount"]).replace(",", "").replace("_", "")),
        type=r["type"],
        day_of_month=r["day"],
        start_date=date(2026, 1, 1),
    )
    db.add(ri)
    ri_objects.append(ri)

db.commit()
print(f"✓ Created {len(ri_objects)} recurring items")

# ─── 6. Past Actual Transactions (Q2 2026 — Apr, May) ─────────────────────────

actuals = [
    # April 2026
    (date(2026, 4, 1),  Decimal("-125.00"),  "HOA Fees",             checking.id, necessities_id),
    (date(2026, 4, 1),  Decimal("-2412.00"), "Mortgage Payment",     checking.id, mortgage_id),
    (date(2026, 4, 2),  Decimal("-194.00"),  "Auto Insurance",       checking.id, insurance_id),
    (date(2026, 4, 5),  Decimal("-1000.00"), "Charitable Giving",    checking.id, charity_id),
    (date(2026, 4, 8),  Decimal("-163.42"),  "Electric Utility",     checking.id, utilities_id),
    (date(2026, 4, 12), Decimal("-79.99"),   "Xfinity Internet",     checking.id, utilities_id),
    (date(2026, 4, 15), Decimal("6066.63"),  "Paycheck 1",           checking.id, income_id),
    (date(2026, 4, 15), Decimal("-22.00"),   "Stormwater Fee",       checking.id, utilities_id),
    (date(2026, 4, 17), Decimal("-500.89"),  "Car Payment",          checking.id, transport_id),
    (date(2026, 4, 18), Decimal("-22.99"),   "Netflix",              checking.id, subscriptions_id),
    (date(2026, 4, 20), Decimal("-38.17"),   "Natural Gas",          checking.id, utilities_id),
    (date(2026, 4, 22), Decimal("-16.99"),   "Spotify",              checking.id, subscriptions_id),
    (date(2026, 4, 30), Decimal("6066.63"),  "Paycheck 2",           checking.id, income_id),

    # May 2026
    (date(2026, 5, 1),  Decimal("-125.00"),  "HOA Fees",             checking.id, necessities_id),
    (date(2026, 5, 1),  Decimal("-2412.00"), "Mortgage Payment",     checking.id, mortgage_id),
    (date(2026, 5, 2),  Decimal("-194.00"),  "Auto Insurance",       checking.id, insurance_id),
    (date(2026, 5, 5),  Decimal("-1000.00"), "Charitable Giving",    checking.id, charity_id),
    (date(2026, 5, 8),  Decimal("-198.55"),  "Electric Utility",     checking.id, utilities_id),
    (date(2026, 5, 15), Decimal("6066.63"),  "Paycheck 1",           checking.id, income_id),
    (date(2026, 5, 15), Decimal("-1000.00"), "Transfer to Savings",  checking.id, savings_id),
    (date(2026, 5, 17), Decimal("-500.89"),  "Car Payment",          checking.id, transport_id),
    (date(2026, 5, 31), Decimal("6066.63"),  "Paycheck 2",           checking.id, income_id),
]

for dt, amount, desc, acc_id, cat_id in actuals:
    txn = models.Transaction(
        user_id=user.id,
        account_id=acc_id,
        category_id=cat_id,
        date=dt,
        amount=amount,
        description=desc,
        is_actual=True,
        source="manual",
    )
    db.add(txn)

db.commit()
print(f"✓ Created {len(actuals)} past actual transactions")

# ─── 7. Credit Card Transactions ─────────────────────────────────────────────

card_txns = [
    # Chase Sapphire — April
    (chase_sapphire.id, date(2026, 4, 3),  Decimal("87.43"),  "Whole Foods Market",  food_id),
    (chase_sapphire.id, date(2026, 4, 5),  Decimal("234.17"), "Amazon",              shopping_id),
    (chase_sapphire.id, date(2026, 4, 7),  Decimal("63.28"),  "Chipotle",            food_id),
    (chase_sapphire.id, date(2026, 4, 9),  Decimal("145.00"), "Target",              shopping_id),
    (chase_sapphire.id, date(2026, 4, 11), Decimal("42.16"),  "Panera Bread",        food_id),
    (chase_sapphire.id, date(2026, 4, 14), Decimal("312.88"), "Home Depot",          shopping_id),
    (chase_sapphire.id, date(2026, 4, 16), Decimal("89.99"),  "Costco Gas",          transport_id),
    (chase_sapphire.id, date(2026, 4, 19), Decimal("55.40"),  "Chick-fil-A",         food_id),
    (chase_sapphire.id, date(2026, 4, 22), Decimal("178.33"), "Sam's Club",          shopping_id),
    (chase_sapphire.id, date(2026, 4, 25), Decimal("47.82"),  "Starbucks x4",        food_id),
    # Chase Sapphire — May
    (chase_sapphire.id, date(2026, 5, 2),  Decimal("93.17"),  "Whole Foods Market",  food_id),
    (chase_sapphire.id, date(2026, 5, 6),  Decimal("189.45"), "Amazon",              shopping_id),
    (chase_sapphire.id, date(2026, 5, 10), Decimal("76.55"),  "Longhorn Steakhouse", food_id),
    (chase_sapphire.id, date(2026, 5, 14), Decimal("412.00"), "Best Buy",            shopping_id),
    (chase_sapphire.id, date(2026, 5, 20), Decimal("34.99"),  "iTunes / App Store",  entertainment_id),
    (chase_sapphire.id, date(2026, 5, 25), Decimal("267.18"), "Nordstrom",           shopping_id),
    # Apple Card — April & May
    (apple_card.id,     date(2026, 4, 8),  Decimal("12.99"),  "App Store",           entertainment_id),
    (apple_card.id,     date(2026, 4, 15), Decimal("2.99"),   "iCloud+ 200GB",       subscriptions_id),
    (apple_card.id,     date(2026, 4, 23), Decimal("29.99"),  "Apple TV+",           subscriptions_id),
    (apple_card.id,     date(2026, 5, 15), Decimal("2.99"),   "iCloud+ 200GB",       subscriptions_id),
    (apple_card.id,     date(2026, 5, 18), Decimal("20.28"),  "App Purchases",       entertainment_id),
]

for card_id, dt, amount, merchant, cat_id in card_txns:
    ct = models.CreditCardTransaction(
        card_id=card_id,
        user_id=user.id,
        category_id=cat_id,
        date=dt,
        amount=amount,
        merchant=merchant,
        source="manual",
    )
    db.add(ct)

db.commit()
print(f"✓ Created {len(card_txns)} credit card transactions")

# ─── 8. Budget Allocations ────────────────────────────────────────────────────

budget_allocs = [
    (necessities_id,   3_500),
    (utilities_id,       500),
    (insurance_id,       200),
    (transport_id,       600),
    (mortgage_id,      2_500),
    (food_id,          1_500),
    (shopping_id,      1_500),
    (entertainment_id,   200),
    (subscriptions_id,   100),
    (savings_id,       1_000),
    (charity_id,       1_000),
    (other_id,           300),
]

for cat_id, amount in budget_allocs:
    if cat_id is None:
        continue
    alloc = models.BudgetAllocation(
        user_id=user.id,
        category_id=cat_id,
        year=2026,
        month=0,  # applies to all months
        budgeted_amount=Decimal(str(amount)),
    )
    db.add(alloc)

db.commit()
print(f"✓ Created {len(budget_allocs)} budget allocations")

# ─── Done ─────────────────────────────────────────────────────────────────────

print()
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  Demo data loaded successfully!")
print()
print("  Login: username=demo  password=demo123")
print()
print("  What's loaded:")
print("  • 2 accounts: Main Checking ($9,148.78), Money Market ($12,000)")
print("  • 2 credit cards: Chase Sapphire, Apple Card")
print("  • 16 recurring items (paychecks, bills, charitable giving)")
print("  • 22 actual transactions (Apr–May 2026)")
print("  • 21 credit card transactions (Apr–May 2026)")
print("  • 12 budget allocations")
print()
print("  Try: python cli/budget.py forecast quarters --username demo \\")
print("       --account 'Main Checking'")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

db.close()
