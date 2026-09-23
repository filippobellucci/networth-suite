"""
The optional shared-secret gate.

Unset by default -- this app has never had accounts and a single-user
instance on a private LAN does not need them. Setting API_KEY is for anyone
exposing the gateway more widely, so what matters is that it then covers
EVERY route rather than most of them: the one endpoint that bypassed the
frontend's request wrapper was also the one that 401'd once the key was set,
making "Download full backup" the only broken button in the app.
"""
from __future__ import annotations

import os
import subprocess
import sys

import httpx
import pytest

from proc import free_port, wait_healthy
from service_loader import REPO_ROOT

pytestmark = [pytest.mark.system, pytest.mark.slow]

KEY = "a-test-api-key"
BROWSER_ORIGIN = "http://127.0.0.1:5199"


@pytest.fixture(scope="module")
def guarded_gateway(stack, tmp_path_factory):
    """A second gateway in front of the same services, with API_KEY set."""
    port = free_port()
    log = tmp_path_factory.mktemp("guarded") / "gateway.log"
    handle = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(REPO_ROOT / "gateway"),
        env={**os.environ, "API_KEY": KEY,
             "ALLOWED_ORIGINS": BROWSER_ORIGIN,
             "CORE_SERVICE_URL": stack.core_url,
             "PRICE_FEED_URL": stack.feed_url,
             "GEO_ALLOCATION_URL": stack.geo_url,
             "PYTHONUNBUFFERED": "1"},
        stdout=log.open("w"), stderr=subprocess.STDOUT,
    )
    wait_healthy(port)
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60) as client:
        yield client
    handle.terminate()
    handle.wait(timeout=10)


def test_health_stays_open(guarded_gateway):
    """Something has to be able to say whether the service is up."""
    assert guarded_gateway.get("/health").status_code == 200


@pytest.mark.parametrize("method,path", [
    ("get", "/api/core/portfolios"),
    ("get", "/api/dashboard/summary"),
    ("get", "/api/backup/export"),
    ("post", "/api/core/portfolios"),
    ("get", "/api/prices/health"),
])
def test_every_route_needs_the_key(guarded_gateway, method, path):
    response = getattr(guarded_gateway, method)(path)
    assert response.status_code == 401, f"{path} answered {response.status_code} without a key"


@pytest.mark.parametrize("path", [
    "/api/core/portfolios", "/api/dashboard/summary", "/api/backup/export",
])
def test_the_right_key_gets_through(guarded_gateway, path):
    response = guarded_gateway.get(path, headers={"X-API-Key": KEY})
    assert response.status_code == 200


def test_a_wrong_key_is_refused(guarded_gateway):
    for wrong in ("", "nope", KEY[:-1], KEY + "x", KEY.upper()):
        response = guarded_gateway.get("/api/core/portfolios", headers={"X-API-Key": wrong})
        assert response.status_code == 401, f"{wrong!r} was accepted"


def test_a_preflight_is_not_blocked(guarded_gateway):
    """A CORS preflight never carries custom headers, so gating OPTIONS would
    stop the browser before the real request ever went out. Sent with no
    X-API-Key at all, which is exactly how a browser sends it."""
    response = guarded_gateway.request(
        "OPTIONS", "/api/core/portfolios",
        headers={"Origin": BROWSER_ORIGIN,
                 "Access-Control-Request-Method": "GET",
                 "Access-Control-Request-Headers": "x-api-key"},
    )
    assert response.status_code < 400, response.text[:200]
    assert response.headers.get("access-control-allow-origin") == BROWSER_ORIGIN


def test_a_real_request_from_the_browser_origin_still_needs_the_key(guarded_gateway):
    """The preflight being exempt must not make the request after it exempt."""
    blocked = guarded_gateway.get("/api/core/portfolios", headers={"Origin": BROWSER_ORIGIN})
    assert blocked.status_code == 401
    allowed = guarded_gateway.get("/api/core/portfolios",
                                  headers={"Origin": BROWSER_ORIGIN, "X-API-Key": KEY})
    assert allowed.status_code == 200


def test_the_export_endpoint_is_reachable_with_the_key(guarded_gateway):
    """The frontend's download bypasses its own request wrapper, so this is
    the one call that has to send the header by itself."""
    response = guarded_gateway.get("/api/backup/export", headers={"X-API-Key": KEY})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers.get("content-disposition", "")
