from collections import defaultdict
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from . import models, price_client
from .schemas import HoldingPosition, PortfolioSnapshot


def _latest_holding_per_asset(db: Session, portfolio_id: str, as_of: date) -> List[models.HoldingEntry]:
    """
    For each asset, pick the most recent HoldingEntry on or before `as_of`.
    This is what lets the UI show "current" positions even though data is
    entered as a time series (like the old spreadsheet's monthly columns).
    """
    entries = (
        db.query(models.HoldingEntry)
        .filter(
            models.HoldingEntry.portfolio_id == portfolio_id,
            models.HoldingEntry.entry_date <= as_of,
        )
        .order_by(models.HoldingEntry.asset_id, models.HoldingEntry.entry_date.desc())
        .all()
    )
    latest_by_asset = {}
    for e in entries:
        if e.asset_id not in latest_by_asset:
            latest_by_asset[e.asset_id] = e
    return list(latest_by_asset.values())


def _latest_cash_balance(db: Session, portfolio_id: str, as_of: date) -> float:
    accounts = db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio_id).all()
    total = 0.0
    for acc in accounts:
        entry = (
            db.query(models.CashBalanceEntry)
            .filter(
                models.CashBalanceEntry.account_id == acc.id,
                models.CashBalanceEntry.entry_date <= as_of,
            )
            .order_by(models.CashBalanceEntry.entry_date.desc())
            .first()
        )
        if entry:
            # NOTE: cash is assumed already in the account's declared currency;
            # conversion to base currency happens the same way as for assets.
            total += entry.balance  # converted by caller if needed
    return total


async def compute_portfolio_snapshot(db: Session, portfolio: models.Portfolio, as_of: Optional[date] = None) -> PortfolioSnapshot:
    as_of = as_of or date.today()
    base_ccy = portfolio.base_currency

    holdings = _latest_holding_per_asset(db, portfolio.id, as_of)
    positions: List[HoldingPosition] = []
    invested_total = 0.0

    for h in holdings:
        asset = h.asset
        price = None
        price_source = "unavailable"
        price_ccy = asset.currency

        if h.manual_price is not None:
            price = h.manual_price
            price_source = "manual"
        elif asset.ticker:
            live = await price_client.get_latest_price(asset.ticker)
            if live:
                price = live["price"]
                price_ccy = live.get("currency", asset.currency)
                price_source = "live"

        value_base = None
        if price is not None:
            fx = await price_client.get_fx_rate(price_ccy, base_ccy)
            fx = fx if fx is not None else 1.0
            value_base = h.quantity * price * fx
            invested_total += value_base

        positions.append(
            HoldingPosition(
                asset_id=asset.id,
                asset_name=asset.name,
                ticker=asset.ticker,
                asset_class=asset.asset_class,
                quantity=h.quantity,
                price=price,
                price_currency=price_ccy,
                price_source=price_source,
                value_base_ccy=value_base,
            )
        )

    # Cash accounts: convert each account's currency to base currency
    accounts = db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio.id).all()
    cash_total = 0.0
    for acc in accounts:
        entry = (
            db.query(models.CashBalanceEntry)
            .filter(
                models.CashBalanceEntry.account_id == acc.id,
                models.CashBalanceEntry.entry_date <= as_of,
            )
            .order_by(models.CashBalanceEntry.entry_date.desc())
            .first()
        )
        if entry:
            fx = await price_client.get_fx_rate(acc.currency, base_ccy)
            fx = fx if fx is not None else 1.0
            cash_total += entry.balance * fx

    return PortfolioSnapshot(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        base_currency=base_ccy,
        as_of=as_of,
        positions=positions,
        cash_total_base_ccy=cash_total,
        invested_total_base_ccy=invested_total,
        net_worth_base_ccy=invested_total + cash_total,
    )


def distinct_entry_dates(db: Session, portfolio_id: Optional[str] = None) -> List[date]:
    """All dates on which something changed (holdings or cash), used to build the history chart."""
    q1 = db.query(models.HoldingEntry.entry_date)
    q2 = db.query(models.CashBalanceEntry.entry_date).join(
        models.CashAccount, models.CashBalanceEntry.account_id == models.CashAccount.id
    )
    if portfolio_id:
        q1 = q1.filter(models.HoldingEntry.portfolio_id == portfolio_id)
        q2 = q2.filter(models.CashAccount.portfolio_id == portfolio_id)
    dates = {d for (d,) in q1.all()} | {d for (d,) in q2.all()}
    return sorted(dates)
