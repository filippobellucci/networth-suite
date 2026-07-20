from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from . import models, price_client
from .models import AllocationCategory
from .schemas import HoldingPosition, CashPosition, PortfolioSnapshot


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


async def compute_portfolio_snapshot(
    db: Session,
    portfolio: models.Portfolio,
    as_of: Optional[date] = None,
    force_refresh: bool = False,
) -> PortfolioSnapshot:
    as_of = as_of or date.today()
    is_historical = as_of < date.today()
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
            # A manually-entered price is exactly what the position was worth
            # at that historical entry's date already -- no lookup needed.
            price = h.manual_price
            price_source = "manual"
        elif asset.ticker:
            if is_historical:
                hist = await price_client.get_price_on_date(asset.ticker, as_of)
                if hist:
                    price = hist["price"]
                    price_ccy = hist.get("currency", asset.currency)
                    price_source = "historical"
            else:
                live = await price_client.get_latest_price(asset.ticker, force=force_refresh)
                if live:
                    price = live["price"]
                    price_ccy = live.get("currency", asset.currency)
                    price_source = "live"

        value_base = None
        if price is not None:
            if is_historical:
                fx = await price_client.get_fx_rate_on_date(price_ccy, base_ccy, as_of)
            else:
                fx = await price_client.get_fx_rate(price_ccy, base_ccy, force=force_refresh)
            fx = fx if fx is not None else 1.0
            value_base = h.quantity * price * fx
            invested_total += value_base

        positions.append(
            HoldingPosition(
                asset_id=asset.id,
                asset_name=asset.name,
                ticker=asset.ticker,
                asset_class=asset.asset_class,
                category=asset.category,
                quantity=h.quantity,
                price=price,
                price_currency=price_ccy,
                price_source=price_source,
                value_base_ccy=value_base,
            )
        )

    # Cash accounts: one row per account, each converted to the portfolio's base currency
    accounts = db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio.id).all()
    cash_positions: List[CashPosition] = []
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
        balance = entry.balance if entry else 0.0
        if is_historical:
            fx = await price_client.get_fx_rate_on_date(acc.currency, base_ccy, as_of)
        else:
            fx = await price_client.get_fx_rate(acc.currency, base_ccy, force=force_refresh)
        fx = fx if fx is not None else 1.0
        value_base = balance * fx
        cash_total += value_base
        cash_positions.append(
            CashPosition(
                account_id=acc.id,
                account_name=acc.name,
                category=acc.category or AllocationCategory.CASH,
                currency=acc.currency,
                balance=balance,
                value_base_ccy=value_base,
                as_of=entry.entry_date if entry else None,
            )
        )

    return PortfolioSnapshot(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        base_currency=base_ccy,
        as_of=as_of,
        positions=positions,
        cash_positions=cash_positions,
        cash_total_base_ccy=cash_total,
        invested_total_base_ccy=invested_total,
        net_worth_base_ccy=invested_total + cash_total,
    )


async def compute_combined_net_worth_now(db: Session, base_currency: str = "EUR", as_of: Optional[date] = None) -> dict:
    """
    Combined net worth across all non-archived portfolios, converted into
    `base_currency`. Valued right now if `as_of` is omitted, or accurately
    as of a past date if given (used by the scheduler to backfill missed
    month-end snapshots with real historical prices instead of whatever
    happened to be live when it finally got a chance to run).
    """
    portfolios = db.query(models.Portfolio).filter(models.Portfolio.archived == False).all()  # noqa: E712

    net_worth_total = 0.0
    invested_total = 0.0
    cash_total = 0.0
    for p in portfolios:
        snap = await compute_portfolio_snapshot(db, p, as_of)
        if as_of and as_of < date.today():
            fx = await price_client.get_fx_rate_on_date(p.base_currency, base_currency, as_of)
        else:
            fx = await price_client.get_fx_rate(p.base_currency, base_currency)
        fx = fx if fx is not None else 1.0
        net_worth_total += snap.net_worth_base_ccy * fx
        invested_total += snap.invested_total_base_ccy * fx
        cash_total += snap.cash_total_base_ccy * fx

    return {"net_worth": net_worth_total, "invested_total": invested_total, "cash_total": cash_total}


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
