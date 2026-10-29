"""
Prices for many days come in one request per ticker, and answer the same.

The history chart values the portfolio on every day it covers. Each of those
valuations asked price-feed for each ticker's close on that day, one request
at a time -- and price-feed asked Yahoo, so after a restart two years of
history cost some 5,000 Yahoo round trips for six ETFs. `warm_prices` now
fetches each ticker's (and each currency pair's) series once; these tests pin
that it does, and that what it fills in is exactly what the day-by-day path
would have answered.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from helpers import add_holding, days_ago, history_points, make_account, make_asset, make_portfolio, ok, set_balance

pytestmark = pytest.mark.integration


async def _usd_portfolio(api, feed):
    feed.set_price("TESTEUR", 10.0)
    feed.set_price("TESTUSD", 50.0, currency="USD")
    feed.set_price_on("TESTUSD", date.fromisoformat(days_ago(20)), 40.0)
    feed.set_fx("USD", "EUR", live=2.0, historical=4.0)
    p = await make_portfolio(api)
    for ticker, qty in (("TESTEUR", 3), ("TESTUSD", 2)):
        a = await make_asset(api, name=ticker, ticker=ticker, currency="USD" if ticker == "TESTUSD" else "EUR")
        await add_holding(api, p["id"], a["id"], qty, on=days_ago(40))
    acc = await make_account(api, p["id"], currency="USD")
    await set_balance(api, acc["id"], 100, on=days_ago(30))
    return p


async def test_the_history_asks_for_one_series_per_ticker_and_pair(api, feed):
    p = await _usd_portfolio(api, feed)
    feed.calls.clear()
    points = await history_points(api, p["id"])
    assert len(points) == 32, "the two entry days, then every day from the last one to today"
    paths = [c[0] for c in feed.calls]
    assert sorted(c[1]["ticker"] for c in feed.calls if c[0] == "/series") == ["TESTEUR", "TESTUSD", "USDEUR=X"]
    assert "/on-date" not in paths, "every past close came from the series"


async def test_the_series_gives_the_same_history_as_asking_day_by_day(api, feed, core_modules):
    p = await _usd_portfolio(api, feed)
    with_series = await history_points(api, p["id"])

    core_modules["price_client"]._cache.clear()
    feed.series_available = False
    feed.calls.clear()
    day_by_day = await history_points(api, p["id"])
    assert any(c[0] == "/on-date" for c in feed.calls), "without /series it falls back to one request per day"
    assert day_by_day == with_series
    assert with_series[days_ago(20)] == pytest.approx(3 * 10 + 2 * 40 * 4 + 100 * 4), "that day's close and rate"


async def test_growth_and_xirr_read_the_series_too(api, feed):
    p = await _usd_portfolio(api, feed)
    feed.calls.clear()
    await ok(await api.get(f"/portfolios/{p['id']}/growth"))
    await ok(await api.get(f"/portfolios/{p['id']}/xirr"))
    assert "/on-date" not in [c[0] for c in feed.calls]


async def test_a_close_is_looked_for_ten_days_back_and_no_further(core_modules, monkeypatch):
    """price-feed's /on-date answers the last close in the ten days up to a
    day, and nothing past that; read out of a series, a day must get the same."""
    price_client = core_modules["price_client"]
    price_client._cache.clear()
    friday = date.today() - timedelta(days=60)
    calls = []

    async def get_json(path, params, timeout):
        calls.append(path)
        if path == "/series":
            return {"ticker": "GAPPY", "currency": "EUR", "closes": [{"date": friday.isoformat(), "close": 12.5}]}
        return None

    monkeypatch.setattr(price_client, "_get_json", get_json)
    within, beyond = friday + timedelta(days=10), friday + timedelta(days=11)
    assert await price_client.prefetch_closes(["GAPPY"], [friday, within, beyond]) == {"GAPPY": "EUR"}

    got = await price_client.get_price_on_date("GAPPY", within)
    assert (got["price"], got["actual_date"], got["requested_date"]) == (12.5, friday.isoformat(), within.isoformat())
    assert await price_client.get_price_on_date("GAPPY", beyond) is None
    assert calls == ["/series"], "neither day went back to the network"
