from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
from enum import Enum as PyEnum
from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Integer,
    Numeric, String, Text, func,
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


class RecurringType(str, PyEnum):
    income = "income"
    expense = "expense"


class TransactionSource(str, PyEnum):
    manual = "manual"
    csv_import = "csv_import"
    forecast_generated = "forecast_generated"


class CardTransactionSource(str, PyEnum):
    manual = "manual"
    csv_import = "csv_import"


class ImportFormat(str, PyEnum):
    chase = "chase"
    amex = "amex"
    apple = "apple"
    generic = "generic"


class UserRole(str, PyEnum):
    admin = "admin"
    viewer = "viewer"


class RecurringFrequency(str, PyEnum):
    monthly = "monthly"
    yearly = "yearly"
    weekly = "weekly"


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

    accounts: Mapped[list[Account]] = relationship(back_populates="user", cascade="all, delete-orphan")
    categories: Mapped[list[Category]] = relationship(back_populates="user", cascade="all, delete-orphan")
    recurring_items: Mapped[list[RecurringItem]] = relationship(back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="user", cascade="all, delete-orphan")
    credit_cards: Mapped[list[CreditCard]] = relationship(back_populates="user", cascade="all, delete-orphan")
    savings_transfers: Mapped[list[SavingsTransfer]] = relationship(back_populates="user", cascade="all, delete-orphan")
    budget_allocations: Mapped[list[BudgetAllocation]] = relationship(back_populates="user", cascade="all, delete-orphan")
    savings_goals: Mapped[list[SavingsGoal]] = relationship(back_populates="user", cascade="all, delete-orphan")
    manual_assets: Mapped[list[ManualAsset]] = relationship(back_populates="user", cascade="all, delete-orphan")
    manual_liabilities: Mapped[list[ManualLiability]] = relationship(back_populates="user", cascade="all, delete-orphan")
    net_worth_snapshots: Mapped[list[NetWorthSnapshot]] = relationship(back_populates="user", cascade="all, delete-orphan")
    forecast_scenarios: Mapped[list[ForecastScenario]] = relationship(back_populates="user", cascade="all, delete-orphan")
    planned_expenses: Mapped[list[PlannedExpense]] = relationship(back_populates="user", cascade="all, delete-orphan")


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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="account")
    recurring_items: Mapped[list[RecurringItem]] = relationship(back_populates="account")
    outgoing_transfers: Mapped[list[SavingsTransfer]] = relationship(foreign_keys="SavingsTransfer.from_account_id", back_populates="from_account")
    incoming_transfers: Mapped[list[SavingsTransfer]] = relationship(foreign_keys="SavingsTransfer.to_account_id", back_populates="to_account")
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
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="recurring_items")
    account: Mapped[Account] = relationship(back_populates="recurring_items")
    category: Mapped[Category | None] = relationship(back_populates="recurring_items")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="recurring_item")


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

class PlannedExpense(Base):
    __tablename__ = "planned_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="planned_expenses")
    category: Mapped[Category | None] = relationship()


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
