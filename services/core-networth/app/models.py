import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Column, String, Float, Date, DateTime, ForeignKey, Enum, Text, Boolean
)
from sqlalchemy.orm import relationship

from .database import Base


def gen_id() -> str:
    return uuid.uuid4().hex[:12]


class AssetClass(str, enum.Enum):
    ETF = "ETF"
    STOCK = "STOCK"
    BOND = "BOND"
    CRYPTO = "CRYPTO"
    CASH = "CASH"
    REAL_ESTATE = "REAL_ESTATE"
    PENSION_FUND = "PENSION_FUND"
    OTHER = "OTHER"


class AllocationCategory(str, enum.Enum):
    """
    A single tagging system used across BOTH tradable positions (via
    Asset.category) and cash-like balances (via CashAccount.category), so the
    whole portfolio -- ETFs, cash, emergency fund, pension fund -- can be
    broken down by the same five buckets in the "Portfolio Allocation" view.
    Nullable on Asset (doesn't make sense for e.g. real estate); defaults to
    CASH on CashAccount.
    """
    STOCK = "STOCK"
    BOND = "BOND"
    CASH = "CASH"
    EMERGENCY_FUND = "EMERGENCY_FUND"
    PENSION_FUND = "PENSION_FUND"


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    base_currency = Column(String, default="EUR", nullable=False)
    notes = Column(Text, nullable=True)
    archived = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    holdings = relationship("HoldingEntry", back_populates="portfolio", cascade="all, delete-orphan")
    cash_accounts = relationship("CashAccount", back_populates="portfolio", cascade="all, delete-orphan")


class Asset(Base):
    """A tracked instrument. Shared across portfolios (e.g. same ETF held in two portfolios)."""
    __tablename__ = "assets"

    id = Column(String, primary_key=True, default=gen_id)
    ticker = Column(String, nullable=True, index=True)  # yfinance-compatible ticker, null for non-listed assets
    isin = Column(String, nullable=True)
    name = Column(String, nullable=False)
    asset_class = Column(Enum(AssetClass), nullable=False, default=AssetClass.OTHER)
    category = Column(Enum(AllocationCategory), nullable=True)
    currency = Column(String, nullable=False, default="EUR")
    notes = Column(Text, nullable=True)

    holdings = relationship("HoldingEntry", back_populates="asset")


class HoldingEntry(Base):
    """
    A point-in-time record of 'I held X units of asset A in portfolio P on date D'.
    This replaces the monthly-column layout of the spreadsheet with a normalized,
    append-only time series: add a new entry whenever quantity changes (buy/sell/rebalance)
    or simply on a periodic tracking cadence, exactly like the old spreadsheet rows.
    """
    __tablename__ = "holding_entries"

    id = Column(String, primary_key=True, default=gen_id)
    portfolio_id = Column(String, ForeignKey("portfolios.id"), nullable=False)
    asset_id = Column(String, ForeignKey("assets.id"), nullable=False)
    entry_date = Column(Date, nullable=False, default=date.today)
    quantity = Column(Float, nullable=False)

    # If set, this overrides any live price lookup (for real estate, private
    # investments, pension funds valued manually, etc.)
    manual_price = Column(Float, nullable=True)

    # Real insertion timestamp, used ONLY as a tie-breaker when two entries
    # share the same entry_date (e.g. the same holding edited twice in one
    # day) -- `id` is a random UUID fragment (see gen_id above), not
    # sortable by creation order, so without this, "which edit wins" for a
    # same-day tie was effectively random (whatever order SQLite happened to
    # return matching rows in). Nullable because older rows created before
    # this column existed have no reliable value to backfill (see migrate.py);
    # NULL sorts before any real timestamp, which is an acceptable fallback.
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)

    portfolio = relationship("Portfolio", back_populates="holdings")
    asset = relationship("Asset", back_populates="holdings")


class CashAccount(Base):
    """
    Despite the name, this is used for any manually-tracked balance the user
    updates from time to time rather than a live-priced position: bank/broker
    cash, an emergency fund, or a pension fund whose value you check on the
    provider's website occasionally. `category` distinguishes which of those
    it represents; defaults to CASH (also the fallback for rows created
    before this field existed, where it's left NULL).
    """
    __tablename__ = "cash_accounts"

    id = Column(String, primary_key=True, default=gen_id)
    portfolio_id = Column(String, ForeignKey("portfolios.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g. "Revolut", "Trade Republic", "Checking Account"
    currency = Column(String, nullable=False, default="EUR")
    institution = Column(String, nullable=True)
    category = Column(Enum(AllocationCategory), nullable=True)  # None is treated as CASH

    portfolio = relationship("Portfolio", back_populates="cash_accounts")
    balances = relationship("CashBalanceEntry", back_populates="account", cascade="all, delete-orphan")


class CashBalanceEntry(Base):
    __tablename__ = "cash_balance_entries"

    id = Column(String, primary_key=True, default=gen_id)
    account_id = Column(String, ForeignKey("cash_accounts.id"), nullable=False)
    entry_date = Column(Date, nullable=False, default=date.today)
    balance = Column(Float, nullable=False)

    # Same tie-breaker as HoldingEntry.created_at above -- see that comment
    # for the full rationale. Without this, updating a balance twice in the
    # same day (both rows sharing entry_date=today) meant whichever row
    # SQLite happened to return first for "most recent balance" was
    # effectively random, so a second same-day update could silently appear
    # not to have "taken" even though it was correctly saved.
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)

    account = relationship("CashAccount", back_populates="balances")


class NetWorthSnapshot(Base):
    """
    A FROZEN combined net worth figure across all portfolios, taken at a point
    in time and never recomputed afterwards -- unlike the live chart on the
    Summary/Portfolio pages, which always re-values every holding at today's
    price no matter which past date it's plotting. Rows here are written only
    when the user (or a future scheduler) explicitly takes a snapshot, exactly
    like manually copying a total into a spreadsheet row once a month.
    One row per (snapshot_date, currency) -- taking a snapshot again on the
    same date overwrites that day's row instead of duplicating it.
    """
    __tablename__ = "networth_snapshots"

    id = Column(String, primary_key=True, default=gen_id)
    snapshot_date = Column(Date, nullable=False, default=date.today)
    currency = Column(String, nullable=False, default="EUR")
    net_worth = Column(Float, nullable=False)
    invested_total = Column(Float, nullable=False)
    cash_total = Column(Float, nullable=False)
    source = Column(String, nullable=False, default="manual")  # "manual" | "auto" (scheduler catch-up)
    created_at = Column(DateTime, default=datetime.utcnow)
