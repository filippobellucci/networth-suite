import bisect
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import List, Optional, Callable, Awaitable

from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from . import models, price_client
from .models import AllocationCategory, TransactionDirection, CashAccountKind
from .schemas import HoldingPosition, CashPosition, PortfolioSnapshot


def resolve_cash_balance(db: Session, account: models.CashAccount, as_of: date) -> tuple[float, Optional[date]]:
    """
    A cash account's balance as of a given date is no longer a single
    editable field -- it's the most recent manually-set CashBalanceEntry on
    or before `as_of` (its "opening balance"; 0.0 if none exists yet), plus
    every CashTransaction (income/expense) dated after that entry and on or
    before `as_of`. In other words: manual entries anchor the balance,
    transactions move it from there -- exactly like an opening balance
    followed by a bank statement's line items.

    For a VOUCHER account, everything above is in *unit count* rather than
    money -- CashBalanceEntry.balance and each transaction's `quantity`
    (never `amount`) are what's summed, since the number of vouchers is what
    actually accumulates; converting that count to money using unit_value is
    the caller's job (see compute_portfolio_snapshot below), not this
    function's, so this stays the one place both account kinds share.

    A transaction dated the exact same day as the opening balance entry
    still counts (ordered by `created_at`) -- see the same-day handling
    below for why a naive date-only comparison would silently drop it.

    Returns (raw, most_recent_event_date) -- `raw` is a money balance for a
    CURRENCY account or a unit count for a VOUCHER account. The second value
    is only used for display ("as of ...") and is None if the account has no
    balance entry and no transaction at or before `as_of` yet.
    """
    is_voucher = account.kind == CashAccountKind.VOUCHER
    anchor = (
        db.query(models.CashBalanceEntry)
        .filter(
            models.CashBalanceEntry.account_id == account.id,
            models.CashBalanceEntry.entry_date <= as_of,
        )
        .order_by(
            models.CashBalanceEntry.entry_date.desc(),
            models.CashBalanceEntry.created_at.desc(),
        )
        .first()
    )
    raw = anchor.balance if anchor else 0.0
    last_event = anchor.entry_date if anchor else None

    txns_query = db.query(models.CashTransaction).filter(
        models.CashTransaction.account_id == account.id,
        models.CashTransaction.entry_date <= as_of,
    )
    if anchor:
        # A transaction logged the SAME DAY the opening balance was set (the
        # common case: create the account and immediately log its first
        # movement) must still count -- a strict `entry_date > anchor date`
        # here would silently drop it, since both share that date. Fall back
        # to `created_at` to order same-day events: only transactions that
        # happened after the anchor was recorded count towards it, so
        # re-setting the opening balance later that same day doesn't
        # double-count whatever was logged before it.
        #
        # Both `created_at` columns are nullable (rows created before that
        # column existed have none -- see their docstrings), and SQLAlchemy
        # rejects `>` against a Python None outright (it has to be `is_()`),
        # so a same-day comparison can't unconditionally use `>`. Missing
        # data defaults to *including* the transaction rather than excluding
        # it -- excluding same-day transactions is the exact bug this whole
        # block exists to avoid, so "unknown" should fail open, not closed.
        if anchor.created_at is not None:
            same_day = and_(
                models.CashTransaction.entry_date == anchor.entry_date,
                or_(
                    models.CashTransaction.created_at.is_(None),
                    models.CashTransaction.created_at > anchor.created_at,
                ),
            )
        else:
            same_day = models.CashTransaction.entry_date == anchor.entry_date
        txns_query = txns_query.filter(or_(models.CashTransaction.entry_date > anchor.entry_date, same_day))
    txns = txns_query.order_by(models.CashTransaction.entry_date.asc()).all()

    for t in txns:
        delta = (t.quantity or 0.0) if is_voucher else t.amount
        raw += delta if t.direction == TransactionDirection.INCOME else -delta
        if last_event is None or t.entry_date > last_event:
            last_event = t.entry_date

    return raw, last_event


async def _resolve_fx(from_ccy: str, to_ccy: str, as_of: date, is_historical: bool, force_refresh: bool = False) -> float:
    """
    Shared by every place this module converts between currencies: a real
    historical rate for a past date, today's rate otherwise. Falls back to
    1.0 if a rate genuinely can't be found -- same behaviour as before this
    was pulled out of three near-identical copies of this same logic, one
    per caller.
    """
    if is_historical:
        fx = await price_client.get_fx_rate_on_date(from_ccy, to_ccy, as_of)
    else:
        fx = await price_client.get_fx_rate(from_ccy, to_ccy, force=force_refresh)
    return fx if fx is not None else 1.0


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
        .order_by(
            models.HoldingEntry.asset_id,
            models.HoldingEntry.entry_date.desc(),
            models.HoldingEntry.created_at.desc(),
        )
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
                    # Historical fetch failed -- network hiccup, or (very
                    # commonly) the price-feed cache was just wiped by a
                    # container restart and every ticker needs a fresh fetch
                    # at once. Rather than counting this position as worth
                    # zero -- catastrophic if this snapshot is the frozen,
                    # permanent kind taken by the month-end scheduler --
                    # fall back to the latest available price as an
                    # approximation. Same resilience compute_asset_growth's
                    # value_at() already uses for the per-asset chart; this
                    # closes the same gap for portfolio-level valuation.
                    live = await price_client.get_latest_price(asset.ticker)
                    if live:
                        price = live["price"]
                        price_ccy = live.get("currency", asset.currency)
                        price_source = "historical_fallback"
            else:
                live = await price_client.get_latest_price(asset.ticker, force=force_refresh)
                if live:
                    price = live["price"]
                    price_ccy = live.get("currency", asset.currency)
                    price_source = "live"

        value_base = None
        if price is not None:
            # Either a real historical rate for a past date, or today's rate
            # for a live/today valuation -- and also today's rate for a
            # historical fallback, since in that case the price itself is
            # already today's, so pairing it with a past date's FX rate
            # would mix a today price with a stale rate.
            effective_historical = is_historical and price_source != "historical_fallback"
            fx = await _resolve_fx(price_ccy, base_ccy, as_of, effective_historical, force_refresh)
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

    # Cash accounts: one row per account, each converted to the portfolio's base currency.
    # An archived account (see CashAccount.archived_at) is still included for
    # any `as_of` date strictly before the day it was archived -- it
    # genuinely existed and contributed then -- but excluded from that day
    # onward (today included), so "removing" it takes effect immediately
    # without rewriting what already happened in the past.
    accounts = [
        acc
        for acc in db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio.id).all()
        if acc.archived_at is None or as_of < acc.archived_at.date()
    ]
    cash_positions: List[CashPosition] = []
    cash_total = 0.0
    for acc in accounts:
        raw, as_of_event = resolve_cash_balance(db, acc, as_of)
        is_voucher = acc.kind == CashAccountKind.VOUCHER
        # For a VOUCHER account `raw` is a unit count -- convert to money
        # using today's unit_value before FX, same as a CURRENCY account's
        # `raw` is already money in its own currency.
        native_value = raw * (acc.unit_value or 0.0) if is_voucher else raw
        fx = await _resolve_fx(acc.currency, base_ccy, as_of, is_historical, force_refresh)
        value_base = native_value * fx
        cash_total += value_base
        cash_positions.append(
            CashPosition(
                account_id=acc.id,
                account_name=acc.name,
                category=acc.category or AllocationCategory.CASH,
                currency=acc.currency,
                kind=acc.kind,
                unit_value=acc.unit_value,
                balance=raw,
                value_base_ccy=value_base,
                as_of=as_of_event,
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
        fx = await _resolve_fx(p.base_currency, base_currency, as_of or date.today(), bool(as_of and as_of < date.today()))
        net_worth_total += snap.net_worth_base_ccy * fx
        invested_total += snap.invested_total_base_ccy * fx
        cash_total += snap.cash_total_base_ccy * fx

    return {"net_worth": net_worth_total, "invested_total": invested_total, "cash_total": cash_total}


def distinct_entry_dates(db: Session, portfolio_id: Optional[str] = None) -> List[date]:
    """All dates on which something changed (holdings, cash balance edits, or
    cash transactions), used to build the history chart."""
    q1 = db.query(models.HoldingEntry.entry_date)
    q2 = db.query(models.CashBalanceEntry.entry_date).join(
        models.CashAccount, models.CashBalanceEntry.account_id == models.CashAccount.id
    )
    q3 = db.query(models.CashTransaction.entry_date).join(
        models.CashAccount, models.CashTransaction.account_id == models.CashAccount.id
    )
    if portfolio_id:
        q1 = q1.filter(models.HoldingEntry.portfolio_id == portfolio_id)
        q2 = q2.filter(models.CashAccount.portfolio_id == portfolio_id)
        q3 = q3.filter(models.CashAccount.portfolio_id == portfolio_id)
    dates = {d for (d,) in q1.all()} | {d for (d,) in q2.all()} | {d for (d,) in q3.all()}
    return sorted(dates)


def with_trailing_days_filled(dates: List[date], today: Optional[date] = None) -> List[date]:
    """
    The live chart always needs to reach today, but a single re-appended
    "today" point that's never actually stored creates a visible bug: it
    replaces itself day after day instead of leaving a trail, so the chart
    looks like it jumps straight from the last real entry to whatever
    "today" happens to be, silently skipping every day in between that was
    never revisited. Filling in one point for every day since the last real
    entry (not just the latest one) fixes that -- each day's point becomes
    real and stable the moment it's first computed, and stays that way.
    """
    today = today or date.today()
    if not dates:
        return [today]
    last = dates[-1]
    if last >= today:
        return dates
    filler = [last + timedelta(days=i) for i in range(1, (today - last).days + 1)]
    return dates + filler


def _subtract_months(d: date, months: int) -> date:
    """Subtracts whole months, clamping the day-of-month so e.g. Mar 31 minus
    one month lands on Feb 28/29 instead of overflowing into March."""
    total = d.month - 1 - months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


async def _build_growth_stats(
    value_at: Callable[[date], Awaitable[float]], today: date, earliest: date
) -> dict:
    """
    Shared by both compute_portfolio_growth and compute_combined_growth:
    given a function that values the portfolio(s) as of any date, returns
    day/month/year/max growth (start value, current value, absolute and
    percentage change), each computed with real historical prices for the
    start date -- not just whatever data point happened to already exist.
    """
    current = await value_at(today)

    periods = {
        "day": max(today - timedelta(days=1), earliest),
        "week": max(today - timedelta(days=7), earliest),
        "month": max(_subtract_months(today, 1), earliest),
        "year": max(_subtract_months(today, 12), earliest),
        "max": earliest,
    }

    result: dict = {"current": current}
    for key, start_date in periods.items():
        if start_date >= today:
            result[key] = None
            continue
        start_value = await value_at(start_date)
        change = current - start_value
        change_pct = (change / start_value * 100) if start_value else None
        result[key] = {
            "start_date": start_date.isoformat(),
            "start_value": start_value,
            "current_value": current,
            "change": change,
            "change_pct": change_pct,
        }
    return result


async def compute_portfolio_growth(db: Session, portfolio: models.Portfolio) -> dict:
    today = date.today()
    entry_dates = distinct_entry_dates(db, portfolio.id)
    earliest = entry_dates[0] if entry_dates else today

    async def value_at(as_of: date) -> float:
        snap = await compute_portfolio_snapshot(db, portfolio, as_of)
        return snap.net_worth_base_ccy

    return await _build_growth_stats(value_at, today, earliest)


async def compute_combined_growth(db: Session, base_currency: str = "EUR") -> dict:
    today = date.today()
    entry_dates = distinct_entry_dates(db)
    earliest = entry_dates[0] if entry_dates else today

    async def value_at(as_of: date) -> float:
        totals = await compute_combined_net_worth_now(db, base_currency, as_of)
        return totals["net_worth"]

    return await _build_growth_stats(value_at, today, earliest)


async def compute_portfolio_intraday(db: Session, portfolio: models.Portfolio, target_date: date) -> List[dict]:
    """
    Hourly net worth for a single portfolio on one trading day, using real
    intraday prices where available. Two things are held constant across the
    whole day rather than resolved hour-by-hour, on purpose:

      - Cash balances: a bank/broker balance has no intraday granularity to
        begin with, so today's cash total is simply added to every hour.
      - FX rates: fetched once (today's live rate) and reused for every hour,
        rather than an hourly FX lookup for every currency pair -- a
        reasonable simplification for major currency pairs over one day.

    So it's genuinely the *invested* portion of the line that moves with
    real intraday price action; cash and FX are flat by design, not a bug.

    A ticker with no data yet at a given hour (e.g. before its market opens)
    carries forward the previous trading day's closing price, matching how a
    broker keeps showing the last traded price until the market reopens.
    """
    holdings = _latest_holding_per_asset(db, portfolio.id, target_date)
    base_ccy = portfolio.base_currency

    today_snapshot = await compute_portfolio_snapshot(db, portfolio, date.today())
    cash_flat = today_snapshot.cash_total_base_ccy

    ticker_times: dict = {}
    ticker_prices: dict = {}
    ticker_fallback: dict = {}
    ticker_currency: dict = {}
    manual_value: dict = {}

    for h in holdings:
        asset = h.asset
        if h.manual_price is not None:
            manual_value[h.asset_id] = h.quantity * h.manual_price
            ticker_currency[h.asset_id] = asset.currency
            continue
        if not asset.ticker:
            continue

        points = await price_client.get_intraday_prices(asset.ticker, target_date)
        if points:
            ticker_times[h.asset_id] = [datetime.fromisoformat(p["time"]) for p in points]
            ticker_prices[h.asset_id] = [p["price"] for p in points]

        prev = await price_client.get_price_on_date(asset.ticker, target_date - timedelta(days=1))
        if prev:
            ticker_fallback[h.asset_id] = prev["price"]
        ticker_currency[h.asset_id] = asset.currency

    all_times = sorted({t for times in ticker_times.values() for t in times})
    if not all_times:
        return []

    fx_cache: dict = {}

    async def fx_for(ccy: str) -> float:
        if ccy not in fx_cache:
            rate = await price_client.get_fx_rate(ccy, base_ccy)
            fx_cache[ccy] = rate if rate is not None else 1.0
        return fx_cache[ccy]

    points_out = []
    for t in all_times:
        total = cash_flat
        for h in holdings:
            asset = h.asset
            if h.asset_id in manual_value:
                total += manual_value[h.asset_id] * await fx_for(asset.currency)
                continue

            price = None
            times = ticker_times.get(h.asset_id)
            if times:
                idx = bisect.bisect_right(times, t) - 1
                if idx >= 0:
                    price = ticker_prices[h.asset_id][idx]
            if price is None:
                price = ticker_fallback.get(h.asset_id)
            if price is None:
                continue

            total += h.quantity * price * await fx_for(ticker_currency[h.asset_id])

        points_out.append({"time": t.isoformat(), "net_worth_base_ccy": total})

    return points_out


async def compute_combined_intraday(db: Session, target_date: date, base_currency: str = "EUR") -> List[dict]:
    """
    Same idea as compute_portfolio_intraday, merged across every portfolio.
    A portfolio with no ticker-based holdings at all (so no hourly data of
    its own) still contributes its current flat total to every hour, rather
    than silently vanishing from the combined line.
    """
    portfolios = db.query(models.Portfolio).filter(models.Portfolio.archived == False).all()  # noqa: E712

    per_portfolio_series: dict = {}
    flat_totals: dict = {}

    for p in portfolios:
        fx = await price_client.get_fx_rate(p.base_currency, base_currency)
        fx = fx if fx is not None else 1.0

        pts = await compute_portfolio_intraday(db, p, target_date)
        if pts:
            per_portfolio_series[p.id] = [
                (datetime.fromisoformat(pt["time"]), pt["net_worth_base_ccy"] * fx) for pt in pts
            ]
        else:
            snap = await compute_portfolio_snapshot(db, p, date.today())
            flat_totals[p.id] = snap.net_worth_base_ccy * fx

    all_times = sorted({t for series in per_portfolio_series.values() for t, _ in series})
    if not all_times:
        return []

    base_flat = sum(flat_totals.values())
    result = []
    for t in all_times:
        total = base_flat
        for series in per_portfolio_series.values():
            times = [x[0] for x in series]
            idx = bisect.bisect_right(times, t) - 1
            if idx >= 0:
                total += series[idx][1]
        result.append({"time": t.isoformat(), "net_worth_base_ccy": total})

    return result


def get_asset_manual_price_history(db: Session, asset_id: str) -> List[dict]:
    """
    For assets with no ticker (real estate, unlisted funds...), the only
    price history that exists is whatever manual prices were entered over
    time across any portfolio holding this asset. Deduplicates same-day
    entries (keeping the most recently created one) since the same asset
    could in principle be held -- and re-priced -- in more than one portfolio.
    """
    entries = (
        db.query(models.HoldingEntry)
        .filter(models.HoldingEntry.asset_id == asset_id, models.HoldingEntry.manual_price.isnot(None))
        .order_by(models.HoldingEntry.entry_date, models.HoldingEntry.created_at)
        .all()
    )
    by_date: dict = {}
    for e in entries:
        by_date[e.entry_date] = e.manual_price  # later rows for the same date win
    return [{"date": d.isoformat(), "price": p} for d, p in sorted(by_date.items())]


async def compute_asset_growth(db: Session, asset: models.Asset) -> dict:
    """
    Day/week/month/year/max growth for a single asset's *price* (not a
    position's value -- quantity doesn't factor in here). "Max" is bounded by
    the earliest date this asset appears in any holding entry, same principle
    as portfolio growth's "max" being bounded by the earliest tracked data
    rather than an unbounded lookback to a ticker's IPO.
    """
    today = date.today()
    entries = (
        db.query(models.HoldingEntry)
        .filter(models.HoldingEntry.asset_id == asset.id)
        .order_by(models.HoldingEntry.entry_date)
        .all()
    )
    earliest = entries[0].entry_date if entries else today

    manual_by_date = None
    if not asset.ticker:
        manual_by_date = get_asset_manual_price_history(db, asset.id)

    async def value_at(as_of: date) -> float:
        if asset.ticker:
            if as_of < today:
                hist = await price_client.get_price_on_date(asset.ticker, as_of)
                if hist:
                    return hist["price"]
            else:
                live = await price_client.get_latest_price(asset.ticker)
                if live:
                    return live["price"]
            # Fetch failed (e.g. network issue) -- fall back to today's price
            # rather than crashing the whole growth computation over one gap.
            fallback = await price_client.get_latest_price(asset.ticker)
            return fallback["price"] if fallback else 0.0
        else:
            candidates = [p for p in (manual_by_date or []) if p["date"] <= as_of.isoformat()]
            return candidates[-1]["price"] if candidates else 0.0

    return await _build_growth_stats(value_at, today, earliest)
