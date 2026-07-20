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

Contract (used by core-networth via price_client.py):
  GET /prices/latest?ticker=SWDA.MI&force=false     -> {"ticker", "price", "currency", "as_of"}
  GET /prices/on-date?ticker=...&date=YYYY-MM-DD     -> {"ticker", "requested_date", "actual_date", "price", "currency"}
  GET /prices/history?ticker=...&range=1y            -> {"ticker", "points": [{"date","price"}]}
  GET /fx/latest?base=USD&quote=EUR&force=false      -> {"base","quote","rate"}
"""
import logging
import time
from datetime import date, datetime, timedelta
from typing import Dict, Optional

import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("price-feed")

app = FastAPI(title="Price Feed Service", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CACHE_TTL_SECONDS = 15 * 60
_price_cache: Dict[str, tuple] = {}  # ticker -> (timestamp, payload)
_fx_cache: Dict[str, tuple] = {}
# Historical closes never change once the trading day is over, so this cache
# has no TTL -- an entry is valid forever (until the process restarts).
_historical_cache: Dict[str, dict] = {}  # "ticker|YYYY-MM-DD" -> payload


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
    except Exception as e:
        logger.warning("fast_info failed for '%s': %s", ticker, e)

    # Fallback: last close from recent daily history, in case fast_info is
    # unavailable for this ticker (happens for some ETFs/exchanges).
    if price is None:
        try:
            hist = yf.Ticker(ticker).history(period="5d")
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


@app.get("/prices/latest", response_model=PriceOut)
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


@app.get("/prices/on-date", response_model=HistoricalPriceOut)
def price_on_date(ticker: str = Query(...), date: str = Query(..., description="YYYY-MM-DD")):
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, f"Invalid date '{date}', expected YYYY-MM-DD")

    payload = _fetch_price_on_date(ticker, target)
    if not payload:
        raise HTTPException(404, f"No historical price for '{ticker}' on or before {date}")
    return payload


@app.get("/prices/batch")
def batch_prices(tickers: str = Query(..., description="Comma-separated tickers"), force: bool = Query(False)):
    result = {}
    for t in [x.strip() for x in tickers.split(",") if x.strip()]:
        result[t] = _fetch_ticker_price(t, force=force)
    return result


@app.get("/prices/history")
def price_history(ticker: str, range: str = "1y", interval: str = "1mo"):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=range, interval=interval)
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
