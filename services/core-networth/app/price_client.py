"""
Thin client for the price-feed service. Kept isolated so the core service
never talks to yfinance (or any market-data source) directly -- it only
knows about the internal HTTP contract of the price-feed module.

Two things here exist purely for speed, and they matter a lot: building a
historical chart values the portfolio once per tracked day, and every one of
those valuations needs a price and an FX rate.

  * One shared HTTP client per event loop, instead of a fresh
    httpx.AsyncClient (and connection) for every day plotted.
  * A small in-process cache. A completed day's close and a past day's FX
    rate can never change, so they're cached for the life of the process;
    live prices/rates get a short TTL, and `force=True` (the "Refresh
    prices" action, the scheduler's warm-up) always bypasses and refreshes
    it. The price-feed service caches too, but only after the request has
    already crossed the network.
"""
import asyncio
import bisect
import time
import weakref
from datetime import date, timedelta
from typing import Any, Optional

import httpx

from .config import PRICE_FEED_URL

LIVE_TTL_SECONDS = 60
# A price or rate for a day that is already over is final; keep it forever.
FOREVER = float("inf")
# How far back price-feed's /on-date looks for the close "on or before" a
# day; prefetch_closes reads the same answer out of a series.
ON_DATE_LOOKBACK_DAYS = 10
# Cached for a day a series showed no close for, so it isn't asked again
# one day at a time while the same valuation runs.
_NO_CLOSE = object()

_cache: dict[str, tuple[float, float, Any]] = {}  # key -> (stored_at, ttl, payload)
# One client per event loop, since a client is bound to the loop it was
# created on. Keyed weakly by the loop *object* (not id(loop), an address
# CPython reuses): entries vanish when their loop is collected, and two
# loops can never collide.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = (
    weakref.WeakKeyDictionary()
)


def _client() -> httpx.AsyncClient:
    """The shared client (and therefore the pooled connection) for this loop."""
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=15.0)
        _clients[loop] = client
    return client


def _cached(key: str) -> Any:
    entry = _cache.get(key)
    if entry is None:
        return None
    stored_at, ttl, payload = entry
    return payload if time.time() - stored_at < ttl else None


def _store(key: str, payload: Any, ttl: float) -> Any:
    _cache[key] = (time.time(), ttl, payload)
    return payload


async def _get_json(path: str, params: dict, timeout: float) -> Optional[dict]:
    try:
        resp = await _client().get(f"{PRICE_FEED_URL}{path}", params=params, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
    except httpx.HTTPError:
        pass
    return None


async def get_latest_price(ticker: str, force: bool = False) -> Optional[dict]:
    """Returns {"price": float, "currency": str} or None if unavailable."""
    key = f"latest|{ticker}"
    if not force:
        cached = _cached(key)
        if cached is not None:
            return cached
    payload = await _get_json("/latest", {"ticker": ticker, "force": force}, timeout=10.0)
    return _store(key, payload, LIVE_TTL_SECONDS) if payload else None


async def get_fx_rate(from_ccy: str, to_ccy: str, force: bool = False) -> Optional[float]:
    if from_ccy == to_ccy:
        return 1.0
    key = f"fx|{from_ccy}|{to_ccy}"
    if not force:
        cached = _cached(key)
        if cached is not None:
            return cached
    payload = await _get_json(
        "/fx/latest", {"base": from_ccy, "quote": to_ccy, "force": force}, timeout=10.0
    )
    rate = payload.get("rate") if payload else None
    return _store(key, rate, LIVE_TTL_SECONDS) if rate is not None else None


async def get_price_on_date(ticker: str, target_date: date) -> Optional[dict]:
    """
    Returns {"price": float, "currency": str, "actual_date": str} for the closing
    price on or before `target_date` (e.g. the prior Friday's close for a
    Saturday date), or None if unavailable. Used to make historical net worth
    points reflect what the price actually was back then, instead of today's
    price.
    """
    # Only a day that is fully over has a final close worth remembering;
    # today's bar is still moving, so it is fetched fresh every time.
    is_final = target_date < date.today()
    key = f"on-date|{ticker}|{target_date.isoformat()}"
    if is_final:
        cached = _cached(key)
        if cached is _NO_CLOSE:
            return None
        if cached is not None:
            return cached
    payload = await _get_json(
        "/on-date", {"ticker": ticker, "date": target_date.isoformat()}, timeout=15.0
    )
    if payload and is_final:
        return _store(key, payload, FOREVER)
    return payload


async def prefetch_closes(tickers: list[str], days: list[date]) -> dict[str, str]:
    """
    Fills the cache get_price_on_date reads with each ticker's close on each
    of `days` (past ones only), from one /series request per ticker covering
    them all -- the history chart values a portfolio on every day, and asking
    for each day separately meant a Yahoo round trip per ticker per day.

    Each day gets exactly what /on-date would answer: the last close within
    ON_DATE_LOOKBACK_DAYS on or before it. A day with none is remembered as
    such only briefly (a series is fetched fresh next time). A ticker whose
    series can't be fetched is left alone: its days are then asked for one by
    one, as without this. Returns each ticker's quotation currency, where known.
    """
    today = date.today()
    past = sorted({d for d in days if d < today})
    quoted_in: dict[str, str] = {}

    async def one(ticker: str) -> None:
        keys = {d: f"on-date|{ticker}|{d.isoformat()}" for d in past}
        missing = [d for d in past if _cached(keys[d]) is None]
        for d in past:
            known = _cached(keys[d])
            if isinstance(known, dict):
                quoted_in[ticker] = known["currency"]
                break
        if not missing:
            return
        first = missing[0] - timedelta(days=ON_DATE_LOOKBACK_DAYS)
        series = await _get_json(
            "/series", {"ticker": ticker, "start": first.isoformat(), "end": missing[-1].isoformat()}, timeout=60.0
        )
        if not series:
            return
        quoted_in[ticker] = series["currency"]
        closes = [(date.fromisoformat(c["date"]), c["close"]) for c in series["closes"]]
        close_dates = [c[0] for c in closes]
        for d in missing:
            i = bisect.bisect_right(close_dates, d) - 1
            if i >= 0 and close_dates[i] >= d - timedelta(days=ON_DATE_LOOKBACK_DAYS):
                payload = {"ticker": ticker, "requested_date": d.isoformat(), "actual_date": close_dates[i].isoformat(),
                           "price": closes[i][1], "currency": series["currency"]}
                _store(keys[d], payload, FOREVER)
            else:
                _store(keys[d], _NO_CLOSE, LIVE_TTL_SECONDS)

    await asyncio.gather(*(one(t) for t in tickers))
    return quoted_in


async def get_fx_rate_on_date(from_ccy: str, to_ccy: str, target_date: date) -> Optional[float]:
    if from_ccy == to_ccy:
        return 1.0
    pair = await get_price_on_date(f"{from_ccy}{to_ccy}=X", target_date)
    return pair["price"] if pair else None


async def fx_rate_at(from_ccy: str, to_ccy: str, day: date) -> float:
    """The rate as it was on `day` for a past day, today's live rate
    otherwise -- 1.0 when none is available. Converting a past amount at
    today's rate would move it every time the rate does."""
    if day < date.today():
        fx = await get_fx_rate_on_date(from_ccy, to_ccy, day)
    else:
        fx = await get_fx_rate(from_ccy, to_ccy)
    return fx if fx is not None else 1.0


async def get_intraday_prices(ticker: str, target_date: date) -> Optional[list]:
    """
    Returns a list of {"time": isoformat, "price": float} hourly points for
    the given trading day, or None on a hard failure (vs. an empty list,
    which is the valid answer for a weekend/holiday with no trading).
    """
    payload = await _get_json(
        "/intraday", {"ticker": ticker, "date": target_date.isoformat()}, timeout=20.0
    )
    return payload.get("points", []) if payload else None
