#!/usr/bin/env python3
"""
Seed transaction-categorization rules and backfill existing uncategorized rows.

Only two rules existed (Mortgage, Kroger), so most imported spending landed with
no category. Measured 2026-08-12: 169 distinct uncategorized card merchants, and
"Uncategorized" ranked third in the Household Snapshot's 7-day category list --
which is the breakdown Dan's wife reads in the weekly email, so an unlabeled
bucket is the worst possible place for the money to sit.

Patterns are drawn from the merchant strings actually present in this database,
so each one earns its keep rather than being a generic guess.

Run from project root:
    source .venv/bin/activate
    python scripts/seed_categorization_rules.py [--apply]
"""
import sys, os, argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend import models
from backend.services.rules_engine import apply_rules

USER_ID = 2

# (category name, [merchant substrings]) -- matched case-insensitively.
RULES: list[tuple[str, list[str]]] = [
    ("Groceries", [
        "MEIJER", "COSTCO", "WHOLEFDS", "WHOLE FOODS", "TRADER JOE", "ALDI",
        "FRESH THYME", "CARNICERIA", "DULCERIA", "SAMS CLUB", "WALMART",
        "TARGET", "SPROUTS",
    ]),
    ("Food & Drinks", [
        "MOTW COFFE", "URBAN VINES", "SUSHI STATION", "ALII POKE", "NAFNAFGRILL",
        "THINK COFFEE", "STARBUCKS", "DUNKIN", "CHIPOTLE", "PANERA",
        "SMOOTHIE KING", "GRAETERS", "BOVACONTI", "FERNANDO", "WOLFIES GRILL",
        "ANTHONYS CHOPHOUSE", "THE GRADUATE", "DOORDASH", "UBER EATS",
        "GRUBHUB", "MCDONALD", "CHICK-FIL-A", "PIZZA", "TST*", "UEP*",
        "RESTAURANT", "BREWING", "TAVERN", "CAFE", "COFFEE", "FRESHLYX",
    ]),
    ("Shopping", [
        "AMAZON", "AMZN", "ETSY", "IKEA", "AZAZIE", "CARTER'S", "AMERICAN EAGLE",
        "HOBBY-LOBBY", "AT HOME STORE", "ACE HARDWARE", "DICKSSPORTINGGOODS",
        "GROOVE LIFE", "EUFY", "BLISS DIAMO", "HOBBS LONDON", "RUBY LUCY",
        "BEST BUY", "HOME DEPOT", "LOWES", "WAYFAIR", "EBAY",
    ]),
    ("Travel", [
        "AIRBNB", "DELTA", "VIRGIN ATLANTIC", "HEATHROWEXPRESS", "TFL TRAVEL",
        "MTA*NYCT", "AVIS RENT-A-CAR", "HOTEL", "GETT", "TAXI", "LEFT-BAGGAGE",
        "AVOLTA", "HUDSON ST", "TOP OF THE ROCK", "LYFT", "UBER   *TRIP",
        "AIRLINES", "EXPEDIA", "MARRIOTT", "HILTON",
    ]),
    ("Subscriptions", [
        "OZWELL", "SEED.COM", "PELOTON", "SPOTIFY", "NETFLIX", "HULU", "HBO",
        "APPLE.COM/BILL", "AUDIBLE", "NYTIMES", "RUNNA", "FITBOD",
    ]),
    ("Vehicles", [
        "VIOC", "AUTO-OWNERS INSURANCE", "SHELL", "SPEEDWAY", "MARATHON",
        "RIVIAN", "DISCOUNT TIRE", "JIFFY LUBE", "CIRCLE K",
    ]),
    ("Healthcare", [
        "CTR FOR DIAGNOSTIC", "EXCELL FOR LIFE", "PET WELLNESS", "PHARMACY",
        "CVS", "WALGREENS", "DENTAL", "ORTHO", "MED*",
    ]),
    ("Entertainment", [
        "U90SOCCER", "500 FESTIVAL RUNN", "AMC ", "CINEMA", "TICKETMASTER",
        "STEAM GAMES", "GOLF",
    ]),
    ("Services", [
        "MONON LAWN", "GREENIX", "WOODHOUSESPA", "THE W NAIL BAR", "SKINBEAUTIF",
        "SKIN TWINS", "MINDBODY", "HOUSE CLEAN", "VICKY", "SECRET SPA",
    ]),
    # The two that matter most on the checking side. Everything else left
    # uncategorized there is a transfer, a card autopay, or a person-to-person
    # Zelle -- none of which is a spending category, and all of which the
    # spending helpers already exclude by other means.
    ("Church / Tithe", [
        "MERCYROAD",     # $1,300/mo, the largest single uncategorized checking line
    ]),
    ("Vehicles", [
        "TO AUTO LOAN",  # the Rivian R1T payment, $500.89/mo
    ]),
]

# A second pass aimed at the long tail left after the first: mostly one-visit
# restaurants and shops. Generic words are used only where they are unambiguous
# in a merchant string ("DINER", "TAQUERIA"), never bare words like "BAR" that
# would catch "BARNES" or "BARBER".
RULES += [
    ("Food & Drinks", [
        "TORCHYS", "JAGGER", "FIRST WATCH", "NOMAD DINER", "JAWDI GRILL",
        "BOCADO", "MATADOR", "TE'KILA", "HOLE IN THE WALL", "DINER",
        "TAQUERIA", "BRUNCH", "STEAKHOUSE", "CREAMERY", "BAKERY", "DELI",
        "BISTRO", "EATERY", "GRILL",
    ]),
    ("Shopping", [
        "ARITZIA", "MICHAELS STORES", "ONCE UPON A CHLD", "FABLETICS",
        "TKMAXX", "RTIC OUTDOORS", "OUR TRUE GOD", "ITALIAN LEATHER",
        "OLD NAVY", "GAP ", "NORDSTROM", "MARSHALLS",
    ]),
    ("Travel", [
        "FAST PARK", "STATUE CRUISES", "PARKING", "RENTAL CAR",
    ]),
    ("Subscriptions", [
        "ANNUAL MEMBERSHIP FEE",  # the card's own annual fee
    ]),
]


def resolve_categories(db):
    """Map the names above onto real categories, falling back where a name has
    no counterpart. 'Services' and 'Healthcare' are the two the sheet uses but
    this user's category tree lacks -- both fold into Subscriptions/Necessities
    the way '2026 Overview' folds "Services" into the credit budget."""
    by_name = {
        c.name: c for c in db.query(models.Category).filter_by(user_id=USER_ID).all()
    }
    fallbacks = {"Services": "Subscriptions", "Healthcare": "Necessities"}
    resolved = {}
    for name, _ in RULES:
        cat = by_name.get(name) or by_name.get(fallbacks.get(name, ""))
        if cat:
            resolved[name] = cat
        else:
            print(f"  MISSING  no category for {name} (and no fallback) -- rules skipped")
    return resolved


def seed_rules(db):
    """Always stages into the session and flushes, so a dry run can preview the
    backfill against the full rule set. main() decides commit vs rollback."""
    print("Rules:")
    resolved = resolve_categories(db)
    existing = {
        (r.pattern.lower(), r.category_id)
        for r in db.query(models.TransactionRule).filter_by(user_id=USER_ID).all()
    }
    created = 0
    for cat_name, patterns in RULES:
        cat = resolved.get(cat_name)
        if not cat:
            continue
        for pattern in patterns:
            if (pattern.lower(), cat.id) in existing:
                continue
            db.add(models.TransactionRule(
                user_id=USER_ID,
                name=f"{pattern} -> {cat.name}",
                field=models.RuleField.description,
                pattern_type=models.RulePatternType.contains,
                pattern=pattern,
                action=models.RuleAction.set_category,
                category_id=cat.id,
                priority=0,
                is_active=True,
            ))
            created += 1
    print(f"  {created} new rules ({len(existing)} already present)")
    db.flush()


def backfill(db, apply: bool):
    """Run the rule set over rows that never got a category. Only fills blanks --
    never overwrites a category a human or the auto-categorizer already set."""
    rules = db.query(models.TransactionRule).filter_by(user_id=USER_ID).all()
    print(f"\nBackfill with {len(rules)} rules:")

    hits = Counter()
    card_rows = db.query(models.CreditCardTransaction).filter(
        models.CreditCardTransaction.user_id == USER_ID,
        models.CreditCardTransaction.category_id.is_(None),
    ).all()
    for row in card_rows:
        match = apply_rules(row.merchant or "", rules)
        if match and match.category_id:
            hits[match.category_id] += 1
            if apply:
                row.category_id = match.category_id

    chk_rows = db.query(models.Transaction).filter(
        models.Transaction.user_id == USER_ID,
        models.Transaction.category_id.is_(None),
    ).all()
    for row in chk_rows:
        match = apply_rules(row.description or "", rules)
        if match and match.category_id:
            hits[match.category_id] += 1
            if apply:
                row.category_id = match.category_id

    names = {c.id: c.name for c in db.query(models.Category).filter_by(user_id=USER_ID).all()}
    total = sum(hits.values())
    print(f"  {len(card_rows)} uncategorized card rows, {len(chk_rows)} checking rows")
    print(f"  matched {total}:")
    for cid, n in hits.most_common():
        print(f"    {names.get(cid, cid):<18} {n}")


def report(db):
    print("\nUncategorized share, trailing 90 days:")
    for label, model, field in (
        ("card", models.CreditCardTransaction, "merchant"),
        ("checking", models.Transaction, "description"),
    ):
        rows = db.query(model).filter(
            model.user_id == USER_ID, model.date >= "2026-05-14",
        ).all()
        if not rows:
            print(f"  {label}: no rows")
            continue
        blank = sum(1 for r in rows if r.category_id is None)
        print(f"  {label}: {blank}/{len(rows)} = {blank / len(rows):.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    seed_rules(db)
    backfill(db, args.apply)
    if args.apply:
        db.commit()
        print("\nCommitted.")
    else:
        db.rollback()
        print("\nDry run -- nothing written. Re-run with --apply to commit.")
    report(db)


if __name__ == "__main__":
    main()
