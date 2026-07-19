from datetime import date
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models, schemas, valuation
from .database import Base, engine, get_db
from .migrate import run_lightweight_migrations

Base.metadata.create_all(bind=engine)
run_lightweight_migrations(engine)

app = FastAPI(title="Core Net Worth Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # locked down at the gateway layer instead
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


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
    a = db.get(models.Asset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    db.delete(a)
    db.commit()


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
    return q.order_by(models.HoldingEntry.entry_date.desc()).all()


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
    points = []
    for d in dates:
        snap = await valuation.compute_portfolio_snapshot(db, p, d)
        points.append(schemas.NetWorthPoint(date=d, net_worth_base_ccy=snap.net_worth_base_ccy))
    return schemas.NetWorthHistory(portfolio_id=portfolio_id, base_currency=p.base_currency, points=points)


@app.get("/networth/combined", response_model=schemas.NetWorthHistory)
async def combined_net_worth(base_currency: str = "EUR", db: Session = Depends(get_db)):
    """Aggregated net worth across ALL non-archived portfolios, converted to `base_currency`."""
    portfolios = db.query(models.Portfolio).filter(models.Portfolio.archived == False).all()  # noqa: E712
    all_dates = sorted({d for p in portfolios for d in valuation.distinct_entry_dates(db, p.id)})

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
