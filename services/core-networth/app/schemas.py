from datetime import date, datetime, timedelta
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import AssetClass, AllocationCategory, TransactionDirection, CashAccountKind

# Generous caps on free-text input fields -- not meant to constrain any
# realistic legitimate value, just to stop an accidental huge paste (or a
# malicious payload) from bloating the SQLite file or breaking UI layout.
# Existing stored rows longer than these (there shouldn't be any, but
# nothing enforced this before) are untouched -- only new writes are capped,
# and the *Out schemas below deliberately have no max_length so reading
# back an existing longer value never fails.
NAME_MAX_LEN = 200
NOTE_MAX_LEN = 4000


def _round3(v: Optional[float]) -> Optional[float]:
    """All monetary inputs accept up to 3 decimal places; anything beyond
    that is rounded here so precision stays consistent everywhere the value
    is later displayed or aggregated, regardless of what the client sent."""
    return None if v is None else round(v, 3)


def _round4(v: Optional[float]) -> Optional[float]:
    """Unit values (e.g. what a single meal voucher is worth) accept up to
    4 decimal places -- one more than _round3, since a unit value multiplied
    by a large quantity can otherwise accumulate visible rounding drift."""
    return None if v is None else round(v, 4)


def _reject_future_date(v: Optional[date]) -> Optional[date]:
    """
    No entry may be dated in the future, and none ever is: everything
    downstream depends on it. A future-dated entry sorts after the final
    "today" valuation flow that XIRR closes its series with (turning a
    perfectly healthy account into a -98%/year return), and puts a point past
    today on the history chart while the days in between are never filled in.

    "Today" is the server's date, which is not necessarily the user's: east
    of the server their local today is the server's tomorrow for a few hours
    every evening. Rejecting those entries outright is a confusing error for
    something the user did nothing wrong in, so a date one day ahead -- the
    most any real timezone offset can produce -- is read as "now" and stored
    as the server's today. Anything beyond that is genuinely future-dated
    and still refused.
    """
    if v is None:
        return v
    today = date.today()
    if v > today + timedelta(days=1):
        raise ValueError("entry_date can't be in the future")
    return min(v, today)


def _normalize_currency(v: Optional[str]) -> Optional[str]:
    """Currency codes reach Intl.NumberFormat in the browser, which throws on
    anything that isn't three letters -- and an unhandled throw there blanks
    the whole page, with no way left to correct the value that caused it.
    Rejecting it at the door is the only place that can't be bypassed."""
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
    v = round(v, 4)
    if v <= 0:
        raise ValueError("must be positive")
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

    _round_price = field_validator("manual_price")(_round3)
    _no_future_date = field_validator("entry_date")(_reject_future_date)


class HoldingEntryUpdate(BaseModel):
    entry_date: Optional[date] = None
    quantity: Optional[float] = None
    manual_price: Optional[float] = None

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

    _round_unit_value = field_validator("unit_value")(_round4)
    _currency = field_validator("currency")(_normalize_currency)


class CashBalanceEntryCreate(BaseModel):
    entry_date: date
    balance: float

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


class TransferOut(BaseModel):
    transfer_id: str
    from_leg: CashTransactionOut
    to_leg: CashTransactionOut


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
