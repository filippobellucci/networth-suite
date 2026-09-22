"""
Same daily-backup-on-startup pattern as core-networth's scheduler, scoped to
just this service's own data: the uploaded fund/ETF factsheets and their
parsed allocation results. See core-networth/app/scheduler.py for the fuller
explanation of the "runs once immediately, then re-checks periodically,
never retroactive" design.
"""
import asyncio
import logging
import shutil
from datetime import date

from .config import FUND_FILES_DIR, backup_target

logger = logging.getLogger("geo-allocation.scheduler")

CHECK_INTERVAL_HOURS = 6


def maybe_run_daily_backup():
    try:
        if not FUND_FILES_DIR.exists() or not any(FUND_FILES_DIR.iterdir()):
            return
        today_dir = backup_target(date.today().isoformat())
        dest = today_dir / "fund-files"
        if dest.exists():
            return
        shutil.copytree(FUND_FILES_DIR, dest)
        logger.info("Backed up fund files to %s", dest)
    except Exception as e:
        logger.warning("Daily backup failed: %s", e)


async def run_all_jobs():
    maybe_run_daily_backup()


async def scheduler_loop():
    """Same guard as core-networth's loop: anything escaping a job ends this
    background task for good, silently, and the daily backup just stops
    happening with nothing on screen to say so. `Exception`, not a bare
    `except`, so shutdown's CancelledError still passes through."""
    while True:
        try:
            await run_all_jobs()
        except Exception as e:
            logger.warning("Scheduled job cycle failed: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_HOURS * 3600)
