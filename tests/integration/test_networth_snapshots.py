"""
Frozen net worth snapshots: a snapshot never changes once taken, so it is
only taken from totals that are complete.

A holding with no price is counted as zero, and an amount whose exchange
rate is missing is converted 1:1. The live pages say so on screen and
correct themselves once the feed answers again; a frozen month-end row did
neither, and kept the wrong, plausible-looking total in the history for good.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from helpers import add_holding, days_ago, make_account, make_asset, make_portfolio, ok, set_balance

pytestmark = pytest.mark.integration


async def snapshots(api):
    return await ok(await api.get("/networth-snapshots", params={"currency": "EUR"}))


async def test_a_snapshot_is_refused_while_a_holding_has_no_price(api, feed):
    p = await make_portfolio(api)
    asset = await make_asset(api, name="World ETF", ticker="WORLD.MI")
    await add_holding(api, p["id"], asset["id"], 10)
    account = await make_account(api, p["id"])
    await set_balance(api, account["id"], 500)

    refused = await api.post("/networth-snapshots", json={"currency": "EUR"})
    assert refused.status_code == 409
    assert "World ETF" in refused.json()["detail"], "the message must name what is missing"
    assert await snapshots(api) == [], "the incomplete total (500 instead of 1,500) must not be frozen"

    feed.set_price("WORLD.MI", 100.0)
    taken = await ok(await api.post("/networth-snapshots", json={"currency": "EUR"}))
    assert taken["net_worth"] == 1500.0


async def test_a_snapshot_is_refused_while_an_exchange_rate_is_missing(api, feed):
    p = await make_portfolio(api)
    account = await make_account(api, p["id"], currency="USD")
    await set_balance(api, account["id"], 1000)

    refused = await api.post("/networth-snapshots", json={"currency": "EUR"})
    assert refused.status_code == 409, "1,000 dollars counted as 1,000 euros must not be frozen"
    assert "exchange rate" in refused.json()["detail"]

    feed.set_fx("USD", "EUR", 0.5)
    taken = await ok(await api.post("/networth-snapshots", json={"currency": "EUR"}))
    assert taken["net_worth"] == 500.0


async def test_a_month_end_with_a_missing_price_is_postponed_not_frozen(api, feed, core_modules, db_engine, monkeypatch):
    """The scheduler's catch-up leaves the month out and fills it on a later
    cycle, once the price is back -- with that day's real close."""
    from sqlalchemy.orm import sessionmaker

    scheduler = core_modules["scheduler"]
    monkeypatch.setattr(scheduler, "SessionLocal", sessionmaker(bind=db_engine))

    last_month_end = date.today().replace(day=1) - timedelta(days=1)
    p = await make_portfolio(api)
    asset = await make_asset(api, name="World ETF", ticker="WORLD.MI")
    await add_holding(api, p["id"], asset["id"], 10, on=days_ago(70))

    await scheduler.catch_up_monthly_snapshots()
    assert await snapshots(api) == []

    feed.set_price("WORLD.MI", 100.0)
    feed.set_price_on("WORLD.MI", last_month_end, 90.0)
    await scheduler.catch_up_monthly_snapshots()
    rows = {s["snapshot_date"]: s for s in await snapshots(api)}
    assert rows[last_month_end.isoformat()]["net_worth"] == 900.0
    assert all(s["source"] == "auto" for s in rows.values())
