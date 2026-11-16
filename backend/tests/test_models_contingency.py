"""Task 1 (Contingency Planning): is_essential/contingency_paused_at columns on
RecurringItem and the one-time backfill that derives is_essential from each
item's category on upgrade."""
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend import models


def test_new_item_defaults_essential_true(db_session, test_user, test_account):
    item = models.RecurringItem(
        user_id=test_user.id, account_id=test_account.id, name="Test Item",
        amount=Decimal("45.00"), type=models.RecurringType.expense,
        day_of_month=15, start_date=date(2026, 1, 1),
    )
    db_session.add(item)
    db_session.commit()
    assert item.is_essential is True
    assert item.contingency_paused_at is None


def test_existing_item_backfills_essential_from_category(monkeypatch):
    """A pre-existing row (simulating data from before this migration) with a
    discretionary category backfills to is_essential=False; one with a
    non-discretionary category backfills to True. Mirrors
    test_plaid_schema.py's engine-swap pattern -- never touches the real DB."""
    import backend.database as database_module

    test_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with test_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
                name VARCHAR(64) NOT NULL, is_discretionary BOOLEAN DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE recurring_items (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL, category_id INTEGER,
                name VARCHAR(128) NOT NULL, amount NUMERIC(14,2) NOT NULL,
                type VARCHAR(20) NOT NULL, frequency VARCHAR(10) DEFAULT 'monthly',
                day_of_month INTEGER NOT NULL, start_date DATE NOT NULL,
                is_active BOOLEAN DEFAULT 1
            )
        """))
        conn.execute(text(
            "INSERT INTO categories (id, user_id, name, is_discretionary) VALUES "
            "(1, 1, 'Test Discretionary', 1), (2, 1, 'Test Necessary', 0)"
        ))
        conn.execute(text(
            "INSERT INTO recurring_items (user_id, account_id, category_id, name, amount, type, day_of_month, start_date) "
            "VALUES (1, 1, 1, 'Pre-migration Discretionary', 45.00, 'expense', 15, '2026-01-01'), "
            "(1, 1, 2, 'Pre-migration Necessary', 45.00, 'expense', 15, '2026-01-01')"
        ))
        conn.commit()

    monkeypatch.setattr(database_module, "engine", test_engine)
    database_module.upgrade_schema()

    with test_engine.connect() as conn:
        rows = {
            row[0]: row[1] for row in conn.execute(
                text("SELECT name, is_essential FROM recurring_items")
            )
        }
    assert rows["Pre-migration Discretionary"] == 0
    assert rows["Pre-migration Necessary"] == 1
