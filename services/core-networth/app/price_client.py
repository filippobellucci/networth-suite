"""
Thin client for the price-feed service. Kept isolated so the core service
never talks to yfinance (or any market-data source) directly -- it only
knows about the internal HTTP contract of the price-feed module.
"""
from datetime import date
from typing import Optional
import httpx

from .config import PRICE_FEED_URL


async def get_latest_price(ticker: str, force: bool = False) -> Optional[dict]:
    """Returns {"price": float, "currency": str} or None if unavailable."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{PRICE_FEED_URL}/latest", params={"ticker": ticker, "force": force}
            )
            if resp.status_code == 200:
                return resp.json()
    except httpx.HTTPError:
        pass
    return None


async def get_fx_rate(from_ccy: str, to_ccy: str, force: bool = False) -> Optional[float]:
    if from_ccy == to_ccy:
        return 1.0
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{PRICE_FEED_URL}/fx/latest", params={"base": from_ccy, "quote": to_ccy, "force": force}
            )
            if resp.status_code == 200:
                return resp.json().get("rate")
    except httpx.HTTPError:
        pass
    return None


async def get_price_on_date(ticker: str, target_date: date) -> Optional[dict]:
    """
    Returns {"price": float, "currency": str, "actual_date": str} for the closing
    price on or before `target_date` (e.g. the prior Friday's close for a
    Saturday date), or None if unavailable. Used to make historical net worth
    points reflect what the price actually was back then, instead of today's
    price.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{PRICE_FEED_URL}/on-date",
                params={"ticker": ticker, "date": target_date.isoformat()},
            )
            if resp.status_code == 200:
                return resp.json()
    except httpx.HTTPError:
        pass
    return None


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
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{PRICE_FEED_URL}/intraday",
                params={"ticker": ticker, "date": target_date.isoformat()},
            )
            if resp.status_code == 200:
                return resp.json().get("points", [])
    except httpx.HTTPError:
        pass
    return None
