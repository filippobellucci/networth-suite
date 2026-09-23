"""
Idempotency-Key on the endpoints that move money.

The header exists for one situation: a client whose request timed out retries
while the original is still in flight. Checking the key and running the
mutation used to be two steps, so both copies passed the check before either
committed and both ran -- sixteen simultaneous replays of one key produced
three transactions. The key row is now written inside the same transaction as
the mutation it guards, so the two commit or roll back together.
"""
from __future__ import annotations

import asyncio

import pytest

from helpers import days_ago, make_account, make_asset, make_portfolio, ok, set_balance, today_iso

pytestmark = pytest.mark.integration


@pytest.fixture
async def account(api, feed):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 10000, on=days_ago(20))
    return {"portfolio": p, "account": acc}


def expense(amount=25.0):
    return {"entry_date": today_iso(), "direction": "EXPENSE", "amount": amount}


async def test_replaying_a_key_returns_the_first_answer(api, account):
    path = f"/cash-accounts/{account['account']['id']}/transactions"
    headers = {"Idempotency-Key": "retry-me"}
    first = await ok(await api.post(path, json=expense(), headers=headers))
    second = await ok(await api.post(path, json=expense(), headers=headers))
    assert first["id"] == second["id"], "a replay must not create a second transaction"

    rows = await ok(await api.get(path))
    assert len(rows) == 1


async def test_a_replay_does_not_move_the_balance_twice(api, account):
    path = f"/cash-accounts/{account['account']['id']}/transactions"
    headers = {"Idempotency-Key": "retry-me"}
    await ok(await api.post(path, json=expense(100), headers=headers))
    await ok(await api.post(path, json=expense(100), headers=headers))

    snap = await ok(await api.get(f"/portfolios/{account['portfolio']['id']}/snapshot"))
    assert snap["cash_total_base_ccy"] == 9900.0


async def test_different_keys_are_different_requests(api, account):
    path = f"/cash-accounts/{account['account']['id']}/transactions"
    a = await ok(await api.post(path, json=expense(), headers={"Idempotency-Key": "one"}))
    b = await ok(await api.post(path, json=expense(), headers={"Idempotency-Key": "two"}))
    assert a["id"] != b["id"]
    assert len(await ok(await api.get(path))) == 2


async def test_without_the_header_nothing_is_deduplicated(api, account):
    """The feature is opt-in: two identical requests with no key are two
    genuine transactions, which is what logging the same coffee twice is."""
    path = f"/cash-accounts/{account['account']['id']}/transactions"
    await ok(await api.post(path, json=expense()))
    await ok(await api.post(path, json=expense()))
    assert len(await ok(await api.get(path))) == 2


async def test_simultaneous_replays_create_exactly_one_transaction(api, account):
    """The race the header exists for. Whichever request commits first owns
    the key; the losers replay its answer or are told to retry, and never
    land a duplicate."""
    path = f"/cash-accounts/{account['account']['id']}/transactions"
    headers = {"Idempotency-Key": "stampede"}

    responses = await asyncio.gather(
        *[api.post(path, json=expense(75), headers=headers) for _ in range(16)]
    )

    assert all(r.status_code in (200, 409) for r in responses), \
        sorted({r.status_code for r in responses})
    rows = await ok(await api.get(path))
    assert len(rows) == 1, f"{len(rows)} transactions from 16 simultaneous replays"

    succeeded = [r.json()["id"] for r in responses if r.status_code == 200]
    assert len(set(succeeded)) == 1, "every success must describe the same transaction"


async def test_the_key_guards_holdings_and_transfers_too(api, account, feed):
    p = account["portfolio"]
    asset = await make_asset(api, ticker="TESTEUR")
    feed.set_price("TESTEUR", 10.0)
    headers = {"Idempotency-Key": "holding-key"}
    body = {"asset_id": asset["id"], "entry_date": today_iso(), "quantity": 5}
    first = await ok(await api.post(f"/portfolios/{p['id']}/holdings", json=body, headers=headers))
    second = await ok(await api.post(f"/portfolios/{p['id']}/holdings", json=body, headers=headers))
    assert first["id"] == second["id"]

    other = await make_account(api, p["id"], name="Other")
    await set_balance(api, other["id"], 0, on=days_ago(20))
    transfer_body = {"from_account_id": account["account"]["id"], "to_account_id": other["id"],
                     "entry_date": today_iso(), "amount": 50}
    t_headers = {"Idempotency-Key": "transfer-key"}
    t1 = await ok(await api.post("/transfers", json=transfer_body, headers=t_headers))
    t2 = await ok(await api.post("/transfers", json=transfer_body, headers=t_headers))
    assert t1["transfer_id"] == t2["transfer_id"]

    snap = await ok(await api.get(f"/portfolios/{p['id']}/snapshot"))
    moved = {c["account_id"]: c["balance"] for c in snap["cash_positions"]}
    assert moved[other["id"]] == 50.0, "the transfer happened exactly once"
