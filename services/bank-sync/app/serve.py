"""
bank-sync's entrypoint (`python -m app.serve`): main.py's two apps on their
two ports, in one process, so they share the database, the sync lock and the
pending authorizations. The startup work -- reconciling links.yaml with the
database, starting the scheduler -- is done here, once, rather than in either
app's lifespan, which would run it twice; so is closing the shared HTTP
clients (`clients.py`) at shutdown.

On SIGTERM/SIGINT each uvicorn server stops and passes the signal on to the
one started before it, so both shut down cleanly.
"""
import asyncio

import uvicorn

from . import clients
from .config import INTERNAL_PORT, PUBLIC_PORT
from .database import SessionLocal
from .links_config import sync_links_config_to_db
from .main import internal_app, public_app
from .scheduler import scheduler_loop


async def main() -> None:
    db = SessionLocal()
    try:
        sync_links_config_to_db(db)
    finally:
        db.close()
    scheduler = asyncio.create_task(scheduler_loop())
    servers = [
        uvicorn.Server(uvicorn.Config(public_app, host="0.0.0.0", port=PUBLIC_PORT)),
        uvicorn.Server(uvicorn.Config(internal_app, host="0.0.0.0", port=INTERNAL_PORT)),
    ]
    try:
        await asyncio.gather(*(server.serve() for server in servers))
    finally:
        scheduler.cancel()
        await clients.aclose()


if __name__ == "__main__":
    asyncio.run(main())
