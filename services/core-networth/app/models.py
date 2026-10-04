import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Column, String, Float, Date, DateTime, ForeignKey, Enum, Text, Boolean, UniqueConstraint
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


class TransactionDirection(str, enum.Enum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class InvestmentIncomeKind(str, enum.Enum):
    """
    Marks an INCOME CashTransaction as capital income -- money the
    investment itself paid out -- rather than money moved in from outside.
    See xirr.build_portfolio_cashflows for the one place this changes
    anything: such a transaction is excluded from the reconstructed
    cashflows, so it reads as return instead of as a contribution.
    """
    DIVIDEND = "DIVIDEND"
    COUPON = "COUPON"
    INTEREST = "INTEREST"


class MerchantMatchType(str, enum.Enum):
    EXACT = "EXACT"        # the whole counterparty name, e.g. "unicoop firenze-ponsacco"
    CONTAINS = "CONTAINS"  # a piece of it, e.g. "unicoop" for every store of the chain


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
    # share the same entry_date -- `id` (see gen_id) isn't sortable by
    # creation order. Nullable: rows from before the column existed have
    # none, and NULL sorts before any real timestamp.
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)

    portfolio = relationship("Portfolio", back_populates="holdings")
    asset = relationship("Asset", back_populates="holdings")


class CashAccountKind(str, enum.Enum):
    """
    CURRENCY: a balance in a real currency, updated by hand or via
    CashTransaction amounts. VOUCHER is for
    balances tracked as a count of identical-value units instead -- meal
    vouchers being the motivating case -- where `unit_value` converts that
    count into money for net worth and expense reporting.
    """
    CURRENCY = "CURRENCY"
    VOUCHER = "VOUCHER"


class CashAccount(Base):
    """
    Despite the name, this is used for any manually-tracked balance the user
    updates from time to time rather than a live-priced position: bank/broker
    cash, an emergency fund, or a pension fund whose value you check on the
    provider's website occasionally. `category` distinguishes which of those
    it represents; NULL is treated as CASH.
    """
    __tablename__ = "cash_accounts"

    id = Column(String, primary_key=True, default=gen_id)
    portfolio_id = Column(String, ForeignKey("portfolios.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g. "Revolut", "Trade Republic", "Checking Account"
    currency = Column(String, nullable=False, default="EUR")
    institution = Column(String, nullable=True)
    category = Column(Enum(AllocationCategory), nullable=True)  # None is treated as CASH
    kind = Column(Enum(CashAccountKind), nullable=False, default=CashAccountKind.CURRENCY)
    # Set when the user "removes" this account (see DELETE /cash-accounts/{id}
    # in main.py). Never hard-deleted: past dates still need this account's
    # balance history to value the portfolio as it was. NULL means active.
    #
    # Written in LOCAL time, unlike every other timestamp in this file (UTC):
    # its .date() is compared against calendar days, which are local
    # throughout the app.
    archived_at = Column(DateTime, nullable=True)
    # Only meaningful when kind == VOUCHER: money value of a single unit,
    # e.g. 7.0 for a EUR7 meal voucher. Editable any time; changing it only
    # affects transactions logged *after* the change -- see
    # CashTransaction.amount's docstring for why past ones don't move.
    unit_value = Column(Float, nullable=True)

    portfolio = relationship("Portfolio", back_populates="cash_accounts")
    balances = relationship("CashBalanceEntry", back_populates="account", cascade="all, delete-orphan")
    transactions = relationship("CashTransaction", back_populates="account", cascade="all, delete-orphan")


class CashBalanceEntry(Base):
    __tablename__ = "cash_balance_entries"

    id = Column(String, primary_key=True, default=gen_id)
    account_id = Column(String, ForeignKey("cash_accounts.id"), nullable=False)
    entry_date = Column(Date, nullable=False, default=date.today)
    balance = Column(Float, nullable=False)

    # Same tie-breaker as HoldingEntry.created_at above.
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)

    account = relationship("CashAccount", back_populates="balances")


class ExpenseCategory(Base):
    """
    A spending category (Groceries, Bills, Entertainment...), managed only
    from the Expenses tabs -- deliberately a separate taxonomy from
    AllocationCategory (Stock/Bond/Cash/...), which tags *where* money sits
    in the portfolio, not *what* it was spent on.
    """
    __tablename__ = "expense_categories"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    color = Column(String, nullable=True)  # hex string, e.g. "#6B4E14" -- optional, for charts
    created_at = Column(DateTime, default=datetime.utcnow)

    transactions = relationship("CashTransaction", back_populates="category")


class CashTransaction(Base):
    """
    A single income or expense movement against a cash account. This is the
    ledger the Expenses feature writes to; a cash account's *current*
    balance (see valuation.resolve_cash_balance) is derived from the most
    recent CashBalanceEntry (its "opening balance") plus every transaction
    dated after it, rather than being edited by hand from that point on.
    `amount` is always stored positive -- `direction` says which way it
    moves the balance.
    """
    __tablename__ = "cash_transactions"

    id = Column(String, primary_key=True, default=gen_id)
    account_id = Column(String, ForeignKey("cash_accounts.id"), nullable=False)
    category_id = Column(String, ForeignKey("expense_categories.id"), nullable=True)
    entry_date = Column(Date, nullable=False, default=date.today)
    direction = Column(Enum(TransactionDirection), nullable=False)
    # For a CURRENCY account, this is the money amount directly. For a
    # VOUCHER account, this is computed server-side as
    # quantity * account.unit_value AT THE TIME OF THIS TRANSACTION and then
    # frozen -- so if the unit value changes later (a new meal-voucher
    # contract, say), past transactions keep reporting the euro value they
    # actually had, instead of silently changing.
    amount = Column(Float, nullable=False)
    # Only set for VOUCHER-account transactions: how many units this
    # transaction moved (e.g. "2 vouchers"). Null for ordinary CURRENCY
    # transactions, where the balance is just `amount`.
    quantity = Column(Float, nullable=True)
    note = Column(Text, nullable=True)
    # Set on BOTH legs of an internal transfer between two of the user's own
    # cash accounts (see POST /transfers) -- an expense on the source
    # account and an income on the destination account, sharing this same
    # id. It's not real spending or income, just money moving between
    # buckets the user already owns, so /expenses/summary excludes any row
    # with this set, keeping category/monthly statistics honest. Null for
    # an ordinary transaction.
    transfer_id = Column(String, nullable=True)
    # Set on a refund (an INCOME row) that offsets a specific earlier
    # EXPENSE row -- e.g. lending someone money (logged as an expense) and
    # getting some or all of it back later. Points at that expense's id.
    # Deliberately does NOT rewrite the original expense's `amount` (that
    # would retroactively change historical balances), so the balance-affecting
    # side of a refund is just an ordinary income, dated when the money
    # actually arrived. What DOES change is how /expenses/summary counts
    # it: see main.py's compute_refund_adjustments.
    refund_of_id = Column(String, ForeignKey("cash_transactions.id"), nullable=True)

    # Set on an INCOME row that is a dividend, coupon or interest payment --
    # money the investment itself paid out, not money moved in from
    # outside. Only this marks the distinction: direction, amount and
    # balance effect are exactly like any other income. Null for an
    # ordinary income/expense (the only option before this column existed,
    # which is why it's never backfilled -- see DESIGN_NOTES.md).
    investment_income_kind = Column(Enum(InvestmentIncomeKind), nullable=True)

    # Same same-day tie-breaker role as CashBalanceEntry.created_at above.
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)

    # Who the money went to or came from, as the bank named them -- the
    # merchant on a card payment, the sender on an incoming transfer. Set by
    # bank-sync on what it captures (null on anything logged by hand), and
    # what MerchantRule matches against. `counterparty_key` is the same name
    # normalized (see merchants.normalize), since a bank can spell one
    # merchant differently from one message to the next.
    counterparty = Column(String, nullable=True)
    counterparty_key = Column(String, nullable=True)

    account = relationship("CashAccount", back_populates="transactions")
    category = relationship("ExpenseCategory", back_populates="transactions")


class Budget(Base):
    """
    A monthly spending limit for one expense category, in `currency` -- spent
    is counted like /expenses/summary (see reports.py) and converted into it.
    One per category: a second limit for the same category would just be two
    answers to the same question.
    """
    __tablename__ = "budgets"

    id = Column(String, primary_key=True, default=gen_id)
    category_id = Column(String, ForeignKey("expense_categories.id"), nullable=False, unique=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="EUR")
    created_at = Column(DateTime, default=datetime.utcnow)


class MerchantRule(Base):
    """
    "Transactions with this counterparty go in this category" -- the way to
    categorize what a bank sends without a usable merchant category code
    (Revolut through Enable Banking sends none at all). Applied by
    core-networth itself when a transaction with a counterparty is created
    without a category, and, when the rule is saved, to that counterparty's
    earlier transactions still uncategorized. See merchants.py.

    An EXACT rule names one counterparty; a CONTAINS rule a piece of the name
    shared by many (every store of a chain). EXACT always wins, then the
    longest matching CONTAINS. `ignored` marks a counterparty deliberately
    left uncategorized -- your own name on a transfer, a shop where every
    purchase is something different -- so it stops showing up as one still
    to map.
    """
    __tablename__ = "merchant_rules"

    id = Column(String, primary_key=True, default=gen_id)
    pattern = Column(String, nullable=False)  # always normalized
    match_type = Column(Enum(MerchantMatchType), nullable=False, default=MerchantMatchType.EXACT)
    category_id = Column(String, ForeignKey("expense_categories.id"), nullable=True)
    ignored = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("pattern", "match_type", name="uq_merchant_rule_pattern"),)


class IdempotencyKey(Base):
    """
    Lets a client (the frontend, a future retry layer, a script) safely
    replay a POST that might not have gotten a response the first time --
    a flaky connection where it's unclear whether the request actually
    went through -- without risking a duplicate transaction/transfer/
    holding entry. A client sends an `Idempotency-Key` header on the
    original request; if the exact same key shows up again for the same
    endpoint, the stored response is returned as-is instead of re-running
    the mutation. Entries older than IDEMPOTENCY_TTL_HOURS (see main.py)
    are pruned: a retry happens within seconds or minutes.
    """
    __tablename__ = "idempotency_keys"

    key = Column(String, primary_key=True)
    endpoint = Column(String, nullable=False)
    response_body = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class NetWorthSnapshot(Base):
    """
    A FROZEN combined net worth figure across all portfolios, taken at a point
    in time and never recomputed afterwards -- unlike the live charts, which
    re-value from the current data every time. Rows are written when the user
    takes a snapshot, or by the scheduler's month-end catch-up (`source`).
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
