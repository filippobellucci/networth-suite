"""
Thin client for the price-feed service. Kept isolated so the core service
never talks to yfinance (or any market-data source) directly -- it only
knows about the internal HTTP contract of the price-feed module.

Two things here exist purely for speed, and they matter a lot: building a
historical chart values the portfolio once per tracked day, and every one of
those valuations needs a price and an FX rate.

  * One shared HTTP client per event loop, instead of a fresh
    httpx.AsyncClient per call. Opening a client per request meant a new
    connection (and TLS/socket setup) for every single day plotted -- with
    ~600 days of history that alone took ~90ms per call, nearly a minute per
    chart, and the gateway's 30s timeout turned it into a failed page load.
  * A small in-process cache. A completed day's close and a past day's FX
    rate can never change, so they're cached for the life of the process;
    live prices/rates get a short TTL, and `force=True` (the "Refresh
    prices" action, the scheduler's warm-up) always bypasses and refreshes
    it. The price-feed service caches too, but only after the request has
    already crossed the network.
"""
import asyncio
import time
import weakref
from datetime import date
from typing import Any, Optional

import httpx

from .config import PRICE_FEED_URL

LIVE_TTL_SECONDS = 60
# A price or rate for a day that is already over is final; keep it forever.
FOREVER = float("inf")

_cache: dict[str, tuple[float, float, Any]] = {}  # key -> (stored_at, ttl, payload)
# One client per event loop, since a client is bound to the loop it was
# created on. A weak map keyed by the loop *object*, rather than a plain dict
# keyed by id(loop), for two reasons:
#
#   * nothing ever removed an id() entry, so every loop that had ever run left
#     its client behind for the life of the process -- 50 short-lived loops
#     left 33 clients (and their transports) still held;
#   * id() is an address, and CPython hands the same address out again once
#     the object at it is freed -- in that same run, 17 of the 50 new loops
#     landed on the address of a loop already gone, and so were given that
#     loop's client. It happened to be harmless there because the client had
#     been closed and `is_closed` below replaces it; a client left open by a
#     loop that simply went away is not caught that way, and every request
#     through it fails on the dead loop.
#
# Keying on the object sidesteps both: entries vanish when their loop is
# collected, and two distinct loops can never collide. A client whose loop is
# gone cannot be awaited shut in any case -- its transport is released with it.
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
        if cached is not None:
            return cached
    payload = await _get_json(
        "/on-date", {"ticker": ticker, "date": target_date.isoformat()}, timeout=15.0
    )
    if payload and is_final:
        return _store(key, payload, FOREVER)
    return payload


async def get_fx_rate_on_date(from_ccy: str, to_ccy: str, target_date: date) -> Optional[float]:
    if from_ccy == to_ccy:
        return 1.0
    pair = await get_price_on_date(f"{from_ccy}{to_ccy}=X", target_date)
    return pair["price"] if pair else None


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
