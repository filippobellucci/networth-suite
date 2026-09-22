"""
A stand-in for the price-feed service, used by the system tier.

It answers the four endpoints core-networth actually calls, with fixed values
so every figure in a system test is predictable. It mirrors the real service's
CONTRACT, not just its happy path -- in particular it raises 404 for anything
it does not know, exactly as price-feed does. That detail matters: a stub that
answered 200 with an error body once produced a KeyError deep inside
core-networth that looked convincingly like a real bug, and core caches a past
day's answer permanently, so the false positive outlived the broken stub.

Live and historical rates differ on purpose (USD->EUR is 2.0 now and was 4.0),
which is what makes "did this convert at today's rate or that day's?"
answerable at all.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="price-feed stub")

PRICES: dict[str, tuple[float, str]] = {
    "TESTEUR": (100.0, "EUR"),
    "TESTUSD": (50.0, "USD"),
}
FX_LIVE: dict[tuple[str, str], float] = {("USD", "EUR"): 2.0, ("EUR", "USD"): 0.5}
FX_HISTORICAL: dict[tuple[str, str], float] = {("USD", "EUR"): 4.0, ("EUR", "USD"): 0.25}
INTRADAY_HOURS = (10, 11, 12, 13)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/latest")
def latest(ticker: str = Query(...), force: bool = Query(False)):
    if ticker not in PRICES:
        raise HTTPException(404, f"No price data for ticker '{ticker}'")
    price, currency = PRICES[ticker]
    return {"ticker": ticker, "price": price, "currency": currency}


@app.get("/fx/latest")
def fx_latest(base: str = Query(...), quote: str = Query(...), force: bool = Query(False)):
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return {"base": base, "quote": quote, "rate": 1.0}
    rate = FX_LIVE.get((base, quote))
    if rate is None:
        raise HTTPException(404, f"No FX rate for {base}/{quote}")
    return {"base": base, "quote": quote, "rate": rate}


@app.get("/on-date")
def on_date(ticker: str = Query(...), date: str = Query(...)):
    if ticker.endswith("=X"):
        pair = ticker[:-2]
        base, quote = pair[:3], pair[3:6]
        rate = 1.0 if base == quote else FX_HISTORICAL.get((base, quote))
        if rate is None:
            raise HTTPException(404, f"No historical price for '{ticker}'")
        return {"ticker": ticker, "requested_date": date, "actual_date": date,
                "price": rate, "currency": quote}
    if ticker not in PRICES:
        raise HTTPException(404, f"No historical price for '{ticker}'")
    price, currency = PRICES[ticker]
    return {"ticker": ticker, "requested_date": date, "actual_date": date,
            "price": price, "currency": currency}


@app.get("/intraday")
def intraday(ticker: str = Query(...), date: str = Query(...)):
    if ticker not in PRICES:
        return {"ticker": ticker, "date": date, "points": []}
    day = datetime.fromisoformat(date)
    price = PRICES[ticker][0]
    return {
        "ticker": ticker,
        "date": date,
        "points": [{"time": day.replace(hour=h).isoformat(), "price": price}
                   for h in INTRADAY_HOURS],
    }
