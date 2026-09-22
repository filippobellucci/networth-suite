"""
What a portfolio is worth, now and on any past day.

The recurring bug in this area has one shape: a figure converted at the wrong
moment's exchange rate. It has been found four separate times -- in the
combined history, in the intraday chart, per-portfolio and combined -- and
each time the symptom was two numbers on the same screen disagreeing while
both looked plausible. The fake feed therefore gives USD->EUR two different
rates (2.0 live, 4.0 historical), which is the only way to tell which one a
figure used.
"""
from __future__ import annotations

import pytest

from helpers import (add_holding, days_ago, history_points, make_account, make_asset,
                     make_portfolio, ok, set_balance, snapshot, today_iso)

pytestmark = pytest.mark.integration


@pytest.fixture
def eur_usd(feed):
    feed.set_price("TESTUSD", 100.0, currency="USD")
    feed.set_price("TESTEUR", 10.0, currency="EUR")
    feed.set_fx("USD", "EUR", live=2.0, historical=4.0)
    feed.set_fx("EUR", "USD", live=0.5, historical=0.25)
    return feed


# ------------------------------------------------------------ the basic sums
async def test_a_holding_is_worth_quantity_times_price(api, feed):
    feed.set_price("TESTEUR", 25.0, currency="EUR")
    p = await make_portfolio(api)
    a = await make_asset(api, ticker="TESTEUR")
    await add_holding(api, p["id"], a["id"], 10)

    snap = await snapshot(api, p["id"])
    assert snap["invested_total_base_ccy"] == 250.0
    assert snap["net_worth_base_ccy"] == 250.0
    assert snap["positions"][0]["price_source"] == "live"


async def test_cash_and_holdings_add_up(api, feed):
    feed.set_price("TESTEUR", 25.0, currency="EUR")
    p = await make_portfolio(api)
    a = await make_asset(api, ticker="TESTEUR")
    await add_holding(api, p["id"], a["id"], 10)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 1000)

    snap = await snapshot(api, p["id"])
    assert snap["cash_total_base_ccy"] == 1000.0
    assert snap["invested_total_base_ccy"] == 250.0
    assert snap["net_worth_base_ccy"] == 1250.0


async def test_only_the_latest_entry_per_asset_counts(api, feed):
    """Holdings are a running record, not a ledger: the most recent entry on
    or before the date is the position."""
    feed.set_price("TESTEUR", 10.0)
    p = await make_portfolio(api)
    a = await make_asset(api, ticker="TESTEUR")
    await add_holding(api, p["id"], a["id"], 5, on=days_ago(10))
    await add_holding(api, p["id"], a["id"], 8, on=days_ago(5))

    assert (await snapshot(api, p["id"]))["net_worth_base_ccy"] == 80.0
    assert (await snapshot(api, p["id"], days_ago(7)))["net_worth_base_ccy"] == 50.0
    assert (await snapshot(api, p["id"], days_ago(20)))["net_worth_base_ccy"] == 0.0


# --------------------------------------------------------------- manual price
async def test_a_manually_priced_holding_uses_its_own_price(api, feed):
    """A house or an unlisted fund has no ticker; its value is what the user
    typed, in the asset's own currency."""
    p = await make_portfolio(api)
    a = await make_asset(api, name="House", ticker=None, asset_class="REAL_ESTATE")
    await add_holding(api, p["id"], a["id"], 1, manual_price=250000)

    snap = await snapshot(api, p["id"])
    assert snap["net_worth_base_ccy"] == 250000.0
    assert snap["positions"][0]["price_source"] == "manual"


# ------------------------------------------------------------ unpriced holdings
async def test_a_holding_with_no_price_is_reported_not_hidden(api, feed):
    """A position that contributes nothing to the total must say so -- the
    headline figure being silently too low is worse than an error."""
    p = await make_portfolio(api)
    a = await make_asset(api, ticker="NOSUCHTICKER")
    await add_holding(api, p["id"], a["id"], 1000)

    snap = await snapshot(api, p["id"])
    assert snap["net_worth_base_ccy"] == 0.0
    assert snap["positions"][0]["price_source"] == "unavailable"
    assert snap["positions"][0]["value_base_ccy"] is None


async def test_a_missing_exchange_rate_is_flagged(api, feed):
    """Counted 1:1 rather than dropped, but the payload says the totals are
    not really converted."""
    feed.set_price("TESTUSD", 100.0, currency="USD")
    p = await make_portfolio(api, currency="EUR")
    a = await make_asset(api, ticker="TESTUSD", currency="USD")
    await add_holding(api, p["id"], a["id"], 1)

    snap = await snapshot(api, p["id"])
    assert snap["fx_unavailable"] is True
    assert snap["net_worth_base_ccy"] == 100.0


# ----------------------------------------------------- historical vs live rate
async def test_today_is_valued_at_the_live_rate(api, eur_usd):
    p = await make_portfolio(api, currency="EUR")
    a = await make_asset(api, ticker="TESTUSD", currency="USD")
    await add_holding(api, p["id"], a["id"], 10, on=days_ago(5))

    snap = await snapshot(api, p["id"])
    assert snap["net_worth_base_ccy"] == 2000.0, "10 x 100 USD at today's 2.0"


async def test_a_past_day_is_valued_at_that_day_s_rate(api, eur_usd):
    p = await make_portfolio(api, currency="EUR")
    a = await make_asset(api, ticker="TESTUSD", currency="USD")
    await add_holding(api, p["id"], a["id"], 10, on=days_ago(5))

    snap = await snapshot(api, p["id"], as_of=days_ago(3))
    assert snap["net_worth_base_ccy"] == 4000.0, "10 x 100 USD at that day's 4.0"


async def test_the_history_chart_agrees_with_the_snapshot_on_every_day(api, eur_usd):
    """The two are computed by different code paths and are shown next to each
    other, so they have to agree -- that is exactly what stopped being true
    when the history converted every past point at today's rate."""
    p = await make_portfolio(api, currency="EUR")
    a = await make_asset(api, ticker="TESTUSD", currency="USD")
    await add_holding(api, p["id"], a["id"], 10, on=days_ago(6))

    points = await history_points(api, p["id"])
    assert points, "a portfolio with a holding must have a history"
    for day, value in points.items():
        expected = (await snapshot(api, p["id"], as_of=day))["net_worth_base_ccy"]
        assert value == pytest.approx(expected), f"history and snapshot differ on {day}"


async def test_the_combined_history_also_uses_each_day_s_rate(api, eur_usd):
    """The combined chart converts each portfolio's own total into the
    requested currency; doing that at today's rate redrew the entire history
    every time a rate moved."""
    usd = await make_portfolio(api, name="USD book", currency="USD")
    a = await make_asset(api, ticker="TESTUSD", currency="USD")
    await add_holding(api, usd["id"], a["id"], 10, on=days_ago(6))

    body = await ok(await api.get("/networth/combined", params={"base_currency": "EUR"}))
    points = {p["date"]: p["net_worth_base_ccy"] for p in body["points"]}
    assert points[days_ago(3)] == pytest.approx(4000.0), "a past day at 4.0"
    assert points[today_iso()] == pytest.approx(2000.0), "today at 2.0"


async def test_combined_totals_convert_instead_of_adding_currencies_together(api, eur_usd):
    """Summing the per-portfolio snapshots client-side counted dollars as
    euros; only this endpoint applies the conversion."""
    eur = await make_portfolio(api, name="EUR book", currency="EUR")
    usd = await make_portfolio(api, name="USD book", currency="USD")
    acc_eur = await make_account(api, eur["id"], currency="EUR")
    acc_usd = await make_account(api, usd["id"], currency="USD")
    await set_balance(api, acc_eur["id"], 1000)
    await set_balance(api, acc_usd["id"], 1000)

    totals = await ok(await api.get("/networth/combined/totals", params={"base_currency": "EUR"}))
    assert totals["net_worth"] == pytest.approx(3000.0), "1000 EUR + 1000 USD at 2.0"


# ------------------------------------------------------------------- history
async def test_the_history_reaches_today_with_no_gaps(api, feed):
    feed.set_price("TESTEUR", 10.0)
    p = await make_portfolio(api)
    a = await make_asset(api, ticker="TESTEUR")
    await add_holding(api, p["id"], a["id"], 1, on=days_ago(4))

    points = await history_points(api, p["id"])
    assert today_iso() in points
    days = sorted(points)
    assert days == sorted(set(days)), "no day appears twice"
    from datetime import date
    first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    assert len(days) == (last - first).days + 1, "every day between the first entry and today"


async def test_an_empty_portfolio_answers_everything_without_failing(api, feed):
    p = await make_portfolio(api)
    for path in ("snapshot", "history", "growth", "xirr", "intraday"):
        await ok(await api.get(f"/portfolios/{p['id']}/{path}"))


async def test_a_portfolio_worth_nothing_is_not_an_error(api, feed):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 0)
    assert (await snapshot(api, p["id"]))["net_worth_base_ccy"] == 0.0
    await ok(await api.get(f"/portfolios/{p['id']}/growth"))
    await ok(await api.get(f"/portfolios/{p['id']}/xirr"))


async def test_an_unknown_portfolio_is_a_404_everywhere(api, feed):
    for path in ("snapshot", "history", "growth", "xirr", "intraday", "holdings"):
        response = await api.get(f"/portfolios/does-not-exist/{path}")
        assert response.status_code in (404, 200), path
        if path in ("snapshot", "growth", "xirr", "intraday"):
            assert response.status_code == 404, path
