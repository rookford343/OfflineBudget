from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from backend.config import settings


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)

# Enable WAL mode and foreign keys for SQLite
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def create_tables():
    Base.metadata.create_all(bind=engine)


def upgrade_categories():
    """One-time rename: 'Tithing / Giving' → 'Charity'; remove orphan 'Charity' sub-category."""
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "UPDATE categories SET name = 'Charity' WHERE name = 'Tithing / Giving' AND parent_id IS NULL"
            ))
            conn.commit()
            conn.execute(text("""
                DELETE FROM categories
                WHERE name = 'Charity'
                  AND parent_id IN (
                      SELECT id FROM categories WHERE name = 'Charity' AND parent_id IS NULL
                  )
            """))
            conn.commit()
        except Exception:
            conn.rollback()


def upgrade_schema():
    """Add new columns to existing tables. Ignores errors for already-existing columns."""
    stmts = [
        "ALTER TABLE accounts ADD COLUMN low_balance_threshold NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN role VARCHAR(10) DEFAULT 'admin'",
        "ALTER TABLE recurring_items ADD COLUMN frequency VARCHAR(10) DEFAULT 'monthly'",
        "ALTER TABLE recurring_items ADD COLUMN month_of_year INTEGER",
        "ALTER TABLE categories ADD COLUMN rollover_enabled BOOLEAN DEFAULT 0",
        "ALTER TABLE categories ADD COLUMN rollover_balance NUMERIC(14,2) DEFAULT 0",
        "ALTER TABLE users ADD COLUMN ss_gross_per_paycheck NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN ss_wage_base NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN ss_bonus_ytd NUMERIC(14,2)",
        "ALTER TABLE recurring_items ADD COLUMN card_id INTEGER",
        "ALTER TABLE users ADD COLUMN linked_to_user_id INTEGER",
        "ALTER TABLE users ADD COLUMN email TEXT",
        "ALTER TABLE accounts ADD COLUMN interest_rate NUMERIC(14,4)",
        "ALTER TABLE categories ADD COLUMN tax_deductible BOOLEAN DEFAULT 0",
        "ALTER TABLE credit_cards ADD COLUMN next_payment_date DATE",
        "ALTER TABLE planned_expenses ADD COLUMN account_id INTEGER REFERENCES accounts(id)",
        "ALTER TABLE credit_cards ADD COLUMN monthly_spend_estimate NUMERIC(14,2)",
        """CREATE TABLE IF NOT EXISTS transaction_rules (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(128) NOT NULL,
            field VARCHAR(20) NOT NULL,
            pattern_type VARCHAR(20) NOT NULL,
            pattern VARCHAR(256) NOT NULL,
            action VARCHAR(20) NOT NULL,
            category_id INTEGER REFERENCES categories(id),
            priority INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        "ALTER TABLE users ADD COLUMN tax_filing_status VARCHAR(32)",
        "ALTER TABLE users ADD COLUMN tax_state VARCHAR(2)",
        "ALTER TABLE users ADD COLUMN annual_salary NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN other_income NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN federal_withholding_ytd NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN state_withholding_ytd NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN itemized_mortgage_interest NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN itemized_donations NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN itemized_salt NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN itemized_property_tax NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN itemized_other NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN recovery_code_hash TEXT",
        "ALTER TABLE users ADD COLUMN recovery_code_created_at DATETIME",
        """CREATE TABLE IF NOT EXISTS forecast_day_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            date DATE NOT NULL,
            actual_balance NUMERIC(14,2) NOT NULL,
            note TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, account_id, date)
        )""",
        """CREATE TABLE IF NOT EXISTS monthly_forecast_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            forecasted_open NUMERIC(14,2) NOT NULL,
            forecasted_close NUMERIC(14,2) NOT NULL,
            snapshot_taken_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, account_id, year, month)
        )""",
        "ALTER TABLE credit_cards ADD COLUMN pending_charges NUMERIC(14,2) DEFAULT 0",
        "ALTER TABLE transactions ADD COLUMN external_id VARCHAR(128)",
        "ALTER TABLE credit_card_transactions ADD COLUMN external_id VARCHAR(128)",
    ]
    with engine.connect() as conn:
        for s in stmts:
            try:
                conn.execute(text(s))
                conn.commit()
            except Exception:
                conn.rollback()  # column already exists — skip
