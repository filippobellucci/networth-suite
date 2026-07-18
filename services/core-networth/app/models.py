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

    portfolio = relationship("Portfolio", back_populates="holdings")
    asset = relationship("Asset", back_populates="holdings")


class CashAccount(Base):
    __tablename__ = "cash_accounts"

    id = Column(String, primary_key=True, default=gen_id)
    portfolio_id = Column(String, ForeignKey("portfolios.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g. "Revolut", "Trade Republic", "Checking Account"
    currency = Column(String, nullable=False, default="EUR")
    institution = Column(String, nullable=True)

    portfolio = relationship("Portfolio", back_populates="cash_accounts")
    balances = relationship("CashBalanceEntry", back_populates="account", cascade="all, delete-orphan")


class CashBalanceEntry(Base):
    __tablename__ = "cash_balance_entries"

    id = Column(String, primary_key=True, default=gen_id)
    account_id = Column(String, ForeignKey("cash_accounts.id"), nullable=False)
    entry_date = Column(Date, nullable=False, default=date.today)
    balance = Column(Float, nullable=False)

    account = relationship("CashAccount", back_populates="balances")
