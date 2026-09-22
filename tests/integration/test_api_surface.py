"""
The shape of the API itself: pagination, what a refusal looks like, and what
happens to input nobody expected.

The theme running through this file is that a bad request must be a 4xx. A
500 is the service saying it broke, which sends whoever is debugging it
looking in the wrong place -- and several of these used to be exactly that.
"""
from __future__ import annotations

import pytest

from helpers import (add_transaction, days_ago, make_account, make_asset, make_portfolio,
                     ok, set_balance, today_iso)

pytestmark = pytest.mark.integration


@pytest.fixture
async def ledger(api, feed):
    """A portfolio with an account and five dated transactions."""
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(20))
    for i in range(5):
        await add_transaction(api, acc["id"], "EXPENSE", 10 + i, on=days_ago(10 - i))
    return {"portfolio": p, "account": acc}


# ----------------------------------------------------------------- pagination
async def test_omitting_a_limit_returns_everything(api, ledger):
    rows = await ok(await api.get(f"/cash-accounts/{ledger['account']['id']}/transactions"))
    assert len(rows) == 5


async def test_a_limit_of_zero_returns_nothing(api, ledger):
    """Not "everything": a falsy-check on the limit would make 0 mean "no
    limit", which is the opposite of what the caller asked for."""
    rows = await ok(await api.get(f"/cash-accounts/{ledger['account']['id']}/transactions",
                                  params={"limit": 0}))
    assert rows == []


async def test_pages_do_not_overlap_or_skip(api, ledger):
    path = f"/cash-accounts/{ledger['account']['id']}/transactions"
    first = await ok(await api.get(path, params={"limit": 2, "offset": 0}))
    second = await ok(await api.get(path, params={"limit": 2, "offset": 2}))
    third = await ok(await api.get(path, params={"limit": 2, "offset": 4}))
    ids = [r["id"] for r in first + second + third]
    assert len(ids) == 5
    assert len(set(ids)) == 5, "a row appeared on two pages"
    everything = await ok(await api.get(path))
    assert ids == [r["id"] for r in everything], "paging changed the order"


async def test_an_offset_past_the_end_is_empty(api, ledger):
    rows = await ok(await api.get(f"/cash-accounts/{ledger['account']['id']}/transactions",
                                  params={"offset": 999}))
    assert rows == []


@pytest.mark.parametrize("params", [
    {"limit": -1}, {"offset": -1}, {"limit": -5, "offset": -5}, {"offset": -1000000},
    {"limit": 10 ** 12}, {"offset": 10 ** 12},
])
async def test_nonsensical_paging_never_fails(api, ledger, params):
    response = await api.get(f"/cash-accounts/{ledger['account']['id']}/transactions",
                             params=params)
    assert response.status_code < 500, response.text[:200]


@pytest.mark.parametrize("params", [{"limit": "abc"}, {"offset": "abc"}, {"limit": 1.5}])
async def test_a_non_numeric_page_is_a_422(api, ledger, params):
    response = await api.get(f"/cash-accounts/{ledger['account']['id']}/transactions",
                             params=params)
    assert response.status_code == 422


@pytest.mark.parametrize("path", [
    "/assets", "/transactions", "/networth-snapshots",
])
async def test_every_paginated_list_accepts_the_same_parameters(api, ledger, path):
    await ok(await api.get(path, params={"limit": 2, "offset": 1}))


# ------------------------------------------------------- what a refusal says
async def test_a_validation_error_names_the_field(api, feed):
    """The frontend turns this into the sentence the user reads, so the
    structure matters: a list of entries, each with a `loc` and a `msg`."""
    response = await api.post("/assets", json={"name": "A", "ticker": "T" * 25,
                                               "asset_class": "ETF", "currency": "EUR"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    assert detail[0]["loc"][-1] == "ticker"
    assert "msg" in detail[0]


async def test_a_deliberate_refusal_is_a_sentence(api, feed):
    """Refusals the code raises itself carry a string, which is passed
    through to the user unchanged."""
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"], kind="VOUCHER")
    response = await api.post(f"/cash-accounts/{acc['id']}/transactions", json={
        "entry_date": today_iso(), "direction": "EXPENSE", "quantity": 1})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


async def test_refusing_a_non_finite_value_does_not_itself_break(api, feed):
    """A validation error echoes the offending input back, so refusing
    Infinity produced a 422 body that could not be JSON-encoded -- and the
    422 became a 500 while it was being rendered."""
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    response = await api.post(
        f"/cash-accounts/{acc['id']}/transactions",
        content=b'{"entry_date":"%s","direction":"EXPENSE","amount":Infinity}' % today_iso().encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list)


# ------------------------------------------------------------- query parameters
@pytest.mark.parametrize("params", [
    {"as_of": "not-a-date"}, {"as_of": "2026-13-45"}, {"as_of": ""},
])
async def test_a_malformed_date_parameter_is_a_422(api, feed, params):
    p = await make_portfolio(api)
    response = await api.get(f"/portfolios/{p['id']}/snapshot", params=params)
    assert response.status_code == 422


@pytest.mark.parametrize("params", [
    {"as_of": "0001-01-01"}, {"as_of": "9999-12-31"},
])
async def test_an_extreme_but_valid_date_is_answered(api, feed, params):
    p = await make_portfolio(api)
    await ok(await api.get(f"/portfolios/{p['id']}/snapshot", params=params))


@pytest.mark.parametrize("search", ["%", "_", "'", "x" * 3000, "%%", "\\"])
async def test_search_never_fails_on_odd_input(api, feed, search):
    await make_asset(api, name="Findable")
    response = await api.get("/assets", params={"search": search})
    assert response.status_code < 500, response.text[:200]


async def test_search_finds_by_name_and_ticker(api, feed):
    await make_asset(api, name="World Equity", ticker="TESTEUR")
    await make_asset(api, name="Something else", ticker="OTHER")
    by_name = await ok(await api.get("/assets", params={"search": "World"}))
    by_ticker = await ok(await api.get("/assets", params={"search": "TESTEUR"}))
    assert [a["name"] for a in by_name] == ["World Equity"]
    assert [a["name"] for a in by_ticker] == ["World Equity"]


async def test_an_inverted_date_range_is_answered_not_refused(api, feed):
    p = await make_portfolio(api)
    await ok(await api.get("/expenses/summary", params={
        "from_date": today_iso(), "to_date": days_ago(30),
        "portfolio_id": p["id"], "currency": "EUR"}))


async def test_an_unknown_id_in_a_filter_is_simply_empty(api, feed):
    rows = await ok(await api.get("/transactions", params={"portfolio_id": "../../etc/passwd"}))
    assert rows == []


# ---------------------------------------------------------------- 404 handling
@pytest.mark.parametrize("method,path", [
    ("get", "/portfolios/nope/snapshot"),
    ("get", "/assets/nope"),
    ("patch", "/portfolios/nope"),
    ("patch", "/assets/nope"),
    ("delete", "/assets/nope"),
    ("delete", "/cash-accounts/nope"),
    ("delete", "/cash-transactions/nope"),
    ("delete", "/expense-categories/nope"),
    ("delete", "/networth-snapshots/nope"),
])
async def test_an_unknown_id_is_a_404(api, feed, method, path):
    call = getattr(api, method)
    response = await call(path, **({"json": {}} if method == "patch" else {}))
    assert response.status_code == 404, response.text[:200]


# ------------------------------------------------------------------- updating
async def test_a_ticker_can_be_cleared(api, feed):
    """Sending no `ticker` key means "leave it alone", so clearing it needs an
    explicit null -- and a ticker saved with a typo prices the holding off the
    wrong instrument until it can be corrected."""
    asset = await make_asset(api, ticker="TESTEUR", isin="IE00B4L5Y983")
    updated = await ok(await api.patch(f"/assets/{asset['id']}",
                                       json={"ticker": None, "isin": None}))
    assert updated["ticker"] is None and updated["isin"] is None


async def test_omitting_a_field_leaves_it_alone(api, feed):
    asset = await make_asset(api, name="Original", ticker="TESTEUR")
    updated = await ok(await api.patch(f"/assets/{asset['id']}", json={"name": "Renamed"}))
    assert updated["name"] == "Renamed"
    assert updated["ticker"] == "TESTEUR"


async def test_setting_a_required_field_to_null_is_a_422_not_a_500(api, feed):
    p = await make_portfolio(api)
    for field in ("name", "base_currency", "archived"):
        response = await api.patch(f"/portfolios/{p['id']}", json={field: None})
        assert response.status_code == 422, f"{field} -> {response.status_code}"
