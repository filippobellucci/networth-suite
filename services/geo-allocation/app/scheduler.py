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
from pathlib import Path

from .config import FUND_FILES_DIR

logger = logging.getLogger("geo-allocation.scheduler")

CHECK_INTERVAL_HOURS = 6
BACKUP_DIR = Path("/backups")


def maybe_run_daily_backup():
    try:
        if not FUND_FILES_DIR.exists() or not any(FUND_FILES_DIR.iterdir()):
            return
        today_dir = BACKUP_DIR / date.today().isoformat()
        dest = today_dir / "fund-files"
        if dest.exists():
            return
        today_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(FUND_FILES_DIR, dest)
        logger.info("Backed up fund files to %s", dest)
    except Exception as e:
        logger.warning("Daily backup failed: %s", e)


async def run_all_jobs():
    maybe_run_daily_backup()


async def scheduler_loop():
    await run_all_jobs()
    while True:
        await asyncio.sleep(CHECK_INTERVAL_HOURS * 3600)
        await run_all_jobs()
