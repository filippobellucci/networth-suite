from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, price_client, schemas, valuation, xirr
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
    dates = valuation.distinct_entry_dates(db, portfolio_id)
    dates = valuation.with_trailing_days_filled(dates)
    points = []
    for d in dates:
        snap = await valuation.compute_portfolio_snapshot(db, p, d)
        points.append(schemas.NetWorthPoint(date=d, net_worth_base_ccy=snap.net_worth_base_ccy))
    return schemas.NetWorthHistory(portfolio_id=portfolio_id, base_currency=p.base_currency, points=points)


@router.get("/portfolios/{portfolio_id}/growth")
async def portfolio_growth(portfolio_id: str, db: Session = Depends(get_db)):
    """Day/month/year/max growth for a single portfolio -- start value, current
    value, and the change between them, each priced with real historical data."""
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    return await valuation.compute_portfolio_growth(db, p)


@router.get("/networth/combined", response_model=schemas.NetWorthHistory)
async def combined_net_worth(base_currency: str = "EUR", db: Session = Depends(get_db)):
    """Aggregated net worth across ALL non-archived portfolios, converted to `base_currency`."""
    portfolios = db.query(models.Portfolio).filter(models.Portfolio.archived == False).all()  # noqa: E712
    all_dates = sorted({d for p in portfolios for d in valuation.distinct_entry_dates(db, p.id)})
    all_dates = valuation.with_trailing_days_filled(all_dates)

    points = []
    for d in all_dates:
        total = 0.0
        for p in portfolios:
            snap = await valuation.compute_portfolio_snapshot(db, p, d)
            # That day's real rate for a past point, not today's: the
            # snapshot is already valued at that day's prices and rates in
            # the portfolio's own base currency, and converting it at
            # today's rate would redraw the whole history every time the
            # rate moved. Same split as compute_combined_net_worth_now,
            # which this chart is expected to agree with.
            fx = await price_client.fx_rate_at(p.base_currency, base_currency, d)
            total += snap.net_worth_base_ccy * fx
        points.append(schemas.NetWorthPoint(date=d, net_worth_base_ccy=total))

    return schemas.NetWorthHistory(portfolio_id=None, base_currency=base_currency, points=points)


@router.get("/networth/combined/totals")
async def combined_totals(base_currency: str = "EUR", db: Session = Depends(get_db)):
    """
    Net worth / invested / cash across ALL non-archived portfolios right now,
    each converted into `base_currency`.

    Each per-portfolio snapshot is in its OWN base currency, so they can't
    simply be summed client-side; this endpoint (and /networth/combined)
    applies the conversion.
    """
    return await valuation.compute_combined_net_worth_now(db, base_currency)


@router.get("/networth/combined/growth")
async def combined_growth(base_currency: str = "EUR", db: Session = Depends(get_db)):
    """Day/month/year/max growth across ALL portfolios combined."""
    return await valuation.compute_combined_growth(db, base_currency)


@router.get("/portfolios/{portfolio_id}/xirr")
async def portfolio_xirr(portfolio_id: str, db: Session = Depends(get_db)):
    """Real (money-weighted) annualized return for one portfolio, over the
    last year and since inception. See app/xirr.py for the methodology."""
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    return await xirr.compute_portfolio_xirr(db, p)


@router.get("/networth/combined/xirr")
async def combined_xirr(base_currency: str = "EUR", db: Session = Depends(get_db)):
    """Real (money-weighted) annualized return across ALL portfolios combined."""
    return await xirr.compute_combined_xirr(db, base_currency)


@router.get("/portfolios/{portfolio_id}/intraday")
async def portfolio_intraday(portfolio_id: str, for_date: Optional[date] = None, db: Session = Depends(get_db)):
    """Hourly net worth for one trading day (defaults to today), using real
    intraday prices -- powers the "Day" range with broker-style granularity."""
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    target = for_date or date.today()
    points = await valuation.compute_portfolio_intraday(db, p, target)
    return {"portfolio_id": portfolio_id, "base_currency": p.base_currency, "date": target.isoformat(), "points": points}


@router.get("/networth/combined/intraday")
async def combined_intraday(for_date: Optional[date] = None, base_currency: str = "EUR", db: Session = Depends(get_db)):
    target = for_date or date.today()
    points = await valuation.compute_combined_intraday(db, target, base_currency)
    return {"base_currency": base_currency, "date": target.isoformat(), "points": points}


# ---------------------------------------------------------------- Historical net worth snapshots (frozen, manual)
@router.post("/networth-snapshots", response_model=schemas.NetWorthSnapshotOut)
async def take_networth_snapshot(payload: schemas.NetWorthSnapshotCreate, db: Session = Depends(get_db)):
    """
    Freezes the combined net worth right now into a permanent row. Calling
    this again on the same date overwrites that date's row rather than
    creating a duplicate, so pressing the button twice by mistake is harmless.
    """
    totals = await valuation.compute_combined_net_worth_now(db, payload.currency)
    today = date.today()

    existing = (
        db.query(models.NetWorthSnapshot)
        .filter(
            models.NetWorthSnapshot.snapshot_date == today,
            models.NetWorthSnapshot.currency == payload.currency,
        )
        .first()
    )
    snapshot = existing or models.NetWorthSnapshot(snapshot_date=today, currency=payload.currency)
    snapshot.net_worth = totals["net_worth"]
    snapshot.invested_total = totals["invested_total"]
    snapshot.cash_total = totals["cash_total"]
    # Taking a snapshot by hand over a date the scheduler had already filled
    # in makes it a manual one.
    snapshot.source = "manual"
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get("/networth-snapshots", response_model=List[schemas.NetWorthSnapshotOut])
def list_networth_snapshots(
    currency: str = "EUR",
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = (
        db.query(models.NetWorthSnapshot)
        .filter(models.NetWorthSnapshot.currency == currency)
        .order_by(models.NetWorthSnapshot.snapshot_date.desc())
    )
    return _paginate(q, limit, offset).all()


@router.delete("/networth-snapshots/{snapshot_id}", status_code=204)
def delete_networth_snapshot(snapshot_id: str, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, models.NetWorthSnapshot, snapshot_id, "Snapshot"))
    db.commit()
