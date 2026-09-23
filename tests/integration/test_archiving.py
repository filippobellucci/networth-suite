"""
Removing things without rewriting the past.

Nothing here is hard-deleted, and the reason is the bug that made it so:
deleting a cash account outright retroactively erased its contribution from
every past date too, producing a fake overnight swing on the day it was
removed. So an archived account still counts for every date before the day it
was archived, and stops counting from that day on.

That date comparison is the whole feature, and it is also where it broke
again: the timestamp was written in UTC while every date it is compared
against is local, so for the hours each day when the two differ the account
appeared or disappeared a day early or late.
"""
from __future__ import annotations

import pytest

from helpers import (add_transaction, days_ago, make_account, make_portfolio, ok,
                     set_balance, snapshot, today_iso)

pytestmark = pytest.mark.integration


async def test_an_archived_account_still_counts_before_it_was_archived(api, feed):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    await ok(await api.delete(f"/cash-accounts/{acc['id']}"), 204)

    yesterday = (await snapshot(api, p["id"], as_of=days_ago(1)))["net_worth_base_ccy"]
    assert yesterday == 1000.0, "removing it today must not rewrite yesterday"


async def test_an_archived_account_stops_counting_from_today(api, feed):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    await ok(await api.delete(f"/cash-accounts/{acc['id']}"), 204)

    assert (await snapshot(api, p["id"]))["net_worth_base_ccy"] == 0.0


async def test_the_archived_date_is_judged_on_the_local_calendar(api, feed):
    """Written with utcnow() while compared against local dates, an account
    archived late in the evening west of UTC stayed in today's totals, and one
    archived just after midnight east of UTC dropped out of YESTERDAY's -- the
    retroactive rewrite this whole design exists to prevent."""
    from datetime import datetime

    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    await ok(await api.delete(f"/cash-accounts/{acc['id']}"), 204)

    rows = await ok(await api.get(f"/portfolios/{p['id']}/cash-accounts",
                                  params={"include_archived": True}))
    archived_at = datetime.fromisoformat(rows[0]["archived_at"])
    assert archived_at.date() == datetime.now().date(), (
        "archived_at must be recorded on the same clock as the dates it is compared with"
    )


async def test_an_archived_account_is_hidden_by_default_and_available_on_request(api, feed):
    """Every picker offering somewhere to log something wants active accounts
    only. A read-only view describing rows that already exist needs the
    archived ones too -- without them an archived dollar account's past
    spending rendered, with no warning, as euros."""
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"], name="Closed", currency="USD")
    await set_balance(api, acc["id"], 100, on=days_ago(10))
    await ok(await api.delete(f"/cash-accounts/{acc['id']}"), 204)

    active = await ok(await api.get(f"/portfolios/{p['id']}/cash-accounts"))
    assert active == []

    everything = await ok(await api.get(f"/portfolios/{p['id']}/cash-accounts",
                                        params={"include_archived": True}))
    assert len(everything) == 1
    assert everything[0]["currency"] == "USD", "its currency is what the caller needed"
    assert everything[0]["archived_at"] is not None


async def test_an_archived_account_keeps_its_transactions(api, feed):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    await add_transaction(api, acc["id"], "EXPENSE", 50, on=days_ago(5))
    await ok(await api.delete(f"/cash-accounts/{acc['id']}"), 204)

    rows = await ok(await api.get(f"/cash-accounts/{acc['id']}/transactions"))
    assert len(rows) == 1, "removing the account never removes what was logged against it"


async def test_nothing_new_can_be_logged_against_an_archived_account(api, feed):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    await ok(await api.delete(f"/cash-accounts/{acc['id']}"), 204)

    response = await api.post(f"/cash-accounts/{acc['id']}/transactions", json={
        "entry_date": today_iso(), "direction": "EXPENSE", "amount": 10})
    assert response.status_code == 400


# ---------------------------------------------------------- archived portfolios
async def test_an_archived_portfolio_leaves_every_combined_aggregate(api, feed):
    """All six combined endpoints have to agree about this. One of them
    disagreeing means the dashboard's tile and its chart show different
    money."""
    keep = await make_portfolio(api, name="Active", currency="EUR")
    drop = await make_portfolio(api, name="Archived", currency="EUR")
    for p, amount in ((keep, 1000), (drop, 500)):
        acc = await make_account(api, p["id"])
        await set_balance(api, acc["id"], amount, on=days_ago(5))

    before = await ok(await api.get("/networth/combined/totals"))
    assert before["net_worth"] == 1500.0

    await ok(await api.patch(f"/portfolios/{drop['id']}", json={"archived": True}))

    totals = await ok(await api.get("/networth/combined/totals"))
    assert totals["net_worth"] == 1000.0

    history = await ok(await api.get("/networth/combined"))
    assert history["points"][-1]["net_worth_base_ccy"] == 1000.0

    listed = await ok(await api.get("/portfolios"))
    assert [x["id"] for x in listed] == [keep["id"]]

    with_archived = await ok(await api.get("/portfolios", params={"include_archived": True}))
    assert {x["id"] for x in with_archived} == {keep["id"], drop["id"]}


async def test_an_archived_portfolio_can_still_be_read_directly(api, feed):
    """It is hidden from the aggregates, not deleted."""
    p = await make_portfolio(api, name="Archived")
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 700, on=days_ago(5))
    await ok(await api.patch(f"/portfolios/{p['id']}", json={"archived": True}))

    assert (await snapshot(api, p["id"]))["net_worth_base_ccy"] == 700.0


async def test_un_archiving_puts_it_back(api, feed):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 700, on=days_ago(5))
    await ok(await api.patch(f"/portfolios/{p['id']}", json={"archived": True}))
    assert (await ok(await api.get("/networth/combined/totals")))["net_worth"] == 0.0
    await ok(await api.patch(f"/portfolios/{p['id']}", json={"archived": False}))
    assert (await ok(await api.get("/networth/combined/totals")))["net_worth"] == 700.0
