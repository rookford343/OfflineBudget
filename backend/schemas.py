from datetime import date, date as date_type, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator
from backend.models import AccountType, CategoryType, RecurringType, ImportFormat, UserRole, RecurringFrequency, RuleField, RulePatternType, RuleAction, BankConnectionStatus, PlannedTransferStatus, VerificationFeature, VerificationFlagStatus, PlannedDirection


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
    ss_withheld_ytd: Optional[Decimal] = None
    ss_withheld_ytd_as_of: Optional[date] = None
    debug_capture_raw_bank_data: bool = False
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
    transfer_increment: Optional[Decimal] = None
    savings_strategy: Optional[str] = None



class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    ss_gross_per_paycheck: Optional[Decimal] = None
    ss_wage_base: Optional[Decimal] = None
    ss_bonus_ytd: Optional[Decimal] = None
    ss_withheld_ytd: Optional[Decimal] = None
    ss_withheld_ytd_as_of: Optional[date] = None
    debug_capture_raw_bank_data: Optional[bool] = None
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
    transfer_increment: Optional[Decimal] = None
    savings_strategy: Optional[str] = None

    @field_validator("savings_strategy")
    @classmethod
    def _known_strategy(cls, v):
        # An unrecognized value would fall through to the save_monthly branch
        # and silently change the headline number, so reject it at the edge.
        if v is not None and v not in ("save_monthly", "pull_from_savings"):
            raise ValueError("savings_strategy must be save_monthly or pull_from_savings")
        return v


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
    is_emergency_fund: bool = False
    notes: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    current_balance: Optional[Decimal] = None
    low_balance_threshold: Optional[Decimal] = None
    interest_rate: Optional[Decimal] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    is_emergency_fund: Optional[bool] = None


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
    is_emergency_fund: bool = False
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
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None
    include_in_forecast: Optional[bool] = None
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
    include_in_forecast: bool = True
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
    external_id: Optional[str] = None
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
    # True only on the payoff of an already-statemented balance -- the amount
    # is known and the date is fixed, so Dan treats it as locked in rather
    # than forecast ("8/25 is locked in and typically does not change unless a
    # refund happens", 2026-08-14). Estimated payoffs for later cycles are
    # is_cc_payment but NOT locked: they are still in flux.
    is_cc_locked: bool = False
    is_transfer: bool = False
    is_planned_transfer: bool = False
    recurring_item_id: Optional[int] = None
    transaction_id: Optional[int] = None
    # True on a projected paycheck that includes the SS wage-base boost. Lets
    # the frontend show the real crossing date instead of re-deriving one --
    # see forecast_engine.py's ss_boost comment for why a client-side estimate
    # drifted from this by two months.
    is_ss_boosted: bool = False


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
    suggested_transfer_amount: Optional[Decimal] = None
    suggested_transfer_date: Optional[date] = None
    suggested_transfer_from_account_id: Optional[int] = None
    suggested_transfer_already_planned: bool = False


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
    # Needed so the Budget page can drop income rows. Without it "Income" and
    # "Salary / Wages" showed as $12,133.26 budget lines apiece.
    category_type: str = "expense"
    budgeted: Decimal
    actual_checking: Decimal
    actual_cards: Decimal
    actual_total: Decimal
    variance: Decimal  # budgeted - actual (positive = under budget)
    rollover_enabled: bool = False
    rollover_balance: Decimal = Decimal("0")


class BillAmountOverrideCreate(BaseModel):
    recurring_item_id: int
    due_date: date
    actual_amount: Decimal
    notes: Optional[str] = None


class BillAmountOverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recurring_item_id: int
    recurring_item_name: str = ""
    due_date: date
    actual_amount: Decimal
    projected_amount: Decimal = Decimal("0")
    notes: Optional[str] = None


class RecurringLinkPattern(BaseModel):
    """Attach a detected bank descriptor to an existing recurring item."""
    pattern: str
    field: str = "description"          # description | merchant
    pattern_type: str = "contains"      # contains | startswith | regex
    backfill: bool = True

    @field_validator("pattern")
    @classmethod
    def _pattern_not_blank(cls, v: str) -> str:
        # A blank pattern would match every transaction and silently recategorize
        # the whole ledger on backfill.
        if not v or not v.strip():
            raise ValueError("pattern must not be empty")
        return v.strip()


class RecurringLinkResult(BaseModel):
    rule_id: Optional[int] = None
    rule_created: bool = False
    linked_checking: int = 0
    linked_card: int = 0
    category_name: Optional[str] = None


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
    payment_sent_pending_sync: bool = False
    payment_sent_amount: Optional[Decimal] = None
    pending_charges_updated_at: Optional[datetime] = None
    balance_due_updated_at: Optional[datetime] = None


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
    external_id: Optional[str] = None
    created_at: datetime


class RawSnapshotOut(BaseModel):
    external_id: str
    raw_json: str
    captured_at: datetime


class MerchantAliasCreate(BaseModel):
    pattern: str
    display_name: str


class MerchantAliasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pattern: str
    display_name: str


class EnvStatusEntry(BaseModel):
    """An env-only setting's name and whether it's set. Never its value."""
    key: str
    configured: bool


class AppSettingsOut(BaseModel):
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_from: Optional[str] = None
    daily_summary_hour: Optional[int] = None
    weekly_digest_day: Optional[str] = None
    weekly_digest_enabled: Optional[bool] = None
    report_recipients: Optional[str] = None
    # Presence flag, not the secret -- see routers/settings.py.
    smtp_pass_set: bool = False
    encryption_configured: bool = False
    env_status: list[EnvStatusEntry] = []


class AppSettingsUpdate(BaseModel):
    """All optional: PATCH semantics, exclude_unset distinguishes "clear this"
    (explicit null/"") from "leave it alone" (absent)."""
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    smtp_from: Optional[str] = None
    daily_summary_hour: Optional[int] = None
    weekly_digest_day: Optional[str] = None
    weekly_digest_enabled: Optional[bool] = None
    report_recipients: Optional[str] = None

    @field_validator("daily_summary_hour")
    @classmethod
    def _valid_hour(cls, v):
        if v is not None and not (0 <= v <= 23):
            raise ValueError("daily_summary_hour must be between 0 and 23")
        return v

    @field_validator("weekly_digest_day")
    @classmethod
    def _valid_day(cls, v):
        if v is None or v == "":
            return v
        allowed = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        if v.strip().lower() not in allowed:
            raise ValueError(f"weekly_digest_day must be one of {sorted(allowed)}")
        return v.strip().lower()

    @field_validator("report_recipients")
    @classmethod
    def _valid_recipients(cls, v):
        """Catch a typo'd address at save time rather than discovering it as a
        silent non-delivery a day later."""
        if not v or not v.strip():
            return v
        bad = [p.strip() for p in v.split(",") if p.strip() and "@" not in p]
        if bad:
            raise ValueError(f"Not valid email addresses: {', '.join(bad)}")
        return v


class SchedulerRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    job_name: str
    last_attempt_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None


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
    # Spending you can decide about this month, vs commitments made before it
    # started. Without the split the page headlines Mortgage and Tithe as if
    # they were choices and buries the part that is actually steerable.
    is_discretionary: bool = False
    children: list[SpendingSubCategory]


class SpendingOverview(BaseModel):
    start_date: date
    end_date: date
    categories: list[SpendingTopLevel]
    total_budgeted: Decimal
    total_actual: Decimal
    total_variance: Decimal
    discretionary_actual: Decimal = Decimal("0")
    discretionary_budgeted: Decimal = Decimal("0")
    fixed_actual: Decimal = Decimal("0")


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
    # Provider transaction id when the row came from a bank sync; None for
    # CSV/OFX and manual rows.
    external_id: Optional[str] = None


class ImportConfirmRequest(BaseModel):
    account_id: Optional[int] = None
    card_id: Optional[int] = None
    rows: list[ImportConfirmRow]


class ImportConfirmResponse(BaseModel):
    imported: int
    skipped_duplicates: int


# ── Bank Sync (SimpleFIN) ────────────────────────────────────────────────────

class BankConnectionAccountOut(BaseModel):
    """One SimpleFIN account discovered on the connection, for the mapping UI."""
    simplefin_account_id: str
    name: str
    org_name: str
    balance: Decimal
    currency: str


class BankConnectionConnectRequest(BaseModel):
    setup_token: str


class BankConnectionConnectResponse(BaseModel):
    connection_id: int
    accounts: list[BankConnectionAccountOut]


class BankConnectionLinkRequest(BaseModel):
    simplefin_account_id: str
    simplefin_account_name: str
    local_account_id: Optional[int] = None
    local_credit_card_id: Optional[int] = None


class BankConnectionLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    simplefin_account_id: str
    simplefin_account_name: str
    local_account_id: Optional[int]
    local_credit_card_id: Optional[int]
    last_synced_at: Optional[datetime]


class BankConnectionStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: BankConnectionStatus
    last_synced_at: Optional[datetime]
    last_error: Optional[str]
    links: list[BankConnectionLinkOut]


class BankSyncNowResponse(BaseModel):
    synced_connections: int
    errors: list[str]
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
    card_id: Optional[int] = None
    direction: PlannedDirection = PlannedDirection.outflow
    # Funding source for a purchase paid out of savings rather than the
    # month's cash flow. Derived into a transfer by the forecast, so it can
    # never drift from the purchase date the way a separate record can.
    funding_account_id: Optional[int] = None
    funding_amount: Optional[Decimal] = None
    funding_lead_days: int = 0


class PlannedExpenseUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[Decimal] = None
    expected_date: Optional[date] = None
    notes: Optional[str] = None
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    card_id: Optional[int] = None
    direction: Optional[PlannedDirection] = None
    funding_account_id: Optional[int] = None
    funding_amount: Optional[Decimal] = None
    funding_lead_days: Optional[int] = None


class PlannedExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    amount: Decimal
    expected_date: date
    notes: Optional[str]
    category_id: Optional[int]
    account_id: Optional[int]
    card_id: Optional[int] = None
    direction: PlannedDirection
    funding_account_id: Optional[int] = None
    funding_amount: Optional[Decimal] = None
    funding_lead_days: int = 0
    settled_on: Optional[date] = None
    actual_amount: Optional[Decimal] = None
    is_settled: bool = False
    created_at: datetime


class PlannedExpenseSettle(BaseModel):
    """Close out a one-off once its date has passed.

    `actual_amount` is optional because the two real outcomes differ: it
    happened (record what actually moved, which is rarely the estimate) or it
    didn't happen at all (settle with nothing, keeping the row as a record of
    a prediction that missed rather than deleting the evidence)."""
    actual_amount: Optional[Decimal] = None
    settled_on: Optional[date] = None


# ── Planned Transfers ────────────────────────────────────────────────────────

class PlannedTransferCreate(BaseModel):
    from_account_id: Optional[int] = None
    to_account_id: int
    amount: Decimal
    target_date: date
    suggested: bool = False
    notes: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be greater than 0")
        return v


class PlannedTransferUpdate(BaseModel):
    """`status` is deliberately absent.

    The only sanctioned status transitions are the dedicated
    /mark-scheduled endpoint and the auto-verifier. Letting a plain PATCH
    set an arbitrary status (notably verified -> pending) would silently
    re-enable forecast injection for a transfer whose real transaction is
    already in actuals, double-counting it.
    """
    from_account_id: Optional[int] = None
    to_account_id: Optional[int] = None
    amount: Optional[Decimal] = None
    target_date: Optional[date] = None
    notes: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("amount must be greater than 0")
        return v


class PlannedTransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    from_account_id: Optional[int]
    to_account_id: int
    amount: Decimal
    target_date: date
    status: PlannedTransferStatus
    suggested: bool
    notes: Optional[str]
    verified_transaction_id: Optional[int]
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


class SpendingLineItem(BaseModel):
    """One row behind a spending total. Deliberately spans both checking and
    card sources so the drill-down shows exactly what composes the bar --
    transfers and card payoffs are already excluded upstream."""
    date: date_type
    description: str
    amount: Decimal
    source: str  # "checking" | "card"


class WeeklyDigestCategory(BaseModel):
    category_id: int
    category_name: str
    total: Decimal


class CardSnapshot(BaseModel):
    id: int
    name: str
    current_balance: Decimal
    pending_charges: Decimal
    credit_limit: Decimal
    utilization_pct: float
    due_day: int


class BudgetSnapshot(BaseModel):
    as_of: date
    leftover: Decimal
    left_to_spend: Decimal
    left_to_spend_weekly: Decimal
    # Decision support for the two thresholds. Weekly spendable below zero
    # means this month's savings transfer gets skipped; safety margin below
    # zero means money has to come back out of savings.
    savings_budget: Decimal
    left_to_spend_if_savings_skipped: Decimal
    savings_pull_needed: Decimal
    # Bonus-as-reserve: how big the gap is this month, what covering it for
    # the rest of the year would take, and whether savings can absorb that.
    shortfall_this_month: Decimal
    reserve_needed: Decimal
    savings_balance: Decimal
    months_left_in_year: int
    spendable_today: Decimal
    days_left_in_week: int
    on_pace: bool
    # Renamed from not_saving/not_saving_weekly 2026-08-13 -- "Not Saving"
    # didn't say what it measured and reads oddly once positive. This is the
    # quarter's lowest projected checking balance after also reserving the
    # recurring card bills still due this month: positive means that much
    # room above zero before touching savings; negative means the plan
    # already runs into savings even before anything unexpected happens.
    safety_margin: Decimal
    safety_margin_weekly: Decimal
    days_remaining_in_month: int
    # The quarter's projected low point and the day it lands. Already computed
    # for safety_margin; surfaced because it is what Dan checks before
    # approving a large purchase ('2026 Overview'!B23:C27 keeps the pair side
    # by side).
    lookahead_minimum: Decimal = Decimal("0")
    lookahead_minimum_date: Optional[date] = None
    cards: list[CardSnapshot]
    categories: list[WeeklyDigestCategory]
    top_merchants: list[MerchantSpendingEntry]


class WeeklyDigest(BaseModel):
    week_start: date
    week_end: date
    total_spent: Decimal
    categories: list[WeeklyDigestCategory]
    top_merchants: list[MerchantSpendingEntry]
    risk: ForecastRisk
    snapshot: BudgetSnapshot


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



# ── Verification Flags ────────────────────────────────────────────────────────

class VerificationFlagCreate(BaseModel):
    feature: VerificationFeature
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    observed: dict
    expected_value: Optional[Decimal] = None
    note: Optional[str] = None


class VerificationFlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    feature: VerificationFeature
    reference_type: Optional[str]
    reference_id: Optional[int]
    observed_json: str
    expected_value: Optional[Decimal]
    note: Optional[str]
    status: VerificationFlagStatus
    created_at: datetime
    resolved_at: Optional[datetime]


class VerificationFlagResolve(BaseModel):
    status: VerificationFlagStatus


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
