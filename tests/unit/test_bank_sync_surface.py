"""
bank-sync's two surfaces: the public app (the port the browser and each
bank's login redirect reach) serves only the status page, the authorization
round trip and a health check; everything else -- backups, helpers, the JSON
status, the raw audit log, a manual sync -- is on the internal app, which
only the gateway reaches.

The routes themselves are covered elsewhere; this pins which app each one
belongs to, so a new endpoint cannot land on the public port by accident.
"""
from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from service_loader import service_module

pytestmark = pytest.mark.unit


@pytest.fixture
def main(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/bank_sync.db")
    return service_module("bank_app", "main")


def routes(app) -> set[tuple[str, str]]:
    return {(method, r.path) for r in app.routes if isinstance(r, APIRoute) for method in r.methods}


def test_the_public_app_serves_only_the_browser_facing_routes(main):
    assert routes(main.public_app) == {
        ("GET", "/"),
        ("GET", "/authorize/{label}"),
        ("GET", "/callback"),
        ("GET", "/health"),
    }


def test_the_internal_app_serves_everything_else_and_no_authorization(main):
    internal = routes(main.internal_app)
    for route in [("GET", "/status"), ("POST", "/sync-now"), ("GET", "/transactions-log.csv"),
                  ("GET", "/backup/export"), ("GET", "/backup/stats"), ("POST", "/backup/preview"),
                  ("POST", "/backup/restore"), ("GET", "/helper/aspsps"), ("GET", "/helper/accounts"),
                  ("GET", "/helper/categories"), ("GET", "/health")]:
        assert route in internal
    assert not {path for _, path in internal} & {"/", "/authorize/{label}", "/callback"}


def test_sync_now_is_a_post_and_a_get_does_not_trigger_it(main, monkeypatch):
    from fastapi.testclient import TestClient

    cycles = []

    async def sync_all():
        cycles.append(1)
        return {"synced": 0}

    monkeypatch.setattr(main, "sync_all", sync_all)
    # Not a context manager: no startup work, no scheduler.
    client = TestClient(main.internal_app)

    assert client.get("/sync-now").status_code == 405
    assert cycles == []
    r = client.post("/sync-now")
    assert r.status_code == 200
    assert r.json() == {"synced": 0}
    assert cycles == [1]


def test_the_status_page_links_neither_the_audit_log_nor_a_manual_sync(main, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path}/page.db")
    service_module("bank_app", "database").Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=engine))

    page = TestClient(main.public_app).get("/").text
    assert "/sync-now" not in page
    assert "/transactions-log.csv" not in page
