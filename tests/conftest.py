"""
Shared fixtures.

Two tiers, because they buy different things:

  * `integration` drives core-networth's ASGI app in-process, with a fresh
    SQLite file and a controllable price feed per test. Fast and completely
    isolated, which is what makes it usable as a pre-commit gate.

  * `system` starts the real services as separate processes behind the real
    gateway. Slower, and only used for the properties that do not exist
    anywhere else: the proxy, cross-service backup/restore, the connection
    pool under concurrency, the API-key gate.

Anything that needs neither is a `unit` test and imports the module directly.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_feed import FakeFeed  # noqa: E402
from proc import Service, free_port, wait_healthy  # noqa: E402
from service_loader import REPO_ROOT, load_service, service_module  # noqa: E402


# --------------------------------------------------------------- date helpers
# Every test dates its data relative to today, so the suite never rots: a
# hardcoded 2024 date would start failing the moment "a year ago" moved.
TODAY = date.today()


def days_ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def iso(d: date) -> str:
    return d.isoformat()


# ------------------------------------------------------------- service import
@pytest.fixture(scope="session")
def core(tmp_path_factory):
    """The core-networth package, imported once with its own data directory."""
    data_dir = tmp_path_factory.mktemp("core-import")
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["DATABASE_URL"] = f"sqlite:///{data_dir}/import.db"
    os.environ.setdefault("PRICE_FEED_URL", "http://price-feed.invalid")
    return load_service("core_app")


@pytest.fixture(scope="session")
def core_modules(core):
    return {
        name: service_module("core_app", name)
        for name in ("main", "models", "schemas", "valuation", "xirr",
                     "price_client", "scheduler", "database", "backup", "migrate")
    }


# ----------------------------------------------------------------- price feed
@pytest.fixture
def feed(core_modules, monkeypatch) -> FakeFeed:
    """A price feed under the test's control, wired in at the HTTP boundary.

    The in-process cache is cleared too: it is keyed by ticker and date and
    deliberately permanent for a past day, so without this a price set by one
    test would be served to the next one.
    """
    price_client = core_modules["price_client"]
    fake = FakeFeed()
    price_client._cache.clear()
    monkeypatch.setattr(price_client, "_get_json", fake.get_json)
    return fake


# ------------------------------------------------------------------- database
@pytest.fixture
def db_engine(core_modules, tmp_path):
    """A brand-new SQLite database per test, built the way production builds it."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    core_modules["models"].Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(core_modules, db_engine):
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api(core_modules, db_engine, feed):
    """An httpx client speaking to core-networth's ASGI app in-process.

    `get_db` is overridden so every request runs against this test's own
    database. The app object itself is shared (importing it is not free), which
    is safe because nothing test-visible lives on it -- all state is in the
    database the dependency hands out.
    """
    import httpx
    from sqlalchemy.orm import sessionmaker

    main = core_modules["main"]
    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[core_modules["database"].get_db] = override_get_db
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app),
        base_url="http://core-networth",
        timeout=60.0,
    )
    yield client
    main.app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def stack(tmp_path_factory):
    """The whole app running for real: fake price feed, core, geo, gateway.

    Session-scoped because starting four processes per test would dominate the
    run. Tests that need an empty instance create their own portfolio and
    assert about that, rather than about global totals.
    """
    root = tmp_path_factory.mktemp("stack")
    logs = root / "logs"
    logs.mkdir()

    feed_port = free_port()
    feed_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "price_feed_stub:app",
         "--host", "127.0.0.1", "--port", str(feed_port), "--log-level", "warning"],
        cwd=str(Path(__file__).resolve().parent),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=(logs / "feed.log").open("w"), stderr=subprocess.STDOUT,
    )
    wait_healthy(feed_port)

    core_port, geo_port, gw_port = free_port(), free_port(), free_port()
    core_data = root / "core-data"
    geo_data = root / "geo-data"
    backups = root / "backups"
    core_data.mkdir()
    geo_data.mkdir()
    backups.mkdir()

    services = [
        # BACKUP_DIR is set so the suite never writes to the real /backups,
        # on a runner or on a developer's machine. The default is an absolute
        # path only root can create, which is how a restore that works under
        # Docker came to fail everywhere else.
        Service("core", REPO_ROOT / "services" / "core-networth", core_port,
                 {"DATA_DIR": str(core_data),
                  "DATABASE_URL": f"sqlite:///{core_data}/networth.db",
                  "BACKUP_DIR": str(backups / "core"),
                  "PRICE_FEED_URL": f"http://127.0.0.1:{feed_port}"},
                 logs / "core.log"),
        Service("geo", REPO_ROOT / "services" / "geo-allocation", geo_port,
                 {"DATA_DIR": str(geo_data),
                  "BACKUP_DIR": str(backups / "geo")}, logs / "geo.log"),
    ]
    for s in services:
        wait_healthy(s.port)

    # Reserved up front so the gateway can be told which origin the browser
    # suite will serve the built frontend from: a CORS rejection there looks
    # exactly like a broken application.
    spa_port = free_port()

    gateway = Service(
        "gateway", REPO_ROOT / "gateway", gw_port,
        {"CORE_SERVICE_URL": f"http://127.0.0.1:{core_port}",
         "PRICE_FEED_URL": f"http://127.0.0.1:{feed_port}",
         "GEO_ALLOCATION_URL": f"http://127.0.0.1:{geo_port}",
         "ALLOWED_ORIGINS": f"http://127.0.0.1:{spa_port}"},
        logs / "gateway.log")
    wait_healthy(gw_port)

    class Stack:
        core_url = f"http://127.0.0.1:{core_port}"
        geo_url = f"http://127.0.0.1:{geo_port}"
        gateway_url = f"http://127.0.0.1:{gw_port}"
        feed_url = f"http://127.0.0.1:{feed_port}"
        frontend_port = spa_port
        core_data_dir = core_data
        geo_data_dir = geo_data
        backups_dir = backups
        logs_dir = logs
        gateway_log = staticmethod(gateway.log_text)
        core_log = staticmethod(services[0].log_text)

    yield Stack()

    gateway.stop()
    for s in services:
        s.stop()
    feed_proc.terminate()
    try:
        feed_proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover
        feed_proc.kill()


@pytest.fixture
def gw(stack):
    """A client for the running gateway."""
    import httpx

    with httpx.Client(base_url=stack.gateway_url, timeout=120.0) as client:
        yield client


@pytest.fixture
def core_http(stack):
    """A client that talks to the running core service directly."""
    import httpx

    with httpx.Client(base_url=stack.core_url, timeout=120.0) as client:
        yield client
