from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, valuation, xirr
from ..database import get_db
from ..helpers import _get_or_404, _paginate

router = APIRouter()


# ---------------------------------------------------------------- Valuation / snapshots
@router.get("/portfolios/{portfolio_id}/snapshot", response_model=schemas.PortfolioSnapshot)
async def portfolio_snapshot(
    portfolio_id: str,
    as_of: Optional[date] = None,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    return await valuation.compute_portfolio_snapshot(db, p, as_of, force_refresh=refresh)


@router.get("/portfolios/{portfolio_id}/history", response_model=schemas.NetWorthHistory)
async def portfolio_history(portfolio_id: str, db: Session = Depends(get_db)):
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    ledger = valuation.PortfolioLedger(db, p)
    dates = valuation.with_trailing_days_filled(ledger.entry_dates())
    await valuation.warm_prices(ledger, dates)
    points = []
    for d in dates:
        snap = await valuation.compute_portfolio_snapshot(db, p, d, ledger=ledger)
        points.append(schemas.NetWorthPoint(date=d, net_worth_base_ccy=snap.net_worth_base_ccy))
    return schemas.NetWorthHistory(portfolio_id=portfolio_id, base_currency=p.base_currency, points=points)


@router.get("/portfolios/{portfolio_id}/growth")
async def portfolio_growth(portfolio_id: str, db: Session = Depends(get_db)):
    """Day/month/year/max growth for a single portfolio -- start value, current
    value, and the change between them, each priced with real historical data."""
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    return await valuation.compute_portfolio_growth(db, p)


@router.get("/portfolios/{portfolio_id}/xirr")
async def portfolio_xirr(portfolio_id: str, db: Session = Depends(get_db)):
    """Real (money-weighted) annualized return for one portfolio, over the
    last year and since inception. See app/xirr.py for the methodology."""
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    return await xirr.compute_portfolio_xirr(db, p)


@router.get("/portfolios/{portfolio_id}/intraday")
async def portfolio_intraday(portfolio_id: str, for_date: Optional[date] = None, db: Session = Depends(get_db)):
    """Hourly net worth for one trading day (defaults to today), using real
    intraday prices -- powers the "Day" range with broker-style granularity."""
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    target = for_date or date.today()
    points = await valuation.compute_portfolio_intraday(db, p, target)
    return {"portfolio_id": portfolio_id, "base_currency": p.base_currency, "date": target.isoformat(), "points": points}


# ---------------------------------------------------------------- Historical net worth snapshots (frozen, manual)
@router.post("/portfolios/{portfolio_id}/networth-snapshots", response_model=schemas.NetWorthSnapshotOut)
async def take_networth_snapshot(portfolio_id: str, db: Session = Depends(get_db)):
    """
    Freezes this portfolio's net worth right now, in its base currency, into
    a permanent row. Calling this again on the same date overwrites that
    date's row rather than creating a duplicate, so pressing the button twice
    by mistake is harmless. Refused while a price or a rate is missing
    (why_snapshot_cannot_be_frozen).
    """
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    snap = await valuation.compute_portfolio_snapshot(db, p)
    problem = valuation.why_snapshot_cannot_be_frozen(snap)
    if problem:
        raise HTTPException(409, f"Snapshot not taken: {problem}, and a snapshot never changes once taken. "
                                 "Try again once prices are available (see \"Modules & Status\").")
    today = date.today()

    existing = (
        db.query(models.NetWorthSnapshot)
        .filter(
            models.NetWorthSnapshot.portfolio_id == portfolio_id,
            models.NetWorthSnapshot.snapshot_date == today,
            models.NetWorthSnapshot.currency == p.base_currency,
        )
        .first()
    )
    snapshot = existing or models.NetWorthSnapshot(
        portfolio_id=portfolio_id, snapshot_date=today, currency=p.base_currency
    )
    snapshot.net_worth = snap.net_worth_base_ccy
    snapshot.invested_total = snap.invested_total_base_ccy
    snapshot.cash_total = snap.cash_total_base_ccy
    # Taking a snapshot by hand over a date the scheduler had already filled
    # in makes it a manual one.
    snapshot.source = "manual"
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get("/portfolios/{portfolio_id}/networth-snapshots", response_model=List[schemas.NetWorthSnapshotOut])
def list_networth_snapshots(
    portfolio_id: str,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Every currency, not only the base one: a snapshot keeps the currency
    it was taken in even if the portfolio's base currency changes later."""
    q = (
        db.query(models.NetWorthSnapshot)
        .filter(models.NetWorthSnapshot.portfolio_id == portfolio_id)
        .order_by(models.NetWorthSnapshot.snapshot_date.desc(), models.NetWorthSnapshot.currency)
    )
    return _paginate(q, limit, offset).all()


@router.delete("/networth-snapshots/{snapshot_id}", status_code=204)
def delete_networth_snapshot(snapshot_id: str, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, models.NetWorthSnapshot, snapshot_id, "Snapshot"))
    db.commit()
