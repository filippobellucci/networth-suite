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
  GET /prices/latest?ticker=SWDA.MI&force=false  -> {"ticker", "price", "currency", "as_of"}
  GET /prices/history?ticker=...&range=1y         -> {"ticker", "points": [{"date","price"}]}
  GET /fx/latest?base=USD&quote=EUR&force=false   -> {"base","quote","rate"}
"""
import logging
import time
from typing import Dict, Optional

import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("price-feed")

app = FastAPI(title="Price Feed Service", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CACHE_TTL_SECONDS = 15 * 60
_price_cache: Dict[str, tuple] = {}  # ticker -> (timestamp, payload)
_fx_cache: Dict[str, tuple] = {}


class PriceOut(BaseModel):
    ticker: str
    price: float
    currency: str
    as_of: str


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
