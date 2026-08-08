from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator
from backend.models import AccountType, CategoryType, RecurringType, ImportFormat, UserRole, RecurringFrequency, RuleField, RulePatternType, RuleAction


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
    email: Optional[str] = None
    ss_gross_per_paycheck: Optional[Decimal] = None
    ss_wage_base: Optional[Decimal] = None
    ss_bonus_ytd: Optional[Decimal] = None
    tax_filing_status: Optional[str] = None
    tax_state: Optional[str] = None
    annual_salary: Optional[Decimal] = None
    other_income: Optional[Decimal] = None
    federal_withholding_ytd: Optional[Decimal] = None
    state_withholding_ytd: Optional[Decimal] = None
    itemized_mortgage_interest: Optional[Decimal] = None
    itemized_donations: Optional[Decimal] = None
    itemized_salt: Optional[Decimal] = None
    itemized_property_tax: Optional[Decimal] = None
    itemized_other: Optional[Decimal] = None
    recovery_code_created_at: Optional[datetime] = None


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    ss_gross_per_paycheck: Optional[Decimal] = None
    ss_wage_base: Optional[Decimal] = None
    ss_bonus_ytd: Optional[Decimal] = None
    tax_filing_status: Optional[str] = None
    tax_state: Optional[str] = None
    annual_salary: Optional[Decimal] = None
    other_income: Optional[Decimal] = None
    federal_withholding_ytd: Optional[Decimal] = None
    state_withholding_ytd: Optional[Decimal] = None
    itemized_mortgage_interest: Optional[Decimal] = None
    itemized_donations: Optional[Decimal] = None
    itemized_salt: Optional[Decimal] = None
    itemized_property_tax: Optional[Decimal] = None
    itemized_other: Optional[Decimal] = None


class UserPasswordChange(BaseModel):
    current_password: str
    new_password: str


class DeleteAccountRequest(BaseModel):
    password: str


class UserAdminCreate(BaseModel):
    username: str
    password: str
    display_name: str
    role: UserRole = UserRole.viewer
    linked_to_user_id: Optional[int] = None


class UserAdminUpdate(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    display_name: Optional[str] = None
    linked_to_user_id: Optional[int] = None


class AdminPasswordReset(BaseModel):
    new_password: str


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    linked_to_user_id: Optional[int] = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class LoginRequest(BaseModel):
    username: str
    password: str


class ForgotPasswordRequest(BaseModel):
    username: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ResetPasswordWithCodeRequest(BaseModel):
    username: str
    code: str
    new_password: str


class RecoveryCodeOut(BaseModel):
    code: str
    created_at: datetime


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
    interest_rate: Optional[Decimal] = None
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
    interest_rate: Optional[Decimal] = None
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
    tax_deductible: Optional[bool] = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: Optional[int]
    name: str
    type: CategoryType
    color: str
    icon: Optional[str]
    sort_order: int
    tax_deductible: bool = False
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
    card_id: Optional[int] = None
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
    type: Optional[RecurringType] = None
    frequency: Optional[RecurringFrequency] = None
    account_id: Optional[int] = None
    category_id: Optional[int] = None
    card_id: Optional[int] = None
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
    card_id: Optional[int] = None
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
    recurring_item_id: Optional[int] = None


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
    type: str  # "income" | "expense" | "credit_card_payment"
    category_name: Optional[str]
    is_actual: bool
    is_planned: bool = False
    is_cc_payment: bool = False
    is_transfer: bool = False
    recurring_item_id: Optional[int] = None
    transaction_id: Optional[int] = None


class ForecastEntry(BaseModel):
    date: date
    projected_balance: Decimal
    transactions: list[ForecastTransaction]


class ForecastRisk(BaseModel):
    at_risk: bool
    date: Optional[date]
    amount: Optional[Decimal]
    threshold: Decimal
    transfer_triggered: bool = False
    transfer_date: Optional[date] = None
    transfer_amount: Optional[Decimal] = None
    transfer_from: Optional[str] = None
    action_threshold: Optional[Decimal] = None


class BufferTransferRuleCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    action_threshold: Decimal
    target_floor: Decimal
    increment: Decimal = Decimal("1000.00")
    check_day: int = 1

    @field_validator("target_floor")
    @classmethod
    def floor_above_threshold(cls, v, info):
        threshold = info.data.get("action_threshold")
        if threshold is not None and v <= threshold:
            raise ValueError("target_floor must be greater than action_threshold")
        return v

    @field_validator("increment")
    @classmethod
    def increment_positive(cls, v):
        if v <= 0:
            raise ValueError("increment must be greater than 0")
        return v

    @field_validator("check_day")
    @classmethod
    def check_day_in_range(cls, v):
        if not (1 <= v <= 28):
            raise ValueError("check_day must be between 1 and 28")
        return v


class BufferTransferRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    from_account_id: int
    to_account_id: int
    action_threshold: Decimal
    target_floor: Decimal
    increment: Decimal
    check_day: int
    is_active: bool


class QuarterSummary(BaseModel):
    quarter: int
    year: int
    open_balance: Decimal
    close_balance: Decimal
    total_income: Decimal
    total_expenses: Decimal
    net: Decimal
    days: list[ForecastEntry]
    quarter_end_checkpoint: Optional[Decimal] = None


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
    next_payment_date: Optional[date] = None
    monthly_spend_estimate: Optional[Decimal] = None
    pending_charges: Decimal = Decimal("0")
    notes: Optional[str] = None


class CreditCardUpdate(BaseModel):
    name: Optional[str] = None
    last_four: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    statement_day: Optional[int] = None
    due_day: Optional[int] = None
    current_balance: Optional[Decimal] = None
    balance_due: Optional[Decimal] = None
    next_payment_date: Optional[date] = None
    monthly_spend_estimate: Optional[Decimal] = None
    pending_charges: Optional[Decimal] = None
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
    next_payment_date: Optional[date]
    monthly_spend_estimate: Optional[Decimal]
    pending_charges: Decimal
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


class CreditCardDueEntry(BaseModel):
    card_id: int
    card_name: str
    due_day: int
    next_due_date: date
    balance_due: Decimal
    current_balance: Decimal


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
    is_transfer: bool = False
    suggested_recurring_item_id: Optional[int] = None
    suggested_recurring_item_name: Optional[str] = None


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
    notes: Optional[str] = None
    recurring_item_id: Optional[int] = None
    is_transfer: bool = False


class ImportConfirmRequest(BaseModel):
    account_id: Optional[int] = None
    card_id: Optional[int] = None
    rows: list[ImportConfirmRow]


class ImportConfirmResponse(BaseModel):
    imported: int
    skipped_duplicates: int


# ── Forecast Day Checkpoints ──────────────────────────────────────────────────

class ForecastDayCheckpointUpsert(BaseModel):
    account_id: int
    actual_balance: Decimal
    note: Optional[str] = None


class ForecastDayCheckpointOut(BaseModel):
    id: int
    account_id: int
    date: date
    actual_balance: Decimal
    note: Optional[str]
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


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


# ── Net Worth ─────────────────────────────────────────────────────────────────

class ManualAssetCreate(BaseModel):
    name: str
    asset_type: str
    current_value: Decimal
    as_of_date: date


class ManualAssetUpdate(BaseModel):
    name: Optional[str] = None
    asset_type: Optional[str] = None
    current_value: Optional[Decimal] = None
    as_of_date: Optional[date] = None


class ManualAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    asset_type: str
    current_value: Decimal
    as_of_date: date


class ManualLiabilityCreate(BaseModel):
    name: str
    liability_type: str
    current_balance: Decimal
    as_of_date: date


class ManualLiabilityUpdate(BaseModel):
    name: Optional[str] = None
    liability_type: Optional[str] = None
    current_balance: Optional[Decimal] = None
    as_of_date: Optional[date] = None


class ManualLiabilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    liability_type: str
    current_balance: Decimal
    as_of_date: date


class NetWorthTotals(BaseModel):
    total_assets: Decimal
    account_balances: Decimal
    card_balances: Decimal
    total_liabilities: Decimal
    net_worth: Decimal


class NetWorthSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    snapshot_date: date
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal


# ── Forecast Scenarios ────────────────────────────────────────────────────────

class ScenarioCreate(BaseModel):
    name: str


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None


class ScenarioOverrideCreate(BaseModel):
    recurring_item_id: int
    amount_delta: Decimal


class ScenarioOverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recurring_item_id: int
    amount_delta: Decimal


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    created_at: datetime
    overrides: list[ScenarioOverrideOut] = []


# ── Planned Expenses ─────────────────────────────────────────────────────────

class PlannedExpenseCreate(BaseModel):
    name: str
    amount: Decimal
    expected_date: date
    notes: Optional[str] = None
    category_id: Optional[int] = None
    account_id: Optional[int] = None


class PlannedExpenseUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[Decimal] = None
    expected_date: Optional[date] = None
    notes: Optional[str] = None
    category_id: Optional[int] = None
    account_id: Optional[int] = None


class PlannedExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    amount: Decimal
    expected_date: date
    notes: Optional[str]
    category_id: Optional[int]
    account_id: Optional[int]
    created_at: datetime


# ── Sankey ────────────────────────────────────────────────────────────────────

class SankeyNode(BaseModel):
    id: str
    name: str
    type: str  # "income" or "expense"


class SankeyLink(BaseModel):
    source: str
    target: str
    value: Decimal


class SankeyResponse(BaseModel):
    nodes: list[SankeyNode]
    links: list[SankeyLink]


# ── Tax Summary ───────────────────────────────────────────────────────────────

class TaxSummaryRow(BaseModel):
    date: date
    description: str
    amount: Decimal
    category_name: str


class TaxSummaryResponse(BaseModel):
    year: int
    rows: list[TaxSummaryRow]
    total_amount: Decimal


# ── Merchant spending ─────────────────────────────────────────────────────────

class MerchantSpendingEntry(BaseModel):
    name: str
    total: Decimal
    count: int


class WeeklyDigestCategory(BaseModel):
    category_id: int
    category_name: str
    total: Decimal


class WeeklyDigest(BaseModel):
    week_start: date
    week_end: date
    total_spent: Decimal
    categories: list[WeeklyDigestCategory]
    top_merchants: list[MerchantSpendingEntry]
    risk: ForecastRisk


# ── Reconciliation ────────────────────────────────────────────────────────────

class ReconcileMatchedItem(BaseModel):
    transaction_id: int
    date: date
    description: str
    actual_amount: Decimal
    recurring_item_id: Optional[int] = None
    card_id: Optional[int] = None
    recurring_name: str
    expected_amount: Decimal
    variance: Decimal


class ReconcileUnmatchedRecurring(BaseModel):
    recurring_item_id: int
    name: str
    expected_amount: Decimal
    expected_day: int


class ReconcileUnmatchedTransaction(BaseModel):
    transaction_id: int
    date: date
    description: str
    amount: Decimal


class ReconcileResponse(BaseModel):
    account_id: int
    year: int
    month: int
    matched: list[ReconcileMatchedItem]
    unmatched_recurring: list[ReconcileUnmatchedRecurring]
    unmatched_transactions: list[ReconcileUnmatchedTransaction]


class MonthlyForecastSummary(BaseModel):
    account_id: int
    year: int
    month: int
    forecasted_open: Decimal
    forecasted_close: Decimal
    snapshot_taken_at: Optional[datetime]
    actual_close: Optional[Decimal]
    delta: Optional[Decimal]
    reconcile: ReconcileResponse






# ── Transaction Rules ─────────────────────────────────────────────────────────

class TransactionRuleCreate(BaseModel):
    name: str
    field: RuleField
    pattern_type: RulePatternType
    pattern: str
    action: RuleAction
    category_id: Optional[int] = None
    priority: int = 0


class TransactionRuleUpdate(BaseModel):
    name: Optional[str] = None
    field: Optional[RuleField] = None
    pattern_type: Optional[RulePatternType] = None
    pattern: Optional[str] = None
    action: Optional[RuleAction] = None
    category_id: Optional[int] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class TransactionRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    field: RuleField
    pattern_type: RulePatternType
    pattern: str
    action: RuleAction
    category_id: Optional[int]
    priority: int
    is_active: bool
    created_at: datetime


class RuleTestRequest(BaseModel):
    pattern: str
    pattern_type: RulePatternType
    description: str


class RuleTestResponse(BaseModel):
    matched: bool
