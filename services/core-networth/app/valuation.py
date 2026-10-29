import bisect
import logging
from calendar import monthrange
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import List, Optional, Callable, Awaitable

from sqlalchemy.orm import Session, joinedload

from . import models, price_client
from .models import AllocationCategory, TransactionDirection, CashAccountKind
from .schemas import HoldingPosition, CashPosition, PortfolioSnapshot

logger = logging.getLogger("core-networth.valuation")


class AccountLedger:
    """
    One cash account's balance entries and transactions, loaded once, so its
    balance on any number of dates is answered in memory (see `balance`).

    Transactions are kept sorted by date with exact running sums (Fractions
    of the stored floats), so a balance is the difference of two of them --
    without the rounding drift a float difference would add -- however many
    transactions came before.
    """

    def __init__(self, account: models.CashAccount, balances: list, transactions: list):
        """`balances` come newest first, as `load` orders them; kept here
        oldest first, so the anchor of a date is the last one on or before it."""
        self.account = account
        is_voucher = account.kind == CashAccountKind.VOUCHER
        # (entry_date, created_at, balance)
        self.balances = balances[::-1]
        self._balance_dates = [b[0] for b in self.balances]
        # (entry_date, created_at, signed delta, investment_income_kind, amount)
        txns = []
        for entry_date, created_at, direction, amount, quantity, income_kind in transactions:
            # A voucher account accumulates `quantity`, a currency account
            # `amount` (see `balance`); quantity is nullable.
            delta = (quantity if is_voucher else amount) or 0.0
            signed = delta if direction == TransactionDirection.INCOME else -delta
            txns.append((entry_date, created_at, signed, income_kind, amount))
        txns.sort(key=lambda t: t[0])
        self.transactions = txns
        self._txn_dates = [t[0] for t in txns]
        self._running = [Fraction(0)]
        for t in txns:
            self._running.append(self._running[-1] + Fraction(t[2]))
        # What each balance entry's own day adds after it (see `balance`).
        self._same_day = {}
        for i, (b_date, b_created, _) in enumerate(self.balances):
            lo, hi = bisect.bisect_left(self._txn_dates, b_date), bisect.bisect_right(self._txn_dates, b_date)
            self._same_day[i] = sum(
                (Fraction(t[2]) for t in txns[lo:hi]
                 if b_created is None or t[1] is None or t[1] > b_created),
                Fraction(0),
            )

    @staticmethod
    def load(db: Session, accounts: List[models.CashAccount]) -> dict:
        """Ledgers for `accounts`, keyed by account id, in two queries."""
        ids = [a.id for a in accounts]
        balances: dict = {i: [] for i in ids}
        transactions: dict = {i: [] for i in ids}
        if ids:
            # Newest first, the order the anchor of a date is chosen in: the
            # latest date, then the latest creation (an unknown one, from
            # before the column existed, counts as the oldest). Left to the
            # database, as before the ledger, so rows equal on both are
            # still told apart the way they always were.
            for account_id, *row in (
                db.query(
                    models.CashBalanceEntry.account_id, models.CashBalanceEntry.entry_date,
                    models.CashBalanceEntry.created_at, models.CashBalanceEntry.balance,
                )
                .filter(models.CashBalanceEntry.account_id.in_(ids))
                .order_by(models.CashBalanceEntry.entry_date.desc(), models.CashBalanceEntry.created_at.desc())
            ):
                balances[account_id].append(tuple(row))
            for account_id, *row in db.query(
                models.CashTransaction.account_id, models.CashTransaction.entry_date,
                models.CashTransaction.created_at, models.CashTransaction.direction,
                models.CashTransaction.amount, models.CashTransaction.quantity,
                models.CashTransaction.investment_income_kind,
            ).filter(models.CashTransaction.account_id.in_(ids)):
                transactions[account_id].append(tuple(row))
        return {a.id: AccountLedger(a, balances[a.id], transactions[a.id]) for a in accounts}

    def balance(self, as_of: date) -> tuple[float, Optional[date]]:
        """
        The account's balance as of a given date is no longer a single
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
        still counts when it was recorded after that entry (ordered by
        `created_at`), and re-setting the opening balance later that day
        doesn't double-count what was logged before it. Both `created_at`
        columns are nullable; an unknown one includes the transaction.

        Returns (raw, most_recent_event_date) -- `raw` is a money balance for a
        CURRENCY account or a unit count for a VOUCHER account. The second value
        is only used for display ("as of ...") and is None if the account has no
        balance entry and no transaction at or before `as_of` yet.
        """
        end = bisect.bisect_right(self._txn_dates, as_of)
        anchor_index = bisect.bisect_right(self._balance_dates, as_of) - 1
        if anchor_index < 0:
            latest = self._txn_dates[end - 1] if end else None
            return float(self._running[end]), latest
        anchor_date, _, anchor_balance = self.balances[anchor_index]
        start = bisect.bisect_right(self._txn_dates, anchor_date)
        moved = self._same_day[anchor_index] + (self._running[end] - self._running[start] if end > start else 0)
        last_event = self._txn_dates[end - 1] if end > start else anchor_date
        return anchor_balance + float(moved), last_event

    def event_dates(self) -> set:
        """Every date this account's balance could have changed on."""
        return set(self._balance_dates) | set(self._txn_dates)


class PortfolioLedger:
    """
    Everything a valuation of this portfolio reads from the database --
    holdings, cash accounts, their balance entries and transactions -- loaded
    once (four queries), so valuing it on many dates (the history chart,
    growth, XIRR) costs no further query. Prices and rates are not in it:
    see warm_prices.
    """

    def __init__(self, db: Session, portfolio: models.Portfolio):
        self.portfolio = portfolio
        # Newest first per asset, in asset id order (the order positions are
        # listed in), sorted by the database for the reason given in
        # AccountLedger.load.
        entries = (
            db.query(models.HoldingEntry)
            .options(joinedload(models.HoldingEntry.asset))
            .filter(models.HoldingEntry.portfolio_id == portfolio.id)
            .order_by(
                models.HoldingEntry.asset_id,
                models.HoldingEntry.entry_date.desc(),
                models.HoldingEntry.created_at.desc(),
            )
            .all()
        )
        # Kept oldest first, so the entry in force on a date is the last one
        # on or before it.
        self._holdings: dict = {}
        for e in entries:
            self._holdings.setdefault(e.asset_id, []).append(e)
        for asset_entries in self._holdings.values():
            asset_entries.reverse()
        self._holding_dates = {a: [e.entry_date for e in es] for a, es in self._holdings.items()}
        self.accounts = db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio.id).all()
        self.cash = AccountLedger.load(db, self.accounts)

    def holdings_on(self, as_of: date) -> List[models.HoldingEntry]:
        """For each asset, the most recent HoldingEntry on or before `as_of`.
        This is what lets the UI show "current" positions even though data is
        entered as a time series (like the old spreadsheet's monthly columns)."""
        out = []
        for asset_id, entries in self._holdings.items():
            i = bisect.bisect_right(self._holding_dates[asset_id], as_of)
            if i:
                out.append(entries[i - 1])
        return out

    def holding_entries(self, asset_id: str) -> List[models.HoldingEntry]:
        """Every entry of one asset, oldest first."""
        return self._holdings.get(asset_id, [])

    def assets(self) -> List[models.Asset]:
        return [entries[0].asset for entries in self._holdings.values()]

    def entry_dates(self) -> List[date]:
        """All dates on which something changed (holdings, cash balance edits,
        or cash transactions), used to build the history chart.

        Dates after today are dropped. Writes can't create them (see
        schemas._reject_future_date), but a row edited straight in the database
        could, and one future date is enough to put a point past today on the
        chart, stop with_trailing_days_filled from filling anything, and push a
        cashflow past the closing valuation XIRR solves against."""
        dates = {d for ds in self._holding_dates.values() for d in ds}
        for ledger in self.cash.values():
            dates |= ledger.event_dates()
        today = date.today()
        return sorted(d for d in dates if d <= today)


async def warm_prices(ledger: PortfolioLedger, dates) -> None:
    """
    Fetches, ahead of valuing the portfolio on many past `dates`, every close
    and exchange rate those valuations will ask price_client for -- one
    request per ticker and per currency pair for the whole span instead of
    one per ticker per date (see price_client.prefetch_closes). Only a speed
    measure: whatever it doesn't manage to fetch is still asked for day by
    day, exactly as without it.
    """
    today = date.today()
    past = sorted({d for d in dates if d < today})
    if not past:
        return
    base = ledger.portfolio.base_currency
    tickers = sorted({a.ticker for a in ledger.assets() if a.ticker})
    quoted_in = await price_client.prefetch_closes(tickers, past)
    currencies = set(quoted_in.values()) | {a.currency for a in ledger.assets()} | {
        acc.currency for acc in ledger.accounts
    }
    pairs = sorted(f"{c}{base}=X" for c in currencies if c and c != base)
    await price_client.prefetch_closes(pairs, past)


async def _resolve_fx(
    from_ccy: str, to_ccy: str, as_of: date, is_historical: bool, force_refresh: bool = False
) -> tuple[float, bool]:
    """
    Shared by every place this module converts between currencies: a real
    historical rate for a past date, today's rate otherwise.

    Returns (rate, resolved). When no rate can be found the rate falls back
    to 1.0 -- valuing the position at its face value is still better than
    dropping it -- but `resolved` is False so the caller can say so. Silently
    counting, say, dollars as euros produces a total that looks perfectly
    plausible and is simply wrong, which is the one failure mode a net worth
    figure must never have.
    """
    if is_historical:
        fx = await price_client.get_fx_rate_on_date(from_ccy, to_ccy, as_of)
    else:
        fx = await price_client.get_fx_rate(from_ccy, to_ccy, force=force_refresh)
    if fx is None:
        logger.warning("No FX rate for %s->%s on %s; valuing 1:1", from_ccy, to_ccy, as_of)
        return 1.0, False
    return fx, True


async def compute_portfolio_snapshot(
    db: Session,
    portfolio: models.Portfolio,
    as_of: Optional[date] = None,
    force_refresh: bool = False,
    ledger: Optional[PortfolioLedger] = None,
) -> PortfolioSnapshot:
    """The portfolio valued on one date. Pass the `ledger` when valuing it on
    many dates, so its rows are read once rather than once per date."""
    as_of = as_of or date.today()
    is_historical = as_of < date.today()
    base_ccy = portfolio.base_currency
    ledger = ledger or PortfolioLedger(db, portfolio)

    holdings = ledger.holdings_on(as_of)
    positions: List[HoldingPosition] = []
    invested_total = 0.0
    # Set as soon as any conversion in this snapshot had to fall back to 1:1
    # -- surfaced to the UI, which otherwise has no way to tell a genuine
    # total from one that quietly mixed currencies (see _resolve_fx).
    fx_unavailable = False

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
                    # Historical fetch failed (a network hiccup, or a cold
                    # price-feed cache after a restart): the latest price is
                    # a better approximation than counting the position as
                    # zero -- which a frozen month-end snapshot would keep.
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
            fx, fx_ok = await _resolve_fx(price_ccy, base_ccy, as_of, effective_historical, force_refresh)
            fx_unavailable = fx_unavailable or not fx_ok
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
    accounts = [acc for acc in ledger.accounts if acc.archived_at is None or as_of < acc.archived_at.date()]
    cash_positions: List[CashPosition] = []
    cash_total = 0.0
    for acc in accounts:
        raw, as_of_event = ledger.cash[acc.id].balance(as_of)
        is_voucher = acc.kind == CashAccountKind.VOUCHER
        # For a VOUCHER account `raw` is a unit count -- convert to money
        # using today's unit_value before FX, same as a CURRENCY account's
        # `raw` is already money in its own currency.
        native_value = raw * (acc.unit_value or 0.0) if is_voucher else raw
        fx, fx_ok = await _resolve_fx(acc.currency, base_ccy, as_of, is_historical, force_refresh)
        fx_unavailable = fx_unavailable or not fx_ok
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
        fx_unavailable=fx_unavailable,
    )


def why_snapshot_cannot_be_frozen(snap: PortfolioSnapshot) -> Optional[str]:
    """
    Why a portfolio's valuation is not fit to be frozen into a
    NetWorthSnapshot, or None when it is. A snapshot never changes once
    taken, so a holding counted as zero for want of a price, or an amount
    converted 1:1 for want of a rate, would stay wrong in the history for good.
    """
    unpriced = sorted({pos.asset_name for pos in snap.positions if pos.price is None})
    if unpriced:
        return "no price could be fetched for " + ", ".join(unpriced)
    if snap.fx_unavailable:
        return "an exchange rate could not be fetched"
    return None


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


def _growth_start_dates(today: date, earliest: date) -> dict:
    """The date each growth period starts on, never before the first data."""
    return {
        "day": max(today - timedelta(days=1), earliest),
        "week": max(today - timedelta(days=7), earliest),
        "month": max(_subtract_months(today, 1), earliest),
        "year": max(_subtract_months(today, 12), earliest),
        "max": earliest,
    }


async def _build_growth_stats(
    value_at: Callable[[date], Awaitable[float]], today: date, earliest: date
) -> dict:
    """
    Shared by compute_portfolio_growth and compute_asset_growth: given a
    function that values the portfolio (or asset) as of any date, returns
    day/month/year/max growth (start value, current value, absolute and
    percentage change), each computed with real historical prices for the
    start date -- not just whatever data point happened to already exist.
    """
    current = await value_at(today)
    periods = _growth_start_dates(today, earliest)

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
    ledger = PortfolioLedger(db, portfolio)
    entry_dates = ledger.entry_dates()
    earliest = entry_dates[0] if entry_dates else today
    await warm_prices(ledger, _growth_start_dates(today, earliest).values())

    async def value_at(as_of: date) -> float:
        snap = await compute_portfolio_snapshot(db, portfolio, as_of, ledger=ledger)
        return snap.net_worth_base_ccy

    return await _build_growth_stats(value_at, today, earliest)


async def compute_portfolio_intraday(db: Session, portfolio: models.Portfolio, target_date: date) -> List[dict]:
    """
    Hourly net worth for a single portfolio on one trading day, using real
    intraday prices where available. Two things are held constant across the
    whole day rather than resolved hour-by-hour, on purpose:

      - Cash balances: a bank/broker balance has no intraday granularity to
        begin with, so today's cash total is simply added to every hour.
      - FX rates: fetched once for `target_date` and reused for every hour,
        rather than an hourly FX lookup for every currency pair -- a
        reasonable simplification for major currency pairs over one day.
        For a past date that is the rate as it was ON that day, not today's,
        so this line agrees with the same day's history point and snapshot.

    So it's genuinely the *invested* portion of the line that moves with
    real intraday price action; cash and FX are flat by design, not a bug.

    A ticker with no data yet at a given hour (e.g. before its market opens)
    carries forward the previous trading day's closing price, matching how a
    broker keeps showing the last traded price until the market reopens.
    """
    ledger = PortfolioLedger(db, portfolio)
    holdings = ledger.holdings_on(target_date)
    base_ccy = portfolio.base_currency

    # Cash has no intraday granularity, so it's held flat across the whole
    # day -- at *that day's* balance, for a past date too.
    day_snapshot = await compute_portfolio_snapshot(db, portfolio, target_date, ledger=ledger)
    cash_flat = day_snapshot.cash_total_base_ccy

    ticker_times: dict = {}
    ticker_prices: dict = {}
    ticker_fallback: dict = {}
    manual_value: dict = {}
    # The currency each ticker's prices are quoted in. /intraday doesn't
    # report one, so it's taken from the daily price payload fetched below
    # for the fallback -- the source compute_portfolio_snapshot trusts. The
    # asset record's own currency is the last resort.
    ticker_ccy: dict = {}

    for h in holdings:
        asset = h.asset
        if h.manual_price is not None:
            manual_value[h.asset_id] = h.quantity * h.manual_price
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
            ticker_ccy[h.asset_id] = prev.get("currency") or asset.currency

    all_times = sorted({t for times in ticker_times.values() for t in times})
    if not all_times:
        return []

    fx_cache: dict = {}
    # One rate for the whole day (see the docstring) -- *that day's* rate,
    # cached to one lookup per currency.
    async def fx_for(ccy: str) -> float:
        if ccy not in fx_cache:
            fx_cache[ccy] = await price_client.fx_rate_at(ccy, base_ccy, target_date)
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

            total += h.quantity * price * await fx_for(ticker_ccy.get(h.asset_id, asset.currency))

        points_out.append({"time": t.isoformat(), "net_worth_base_ccy": total})

    return points_out


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
