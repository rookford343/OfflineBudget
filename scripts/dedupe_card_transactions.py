#!/usr/bin/env python3
"""
One-off cleanup for card transactions double-imported before the dedupe
matcher learned about post dates (see import_service._DATE_WINDOW_DAYS).

A card CSV export carries the transaction date; SimpleFIN reports the *post*
date, routinely 1-2 days later. The old matcher required an exact date match,
so every charge already loaded from CSV was re-imported on the next sync.
Found live 2026-08-12: 130 pairs, $7,702.40, dated 2026-07-10..2026-08-04 --
which inflated the Household Snapshot's category totals and the weekly
spending email.

Pairs rows on (card_id, merchant, amount) within +/-3 days across differing
`source`, strictly 1:1 and closest-date-first, then deletes the bank_sync
member -- the csv_import row carries the true transaction date. Deliberately
does NOT touch CreditCard.current_balance: that comes from SimpleFIN's live
balance, not from summing rows.

Run from project root:
    source .venv/bin/activate
    python scripts/dedupe_card_transactions.py [--apply]

Without --apply it reports what it would do and changes nothing.
"""
import sys, os, shutil, argparse
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend import models
from backend.services.import_service import _DATE_WINDOW_DAYS, _normalize_desc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "budget.db")
BACKUP_DIR = os.path.join(ROOT, "data", "backups")


def find_duplicate_pairs(db):
    """Return [(keep_row, delete_row)] -- the csv_import row and its bank_sync twin.

    Grouped by (card_id, normalized merchant, amount) so the whitespace
    normalization used at import time applies here too. Within a group,
    candidates are paired closest-date-first and each row is used at most once,
    matching the 1:1 rule in import_service._pick_closest.
    """
    groups = defaultdict(list)
    for row in db.query(models.CreditCardTransaction).order_by(models.CreditCardTransaction.id).all():
        groups[(row.card_id, _normalize_desc(row.merchant or ""), row.amount)].append(row)

    pairs = []
    for rows in groups.values():
        if len(rows) < 2:
            continue
        csv_rows = [r for r in rows if r.source == models.CardTransactionSource.csv_import]
        sync_rows = [r for r in rows if r.source == models.CardTransactionSource.bank_sync]
        used_csv = set()
        # Closest date first, so a tight pair is never broken up by a looser one.
        candidates = sorted(
            (
                (abs((s.date - c.date).days), c.id, s.id, c, s)
                for c in csv_rows for s in sync_rows
                if abs((s.date - c.date).days) <= _DATE_WINDOW_DAYS
            ),
            key=lambda t: t[:3],
        )
        used_sync = set()
        for _, cid, sid, csv_row, sync_row in candidates:
            if cid in used_csv or sid in used_sync:
                continue
            used_csv.add(cid)
            used_sync.add(sid)
            pairs.append((csv_row, sync_row))
    return pairs


def month_report(db, card_id):
    out = {}
    for row in db.query(models.CreditCardTransaction).filter_by(card_id=card_id).all():
        key = row.date.strftime("%Y-%m")
        count, total = out.get(key, (0, 0))
        out[key] = (count + 1, total + float(row.amount))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    args = ap.parse_args()

    db = SessionLocal()
    card_ids = sorted({c.id for c in db.query(models.CreditCard).all()})
    before = {cid: month_report(db, cid) for cid in card_ids}

    pairs = find_duplicate_pairs(db)
    total = sum(float(s.amount) for _, s in pairs)
    print(f"Found {len(pairs)} duplicate pairs, ${total:,.2f} of double-counted charges")
    if pairs:
        dates = sorted(s.date for _, s in pairs)
        print(f"  date range: {dates[0]} .. {dates[-1]}")
        print("\n  sample (keep <- delete):")
        for csv_row, sync_row in pairs[:10]:
            print(f"    {csv_row.date} {csv_row.merchant[:34]:34} ${float(csv_row.amount):>10,.2f}"
                  f"   <- id {sync_row.id} dated {sync_row.date}")

    if not args.apply:
        print("\nDry run -- nothing deleted. Re-run with --apply to commit.")
        return

    if not pairs:
        print("Nothing to do.")
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = os.path.join(BACKUP_DIR, f"budget.db.pre-dedupe-{stamp}")
    shutil.copy2(DB_PATH, backup)
    print(f"\nBacked up to {backup}")

    for _, sync_row in pairs:
        db.delete(sync_row)
    db.commit()
    print(f"Deleted {len(pairs)} bank_sync rows")

    print("\nPer-month totals, before -> after:")
    for cid in card_ids:
        after = month_report(db, cid)
        changed = [m for m in sorted(set(before[cid]) | set(after)) if before[cid].get(m) != after.get(m)]
        if not changed:
            continue
        card = db.get(models.CreditCard, cid)
        print(f"  card {cid} ({card.name}):")
        for m in changed:
            bc, bt = before[cid].get(m, (0, 0))
            ac, at = after.get(m, (0, 0))
            print(f"    {m}  {bc:>4} rows ${bt:>12,.2f}  ->  {ac:>4} rows ${at:>12,.2f}")


if __name__ == "__main__":
    main()
