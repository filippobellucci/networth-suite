"""
How many queries a page costs must not grow with how much data there is.

Every slow page this app has had was the same shape: a query per day plotted,
per account, per transaction. Two years of daily expenses made the history
chart 13,893 queries and 11 seconds. These tests count the statements each
heavy endpoint runs on a small ledger and on one ten times its size: the two
counts must be equal, so a per-row query reappearing anywhere fails here
before anyone feels it.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event

from helpers import add_holding, add_transaction, days_ago, make_account, make_asset, make_portfolio, ok, set_balance

pytestmark = pytest.mark.integration


@pytest.fixture
def statements(db_engine):
    count = [0]

    def on_execute(*_args, **_kwargs):
        count[0] += 1

    event.listen(db_engine, "before_cursor_execute", on_execute)
    yield count
    event.remove(db_engine, "before_cursor_execute", on_execute)


async def _ledger(api, days):
    p = await make_portfolio(api, name=f"{days} days")
    asset = await make_asset(api, name=f"ETF {days}", ticker="TESTEUR")
    acc = await make_account(api, p["id"])
    other = await make_account(api, p["id"], name="Other")
    await set_balance(api, acc["id"], 1000, on=days_ago(days + 1))
    cat = await ok(await api.post("/expense-categories", json={"portfolio_id": p["id"], "name": "Spesa"}))
    for i in range(days, 0, -1):
        if i % 7 == 0:
            await add_holding(api, p["id"], asset["id"], days - i + 1, on=days_ago(i))
        expense = await add_transaction(api, acc["id"], "EXPENSE", 5 + i % 3, on=days_ago(i), category_id=cat["id"])
        if i % 5 == 0:
            await add_transaction(api, other["id"], "INCOME", 1, on=days_ago(i), refund_of_id=None)
            await add_transaction(api, acc["id"], "INCOME", 2, on=days_ago(i), refund_of_id=expense["id"])
    return p


async def _count(api, statements, path, params=None):
    statements[0] = 0
    await ok(await api.get(path, params=params))
    return statements[0]


@pytest.mark.parametrize("path,params", [
    ("/portfolios/{p}/snapshot", None),
    ("/portfolios/{p}/history", None),
    ("/portfolios/{p}/growth", None),
    ("/portfolios/{p}/xirr", None),
    ("/expenses/summary", {"from_date": days_ago(400), "to_date": days_ago(0)}),
    ("/expenses/monthly", {"months": 12}),
    ("/recurring", {}),
    ("/budgets/progress", {}),
])
async def test_the_query_count_does_not_grow_with_the_data(api, feed, statements, path, params):
    feed.set_price("TESTEUR", 10.0)
    counts = []
    for days in (12, 120):
        p = await _ledger(api, days)
        query = {**params, "portfolio_id": p["id"]} if params is not None else None
        counts.append(await _count(api, statements, path.format(p=p["id"]), query))
    assert counts[0] == counts[1], f"{path}: {counts[0]} queries for 12 days of data, {counts[1]} for 120"


async def test_an_assets_growth_asks_for_one_series_not_one_close_per_period(api, feed):
    feed.set_price("TESTEUR", 10.0)
    p = await make_portfolio(api)
    asset = await make_asset(api, ticker="TESTEUR")
    await add_holding(api, p["id"], asset["id"], 1, on=days_ago(500))
    feed.calls.clear()
    await ok(await api.get(f"/assets/{asset['id']}/growth"))
    assert [c[0] for c in feed.calls if c[0] in ("/series", "/on-date")] == ["/series"]
