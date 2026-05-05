"""Keyword-based auto-categorization for imported transactions."""
from __future__ import annotations
from backend import models

# (keyword_lower, category_name) — first match wins; order matters
KEYWORD_RULES: list[tuple[str, str]] = [
    # Food & Drinks
    ("whole foods", "Food & Drinks"),
    ("trader joe", "Food & Drinks"),
    ("kroger", "Food & Drinks"),
    ("publix", "Food & Drinks"),
    ("safeway", "Food & Drinks"),
    ("aldi", "Food & Drinks"),
    ("mcdonald", "Food & Drinks"),
    ("chick-fil-a", "Food & Drinks"),
    ("chipotle", "Food & Drinks"),
    ("panera", "Food & Drinks"),
    ("starbucks", "Food & Drinks"),
    ("dunkin", "Food & Drinks"),
    ("domino", "Food & Drinks"),
    ("pizza hut", "Food & Drinks"),
    ("doordash", "Food & Drinks"),
    ("grubhub", "Food & Drinks"),
    ("ubereats", "Food & Drinks"),
    ("uber eats", "Food & Drinks"),
    ("longhorn", "Food & Drinks"),
    ("olive garden", "Food & Drinks"),
    ("chili's", "Food & Drinks"),
    ("applebee", "Food & Drinks"),
    ("outback", "Food & Drinks"),
    # Subscriptions
    ("netflix", "Subscriptions"),
    ("spotify", "Subscriptions"),
    ("hulu", "Subscriptions"),
    ("disney+", "Subscriptions"),
    ("apple tv", "Subscriptions"),
    ("apple one", "Subscriptions"),
    ("youtube premium", "Subscriptions"),
    ("icloud", "Subscriptions"),
    ("amazon prime", "Subscriptions"),
    ("peacock", "Subscriptions"),
    ("paramount", "Subscriptions"),
    ("max.com", "Subscriptions"),
    # Entertainment
    ("app store", "Entertainment"),
    ("itunes", "Entertainment"),
    ("google play", "Entertainment"),
    ("steam", "Entertainment"),
    ("xbox", "Entertainment"),
    ("playstation", "Entertainment"),
    ("fandango", "Entertainment"),
    ("amc", "Entertainment"),
    # Transportation
    ("shell", "Transportation"),
    ("bp ", "Transportation"),
    ("exxon", "Transportation"),
    ("chevron", "Transportation"),
    ("costco gas", "Transportation"),
    ("sam's gas", "Transportation"),
    ("uber", "Transportation"),
    ("lyft", "Transportation"),
    ("e-zpass", "Transportation"),
    ("sunpass", "Transportation"),
    ("jiffy lube", "Transportation"),
    ("autozone", "Transportation"),
    ("o'reilly", "Transportation"),
    ("advance auto", "Transportation"),
    # Shopping
    ("amazon", "Shopping"),
    ("walmart", "Shopping"),
    ("target", "Shopping"),
    ("costco", "Shopping"),
    ("sam's club", "Shopping"),
    ("home depot", "Shopping"),
    ("lowe's", "Shopping"),
    ("best buy", "Shopping"),
    ("nordstrom", "Shopping"),
    ("macy's", "Shopping"),
    ("gap", "Shopping"),
    ("old navy", "Shopping"),
    ("tj maxx", "Shopping"),
    ("marshalls", "Shopping"),
    ("ross ", "Shopping"),
    # Utilities
    ("duke energy", "Utilities"),
    ("duke electric", "Utilities"),
    ("xfinity", "Utilities"),
    ("comcast", "Utilities"),
    ("at&t", "Utilities"),
    ("verizon", "Utilities"),
    ("t-mobile", "Utilities"),
    ("spectrum", "Utilities"),
    ("google fi", "Utilities"),
    ("piedmont natural gas", "Utilities"),
    ("dominion", "Utilities"),
    # Insurance
    ("geico", "Insurance"),
    ("progressive", "Insurance"),
    ("state farm", "Insurance"),
    ("allstate", "Insurance"),
    ("nationwide", "Insurance"),
    ("usaa", "Insurance"),
    # Healthcare
    ("cvs", "Healthcare"),
    ("walgreens", "Healthcare"),
    ("rite aid", "Healthcare"),
    ("labcorp", "Healthcare"),
    ("quest diagnostics", "Healthcare"),
    # Church / Tithe
    ("church", "Church / Tithe"),
    ("tithe", "Church / Tithe"),
    ("giving", "Church / Tithe"),
]


def categorize(
    description: str,
    categories: list[models.Category],
    history_map: dict[str, int] | None = None,
) -> models.Category | None:
    """Return the best matching category for a transaction description, or None.

    history_map: {description_lower: category_id} built from past transactions.
    History match takes precedence over keyword rules.
    """
    desc_lower = description.lower()
    cat_by_id: dict[int, models.Category] = {c.id: c for c in categories}
    cat_by_name: dict[str, models.Category] = {c.name.lower(): c for c in categories}

    if history_map:
        cat_id = history_map.get(desc_lower)
        if cat_id and cat_id in cat_by_id:
            return cat_by_id[cat_id]

    for keyword, cat_name in KEYWORD_RULES:
        if keyword in desc_lower:
            target = cat_by_name.get(cat_name.lower())
            if target:
                return target
    return None
