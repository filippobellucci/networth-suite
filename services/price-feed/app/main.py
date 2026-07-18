"""
Price Feed Service
-------------------
Wraps yfinance so the rest of the system never depends on a specific
market-data provider directly. Caches results in-memory with a short TTL
to avoid hammering Yahoo Finance (and to survive brief outages).

Contract (used by core-networth via price_client.py):
  GET /prices/latest?ticker=SWDA.MI      -> {"ticker", "price", "currency", "as_of"}
  GET /prices/history?ticker=...&range=1y -> {"ticker", "points": [{"date","price"}]}
  GET /fx/latest?base=USD&quote=EUR       -> {"base","quote","rate"}
"""
import time
from typing import Dict, Optional

import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Price Feed Service", version="0.1.0")
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


def _fetch_ticker_price(ticker: str) -> Optional[dict]:
    now = time.time()
    cached = _price_cache.get(ticker)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    try:
        t = yf.Ticker(ticker)
        fast = t.fast_info
        price = fast.get("last_price") if hasattr(fast, "get") else fast.last_price
        currency = fast.get("currency") if hasattr(fast, "get") else fast.currency
        if price is None:
            return None
        payload = {"ticker": ticker, "price": float(price), "currency": currency or "USD", "as_of": str(now)}
        _price_cache[ticker] = (now, payload)
        return payload
    except Exception:
        return None


@app.get("/prices/latest", response_model=PriceOut)
def latest_price(ticker: str = Query(...)):
    payload = _fetch_ticker_price(ticker)
    if not payload:
        raise HTTPException(404, f"No price data for ticker '{ticker}'")
    return payload


@app.get("/prices/batch")
def batch_prices(tickers: str = Query(..., description="Comma-separated tickers")):
    result = {}
    for t in [x.strip() for x in tickers.split(",") if x.strip()]:
        result[t] = _fetch_ticker_price(t)
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
        raise HTTPException(502, f"Failed to fetch history for '{ticker}': {e}")


@app.get("/fx/latest", response_model=FxOut)
def fx_latest(base: str = Query(...), quote: str = Query(...)):
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return FxOut(base=base, quote=quote, rate=1.0)

    key = f"{base}{quote}"
    now = time.time()
    cached = _fx_cache.get(key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    pair_ticker = f"{base}{quote}=X"
    payload = _fetch_ticker_price(pair_ticker)
    if not payload:
        raise HTTPException(404, f"No FX rate for {base}/{quote}")
    result = FxOut(base=base, quote=quote, rate=payload["price"])
    _fx_cache[key] = (now, result)
    return result
