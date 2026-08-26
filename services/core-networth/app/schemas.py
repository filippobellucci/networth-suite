from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, field_validator

from .models import AssetClass, AllocationCategory, TransactionDirection, CashAccountKind


def _round3(v: Optional[float]) -> Optional[float]:
    """All monetary inputs accept up to 3 decimal places; anything beyond
    that is rounded here so precision stays consistent everywhere the value
    is later displayed or aggregated, regardless of what the client sent."""
    return None if v is None else round(v, 3)


# ---------- Portfolio ----------
class PortfolioCreate(BaseModel):
    name: str
    base_currency: str = "EUR"
    notes: Optional[str] = None


class PortfolioUpdate(BaseModel):
    name: Optional[str] = None
    base_currency: Optional[str] = None
    notes: Optional[str] = None
    archived: Optional[bool] = None


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
    ticker: Optional[str] = None
    isin: Optional[str] = None
    name: str
    asset_class: AssetClass = AssetClass.OTHER
    category: Optional[AllocationCategory] = None
    currency: str = "EUR"
    notes: Optional[str] = None


class AssetUpdate(BaseModel):
    ticker: Optional[str] = None
    isin: Optional[str] = None
    name: Optional[str] = None
    asset_class: Optional[AssetClass] = None
    category: Optional[AllocationCategory] = None
    currency: Optional[str] = None
    notes: Optional[str] = None


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


class HoldingEntryUpdate(BaseModel):
    entry_date: Optional[date] = None
    quantity: Optional[float] = None
    manual_price: Optional[float] = None

    _round_price = field_validator("manual_price")(_round3)


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
    name: str
    currency: str = "EUR"
    institution: Optional[str] = None
    category: AllocationCategory = AllocationCategory.CASH
    kind: CashAccountKind = CashAccountKind.CURRENCY
    unit_value: Optional[float] = None

    @field_validator("unit_value")
    @classmethod
    def _round_unit_value(cls, v: Optional[float]) -> Optional[float]:
        return round(v, 4) if v is not None else v


class CashAccountUpdate(BaseModel):
    name: Optional[str] = None
    currency: Optional[str] = None
    institution: Optional[str] = None
    category: Optional[AllocationCategory] = None
    unit_value: Optional[float] = None

    @field_validator("unit_value")
    @classmethod
    def _round_unit_value(cls, v: Optional[float]) -> Optional[float]:
        return round(v, 4) if v is not None else v


class CashBalanceEntryCreate(BaseModel):
    entry_date: date
    balance: float

    _round_balance = field_validator("balance")(_round3)


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


class CashBalanceEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    account_id: str
    entry_date: date
    balance: float


# ---------- Expense categories (managed only from the Expenses tabs) ----------
class ExpenseCategoryCreate(BaseModel):
    name: str


class ExpenseCategoryUpdate(BaseModel):
    name: Optional[str] = None


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
    note: Optional[str] = None

    @field_validator("amount", "quantity")
    @classmethod
    def _round_and_check_positive(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        v = round(v, 4)
        if v <= 0:
            raise ValueError("must be positive -- use `direction` to say whether it's income or expense")
        return v


class CashTransactionUpdate(BaseModel):
    entry_date: Optional[date] = None
    direction: Optional[TransactionDirection] = None
    amount: Optional[float] = None
    quantity: Optional[float] = None
    category_id: Optional[str] = None
    note: Optional[str] = None

    @field_validator("amount", "quantity")
    @classmethod
    def _round_and_check_positive(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        v = round(v, 4)
        if v <= 0:
            raise ValueError("must be positive -- use `direction` to say whether it's income or expense")
        return v


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
