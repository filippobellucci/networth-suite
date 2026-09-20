"""
Price Feed Service
-------------------
Wraps yfinance so the rest of the system never depends on a specific
market-data provider directly. Caches results in-memory with a short TTL
to avoid hammering Yahoo Finance (and to survive brief outages).

If prices consistently show as unavailable, check this service's logs
(`docker compose logs price-feed`) -- failures are logged with the real
reason (bad ticker, rate limiting, network issue) instead of being hidden.
The most common cause is a ticker missing its exchange suffix, e.g. a
Milan-listed ETF needs ".MI" (SWDA.MI), Xetra needs ".DE", Amsterdam ".AS", etc.

Contract (used by core-networth via price_client.py, and called directly by the
frontend through the gateway's generic /api/prices/... proxy for the per-asset
price chart -- routes here deliberately do NOT repeat "prices" in their own
path, unlike core-networth/geo-allocation's internal routes, the gateway's
module-name-stripping proxy would otherwise 404 on every request):
  GET /latest?ticker=SWDA.MI&force=false     -> {"ticker", "price", "currency", "as_of"}
  GET /on-date?ticker=...&date=YYYY-MM-DD     -> {"ticker", "requested_date", "actual_date", "price", "currency"}
  GET /intraday?ticker=...&date=YYYY-MM-DD    -> {"ticker", "date", "points": [{"time","price"}]}
  GET /history?ticker=...&range=1y            -> {"ticker", "points": [{"date","price"}]}
  GET /fx/latest?base=USD&quote=EUR&force=false -> {"base","quote","rate"}
"""
import logging
import math
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("price-feed")

app = FastAPI(title="Price Feed Service", version="0.4.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _drop_unusable_rows(hist):
    """
    Yahoo occasionally returns a row for a date with no usable Close (a data
    gap, not an actual non-trading day) -- its value is NaN. A NaN float is
    valid Python but not valid JSON: leaving one in any response crashes
    serialization with a 500 (`ValueError: Out of range float values are
    not JSON compliant: nan`) instead of the caller ever seeing a clean
    "unavailable" answer. Used everywhere a price is read from a yfinance
    history() DataFrame, so a single bad row degrades gracefully (skipped,
    same as a weekend/holiday) rather than taking down the whole response.
    """
    return hist[hist["Close"].notna()]

CACHE_TTL_SECONDS = 15 * 60
# Never expires: used for data that can't change once it exists (a completed
# trading day's close, a ticker's quotation currency).
FOREVER = math.inf


class TtlCache:
    """
    The one in-memory cache used by every endpoint here: a key -> payload map
    where each entry remembers when it was stored and how long it stays
    valid, and is served only while it's younger than that. `ttl=FOREVER`
    makes entries permanent (until the process restarts); an entry can
    override the cache's default when it is stored (see `set`).
    """

    def __init__(self, ttl: float = CACHE_TTL_SECONDS):
        self._ttl = ttl
        self._entries: dict[str, tuple[float, float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, ttl, payload = entry
        return payload if time.time() - stored_at < ttl else None

    def set(self, key: str, payload: Any, ttl: Optional[float] = None) -> None:
        """`ttl` overrides this cache's default for one entry. It belongs
        here, at write time, because that is where it's known whether the
        value being stored is final: the reader has no way to tell a
        completed day's data from a snapshot of a day still in progress."""
        self._entries[key] = (time.time(), self._ttl if ttl is None else ttl, payload)

    def clear(self) -> None:
        self._entries.clear()


_price_cache = TtlCache()  # ticker -> payload
_fx_cache = TtlCache()  # "BASEQUOTE" -> FxOut
# Historical closes never change once the trading day is over.
_historical_cache = TtlCache(FOREVER)  # "ticker|YYYY-MM-DD" -> payload
# Same idea for intraday hourly points, EXCEPT for the current day, which is
# still filling in as the trading day goes on -- that one is read back with a
# short TTL instead, same as live prices.
_intraday_cache = TtlCache(FOREVER)  # "ticker|YYYY-MM-DD" -> payload
# /history was previously the only price endpoint hitting yfinance on every
# single request, even for the same ticker/range/interval requested repeatedly
# (e.g. a chart reloaded a few times in a row), unlike every other one here.
_history_cache = TtlCache()  # "ticker|range|interval" -> payload
# A ticker's quotation currency doesn't change.
_currency_cache = TtlCache(FOREVER)  # ticker -> currency


class PriceOut(BaseModel):
    ticker: str
    price: float
    currency: str
    as_of: str


class HistoricalPriceOut(BaseModel):
    ticker: str
    requested_date: str
    actual_date: str  # the actual trading day used, e.g. the prior Friday for a Saturday request
    price: float
    currency: str


class FxOut(BaseModel):
    base: str
    quote: str
    rate: float


@app.get("/health")
def health():
    return {"status": "ok"}


def _fetch_ticker_price(ticker: str, force: bool = False) -> Optional[dict]:
    if not force:
        cached = _price_cache.get(ticker)
        if cached:
            return cached

    price = None
    currency = None

    # Primary path: fast_info (cheap, single request)
    try:
        t = yf.Ticker(ticker)
        fast = t.fast_info
        price = fast.get("last_price") if hasattr(fast, "get") else getattr(fast, "last_price", None)
        currency = fast.get("currency") if hasattr(fast, "get") else getattr(fast, "currency", None)
        if price is not None and isinstance(price, float) and math.isnan(price):
            # Same "NaN isn't valid JSON" issue as the history path below --
            # treat it as no price available so this falls through to the
            # history-based fallback instead of crashing serialization.
            price = None
    except Exception as e:
        logger.warning("fast_info failed for '%s': %s", ticker, e)

    # Fallback: last close from recent daily history, in case fast_info is
    # unavailable for this ticker (happens for some ETFs/exchanges).
    if price is None:
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            hist = _drop_unusable_rows(hist)
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                if currency is None:
                    info = yf.Ticker(ticker).fast_info
                    currency = info.get("currency") if hasattr(info, "get") else getattr(info, "currency", None)
        except Exception as e:
            logger.warning("history fallback failed for '%s': %s", ticker, e)

    if price is None:
        logger.warning("No price data available for ticker '%s' (tried fast_info and history)", ticker)
        return None

    payload = {"ticker": ticker, "price": float(price), "currency": currency or "USD", "as_of": str(time.time())}
    _price_cache.set(ticker, payload)
    return payload


@app.get("/latest", response_model=PriceOut)
def latest_price(ticker: str = Query(...), force: bool = Query(False)):
    payload = _fetch_ticker_price(ticker, force=force)
    if not payload:
        raise HTTPException(
            404,
            f"No price data for ticker '{ticker}'. Check it's a valid Yahoo Finance symbol "
            "(European listings usually need an exchange suffix, e.g. '.MI', '.DE', '.AS'), "
            "and check this service's logs for the underlying error.",
        )
    return payload


def _ticker_currency(ticker: str) -> str:
    """
    The currency a ticker is quoted in, remembered permanently once known.

    Only a currency Yahoo actually told us is permanent. The "USD" below is a
    guess made because the lookup failed, and guessing has to stay temporary:
    remembering it forever meant that one rate-limited reply, at any moment in
    the life of the process, silently relabelled a Milan-listed EUR holding as
    USD -- and kept it that way, because the _historical_cache entries built
    from it are permanent too. Core would then convert a price that was never
    in dollars, so the portfolio was wrong by the EUR/USD rate with nothing
    on screen to suggest it. A short TTL still spares Yahoo a lookup per
    request, and the next attempt can correct it.
    """
    cached = _currency_cache.get(ticker)
    if cached is not None:
        return cached
    currency = None
    try:
        fast = yf.Ticker(ticker).fast_info
        currency = fast.get("currency") if hasattr(fast, "get") else getattr(fast, "currency", None)
    except Exception as e:
        logger.warning("Could not resolve currency for '%s', assuming USD for now: %s", ticker, e)
    if currency:
        _currency_cache.set(ticker, currency)
        return currency
    logger.warning("Yahoo reported no currency for '%s'; assuming USD until the next lookup", ticker)
    _currency_cache.set(ticker, "USD", ttl=CACHE_TTL_SECONDS)
    return "USD"


def _fetch_price_on_date(ticker: str, target_date: date) -> Optional[dict]:
    # A past close never changes, so it's safe to cache forever -- but
    # target_date == today (or later) is a different case: the daily bar
    # for a day that hasn't closed yet is still filling in as the market
    # trades, so whatever's fetched now is a partial, non-final snapshot,
    # not "the close". Caching that forever under this date's key would
    # permanently serve that stale partial value even after the real close
    # is known. Only the true "past date" case uses the permanent cache;
    # today/future are always fetched fresh and never cached here.
    is_final_trading_day = target_date < date.today()
    cache_key = f"{ticker}|{target_date.isoformat()}"
    if is_final_trading_day:
        cached = _historical_cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        # Window back far enough to cross any run of consecutive non-trading
        # days (long weekends, multi-day market holidays) and still find a
        # close on or before the requested date.
        start = target_date - timedelta(days=10)
        end = target_date + timedelta(days=1)
        hist = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat())
        if hist.empty:
            logger.warning("No historical data for '%s' around %s", ticker, target_date)
            return None

        hist = hist[hist.index.date <= target_date]
        # Yahoo occasionally returns a row for a date with no usable close
        # (a data gap, not an actual non-trading day) -- its Close is NaN.
        # A NaN float is valid Python but not valid JSON, so leaving it in
        # crashed response serialization with a 500 rather than falling
        # through to "no data" like an empty DataFrame already does. Drop
        # those rows so we naturally fall back to the nearest earlier day
        # with a real close, same as we already do for weekends/holidays --
        # reuses the same helper every other price path here uses, instead
        # of a second copy of the same filter.
        hist = _drop_unusable_rows(hist)
        if hist.empty:
            logger.warning("No trading day on/before %s for '%s' (asset may not have existed yet)", target_date, ticker)
            return None

        actual_date = hist.index[-1].date()
        price = float(hist["Close"].iloc[-1])
        currency = _ticker_currency(ticker)

        payload = {
            "ticker": ticker,
            "requested_date": target_date.isoformat(),
            "actual_date": actual_date.isoformat(),
            "price": price,
            "currency": currency,
        }
        # Only ever cache a completed trading day's close -- see
        # is_final_trading_day above. If the actual row we landed on (after
        # walking back for weekends/holidays) is itself before today, it's
        # final and safe to cache even if target_date resolved to today.
        if actual_date < date.today():
            _historical_cache.set(cache_key, payload)
        return payload
    except Exception as e:
        logger.warning("on-date history failed for '%s' on %s: %s", ticker, target_date, e)
        return None


@app.get("/on-date", response_model=HistoricalPriceOut)
def price_on_date(ticker: str = Query(...), date: str = Query(..., description="YYYY-MM-DD")):
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, f"Invalid date '{date}', expected YYYY-MM-DD")

    payload = _fetch_price_on_date(ticker, target)
    if not payload:
        raise HTTPException(404, f"No historical price for '{ticker}' on or before {date}")
    return payload


def _fetch_intraday(ticker: str, target_date: date) -> Optional[dict]:
    cache_key = f"{ticker}|{target_date.isoformat()}"
    is_today = target_date == date.today()
    cached = _intraday_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        start = target_date
        end = target_date + timedelta(days=1)
        # 60-minute bars; Yahoo only keeps hourly granularity for roughly the
        # last two years, plenty for "what did today/this week look like".
        hist = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(), interval="60m")
        hist = _drop_unusable_rows(hist)
        points = [
            {"time": idx.isoformat(), "price": float(row["Close"])} for idx, row in hist.iterrows()
        ]
        payload = {"ticker": ticker, "date": target_date.isoformat(), "points": points}
        # Cached even when empty (e.g. a weekend/holiday) -- that's a valid,
        # stable answer, not a transient failure worth retrying every request.
        # Today's series is still filling in as the day trades, so it only
        # holds for the short TTL: remembering a partial day forever meant
        # that from tomorrow on, that truncated series was served as if it
        # were the finished day, and the afternoon never appeared at all.
        _intraday_cache.set(cache_key, payload, ttl=CACHE_TTL_SECONDS if is_today else None)
        return payload
    except Exception as e:
        logger.warning("intraday fetch failed for '%s' on %s: %s", ticker, target_date, e)
        return None


@app.get("/intraday")
def intraday_prices(ticker: str = Query(...), date: str = Query(..., description="YYYY-MM-DD")):
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, f"Invalid date '{date}', expected YYYY-MM-DD")
    if target > datetime.now().date():
        raise HTTPException(422, "Can't fetch intraday prices for a future date")

    payload = _fetch_intraday(ticker, target)
    if payload is None:
        raise HTTPException(502, f"Failed to fetch intraday data for '{ticker}' on {date}")
    return payload


@app.get("/history")
def price_history(ticker: str, range: str = "1y", interval: str = "1mo", force: bool = Query(False)):
    cache_key = f"{ticker}|{range}|{interval}"
    if not force:
        cached = _history_cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=range, interval=interval)
        hist = _drop_unusable_rows(hist)
        points = [
            {"date": idx.strftime("%Y-%m-%d"), "price": float(row["Close"])}
            for idx, row in hist.iterrows()
        ]
        payload = {"ticker": ticker, "points": points}
        _history_cache.set(cache_key, payload)
        return payload
    except Exception as e:
        logger.warning("history failed for '%s': %s", ticker, e)
        raise HTTPException(502, f"Failed to fetch history for '{ticker}': {e}")


@app.get("/fx/latest", response_model=FxOut)
def fx_latest(base: str = Query(...), quote: str = Query(...), force: bool = Query(False)):
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return FxOut(base=base, quote=quote, rate=1.0)

    key = f"{base}{quote}"
    if not force:
        cached = _fx_cache.get(key)
        if cached is not None:
            return cached

    pair_ticker = f"{base}{quote}=X"
    payload = _fetch_ticker_price(pair_ticker, force=force)
    if not payload:
        raise HTTPException(404, f"No FX rate for {base}/{quote}")
    result = FxOut(base=base, quote=quote, rate=payload["price"])
    _fx_cache.set(key, result)
    return result


# NOTE: there is deliberately no /cache/clear endpoint. One existed, its
# docstring claiming the "refresh prices" action used it -- nothing ever
# called it. That action passes `force=true` on the specific prices it is
# refreshing instead, which is both targeted and immediate, and every cache
# here already expires on its own (see TtlCache).
