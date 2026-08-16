from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
from enum import Enum as PyEnum
from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class AccountType(str, PyEnum):
    checking = "checking"
    savings = "savings"
    money_market = "money_market"


class CategoryType(str, PyEnum):
    income = "income"
    expense = "expense"
    savings = "savings"


class RecurringType(str, PyEnum):
    income = "income"
    expense = "expense"
    credit_card_payment = "credit_card_payment"


class TransactionSource(str, PyEnum):
    manual = "manual"
    csv_import = "csv_import"
    forecast_generated = "forecast_generated"
    bank_sync = "bank_sync"


class CardTransactionSource(str, PyEnum):
    manual = "manual"
    csv_import = "csv_import"
    bank_sync = "bank_sync"


class ImportFormat(str, PyEnum):
    chase = "chase"
    amex = "amex"
    apple = "apple"
    generic = "generic"
    ofx = "ofx"


class UserRole(str, PyEnum):
    admin = "admin"
    viewer = "viewer"


class RecurringFrequency(str, PyEnum):
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"
    weekly = "weekly"
    biweekly = "biweekly"


class VerificationFeature(str, PyEnum):
    forecast = "forecast"
    transactions = "transactions"
    household_snapshot = "household_snapshot"


class VerificationFlagStatus(str, PyEnum):
    open = "open"
    resolved = "resolved"


class RuleField(str, PyEnum):
    description = "description"
    merchant = "merchant"


class RulePatternType(str, PyEnum):
    contains = "contains"
    startswith = "startswith"
    regex = "regex"


class RuleAction(str, PyEnum):
    set_category = "set_category"
    mark_transfer = "mark_transfer"


# ── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.admin, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ss_gross_per_paycheck: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ss_wage_base: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ss_bonus_ytd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # Direct checkpoint from a real pay stub -- the dollar amount of employee-
    # side 6.2% Social Security tax withheld year-to-date, and the date of the
    # last paycheck it reflects. Preferred over reconstructing YTD gross wages
    # by counting actual paychecks against a flat ss_gross_per_paycheck, which
    # compounds error across every raise in the year (Dan's April raise alone
    # misdated the 2026 crossing by a full paycheck -- see forecast_engine.py).
    # ss_withheld_ytd / 0.062 recovers gross wages actually subject to SS,
    # already correct for every raise, with no reconstruction needed. Falls
    # back to the legacy ss_bonus_ytd method when unset.
    ss_withheld_ytd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ss_withheld_ytd_as_of: Mapped[date | None] = mapped_column(Date)
    # Debug-only: when on, bank sync writes the full raw SimpleFIN payload per
    # transaction to BankSyncRawSnapshot. Off by default -- see that model's
    # docstring for why this is a toggle, not a permanent column.
    debug_capture_raw_bank_data: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_increment: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("1000.00"))

    linked_to_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    email: Mapped[str | None] = mapped_column(String(256))
    recovery_code_hash: Mapped[str | None] = mapped_column(String(256))
    recovery_code_created_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Tax profile
    tax_filing_status: Mapped[str | None] = mapped_column(String(32))   # single | married_jointly | married_separately | head_of_household
    tax_state: Mapped[str | None] = mapped_column(String(2))            # 2-letter state code
    annual_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    other_income: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    federal_withholding_ytd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    state_withholding_ytd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # Itemized deductions (manually entered from tax documents)
    itemized_mortgage_interest: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    itemized_donations: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    itemized_salt: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    itemized_property_tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    itemized_other: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    accounts: Mapped[list[Account]] = relationship(back_populates="user", cascade="all, delete-orphan")
    categories: Mapped[list[Category]] = relationship(back_populates="user", cascade="all, delete-orphan")
    recurring_items: Mapped[list[RecurringItem]] = relationship(back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="user", cascade="all, delete-orphan")
    credit_cards: Mapped[list[CreditCard]] = relationship(back_populates="user", cascade="all, delete-orphan")
    savings_transfers: Mapped[list[SavingsTransfer]] = relationship(back_populates="user", cascade="all, delete-orphan")
    buffer_transfer_rules: Mapped[list[BufferTransferRule]] = relationship(back_populates="user", cascade="all, delete-orphan")
    budget_allocations: Mapped[list[BudgetAllocation]] = relationship(back_populates="user", cascade="all, delete-orphan")
    savings_goals: Mapped[list[SavingsGoal]] = relationship(back_populates="user", cascade="all, delete-orphan")
    manual_assets: Mapped[list[ManualAsset]] = relationship(back_populates="user", cascade="all, delete-orphan")
    manual_liabilities: Mapped[list[ManualLiability]] = relationship(back_populates="user", cascade="all, delete-orphan")
    net_worth_snapshots: Mapped[list[NetWorthSnapshot]] = relationship(back_populates="user", cascade="all, delete-orphan")
    forecast_scenarios: Mapped[list[ForecastScenario]] = relationship(back_populates="user", cascade="all, delete-orphan")
    planned_expenses: Mapped[list[PlannedExpense]] = relationship(back_populates="user", cascade="all, delete-orphan")
    monthly_forecast_snapshots: Mapped[list["MonthlyForecastSnapshot"]] = relationship(back_populates="user", cascade="all, delete-orphan")


# ── Accounts ─────────────────────────────────────────────────────────────────

class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    low_balance_threshold: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="account")
    recurring_items: Mapped[list[RecurringItem]] = relationship(back_populates="account")
    outgoing_transfers: Mapped[list[SavingsTransfer]] = relationship(foreign_keys="SavingsTransfer.from_account_id", back_populates="from_account")
    incoming_transfers: Mapped[list[SavingsTransfer]] = relationship(foreign_keys="SavingsTransfer.to_account_id", back_populates="to_account")
    outgoing_buffer_rules: Mapped[list[BufferTransferRule]] = relationship(foreign_keys="BufferTransferRule.from_account_id", back_populates="from_account")
    incoming_buffer_rules: Mapped[list[BufferTransferRule]] = relationship(foreign_keys="BufferTransferRule.to_account_id", back_populates="to_account")
    card_payments: Mapped[list[CreditCardPayment]] = relationship(back_populates="checking_account")


# ── Categories ───────────────────────────────────────────────────────────────

class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[CategoryType] = mapped_column(Enum(CategoryType), nullable=False)
    color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    icon: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    rollover_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    rollover_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    tax_deductible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Discretionary = spending Dan can actually decide about this month
    # (Shopping, Food & Drinks, Entertainment). Fixed = committed before the
    # month starts (Mortgage, Tithe, Insurance). Mixing them made the
    # Spending page headline Mortgage $4,405 and Tithe $1,300 as if they were
    # choices, burying the ~$1,500 that is actually steerable. Mirrors the
    # discretionary grid in Dan's spreadsheet ('2026 Overview'!E3:E8).
    is_discretionary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)

    user: Mapped[User] = relationship(back_populates="categories")
    parent: Mapped[Category | None] = relationship(remote_side="Category.id", back_populates="children")
    children: Mapped[list[Category]] = relationship(back_populates="parent")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="category")
    recurring_items: Mapped[list[RecurringItem]] = relationship(back_populates="category")
    card_transactions: Mapped[list[CreditCardTransaction]] = relationship(back_populates="category")
    budget_allocations: Mapped[list[BudgetAllocation]] = relationship(back_populates="category")


# ── Recurring Items ───────────────────────────────────────────────────────────

class RecurringItem(Base):
    __tablename__ = "recurring_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_cards.id"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    type: Mapped[RecurringType] = mapped_column(Enum(RecurringType), nullable=False)
    frequency: Mapped[RecurringFrequency] = mapped_column(Enum(RecurringFrequency), default=RecurringFrequency.monthly, nullable=False)
    # 1-31 for specific day; 0 = last day of month
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    # 1-12 for yearly items: which month to fire in
    month_of_year: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Counts toward monthly budget totals (_monthly_income/_monthly_expenses)
    # either way. When False, excluded from the day-by-day cash forecast
    # (build_forecast/build_quarters) -- for income that's real but already
    # spoken for the moment it lands (e.g. an annual bonus modeled as 1/12th
    # per month for budget planning), not sitting in checking waiting to be
    # spent. Defaults True so every existing item keeps forecasting exactly
    # as before.
    include_in_forecast: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="recurring_items")
    account: Mapped[Account] = relationship(back_populates="recurring_items")
    category: Mapped[Category | None] = relationship(back_populates="recurring_items")
    card: Mapped[CreditCard | None] = relationship(foreign_keys=[card_id])
    transactions: Mapped[list[Transaction]] = relationship(back_populates="recurring_item")


class BufferTransferRule(Base):
    """Conditional monthly transfer: if `to_account` would dip below
    `action_threshold` before the next check_day, transfer `increment`-sized
    steps from `from_account` until it clears `target_floor`."""
    __tablename__ = "buffer_transfer_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    from_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    to_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    action_threshold: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    target_floor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    increment: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    check_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="buffer_transfer_rules")
    from_account: Mapped[Account] = relationship(foreign_keys=[from_account_id], back_populates="outgoing_buffer_rules")
    to_account: Mapped[Account] = relationship(foreign_keys=[to_account_id], back_populates="incoming_buffer_rules")


# ── Transactions ──────────────────────────────────────────────────────────────

class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    recurring_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("recurring_items.id"))
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)  # positive=credit, negative=debit
    description: Mapped[str] = mapped_column(String(256), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_actual: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[TransactionSource] = mapped_column(Enum(TransactionSource), default=TransactionSource.manual)
    # Upstream provider's own transaction id (SimpleFIN). NULL for manual entry
    # and CSV/OFX imports, which have no stable external identifier.
    external_id: Mapped[str | None] = mapped_column(String(128))
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="transactions")
    account: Mapped[Account] = relationship(back_populates="transactions")
    category: Mapped[Category | None] = relationship(back_populates="transactions")
    recurring_item: Mapped[RecurringItem | None] = relationship(back_populates="transactions")


# ── Credit Cards ──────────────────────────────────────────────────────────────

class CreditCard(Base):
    __tablename__ = "credit_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_four: Mapped[str | None] = mapped_column(String(4))
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    statement_day: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-31
    due_day: Mapped[int] = mapped_column(Integer, nullable=False)        # 1-31
    current_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    balance_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    next_payment_date: Mapped[date | None] = mapped_column(Date)
    monthly_spend_estimate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    pending_charges: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="credit_cards")
    payments: Mapped[list[CreditCardPayment]] = relationship(back_populates="card", cascade="all, delete-orphan")
    card_transactions: Mapped[list[CreditCardTransaction]] = relationship(back_populates="card", cascade="all, delete-orphan")
    imports: Mapped[list[CreditCardImport]] = relationship(back_populates="card", cascade="all, delete-orphan")


class CreditCardPayment(Base):
    __tablename__ = "credit_card_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    card_id: Mapped[int] = mapped_column(Integer, ForeignKey("credit_cards.id"), nullable=False)
    checking_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    card: Mapped[CreditCard] = relationship(back_populates="payments")
    checking_account: Mapped[Account] = relationship(back_populates="card_payments")


class CreditCardTransaction(Base):
    __tablename__ = "credit_card_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(Integer, ForeignKey("credit_cards.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    import_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_card_imports.id"))
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)  # positive=charge, negative=refund/credit
    merchant: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[CardTransactionSource] = mapped_column(Enum(CardTransactionSource), default=CardTransactionSource.manual)
    # Upstream provider's own transaction id (SimpleFIN). NULL for manual entry
    # and CSV/OFX imports, which have no stable external identifier.
    external_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    card: Mapped[CreditCard] = relationship(back_populates="card_transactions")
    category: Mapped[Category | None] = relationship(back_populates="card_transactions")
    import_record: Mapped[CreditCardImport | None] = relationship(back_populates="transactions")


class CreditCardImport(Base):
    __tablename__ = "credit_card_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(Integer, ForeignKey("credit_cards.id"), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    format: Mapped[ImportFormat] = mapped_column(Enum(ImportFormat), default=ImportFormat.generic)

    card: Mapped[CreditCard] = relationship(back_populates="imports")
    transactions: Mapped[list[CreditCardTransaction]] = relationship(back_populates="import_record")


# ── Savings Transfers ─────────────────────────────────────────────────────────

class SavingsTransfer(Base):
    __tablename__ = "savings_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    from_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    to_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="savings_transfers")
    from_account: Mapped[Account] = relationship(foreign_keys=[from_account_id], back_populates="outgoing_transfers")
    to_account: Mapped[Account] = relationship(foreign_keys=[to_account_id], back_populates="incoming_transfers")


# ── Budget Allocations ────────────────────────────────────────────────────────

class BudgetAllocation(Base):
    __tablename__ = "budget_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = all months
    budgeted_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="budget_allocations")
    category: Mapped[Category] = relationship(back_populates="budget_allocations")


# ── Savings Goals ─────────────────────────────────────────────────────────────

class SavingsGoal(Base):
    __tablename__ = "savings_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    linked_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"))
    current_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="savings_goals")
    linked_account: Mapped[Account | None] = relationship()


# ── Net Worth ────────────────────────────────────────────────────────────────

class ManualAsset(Base):
    __tablename__ = "manual_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    current_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)

    user: Mapped[User] = relationship(back_populates="manual_assets")


class ManualLiability(Base):
    __tablename__ = "manual_liabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    liability_type: Mapped[str] = mapped_column(String(64), nullable=False)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)

    user: Mapped[User] = relationship(back_populates="manual_liabilities")


class NetWorthSnapshot(Base):
    __tablename__ = "net_worth_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_assets: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_liabilities: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    net_worth: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    user: Mapped[User] = relationship(back_populates="net_worth_snapshots")


# ── Forecast Scenarios ────────────────────────────────────────────────────────

class ForecastScenario(Base):
    __tablename__ = "forecast_scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="forecast_scenarios")
    overrides: Mapped[list[ScenarioOverride]] = relationship(back_populates="scenario", cascade="all, delete-orphan")


class ScenarioOverride(Base):
    __tablename__ = "scenario_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(Integer, ForeignKey("forecast_scenarios.id"), nullable=False)
    recurring_item_id: Mapped[int] = mapped_column(Integer, ForeignKey("recurring_items.id"), nullable=False)
    amount_delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    scenario: Mapped[ForecastScenario] = relationship(back_populates="overrides")
    recurring_item: Mapped[RecurringItem] = relationship()


# ── Planned Expenses ─────────────────────────────────────────────────────────

class PlannedDirection(str, PyEnum):
    outflow = "outflow"
    inflow = "inflow"


class PlannedExpense(Base):
    """A one-off, non-recurring event on a future date.

    `direction` makes this usable for money arriving as well as leaving. Before
    it, the forecast forced every row negative, so there was no way to model a
    known one-off inflow -- Dan's April bonus ($38,347.92), Airbnb money from
    family, or an eBay payout, all of which his spreadsheet forecast carries as
    explicit rows. Recurring income belongs in RecurringItem; this is for
    one-time amounts. Defaults to `outflow`, so existing rows are unaffected.

    `card_id` lets an outflow be charged to a card instead of hitting checking
    on `expected_date` directly -- most of Dan's one-off purchases (the Holland
    vacation, e.g.) go on a card, and checking only feels it later, on the
    card's next statement payoff. Nullable: unset means straight to checking
    (or `account_id`), same as before this field existed.
    """
    __tablename__ = "planned_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"))
    card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_cards.id"))
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[PlannedDirection] = mapped_column(
        Enum(PlannedDirection), default=PlannedDirection.outflow, nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    # Settlement. A one-off is a PREDICTION, so once its date passes it has
    # either happened (at some real amount, rarely the estimate) or it hasn't.
    # Leaving it in the list forever made the panel an archive of stale
    # guesses -- Dan's April bonus still sat there in August. `settled_on`
    # marks it closed and `actual_amount` records what really moved, so the
    # estimate can be compared against reality instead of overwritten.
    settled_on: Mapped[date | None] = mapped_column(Date)
    actual_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="planned_expenses")
    account: Mapped[Account | None] = relationship()
    card: Mapped["CreditCard | None"] = relationship()
    category: Mapped[Category | None] = relationship()

    @property
    def is_settled(self) -> bool:
        return self.settled_on is not None


# ── Transaction Rules ─────────────────────────────────────────────────────────

class TransactionRule(Base):
    __tablename__ = "transaction_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    field: Mapped[RuleField] = mapped_column(Enum(RuleField), nullable=False)
    pattern_type: Mapped[RulePatternType] = mapped_column(Enum(RulePatternType), nullable=False)
    pattern: Mapped[str] = mapped_column(String(256), nullable=False)
    action: Mapped[RuleAction] = mapped_column(Enum(RuleAction), nullable=False)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship()
    category: Mapped[Category | None] = relationship()


# ── Password Reset ───────────────────────────────────────────────────────────

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship()


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer)  # not FK — logs survive user deletion
    username: Mapped[str | None] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(256), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    body_summary: Mapped[str | None] = mapped_column(Text)


# ── Day Checkpoints ───────────────────────────────────────────────────────────

class ForecastDayCheckpoint(Base):
    __tablename__ = "forecast_day_checkpoints"
    __table_args__ = (UniqueConstraint("user_id", "account_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship()
    account: Mapped["Account"] = relationship()


# ── Monthly Forecast Snapshots ────────────────────────────────────────────────

class MonthlyForecastSnapshot(Base):
    __tablename__ = "monthly_forecast_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "account_id", "year", "month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    forecasted_open: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    forecasted_close: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    snapshot_taken_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="monthly_forecast_snapshots")
    account: Mapped["Account"] = relationship()


# ── Bank Sync (SimpleFIN) ───────────────────────────────────────────────────

class BankConnectionStatus(str, PyEnum):
    active = "active"
    error = "error"
    disconnected = "disconnected"


class BankConnection(Base):
    __tablename__ = "bank_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    access_url_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[BankConnectionStatus] = mapped_column(Enum(BankConnectionStatus), default=BankConnectionStatus.active, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship()
    links: Mapped[list["BankConnectionAccountLink"]] = relationship(back_populates="connection", cascade="all, delete-orphan")


class BankConnectionAccountLink(Base):
    __tablename__ = "bank_connection_account_links"
    __table_args__ = (UniqueConstraint("connection_id", "simplefin_account_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("bank_connections.id"), nullable=False)
    simplefin_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    simplefin_account_name: Mapped[str] = mapped_column(String(256), nullable=False)
    local_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"))
    local_credit_card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_cards.id"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    connection: Mapped["BankConnection"] = relationship(back_populates="links")
    local_account: Mapped["Account | None"] = relationship()
    local_credit_card: Mapped["CreditCard | None"] = relationship()


class BankSyncRawSnapshot(Base):
    """The full, unmapped SimpleFIN transaction payload -- everything the bank
    actually sends, most of which SimpleFinTransaction discards down to
    id/posted/amount/description. Deliberately NOT a column on Transaction or
    CreditCardTransaction: only written when
    User.debug_capture_raw_bank_data is on, so it stays a debug capture
    Dan can turn off, not a permanent widening of the core transaction
    tables (Dan, 2026-08-14: "a setting to debug rather than a persistent
    feature"). Keyed on (user_id, external_id) with a fresh row on every
    sync overlap, so it never accumulates duplicates for the same
    transaction."""
    __tablename__ = "bank_sync_raw_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── Planned Transfers ────────────────────────────────────────────────────────

class PlannedTransferStatus(str, PyEnum):
    pending = "pending"
    scheduled = "scheduled"
    verified = "verified"


class PlannedTransfer(Base):
    """A one-time, Dan-confirmed transfer plan -- NOT automatic like
    BufferTransferRule. The app never moves money; this tracks a plan Dan
    executes himself in his real bank, and never assumes it happened."""
    __tablename__ = "planned_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    from_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"))
    to_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PlannedTransferStatus] = mapped_column(Enum(PlannedTransferStatus), default=PlannedTransferStatus.pending, nullable=False)
    suggested: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    verified_transaction_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("transactions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship()
    from_account: Mapped["Account | None"] = relationship(foreign_keys=[from_account_id])
    to_account: Mapped["Account"] = relationship(foreign_keys=[to_account_id])
    verified_transaction: Mapped["Transaction | None"] = relationship()


# ── Verification Flags ────────────────────────────────────────────────────────

class VerificationFlag(Base):
    __tablename__ = "verification_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    feature: Mapped[VerificationFeature] = mapped_column(Enum(VerificationFeature), nullable=False)
    # What `reference_id` points at, e.g. "account", "transaction",
    # "card_transaction" -- loose by design, each feature picks its own.
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_id: Mapped[int | None] = mapped_column(Integer)
    # JSON snapshot of exactly what the app displayed at flag time (values,
    # not just ids, so the entry stays meaningful after the underlying data
    # changes). Stored as TEXT and (de)serialized at the API layer -- this
    # codebase has no precedent for a native JSON column type.
    observed_json: Mapped[str] = mapped_column(Text, nullable=False)
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[VerificationFlagStatus] = mapped_column(
        Enum(VerificationFlagStatus), default=VerificationFlagStatus.open, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User"] = relationship()


class MerchantAlias(Base):
    """A user correction to merchant grouping.

    merchant_normalizer's heuristics will mis-group some bank's wording, and
    a wrong grouping nobody can fix is worse than no grouping at all -- the
    totals just quietly lie. `pattern` matches either a raw bank descriptor
    or the normalizer's own output, so a correction can target one specific
    descriptor when two things were wrongly merged, or the merged name when
    it simply needs renaming.
    """
    __tablename__ = "merchant_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pattern: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AppSetting(Base):
    """Server configuration editable from the Settings page, overriding the
    matching .env default at runtime.

    Key/value rather than typed columns because the set of settings changes
    far more often than the schema should: adding one is a constant in
    app_settings.py, not a migration. Values are stored as TEXT and coerced
    on read by the accessor that knows the type.

    `is_secret` rows (currently just the SMTP password) are Fernet-encrypted
    at rest with the same key that protects bank tokens, and the API never
    returns them -- see routers/settings.py. A stolen budget.db therefore
    leaks no more than it did before this table existed.

    Deliberately NOT covering JWT_SECRET, the encryption key itself,
    DATABASE_URL, HOST/PORT or ALLOWED_ORIGINS: those are bootstrap values
    (needed before this table can be read), or rotating them from a web form
    would break the very session doing the rotating. app_settings.EDITABLE is
    the allowlist and the router refuses anything outside it.
    """
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SchedulerRun(Base):
    """One row per scheduled job name -- tracks whether it actually succeeded
    today, independent of whether APScheduler's own trigger fired. The Mac
    sleeping through 5am is not the only way a run goes missing: the trigger
    can fire on time and still fail (no network yet after waking). Two
    distinct failure shapes, two distinct fixes -- see main.py's
    `misfire_grace_time` (catches "didn't fire") and `_scheduler_sweep`
    (catches "fired but failed, or fired never at all") -- both consult this
    table before writing to it."""
    __tablename__ = "scheduler_runs"

    job_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
