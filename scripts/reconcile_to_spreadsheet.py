#!/usr/bin/env python3
"""
Reconcile recurring items, category budgets, and the modeled one-off events to
Budget.xlsx. Idempotent -- safe to re-run after the spreadsheet changes.

Budget.xlsx is the maintained plan and the thing the forecast is judged
against, so where the app and the sheet disagree on a recurring amount, the
sheet wins (Dan's call, 2026-08-12). Where imported actuals disagree with the
sheet materially, this script prints a NOTE rather than silently overriding --
those are cases for Dan to update the sheet.

Run from project root:
    source .venv/bin/activate
    python scripts/reconcile_to_spreadsheet.py [--apply]
"""
import sys, os, argparse
from decimal import Decimal
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend import models

USER_ID = 2
CHECKING_ID = 3
CARD_ID = 3

# name -> (amount, day_of_month) from Budget.xlsx. None leaves the field alone.
RECURRING_FIXES = {
    "Chevy Insurance":         (Decimal("194.00"), None),   # Budget!B10
    "Verizon - Phones":        (Decimal("136.74"), None),   # Budget!B13
    "METRONET (Internet)":     (Decimal("49.99"),  None),   # Budget!B24
    "GREENIX":                 (Decimal("84.00"),  None),   # Budget!B28
    "PET WELLNESS CLINIC":     (Decimal("99.90"),  None),   # Budget!B33 (=49.95*2)
    "MONON LAWN & LANDSCAPE":  (Decimal("295.00"), 30),     # Budget!B41; day_of_month was 0 (= last day)
    "Citizens Energy":         (None,              17),     # Budget!C31
}

# Budget!E24:G32 -- annual expenses, absent from the app entirely (zero yearly
# recurring items existed). Deliberately NOT part of Budget!F1/F2, so these
# show up in the forecast without moving Leftover -- same as the sheet.
#
# start_date is TODAY, not 2026-01-01. Jan-Jul 2026 already holds real
# imported history, and a yearly item has no linked actual to suppress it, so
# backdating injects a projected charge on top of the actual one: seeding at
# 2026-01-01 dropped the Q2 minimum by exactly $2,800 (the May vehicle
# insurance, already paid) and turned it negative. Items whose month has
# passed in 2026 therefore first fire in 2027; Oct/Nov ones still fire this
# year, which is what we want.
ANNUAL_START = date.today()

# (month, day, amount, name, on_card)
ANNUAL_EXPENSES = [
    (1,  15, Decimal("44.99"),   "Fitbod (annual)",              True),
    (1,  15, Decimal("119.99"),  "Runna (annual)",               True),
    (4,  17, Decimal("735.35"),  "Vehicle Registration",         False),  # '2026 Forecast'!F11
    (4,  15, Decimal("65.00"),   "Bitdefender for Mac (annual)", True),
    (5,  15, Decimal("2800.00"), "Vehicle Insurance (annual)",   False),
    (7,  15, Decimal("99.00"),   "Apple TV+ (annual)",           True),
    (7,  15, Decimal("300.00"),  "Ellie Doctor (annual)",        False),
    (10, 15, Decimal("149.00"),  "Rivian Connect+ (annual)",     True),
    (11, 15, Decimal("119.99"),  "Natural Cycles (annual)",      True),
]

# '2026 Overview'!F3:F8 -- the discretionary budget grid, absent from
# budget_allocations. "Services" has no matching category; it maps to
# Subscriptions. Groceries (700) and the rest already exist.
CATEGORY_BUDGETS = {
    "Shopping":      Decimal("1500.00"),
    "Food & Drinks": Decimal("1500.00"),
    "Subscriptions": Decimal("800.00"),   # sheet calls this "Services"
    "Entertainment": Decimal("250.00"),
    "Other":         Decimal("750.00"),
}


def _log(changed: bool, msg: str):
    print(("  CHANGE  " if changed else "  ok      ") + msg)


def fix_recurring(db, apply: bool):
    print("\nRecurring items (Budget.xlsx wins):")
    for name, (amount, day) in RECURRING_FIXES.items():
        item = db.query(models.RecurringItem).filter_by(user_id=USER_ID, name=name).first()
        if not item:
            print(f"  MISSING  {name} -- no such recurring item")
            continue
        bits = []
        if amount is not None and item.amount != amount:
            bits.append(f"amount {item.amount} -> {amount}")
            if apply:
                item.amount = amount
        if day is not None and item.day_of_month != day:
            bits.append(f"day {item.day_of_month} -> {day}")
            if apply:
                item.day_of_month = day
        _log(bool(bits), f"{name}: " + (", ".join(bits) if bits else "already matches"))


def add_annual_expenses(db, apply: bool):
    print("\nAnnual expenses (Budget!E24:G32) as yearly recurring items:")
    for month, day, amount, name, on_card in ANNUAL_EXPENSES:
        existing = db.query(models.RecurringItem).filter_by(user_id=USER_ID, name=name).first()
        if existing:
            _log(False, f"{name}: already present")
            continue
        if apply:
            db.add(models.RecurringItem(
                user_id=USER_ID, account_id=CHECKING_ID,
                card_id=CARD_ID if on_card else None,
                name=name, amount=amount,
                type=models.RecurringType.expense,
                frequency=models.RecurringFrequency.yearly,
                day_of_month=day, month_of_year=month,
                start_date=ANNUAL_START,
                notes="From Budget.xlsx annual expense list",
            ))
        _log(True, f"{name}: create yearly ${amount} on {month:02d}/{day:02d}"
                   f" ({'card' if on_card else 'checking'}), from {ANNUAL_START}")


def add_category_budgets(db, apply: bool):
    print("\nCategory budgets ('2026 Overview'!F3:F8):")
    for cat_name, amount in CATEGORY_BUDGETS.items():
        cat = db.query(models.Category).filter_by(user_id=USER_ID, name=cat_name).first()
        if not cat:
            print(f"  MISSING  category {cat_name}")
            continue
        row = db.query(models.BudgetAllocation).filter_by(
            user_id=USER_ID, category_id=cat.id, year=2026, month=0,
        ).first()
        if row and row.budgeted_amount == amount:
            _log(False, f"{cat_name}: already ${amount}")
            continue
        if apply:
            if row:
                row.budgeted_amount = amount
            else:
                db.add(models.BudgetAllocation(
                    user_id=USER_ID, category_id=cat.id, year=2026, month=0,
                    budgeted_amount=amount,
                ))
        _log(True, f"{cat_name}: {'update to' if row else 'create'} ${amount}")


def add_r2_event(db, apply: bool):
    """'2026 Forecast'!K31:K34 -- the R2 purchase, the largest unmodeled event
    and only a month out: pull $22k from savings on 9/15, spend $21k the same
    day. The $500/mo R2 loan item already exists with start_date 2026-09-15."""
    print("\nSeptember R2 event ('2026 Forecast'!K31:K34):")
    savings = db.query(models.Account).filter_by(user_id=USER_ID, type=models.AccountType.savings).first()
    if not savings:
        print("  MISSING  no savings account to transfer from")
    else:
        existing = db.query(models.PlannedTransfer).filter_by(
            user_id=USER_ID, to_account_id=CHECKING_ID, target_date=date(2026, 9, 15),
        ).first()
        if existing:
            _log(False, "transfer: $22,000 savings -> checking on 2026-09-15 already present")
        else:
            if apply:
                db.add(models.PlannedTransfer(
                    user_id=USER_ID, from_account_id=savings.id, to_account_id=CHECKING_ID,
                    amount=Decimal("22000.00"), target_date=date(2026, 9, 15),
                    status=models.PlannedTransferStatus.scheduled, suggested=False,
                    notes="R2 down payment -- Budget.xlsx '2026 Forecast'!K31",
                ))
            _log(True, "transfer: create $22,000 savings -> checking on 2026-09-15")

    existing = db.query(models.PlannedExpense).filter_by(
        user_id=USER_ID, expected_date=date(2026, 9, 15),
    ).first()
    if existing:
        _log(False, "expense: R2 purchase on 2026-09-15 already present")
    else:
        if apply:
            db.add(models.PlannedExpense(
                user_id=USER_ID, account_id=CHECKING_ID, name="Rivian R2 purchase",
                amount=Decimal("21000.00"), expected_date=date(2026, 9, 15),
                notes="Budget.xlsx '2026 Forecast'!K32",
            ))
        _log(True, "expense: create $21,000 Rivian R2 purchase on 2026-09-15")


# One-off INflows the spreadsheet forecast carries as explicit rows but the app
# had no way to represent until PlannedExpense.direction existed. Historical
# 2026 ones are included so past-quarter accuracy reconciles; they sit on dates
# that already have actuals, so the forecast's own actuals take precedence for
# balance purposes -- their value is in making 2027 projections and the
# quarter-over-quarter comparison honest.
# (date, amount, name)
ONE_OFF_INFLOWS = [
    (date(2026, 4, 15), Decimal("38347.92"), "Annual bonus (after tax)"),   # '2026 Forecast'!F7
    (date(2026, 7, 21), Decimal("1300.00"),  "Airbnb payment from Mom"),    # '2026 Forecast'!K10
]


def add_one_off_inflows(db, apply: bool):
    print("\nOne-off inflows (needs PlannedExpense.direction):")
    for when, amount, name in ONE_OFF_INFLOWS:
        existing = db.query(models.PlannedExpense).filter_by(user_id=USER_ID, name=name).first()
        if existing:
            _log(False, f"{name}: already present")
            continue
        if apply:
            db.add(models.PlannedExpense(
                user_id=USER_ID, account_id=CHECKING_ID, name=name,
                amount=amount, expected_date=when,
                direction=models.PlannedDirection.inflow,
                notes="From Budget.xlsx '2026 Forecast'",
            ))
        _log(True, f"{name}: create +${amount} on {when}")


def notes():
    print("""
NOTES for Dan -- imported actuals disagree with Budget.xlsx. The sheet value
was applied as decided; these are the ones worth a look:

  METRONET (Internet)   sheet $49.99   actual $75.09/mo Apr-Jun, $85.39 in Jul
                        The sheet looks stale by ~$25-35/mo.
  GREENIX               sheet $84.00   actual $92.14 + $40 = $132.14/mo
                        Two separate charges each month; sheet looks stale.
  MONON LAWN            sheet $295.00  actual ~$250/mo (60 + 130 + 60)
  PET WELLNESS CLINIC   sheet $99.90   actual $54.95 x2 = $109.90/mo
  Citizens Energy       sheet $200.00  actual $112-$237, highly seasonal
  House Cleaning        sheet Budget!B18 = $150, but every '2026 Forecast' row
                        charges $200 ("Vicky house clean"). No matching
                        imported transaction exists to break the tie, so this
                        was LEFT AT $150 -- please confirm which is right.
""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="commit changes (default: dry run)")
    args = ap.parse_args()

    db = SessionLocal()
    fix_recurring(db, args.apply)
    add_annual_expenses(db, args.apply)
    add_category_budgets(db, args.apply)
    add_r2_event(db, args.apply)
    add_one_off_inflows(db, args.apply)

    if args.apply:
        db.commit()
        print("\nCommitted.")
    else:
        db.rollback()
        print("\nDry run -- nothing written. Re-run with --apply to commit.")
    notes()


if __name__ == "__main__":
    main()
