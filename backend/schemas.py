from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator
from backend.models import AccountType, CategoryType, RecurringType, ImportFormat, UserRole, RecurringFrequency


# ── Auth ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: UserRole = UserRole.admin
    created_at: datetime


class UserAdminCreate(BaseModel):
    username: str
    password: str
    display_name: str
    role: UserRole = UserRole.viewer


class UserAdminUpdate(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    display_name: Optional[str] = None


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class LoginRequest(BaseModel):
    username: str
    password: str


# ── Accounts ──────────────────────────────────────────────────────────────────

class AccountCreate(BaseModel):
    name: str
    type: AccountType
    current_balance: Decimal = Decimal("0")
    currency: str = "USD"
    notes: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    current_balance: Optional[Decimal] = None
    low_balance_threshold: Optional[Decimal] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: AccountType
    current_balance: Decimal
    currency: str
    low_balance_threshold: Optional[Decimal]
    is_active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# ── Categories ────────────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str
    type: CategoryType
    parent_id: Optional[int] = None
    color: str = "#6366f1"
    icon: Optional[str] = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    parent_id: Optional[int] = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: Optional[int]
    name: str
    type: CategoryType
    color: str
    icon: Optional[str]
    sort_order: int
    children: list["CategoryOut"] = []


CategoryOut.model_rebuild()


# ── Recurring Items ───────────────────────────────────────────────────────────

class RecurringCreate(BaseModel):
    name: str
    amount: Decimal
    type: RecurringType
    frequency: RecurringFrequency = RecurringFrequency.monthly
    account_id: int
    category_id: Optional[int] = None
    day_of_month: int  # 1-31; 0 = last day
    month_of_year: Optional[int] = None  # 1-12 for yearly items
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None

    @field_validator("day_of_month")
    @classmethod
    def validate_day(cls, v: int) -> int:
        if not (0 <= v <= 31):
            raise ValueError("day_of_month must be 0 (last day) or 1-31")
        return v


class RecurringUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[Decimal] = None
    frequency: Optional[RecurringFrequency] = None
    category_id: Optional[int] = None
    day_of_month: Optional[int] = None
    month_of_year: Optional[int] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class RecurringOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int
    category_id: Optional[int]
    name: str
    amount: Decimal
    type: RecurringType
    frequency: RecurringFrequency
    day_of_month: int
    month_of_year: Optional[int]
    start_date: date
    end_date: Optional[date]
    is_active: bool
    notes: Optional[str]


# ── Transactions ──────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    account_id: int
    category_id: Optional[int] = None
    recurring_item_id: Optional[int] = None
    date: date
    amount: Decimal  # positive=credit, negative=debit
    description: str
    notes: Optional[str] = None


class TransactionUpdate(BaseModel):
    category_id: Optional[int] = None
    date: Optional[date] = None
    amount: Optional[Decimal] = None
    description: Optional[str] = None
    notes: Optional[str] = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int
    category_id: Optional[int]
    recurring_item_id: Optional[int]
    date: date
    amount: Decimal
    description: str
    notes: Optional[str]
    is_actual: bool
    source: str
    created_at: datetime


# ── Forecast ──────────────────────────────────────────────────────────────────

class ForecastTransaction(BaseModel):
    name: str
    amount: Decimal
    type: str  # "income" | "expense"
    category_name: Optional[str]
    is_actual: bool
    recurring_item_id: Optional[int] = None
    transaction_id: Optional[int] = None


class ForecastEntry(BaseModel):
    date: date
    projected_balance: Decimal
    transactions: list[ForecastTransaction]


class QuarterSummary(BaseModel):
    quarter: int
    year: int
    open_balance: Decimal
    close_balance: Decimal
    total_income: Decimal
    total_expenses: Decimal
    net: Decimal
    days: list[ForecastEntry]


# ── Budget ────────────────────────────────────────────────────────────────────

class BudgetAllocationCreate(BaseModel):
    category_id: int
    year: int
    month: int  # 0 = all months, 1-12 = specific month
    budgeted_amount: Decimal


class BudgetAllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category_id: int
    year: int
    month: int
    budgeted_amount: Decimal


class BudgetOverviewRow(BaseModel):
    category_id: int
    category_name: str
    parent_id: Optional[int]
    budgeted: Decimal
    actual_checking: Decimal
    actual_cards: Decimal
    actual_total: Decimal
    variance: Decimal  # budgeted - actual (positive = under budget)
    rollover_enabled: bool = False
    rollover_balance: Decimal = Decimal("0")


class CategoryRolloverUpdate(BaseModel):
    rollover_enabled: bool


class RecurringSuggestion(BaseModel):
    description: str
    median_amount: Decimal
    frequency: RecurringFrequency
    occurrences: int


class MonthlySummary(BaseModel):
    year: int
    month: int
    top_category: Optional[str]
    top_category_amount: Optional[Decimal]
    mom_delta: Optional[Decimal]  # current - prior month total spending
    mom_delta_pct: Optional[Decimal]  # percentage change, None if prior month was zero
    net_cashflow: Decimal  # total credits - total debits
    text: str  # plain-English narrative


# ── Credit Cards ──────────────────────────────────────────────────────────────

class CreditCardCreate(BaseModel):
    name: str
    last_four: Optional[str] = None
    credit_limit: Decimal
    statement_day: int
    due_day: int
    current_balance: Decimal = Decimal("0")
    balance_due: Decimal = Decimal("0")
    notes: Optional[str] = None


class CreditCardUpdate(BaseModel):
    name: Optional[str] = None
    last_four: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    statement_day: Optional[int] = None
    due_day: Optional[int] = None
    current_balance: Optional[Decimal] = None
    balance_due: Optional[Decimal] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class CreditCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    last_four: Optional[str]
    credit_limit: Decimal
    statement_day: int
    due_day: int
    current_balance: Decimal
    balance_due: Decimal
    is_active: bool
    notes: Optional[str]
    utilization_pct: float = 0.0
    updated_at: datetime


class CreditCardPaymentCreate(BaseModel):
    checking_account_id: int
    date: date
    amount: Decimal
    notes: Optional[str] = None


class CreditCardPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    card_id: int
    checking_account_id: int
    date: date
    amount: Decimal
    notes: Optional[str]
    created_at: datetime


class CardTransactionCreate(BaseModel):
    date: date
    amount: Decimal  # positive=charge, negative=refund
    merchant: str
    description: Optional[str] = None
    category_id: Optional[int] = None


class CardTransactionUpdate(BaseModel):
    category_id: Optional[int] = None
    merchant: Optional[str] = None
    description: Optional[str] = None


class CardTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    card_id: int
    category_id: Optional[int]
    date: date
    amount: Decimal
    merchant: str
    description: Optional[str]
    source: str
    created_at: datetime


# ── Spending Analysis ─────────────────────────────────────────────────────────

class SpendingSubCategory(BaseModel):
    category_id: int
    category_name: str
    color: str
    budgeted: Decimal
    actual: Decimal
    variance: Decimal
    breakdown_by_source: dict[str, Decimal]  # {"Chase Sapphire": 834.00, "Checking": 70.00}


class SpendingTopLevel(BaseModel):
    category_id: int
    category_name: str
    color: str
    budgeted: Decimal
    actual: Decimal
    variance: Decimal
    children: list[SpendingSubCategory]


class SpendingOverview(BaseModel):
    start_date: date
    end_date: date
    categories: list[SpendingTopLevel]
    total_budgeted: Decimal
    total_actual: Decimal
    total_variance: Decimal


class MonthlySpendingEntry(BaseModel):
    month: str  # "2026-04"
    total: Decimal
    checking: Decimal
    cards: Decimal


class CategoryMonthlyTotal(BaseModel):
    category_id: int
    category_name: str
    color: str
    total: Decimal


class MonthlyCategoryRow(BaseModel):
    month: str
    total: Decimal
    categories: list[CategoryMonthlyTotal]


# ── Import ────────────────────────────────────────────────────────────────────

class ImportPreviewRow(BaseModel):
    row_index: int
    date: date
    description: str
    amount: Decimal
    category_id: Optional[int]
    category_name: Optional[str]
    needs_review: bool


class ImportPreviewStats(BaseModel):
    total: int
    categorized: int
    needs_review: int


class ImportPreviewResponse(BaseModel):
    format: ImportFormat
    rows: list[ImportPreviewRow]
    stats: ImportPreviewStats


class ImportConfirmRow(BaseModel):
    date: date
    description: str
    amount: Decimal
    category_id: Optional[int] = None


class ImportConfirmRequest(BaseModel):
    account_id: Optional[int] = None
    card_id: Optional[int] = None
    rows: list[ImportConfirmRow]


class ImportConfirmResponse(BaseModel):
    imported: int
    skipped_duplicates: int


# ── Admin / Audit Log ─────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    timestamp: datetime
    username: Optional[str]
    method: str
    path: str
    status_code: int
    duration_ms: int
    body_summary: Optional[str]


class AuditLogPage(BaseModel):
    total: int
    items: list[AuditLogOut]


# ── Analytics ─────────────────────────────────────────────────────────────────

class AvailableToSpend(BaseModel):
    monthly_income: Decimal
    committed_expenses: Decimal
    spent_this_month: Decimal
    available: Decimal


class YearlyTrendEntry(BaseModel):
    year: int
    months: dict[str, Decimal]


class RollingMonthEntry(BaseModel):
    month: str  # "YYYY-MM"
    total: Decimal


# ── Savings Goals ─────────────────────────────────────────────────────────────

class SavingsGoalCreate(BaseModel):
    name: str
    target_amount: Decimal
    target_date: Optional[date] = None
    linked_account_id: Optional[int] = None
    current_amount: Decimal = Decimal("0")
    notes: Optional[str] = None


class SavingsGoalUpdate(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[Decimal] = None
    target_date: Optional[date] = None
    linked_account_id: Optional[int] = None
    current_amount: Optional[Decimal] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class SavingsGoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    target_amount: Decimal
    target_date: Optional[date] = None
    linked_account_id: Optional[int] = None
    current_amount: Decimal
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime
    percent_complete: float = 0.0
    monthly_needed: Optional[Decimal] = None
    months_remaining: Optional[int] = None
