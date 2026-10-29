"""
Each portfolio sees only its own data.

Every page of the app shows the one portfolio picked at the top. The symptom
this guards against: with a second portfolio created, the summary, the
budgets, the snapshots and every expense report added the two together --
a budget counting another portfolio's spending, a merchant rule written for
one portfolio categorizing the other's transactions.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from helpers import add_holding, add_transaction, days_ago, make_account, make_asset, make_portfolio, ok, set_balance

pytestmark = pytest.mark.integration


@pytest.fixture
async def two(api, feed):
    """Two portfolios, each with an account and a "Spesa" category."""
    out = {}
    for key in ("a", "b"):
        p = await make_portfolio(api, name=f"Portfolio {key}")
        acc = await make_account(api, p["id"])
        await set_balance(api, acc["id"], 1000, on=days_ago(60))
        cat = await ok(await api.post("/expense-categories", json={"portfolio_id": p["id"], "name": "Spesa"}))
        out[key] = {"p": p["id"], "acc": acc["id"], "cat": cat["id"]}
    return out


# ---------------------------------------------------------------- categories
async def test_each_portfolio_lists_only_its_own_categories(api, two):
    for key in ("a", "b"):
        listed = await ok(await api.get("/expense-categories", params={"portfolio_id": two[key]["p"]}))
        assert [c["id"] for c in listed] == [two[key]["cat"]]
        assert listed[0]["portfolio_id"] == two[key]["p"]


async def test_another_portfolio_s_category_is_refused_everywhere(api, two):
    """Budgets and reports filter by portfolio; a transaction carrying a
    category of another portfolio would be missing from both."""
    a, b = two["a"], two["b"]
    refused = await api.post(f"/cash-accounts/{a['acc']}/transactions", json={
        "entry_date": days_ago(1), "direction": "EXPENSE", "amount": 5, "category_id": b["cat"]})
    assert refused.status_code == 400 and "another portfolio" in refused.json()["detail"]

    txn = await add_transaction(api, a["acc"], "EXPENSE", 5, on=days_ago(1))
    await ok(await api.patch(f"/cash-transactions/{txn['id']}", json={"category_id": b["cat"]}), 400)
    await ok(await api.post("/cash-transactions/bulk-categorize",
                            json={"transaction_ids": [txn["id"]], "category_id": b["cat"]}), 400)
    await ok(await api.post("/merchant-rules", json={"portfolio_id": a["p"], "pattern": "Esselunga",
                                                     "category_id": b["cat"]}), 400)


# ---------------------------------------------------------------- merchants
async def test_a_merchant_rule_only_categorizes_its_own_portfolio(api, two):
    a, b = two["a"], two["b"]
    await ok(await api.post("/merchant-rules", json={"portfolio_id": a["p"], "pattern": "Esselunga",
                                                     "category_id": a["cat"]}))
    in_a = await add_transaction(api, a["acc"], "EXPENSE", 10, on=days_ago(1), counterparty="Esselunga")
    in_b = await add_transaction(api, b["acc"], "EXPENSE", 10, on=days_ago(1), counterparty="Esselunga")
    assert in_a["category_id"] == a["cat"]
    assert in_b["category_id"] is None, "portfolio a's rule must not decide portfolio b's merchant"

    merchants_b = await ok(await api.get("/merchants", params={"portfolio_id": b["p"]}))
    assert [(m["name"], m["status"], m["expense_count"]) for m in merchants_b] == [("Esselunga", "UNMAPPED", 1)]
    assert await ok(await api.get("/merchant-rules", params={"portfolio_id": b["p"]})) == []


async def test_two_portfolios_can_each_have_a_rule_for_the_same_merchant(api, two):
    for key in ("a", "b"):
        await ok(await api.post("/merchant-rules", json={"portfolio_id": two[key]["p"], "pattern": "Esselunga",
                                                         "category_id": two[key]["cat"]}))
    await ok(await api.post("/merchant-rules", json={"portfolio_id": two["a"]["p"], "pattern": "esselunga",
                                                     "category_id": two["a"]["cat"]}), 409)


async def test_applying_a_rule_to_the_past_leaves_other_portfolios_alone(api, two):
    a, b = two["a"], two["b"]
    in_b = await add_transaction(api, b["acc"], "EXPENSE", 10, on=days_ago(2), counterparty="Deliveroo")
    saved = await ok(await api.post("/merchant-rules", json={"portfolio_id": a["p"], "pattern": "Deliveroo",
                                                             "category_id": a["cat"]}))
    assert saved["applied"] == 0
    assert (await ok(await api.get(f"/cash-transactions/{in_b['id']}")))["category_id"] is None


# ---------------------------------------------------------------- budgets and reports
async def test_a_budget_counts_only_its_portfolio_s_spending(api, two):
    a, b = two["a"], two["b"]
    budget = await ok(await api.post("/budgets", json={"category_id": a["cat"], "amount": 100}))
    today = date.today().isoformat()
    await add_transaction(api, a["acc"], "EXPENSE", 30, on=today, category_id=a["cat"])
    await add_transaction(api, b["acc"], "EXPENSE", 500, on=today, category_id=b["cat"])

    progress_a = await ok(await api.get("/budgets/progress", params={"portfolio_id": a["p"]}))
    assert [(i["budget_id"], i["spent"]) for i in progress_a["items"]] == [(budget["id"], 30.0)]
    progress_b = await ok(await api.get("/budgets/progress", params={"portfolio_id": b["p"]}))
    assert progress_b["items"] == [], "portfolio b has no budget of its own"
    assert await ok(await api.get("/budgets", params={"portfolio_id": b["p"]})) == []


async def test_the_reports_count_only_the_selected_portfolio(api, two):
    a, b = two["a"], two["b"]
    for days in (65, 35, 5):
        await add_transaction(api, a["acc"], "EXPENSE", 9.99, on=days_ago(days), counterparty="Netflix")
        await add_transaction(api, b["acc"], "EXPENSE", 400, on=days_ago(days), counterparty="Rent")

    summary = await ok(await api.get("/expenses/summary", params={
        "portfolio_id": a["p"], "from_date": days_ago(90), "to_date": days_ago(0)}))
    assert summary["total_expense"] == pytest.approx(3 * 9.99)
    monthly = await ok(await api.get("/expenses/monthly", params={"portfolio_id": a["p"], "months": 4}))
    assert sum(m["expense"] for m in monthly) == pytest.approx(3 * 9.99)
    recurring = await ok(await api.get("/recurring", params={"portfolio_id": a["p"]}))
    assert [i["name"] for i in recurring["items"]] == ["Netflix"]


async def test_a_report_without_a_portfolio_is_refused(api, two):
    """There is no all-portfolios sum any more: asking for one is a mistake."""
    for path, params in (("/expenses/summary", {"from_date": days_ago(9), "to_date": days_ago(0)}),
                         ("/expenses/monthly", {}), ("/recurring", {}), ("/budgets/progress", {}),
                         ("/budgets", {}), ("/expense-categories", {}), ("/merchants", {}),
                         ("/merchant-rules", {})):
        assert (await api.get(path, params=params)).status_code == 422, path


# ---------------------------------------------------------------- net worth snapshots
async def test_a_snapshot_freezes_one_portfolio_in_its_base_currency(api, feed):
    eur = await make_portfolio(api, name="EUR book", currency="EUR")
    usd = await make_portfolio(api, name="USD book", currency="USD")
    for p, amount in ((eur, 1000), (usd, 300)):
        acc = await make_account(api, p["id"], currency=p["base_currency"])
        await set_balance(api, acc["id"], amount)

    taken = await ok(await api.post(f"/portfolios/{usd['id']}/networth-snapshots"))
    assert (taken["portfolio_id"], taken["currency"], taken["net_worth"]) == (usd["id"], "USD", 300.0)
    assert await ok(await api.get(f"/portfolios/{eur['id']}/networth-snapshots")) == []

    again = await ok(await api.post(f"/portfolios/{usd['id']}/networth-snapshots"))
    assert again["id"] == taken["id"], "the same day's snapshot is overwritten, not duplicated"


async def test_month_end_catch_up_runs_per_active_portfolio(api, feed, core_modules, db_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    scheduler = core_modules["scheduler"]
    monkeypatch.setattr(scheduler, "SessionLocal", sessionmaker(bind=db_engine))
    last_month_end = date.today().replace(day=1) - timedelta(days=1)

    active = await make_portfolio(api, name="Active")
    archived = await make_portfolio(api, name="Archived")
    for p, amount in ((active, 1000), (archived, 500)):
        acc = await make_account(api, p["id"])
        await set_balance(api, acc["id"], amount, on=days_ago(70))
    await ok(await api.patch(f"/portfolios/{archived['id']}", json={"archived": True}))

    await scheduler.catch_up_monthly_snapshots()
    rows = {s["snapshot_date"]: s for s in await ok(await api.get(f"/portfolios/{active['id']}/networth-snapshots"))}
    assert rows[last_month_end.isoformat()]["net_worth"] == 1000.0, "the other portfolio's 500 is not in it"
    assert await ok(await api.get(f"/portfolios/{archived['id']}/networth-snapshots")) == []


# ---------------------------------------------------------------- asset catalogue
async def test_the_catalogue_shows_a_portfolio_its_assets_and_the_unheld_ones(api, two):
    mine = await make_asset(api, name="Mine", ticker="MINE")
    theirs = await make_asset(api, name="Theirs", ticker="THEIRS")
    shared = await make_asset(api, name="Shared", ticker="SHARED")
    free = await make_asset(api, name="Free", ticker="FREE")
    await add_holding(api, two["a"]["p"], mine["id"], 1, manual_price=1)
    await add_holding(api, two["b"]["p"], theirs["id"], 1, manual_price=1)
    for key in ("a", "b"):
        await add_holding(api, two[key]["p"], shared["id"], 1, manual_price=1)

    seen = await ok(await api.get("/assets", params={"portfolio_id": two["a"]["p"]}))
    assert sorted(a["name"] for a in seen) == ["Free", "Mine", "Shared"]
    assert {a["id"] for a in await ok(await api.get("/assets"))} >= {mine["id"], theirs["id"], free["id"]}


async def test_an_asset_held_by_two_portfolios_cannot_be_deleted_from_one(api, two):
    """Deleting it removes every holding of it: from one portfolio's
    catalogue that would empty the other portfolio's position."""
    shared = await make_asset(api, name="Shared", ticker="SHARED")
    for key in ("a", "b"):
        await add_holding(api, two[key]["p"], shared["id"], 1, manual_price=1)
    await ok(await api.delete(f"/assets/{shared['id']}"), 409)
    assert len(await ok(await api.get(f"/portfolios/{two['b']['p']}/holdings"))) == 1
