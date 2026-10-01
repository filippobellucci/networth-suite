"""
Same lightweight in-process pattern as core-networth's scheduler.py: an
asyncio background task, no extra dependency. Runs once on startup, then
every SYNC_INTERVAL_HOURS.
"""
import asyncio
import logging

from .backup import maybe_run_daily_backup
from .sync import sync_all
from .config import SYNC_INTERVAL_HOURS

logger = logging.getLogger("bank-sync.scheduler")


async def scheduler_loop():
    while True:
        maybe_run_daily_backup()  # swallows its own failures
        try:
            await sync_all()
        except Exception as e:
            logger.warning("Sync cycle failed: %s", e)
        await asyncio.sleep(SYNC_INTERVAL_HOURS * 3600)
