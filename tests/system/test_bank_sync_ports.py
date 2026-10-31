"""
bank-sync running for real, as `python -m app.serve` starts it in its
container: the public port (published on the host, reached by the browser and
each bank's login redirect) answers only the status page, the authorization
round trip and /health; everything else is on the internal port, which only
the gateway reaches.
"""
from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.system, pytest.mark.slow]

INTERNAL_ONLY = [
    ("GET", "/backup/export"),
    ("GET", "/backup/stats"),
    ("POST", "/backup/preview"),
    ("POST", "/backup/restore"),
    ("GET", "/transactions-log.csv"),
    ("GET", "/helper/accounts"),
    ("GET", "/helper/aspsps?country=IT"),
    ("GET", "/status"),
    ("GET", "/sync-now"),
    ("POST", "/sync-now"),
]


@pytest.mark.parametrize("method,path", INTERNAL_ONLY)
def test_the_public_port_does_not_serve_internal_routes(stack, method, path):
    r = httpx.request(method, stack.bank_public_url + path, timeout=30)
    assert r.status_code == 404, f"{method} {path} is reachable on the public port"


def test_the_public_port_serves_the_status_page_and_the_authorization_round_trip(stack):
    assert httpx.get(stack.bank_public_url + "/health").json() == {"status": "ok"}
    page = httpx.get(stack.bank_public_url + "/")
    assert page.status_code == 200 and "Bank Sync" in page.text
    # An unknown label is refused by the route itself -- nothing reaches a bank.
    unknown = httpx.get(stack.bank_public_url + "/authorize/no-such-link")
    assert unknown.status_code == 404 and "No link named" in unknown.text
    # No `state`: the callback route answers, and refuses.
    assert httpx.get(stack.bank_public_url + "/callback").status_code == 400


def test_the_internal_port_and_the_gateway_serve_the_rest(stack, gw):
    assert httpx.get(stack.bank_url + "/status").status_code == 200
    assert httpx.get(stack.bank_url + "/authorize/no-such-link").status_code == 404
    status = gw.get("/api/bank/status")
    assert status.status_code == 200 and "links" in status.json()
    assert gw.get("/health").json()["modules"]["bank"] == "ok"
