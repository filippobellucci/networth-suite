from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, field_validator

from .models import AssetClass, AllocationCategory


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


class CashBalanceEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    account_id: str
    entry_date: date
    balance: float


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
    price_source: str  # "live" | "manual" | "unavailable"
    value_base_ccy: Optional[float]


class CashPosition(BaseModel):
    account_id: str
    account_name: str
    category: AllocationCategory
    currency: str
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
    created_at: datetime
