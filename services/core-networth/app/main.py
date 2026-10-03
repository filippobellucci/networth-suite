import asyncio
import colorsys
import csv
import io
import json
import logging
import math
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, Header, HTTPException, Query, Request, UploadFile, File
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas, valuation, xirr, backup, price_client, merchants, reports
from .config import MAX_BACKUP_UPLOAD_SIZE_BYTES
from .database import Base, engine, get_db
from .migrate import run_lightweight_migrations
from .scheduler import scheduler_loop, run_all_jobs

logger = logging.getLogger("core-networth")

Base.metadata.create_all(bind=engine)
run_lightweight_migrations(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fire-and-forget: runs once immediately (price refresh, snapshot
    # catch-up, backup), then keeps re-checking every few hours. Doesn't
    # block startup -- the API is usable immediately either way.
    asyncio.create_task(scheduler_loop())
    yield


app = FastAPI(title="Core Net Worth Service", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # locked down at the gateway layer instead
    allow_methods=["*"],
    allow_headers=["*"],
)


def _json_safe(value):
    """Replaces any non-finite float with its name, recursively."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)  # "inf", "-inf", "nan"
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    """
    FastAPI's own handler, with the offending value made serializable first.

    A validation error echoes the input that caused it back to the caller,
    and Python's json parser accepts the non-standard `NaN` and `Infinity`
    literals in a request body -- so refusing such a value produced an error
    response that could not itself be encoded, and the 422 turned into a
    500 while rendering. The refusal was correct; only the report of it
    failed. Same response shape as the default handler otherwise, so
    ordinary validation errors are unchanged.
    """
    return JSONResponse(status_code=422, content={"detail": _json_safe(jsonable_encoder(exc.errors()))})


@app.post("/scheduler/run-now")
async def trigger_scheduler_now():
    """Manually runs all scheduled jobs immediately, without waiting for the
    next automatic check -- handy for testing or right after adding data."""
    await run_all_jobs()
    return {"status": "done"}


@app.get("/health")
def health():
    return {"status": "ok"}


def _get_or_404(db: Session, model, row_id: str, label: str):
    """The row with this id, or a 404 saying which kind of thing wasn't found."""
    row = db.get(model, row_id)
    if not row:
        raise HTTPException(404, f"{label} not found")
    return row


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


def _replay_or_conflict(db: Session, key: str, endpoint: str) -> Optional[dict]:
    """The stored response for a key already used, None if the key is not in
    use at all, or the reason it can't be replayed."""
    existing = db.get(models.IdempotencyKey, key)
    if existing is None:
        # Pruned by another request's cleanup between the two statements.
        # Nothing left to replay; let the caller run normally.
        return None
    if existing.endpoint != endpoint:
        # Same key, different operation. Carrying on would run the mutation
        # and only then fail on the key's primary key -- a 500 for an
        # operation that actually went through, which a retry would then
        # duplicate. Refuse before touching anything instead.
        raise HTTPException(409, "This Idempotency-Key was already used for a different operation")
    if not existing.response_body:
        # Reserved but not yet filled in: the original request committed its
        # mutation and is a statement away from recording the response.
        raise HTTPException(409, "A request with this Idempotency-Key is still being processed -- retry shortly")
    return json.loads(existing.response_body)


def _check_idempotency(db: Session, key: Optional[str], endpoint: str) -> Optional[dict]:
    if not key:
        return None
    # Opportunistic cleanup on each use -- cheap at personal-finance request
    # volumes, and avoids needing a separate scheduled job just for this.
    cutoff = datetime.utcnow() - timedelta(hours=IDEMPOTENCY_TTL_HOURS)
    db.query(models.IdempotencyKey).filter(models.IdempotencyKey.created_at < cutoff).delete()
    return _replay_or_conflict(db, key, endpoint)


def _commit_with_idempotency(db: Session, key: Optional[str], endpoint: str) -> Optional[dict]:
    """
    Commits the mutation together with its idempotency key, which is what
    actually makes the guarantee hold.

    Checking for the key and then running the mutation is two steps, and two
    concurrent replays of one key both passed the check before either
    committed -- so both ran. That is precisely the case the header exists
    for: a client whose request timed out retries while the original is
    still in flight. Measured at 16 simultaneous replays of a single key,
    three transactions were created.

    Staging the key row in the SAME transaction as the mutation collapses
    those two steps into one: whichever request commits first owns the key,
    and the loser's INSERT violates the primary key, so its mutation rolls
    back with it rather than landing as a duplicate. The response body is
    filled in immediately afterwards (see _store_idempotency); a replay
    arriving in that gap is told to retry rather than being given a
    half-written record.

    Returns None when this request's own commit went through, or the
    response another request already stored when it won the key. An
    IntegrityError that is not about the key is re-raised untouched.
    """
    if key:
        db.add(models.IdempotencyKey(key=key, endpoint=endpoint, response_body=""))
    try:
        db.commit()
        return None
    except IntegrityError:
        db.rollback()
        replayed = _replay_or_conflict(db, key, endpoint) if key else None
        if replayed is None:
            raise
        logger.info("Idempotency key %r was already committed by a concurrent request; replaying it", key)
        return replayed


def _store_idempotency(db: Session, key: Optional[str], endpoint: str, response_dict: dict) -> None:
    """Fills in the response for the key reserved above, once the mutation's
    commit has produced it."""
    if not key:
        return
    row = db.get(models.IdempotencyKey, key)
    if row is None:
        # Pruned in the moment between the two commits -- rare, and only
        # costs this key its ability to replay.
        logger.warning("Idempotency key %r disappeared before its response could be recorded", key)
        return
    row.response_body = json.dumps(response_dict)
    db.commit()


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
    return _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")


@app.patch("/portfolios/{portfolio_id}", response_model=schemas.PortfolioOut)
def update_portfolio(portfolio_id: str, payload: schemas.PortfolioUpdate, db: Session = Depends(get_db)):
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@app.delete("/portfolios/{portfolio_id}", status_code=204)
def delete_portfolio(portfolio_id: str, db: Session = Depends(get_db)):
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")

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
    return _get_or_404(db, models.Asset, asset_id, "Asset")


@app.patch("/assets/{asset_id}", response_model=schemas.AssetOut)
def update_asset(asset_id: str, payload: schemas.AssetUpdate, db: Session = Depends(get_db)):
    a = _get_or_404(db, models.Asset, asset_id, "Asset")
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
    a = _get_or_404(db, models.Asset, asset_id, "Asset")
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
    _get_or_404(db, models.Asset, asset_id, "Asset")
    return {"asset_id": asset_id, "points": valuation.get_asset_manual_price_history(db, asset_id)}


@app.get("/assets/{asset_id}/growth")
async def asset_growth(asset_id: str, db: Session = Depends(get_db)):
    """Day/week/month/year/max price growth for a single asset."""
    asset = _get_or_404(db, models.Asset, asset_id, "Asset")
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
    h = _get_or_404(db, models.HoldingEntry, entry_id, "Holding entry")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(h, k, v)
    db.commit()
    db.refresh(h)
    return h


@app.delete("/holdings/{entry_id}", status_code=204)
def delete_holding_entry(entry_id: str, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, models.HoldingEntry, entry_id, "Holding entry"))
    db.commit()


# ---------------------------------------------------------------- Cash accounts
@app.post("/portfolios/{portfolio_id}/cash-accounts", response_model=schemas.CashAccountOut)
def create_cash_account(portfolio_id: str, payload: schemas.CashAccountCreate, db: Session = Depends(get_db)):
    _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
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
    acc = _get_or_404(db, models.CashAccount, account_id, "Cash account")
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
    acc = _get_or_404(db, models.CashAccount, account_id, "Cash account")
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
    acc = _get_or_404(db, models.CashAccount, account_id, "Cash account")
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
    cat = _get_or_404(db, models.ExpenseCategory, category_id, "Expense category")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(cat, k, v)
    db.commit()
    db.refresh(cat)
    return cat


@app.delete("/expense-categories/{category_id}", status_code=204)
def delete_expense_category(category_id: str, db: Session = Depends(get_db)):
    cat = _get_or_404(db, models.ExpenseCategory, category_id, "Expense category")
    # Deleting a category shouldn't delete the transactions tagged with it --
    # only the tag itself. Explicit, rather than relying on a DB-level
    # cascade, to match how the rest of this codebase handles related rows.
    db.query(models.CashTransaction).filter(models.CashTransaction.category_id == category_id).update(
        {"category_id": None}
    )
    # Merchant rules pointing at it go too: their counterparties become ones
    # still to map again, rather than rules silently categorizing into
    # nothing.
    db.query(models.MerchantRule).filter(models.MerchantRule.category_id == category_id).delete()
    db.query(models.Budget).filter(models.Budget.category_id == category_id).delete()
    db.delete(cat)
    db.commit()


# ---------------------------------------------------------------- Merchants (counterparty -> category)
def _validate_rule_target(db: Session, category_id: Optional[str], ignored: bool) -> None:
    if ignored and category_id:
        raise HTTPException(400, "A merchant is either mapped to a category or ignored, not both")
    if not ignored and not category_id:
        raise HTTPException(400, "Pick a category, or mark the merchant as ignored")
    if category_id:
        _get_or_404(db, models.ExpenseCategory, category_id, "Expense category")


@app.get("/merchants", response_model=List[schemas.MerchantOut])
def list_merchants(db: Session = Depends(get_db)):
    """
    Every counterparty seen on a transaction, with what currently decides its
    category -- the list a merchant still to map is found in. Built from the
    transactions themselves rather than kept as a separate registry, so it
    can never disagree with them. Most frequent first.
    """
    book = merchants.RuleBook(db)
    txns = (
        db.query(models.CashTransaction)
        .filter(models.CashTransaction.counterparty_key.isnot(None), models.CashTransaction.transfer_id.is_(None))
        .order_by(models.CashTransaction.entry_date, models.CashTransaction.created_at)
        .all()
    )
    groups: dict[str, dict] = {}
    for t in txns:
        g = groups.setdefault(t.counterparty_key, {
            "key": t.counterparty_key, "expense_count": 0, "income_count": 0,
            "expense_total": 0.0, "income_total": 0.0, "uncategorized_count": 0,
        })
        g["name"] = t.counterparty  # oldest-first, so the latest spelling wins
        g["last_date"] = t.entry_date
        if t.direction == models.TransactionDirection.INCOME:
            g["income_count"] += 1
            g["income_total"] += t.amount
        else:
            g["expense_count"] += 1
            g["expense_total"] += t.amount
        if t.category_id is None:
            g["uncategorized_count"] += 1

    out = []
    for key, g in groups.items():
        rule = book.match(key)
        status = "UNMAPPED" if rule is None else ("IGNORED" if rule.ignored else "MAPPED")
        out.append(schemas.MerchantOut(
            key=key, name=g["name"], status=status,
            rule=schemas.MerchantRuleOut.model_validate(rule) if rule else None,
            expense_count=g["expense_count"], income_count=g["income_count"],
            expense_total=round(g["expense_total"], 2), income_total=round(g["income_total"], 2),
            uncategorized_count=g["uncategorized_count"], last_date=g["last_date"],
        ))
    out.sort(key=lambda m: (-(m.expense_count + m.income_count), m.name.casefold()))
    return out


@app.get("/merchant-rules", response_model=List[schemas.MerchantRuleOut])
def list_merchant_rules(db: Session = Depends(get_db)):
    return db.query(models.MerchantRule).order_by(models.MerchantRule.match_type, models.MerchantRule.pattern).all()


@app.post("/merchant-rules", response_model=schemas.MerchantRuleSaved)
def create_merchant_rule(payload: schemas.MerchantRuleCreate, db: Session = Depends(get_db)):
    pattern = merchants.normalize(payload.pattern)
    if not pattern:
        raise HTTPException(400, "The merchant name can't be empty")
    if payload.match_type == models.MerchantMatchType.CONTAINS and len(pattern) < 3:
        # A one- or two-letter fragment would be part of nearly every name.
        raise HTTPException(400, "A 'contains' rule needs at least 3 characters")
    _validate_rule_target(db, payload.category_id, payload.ignored)
    existing = (
        db.query(models.MerchantRule)
        .filter(models.MerchantRule.pattern == pattern, models.MerchantRule.match_type == payload.match_type)
        .first()
    )
    if existing:
        raise HTTPException(409, "There's already a rule for this merchant -- edit that one instead")

    rule = models.MerchantRule(
        pattern=pattern, match_type=payload.match_type,
        category_id=None if payload.ignored else payload.category_id, ignored=payload.ignored,
    )
    db.add(rule)
    db.flush()
    applied = merchants.apply_to_uncategorized(db, rule) if payload.apply_to_past else 0
    db.commit()
    db.refresh(rule)
    return schemas.MerchantRuleSaved(rule=rule, applied=applied)


@app.patch("/merchant-rules/{rule_id}", response_model=schemas.MerchantRuleSaved)
def update_merchant_rule(rule_id: str, payload: schemas.MerchantRuleUpdate, db: Session = Depends(get_db)):
    rule = _get_or_404(db, models.MerchantRule, rule_id, "Merchant rule")
    data = payload.model_dump(exclude_unset=True)
    ignored = data.get("ignored", rule.ignored)
    # Picking a category un-ignores; ignoring drops the category.
    if data.get("category_id"):
        ignored = data.get("ignored", False)
    category_id = None if ignored else data.get("category_id", rule.category_id)
    _validate_rule_target(db, category_id, ignored)

    previous_category_id = rule.category_id
    rule.ignored = ignored
    rule.category_id = category_id
    db.flush()
    applied = 0
    if payload.recategorize_previous and previous_category_id != category_id:
        applied += merchants.move_from_category(db, rule, previous_category_id)
    if payload.apply_to_past:
        applied += merchants.apply_to_uncategorized(db, rule)
    db.commit()
    db.refresh(rule)
    return schemas.MerchantRuleSaved(rule=rule, applied=applied)


@app.delete("/merchant-rules/{rule_id}", status_code=204)
def delete_merchant_rule(rule_id: str, db: Session = Depends(get_db)):
    """Only the rule: transactions it already categorized keep their category."""
    db.delete(_get_or_404(db, models.MerchantRule, rule_id, "Merchant rule"))
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
    acc = _get_or_404(db, models.CashAccount, account_id, "Cash account")
    if acc.archived_at is not None:
        raise HTTPException(400, "This account has been removed and no longer accepts transactions")
    if acc.category == models.AllocationCategory.PENSION_FUND:
        raise HTTPException(400, "Pension Fund accounts stay hand-updated only -- they don't accept transactions")
    if payload.category_id:
        _get_or_404(db, models.ExpenseCategory, payload.category_id, "Expense category")
    _validate_refund_target(db, payload.refund_of_id, payload.direction, refund_account=acc)

    data = payload.model_dump(exclude={"amount", "quantity"})
    data["counterparty_key"] = merchants.normalize(payload.counterparty) or None
    if data["counterparty_key"] and not data.get("category_id"):
        data["category_id"] = merchants.RuleBook(db).category_for(data["counterparty_key"])
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
    replayed = _commit_with_idempotency(db, idempotency_key, "create_cash_transaction")
    if replayed is not None:
        return replayed
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
        fx = await price_client.fx_rate_at(from_acc.currency, to_acc.currency, payload.entry_date)
        received = round(payload.amount * fx, 4)

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
    replayed = _commit_with_idempotency(db, idempotency_key, "create_transfer")
    if replayed is not None:
        return replayed
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
    uncategorized: bool = False,
    filters: schemas.TransactionFilters = Depends(),
    db: Session = Depends(get_db),
):
    q = _transactions_query(db, None, account_id, uncategorized, filters)
    return _paginate(q, limit, offset).all()


def _apply_filters(q, f: "schemas.TransactionFilters"):
    """The search/filter parameters both transaction lists (and the CSV
    export) accept. Every one is optional; together they narrow (AND)."""
    T = models.CashTransaction
    if f.q and f.q.strip():
        # A literal search: % and _ typed by the user mean themselves.
        term = f.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{term}%"
        q = q.filter(or_(T.note.ilike(pattern, escape="\\"), T.counterparty.ilike(pattern, escape="\\")))
    if f.category_id:
        q = q.filter(T.category_id == f.category_id)
    if f.from_date:
        q = q.filter(T.entry_date >= f.from_date)
    if f.to_date:
        q = q.filter(T.entry_date <= f.to_date)
    if f.min_amount is not None:
        q = q.filter(T.amount >= f.min_amount)
    if f.max_amount is not None:
        q = q.filter(T.amount <= f.max_amount)
    if f.direction:
        q = q.filter(T.direction == f.direction)
    return q


def _only_uncategorized(q):
    """Transactions still waiting for a category: not transfer legs or
    refunds, which are deliberately never categorized."""
    return q.filter(
        models.CashTransaction.category_id.is_(None),
        models.CashTransaction.transfer_id.is_(None),
        models.CashTransaction.refund_of_id.is_(None),
    )


def _transactions_query(db: Session, portfolio_id, account_id, uncategorized, filters):
    q = db.query(models.CashTransaction)
    if portfolio_id:
        q = q.join(models.CashAccount, models.CashTransaction.account_id == models.CashAccount.id).filter(
            models.CashAccount.portfolio_id == portfolio_id
        )
    if account_id:
        q = q.filter(models.CashTransaction.account_id == account_id)
    if uncategorized:
        q = _only_uncategorized(q)
    q = _apply_filters(q, filters)
    return q.order_by(models.CashTransaction.entry_date.desc(), models.CashTransaction.created_at.desc())


@app.get("/transactions", response_model=List[schemas.CashTransactionOut])
def list_transactions(
    portfolio_id: Optional[str] = None,
    account_id: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    uncategorized: bool = False,
    filters: schemas.TransactionFilters = Depends(),
    db: Session = Depends(get_db),
):
    """Flat, filterable transaction list across accounts/portfolios -- backs the Expenses history/report views.
    `limit`/`offset` are optional -- omitted, every matching row is returned exactly as before."""
    q = _transactions_query(db, portfolio_id, account_id, uncategorized, filters)
    return _paginate(q, limit, offset).all()


@app.get("/transactions/export.csv")
def export_transactions_csv(
    portfolio_id: Optional[str] = None,
    account_id: Optional[str] = None,
    uncategorized: bool = False,
    filters: schemas.TransactionFilters = Depends(),
    db: Session = Depends(get_db),
):
    """
    The same list as GET /transactions, with the same filters, as a CSV file
    -- for a spreadsheet, or whoever does your taxes. Amounts are in each
    account's own currency (named in its own column), never converted:
    an export should say what actually happened.
    """
    q = _transactions_query(db, portfolio_id, account_id, uncategorized, filters)
    accounts: dict[str, models.CashAccount] = {}
    portfolios: dict[str, Optional[models.Portfolio]] = {}
    categories: dict[str, Optional[models.ExpenseCategory]] = {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "portfolio", "account", "type", "amount", "currency", "quantity",
                "category", "counterparty", "note", "transfer_id", "refund_of_id", "id"])
    for t in q.all():
        acc = accounts.setdefault(t.account_id, db.get(models.CashAccount, t.account_id))
        if acc.portfolio_id not in portfolios:
            portfolios[acc.portfolio_id] = db.get(models.Portfolio, acc.portfolio_id)
        portfolio = portfolios[acc.portfolio_id]
        category = None
        if t.category_id:
            if t.category_id not in categories:
                categories[t.category_id] = db.get(models.ExpenseCategory, t.category_id)
            category = categories[t.category_id]
        kind = "TRANSFER" if t.transfer_id else ("REFUND" if t.refund_of_id else t.direction.value)
        w.writerow([
            t.entry_date.isoformat(), portfolio.name if portfolio else "", acc.name, kind,
            # Signed, so a column sum is the net movement.
            f"{(t.amount if t.direction == models.TransactionDirection.INCOME else -t.amount):.2f}",
            acc.currency, "" if t.quantity is None else t.quantity,
            category.name if category else "", t.counterparty or "", t.note or "",
            t.transfer_id or "", t.refund_of_id or "", t.id,
        ])
    stamp = date.today().isoformat()
    return Response(
        # A BOM so Excel opens accented names (and the euro sign) correctly.
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="transactions-{stamp}.csv"'},
    )


@app.post("/cash-transactions/bulk-categorize", response_model=schemas.BulkCategorizeResult)
def bulk_categorize(payload: schemas.BulkCategorize, db: Session = Depends(get_db)):
    """
    Gives several transactions the same category (or clears it, with
    category_id null) in one go. All or nothing: an unknown id, or a transfer
    leg -- which is never categorized -- refuses the whole request, so a
    partial result never has to be worked out from what's on screen.
    """
    if payload.category_id:
        _get_or_404(db, models.ExpenseCategory, payload.category_id, "Expense category")
    ids = list(dict.fromkeys(payload.transaction_ids))
    txns = db.query(models.CashTransaction).filter(models.CashTransaction.id.in_(ids)).all()
    if len(txns) != len(ids):
        raise HTTPException(404, f"{len(ids) - len(txns)} of the selected transactions no longer exist -- reload and try again")
    if any(t.transfer_id is not None for t in txns):
        raise HTTPException(400, "Transfers can't be categorized -- leave them out of the selection")
    for t in txns:
        t.category_id = payload.category_id
    db.commit()
    return schemas.BulkCategorizeResult(updated=len(txns))


@app.post("/cash-transactions/{transaction_id}/convert-to-transfer", response_model=schemas.TransferOut)
async def convert_to_transfer(
    transaction_id: str, payload: schemas.ConvertToTransfer, db: Session = Depends(get_db)
):
    """
    Turns an existing income or expense into one leg of a transfer with
    another of your own accounts, creating only the missing leg there.

    For money moved between your own accounts when only one side of it is
    already recorded -- typically bank-sync capturing a top-up on the one
    linked account. Logging the other side as a fresh transfer would count
    the linked account's side twice; logging it as an ordinary expense would
    count it as spending. Here an INCOME came *from* the other account, an
    EXPENSE went *to* it; both legs then share `transfer_id` and leave the
    income/expense statistics, exactly like a transfer made from scratch.
    """
    txn = _get_or_404(db, models.CashTransaction, transaction_id, "Transaction")
    if txn.transfer_id is not None:
        raise HTTPException(400, "This is already part of a transfer")
    if txn.refund_of_id is not None:
        raise HTTPException(400, "A refund can't become a transfer -- remove the refund link first")
    if db.query(models.CashTransaction.id).filter(models.CashTransaction.refund_of_id == txn.id).first():
        raise HTTPException(400, "This expense has refunds logged against it, so it has to stay an ordinary expense")
    if payload.other_account_id == txn.account_id:
        raise HTTPException(400, "Pick a different account from the one this transaction is on")

    this_acc = db.get(models.CashAccount, txn.account_id)
    other_acc = _get_or_404(db, models.CashAccount, payload.other_account_id, "Cash account")
    if other_acc.archived_at is not None:
        raise HTTPException(400, "The other account has been removed and no longer accepts transfers")
    for acc, role in [(this_acc, "this transaction's"), (other_acc, "the other")]:
        if acc.category == models.AllocationCategory.PENSION_FUND:
            raise HTTPException(400, "Pension Fund accounts stay hand-updated only -- they don't accept transfers")
        if acc.kind == models.CashAccountKind.VOUCHER:
            raise HTTPException(400, f"Voucher accounts don't support transfers ({role} account is one)")

    # The other leg's amount in the other account's own currency, at the
    # transaction's own date -- the same historical/live split create_transfer
    # uses.
    if this_acc.currency == other_acc.currency:
        other_amount = txn.amount
    else:
        fx = await price_client.fx_rate_at(this_acc.currency, other_acc.currency, txn.entry_date)
        other_amount = round(txn.amount * fx, 4)

    transfer_id = models.gen_id()
    other_leg = models.CashTransaction(
        account_id=other_acc.id,
        entry_date=txn.entry_date,
        direction=(
            models.TransactionDirection.EXPENSE
            if txn.direction == models.TransactionDirection.INCOME
            else models.TransactionDirection.INCOME
        ),
        amount=other_amount,
        note=txn.note,
        transfer_id=transfer_id,
    )
    txn.transfer_id = transfer_id
    # A transfer leg is never categorized (and can't be edited to fix one).
    txn.category_id = None
    db.add(other_leg)
    db.commit()
    db.refresh(txn)
    db.refresh(other_leg)
    if txn.direction == models.TransactionDirection.EXPENSE:
        from_leg, to_leg = txn, other_leg
    else:
        from_leg, to_leg = other_leg, txn
    return schemas.TransferOut(transfer_id=transfer_id, from_leg=from_leg, to_leg=to_leg)


@app.get("/cash-transactions/{transaction_id}", response_model=schemas.CashTransactionOut)
def get_cash_transaction(transaction_id: str, db: Session = Depends(get_db)):
    """One transaction by id. bank-sync reads a card payment it captured
    while still pending back through this before correcting it once the bank
    books it, so a category or amount you already fixed by hand is left
    alone instead of being overwritten."""
    return _get_or_404(db, models.CashTransaction, transaction_id, "Transaction")


@app.patch("/cash-transactions/{transaction_id}", response_model=schemas.CashTransactionOut)
def update_cash_transaction(transaction_id: str, payload: schemas.CashTransactionUpdate, db: Session = Depends(get_db)):
    txn = _get_or_404(db, models.CashTransaction, transaction_id, "Transaction")
    if txn.transfer_id is not None:
        raise HTTPException(400, "This is one leg of a transfer -- delete and re-create the transfer instead of editing it")
    data = payload.model_dump(exclude_unset=True)
    if data.get("category_id"):
        _get_or_404(db, models.ExpenseCategory, data["category_id"], "Expense category")

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

    if "counterparty" in data:
        data["counterparty_key"] = merchants.normalize(data["counterparty"]) or None
        # Setting the counterparty of an uncategorized transaction (bank-sync
        # filling it in on ones captured before it sent one) categorizes it
        # the same way creating it with that counterparty would have.
        if data["counterparty_key"] and "category_id" not in data and txn.category_id is None:
            category_id = merchants.RuleBook(db).category_for(data["counterparty_key"])
            if category_id:
                data["category_id"] = category_id

    for k, v in data.items():
        setattr(txn, k, v)
    db.commit()
    db.refresh(txn)
    return txn


@app.delete("/cash-transactions/{transaction_id}", status_code=204)
def delete_cash_transaction(transaction_id: str, db: Session = Depends(get_db)):
    txn = _get_or_404(db, models.CashTransaction, transaction_id, "Transaction")
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
    found = await reports.flows(db, from_date, to_date, portfolio_id, currency, compute_refund_adjustments(db))
    total_income = sum(f.amount for f in found if f.income)
    total_expense = sum(f.amount for f in found if not f.income)
    name_of = _category_namer(db)
    return schemas.ExpenseSummary(
        from_date=from_date,
        to_date=to_date,
        currency=currency,
        total_income=total_income,
        total_expense=total_expense,
        net=total_income - total_expense,
        by_category=reports.by_category(found, income=False, name_of=name_of),
        # Income has categories too (a salary, a merchant's refund, money
        # from a friend) -- reported the same way, separately.
        income_by_category=reports.by_category(found, income=True, name_of=name_of),
    )


def _category_namer(db: Session):
    names: dict[Optional[str], str] = {}

    def name_of(category_id: Optional[str]) -> str:
        if category_id is None:
            return "Uncategorized"
        if category_id not in names:
            cat = db.get(models.ExpenseCategory, category_id)
            names[category_id] = cat.name if cat else "Unknown"
        return names[category_id]
    return name_of


@app.get("/expenses/monthly", response_model=List[schemas.MonthlyFlow])
async def expenses_monthly(
    months: int = Query(12, ge=1, le=120),
    portfolio_id: Optional[str] = None,
    currency: str = "EUR",
    db: Session = Depends(get_db),
):
    """
    Income, spending, what was left and the savings rate for each of the
    last `months` calendar months, the current one included (so far). Counted
    exactly like /expenses/summary.
    """
    last = reports.month_start(date.today())
    first = reports.add_months(last, -(months - 1))
    found = await reports.flows(db, first, date.today(), portfolio_id, currency, compute_refund_adjustments(db))
    return reports.monthly(found, first, last)


# ---------------------------------------------------------------- Budgets
@app.get("/budgets", response_model=List[schemas.BudgetOut])
def list_budgets(db: Session = Depends(get_db)):
    return db.query(models.Budget).order_by(models.Budget.created_at).all()


@app.post("/budgets", response_model=schemas.BudgetOut)
def create_budget(payload: schemas.BudgetCreate, db: Session = Depends(get_db)):
    _get_or_404(db, models.ExpenseCategory, payload.category_id, "Expense category")
    if db.query(models.Budget).filter(models.Budget.category_id == payload.category_id).first():
        raise HTTPException(409, "This category already has a budget -- edit that one instead")
    budget = models.Budget(category_id=payload.category_id, amount=payload.amount, currency=payload.currency)
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


@app.patch("/budgets/{budget_id}", response_model=schemas.BudgetOut)
def update_budget(budget_id: str, payload: schemas.BudgetUpdate, db: Session = Depends(get_db)):
    budget = _get_or_404(db, models.Budget, budget_id, "Budget")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(budget, k, v)
    db.commit()
    db.refresh(budget)
    return budget


@app.delete("/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: str, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, models.Budget, budget_id, "Budget"))
    db.commit()


@app.get("/budgets/progress", response_model=schemas.BudgetProgress)
async def budget_progress(
    month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    portfolio_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Each budget against what its category has spent in `month` (YYYY-MM,
    default the current one), counted like /expenses/summary and converted
    into the budget's own currency. NEAR from 90% of the budget, OVER past
    it. `elapsed_pct` -- how much of the month has gone by -- is what makes
    "60% spent" mean something: alarming on the 5th, fine on the 25th.
    """
    today = date.today()
    start = date(int(month[:4]), int(month[5:]), 1) if month else reports.month_start(today)
    end = reports.month_end(start)
    if start > today:
        elapsed = 0.0
    elif end < today:
        elapsed = 100.0
    else:
        elapsed = round(today.day / end.day * 100, 1)

    budgets = db.query(models.Budget).order_by(models.Budget.created_at).all()
    adjustments = compute_refund_adjustments(db)
    spent_by_currency: dict[str, dict[Optional[str], float]] = {}
    for currency in {b.currency for b in budgets}:
        found = await reports.flows(db, start, min(end, today), portfolio_id, currency, adjustments)
        totals: dict[Optional[str], float] = {}
        for f in found:
            if not f.income:
                totals[f.txn.category_id] = totals.get(f.txn.category_id, 0.0) + f.amount
        spent_by_currency[currency] = totals

    name_of = _category_namer(db)
    items = []
    for b in budgets:
        spent = round(spent_by_currency[b.currency].get(b.category_id, 0.0), 2)
        percent = round(spent / b.amount * 100, 1) if b.amount else 0.0
        items.append(schemas.BudgetProgressItem(
            budget_id=b.id, category_id=b.category_id, category_name=name_of(b.category_id),
            currency=b.currency, budget=b.amount, spent=spent, remaining=round(b.amount - spent, 2),
            percent=percent, status="OVER" if spent > b.amount else ("NEAR" if percent >= 90 else "OK"),
        ))
    return schemas.BudgetProgress(month=start.strftime("%Y-%m"), elapsed_pct=elapsed, items=items)


# ---------------------------------------------------------------- Recurring payments
@app.get("/recurring", response_model=schemas.RecurringReport)
async def recurring_payments(
    portfolio_id: Optional[str] = None,
    currency: str = "EUR",
    db: Session = Depends(get_db),
):
    """
    Subscriptions and other recurring payments, detected from the last ~13
    months of spending (see reports.detect_recurring): grouped by merchant --
    the counterparty a bank sent, or for one logged by hand its note -- with
    the cadence, what it costs per month, and any recent price change.
    `monthly_total` adds up the active ones.
    """
    today = date.today()
    found = await reports.flows(
        db, today - timedelta(days=400), today, portfolio_id, currency, compute_refund_adjustments(db)
    )
    expenses = []
    for f in found:
        if f.income:
            continue
        key = f.txn.counterparty_key or merchants.normalize(f.txn.note)
        name = f.txn.counterparty or f.txn.note or ""
        expenses.append((key, name, f.txn.entry_date, f.amount, f.txn.category_id))
    items = reports.detect_recurring(expenses, today)
    return schemas.RecurringReport(
        currency=currency,
        monthly_total=round(sum(i["monthly_cost"] for i in items if i["active"]), 2),
        items=items,
    )


# ---------------------------------------------------------------- Valuation / snapshots
@app.get("/portfolios/{portfolio_id}/snapshot", response_model=schemas.PortfolioSnapshot)
async def portfolio_snapshot(
    portfolio_id: str,
    as_of: Optional[date] = None,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    return await valuation.compute_portfolio_snapshot(db, p, as_of, force_refresh=refresh)


@app.get("/portfolios/{portfolio_id}/history", response_model=schemas.NetWorthHistory)
async def portfolio_history(portfolio_id: str, db: Session = Depends(get_db)):
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
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
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    return await valuation.compute_portfolio_growth(db, p)


@app.get("/networth/combined", response_model=schemas.NetWorthHistory)
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
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    return await xirr.compute_portfolio_xirr(db, p)


@app.get("/networth/combined/xirr")
async def combined_xirr(base_currency: str = "EUR", db: Session = Depends(get_db)):
    """Real (money-weighted) annualized return across ALL portfolios combined."""
    return await xirr.compute_combined_xirr(db, base_currency)


# `for_date` is typed as a date rather than parsed out of a string by hand:
# strptime on whatever arrived raised ValueError straight out of the
# endpoint, so `?for_date=nope` answered 500 instead of saying what was
# wrong with the request. FastAPI validates the type before the handler
# runs, which is what every other date parameter here already relies on
# (`as_of` on the snapshot endpoint has always answered 422).
@app.get("/portfolios/{portfolio_id}/intraday")
async def portfolio_intraday(portfolio_id: str, for_date: Optional[date] = None, db: Session = Depends(get_db)):
    """Hourly net worth for one trading day (defaults to today), using real
    intraday prices -- powers the "Day" range with broker-style granularity."""
    p = _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    target = for_date or date.today()
    points = await valuation.compute_portfolio_intraday(db, p, target)
    return {"portfolio_id": portfolio_id, "base_currency": p.base_currency, "date": target.isoformat(), "points": points}


@app.get("/networth/combined/intraday")
async def combined_intraday(for_date: Optional[date] = None, base_currency: str = "EUR", db: Session = Depends(get_db)):
    target = for_date or date.today()
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
    snapshot = existing or models.NetWorthSnapshot(snapshot_date=today, currency=payload.currency)
    snapshot.net_worth = totals["net_worth"]
    snapshot.invested_total = totals["invested_total"]
    snapshot.cash_total = totals["cash_total"]
    # Taking a snapshot by hand over a date the scheduler had already filled
    # in makes it a manual one -- leaving source="auto" made the table say
    # the number came from the month-end job when it didn't.
    snapshot.source = "manual"
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
    db.delete(_get_or_404(db, models.NetWorthSnapshot, snapshot_id, "Snapshot"))
    db.commit()
