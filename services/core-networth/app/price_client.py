"""
Thin client for the price-feed service. Kept isolated so the core service
never talks to yfinance (or any market-data source) directly -- it only
knows about the internal HTTP contract of the price-feed module.
"""
from typing import Optional
import httpx

from .config import PRICE_FEED_URL


async def get_latest_price(ticker: str, force: bool = False) -> Optional[dict]:
    """Returns {"price": float, "currency": str} or None if unavailable."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{PRICE_FEED_URL}/prices/latest", params={"ticker": ticker, "force": force}
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
