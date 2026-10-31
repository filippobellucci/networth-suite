"""
bank-sync opens its HTTP connections once, not once per call.

Every call to core-networth and to Enable Banking used to build an
httpx.AsyncClient of its own (a new connection each time), and every request
to Enable Banking read the private key from disk again to sign it.
"""
from __future__ import annotations

import os

import pytest

from service_loader import service_module

pytestmark = pytest.mark.unit

try:  # enable_banking.py reaches PyJWT[crypto], which cannot be imported on every machine
    sync = service_module("bank_app", "sync")
except BaseException as exc:  # noqa: BLE001 - a broken crypto build raises, not imports
    sync = None
    SYNC_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    SYNC_IMPORT_ERROR = ""

if sync is None:
    if os.environ.get("CI"):  # see test_bank_sync_helpers: on CI this must fail, not skip
        raise RuntimeError(f"bank-sync's sync module could not be imported on CI: {SYNC_IMPORT_ERROR}")
    pytest.skip(f"bank-sync's sync module unavailable ({SYNC_IMPORT_ERROR})", allow_module_level=True)

clients = service_module("bank_app", "clients")
enable_banking = service_module("bank_app", "enable_banking")
mcc = service_module("bank_app", "mcc_categories")
httpx = sync.httpx
RealAsyncClient = httpx.AsyncClient


@pytest.fixture
def built(monkeypatch):
    """Every AsyncClient constructed, each answering through a fake server."""
    made: list[httpx.AsyncClient] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/expense-categories":
            return httpx.Response(200, json=[{"id": "c1", "name": "Groceries"}])
        if request.url.path.startswith("/cash-transactions/"):
            return httpx.Response(200, json={"id": request.url.path.rsplit("/", 1)[1]})
        return httpx.Response(200, json={"aspsps": []})

    def factory(**settings):
        client = RealAsyncClient(transport=httpx.MockTransport(handle), **settings)
        made.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setattr(enable_banking, "_signed_jwt", lambda: "token")
    return made


async def test_calls_to_core_share_one_client(built):
    assert await sync._get_from_core("t1") == {"id": "t1"}
    assert await sync._get_from_core("t2") == {"id": "t2"}
    assert await mcc.fetch_category_name_to_id("p1") == {"groceries": "c1"}
    assert len(built) == 1
    assert str(built[0].base_url).rstrip("/") == sync.clients.CORE_SERVICE_URL


async def test_calls_to_enable_banking_share_one_client(built):
    await enable_banking.list_aspsps("IT")
    await enable_banking.list_aspsps("DE")
    assert len(built) == 1


async def test_aclose_closes_the_clients_and_the_next_call_opens_new_ones(built):
    await sync._get_from_core("t1")
    await enable_banking.list_aspsps("IT")
    await clients.aclose()
    assert len(built) == 2 and all(c.is_closed for c in built)

    await sync._get_from_core("t2")
    assert len(built) == 3 and not built[2].is_closed
    await clients.aclose()


def test_private_key_is_read_once_and_again_when_the_file_changes(tmp_path, monkeypatch):
    key = tmp_path / "private.pem"
    key.write_text("first")
    monkeypatch.setattr(enable_banking, "ENABLE_BANKING_PRIVATE_KEY_PATH", str(key))
    monkeypatch.setattr(enable_banking, "_key_cache", None)
    assert enable_banking._private_key() == "first"

    # New content behind the same modification time: only a re-read could see it.
    stat = key.stat()
    key.write_text("other")
    os.utime(key, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert enable_banking._private_key() == "first"

    # The key replaced on disk is picked up without a restart.
    os.utime(key, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert enable_banking._private_key() == "other"

    key.unlink()
    with pytest.raises(enable_banking.EnableBankingError, match="Private key not found"):
        enable_banking._private_key()
