"""
The gateway, with the real services behind it.

Everything here needs separate processes to mean anything: a proxy that does
not proxy, a connection pool that runs out, an auth gate. None of it is
visible when the app is called in-process.
"""
from __future__ import annotations

import concurrent.futures

import httpx
import pytest

pytestmark = [pytest.mark.system, pytest.mark.slow]


# ------------------------------------------------------------------ proxying
def test_a_proxied_call_reaches_the_module(gw):
    assert gw.get("/api/core/portfolios").status_code == 200
    assert gw.get("/api/prices/health").status_code == 200


def test_the_query_string_survives_the_proxy(gw, core_http):
    gw.post("/api/core/assets", json={"name": "Proxy search", "ticker": "TESTEUR",
                                      "asset_class": "ETF", "currency": "EUR"})
    through = gw.get("/api/core/assets", params={"search": "Proxy search"}).json()
    direct = core_http.get("/assets", params={"search": "Proxy search"}).json()
    assert through == direct


def test_every_verb_is_proxied(gw):
    created = gw.post("/api/core/expense-categories", json={"name": "Proxied category"})
    assert created.status_code == 200
    cid = created.json()["id"]
    assert gw.patch(f"/api/core/expense-categories/{cid}", json={"name": "Renamed"}).status_code == 200
    assert gw.get("/api/core/expense-categories").status_code == 200
    assert gw.delete(f"/api/core/expense-categories/{cid}").status_code == 204


def test_an_upstream_status_and_body_pass_through_unchanged(gw):
    missing = gw.get("/api/core/portfolios/nope/snapshot")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Portfolio not found"

    invalid = gw.post("/api/core/portfolios", json={"name": "x", "base_currency": "EURO"})
    assert invalid.status_code == 422
    assert isinstance(invalid.json()["detail"], list), "the validation detail must survive intact"


def test_an_unknown_module_is_a_404(gw):
    assert gw.get("/api/nosuchmodule/anything").status_code == 404


@pytest.mark.parametrize("path,why", [
    ("core/../../etc/passwd", "parent traversal"),
    ("core/..%2f..%2fetc%2fpasswd", "encoded traversal"),
    ("core//127.0.0.1:1/x", "doubled slash"),
    ("core/@127.0.0.1:1/x", "an @ that might read as userinfo"),
    ("core/http://127.0.0.1:1/x", "an absolute url pushed into the path"),
])
def test_the_path_cannot_steer_the_proxy_elsewhere(gw, path, why):
    response = gw.get(f"/api/{path}")
    assert response.status_code in (400, 404), f"{why} -> {response.status_code}"
    assert "root:x:" not in response.text


@pytest.mark.parametrize("encoded", ["x%00y", "x%09y", "x%1fy"])
def test_a_control_character_in_the_path_is_a_400(gw, stack, encoded):
    """httpx refuses to build a URL containing one, and httpx.InvalidURL does
    NOT inherit from httpx.HTTPError -- so the handler meant to turn an
    upstream problem into a 502 never saw it and it escaped as a 500."""
    response = gw.get(f"/api/core/{encoded}")
    assert response.status_code == 400, response.text[:200]
    assert "Traceback" not in stack.gateway_log()


def test_a_valid_non_ascii_path_still_routes(gw):
    assert gw.get("/api/core/%F0%9F%92%B0").status_code == 404, "routed, then simply not found"


# --------------------------------------------------------------- request size
def test_a_huge_proxied_body_is_refused_without_being_buffered(gw):
    """The factsheet upload is the one file that goes through the generic
    proxy. Reading it whole before passing it on meant geo-allocation's own
    cap protected nothing here: a 500MB post took the gateway to 1.5GB of
    resident memory and still ended in the 413 it should have started with."""
    blob = b"x" * (40 * 1024 * 1024)
    response = gw.post("/api/geo/allocation/assets/sizetest/upload",
                       files={"file": ("big.xlsx", blob)}, timeout=180)
    assert response.status_code == 413


def test_an_ordinary_body_is_unaffected(gw):
    response = gw.post("/api/core/portfolios", json={"name": "Small body", "base_currency": "EUR"})
    assert response.status_code == 200


# ------------------------------------------------------------ the dashboard
def test_the_dashboard_returns_everything_the_page_needs(gw):
    gw.post("/api/core/portfolios", json={"name": "Dash", "base_currency": "EUR"})
    body = gw.get("/api/dashboard/summary").json()
    assert set(body) >= {"portfolios", "snapshots", "combined_history", "totals", "base_currency"}
    assert isinstance(body["portfolios"], list) and body["portfolios"]
    assert body["totals"] is not None


def test_the_dashboard_converts_rather_than_adding_currencies_together(gw):
    """Summing the per-portfolio snapshots client-side counted dollars as
    euros and disagreed with the chart directly below."""
    eur = gw.post("/api/core/portfolios", json={"name": "T-EUR", "base_currency": "EUR"}).json()
    usd = gw.post("/api/core/portfolios", json={"name": "T-USD", "base_currency": "USD"}).json()
    for pid, ccy in ((eur["id"], "EUR"), (usd["id"], "USD")):
        acc = gw.post(f"/api/core/portfolios/{pid}/cash-accounts",
                      json={"name": "A", "currency": ccy}).json()
        gw.post(f"/api/core/cash-accounts/{acc['id']}/balances",
                json={"entry_date": "2026-01-02", "balance": 1000})

    totals = gw.get("/api/dashboard/summary", params={"base_currency": "EUR"}).json()["totals"]
    snapshots = gw.get("/api/dashboard/summary").json()["snapshots"]
    naive_sum = sum(s["net_worth_base_ccy"] for s in snapshots)
    assert totals["net_worth"] != pytest.approx(naive_sum), \
        "the converted total must differ from a naive sum once two currencies are involved"


# ----------------------------------------------------------------- concurrency
def test_the_service_survives_concurrent_requests(gw, core_http):
    """SQLAlchemy's default pool caps the engine at 15 concurrent sessions,
    and a request holds its connection for as long as it holds its session --
    price lookups included. The gateway alone fans the dashboard out into one
    request per portfolio, so the ceiling is not something "lots of traffic"
    reaches; a handful of slow requests does. 52 of 60 failed."""
    p = core_http.post("/portfolios", json={"name": "Concurrent", "base_currency": "EUR"}).json()
    acc = core_http.post(f"/portfolios/{p['id']}/cash-accounts",
                         json={"name": "A", "currency": "EUR"}).json()
    core_http.post(f"/cash-accounts/{acc['id']}/balances",
                   json={"entry_date": "2026-01-02", "balance": 500})

    paths = [f"/portfolios/{p['id']}/snapshot", f"/portfolios/{p['id']}/history",
             "/networth/combined/totals", "/portfolios", "/assets"]

    def call(i):
        with httpx.Client(base_url=core_http.base_url, timeout=120) as c:
            return c.get(paths[i % len(paths)]).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(call, range(60)))

    assert all(code == 200 for code in codes), \
        f"{sum(1 for c in codes if c != 200)} of {len(codes)} concurrent requests failed"


def test_concurrent_writes_all_land(core_http):
    p = core_http.post("/portfolios", json={"name": "Writes", "base_currency": "EUR"}).json()
    acc = core_http.post(f"/portfolios/{p['id']}/cash-accounts",
                         json={"name": "A", "currency": "EUR"}).json()
    core_http.post(f"/cash-accounts/{acc['id']}/balances",
                   json={"entry_date": "2026-01-02", "balance": 100000})

    def write(i):
        with httpx.Client(base_url=core_http.base_url, timeout=120) as c:
            return c.post(f"/cash-accounts/{acc['id']}/transactions",
                          json={"entry_date": "2026-06-01", "direction": "EXPENSE",
                                "amount": 1}).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(write, range(40)))
    assert all(code == 200 for code in codes)

    rows = core_http.get(f"/cash-accounts/{acc['id']}/transactions").json()
    assert len(rows) == 40, "every concurrent write must be stored exactly once"
