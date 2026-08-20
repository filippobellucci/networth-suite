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
from typing import Dict, Optional

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
_price_cache: Dict[str, tuple] = {}  # ticker -> (timestamp, payload)
_fx_cache: Dict[str, tuple] = {}
# Historical closes never change once the trading day is over, so this cache
# has no TTL -- an entry is valid forever (until the process restarts).
_historical_cache: Dict[str, dict] = {}  # "ticker|YYYY-MM-DD" -> payload
# Same idea for intraday hourly points, EXCEPT for the current day, which is
# still filling in as the trading day goes on -- that one gets a short TTL
# instead, same as live prices.
_intraday_cache: Dict[str, tuple] = {}  # "ticker|YYYY-MM-DD" -> (timestamp, payload)


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
    now = time.time()
    if not force:
        cached = _price_cache.get(ticker)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

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

    payload = {"ticker": ticker, "price": float(price), "currency": currency or "USD", "as_of": str(now)}
    _price_cache[ticker] = (now, payload)
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


_currency_cache: Dict[str, str] = {}  # ticker -> currency (doesn't change, cache forever)


def _ticker_currency(ticker: str) -> str:
    if ticker in _currency_cache:
        return _currency_cache[ticker]
    currency = "USD"
    try:
        fast = yf.Ticker(ticker).fast_info
        currency = (fast.get("currency") if hasattr(fast, "get") else getattr(fast, "currency", None)) or "USD"
    except Exception as e:
        logger.warning("Could not resolve currency for '%s', defaulting to USD: %s", ticker, e)
    _currency_cache[ticker] = currency
    return currency


def _fetch_price_on_date(ticker: str, target_date: date) -> Optional[dict]:
    cache_key = f"{ticker}|{target_date.isoformat()}"
    if cache_key in _historical_cache:
        return _historical_cache[cache_key]

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
        # with a real close, same as we already do for weekends/holidays.
        hist = hist[hist["Close"].notna()]
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
        _historical_cache[cache_key] = payload
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
    if cached:
        ts, payload = cached
        if not is_today:
            return payload
        if time.time() - ts < CACHE_TTL_SECONDS:
            return payload

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
        _intraday_cache[cache_key] = (time.time(), payload)
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


@app.get("/batch")
def batch_prices(tickers: str = Query(..., description="Comma-separated tickers"), force: bool = Query(False)):
    result = {}
    for t in [x.strip() for x in tickers.split(",") if x.strip()]:
        result[t] = _fetch_ticker_price(t, force=force)
    return result


@app.get("/history")
def price_history(ticker: str, range: str = "1y", interval: str = "1mo"):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=range, interval=interval)
        hist = _drop_unusable_rows(hist)
        points = [
            {"date": idx.strftime("%Y-%m-%d"), "price": float(row["Close"])}
            for idx, row in hist.iterrows()
        ]
        return {"ticker": ticker, "points": points}
    except Exception as e:
        logger.warning("history failed for '%s': %s", ticker, e)
        raise HTTPException(502, f"Failed to fetch history for '{ticker}': {e}")


@app.get("/fx/latest", response_model=FxOut)
def fx_latest(base: str = Query(...), quote: str = Query(...), force: bool = Query(False)):
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return FxOut(base=base, quote=quote, rate=1.0)

    key = f"{base}{quote}"
    now = time.time()
    if not force:
        cached = _fx_cache.get(key)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

    pair_ticker = f"{base}{quote}=X"
    payload = _fetch_ticker_price(pair_ticker, force=force)
    if not payload:
        raise HTTPException(404, f"No FX rate for {base}/{quote}")
    result = FxOut(base=base, quote=quote, rate=payload["price"])
    _fx_cache[key] = (now, result)
    return result


@app.post("/cache/clear")
def clear_cache():
    """Wipes the in-memory price/FX cache -- used by the 'refresh prices' action."""
    _price_cache.clear()
    _fx_cache.clear()
    return {"cleared": True}
