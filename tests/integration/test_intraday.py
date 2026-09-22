"""
The hourly "Day" line.

Two things are held flat across the day by design -- cash, which has no
intraday granularity, and the exchange rate, so the chart does not need an FX
lookup per hour. "Flat" is the intended simplification; *which day's* rate and
*which day's* cash balance it holds flat is not, and both were wrong for a
past date at some point.
"""
from __future__ import annotations

from datetime import date

import pytest

from helpers import (add_holding, add_transaction, days_ago, make_account, make_asset,
                     make_portfolio, ok, set_balance, snapshot)

pytestmark = pytest.mark.integration


@pytest.fixture
def usd_fund(feed):
    feed.set_price("TESTUSD", 100.0, currency="USD")
    feed.set_fx("USD", "EUR", live=2.0, historical=4.0)
    feed.set_intraday("TESTUSD", date.today(), [100.0, 101.0, 102.0])
    return feed


async def test_today_uses_the_live_rate(api, usd_fund):
    p = await make_portfolio(api, currency="EUR")
    a = await make_asset(api, ticker="TESTUSD", currency="USD")
    await add_holding(api, p["id"], a["id"], 10, on=days_ago(5))

    body = await ok(await api.get(f"/portfolios/{p['id']}/intraday"))
    assert body["points"], "a ticker with hourly data must produce points"
    assert body["points"][0]["net_worth_base_ccy"] == pytest.approx(2000.0), "10 x 100 at 2.0"


async def test_a_past_day_uses_that_day_s_rate(api, usd_fund):
    """Converting a past day's hourly line at today's live rate made it
    disagree with the same day's point on the history chart beside it by
    however far the rate had moved since."""
    when = days_ago(4)
    usd_fund.set_intraday("TESTUSD", date.fromisoformat(when),
                          [100.0, 100.0, 100.0])
    p = await make_portfolio(api, currency="EUR")
    a = await make_asset(api, ticker="TESTUSD", currency="USD")
    await add_holding(api, p["id"], a["id"], 10, on=days_ago(6))

    body = await ok(await api.get(f"/portfolios/{p['id']}/intraday", params={"for_date": when}))
    assert body["points"]
    for point in body["points"]:
        assert point["net_worth_base_ccy"] == pytest.approx(4000.0), "that day's 4.0, not today's 2.0"


async def test_a_past_day_agrees_with_that_day_s_snapshot(api, usd_fund):
    """The strongest form of the same statement: whatever the intraday line
    says, the snapshot for that date has to say too."""
    when = days_ago(4)
    usd_fund.set_intraday("TESTUSD", date.fromisoformat(when),
                          [100.0, 100.0])
    p = await make_portfolio(api, currency="EUR")
    a = await make_asset(api, ticker="TESTUSD", currency="USD")
    await add_holding(api, p["id"], a["id"], 10, on=days_ago(6))

    body = await ok(await api.get(f"/portfolios/{p['id']}/intraday", params={"for_date": when}))
    expected = (await snapshot(api, p["id"], as_of=when))["net_worth_base_ccy"]
    assert body["points"][0]["net_worth_base_ccy"] == pytest.approx(expected)


async def test_the_combined_line_also_uses_that_day_s_rate(api, usd_fund):
    when = days_ago(4)
    usd_fund.set_intraday("TESTUSD", date.fromisoformat(when), [100.0])
    usd = await make_portfolio(api, name="USD book", currency="USD")
    a = await make_asset(api, ticker="TESTUSD", currency="USD")
    await add_holding(api, usd["id"], a["id"], 10, on=days_ago(6))

    body = await ok(await api.get("/networth/combined/intraday",
                                  params={"for_date": when, "base_currency": "EUR"}))
    history = await ok(await api.get("/networth/combined", params={"base_currency": "EUR"}))
    same_day = [p["net_worth_base_ccy"] for p in history["points"] if p["date"] == when][0]
    assert body["points"]
    assert body["points"][0]["net_worth_base_ccy"] == pytest.approx(same_day)


async def test_cash_is_that_day_s_balance_not_today_s(api, usd_fund):
    p = await make_portfolio(api, currency="EUR")
    a = await make_asset(api, ticker="TESTUSD", currency="USD")
    await add_holding(api, p["id"], a["id"], 1, on=days_ago(10))
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    await add_transaction(api, acc["id"], "EXPENSE", 400, on=days_ago(1))

    when = days_ago(5)
    usd_fund.set_intraday("TESTUSD", date.fromisoformat(when), [100.0])
    body = await ok(await api.get(f"/portfolios/{p['id']}/intraday", params={"for_date": when}))
    # 1 x 100 USD at 4.0 = 400, plus the cash as it stood that day (1000)
    assert body["points"][0]["net_worth_base_ccy"] == pytest.approx(1400.0)


async def test_a_portfolio_with_no_hourly_data_returns_an_empty_series(api, feed):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 500)
    body = await ok(await api.get(f"/portfolios/{p['id']}/intraday"))
    assert body["points"] == []


async def test_an_unparseable_date_is_refused_rather_than_crashing(api, feed):
    p = await make_portfolio(api)
    response = await api.get(f"/portfolios/{p['id']}/intraday", params={"for_date": "nope"})
    assert response.status_code == 422
    response = await api.get("/networth/combined/intraday", params={"for_date": "2026-13-45"})
    assert response.status_code == 422
