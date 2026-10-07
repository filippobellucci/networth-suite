import math
from datetime import date, datetime, timedelta
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import (
    AssetClass, AllocationCategory, TransactionDirection, CashAccountKind, MerchantMatchType,
    InvestmentIncomeKind,
)

# Generous caps on free-text input fields, against an accidental huge paste
# (or a malicious payload) bloating the SQLite file or breaking UI layout.
# Only writes are capped: the *Out schemas have no max_length, so an older,
# longer stored value still reads back.
NAME_MAX_LEN = 200
NOTE_MAX_LEN = 4000
# A counterparty name as a bank sends it -- generous, but bounded like every
# other free-text field here.
COUNTERPARTY_MAX_LEN = 200


def _require_finite(v: Optional[float]) -> Optional[float]:
    """
    Rejects NaN and +/-Infinity before they can be stored. Python's json
    parser accepts them, "must be positive" doesn't catch them, and one
    stored infinite amount makes every figure it feeds unrepresentable in
    JSON.
    """
    if v is None:
        return v
    if not math.isfinite(v):
        raise ValueError("must be a real number")
    return v


def _round3(v: Optional[float]) -> Optional[float]:
    """All monetary inputs accept up to 3 decimal places; anything beyond
    that is rounded here so precision stays consistent everywhere the value
    is later displayed or aggregated, regardless of what the client sent."""
    return None if v is None else round(_require_finite(v), 3)


def _round4(v: Optional[float]) -> Optional[float]:
    """Unit values (e.g. what a single meal voucher is worth) accept up to
    4 decimal places -- one more than _round3, since a unit value multiplied
    by a large quantity can otherwise accumulate visible rounding drift."""
    return None if v is None else round(_require_finite(v), 4)


def _reject_future_date(v: Optional[date]) -> Optional[date]:
    """
    No entry may be dated in the future: XIRR closes its series with a
    "today" flow, and the history chart ends today.

    "Today" is the server's date, and east of the server the user's today is
    the server's tomorrow for a few hours every evening -- so a date one day
    ahead (the most a timezone offset can produce) is stored as the server's
    today. Anything beyond that is refused.
    """
    if v is None:
        return v
    today = date.today()
    if v > today + timedelta(days=1):
        raise ValueError("entry_date can't be in the future")
    return min(v, today)


def _normalize_currency(v: Optional[str]) -> Optional[str]:
    """Currency codes reach Intl.NumberFormat in the browser, which throws on
    anything that isn't three letters."""
    if v is None:
        return v
    code = v.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("must be a 3-letter currency code, e.g. EUR")
    return code


def _round_and_check_positive(v: Optional[float]) -> Optional[float]:
    """Shared by every amount/quantity field below (a transaction's, a
    transfer's): round to 4 decimals, and reject zero/negative. Nothing here
    is ever signed -- a transaction's `direction` is what says whether it's
    income or an expense, and a transfer always moves money from its source
    to its destination."""
    if v is None:
        return v
    v = round(_require_finite(v), 4)
    if v <= 0:
        raise ValueError("must be positive")
    return v


def _reject_explicit_null(v):
    """
    For a field that the database stores NOT NULL.

    Every *Update schema types its fields Optional so that omitting one
    means "leave this alone", and the endpoints apply the payload with
    `model_dump(exclude_unset=True)` -- which keeps a field sent explicitly
    as null. Pydantic runs this validator only on a value the client
    supplied, so omitting the field still means "unchanged".
    """
    if v is None:
        raise ValueError("can't be set to null -- omit this field to leave it unchanged")
    return v


# ---------- Portfolio ----------
class PortfolioCreate(BaseModel):
    name: str = Field(..., max_length=NAME_MAX_LEN)
    base_currency: str = "EUR"
    notes: Optional[str] = Field(None, max_length=NOTE_MAX_LEN)

    _currency = field_validator("base_currency")(_normalize_currency)


class PortfolioUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=NAME_MAX_LEN)
    base_currency: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=NOTE_MAX_LEN)
    archived: Optional[bool] = None

    # `notes` is genuinely nullable (clearing it is a real edit); the rest
    # are not -- see _reject_explicit_null.
    _not_null = field_validator("name", "base_currency", "archived")(_reject_explicit_null)
    _currency = field_validator("base_currency")(_normalize_currency)


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    base_currency: str
    notes: Optional[str] = None
    archived: bool
    created_at: datetime


# ---------- Asset ----------
class AssetCreate(BaseModel):
    ticker: Optional[str] = Field(None, max_length=20)
    isin: Optional[str] = Field(None, max_length=20)
    name: str = Field(..., max_length=NAME_MAX_LEN)
    asset_class: AssetClass = AssetClass.OTHER
    category: Optional[AllocationCategory] = None
    currency: str = "EUR"
    notes: Optional[str] = Field(None, max_length=NOTE_MAX_LEN)

    _currency = field_validator("currency")(_normalize_currency)


class AssetUpdate(BaseModel):
    ticker: Optional[str] = Field(None, max_length=20)
    isin: Optional[str] = Field(None, max_length=20)
    name: Optional[str] = Field(None, max_length=NAME_MAX_LEN)
    asset_class: Optional[AssetClass] = None
    category: Optional[AllocationCategory] = None
    currency: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=NOTE_MAX_LEN)

    # ticker/isin/category/notes are all nullable columns -- clearing them is
    # a legitimate edit. name/asset_class/currency are not.
    _not_null = field_validator("name", "asset_class", "currency")(_reject_explicit_null)
    _currency = field_validator("currency")(_normalize_currency)


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ticker: Optional[str] = None
    isin: Optional[str] = None
    name: str
    asset_class: AssetClass
    category: Optional[AllocationCategory] = None
    currency: str
    notes: Optional[str] = None


# ---------- Holding entries ----------
class HoldingEntryCreate(BaseModel):
    asset_id: str
    entry_date: date
    quantity: float
    manual_price: Optional[float] = None

    _finite_quantity = field_validator("quantity")(_require_finite)
    _round_price = field_validator("manual_price")(_round3)
    _no_future_date = field_validator("entry_date")(_reject_future_date)


class HoldingEntryUpdate(BaseModel):
    entry_date: Optional[date] = None
    quantity: Optional[float] = None
    manual_price: Optional[float] = None

    # manual_price is nullable -- clearing it switches the position back to
    # its live price, which is a real edit.
    _not_null = field_validator("entry_date", "quantity")(_reject_explicit_null)
    _finite_quantity = field_validator("quantity")(_require_finite)
    _round_price = field_validator("manual_price")(_round3)
    _no_future_date = field_validator("entry_date")(_reject_future_date)


class HoldingEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    portfolio_id: str
    asset_id: str
    entry_date: date
    quantity: float
    manual_price: Optional[float] = None


# ---------- Cash (also used for Emergency Fund / Pension Fund -- see CashAccount) ----------
class CashAccountCreate(BaseModel):
    name: str = Field(..., max_length=NAME_MAX_LEN)
    currency: str = "EUR"
    institution: Optional[str] = Field(None, max_length=NAME_MAX_LEN)
    category: AllocationCategory = AllocationCategory.CASH
    kind: CashAccountKind = CashAccountKind.CURRENCY
    unit_value: Optional[float] = None

    _round_unit_value = field_validator("unit_value")(_round4)
    _currency = field_validator("currency")(_normalize_currency)


class CashAccountUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=NAME_MAX_LEN)
    currency: Optional[str] = None
    institution: Optional[str] = Field(None, max_length=NAME_MAX_LEN)
    category: Optional[AllocationCategory] = None
    unit_value: Optional[float] = None

    # institution/category/unit_value are nullable columns; name/currency
    # are not.
    _not_null = field_validator("name", "currency")(_reject_explicit_null)
    _round_unit_value = field_validator("unit_value")(_round4)
    _currency = field_validator("currency")(_normalize_currency)


class CashBalanceEntryCreate(BaseModel):
    entry_date: date
    balance: float

    # A balance may legitimately be negative (an overdraft) or zero, so it
    # gets _round3 rather than the positive-only validator -- but it must
    # still be a real number.
    _round_balance = field_validator("balance")(_round3)
    _no_future_date = field_validator("entry_date")(_reject_future_date)


class CashAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    portfolio_id: str
    name: str
    currency: str
    institution: Optional[str] = None
    category: Optional[AllocationCategory] = None
    kind: CashAccountKind
    unit_value: Optional[float] = None
    archived_at: Optional[datetime] = None


class CashBalanceEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    account_id: str
    entry_date: date
    balance: float


# ---------- Expense categories (managed only from the Expenses tabs) ----------
class ExpenseCategoryCreate(BaseModel):
    name: str = Field(..., max_length=NAME_MAX_LEN)


class ExpenseCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=NAME_MAX_LEN)

    _not_null = field_validator("name")(_reject_explicit_null)


class ExpenseCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    color: Optional[str] = None
    created_at: datetime


# ---------- Cash transactions (income/expense ledger against a cash account) ----------
class CashTransactionCreate(BaseModel):
    entry_date: date
    direction: TransactionDirection
    # Exactly one of these is expected, depending on the target account's
    # kind -- enforced in the endpoint (it needs to look up the account
    # first to know which). `amount` for a CURRENCY account; `quantity` for
    # a VOUCHER account, whose euro amount the endpoint computes and freezes.
    amount: Optional[float] = None
    quantity: Optional[float] = None
    category_id: Optional[str] = None
    note: Optional[str] = Field(None, max_length=NOTE_MAX_LEN)
    # Set to refund a specific earlier expense (see CashTransaction.refund_of_id).
    # Only valid when direction is INCOME.
    refund_of_id: Optional[str] = None
    # Marks this as a dividend/coupon/interest payment rather than money
    # moved in from outside -- see CashTransaction.investment_income_kind.
    # Only valid when direction is INCOME, and mutually exclusive with
    # refund_of_id (enforced in the endpoint, which needs the account too).
    investment_income_kind: Optional[InvestmentIncomeKind] = None
    # Who the money went to / came from, as the bank named them -- see
    # CashTransaction.counterparty. Left without a category, a transaction
    # with one is categorized by the matching MerchantRule, if any.
    counterparty: Optional[str] = Field(None, max_length=COUNTERPARTY_MAX_LEN)

    _round_amount_and_quantity = field_validator("amount", "quantity")(_round_and_check_positive)
    _no_future_date = field_validator("entry_date")(_reject_future_date)


class CashTransactionUpdate(BaseModel):
    entry_date: Optional[date] = None
    direction: Optional[TransactionDirection] = None
    amount: Optional[float] = None
    quantity: Optional[float] = None
    category_id: Optional[str] = None
    note: Optional[str] = Field(None, max_length=NOTE_MAX_LEN)
    refund_of_id: Optional[str] = None
    investment_income_kind: Optional[InvestmentIncomeKind] = None
    counterparty: Optional[str] = Field(None, max_length=COUNTERPARTY_MAX_LEN)

    # category_id, note, refund_of_id and investment_income_kind are all
    # nullable -- clearing any of them (un-categorising, un-linking a
    # refund, un-marking a dividend) is a real edit. quantity is nullable
    # too, and only meaningful on a voucher account.
    _not_null = field_validator("entry_date", "direction", "amount")(_reject_explicit_null)
    _round_amount_and_quantity = field_validator("amount", "quantity")(_round_and_check_positive)
    _no_future_date = field_validator("entry_date")(_reject_future_date)


class CashTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    account_id: str
    category_id: Optional[str] = None
    entry_date: date
    direction: TransactionDirection
    amount: float
    quantity: Optional[float] = None
    note: Optional[str] = None
    transfer_id: Optional[str] = None
    refund_of_id: Optional[str] = None
    investment_income_kind: Optional[InvestmentIncomeKind] = None
    counterparty: Optional[str] = None


class TransferCreate(BaseModel):
    from_account_id: str
    to_account_id: str
    entry_date: date
    # Amount taken out of `from_account_id`, in that account's own currency.
    # If the destination account uses a different currency, the receiving
    # leg is converted using that day's FX rate -- same historical/live
    # split used everywhere else a past vs. current rate matters.
    amount: float
    note: Optional[str] = Field(None, max_length=NOTE_MAX_LEN)

    _round_amount = field_validator("amount")(_round_and_check_positive)
    _no_future_date = field_validator("entry_date")(_reject_future_date)


class TransactionFilters(BaseModel):
    """Search/filter query parameters shared by the transaction lists and
    the CSV export (FastAPI reads them from the query string)."""
    q: Optional[str] = None  # in the note or the counterparty, case-insensitive
    category_id: Optional[str] = None
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    direction: Optional[TransactionDirection] = None


class ConvertToTransfer(BaseModel):
    # The account the money came from (for an INCOME) or went to (an EXPENSE).
    other_account_id: str


class BulkCategorize(BaseModel):
    transaction_ids: List[str] = Field(..., min_length=1, max_length=500)
    # null clears the category.
    category_id: Optional[str] = None


class BulkCategorizeResult(BaseModel):
    updated: int


class TransferOut(BaseModel):
    transfer_id: str
    from_leg: CashTransactionOut
    to_leg: CashTransactionOut


# ---------- CSV transaction import ----------
# A full bank statement upload shouldn't exceed this for a personal-finance
# CSV; bounds how much is read into memory and parsed before anything is
# even previewed.
IMPORT_CSV_MAX_CHARS = 5_000_000
IMPORT_MAX_ROWS = 20_000


def _valid_decimal_separator(v: str) -> str:
    if v not in (".", ","):
        raise ValueError('decimal_separator must be "." or ","')
    return v


class TransactionImportMapping(BaseModel):
    """Which column of the uploaded file holds each field -- every bank
    names and orders them differently, so this is never guessed. Column
    names must match the file's own header row exactly."""
    date: str
    amount: str
    currency: Optional[str] = None
    description: Optional[str] = None
    counterparty: Optional[str] = None


class TransactionImportRequest(BaseModel):
    csv_content: str = Field(..., min_length=1, max_length=IMPORT_CSV_MAX_CHARS)
    column_mapping: TransactionImportMapping
    # strptime pattern, e.g. "%d/%m/%Y" or "%m/%d/%Y" -- day/month order is
    # ambiguous in most bank exports (01/02/2026 could be either), so the
    # caller must say which one this file uses rather than have it guessed.
    date_format: str = Field(..., min_length=1, max_length=40)
    delimiter: str = Field(",", min_length=1, max_length=1)
    # "." or ",": which character separates the integer part from the
    # decimal part in the amount column (the other is treated as a
    # thousands separator and discarded). Never inferred from the data.
    decimal_separator: str = "."

    _decimal_separator_check = field_validator("decimal_separator")(_valid_decimal_separator)


class TransactionImportRow(BaseModel):
    row_number: int  # 1-based position among the file's non-blank data rows
    status: str  # "import" | "duplicate" | "error"
    reason: Optional[str] = None  # why "duplicate" or "error"
    entry_date: Optional[date] = None
    direction: Optional[TransactionDirection] = None
    amount: Optional[float] = None
    counterparty: Optional[str] = None
    note: Optional[str] = None
    transaction_id: Optional[str] = None  # filled in by the commit endpoint only


class TransactionImportResult(BaseModel):
    total_rows: int
    to_import: int
    duplicates: int
    errors: int
    rows: List[TransactionImportRow]


# ---------- Merchant rules (counterparty -> category) ----------
class MerchantRuleCreate(BaseModel):
    pattern: str = Field(..., max_length=COUNTERPARTY_MAX_LEN)
    match_type: MerchantMatchType = MerchantMatchType.EXACT
    # Exactly one of the two: a category, or ignored=True.
    category_id: Optional[str] = None
    ignored: bool = False
    # Also categorize this counterparty's earlier transactions that are
    # still uncategorized. Never touches one that already has a category.
    apply_to_past: bool = True


class MerchantRuleUpdate(BaseModel):
    category_id: Optional[str] = None
    ignored: Optional[bool] = None
    apply_to_past: bool = True
    # Also move the transactions this rule matches that are still in the
    # category it had before -- off by default, since some of them may have
    # been put there by hand.
    recategorize_previous: bool = False


class MerchantRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    pattern: str
    match_type: MerchantMatchType
    category_id: Optional[str] = None
    ignored: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MerchantRuleSaved(BaseModel):
    rule: MerchantRuleOut
    # How many existing transactions this save categorized.
    applied: int


class MerchantOut(BaseModel):
    """One counterparty seen on transactions, with what currently decides
    its category. Totals add up `amount` as stored, in each transaction's
    own account currency."""
    key: str
    name: str
    status: str  # MAPPED | IGNORED | UNMAPPED
    rule: Optional[MerchantRuleOut] = None
    expense_count: int
    income_count: int
    expense_total: float
    income_total: float
    uncategorized_count: int
    last_date: date


class ExpenseCategoryTotal(BaseModel):
    """One row of the spending-by-category report."""
    category_id: Optional[str]  # null groups every transaction with no category set
    category_name: str
    total: float


class ExpenseSummary(BaseModel):
    from_date: date
    to_date: date
    currency: str
    total_income: float
    total_expense: float
    net: float
    by_category: List[ExpenseCategoryTotal]
    income_by_category: List[ExpenseCategoryTotal] = []


class MonthlyFlow(BaseModel):
    month: str  # YYYY-MM
    income: float
    expense: float
    net: float
    # Percent of the month's income not spent; null for a month without income.
    savings_rate: Optional[float] = None


# ---------- Budgets ----------
class BudgetCreate(BaseModel):
    category_id: str
    amount: float
    currency: str = Field("EUR", min_length=3, max_length=3)

    _round_amount = field_validator("amount")(_round_and_check_positive)
    _upper_currency = field_validator("currency")(lambda v: v.upper())


class BudgetUpdate(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = Field(None, min_length=3, max_length=3)

    _not_null = field_validator("amount", "currency")(_reject_explicit_null)
    _round_amount = field_validator("amount")(_round_and_check_positive)
    _upper_currency = field_validator("currency")(lambda v: v.upper() if v else v)


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    category_id: str
    amount: float
    currency: str
    created_at: Optional[datetime] = None


class BudgetProgressItem(BaseModel):
    budget_id: str
    category_id: str
    category_name: str
    currency: str
    budget: float
    spent: float
    remaining: float
    percent: float
    status: str  # OK | NEAR | OVER


class BudgetProgress(BaseModel):
    month: str
    elapsed_pct: float
    items: List[BudgetProgressItem]


# ---------- Recurring payments ----------
class PriceChange(BaseModel):
    previous: float
    current: float
    date: date


class RecurringPayment(BaseModel):
    key: str
    name: str
    category_id: Optional[str] = None
    cadence: str  # WEEKLY | MONTHLY | QUARTERLY | YEARLY
    occurrences: int
    first_date: date
    last_date: date
    next_expected: date
    last_amount: float
    typical_amount: float
    monthly_cost: float
    active: bool
    price_change: Optional[PriceChange] = None


class RecurringReport(BaseModel):
    currency: str
    monthly_total: float
    items: List[RecurringPayment]


# ---------- Aggregated views ----------
class HoldingPosition(BaseModel):
    """A holding enriched with a resolved price and computed value, in the requested base currency."""
    asset_id: str
    asset_name: str
    ticker: Optional[str]
    asset_class: AssetClass
    category: Optional[AllocationCategory]
    quantity: float
    price: Optional[float]
    price_currency: str
    price_source: str  # "live" | "historical" | "historical_fallback" | "manual" | "unavailable"
    value_base_ccy: Optional[float]


class CashPosition(BaseModel):
    account_id: str
    account_name: str
    category: AllocationCategory
    currency: str
    kind: CashAccountKind
    unit_value: Optional[float] = None
    # For a CURRENCY account, this is the money balance (as always). For a
    # VOUCHER account, this is the unit *count* -- convert with unit_value to
    # get money, which value_base_ccy below already does.
    balance: float
    value_base_ccy: float
    as_of: Optional[date] = None


class PortfolioSnapshot(BaseModel):
    portfolio_id: str
    portfolio_name: str
    base_currency: str
    as_of: date
    positions: List[HoldingPosition]
    cash_positions: List[CashPosition]
    cash_total_base_ccy: float
    invested_total_base_ccy: float
    net_worth_base_ccy: float
    # True when at least one conversion in this snapshot had to fall back to
    # 1:1 because the price-feed couldn't supply a rate: the totals are still
    # returned, but they mix currencies and the UI says so.
    fx_unavailable: bool = False


class NetWorthPoint(BaseModel):
    date: date
    net_worth_base_ccy: float


class NetWorthHistory(BaseModel):
    portfolio_id: Optional[str]  # null = all portfolios combined
    base_currency: str
    points: List[NetWorthPoint]


# ---------- Historical net worth snapshots (frozen, manual) ----------
class NetWorthSnapshotCreate(BaseModel):
    currency: str = "EUR"

    _currency = field_validator("currency")(_normalize_currency)


class NetWorthSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    snapshot_date: date
    currency: str
    net_worth: float
    invested_total: float
    cash_total: float
    source: str
    created_at: datetime
