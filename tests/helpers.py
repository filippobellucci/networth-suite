"""
Builders for integration tests.

Every test sets up its scenario through the real API rather than by inserting
rows, so a change to validation or to an endpoint's shape is felt by the
tests that depend on it instead of being quietly bypassed.
"""
from __future__ import annotations

from datetime import date, timedelta

TODAY = date.today()


def days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def today_iso() -> str:
    return TODAY.isoformat()


async def ok(response, *expected: int):
    """Asserts the status and returns the decoded body, showing the server's
    own message when it disagrees -- a bare assert on the status code turns a
    clear 400 into 'assert 400 == 200'."""
    allowed = expected or (200,)
    assert response.status_code in allowed, (
        f"{response.request.method} {response.request.url.path} "
        f"-> {response.status_code}: {response.text[:400]}"
    )
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


async def make_portfolio(api, name="Test portfolio", currency="EUR", **kw):
    return await ok(await api.post("/portfolios",
                                   json={"name": name, "base_currency": currency, **kw}))


async def make_asset(api, name="Test ETF", ticker="TESTEUR", currency="EUR", **kw):
    body = {"name": name, "asset_class": kw.pop("asset_class", "ETF"), "currency": currency, **kw}
    if ticker is not None:
        body["ticker"] = ticker
    return await ok(await api.post("/assets", json=body))


async def add_holding(api, portfolio_id, asset_id, quantity, on=None, manual_price=None):
    body = {"asset_id": asset_id, "entry_date": on or today_iso(), "quantity": quantity}
    if manual_price is not None:
        body["manual_price"] = manual_price
    return await ok(await api.post(f"/portfolios/{portfolio_id}/holdings", json=body))


async def make_account(api, portfolio_id, name="Bank", currency="EUR", **kw):
    return await ok(await api.post(f"/portfolios/{portfolio_id}/cash-accounts",
                                   json={"name": name, "currency": currency, **kw}))


async def set_balance(api, account_id, amount, on=None):
    return await ok(await api.post(f"/cash-accounts/{account_id}/balances",
                                   json={"entry_date": on or today_iso(), "balance": amount}))


async def add_transaction(api, account_id, direction, amount=None, on=None, **kw):
    body = {"entry_date": on or today_iso(), "direction": direction, **kw}
    if amount is not None:
        body["amount"] = amount
    return await ok(await api.post(f"/cash-accounts/{account_id}/transactions", json=body))


async def snapshot(api, portfolio_id, as_of=None):
    params = {"as_of": as_of} if as_of else None
    return await ok(await api.get(f"/portfolios/{portfolio_id}/snapshot", params=params))


async def history_points(api, portfolio_id):
    body = await ok(await api.get(f"/portfolios/{portfolio_id}/history"))
    return {p["date"]: p["net_worth_base_ccy"] for p in body["points"]}


async def cash_balance_of(api, portfolio_id, account_id, as_of=None):
    snap = await snapshot(api, portfolio_id, as_of)
    for position in snap["cash_positions"]:
        if position["account_id"] == account_id:
            return position["balance"]
    return None
