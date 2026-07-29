import asyncio
from datetime import date, datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from . import models, schemas, valuation, xirr, backup
from .database import Base, engine, get_db
from .migrate import run_lightweight_migrations
from .scheduler import scheduler_loop, run_all_jobs

Base.metadata.create_all(bind=engine)
run_lightweight_migrations(engine)

app = FastAPI(title="Core Net Worth Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # locked down at the gateway layer instead
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _launch_scheduler():
    # Fire-and-forget: runs once immediately (price refresh, snapshot
    # catch-up, backup), then keeps re-checking every few hours. Doesn't
    # block startup -- the API is usable immediately either way.
    asyncio.create_task(scheduler_loop())


@app.post("/scheduler/run-now")
async def trigger_scheduler_now():
    """Manually runs all scheduled jobs immediately, without waiting for the
    next automatic check -- handy for testing or right after adding data."""
    await run_all_jobs()
    return {"status": "done"}


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------- Backup / Restore
@app.get("/backup/export")
def backup_export():
    try:
        data = backup.export_db_bytes()
    except backup.InvalidBackupError as e:
        raise HTTPException(400, str(e))
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="networth.db"'},
    )


@app.get("/backup/stats")
def backup_stats():
    return backup.get_stats()


@app.post("/backup/preview")
async def backup_preview(file: UploadFile = File(...)):
    try:
        return backup.preview_uploaded_db(await file.read())
    except backup.InvalidBackupError as e:
        raise HTTPException(400, str(e))


@app.post("/backup/restore")
async def backup_restore(file: UploadFile = File(...)):
    try:
        return backup.restore_db(await file.read())
    except backup.InvalidBackupError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- Portfolios
@app.post("/portfolios", response_model=schemas.PortfolioOut)
def create_portfolio(payload: schemas.PortfolioCreate, db: Session = Depends(get_db)):
    p = models.Portfolio(**payload.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@app.get("/portfolios", response_model=List[schemas.PortfolioOut])
def list_portfolios(include_archived: bool = False, db: Session = Depends(get_db)):
    q = db.query(models.Portfolio)
    if not include_archived:
        q = q.filter(models.Portfolio.archived == False)  # noqa: E712
    return q.order_by(models.Portfolio.created_at).all()


@app.get("/portfolios/{portfolio_id}", response_model=schemas.PortfolioOut)
def get_portfolio(portfolio_id: str, db: Session = Depends(get_db)):
    p = db.get(models.Portfolio, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return p


@app.patch("/portfolios/{portfolio_id}", response_model=schemas.PortfolioOut)
def update_portfolio(portfolio_id: str, payload: schemas.PortfolioUpdate, db: Session = Depends(get_db)):
    p = db.get(models.Portfolio, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@app.delete("/portfolios/{portfolio_id}", status_code=204)
def delete_portfolio(portfolio_id: str, db: Session = Depends(get_db)):
    p = db.get(models.Portfolio, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    db.delete(p)
    db.commit()


# ---------------------------------------------------------------- Assets (global catalogue)
@app.post("/assets", response_model=schemas.AssetOut)
def create_asset(payload: schemas.AssetCreate, db: Session = Depends(get_db)):
    a = models.Asset(**payload.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@app.get("/assets", response_model=List[schemas.AssetOut])
def list_assets(search: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.Asset)
    if search:
        like = f"%{search}%"
        q = q.filter((models.Asset.name.ilike(like)) | (models.Asset.ticker.ilike(like)))
    return q.order_by(models.Asset.name).all()


@app.get("/assets/{asset_id}", response_model=schemas.AssetOut)
def get_asset(asset_id: str, db: Session = Depends(get_db)):
    a = db.get(models.Asset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    return a


@app.patch("/assets/{asset_id}", response_model=schemas.AssetOut)
def update_asset(asset_id: str, payload: schemas.AssetUpdate, db: Session = Depends(get_db)):
    a = db.get(models.Asset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    db.commit()
    db.refresh(a)
    return a


@app.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: str, db: Session = Depends(get_db)):
    """
    Deletes the asset from the catalogue, plus every HoldingEntry referencing
    it across every portfolio (matching what the frontend's confirmation
    dialog already promises: "removed from every portfolio it appears in").

    This must be an explicit query, not just `db.delete(a)`: `Asset.holdings`
    has no ORM-level cascade (only `Portfolio.holdings`/`Portfolio.cash_accounts`
    do), and there's no SQLite foreign-key enforcement configured either, so
    without this, deleting an asset silently left its HoldingEntry rows
    behind with a now-dangling `asset_id` -- which then raised
    AttributeError deep in valuation.py (`h.asset` resolving to None) the
    next time that portfolio's snapshot/growth/XIRR was computed.
    """
    a = db.get(models.Asset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    db.query(models.HoldingEntry).filter(models.HoldingEntry.asset_id == asset_id).delete(synchronize_session=False)
    db.delete(a)
    db.commit()


@app.get("/assets/{asset_id}/manual-price-history")
def asset_manual_price_history(asset_id: str, db: Session = Depends(get_db)):
    """
    For assets with no ticker: every manually-entered price over time, across
    any portfolio. For ticker-based assets, the frontend fetches price
    history directly from the price-feed service instead (via the gateway),
    since that data doesn't depend on anything in this database.
    """
    asset = db.get(models.Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return {"asset_id": asset_id, "points": valuation.get_asset_manual_price_history(db, asset_id)}


@app.get("/assets/{asset_id}/growth")
async def asset_growth(asset_id: str, db: Session = Depends(get_db)):
    """Day/week/month/year/max price growth for a single asset."""
    asset = db.get(models.Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return await valuation.compute_asset_growth(db, asset)


# ---------------------------------------------------------------- Holding entries
@app.post("/portfolios/{portfolio_id}/holdings", response_model=schemas.HoldingEntryOut)
def add_holding_entry(portfolio_id: str, payload: schemas.HoldingEntryCreate, db: Session = Depends(get_db)):
    if not db.get(models.Portfolio, portfolio_id):
        raise HTTPException(404, "Portfolio not found")
    if not db.get(models.Asset, payload.asset_id):
        raise HTTPException(404, "Asset not found")
    h = models.HoldingEntry(portfolio_id=portfolio_id, **payload.model_dump())
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


@app.get("/portfolios/{portfolio_id}/holdings", response_model=List[schemas.HoldingEntryOut])
def list_holding_entries(portfolio_id: str, asset_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.HoldingEntry).filter(models.HoldingEntry.portfolio_id == portfolio_id)
    if asset_id:
        q = q.filter(models.HoldingEntry.asset_id == asset_id)
    return q.order_by(models.HoldingEntry.entry_date.desc(), models.HoldingEntry.created_at.desc()).all()


@app.patch("/holdings/{entry_id}", response_model=schemas.HoldingEntryOut)
def update_holding_entry(entry_id: str, payload: schemas.HoldingEntryUpdate, db: Session = Depends(get_db)):
    h = db.get(models.HoldingEntry, entry_id)
    if not h:
        raise HTTPException(404, "Holding entry not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(h, k, v)
    db.commit()
    db.refresh(h)
    return h


@app.delete("/holdings/{entry_id}", status_code=204)
def delete_holding_entry(entry_id: str, db: Session = Depends(get_db)):
    h = db.get(models.HoldingEntry, entry_id)
    if not h:
        raise HTTPException(404, "Holding entry not found")
    db.delete(h)
    db.commit()


# ---------------------------------------------------------------- Cash accounts
@app.post("/portfolios/{portfolio_id}/cash-accounts", response_model=schemas.CashAccountOut)
def create_cash_account(portfolio_id: str, payload: schemas.CashAccountCreate, db: Session = Depends(get_db)):
    if not db.get(models.Portfolio, portfolio_id):
        raise HTTPException(404, "Portfolio not found")
    acc = models.CashAccount(portfolio_id=portfolio_id, **payload.model_dump())
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@app.get("/portfolios/{portfolio_id}/cash-accounts", response_model=List[schemas.CashAccountOut])
def list_cash_accounts(portfolio_id: str, db: Session = Depends(get_db)):
    return db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio_id).all()


@app.patch("/cash-accounts/{account_id}", response_model=schemas.CashAccountOut)
def update_cash_account(account_id: str, payload: schemas.CashAccountUpdate, db: Session = Depends(get_db)):
    """
    Was previously missing: Portfolio, Asset, and HoldingEntry all have a
    PATCH endpoint, but CashAccount (also used for Emergency Fund and
    Pension Fund) didn't -- the only way to fix a typo in its name, change
    its currency, or re-tag its category was to delete and recreate it,
    losing its whole balance history in the process.
    """
    acc = db.get(models.CashAccount, account_id)
    if not acc:
        raise HTTPException(404, "Cash account not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(acc, k, v)
    db.commit()
    db.refresh(acc)
    return acc


@app.delete("/cash-accounts/{account_id}", status_code=204)
def delete_cash_account(account_id: str, db: Session = Depends(get_db)):
    acc = db.get(models.CashAccount, account_id)
    if not acc:
        raise HTTPException(404, "Cash account not found")
    db.delete(acc)
    db.commit()


@app.post("/cash-accounts/{account_id}/balances", response_model=schemas.CashBalanceEntryOut)
def add_cash_balance(account_id: str, payload: schemas.CashBalanceEntryCreate, db: Session = Depends(get_db)):
    if not db.get(models.CashAccount, account_id):
        raise HTTPException(404, "Cash account not found")
    entry = models.CashBalanceEntry(account_id=account_id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# ---------------------------------------------------------------- Valuation / snapshots
@app.get("/portfolios/{portfolio_id}/snapshot", response_model=schemas.PortfolioSnapshot)
async def portfolio_snapshot(
    portfolio_id: str,
    as_of: Optional[date] = None,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    p = db.get(models.Portfolio, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return await valuation.compute_portfolio_snapshot(db, p, as_of, force_refresh=refresh)


@app.get("/portfolios/{portfolio_id}/history", response_model=schemas.NetWorthHistory)
async def portfolio_history(portfolio_id: str, db: Session = Depends(get_db)):
    p = db.get(models.Portfolio, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    dates = valuation.distinct_entry_dates(db, portfolio_id)
    dates = valuation.with_trailing_days_filled(dates)
    points = []
    for d in dates:
        snap = await valuation.compute_portfolio_snapshot(db, p, d)
        points.append(schemas.NetWorthPoint(date=d, net_worth_base_ccy=snap.net_worth_base_ccy))
    return schemas.NetWorthHistory(portfolio_id=portfolio_id, base_currency=p.base_currency, points=points)


@app.get("/portfolios/{portfolio_id}/growth")
async def portfolio_growth(portfolio_id: str, db: Session = Depends(get_db)):
    """Day/month/year/max growth for a single portfolio -- start value, current
    value, and the change between them, each priced with real historical data."""
    p = db.get(models.Portfolio, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return await valuation.compute_portfolio_growth(db, p)


@app.get("/networth/combined", response_model=schemas.NetWorthHistory)
async def combined_net_worth(base_currency: str = "EUR", db: Session = Depends(get_db)):
    """Aggregated net worth across ALL non-archived portfolios, converted to `base_currency`."""
    portfolios = db.query(models.Portfolio).filter(models.Portfolio.archived == False).all()  # noqa: E712
    all_dates = sorted({d for p in portfolios for d in valuation.distinct_entry_dates(db, p.id)})
    all_dates = valuation.with_trailing_days_filled(all_dates)

    from . import price_client

    points = []
    for d in all_dates:
        total = 0.0
        for p in portfolios:
            snap = await valuation.compute_portfolio_snapshot(db, p, d)
            fx = await price_client.get_fx_rate(p.base_currency, base_currency)
            fx = fx if fx is not None else 1.0
            total += snap.net_worth_base_ccy * fx
        points.append(schemas.NetWorthPoint(date=d, net_worth_base_ccy=total))

    return schemas.NetWorthHistory(portfolio_id=None, base_currency=base_currency, points=points)


@app.get("/networth/combined/growth")
async def combined_growth(base_currency: str = "EUR", db: Session = Depends(get_db)):
    """Day/month/year/max growth across ALL portfolios combined."""
    return await valuation.compute_combined_growth(db, base_currency)


@app.get("/portfolios/{portfolio_id}/xirr")
async def portfolio_xirr(portfolio_id: str, db: Session = Depends(get_db)):
    """Real (money-weighted) annualized return for one portfolio, over the
    last year and since inception. See app/xirr.py for the methodology."""
    p = db.get(models.Portfolio, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return await xirr.compute_portfolio_xirr(db, p)


@app.get("/networth/combined/xirr")
async def combined_xirr(base_currency: str = "EUR", db: Session = Depends(get_db)):
    """Real (money-weighted) annualized return across ALL portfolios combined."""
    return await xirr.compute_combined_xirr(db, base_currency)


@app.get("/portfolios/{portfolio_id}/intraday")
async def portfolio_intraday(portfolio_id: str, for_date: Optional[str] = None, db: Session = Depends(get_db)):
    """Hourly net worth for one trading day (defaults to today), using real
    intraday prices -- powers the "Day" range with broker-style granularity."""
    p = db.get(models.Portfolio, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    target = datetime.strptime(for_date, "%Y-%m-%d").date() if for_date else date.today()
    points = await valuation.compute_portfolio_intraday(db, p, target)
    return {"portfolio_id": portfolio_id, "base_currency": p.base_currency, "date": target.isoformat(), "points": points}


@app.get("/networth/combined/intraday")
async def combined_intraday(for_date: Optional[str] = None, base_currency: str = "EUR", db: Session = Depends(get_db)):
    target = datetime.strptime(for_date, "%Y-%m-%d").date() if for_date else date.today()
    points = await valuation.compute_combined_intraday(db, target, base_currency)
    return {"base_currency": base_currency, "date": target.isoformat(), "points": points}


# ---------------------------------------------------------------- Historical net worth snapshots (frozen, manual)
@app.post("/networth-snapshots", response_model=schemas.NetWorthSnapshotOut)
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
    if existing:
        existing.net_worth = totals["net_worth"]
        existing.invested_total = totals["invested_total"]
        existing.cash_total = totals["cash_total"]
        db.commit()
        db.refresh(existing)
        return existing

    snapshot = models.NetWorthSnapshot(
        snapshot_date=today,
        currency=payload.currency,
        net_worth=totals["net_worth"],
        invested_total=totals["invested_total"],
        cash_total=totals["cash_total"],
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@app.get("/networth-snapshots", response_model=List[schemas.NetWorthSnapshotOut])
def list_networth_snapshots(currency: str = "EUR", db: Session = Depends(get_db)):
    return (
        db.query(models.NetWorthSnapshot)
        .filter(models.NetWorthSnapshot.currency == currency)
        .order_by(models.NetWorthSnapshot.snapshot_date.desc())
        .all()
    )


@app.delete("/networth-snapshots/{snapshot_id}", status_code=204)
def delete_networth_snapshot(snapshot_id: str, db: Session = Depends(get_db)):
    snap = db.get(models.NetWorthSnapshot, snapshot_id)
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    db.delete(snap)
    db.commit()
