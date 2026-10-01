"""
Fixing up transactions after the fact: the uncategorized filter, bulk
categorizing, and turning a one-sided income/expense into a transfer.

All three exist for what bank-sync captures. It links one account, so money
moved in from another of your own accounts arrives as plain income -- and
logging the other side as a fresh transfer counted the linked side twice,
while logging it as an expense counted it as spending.
"""
from __future__ import annotations

import pytest

from helpers import add_transaction, cash_balance_of, days_ago, make_account, make_portfolio, ok, set_balance

pytestmark = pytest.mark.integration


@pytest.fixture
async def ctx(api, feed):
    feed.set_fx("EUR", "USD", live=1.2, historical=1.1)
    p = await make_portfolio(api)
    revolut = await make_account(api, p["id"], name="Revolut")
    fineco = await make_account(api, p["id"], name="Fineco")
    await set_balance(api, revolut["id"], 100, on=days_ago(30))
    await set_balance(api, fineco["id"], 1000, on=days_ago(30))
    cat = await ok(await api.post("/expense-categories", json={"name": "Spesa"}))
    return {"p": p["id"], "revolut": revolut["id"], "fineco": fineco["id"], "cat": cat["id"]}


async def summary(api):
    return await ok(await api.get("/expenses/summary", params={"from_date": days_ago(60), "to_date": days_ago(0)}))


# ------------------------------------------------------------ uncategorized
async def test_the_uncategorized_filter_leaves_out_transfers_refunds_and_categorized(api, ctx):
    bare = await add_transaction(api, ctx["revolut"], "EXPENSE", 5, on=days_ago(3))
    await add_transaction(api, ctx["revolut"], "EXPENSE", 6, on=days_ago(3), category_id=ctx["cat"])
    expense = await add_transaction(api, ctx["revolut"], "EXPENSE", 7, on=days_ago(3), category_id=ctx["cat"])
    await add_transaction(api, ctx["revolut"], "INCOME", 2, on=days_ago(2), refund_of_id=expense["id"])
    await ok(await api.post("/transfers", json={"from_account_id": ctx["fineco"], "to_account_id": ctx["revolut"],
                                                "entry_date": days_ago(2), "amount": 50}))

    rows = await ok(await api.get(f"/cash-accounts/{ctx['revolut']}/transactions", params={"uncategorized": True}))
    assert [r["id"] for r in rows] == [bare["id"]]
    flat = await ok(await api.get("/transactions", params={"portfolio_id": ctx["p"], "uncategorized": True}))
    assert [r["id"] for r in flat] == [bare["id"]]


async def test_without_the_filter_everything_is_listed_as_before(api, ctx):
    await add_transaction(api, ctx["revolut"], "EXPENSE", 5, on=days_ago(3))
    await add_transaction(api, ctx["revolut"], "EXPENSE", 6, on=days_ago(3), category_id=ctx["cat"])
    assert len(await ok(await api.get(f"/cash-accounts/{ctx['revolut']}/transactions"))) == 2


# ------------------------------------------------------------- bulk categorize
async def test_bulk_categorize_sets_and_clears(api, ctx):
    a = await add_transaction(api, ctx["revolut"], "EXPENSE", 5, on=days_ago(3))
    b = await add_transaction(api, ctx["revolut"], "EXPENSE", 6, on=days_ago(2))
    res = await ok(await api.post("/cash-transactions/bulk-categorize",
                                  json={"transaction_ids": [a["id"], b["id"], a["id"]], "category_id": ctx["cat"]}))
    assert res["updated"] == 2
    for t in (a, b):
        assert (await ok(await api.get(f"/cash-transactions/{t['id']}")))["category_id"] == ctx["cat"]
    res = await ok(await api.post("/cash-transactions/bulk-categorize",
                                  json={"transaction_ids": [a["id"]], "category_id": None}))
    assert (await ok(await api.get(f"/cash-transactions/{a['id']}")))["category_id"] is None


async def test_bulk_categorize_is_all_or_nothing(api, ctx):
    a = await add_transaction(api, ctx["revolut"], "EXPENSE", 5, on=days_ago(3))
    leg = (await ok(await api.post("/transfers", json={"from_account_id": ctx["fineco"], "to_account_id": ctx["revolut"],
                                                       "entry_date": days_ago(2), "amount": 50})))["to_leg"]
    await ok(await api.post("/cash-transactions/bulk-categorize",
                            json={"transaction_ids": [a["id"], leg["id"]], "category_id": ctx["cat"]}), 400)
    await ok(await api.post("/cash-transactions/bulk-categorize",
                            json={"transaction_ids": [a["id"], "gone"], "category_id": ctx["cat"]}), 404)
    await ok(await api.post("/cash-transactions/bulk-categorize",
                            json={"transaction_ids": [a["id"]], "category_id": "no-such-category"}), 404)
    await ok(await api.post("/cash-transactions/bulk-categorize", json={"transaction_ids": [], "category_id": None}), 422)
    assert (await ok(await api.get(f"/cash-transactions/{a['id']}")))["category_id"] is None


# ------------------------------------------------------- convert to transfer
async def test_an_income_from_another_own_account_becomes_a_transfer(api, ctx):
    """The bank-synced top-up: +500 on Revolut, nothing yet on Fineco."""
    topup = await add_transaction(api, ctx["revolut"], "INCOME", 500, on=days_ago(4), counterparty="BELLUCCI FILIPPO",
                                  note="soldi", category_id=ctx["cat"])
    before = await summary(api)
    assert before["total_income"] == 500

    out = await ok(await api.post(f"/cash-transactions/{topup['id']}/convert-to-transfer",
                                  json={"other_account_id": ctx["fineco"]}))
    assert out["to_leg"]["id"] == topup["id"]
    assert out["from_leg"]["account_id"] == ctx["fineco"] and out["from_leg"]["direction"] == "EXPENSE"
    assert out["from_leg"]["amount"] == 500 and out["from_leg"]["entry_date"] == days_ago(4)
    assert out["to_leg"]["transfer_id"] == out["from_leg"]["transfer_id"] == out["transfer_id"]
    assert out["to_leg"]["category_id"] is None and out["to_leg"]["counterparty"] == "BELLUCCI FILIPPO"

    assert await cash_balance_of(api, ctx["p"], ctx["revolut"]) == 600.0, "Revolut counted once, not twice"
    assert await cash_balance_of(api, ctx["p"], ctx["fineco"]) == 500.0
    after = await summary(api)
    assert after["total_income"] == 0 and after["total_expense"] == 0, "no longer income, nor spending"


async def test_an_expense_to_another_own_account_becomes_a_transfer(api, ctx):
    out_txn = await add_transaction(api, ctx["revolut"], "EXPENSE", 30, on=days_ago(2))
    out = await ok(await api.post(f"/cash-transactions/{out_txn['id']}/convert-to-transfer",
                                  json={"other_account_id": ctx["fineco"]}))
    assert out["from_leg"]["id"] == out_txn["id"]
    assert out["to_leg"]["account_id"] == ctx["fineco"] and out["to_leg"]["direction"] == "INCOME"
    assert await cash_balance_of(api, ctx["p"], ctx["fineco"]) == 1030.0


async def test_the_other_leg_is_converted_into_its_accounts_currency(api, ctx):
    usd = await make_account(api, ctx["p"], name="USD wallet", currency="USD")
    txn = await add_transaction(api, ctx["revolut"], "EXPENSE", 100, on=days_ago(5))
    out = await ok(await api.post(f"/cash-transactions/{txn['id']}/convert-to-transfer",
                                  json={"other_account_id": usd["id"]}))
    assert out["to_leg"]["amount"] == pytest.approx(110.0), "a past date uses that day's rate"


async def test_a_converted_transfer_deletes_as_a_pair(api, ctx):
    topup = await add_transaction(api, ctx["revolut"], "INCOME", 500, on=days_ago(4))
    out = await ok(await api.post(f"/cash-transactions/{topup['id']}/convert-to-transfer",
                                  json={"other_account_id": ctx["fineco"]}))
    await ok(await api.delete(f"/cash-transactions/{out['from_leg']['id']}"), 204)
    assert await ok(await api.get(f"/cash-accounts/{ctx['revolut']}/transactions")) == []


@pytest.mark.parametrize("case", ["already_transfer", "refund", "refunded", "same_account", "voucher",
                                  "archived", "missing_account", "missing_txn"])
async def test_what_cannot_become_a_transfer(api, ctx, case):
    txn = await add_transaction(api, ctx["revolut"], "EXPENSE", 40, on=days_ago(3))
    target, txn_id, expected = ctx["fineco"], txn["id"], 400
    if case == "already_transfer":
        await ok(await api.post(f"/cash-transactions/{txn_id}/convert-to-transfer", json={"other_account_id": target}))
    elif case == "refund":
        txn_id = (await add_transaction(api, ctx["revolut"], "INCOME", 10, on=days_ago(2), refund_of_id=txn["id"]))["id"]
    elif case == "refunded":
        await add_transaction(api, ctx["revolut"], "INCOME", 10, on=days_ago(2), refund_of_id=txn["id"])
    elif case == "same_account":
        target = ctx["revolut"]
    elif case == "voucher":
        target = (await make_account(api, ctx["p"], name="Buoni", kind="VOUCHER", unit_value=8))["id"]
    elif case == "archived":
        await ok(await api.delete(f"/cash-accounts/{ctx['fineco']}"), 204)
    elif case == "missing_account":
        target, expected = "no-such-account", 404
    elif case == "missing_txn":
        txn_id, expected = "no-such-txn", 404
    await ok(await api.post(f"/cash-transactions/{txn_id}/convert-to-transfer", json={"other_account_id": target}),
             expected)
    # Nothing half-done: the original is still the only one of its kind on Revolut, untouched.
    rows = await ok(await api.get(f"/cash-accounts/{ctx['fineco']}/transactions")) if case != "archived" else []
    if case not in ("already_transfer",):
        assert all(r["transfer_id"] is None for r in rows)
