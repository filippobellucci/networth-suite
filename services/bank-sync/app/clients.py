"""
The HTTP clients bank-sync talks through: one for core-networth, one for
Enable Banking. Every call shares them, so connections are pooled rather than
opened and closed per request.

A client is bound to the event loop it was first used on, so there is one per
loop -- the service runs on one, tests start one per test -- held weakly by
the loop object, as core-networth's `price_client._clients` does. `aclose`
closes the running loop's clients when the service stops.
"""
import asyncio
import weakref

import httpx

from .config import CORE_SERVICE_URL, ENABLE_BANKING_BASE_URL

_core: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()
_bank: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = weakref.WeakKeyDictionary()


def _shared(clients: weakref.WeakKeyDictionary, **settings) -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(**settings)
        clients[loop] = client
    return client


def core() -> httpx.AsyncClient:
    """core-networth; paths are relative to CORE_SERVICE_URL."""
    return _shared(_core, base_url=CORE_SERVICE_URL, timeout=15.0)


def enable_banking() -> httpx.AsyncClient:
    """Enable Banking's API; paths are relative to ENABLE_BANKING_BASE_URL."""
    return _shared(_bank, base_url=ENABLE_BANKING_BASE_URL, timeout=30.0)


async def aclose() -> None:
    loop = asyncio.get_running_loop()
    for clients in (_core, _bank):
        client = clients.pop(loop, None)
        if client is not None:
            await client.aclose()
