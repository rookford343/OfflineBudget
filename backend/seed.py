"""Seed default categories for a new user on registration."""
from sqlalchemy.orm import Session
from backend import models

DEFAULT_CATEGORIES = [
    # (name, type, color, icon, children)
    ("Income", "income", "#22c55e", "trending-up", [
        ("Salary / Wages", "income", "#16a34a", "briefcase"),
        ("Bonus", "income", "#15803d", "star"),
        ("Other Income", "income", "#166534", "plus-circle"),
    ]),
    ("Necessities", "expense", "#3b82f6", "home", [
        ("Utilities", "expense", "#2563eb", "zap"),
        ("Insurance", "expense", "#1d4ed8", "shield"),
        ("Transportation", "expense", "#1e40af", "car"),
        ("Healthcare", "expense", "#1e3a8a", "heart"),
        ("Mortgage / Rent", "expense", "#172554", "building"),
    ]),
    ("Wants", "expense", "#f59e0b", "shopping-bag", [
        ("Food & Drinks", "expense", "#d97706", "utensils"),
        ("Shopping", "expense", "#b45309", "shopping-cart"),
        ("Entertainment", "expense", "#92400e", "film"),
        ("Travel", "expense", "#78350f", "map"),
        ("Subscriptions", "expense", "#451a03", "repeat"),
    ]),
    ("Savings", "expense", "#8b5cf6", "piggy-bank", [
        ("Emergency Fund", "expense", "#7c3aed", "shield-check"),
        ("Retirement", "expense", "#6d28d9", "trending-up"),
        ("Investment", "expense", "#5b21b6", "bar-chart"),
    ]),
    ("Charity", "expense", "#ec4899", "heart-handshake", [
        ("Church / Tithe", "expense", "#db2777", "church"),
    ]),
    ("Other", "expense", "#6b7280", "more-horizontal", []),
]


def seed_default_categories(db: Session, user: models.User) -> None:
    for sort_top, (name, ctype, color, icon, children) in enumerate(DEFAULT_CATEGORIES):
        parent = models.Category(
            user_id=user.id,
            name=name,
            type=ctype,
            color=color,
            icon=icon,
            sort_order=sort_top,
        )
        db.add(parent)
        db.flush()
        for sort_child, (cname, cctype, ccolor, cicon, *_) in enumerate(children):
            child = models.Category(
                user_id=user.id,
                parent_id=parent.id,
                name=cname,
                type=cctype,
                color=ccolor,
                icon=cicon,
                sort_order=sort_child,
            )
            db.add(child)
    db.commit()
