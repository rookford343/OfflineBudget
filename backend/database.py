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


def rename_utilities_to_home(conn) -> None:
    """Utilities → Home, in place, so every link to the row keeps working.

    Only the Utilities that sits under a top-level Necessities, and only when
    that parent has no Home child already -- running twice, or on a database
    where someone already made Home by hand, must be a no-op rather than
    producing two Homes.
    """
    conn.execute(text("""
        UPDATE categories SET name = 'Home'
        WHERE name = 'Utilities'
          AND parent_id IN (
              SELECT id FROM categories WHERE name = 'Necessities' AND parent_id IS NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM categories AS sib
              WHERE sib.parent_id = categories.parent_id AND sib.name = 'Home'
          )
    """))


def ensure_health_category(conn) -> None:
    """Every top-level Necessities gets a Health child.

    An existing Healthcare there is renamed in place (links keep working);
    otherwise Health is created, last in sort order. Committed spending, not
    an assignable bucket, so is_discretionary stays 0. Idempotent: a parent
    that already has Health is left alone, Healthcare included.
    """
    conn.execute(text("""
        UPDATE categories SET name = 'Health'
        WHERE name = 'Healthcare'
          AND parent_id IN (
              SELECT id FROM categories WHERE name = 'Necessities' AND parent_id IS NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM categories AS sib
              WHERE sib.parent_id = categories.parent_id AND sib.name = 'Health'
          )
    """))
    conn.execute(text("""
        INSERT INTO categories (
            user_id, parent_id, name, type, color, icon, sort_order,
            rollover_enabled, rollover_balance, tax_deductible, is_discretionary
        )
        SELECT n.user_id, n.id, 'Health', 'expense', '#1e3a8a', 'heart',
               COALESCE((SELECT MAX(c.sort_order) + 1 FROM categories AS c WHERE c.parent_id = n.id), 0),
               0, 0, 0, 0
        FROM categories AS n
        WHERE n.name = 'Necessities' AND n.parent_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM categories AS s WHERE s.parent_id = n.id AND s.name = 'Health'
          )
    """))


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
            rename_utilities_to_home(conn)
            conn.commit()
            ensure_health_category(conn)
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
        "ALTER TABLE recurring_items ADD COLUMN include_in_forecast BOOLEAN DEFAULT 1",
        "ALTER TABLE users ADD COLUMN transfer_increment NUMERIC(14,2) DEFAULT 1000.00",
        "ALTER TABLE accounts ADD COLUMN is_emergency_fund BOOLEAN DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS bill_amount_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            recurring_item_id INTEGER NOT NULL REFERENCES recurring_items(id) ON DELETE CASCADE,
            due_date DATE NOT NULL,
            actual_amount NUMERIC(14,2) NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (recurring_item_id, due_date)
        )""",
        "ALTER TABLE users ADD COLUMN savings_strategy VARCHAR(32) DEFAULT 'save_monthly'",
        "ALTER TABLE planned_expenses ADD COLUMN settled_on DATE",
        "ALTER TABLE planned_expenses ADD COLUMN funding_account_id INTEGER REFERENCES accounts(id)",
        "ALTER TABLE planned_expenses ADD COLUMN funding_amount NUMERIC(14,2)",
        "ALTER TABLE planned_expenses ADD COLUMN funding_lead_days INTEGER DEFAULT 0",
        "ALTER TABLE planned_expenses ADD COLUMN actual_amount NUMERIC(14,2)",
        """CREATE TABLE IF NOT EXISTS planned_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            from_account_id INTEGER REFERENCES accounts(id),
            to_account_id INTEGER NOT NULL REFERENCES accounts(id),
            amount NUMERIC(14,2) NOT NULL,
            target_date DATE NOT NULL,
            status VARCHAR(10) NOT NULL DEFAULT 'pending',
            suggested BOOLEAN DEFAULT 0,
            notes TEXT,
            verified_transaction_id INTEGER REFERENCES transactions(id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS verification_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            feature VARCHAR(20) NOT NULL,
            reference_type VARCHAR(32),
            reference_id INTEGER,
            observed_json TEXT NOT NULL,
            expected_value NUMERIC(14,2),
            note TEXT,
            status VARCHAR(10) NOT NULL DEFAULT 'open',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME
        )""",
        # Lets a planned event be money coming IN, not just going out. Defaults
        # to 'outflow' so every existing row keeps its current behaviour.
        "ALTER TABLE planned_expenses ADD COLUMN direction VARCHAR(8) DEFAULT 'outflow'",
        # Lets a one-off expense be charged to a card instead of hitting
        # checking directly -- most of the user's planned purchases go on a card.
        "ALTER TABLE planned_expenses ADD COLUMN card_id INTEGER REFERENCES credit_cards(id)",
        # SS wage-base checkpoint, read straight off a pay stub's YTD
        # withholding line -- see models.py's User docstring comment.
        "ALTER TABLE users ADD COLUMN ss_withheld_ytd NUMERIC(14,2)",
        "ALTER TABLE users ADD COLUMN ss_withheld_ytd_as_of DATE",
        # Debug-only raw bank-sync payload capture -- see BankSyncRawSnapshot.
        "ALTER TABLE users ADD COLUMN debug_capture_raw_bank_data BOOLEAN DEFAULT 0",
        "ALTER TABLE users ADD COLUMN budget_carry_forward BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE categories ADD COLUMN is_discretionary BOOLEAN DEFAULT 0",
        "ALTER TABLE credit_cards ADD COLUMN payment_sent_pending_sync BOOLEAN DEFAULT 0",
        "ALTER TABLE credit_cards ADD COLUMN payment_sent_amount NUMERIC(14,2)",
        "ALTER TABLE credit_cards ADD COLUMN pending_charges_updated_at DATETIME",
        # Bank-sync staleness guard for credit-card balances -- see
        # CreditCard.balance_as_of in models.py for the full rationale.
        "ALTER TABLE credit_cards ADD COLUMN balance_as_of DATETIME",
        # Freshness stamp for the manual-only balance_due field -- see
        # CreditCard.balance_due_updated_at in models.py for the full
        # rationale.
        "ALTER TABLE credit_cards ADD COLUMN balance_due_updated_at DATETIME",
        # SchedulerRun, BankSyncRawSnapshot and AppSetting are brand-new
        # tables, created automatically by create_tables()'s
        # Base.metadata.create_all -- no ALTER TABLE needed for them.
        # What-if scenarios: a scenario can now propose items that do not
        # exist yet, and remember what it created so it can be uncommitted.
        "ALTER TABLE forecast_scenarios ADD COLUMN status VARCHAR(16) DEFAULT 'draft'",
        "ALTER TABLE forecast_scenarios ADD COLUMN committed_at DATETIME",
        "ALTER TABLE forecast_scenarios ADD COLUMN notes TEXT",
        "ALTER TABLE scenario_overrides ADD COLUMN committed_previous_amount NUMERIC(14,2)",
        """CREATE TABLE IF NOT EXISTS scenario_proposed_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL REFERENCES forecast_scenarios(id) ON DELETE CASCADE,
            name VARCHAR(128) NOT NULL,
            amount NUMERIC(14,2) NOT NULL,
            type VARCHAR(32) NOT NULL,
            frequency VARCHAR(10) NOT NULL DEFAULT 'monthly',
            day_of_month INTEGER NOT NULL DEFAULT 1,
            month_of_year INTEGER,
            start_date DATE NOT NULL,
            end_date DATE,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            card_id INTEGER REFERENCES credit_cards(id),
            category_id INTEGER REFERENCES categories(id),
            committed_recurring_item_id INTEGER REFERENCES recurring_items(id)
        )""",
        """CREATE TABLE IF NOT EXISTS scenario_proposed_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL REFERENCES forecast_scenarios(id) ON DELETE CASCADE,
            name VARCHAR(128) NOT NULL,
            amount NUMERIC(14,2) NOT NULL,
            expected_date DATE NOT NULL,
            direction VARCHAR(8) NOT NULL DEFAULT 'outflow',
            account_id INTEGER REFERENCES accounts(id),
            card_id INTEGER REFERENCES credit_cards(id),
            funding_account_id INTEGER REFERENCES accounts(id),
            category_id INTEGER REFERENCES categories(id),
            committed_planned_expense_id INTEGER REFERENCES planned_expenses(id)
        )""",
    ]
    with engine.connect() as conn:
        for s in stmts:
            try:
                conn.execute(text(s))
                conn.commit()
            except Exception:
                conn.rollback()  # column already exists — skip
