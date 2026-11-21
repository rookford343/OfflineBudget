"""Task 1 (Split One-Off Installments): installment_group_id/is_refund_watch
columns on PlannedExpense. Mirrors test_models_contingency.py's engine-swap
migration pattern -- builds an old-shape planned_expenses table with neither
new column, runs upgrade_schema() against it, and asserts both appear."""
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


def test_upgrade_schema_adds_installment_columns(monkeypatch):
    import backend.database as database_module

    test_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with test_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE planned_expenses (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name VARCHAR(128) NOT NULL,
                amount NUMERIC(14,2) NOT NULL,
                expected_date DATE NOT NULL
            )
        """))
        conn.commit()

    monkeypatch.setattr(database_module, "engine", test_engine)
    database_module.upgrade_schema()

    with test_engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(planned_expenses)"))}
    assert "installment_group_id" in cols
    assert "is_refund_watch" in cols
