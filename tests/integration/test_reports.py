"""
The reports built on the income/expense ledger: income by category, the
monthly breakdown with its savings rate, budgets, recurring payments, and
searching/exporting transactions.

All of them must count money exactly like /expenses/summary -- transfers out,
refunds netted, amounts converted at their own day's rate -- so most tests
here mix in a transfer or a refund and check it's handled the same way.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pytest

from helpers import add_transaction, days_ago, make_account, make_portfolio, ok, set_balance

pytestmark = pytest.mark.integration

TODAY = date.today()


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def months_back(n: int) -> date:
    y, m = divmod(TODAY.month - 1 - n, 12)
    return date(TODAY.year + y, m + 1, 1)


@pytest.fixture
async def ctx(api, feed):
    feed.set_fx("USD", "EUR", live=0.5, historical=0.5)
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"], name="Revolut")
    other = await make_account(api, p["id"], name="Fineco")
    usd = await make_account(api, p["id"], name="USD", currency="USD")
    for a in (acc, other, usd):
        await set_balance(api, a["id"], 1000, on=days_ago(800))
    cats = {}
    for name in ("Spesa", "Svago", "Stipendio", "Abbonamenti"):
        cats[name] = (await ok(await api.post("/expense-categories", json={"name": name})))["id"]
    return {"p": p["id"], "acc": acc["id"], "other": other["id"], "usd": usd["id"], "cats": cats}


async def tx(api, ctx, direction, amount, on, account="acc", **kw):
    return await add_transaction(api, ctx[account], direction, amount, on=on, **kw)


# ------------------------------------------------------------ summary
async def test_income_is_broken_down_by_category_too(api, ctx):
    on = TODAY.isoformat()
    await tx(api, ctx, "INCOME", 1500, on, category_id=ctx["cats"]["Stipendio"])
    await tx(api, ctx, "INCOME", 40, on)
    await tx(api, ctx, "EXPENSE", 30, on, category_id=ctx["cats"]["Spesa"])
    s = await ok(await api.get("/expenses/summary", params={"from_date": on, "to_date": on}))
    assert s["income_by_category"] == [
        {"category_id": ctx["cats"]["Stipendio"], "category_name": "Stipendio", "total": 1500},
        {"category_id": None, "category_name": "Uncategorized", "total": 40},
    ]
    assert [c["category_name"] for c in s["by_category"]] == ["Spesa"]
    assert s["total_income"] == 1540 and s["total_expense"] == 30


# ------------------------------------------------------------ monthly
async def test_monthly_breakdown_with_savings_rate(api, ctx):
    this_month, last_month = TODAY.replace(day=1), months_back(1)
    await tx(api, ctx, "INCOME", 2000, last_month.isoformat())
    await tx(api, ctx, "EXPENSE", 500, last_month.isoformat())
    await tx(api, ctx, "EXPENSE", 100, this_month.isoformat())
    # Neither of these is income or spending:
    await ok(await api.post("/transfers", json={"from_account_id": ctx["acc"], "to_account_id": ctx["other"],
                                                "entry_date": this_month.isoformat(), "amount": 300}))
    exp = await tx(api, ctx, "EXPENSE", 80, this_month.isoformat())
    await tx(api, ctx, "INCOME", 80, this_month.isoformat(), refund_of_id=exp["id"])

    rows = await ok(await api.get("/expenses/monthly", params={"months": 3}))
    assert [r["month"] for r in rows] == [month_key(months_back(2)), month_key(last_month), month_key(this_month)]
    assert rows[0] == {"month": month_key(months_back(2)), "income": 0, "expense": 0, "net": 0, "savings_rate": None}
    assert rows[1]["income"] == 2000 and rows[1]["expense"] == 500 and rows[1]["savings_rate"] == 75.0
    assert rows[2]["expense"] == 100 and rows[2]["income"] == 0 and rows[2]["savings_rate"] is None


async def test_monthly_converts_other_currencies(api, ctx):
    await tx(api, ctx, "EXPENSE", 100, TODAY.isoformat(), account="usd")
    rows = await ok(await api.get("/expenses/monthly", params={"months": 1}))
    assert rows[0]["expense"] == 50


async def test_monthly_rejects_a_silly_range(api, ctx):
    await ok(await api.get("/expenses/monthly", params={"months": 0}), 422)
    await ok(await api.get("/expenses/monthly", params={"months": 1000}), 422)


# ------------------------------------------------------------ budgets
async def test_budget_progress_this_month(api, ctx):
    spesa, svago = ctx["cats"]["Spesa"], ctx["cats"]["Svago"]
    b1 = await ok(await api.post("/budgets", json={"category_id": spesa, "amount": 200}))
    await ok(await api.post("/budgets", json={"category_id": svago, "amount": 50, "currency": "eur"}))
    first = TODAY.replace(day=1).isoformat()
    await tx(api, ctx, "EXPENSE", 150, first, category_id=spesa)
    await tx(api, ctx, "EXPENSE", 60, first, category_id=svago)
    await tx(api, ctx, "EXPENSE", 999, months_back(1).isoformat(), category_id=spesa)  # last month: not counted

    prog = await ok(await api.get("/budgets/progress"))
    assert prog["month"] == month_key(TODAY)
    assert 0 < prog["elapsed_pct"] <= 100
    by_cat = {i["category_name"]: i for i in prog["items"]}
    assert by_cat["Spesa"] == {"budget_id": b1["id"], "category_id": spesa, "category_name": "Spesa",
                               "currency": "EUR", "budget": 200, "spent": 150, "remaining": 50,
                               "percent": 75.0, "status": "OK"}
    assert by_cat["Svago"]["status"] == "OVER" and by_cat["Svago"]["remaining"] == -10
    assert by_cat["Svago"]["currency"] == "EUR", "a lowercase currency code is normalized"


async def test_budget_near_its_limit(api, ctx):
    spesa = ctx["cats"]["Spesa"]
    await ok(await api.post("/budgets", json={"category_id": spesa, "amount": 100}))
    await tx(api, ctx, "EXPENSE", 92, TODAY.replace(day=1).isoformat(), category_id=spesa)
    (item,) = (await ok(await api.get("/budgets/progress")))["items"]
    assert item["status"] == "NEAR"


async def test_a_past_month_is_fully_elapsed_and_counts_refunds(api, ctx):
    spesa = ctx["cats"]["Spesa"]
    await ok(await api.post("/budgets", json={"category_id": spesa, "amount": 100}))
    last = months_back(1)
    exp = await tx(api, ctx, "EXPENSE", 120, last.isoformat(), category_id=spesa)
    await tx(api, ctx, "INCOME", 50, last.isoformat(), refund_of_id=exp["id"])
    prog = await ok(await api.get("/budgets/progress", params={"month": month_key(last)}))
    assert prog["elapsed_pct"] == 100.0
    assert prog["items"][0]["spent"] == 70 and prog["items"][0]["status"] == "OK"


async def test_budget_crud_and_validation(api, ctx):
    spesa = ctx["cats"]["Spesa"]
    b = await ok(await api.post("/budgets", json={"category_id": spesa, "amount": 100}))
    await ok(await api.post("/budgets", json={"category_id": spesa, "amount": 5}), 409)
    await ok(await api.post("/budgets", json={"category_id": "nope", "amount": 5}), 404)
    await ok(await api.post("/budgets", json={"category_id": ctx["cats"]["Svago"], "amount": 0}), 422)
    upd = await ok(await api.patch(f"/budgets/{b['id']}", json={"amount": 120.456}))
    assert upd["amount"] == pytest.approx(120.456, abs=0.001)
    await ok(await api.patch(f"/budgets/{b['id']}", json={"amount": None}), 422)
    await ok(await api.get("/budgets/progress", params={"month": "2026-13"}), 422)
    await ok(await api.delete(f"/budgets/{b['id']}"), 204)
    await ok(await api.delete(f"/budgets/{b['id']}"), 404)


async def test_deleting_a_category_deletes_its_budget(api, ctx):
    spesa = ctx["cats"]["Spesa"]
    await ok(await api.post("/budgets", json={"category_id": spesa, "amount": 100}))
    await ok(await api.delete(f"/expense-categories/{spesa}"), 204)
    assert await ok(await api.get("/budgets")) == []
    assert (await ok(await api.get("/budgets/progress")))["items"] == []


# ------------------------------------------------------------ recurring
async def test_a_monthly_subscription_is_detected_with_its_price_change(api, ctx):
    for i, amount in enumerate([12.99, 12.99, 12.99, 13.99]):
        on = (TODAY - timedelta(days=30 * (3 - i) + 2)).isoformat()
        await tx(api, ctx, "EXPENSE", amount, on, counterparty="NETFLIX.COM", category_id=ctx["cats"]["Abbonamenti"])
    # Weekly groceries: regular in time, not in amount -- not a subscription.
    for i, amount in enumerate([35, 80, 12, 64, 50]):
        await tx(api, ctx, "EXPENSE", amount, (TODAY - timedelta(days=7 * i + 1)).isoformat(), counterparty="Unicoop")
    # Random one-offs.
    await tx(api, ctx, "EXPENSE", 20, days_ago(40), counterparty="Deliveroo")
    await tx(api, ctx, "EXPENSE", 25, days_ago(3), counterparty="Deliveroo")

    rep = await ok(await api.get("/recurring"))
    assert [i["name"] for i in rep["items"]] == ["NETFLIX.COM"]
    (sub,) = rep["items"]
    assert sub["cadence"] == "MONTHLY" and sub["occurrences"] == 4 and sub["active"]
    assert sub["last_amount"] == 13.99 and sub["typical_amount"] == 12.99
    assert sub["price_change"]["previous"] == 12.99 and sub["price_change"]["current"] == 13.99
    assert sub["category_id"] == ctx["cats"]["Abbonamenti"]
    assert rep["monthly_total"] == pytest.approx(13.99, abs=0.01)


async def test_a_cancelled_subscription_is_inactive_and_not_in_the_total(api, ctx):
    for i in range(4):
        await tx(api, ctx, "EXPENSE", 9.99, (TODAY - timedelta(days=200 + 30 * i)).isoformat(), counterparty="Spotify")
    rep = await ok(await api.get("/recurring"))
    assert rep["items"][0]["active"] is False and rep["monthly_total"] == 0


async def test_hand_logged_payments_are_grouped_by_note(api, ctx):
    for i in range(3):
        await tx(api, ctx, "EXPENSE", 30, (TODAY - timedelta(days=30 * i + 5)).isoformat(), note="Palestra")
    rep = await ok(await api.get("/recurring"))
    assert [i["name"] for i in rep["items"]] == ["Palestra"]


async def test_transfers_are_never_recurring_payments(api, ctx):
    for i in range(4):
        await ok(await api.post("/transfers", json={
            "from_account_id": ctx["acc"], "to_account_id": ctx["other"],
            "entry_date": (TODAY - timedelta(days=30 * i + 1)).isoformat(), "amount": 200, "note": "risparmio"}))
    assert (await ok(await api.get("/recurring")))["items"] == []


# ------------------------------------------------------------ search
async def test_search_and_filters(api, ctx):
    a = await tx(api, ctx, "EXPENSE", 7.2, days_ago(2), counterparty="Unicoop Firenze", note="spesa",
                 category_id=ctx["cats"]["Spesa"])
    b = await tx(api, ctx, "EXPENSE", 52, days_ago(10), note="Regalo 50% sconto")
    c = await tx(api, ctx, "INCOME", 1500, days_ago(5), counterparty="ACME SPA")

    async def ids(**params):
        rows = await ok(await api.get(f"/cash-accounts/{ctx['acc']}/transactions", params=params))
        return {r["id"] for r in rows}

    assert await ids(q="unicoop") == {a["id"]}, "matches the counterparty, case-insensitively"
    assert await ids(q="REGALO") == {b["id"]}, "and the note"
    assert await ids(q="50%") == {b["id"]}
    assert await ids(q="%") == {b["id"]}, "% is a literal character, not a wildcard"
    assert await ids(q="_") == set()
    assert await ids(min_amount=10, max_amount=100) == {b["id"]}
    assert await ids(direction="INCOME") == {c["id"]}
    assert await ids(from_date=days_ago(6), to_date=days_ago(1)) == {a["id"], c["id"]}
    assert await ids(category_id=ctx["cats"]["Spesa"]) == {a["id"]}
    assert await ids(q="unicoop", direction="INCOME") == set(), "filters combine"
    flat = await ok(await api.get("/transactions", params={"portfolio_id": ctx["p"], "q": "acme"}))
    assert [r["id"] for r in flat] == [c["id"]]


# ------------------------------------------------------------ export
async def test_csv_export_matches_the_filtered_list(api, ctx):
    await tx(api, ctx, "EXPENSE", 7.2, days_ago(2), counterparty="Unicoop", note="spesa, settimanale",
             category_id=ctx["cats"]["Spesa"])
    await tx(api, ctx, "INCOME", 1500, days_ago(5), counterparty="ACME SPA")
    await tx(api, ctx, "EXPENSE", 10, days_ago(3), account="usd")
    await ok(await api.post("/transfers", json={"from_account_id": ctx["acc"], "to_account_id": ctx["other"],
                                                "entry_date": days_ago(1), "amount": 50}))

    r = await api.get("/transactions/export.csv", params={"portfolio_id": ctx["p"]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 5  # 3 + both transfer legs
    unicoop = next(row for row in rows if row["counterparty"] == "Unicoop")
    assert unicoop["amount"] == "-7.20" and unicoop["category"] == "Spesa" and unicoop["type"] == "EXPENSE"
    assert unicoop["note"] == "spesa, settimanale", "a comma inside a field survives"
    assert next(row for row in rows if row["account"] == "USD")["currency"] == "USD"
    assert sorted(row["type"] for row in rows if row["transfer_id"]) == ["TRANSFER", "TRANSFER"]

    only = await api.get("/transactions/export.csv", params={"portfolio_id": ctx["p"], "q": "acme"})
    assert [row["counterparty"] for row in csv.DictReader(io.StringIO(only.content.decode("utf-8-sig")))] == ["ACME SPA"]
