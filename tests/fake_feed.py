"""
A price feed the tests control completely.

It replaces `price_client._get_json` -- the single HTTP boundary between
core-networth and the price-feed service -- rather than the public helpers
above it. That matters: the interesting bugs lived in the layers in between,
so those layers have to stay in the test. Stubbing `_get_json` keeps the real
caching (a past day's close is permanent, a live one expires), the real
"EURUSD=X" pair-ticker construction inside `get_fx_rate_on_date`, and the real
"a 404 means unavailable" handling, while making every price deterministic.

A separate live and historical rate per currency pair is deliberate: several
fixed bugs were the wrong one of the two being used, and they are only
distinguishable when the two differ.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional


class FakeFeed:
    def __init__(self) -> None:
        # ticker -> (price, currency)
        self.prices: dict[str, tuple[float, str]] = {}
        # (ticker, isoformat date) -> price, overriding `prices` for that day
        self.prices_on: dict[tuple[str, str], float] = {}
        # (base, quote) -> rate
        self.fx_live: dict[tuple[str, str], float] = {}
        self.fx_historical: dict[tuple[str, str], float] = {}
        # (ticker, isoformat date) -> [price, ...] one per hour from 10:00
        self.intraday: dict[tuple[str, str], list[float]] = {}
        # every request that actually reached the "network", for cache assertions
        self.calls: list[tuple[str, dict]] = []

    # ---------------------------------------------------------------- setup
    def set_price(self, ticker: str, price: float, currency: str = "EUR") -> None:
        self.prices[ticker] = (price, currency)

    def set_price_on(self, ticker: str, day: date, price: float) -> None:
        self.prices_on[(ticker, day.isoformat())] = price

    def set_fx(self, base: str, quote: str, live: float, historical: Optional[float] = None) -> None:
        """`historical` defaults to `live`; set it differently to tell apart a
        conversion that used today's rate from one that used that day's."""
        self.fx_live[(base, quote)] = live
        self.fx_historical[(base, quote)] = live if historical is None else historical

    def set_intraday(self, ticker: str, day: date, prices: list[float]) -> None:
        self.intraday[(ticker, day.isoformat())] = list(prices)

    def forget(self, ticker: str) -> None:
        """Make a ticker unpriceable, the way the real service 404s."""
        self.prices.pop(ticker, None)

    # ------------------------------------------------------------- the stub
    async def get_json(self, path: str, params: dict, timeout: float):
        self.calls.append((path, dict(params)))

        if path == "/latest":
            ticker = params["ticker"]
            if ticker not in self.prices:
                return None
            price, currency = self.prices[ticker]
            return {"ticker": ticker, "price": price, "currency": currency}

        if path == "/fx/latest":
            base, quote = params["base"], params["quote"]
            rate = self.fx_live.get((base, quote))
            if rate is None:
                return None
            return {"base": base, "quote": quote, "rate": rate}

        if path == "/on-date":
            ticker, day = params["ticker"], params["date"]
            if ticker.endswith("=X"):
                pair = ticker[:-2]
                base, quote = pair[:3], pair[3:6]
                rate = self.fx_historical.get((base, quote))
                if rate is None:
                    return None
                return {"ticker": ticker, "price": rate, "currency": quote,
                        "requested_date": day, "actual_date": day}
            if (ticker, day) in self.prices_on:
                price = self.prices_on[(ticker, day)]
            elif ticker in self.prices:
                price = self.prices[ticker][0]
            else:
                return None
            currency = self.prices.get(ticker, (0.0, "EUR"))[1]
            return {"ticker": ticker, "price": price, "currency": currency,
                    "requested_date": day, "actual_date": day}

        if path == "/intraday":
            ticker, day = params["ticker"], params["date"]
            prices = self.intraday.get((ticker, day))
            if prices is None:
                # a weekend or a ticker with no hourly data: a valid empty answer
                return {"ticker": ticker, "date": day, "points": []}
            base_day = datetime.fromisoformat(day)
            points = [
                {"time": base_day.replace(hour=10 + i).isoformat(), "price": p}
                for i, p in enumerate(prices)
            ]
            return {"ticker": ticker, "date": day, "points": points}

        raise AssertionError(f"FakeFeed got an unexpected price-feed path: {path}")
