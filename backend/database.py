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
    ]
    with engine.connect() as conn:
        for s in stmts:
            try:
                conn.execute(text(s))
                conn.commit()
            except Exception:
                conn.rollback()  # column already exists — skip
