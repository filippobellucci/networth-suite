from typing import List, Optional

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from .. import models, schemas, valuation
from ..database import get_db
from ..helpers import _check_idempotency, _commit_with_idempotency, _get_or_404, _paginate, _store_idempotency

router = APIRouter()


# ---------------------------------------------------------------- Portfolios
@router.post("/portfolios", response_model=schemas.PortfolioOut)
def create_portfolio(payload: schemas.PortfolioCreate, db: Session = Depends(get_db)):
    p = models.Portfolio(**payload.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/portfolios", response_model=List[schemas.PortfolioOut])
def list_portfolios(include_archived: bool = False, db: Session = Depends(get_db)):
    q = db.query(models.Portfolio)
    if not include_archived:
        q = q.filter(models.Portfolio.archived == False)  # noqa: E712
    return q.order_by(models.Portfolio.created_at).all()


@router.get("/portfolios/{portfolio_id}", response_model=schemas.PortfolioOut)
def get_portfolio(portfolio_id: str, db: Session = Depends(get_db)):
    return _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")


@router.patch("/portfolios/{portfolio_id}", response_model=schemas.PortfolioOut)
def update_portfolio(portfolio_id: str, payload: schemas.PortfolioUpdate, db: Session = Depends(get_db)):
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/portfolios/{portfolio_id}", status_code=204)
def delete_portfolio(portfolio_id: str, db: Session = Depends(get_db)):
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")

    # Deleting the portfolio cascades to its cash accounts and their
    # transactions -- including expenses that a refund in ANOTHER portfolio
    # points at. Those refunds are un-linked first, as delete_cash_transaction
    # does, so they keep counting as income. A subquery, not a list of ids:
    # SQLite caps the number of bind parameters.
    doomed_txns = (
        db.query(models.CashTransaction.id)
        .join(models.CashAccount, models.CashTransaction.account_id == models.CashAccount.id)
        .filter(models.CashAccount.portfolio_id == portfolio_id)
        .scalar_subquery()
    )
    db.query(models.CashTransaction).filter(models.CashTransaction.refund_of_id.in_(doomed_txns)).update(
        {"refund_of_id": None}, synchronize_session=False
    )

    db.delete(p)
    db.commit()


# ---------------------------------------------------------------- Assets (global catalogue)
@router.post("/assets", response_model=schemas.AssetOut)
def create_asset(payload: schemas.AssetCreate, db: Session = Depends(get_db)):
    a = models.Asset(**payload.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.get("/assets", response_model=List[schemas.AssetOut])
def list_assets(
    search: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(models.Asset)
    if search:
        like = f"%{search}%"
        q = q.filter((models.Asset.name.ilike(like)) | (models.Asset.ticker.ilike(like)))
    return _paginate(q.order_by(models.Asset.name), limit, offset).all()


@router.get("/assets/{asset_id}", response_model=schemas.AssetOut)
def get_asset(asset_id: str, db: Session = Depends(get_db)):
    return _get_or_404(db, models.Asset, asset_id, "Asset")


@router.patch("/assets/{asset_id}", response_model=schemas.AssetOut)
def update_asset(asset_id: str, payload: schemas.AssetUpdate, db: Session = Depends(get_db)):
    a = _get_or_404(db, models.Asset, asset_id, "Asset")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: str, db: Session = Depends(get_db)):
    """
    Deletes the asset from the catalogue, plus every HoldingEntry referencing
    it across every portfolio ("removed from every portfolio it appears in",
    as the frontend's confirmation says). An explicit query: `Asset.holdings`
    has no ORM cascade and SQLite enforces no foreign keys.
    """
    a = _get_or_404(db, models.Asset, asset_id, "Asset")
    db.query(models.HoldingEntry).filter(models.HoldingEntry.asset_id == asset_id).delete(synchronize_session=False)
    db.delete(a)
    db.commit()


@router.get("/assets/{asset_id}/manual-price-history")
def asset_manual_price_history(asset_id: str, db: Session = Depends(get_db)):
    """
    For assets with no ticker: every manually-entered price over time, across
    any portfolio. For ticker-based assets, the frontend fetches price
    history directly from the price-feed service instead (via the gateway),
    since that data doesn't depend on anything in this database.
    """
    _get_or_404(db, models.Asset, asset_id, "Asset")
    return {"asset_id": asset_id, "points": valuation.get_asset_manual_price_history(db, asset_id)}


@router.get("/assets/{asset_id}/growth")
async def asset_growth(asset_id: str, db: Session = Depends(get_db)):
    """Day/week/month/year/max price growth for a single asset."""
    asset = _get_or_404(db, models.Asset, asset_id, "Asset")
    return await valuation.compute_asset_growth(db, asset)


# ---------------------------------------------------------------- Holding entries
@router.post("/portfolios/{portfolio_id}/holdings", response_model=schemas.HoldingEntryOut)
def add_holding_entry(
    portfolio_id: str,
    payload: schemas.HoldingEntryCreate,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    cached = _check_idempotency(db, idempotency_key, "add_holding_entry")
    if cached is not None:
        return cached
    _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    _get_or_404(db, models.Asset, payload.asset_id, "Asset")
    h = models.HoldingEntry(portfolio_id=portfolio_id, **payload.model_dump())
    db.add(h)
    replayed = _commit_with_idempotency(db, idempotency_key, "add_holding_entry")
    if replayed is not None:
        return replayed
    db.refresh(h)
    out = schemas.HoldingEntryOut.model_validate(h)
    _store_idempotency(db, idempotency_key, "add_holding_entry", out.model_dump(mode="json"))
    return out


@router.get("/portfolios/{portfolio_id}/holdings", response_model=List[schemas.HoldingEntryOut])
def list_holding_entries(
    portfolio_id: str,
    asset_id: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(models.HoldingEntry).filter(models.HoldingEntry.portfolio_id == portfolio_id)
    if asset_id:
        q = q.filter(models.HoldingEntry.asset_id == asset_id)
    q = q.order_by(models.HoldingEntry.entry_date.desc(), models.HoldingEntry.created_at.desc())
    return _paginate(q, limit, offset).all()


@router.patch("/holdings/{entry_id}", response_model=schemas.HoldingEntryOut)
def update_holding_entry(entry_id: str, payload: schemas.HoldingEntryUpdate, db: Session = Depends(get_db)):
    h = _get_or_404(db, models.HoldingEntry, entry_id, "Holding entry")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(h, k, v)
    db.commit()
    db.refresh(h)
    return h


@router.delete("/holdings/{entry_id}", status_code=204)
def delete_holding_entry(entry_id: str, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, models.HoldingEntry, entry_id, "Holding entry"))
    db.commit()
