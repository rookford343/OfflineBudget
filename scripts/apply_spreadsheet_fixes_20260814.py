#!/usr/bin/env python3
"""
Data half of the 2026-08-14 reconciliation against Budget.xlsx.

Companion to reconcile_to_spreadsheet.py, which covered the recurring amounts,
annual expenses, and category budgets. This one fixes the five items that the
Q3 forecast comparison turned up -- each is a frequency, date, or routing
problem rather than an amount, so they could not be expressed as a
RECURRING_FIXES entry.

Same rule as before: Budget.xlsx is the maintained plan and the forecast is
judged against it, so where the two disagree the sheet wins. The two
exceptions are called out in NOTES at the bottom -- places where the sheet is
the thing that needs updating.

Idempotent. Run from project root:
    source .venv/bin/activate
    python scripts/apply_spreadsheet_fixes_20260814.py [--apply]
"""
import sys, os, argparse, shutil
from datetime import date, datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend import models

USER_ID = 2
APPLE_CARD_ID = 4

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "budget.db")


def _log(changed: bool, msg: str):
    print(("  CHANGE  " if changed else "  ok      ") + msg)


def _get(db, name: str) -> "models.RecurringItem | None":
    item = db.query(models.RecurringItem).filter_by(user_id=USER_ID, name=name).first()
    if not item:
        print(f"  MISSING  {name} -- no such recurring item")
    return item


def fix_stormwater(db, apply: bool):
    """Budget!B15 carries Stormwater at $4.94 with C15 marked "Qtr", and the
    forecast charges the full $14.82 on 9/30 and 12/31. The app had it as a
    $4.94 monthly charge -- right over a quarter, wrong on any given day, and
    it put a charge on checking in eight months that should have none."""
    print("\nStormwater -> quarterly (Budget!B15, C15 = 'Qtr'):")
    item = _get(db, "Stormwater")
    if not item:
        return
    target = (Decimal("14.82"), models.RecurringFrequency.quarterly, 3, 0)
    current = (item.amount, item.frequency, item.month_of_year, item.day_of_month)
    if current == target:
        _log(False, "already $14.82 quarterly, last day of Mar/Jun/Sep/Dec")
        return
    if apply:
        item.amount, item.frequency, item.month_of_year, item.day_of_month = target
    _log(True, f"{current} -> $14.82 quarterly, month_of_year=3, last day of month")


def fix_hoa(db, apply: bool):
    """Budget!C16 marks HOA Fees "Yearly" and the 2026 Forecast never charges
    it, yet the app hit checking for $58.33 every month. Dan confirmed
    2026-08-14: it is a single $600 charge in January. The monthly figure was
    the accrual, which the yearly frequency now reproduces on its own."""
    print("\nHOA Fees -> $600 yearly in January (Budget!C16, Dan 2026-08-14):")
    item = _get(db, "HOA Fees")
    if not item:
        return
    target = (Decimal("600.00"), models.RecurringFrequency.yearly, 1, 1)
    current = (item.amount, item.frequency, item.month_of_year, item.day_of_month)
    if current == target:
        _log(False, "already $600 yearly on January 1")
        return
    if apply:
        item.amount, item.frequency, item.month_of_year, item.day_of_month = target
    _log(True, f"{current} -> $600 yearly, January 1")


def fix_house_cleaning(db, apply: bool):
    """Budget!B18 says $150 but every "Vicky house clean" row in the 2026
    Forecast charges $200. Dan resolved it 2026-08-14 in favour of the
    forecast rows; Budget!B18 is the stale cell."""
    print("\nHouse Cleaning -> $200 ('2026 Forecast' rows, Dan 2026-08-14):")
    item = _get(db, "House Cleaning")
    if not item:
        return
    if item.amount == Decimal("200.00"):
        _log(False, "already $200")
        return
    was = item.amount
    if apply:
        item.amount = Decimal("200.00")
    _log(True, f"${was} -> $200.00")


def fix_r2_start(db, apply: bool):
    """The R2 loan payment started 2026-09-15 in the app, so it first fired
    9/17. The sheet's first $500 R2 row is 10/17 ('2026 Forecast'!P9); its
    9/17 row is present but zero. Moving the start to 10/01 lands the first
    payment on 10/17 without touching day_of_month."""
    print("\nRivian R2 first payment -> 2026-10-17 ('2026 Forecast'!K33 is $0, P9 is $500):")
    item = _get(db, "Rivian R2")
    if not item:
        return
    if item.start_date == date(2026, 10, 1):
        _log(False, "already starts 2026-10-01 (first fires 10/17)")
        return
    was = item.start_date
    if apply:
        item.start_date = date(2026, 10, 1)
    _log(True, f"start_date {was} -> 2026-10-01 (first fires 10/17)")


def move_apple_to_apple_card(db, apply: bool):
    """Every card-linked recurring item pointed at Chase Sapphire, so the
    Apple Card had no subscriptions and its derived spend estimate came out
    $0. Dan confirmed 2026-08-14 that the Apple line belongs on the Apple
    Card; the rest he will reassign in the UI as he goes."""
    print("\nApple ($57.39) -> Apple Card (Dan 2026-08-14):")
    card = db.query(models.CreditCard).filter_by(user_id=USER_ID, id=APPLE_CARD_ID).first()
    if not card:
        print(f"  MISSING  no credit card id={APPLE_CARD_ID}")
        return
    item = _get(db, "Apple")
    if not item:
        return
    if item.card_id == APPLE_CARD_ID:
        _log(False, f"already on {card.name}")
        return
    was = item.card_id
    if apply:
        item.card_id = APPLE_CARD_ID
    _log(True, f"card_id {was} -> {APPLE_CARD_ID} ({card.name})")


def notes():
    print("""
NOTES -- these are the sheet's turn to change, not the app's:

  Skin Twins        $160/mo on day 20 is a live recurring card charge in the
                    app but appears nowhere in Budget!A22:B40. It is the whole
                    of the $160 gap between the app's remaining card bills
                    ($913.59) and the sheet's ($753.59), and it is also why
                    app Leftover reads $3,148.51 against the sheet's
                    $3,275.59. Add it to the Credit Card Bills list.

  '2026 Overview'   B25 is =min('2026 Forecast'!L24:L40). Row 24 is 8/31, so
  !B25              the range skips the real Q3 trough at L23 -- $676.12 on
                    8/25. C25 beside it uses the full column and does report
                    8/25, so the sheet is printing an amount and a date from
                    two different rows. Widen B25 to L3:L40. Q1's B23
                    (=min(B16:B56)) has the same shape and wants the same fix.

  METRONET          Sheet still says $49.99; actuals ran $75.09/mo Apr-Jun and
                    $85.39 in Jul. Carried over from the last reconciliation,
                    still unresolved.
""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="commit changes (default: dry run)")
    args = ap.parse_args()

    if args.apply and os.path.exists(DB_PATH):
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = os.path.join(os.path.dirname(DB_PATH), "backups", f"budget_{stamp}_pre-spreadsheet-fixes.db")
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copy2(DB_PATH, backup)
        print(f"Backed up to {backup}")

    db = SessionLocal()
    fix_stormwater(db, args.apply)
    fix_hoa(db, args.apply)
    fix_house_cleaning(db, args.apply)
    fix_r2_start(db, args.apply)
    move_apple_to_apple_card(db, args.apply)

    if args.apply:
        db.commit()
        print("\nCommitted.")
    else:
        db.rollback()
        print("\nDry run -- nothing written. Re-run with --apply to commit.")
    notes()


if __name__ == "__main__":
    main()
