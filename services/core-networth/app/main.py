import asyncio
import colorsys
import json
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, Header, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas, valuation, xirr, backup, price_client
from .config import MAX_BACKUP_UPLOAD_SIZE_BYTES
from .database import Base, engine, get_db
from .migrate import run_lightweight_migrations
from .scheduler import scheduler_loop, run_all_jobs

logger = logging.getLogger("core-networth")

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


def _paginate(query, limit: Optional[int], offset: int):
    """Shared by every list endpoint that accepts `limit`/`offset`: both are
    optional, and omitting `limit` returns every matching row exactly as
    before pagination was added."""
    query = query.offset(offset)
    return query.limit(limit) if limit is not None else query


# ---------------------------------------------------------------- Idempotency
# Optional `Idempotency-Key` header support for the financial-mutation POSTs
# most at risk from a client retrying a request it's unsure went through
# (create_cash_transaction, create_transfer, add_holding_entry): replaying
# the exact same key for the same endpoint returns the original response
# instead of creating a second transaction/transfer/holding entry. A client
# that never sends the header (the common case today) sees no change in
# behavior at all.
IDEMPOTENCY_TTL_HOURS = 24


def _check_idempotency(db: Session, key: Optional[str], endpoint: str) -> Optional[dict]:
    if not key:
        return None
    # Opportunistic cleanup on each use -- cheap at personal-finance request
    # volumes, and avoids needing a separate scheduled job just for this.
    cutoff = datetime.utcnow() - timedelta(hours=IDEMPOTENCY_TTL_HOURS)
    db.query(models.IdempotencyKey).filter(models.IdempotencyKey.created_at < cutoff).delete()
    existing = db.get(models.IdempotencyKey, key)
    if existing is None:
        return None
    if existing.endpoint == endpoint:
        return json.loads(existing.response_body)
    # Same key, different operation. Carrying on would run the mutation and
    # only then fail on the key's primary key -- a 500 for an operation that
    # actually went through, which a retry would then duplicate. Refuse
    # before touching anything instead.
    raise HTTPException(409, "This Idempotency-Key was already used for a different operation")


def _store_idempotency(db: Session, key: Optional[str], endpoint: str, response_dict: dict) -> None:
    if not key:
        return
    db.add(models.IdempotencyKey(key=key, endpoint=endpoint, response_body=json.dumps(response_dict)))
    try:
        db.commit()
    except IntegrityError:
        # Two identical requests raced past the check above and both ran.
        # The mutation is already committed and the response is the caller's
        # to keep; only this bookkeeping row is lost.
        db.rollback()
        logger.warning("Idempotency key %r was stored concurrently; keeping the first record", key)


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


async def _read_bounded(file: UploadFile) -> bytes:
    """
    Reads the upload in chunks and gives up as soon as it exceeds the limit.

    Reading it whole and *then* checking the length (what this used to do)
    meant the size cap protected nothing: a multi-gigabyte upload was already
    fully in memory by the time it was rejected, which on a small home server
    is enough to get the process killed.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_BACKUP_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                413, f"File too large -- max is {MAX_BACKUP_UPLOAD_SIZE_BYTES} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@app.post("/backup/preview")
async def backup_preview(file: UploadFile = File(...)):
    try:
        return backup.preview_uploaded_db(await _read_bounded(file))
    except backup.InvalidBackupError as e:
        raise HTTPException(400, str(e))


@app.post("/backup/restore")
async def backup_restore(file: UploadFile = File(...)):
    try:
        return backup.restore_db(await _read_bounded(file))
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

    # Deleting the portfolio cascades to its cash accounts and their
    # transactions -- including expenses that a refund in ANOTHER portfolio
    # points at. Those refunds must be un-linked first, exactly as
    # delete_cash_transaction already does: a refund whose target is gone is
    # skipped by compute_refund_adjustments, so it would silently stop
    # counting as income while still moving its account's balance -- money
    # that came back, visible nowhere in the reports, forever.
    # Expressed as a subquery rather than by reading the ids into Python and
    # passing them back as bind parameters: a busy ledger would hand SQLite
    # one parameter per transaction, and how many it accepts depends on how
    # that particular SQLite was built.
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
@app.post("/assets", response_model=schemas.AssetOut)
def create_asset(payload: schemas.AssetCreate, db: Session = Depends(get_db)):
    a = models.Asset(**payload.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@app.get("/assets", response_model=List[schemas.AssetOut])
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
def add_holding_entry(
    portfolio_id: str,
    payload: schemas.HoldingEntryCreate,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    cached = _check_idempotency(db, idempotency_key, "add_holding_entry")
    if cached is not None:
        return cached
    if not db.get(models.Portfolio, portfolio_id):
        raise HTTPException(404, "Portfolio not found")
    if not db.get(models.Asset, payload.asset_id):
        raise HTTPException(404, "Asset not found")
    h = models.HoldingEntry(portfolio_id=portfolio_id, **payload.model_dump())
    db.add(h)
    db.commit()
    db.refresh(h)
    out = schemas.HoldingEntryOut.model_validate(h)
    _store_idempotency(db, idempotency_key, "add_holding_entry", out.model_dump(mode="json"))
    return out


@app.get("/portfolios/{portfolio_id}/holdings", response_model=List[schemas.HoldingEntryOut])
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
def list_cash_accounts(portfolio_id: str, include_archived: bool = False, db: Session = Depends(get_db)):
    """
    Active accounts only by default -- that's what every picker offering a
    place to log something wants.

    `include_archived=True` is for the read-only views that describe rows
    which already exist: an archived account's past transactions never stop
    being real, and a caller that can't resolve their account has no way to
    label them or even to know which currency their amounts are in (the
    Expenses history used to fall back to EUR, so an archived dollar
    account's spending was rendered, silently, as euros).
    """
    q = db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio_id)
    if not include_archived:
        q = q.filter(models.CashAccount.archived_at.is_(None))
    return q.all()


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
    data = payload.model_dump(exclude_unset=True)
    # Pension Fund accounts must never accept transactions (enforced in
    # create_cash_transaction), and XIRR treats a Pension Fund's balance
    # changes as investment return rather than contributions/withdrawals --
    # so retagging an account *into* Pension Fund while it already has real
    # transaction history would let that history silently skew XIRR. The
    # loophole this closes: retag PENSION_FUND -> CASH, log transactions
    # (now allowed), then retag back to PENSION_FUND.
    if (
        data.get("category") == models.AllocationCategory.PENSION_FUND
        and acc.category != models.AllocationCategory.PENSION_FUND
        and db.query(models.CashTransaction.id).filter(models.CashTransaction.account_id == account_id).first()
    ):
        raise HTTPException(
            400,
            "Can't tag this account as Pension Fund: it already has transaction history, and Pension Fund "
            "accounts never accept transactions.",
        )
    for k, v in data.items():
        setattr(acc, k, v)
    db.commit()
    db.refresh(acc)
    return acc


@app.delete("/cash-accounts/{account_id}", status_code=204)
def delete_cash_account(account_id: str, db: Session = Depends(get_db)):
    acc = db.get(models.CashAccount, account_id)
    if not acc:
        raise HTTPException(404, "Cash account not found")
    # Archived, not hard-deleted -- see CashAccount.archived_at's docstring.
    # It disappears from every current list/total from now on, but its
    # existing balance/transaction rows stay untouched so past dates still
    # value correctly.
    #
    # now(), not utcnow(): this is the one timestamp in this service whose
    # DATE is compared against calendar days (valuation.py and xirr.py both
    # test `as_of < archived_at.date()`), and every date it is compared
    # against -- date.today(), an `as_of` the user picked, an entry_date the
    # browser built from its own calendar -- is a LOCAL day. Recording the
    # moment in UTC made the two disagree for the hours each day when the
    # local and UTC dates differ, and the account then either lingered in
    # today's totals after being removed (server behind UTC) or vanished
    # from yesterday's history as well (server ahead of it) -- the exact
    # retroactive rewrite this whole column exists to prevent.
    acc.archived_at = datetime.now()
    db.commit()


@app.post("/cash-accounts/{account_id}/balances", response_model=schemas.CashBalanceEntryOut)
def add_cash_balance(account_id: str, payload: schemas.CashBalanceEntryCreate, db: Session = Depends(get_db)):
    acc = db.get(models.CashAccount, account_id)
    if not acc:
        raise HTTPException(404, "Cash account not found")
    if acc.archived_at is not None:
        raise HTTPException(400, "This account has been removed and no longer accepts new balances")
    entry = models.CashBalanceEntry(account_id=account_id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# ---------------------------------------------------------------- Expense categories
def _next_category_color(db: Session) -> str:
    """
    Assigns each new category a color automatically -- no fixed swatch list
    to run out of. Hues are spread using the golden angle (~137.508 degrees),
    the standard trick for placing points around a circle one at a time so
    each new one lands as far as possible from every hue already assigned,
    however many categories accumulate.
    """
    n = db.query(models.ExpenseCategory).count()
    hue = (n * 137.508) % 360
    r, g, b = colorsys.hls_to_rgb(hue / 360, 0.50, 0.55)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


@app.post("/expense-categories", response_model=schemas.ExpenseCategoryOut)
def create_expense_category(payload: schemas.ExpenseCategoryCreate, db: Session = Depends(get_db)):
    cat = models.ExpenseCategory(name=payload.name, color=_next_category_color(db))
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@app.get("/expense-categories", response_model=List[schemas.ExpenseCategoryOut])
def list_expense_categories(db: Session = Depends(get_db)):
    return db.query(models.ExpenseCategory).order_by(models.ExpenseCategory.name).all()


@app.patch("/expense-categories/{category_id}", response_model=schemas.ExpenseCategoryOut)
def update_expense_category(category_id: str, payload: schemas.ExpenseCategoryUpdate, db: Session = Depends(get_db)):
    cat = db.get(models.ExpenseCategory, category_id)
    if not cat:
        raise HTTPException(404, "Expense category not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(cat, k, v)
    db.commit()
    db.refresh(cat)
    return cat


@app.delete("/expense-categories/{category_id}", status_code=204)
def delete_expense_category(category_id: str, db: Session = Depends(get_db)):
    cat = db.get(models.ExpenseCategory, category_id)
    if not cat:
        raise HTTPException(404, "Expense category not found")
    # Deleting a category shouldn't delete the transactions tagged with it --
    # only the tag itself. Explicit, rather than relying on a DB-level
    # cascade, to match how the rest of this codebase handles related rows.
    db.query(models.CashTransaction).filter(models.CashTransaction.category_id == category_id).update(
        {"category_id": None}
    )
    db.delete(cat)
    db.commit()


# ---------------------------------------------------------------- Cash transactions (Expenses feature)
def _validate_refund_target(
    db: Session,
    refund_of_id: Optional[str],
    direction: models.TransactionDirection,
    refund_account: Optional[models.CashAccount] = None,
) -> None:
    if refund_of_id is None:
        return
    if direction != models.TransactionDirection.INCOME:
        raise HTTPException(400, "Only an income can be marked as a refund")
    target = db.get(models.CashTransaction, refund_of_id)
    if not target:
        raise HTTPException(404, "The expense being refunded was not found")
    if target.direction != models.TransactionDirection.EXPENSE:
        raise HTTPException(400, "Only an expense can be refunded")
    if target.transfer_id is not None:
        raise HTTPException(400, "A transfer leg can't be refunded")
    if target.refund_of_id is not None:
        raise HTTPException(400, "A refund can't itself be refunded")

    # A refund is netted against its expense as a raw number, with no FX
    # conversion and no regard for which portfolio each side sits in (see
    # compute_refund_adjustments -- deliberately global, since a refund can
    # legitimately arrive outside the reporting window). That only holds
    # together while both sides are the same money in the same place: a USD
    # refund against a EUR expense would cancel it 1:1, and a refund logged
    # in another portfolio would shrink that portfolio's spending using
    # money that never entered it. The Expenses page only ever offers
    # same-portfolio expenses; this is the same rule the API couldn't skip.
    #
    # Checked only where the link is being created or changed (the caller
    # passes the account in that case): a row that predates this rule must
    # still be editable and deletable -- refusing to let its note be fixed
    # would leave it stuck for good.
    if refund_account is not None:
        target_account = db.get(models.CashAccount, target.account_id)
        if target_account is None:
            raise HTTPException(404, "The expense being refunded was not found")
        if target_account.portfolio_id != refund_account.portfolio_id:
            raise HTTPException(400, "A refund must be logged in the same portfolio as the expense it refunds")
        if target_account.currency != refund_account.currency:
            raise HTTPException(
                400,
                f"This expense is in {target_account.currency}: log its refund against a "
                f"{target_account.currency} account (refunds aren't currency-converted)",
            )


@app.post("/cash-accounts/{account_id}/transactions", response_model=schemas.CashTransactionOut)
def create_cash_transaction(
    account_id: str,
    payload: schemas.CashTransactionCreate,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    cached = _check_idempotency(db, idempotency_key, "create_cash_transaction")
    if cached is not None:
        return cached
    acc = db.get(models.CashAccount, account_id)
    if not acc:
        raise HTTPException(404, "Cash account not found")
    if acc.archived_at is not None:
        raise HTTPException(400, "This account has been removed and no longer accepts transactions")
    if acc.category == models.AllocationCategory.PENSION_FUND:
        raise HTTPException(400, "Pension Fund accounts stay hand-updated only -- they don't accept transactions")
    if payload.category_id and not db.get(models.ExpenseCategory, payload.category_id):
        raise HTTPException(404, "Expense category not found")
    _validate_refund_target(db, payload.refund_of_id, payload.direction, refund_account=acc)

    data = payload.model_dump(exclude={"amount", "quantity"})
    if acc.kind == models.CashAccountKind.VOUCHER:
        if payload.quantity is None:
            raise HTTPException(422, "quantity is required for a voucher account (not amount)")
        if not acc.unit_value:
            # Without this, amount silently freezes at 0 forever (unit_value
            # is only applied at write time, never recomputed retroactively),
            # producing a transaction that moves the unit-count balance but
            # is invisible to /expenses/summary and every euro-value report.
            raise HTTPException(400, "Set this account's unit value before logging voucher transactions")
        # Frozen at today's unit_value -- see CashTransaction.amount's
        # docstring for why a later unit_value change shouldn't rewrite this.
        amount = round(payload.quantity * acc.unit_value, 4)
        txn = models.CashTransaction(account_id=account_id, amount=amount, quantity=payload.quantity, **data)
    else:
        if payload.amount is None:
            raise HTTPException(422, "amount is required for this account (not quantity)")
        txn = models.CashTransaction(account_id=account_id, amount=payload.amount, quantity=None, **data)

    db.add(txn)
    db.commit()
    db.refresh(txn)
    out = schemas.CashTransactionOut.model_validate(txn)
    _store_idempotency(db, idempotency_key, "create_cash_transaction", out.model_dump(mode="json"))
    return out


@app.post("/transfers", response_model=schemas.TransferOut)
async def create_transfer(
    payload: schemas.TransferCreate,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Moves money between two of the user's own cash accounts -- e.g. topping
    up the Emergency Fund from everyday Cash. Recorded as a linked pair of
    ordinary CashTransaction rows (an EXPENSE on the source, an INCOME on
    the destination, sharing `transfer_id`) so account balances update
    exactly like any other transaction -- but /expenses/summary excludes
    both legs, since moving your own money between your own buckets is
    neither real spending nor real income and shouldn't distort those
    statistics.
    """
    cached = _check_idempotency(db, idempotency_key, "create_transfer")
    if cached is not None:
        return cached
    if payload.from_account_id == payload.to_account_id:
        raise HTTPException(400, "Source and destination must be different accounts")

    from_acc = db.get(models.CashAccount, payload.from_account_id)
    to_acc = db.get(models.CashAccount, payload.to_account_id)
    if not from_acc or not to_acc:
        raise HTTPException(404, "Cash account not found")

    for acc, role in [(from_acc, "source"), (to_acc, "destination")]:
        if acc.archived_at is not None:
            raise HTTPException(400, f"The {role} account has been removed and no longer accepts transfers")
        if acc.category == models.AllocationCategory.PENSION_FUND:
            raise HTTPException(400, "Pension Fund accounts stay hand-updated only -- they don't accept transfers")
        if acc.kind == models.CashAccountKind.VOUCHER:
            raise HTTPException(400, "Voucher accounts don't support transfers")

    if from_acc.currency == to_acc.currency:
        received = payload.amount
    else:
        is_historical = payload.entry_date < date.today()
        if is_historical:
            fx = await price_client.get_fx_rate_on_date(from_acc.currency, to_acc.currency, payload.entry_date)
        else:
            fx = await price_client.get_fx_rate(from_acc.currency, to_acc.currency)
        received = round(payload.amount * (fx if fx is not None else 1.0), 4)

    transfer_id = models.gen_id()
    from_leg = models.CashTransaction(
        account_id=from_acc.id,
        entry_date=payload.entry_date,
        direction=models.TransactionDirection.EXPENSE,
        amount=payload.amount,
        note=payload.note,
        transfer_id=transfer_id,
    )
    to_leg = models.CashTransaction(
        account_id=to_acc.id,
        entry_date=payload.entry_date,
        direction=models.TransactionDirection.INCOME,
        amount=received,
        note=payload.note,
        transfer_id=transfer_id,
    )
    db.add(from_leg)
    db.add(to_leg)
    db.commit()
    db.refresh(from_leg)
    db.refresh(to_leg)
    out = schemas.TransferOut(transfer_id=transfer_id, from_leg=from_leg, to_leg=to_leg)
    _store_idempotency(db, idempotency_key, "create_transfer", out.model_dump(mode="json"))
    return out


@app.get("/cash-accounts/{account_id}/transactions", response_model=List[schemas.CashTransactionOut])
def list_cash_account_transactions(
    account_id: str,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = (
        db.query(models.CashTransaction)
        .filter(models.CashTransaction.account_id == account_id)
        .order_by(models.CashTransaction.entry_date.desc(), models.CashTransaction.created_at.desc())
    )
    return _paginate(q, limit, offset).all()


@app.get("/transactions", response_model=List[schemas.CashTransactionOut])
def list_transactions(
    portfolio_id: Optional[str] = None,
    account_id: Optional[str] = None,
    category_id: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Flat, filterable transaction list across accounts/portfolios -- backs the Expenses history/report views.
    `limit`/`offset` are optional -- omitted, every matching row is returned exactly as before."""
    q = db.query(models.CashTransaction)
    if portfolio_id:
        q = q.join(models.CashAccount, models.CashTransaction.account_id == models.CashAccount.id).filter(
            models.CashAccount.portfolio_id == portfolio_id
        )
    if account_id:
        q = q.filter(models.CashTransaction.account_id == account_id)
    if category_id:
        q = q.filter(models.CashTransaction.category_id == category_id)
    if from_date:
        q = q.filter(models.CashTransaction.entry_date >= from_date)
    if to_date:
        q = q.filter(models.CashTransaction.entry_date <= to_date)
    q = q.order_by(models.CashTransaction.entry_date.desc(), models.CashTransaction.created_at.desc())
    return _paginate(q, limit, offset).all()


@app.patch("/cash-transactions/{transaction_id}", response_model=schemas.CashTransactionOut)
def update_cash_transaction(transaction_id: str, payload: schemas.CashTransactionUpdate, db: Session = Depends(get_db)):
    txn = db.get(models.CashTransaction, transaction_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    if txn.transfer_id is not None:
        raise HTTPException(400, "This is one leg of a transfer -- delete and re-create the transfer instead of editing it")
    data = payload.model_dump(exclude_unset=True)
    if data.get("category_id") and not db.get(models.ExpenseCategory, data["category_id"]):
        raise HTTPException(404, "Expense category not found")

    # Re-validate against the transaction's *final* state, not just the
    # fields the payload happens to touch -- changing only `direction` (say,
    # INCOME -> EXPENSE) while leaving an existing refund_of_id untouched
    # would otherwise leave a now-EXPENSE row still linked as a refund,
    # which compute_refund_adjustments() would then double-count.
    final_refund_of_id = data.get("refund_of_id", txn.refund_of_id)
    final_direction = data.get("direction", txn.direction)
    if final_refund_of_id == transaction_id:
        raise HTTPException(400, "A transaction can't refund itself")

    # The same rules _validate_refund_target enforces on a refund's *target*
    # at link time have to hold from the target's side too, or an edit can
    # quietly break a link that was valid when it was made: an expense other
    # refunds point at must stay an expense, and must not itself become a
    # refund. Either change leaves compute_refund_adjustments netting those
    # refunds against a row /expenses/summary no longer counts as spending,
    # so their own income silently stops being reported while still moving
    # the account balance. Deleting such an expense already un-links its
    # refunds explicitly; editing one must not be able to do it invisibly.
    if final_direction != models.TransactionDirection.EXPENSE or final_refund_of_id is not None:
        has_refunds = (
            db.query(models.CashTransaction.id)
            .filter(models.CashTransaction.refund_of_id == transaction_id)
            .first()
        )
        if has_refunds:
            raise HTTPException(
                400,
                "This expense has refunds logged against it, so it has to stay an ordinary expense. "
                "Remove those refunds first if you need to change it.",
            )

    acc = db.get(models.CashAccount, txn.account_id)
    # The full same-portfolio/same-currency check applies to a link being set
    # or changed by this request; an untouched one is only re-checked for the
    # direction/target rules, so an older row stays editable.
    _validate_refund_target(
        db,
        final_refund_of_id,
        final_direction,
        refund_account=acc if "refund_of_id" in data else None,
    )

    if acc.kind == models.CashAccountKind.VOUCHER:
        # On a voucher account `amount` is derived (quantity * unit_value)
        # and frozen at write time -- accepting a direct edit of it left the
        # euro figure in every report disagreeing with the unit count that
        # actually moves the balance, with no way to tell which was right.
        if "amount" in data:
            raise HTTPException(
                400, "On a voucher account edit `quantity` -- `amount` is derived from it and can't be set directly"
            )
        if "quantity" in data:
            if not acc.unit_value:
                raise HTTPException(400, "Set this account's unit value before editing voucher transactions")
            # Re-freeze the amount using *today's* unit_value, same as creating
            # a new transaction would -- editing a quantity is treated as a
            # fresh entry, not a correction that should preserve an old rate.
            data["amount"] = round(data["quantity"] * acc.unit_value, 4)
    else:
        data.pop("quantity", None)  # ignore quantity edits on a CURRENCY account

    for k, v in data.items():
        setattr(txn, k, v)
    db.commit()
    db.refresh(txn)
    return txn


@app.delete("/cash-transactions/{transaction_id}", status_code=204)
def delete_cash_transaction(transaction_id: str, db: Session = Depends(get_db)):
    txn = db.get(models.CashTransaction, transaction_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    if txn.transfer_id is not None:
        # Delete both legs together -- leaving one side behind would look
        # like a real, one-sided expense or income that never happened.
        db.query(models.CashTransaction).filter(models.CashTransaction.transfer_id == txn.transfer_id).delete()
    else:
        # Deleting an expense that already has refunds against it shouldn't
        # make that refunded money silently vanish from the statistics --
        # un-link any refunds instead, so they simply become ordinary,
        # full-value income from here on.
        db.query(models.CashTransaction).filter(models.CashTransaction.refund_of_id == transaction_id).update(
            {"refund_of_id": None}
        )
        db.delete(txn)
    db.commit()


def compute_refund_adjustments(db: Session) -> tuple[dict[str, float], dict[str, float]]:
    """
    Refunds (see CashTransaction.refund_of_id) don't rewrite the expense
    they offset -- they're ordinary income rows, dated whenever the money
    actually came back. This is where that gets reconciled for reporting:

    - effective_amounts[expense_id]: the expense's own amount minus every
      refund against it (in chronological order, so several partial
      refunds are applied correctly), floored at 0. This is what
      /expenses/summary should count as "spent" for that expense, however
      long ago it happened -- not its original, un-refunded amount.
    - excess_amounts[refund_id]: how much of a given refund went *beyond*
      what was left owed on its expense. Only this leftover portion should
      ever count as real income -- the rest already shows up as a smaller
      expense via effective_amounts, so counting it again as income too
      would double-count the same money.

    Computed globally (not date- or portfolio-filtered) since a refund
    outside a report's window can still reduce an expense inside it, and
    vice versa.
    """
    refunds = (
        db.query(models.CashTransaction)
        .filter(models.CashTransaction.refund_of_id.isnot(None))
        .order_by(models.CashTransaction.entry_date, models.CashTransaction.created_at)
        .all()
    )
    by_expense: dict[str, list[models.CashTransaction]] = {}
    for r in refunds:
        by_expense.setdefault(r.refund_of_id, []).append(r)

    effective_amounts: dict[str, float] = {}
    excess_amounts: dict[str, float] = {}
    for expense_id, rs in by_expense.items():
        expense = db.get(models.CashTransaction, expense_id)
        if not expense:
            # The expense this points at is gone. Every delete path that can
            # remove one un-links its refunds first (see
            # delete_cash_transaction / delete_portfolio), so this is only
            # reachable for a row that predates those or was edited straight
            # in the database -- but falling through with nothing recorded
            # made /expenses/summary read excess_amounts.get(id, 0.0) as
            # "fully absorbed" and drop the refund entirely: money that
            # really came back, visible in no report at all. With no expense
            # left to absorb any of it, all of it is ordinary income.
            for r in rs:
                excess_amounts[r.id] = r.amount
            continue
        remaining = expense.amount
        for r in rs:
            applied = min(r.amount, remaining)
            excess_amounts[r.id] = round(r.amount - applied, 4)
            remaining -= applied
        effective_amounts[expense_id] = round(remaining, 4)
    return effective_amounts, excess_amounts


@app.get("/expenses/summary", response_model=schemas.ExpenseSummary)
async def expenses_summary(
    from_date: date,
    to_date: date,
    portfolio_id: Optional[str] = None,
    currency: str = "EUR",
    db: Session = Depends(get_db),
):
    """
    Total income/expense and a per-category breakdown over a date range, all
    converted to `currency` using each transaction's own account currency and
    that day's historical FX rate -- the same approach used for historical
    net worth valuation, since accounts (and therefore their transactions)
    aren't necessarily all in the same currency. Internal transfers (see
    POST /transfers) are excluded entirely -- moving your own money between
    your own accounts isn't spending or income, and counting it as either
    would distort these very statistics. Refunded expenses count at their
    reduced, post-refund amount (see compute_refund_adjustments); a refund
    itself only counts as income for whatever portion exceeded its expense.
    """
    effective_amounts, excess_amounts = compute_refund_adjustments(db)

    q = db.query(models.CashTransaction).filter(
        models.CashTransaction.entry_date >= from_date,
        models.CashTransaction.entry_date <= to_date,
        models.CashTransaction.transfer_id.is_(None),
    )
    if portfolio_id:
        q = q.join(models.CashAccount, models.CashTransaction.account_id == models.CashAccount.id).filter(
            models.CashAccount.portfolio_id == portfolio_id
        )
    txns = q.all()

    total_income = 0.0
    total_expense = 0.0
    by_category: dict[Optional[str], float] = {}
    category_names: dict[Optional[str], str] = {}

    for t in txns:
        acc = db.get(models.CashAccount, t.account_id)
        fx = await price_client.get_fx_rate_on_date(acc.currency, currency, t.entry_date)
        fx = fx if fx is not None else 1.0

        if t.direction == models.TransactionDirection.INCOME:
            if t.refund_of_id is not None:
                raw_amount = excess_amounts.get(t.id, 0.0)
                if raw_amount <= 0:
                    continue  # fully absorbed by the expense it refunds -- see docstring above
            else:
                raw_amount = t.amount
            total_income += raw_amount * fx
        else:
            raw_amount = effective_amounts.get(t.id, t.amount)
            value = raw_amount * fx
            total_expense += value
            # Only expenses are broken down by category -- income isn't
            # currently tagged with a spending category.
            key = t.category_id
            by_category[key] = by_category.get(key, 0.0) + value
            if key and key not in category_names:
                cat = db.get(models.ExpenseCategory, key)
                category_names[key] = cat.name if cat else "Unknown"

    rows = [
        schemas.ExpenseCategoryTotal(
            category_id=cid,
            category_name=category_names.get(cid, "Uncategorized"),
            total=total,
        )
        for cid, total in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)
        if total > 0  # a fully-refunded expense nets to 0 -- drop it instead of showing an empty row
    ]

    return schemas.ExpenseSummary(
        from_date=from_date,
        to_date=to_date,
        currency=currency,
        total_income=total_income,
        total_expense=total_expense,
        net=total_income - total_expense,
        by_category=rows,
    )


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

    today = date.today()
    points = []
    for d in all_dates:
        total = 0.0
        for p in portfolios:
            snap = await valuation.compute_portfolio_snapshot(db, p, d)
            # That day's real rate for a past point, not today's. The
            # snapshot itself is already valued with historical prices AND
            # historical rates inside the portfolio's own base currency, so
            # converting THAT into the requested currency at today's rate
            # (what this used to do) mixed the two: a USD portfolio's whole
            # history moved every time EUR/USD did, redrawing past points
            # that had already been plotted. Same historical/live split as
            # compute_combined_net_worth_now, which this chart is otherwise
            # expected to agree with.
            if d < today:
                fx = await price_client.get_fx_rate_on_date(p.base_currency, base_currency, d)
            else:
                fx = await price_client.get_fx_rate(p.base_currency, base_currency)
            fx = fx if fx is not None else 1.0
            total += snap.net_worth_base_ccy * fx
        points.append(schemas.NetWorthPoint(date=d, net_worth_base_ccy=total))

    return schemas.NetWorthHistory(portfolio_id=None, base_currency=base_currency, points=points)


@app.get("/networth/combined/totals")
async def combined_totals(base_currency: str = "EUR", db: Session = Depends(get_db)):
    """
    Net worth / invested / cash across ALL non-archived portfolios right now,
    each converted into `base_currency`.

    Exists because summing the per-portfolio snapshots client-side is wrong
    the moment two portfolios have different base currencies: each snapshot
    is expressed in its OWN base currency, so adding them together silently
    treats, say, dollars as euros. Only this endpoint (and /networth/combined
    below) applies the conversion.
    """
    return await valuation.compute_combined_net_worth_now(db, base_currency)


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
        # Taking a snapshot by hand over a date the scheduler had already
        # filled in makes it a manual one -- leaving source="auto" made the
        # table say the number came from the month-end job when it didn't.
        existing.source = "manual"
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


@app.delete("/networth-snapshots/{snapshot_id}", status_code=204)
def delete_networth_snapshot(snapshot_id: str, db: Session = Depends(get_db)):
    snap = db.get(models.NetWorthSnapshot, snapshot_id)
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    db.delete(snap)
    db.commit()
