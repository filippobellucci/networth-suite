import enum
from datetime import datetime

from sqlalchemy import Column, String, Float, Date, DateTime, ForeignKey, Enum, Text, UniqueConstraint

from .database import Base


class LinkStatus(str, enum.Enum):
    PENDING = "PENDING"          # in links.yaml, never authorized with the bank yet
    AUTHORIZING = "AUTHORIZING"  # you clicked "Authorize", waiting for the bank's redirect back
    ACTIVE = "ACTIVE"            # authorized, being synced on schedule
    EXPIRED = "EXPIRED"          # the bank's consent window (see ACCESS_VALID_DAYS) has passed
    ERROR = "ERROR"              # authorization itself failed -- see last_error
    REMOVED = "REMOVED"          # label no longer present in links.yaml -- excluded from syncing,
                                  # row kept (not deleted) so SyncedTransaction history stays valid
                                  # and re-adding the same label later can resume without re-authorizing


class BankLink(Base):
    """
    One row per entry in links.yaml -- one bank account you've asked this
    service to watch. Keyed by `label` (not a random id) specifically so
    that re-reading links.yaml on every startup can find-or-update the
    matching row instead of creating duplicates each time the container
    restarts.
    """
    __tablename__ = "bank_links"

    label = Column(String, primary_key=True)  # e.g. "Fineco" -- must be unique in links.yaml
    aspsp_name = Column(String, nullable=False)
    aspsp_country = Column(String, nullable=False)
    portfolio_id = Column(String, nullable=False)
    cash_account_id = Column(String, nullable=False)

    status = Column(Enum(LinkStatus), nullable=False, default=LinkStatus.PENDING)
    session_id = Column(String, nullable=True)
    eb_account_id = Column(String, nullable=True)  # which account within the bank session gets synced
    valid_until = Column(DateTime, nullable=True)  # when the bank's consent expires -- re-authorize before this
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class SyncedTransaction(Base):
    """
    One row per bank transaction already pushed into core-networth --
    purely a dedupe ledger, since Enable Banking's transaction list for a
    date range is re-fetched (not diffed) on every sync, so without this
    every poll would re-create the same expenses over and over.
    """
    __tablename__ = "synced_transactions"

    id = Column(String, primary_key=True)  # f"{bank_link_label}:{external_id}", see sync.py
    bank_link_label = Column(String, ForeignKey("bank_links.label"), nullable=False)
    external_id = Column(String, nullable=False)  # Enable Banking's own transaction identifier
    entry_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)  # signed: negative = expense, positive = income
    core_transaction_id = Column(String, nullable=True)  # the CashTransaction this became in core-networth
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("bank_link_label", "external_id", name="uq_link_external_id"),)
