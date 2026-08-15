#!/usr/bin/env python3
"""
Sets Dan's Social Security wage-base checkpoint from a real pay stub, and
retires the flat-rate reconstruction that had been misdating the 2026
crossing (see forecast_engine.py's checkpoint comment).

YTD SS tax withheld through the 8/14/2026 paycheck: $11,343.06 (Dan, pay
stub). Implies gross wages subject to SS of $11,343.06 / 0.062 = $182,952.58,
still $1,547.42 under the $184,500 wage base -- the crossing has not
happened yet and lands on the 8/31 paycheck, not 8/14.

Idempotent. Run from project root:
    source .venv/bin/activate
    python scripts/set_ss_checkpoint_20260814.py [--apply]
"""
import sys, os, argparse, shutil
from datetime import date, datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend import models

USER_ID = 2
WITHHELD_YTD = Decimal("11343.06")
AS_OF = date(2026, 8, 14)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "budget.db")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="commit changes (default: dry run)")
    args = ap.parse_args()

    if args.apply and os.path.exists(DB_PATH):
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = os.path.join(os.path.dirname(DB_PATH), "backups", f"budget_{stamp}_pre-ss-checkpoint.db")
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copy2(DB_PATH, backup)
        print(f"Backed up to {backup}")

    db = SessionLocal()
    user = db.query(models.User).filter_by(id=USER_ID).first()
    if not user:
        print(f"MISSING  no user id={USER_ID}")
        return

    current = (user.ss_withheld_ytd, user.ss_withheld_ytd_as_of)
    target = (WITHHELD_YTD, AS_OF)
    if current == target:
        print(f"  ok      already ${WITHHELD_YTD} as of {AS_OF}")
    else:
        print(f"  CHANGE  ss_withheld_ytd/as_of {current} -> {target}")
        if args.apply:
            user.ss_withheld_ytd = WITHHELD_YTD
            user.ss_withheld_ytd_as_of = AS_OF

    if args.apply:
        db.commit()
        print("Committed.")
    else:
        db.rollback()
        print("Dry run -- nothing written. Re-run with --apply to commit.")

    gross_equiv = (WITHHELD_YTD / Decimal("0.062")).quantize(Decimal("0.01"))
    print(f"\nImplied gross YTD through {AS_OF}: ${gross_equiv}")
    if user.ss_wage_base:
        room = user.ss_wage_base - gross_equiv
        print(f"Room left under the ${user.ss_wage_base} base: ${room}")


if __name__ == "__main__":
    main()
