"""Delete everything a user owns, generically from the table metadata.

The ORM cascades on ``User`` only cover some tables, and SQLite enforces
foreign keys, so ``db.delete(user)`` fails for anyone with rows elsewhere
(bank connections, trips, wish items, rules...). Walking ``Base.metadata``
instead means a table added later is covered without touching this file;
the guard test in test_security_regressions.py fails if a new table is
neither owned nor on the explicit global list.

Ownership: a row is owned when its table has ``user_id`` equal to the user's
id, or (for tables without ``user_id``) when a foreign key points at an owned
row, transitively (links -> bank_connections, scenario_overrides ->
forecast_scenarios, ...).
"""
from __future__ import annotations

from sqlalchemy import Table, delete, or_, select, update
from sqlalchemy.orm import Session

from backend import models
from backend.database import Base

# Global tables no user owns. Never touched.
GLOBAL_TABLES = frozenset({"app_settings", "scheduler_runs"})


def is_owned_table(table: Table, _seen: frozenset[str] = frozenset()) -> bool:
    """True when rows of ``table`` can be attributed to a user (directly or via FKs)."""
    if table.name == "users" or table.name in GLOBAL_TABLES:
        return False
    if "user_id" in table.c:
        return True
    if table.name in _seen:
        return False
    seen = _seen | {table.name}
    return any(
        is_owned_table(fk.column.table, seen)
        for col in table.c for fk in col.foreign_keys
    )


def _owned_where(table: Table, user_id: int, _seen: frozenset[str] = frozenset()):
    """SQL condition selecting this table's rows owned by ``user_id`` (None if unowned)."""
    if "user_id" in table.c:
        return table.c.user_id == user_id
    if table.name in _seen:
        return None
    seen = _seen | {table.name}
    clauses = []
    for col in table.c:
        for fk in col.foreign_keys:
            parent = fk.column.table
            if parent.name in GLOBAL_TABLES or parent.name == "users":
                continue
            cond = _owned_where(parent, user_id, seen)
            if cond is not None:
                clauses.append(col.in_(select(fk.column).where(cond)))
    return or_(*clauses) if clauses else None


def delete_user_data(db: Session, user: models.User) -> None:
    """Remove every row ``user`` owns, then the user row. Commits."""
    uid = user.id
    users_t = Base.metadata.tables["users"]
    tables = list(Base.metadata.sorted_tables)
    position = {t.name: i for i, t in enumerate(tables)}

    # Other logins linked to this one become standalone; this user's own
    # shortfall-account pointer is cleared (works on old and new schemas).
    db.execute(update(users_t).where(users_t.c.linked_to_user_id == uid).values(linked_to_user_id=None))
    db.execute(update(users_t).where(users_t.c.id == uid).values(bonus_shortfall_account_id=None))

    # FK cycles (use_alter edges, e.g. wish_items.plan_option_id -> wish_options)
    # are ignored by sorted_tables: null the nullable side of owned rows first.
    for table in tables:
        where = _owned_where(table, uid)
        if where is None:
            continue
        for col in table.c:
            for fk in col.foreign_keys:
                parent = fk.column.table
                if parent is not table and parent.name != "users" and position[parent.name] > position[table.name]:
                    db.execute(update(table).where(where).values({col.name: None}))

    for table in reversed(tables):
        where = _owned_where(table, uid)
        if where is not None:
            db.execute(delete(table).where(where))

    db.execute(delete(users_t).where(users_t.c.id == uid))
    # Detach everything: the ORM objects for deleted rows must not be flushed again.
    db.expunge_all()
    db.commit()
