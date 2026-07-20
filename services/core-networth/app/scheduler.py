"""
Lightweight in-process scheduler -- no extra dependency (no APScheduler
needed): a background asyncio task that runs all jobs once immediately on
startup (so a machine that's only powered on once a day still gets same-day
results) and then re-checks periodically in case the app stays running
longer than that.

Three independent, idempotent jobs (safe to run as often as we like):

  - refresh_all_prices(): warms live prices for every tracked ticker/currency
    pair. Runs on every startup regardless of how long the machine was off --
    there's no meaningful "missed days" backlog for a *live* price (it only
    ever represents "right now"); what matters is that it's fresh the moment
    someone might look at it. Real historical accuracy for past dates is
    handled separately by the on-date historical price endpoint, which
    always re-derives from Yahoo Finance directly and is unaffected by any
    of this.

  - catch_up_monthly_snapshots(): backfills any missed end-of-month net
    worth snapshot, dated and priced as of the date it *should* have been
    taken (using real historical prices), not the date it actually got a
    chance to run.

  - maybe_run_daily_backup(): copies the SQLite database into ./backups
    once per calendar day. Deliberately NOT retroactive -- if the machine
    was off all day, that day simply has no backup, which is fine.
"""
import asyncio
import logging
import shutil
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

from . import models, price_client, valuation
from .config import DATA_DIR
from .database import SessionLocal

logger = logging.getLogger("core-networth.scheduler")

CHECK_INTERVAL_HOURS = 6
BACKUP_DIR = Path("/backups")
SNAPSHOT_CURRENCY = "EUR"
MAX_MONTHS_BACK = 36  # sanity cap on how far catch-up will ever backfill


async def refresh_all_prices():
    db = SessionLocal()
    try:
        tickers = {a.ticker for a in db.query(models.Asset).filter(models.Asset.ticker.isnot(None)).all()}
        if not tickers:
            return
        logger.info("Scheduled price refresh: %d ticker(s)", len(tickers))
        for t in tickers:
            await price_client.get_latest_price(t, force=True)

        currencies = {p.base_currency for p in db.query(models.Portfolio).all()}
        currencies |= {a.currency for a in db.query(models.Asset).all()}
        currencies |= {c.currency for c in db.query(models.CashAccount).all()}
        for c in currencies:
            for base in currencies:
                if c != base:
                    await price_client.get_fx_rate(c, base, force=True)
        logger.info("Scheduled price refresh complete")
    except Exception as e:
        logger.warning("Scheduled price refresh failed: %s", e)
    finally:
        db.close()


def _last_day_of_month(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _last_completed_month_end(today: date) -> date:
    """The most recent month-end that has fully happened -- today itself,
    if today happens to be the last day of the month."""
    if today == _last_day_of_month(today.year, today.month):
        return today
    year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return _last_day_of_month(year, month)


def _month_ends_between(start: date, end: date):
    y, m = start.year, start.month
    while True:
        last = _last_day_of_month(y, m)
        if last > end:
            return
        yield last
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


async def catch_up_monthly_snapshots():
    db = SessionLocal()
    try:
        entry_dates = valuation.distinct_entry_dates(db)
        if not entry_dates:
            return

        today = date.today()
        start = max(entry_dates[0], today - timedelta(days=MAX_MONTHS_BACK * 31))
        last_completed = _last_completed_month_end(today)

        existing = {
            s.snapshot_date
            for s in db.query(models.NetWorthSnapshot)
            .filter(models.NetWorthSnapshot.currency == SNAPSHOT_CURRENCY)
            .all()
        }

        for month_end in _month_ends_between(start, last_completed):
            if month_end in existing:
                continue
            totals = await valuation.compute_combined_net_worth_now(db, SNAPSHOT_CURRENCY, as_of=month_end)
            db.add(
                models.NetWorthSnapshot(
                    snapshot_date=month_end,
                    currency=SNAPSHOT_CURRENCY,
                    net_worth=totals["net_worth"],
                    invested_total=totals["invested_total"],
                    cash_total=totals["cash_total"],
                    source="auto",
                )
            )
            db.commit()
            logger.info("Auto snapshot backfilled for %s: %.2f %s", month_end, totals["net_worth"], SNAPSHOT_CURRENCY)
    except Exception as e:
        logger.warning("Monthly snapshot catch-up failed: %s", e)
        db.rollback()
    finally:
        db.close()


def maybe_run_daily_backup():
    """Copies the SQLite database into /backups/<today>/ once per calendar
    day. `/backups` is expected to be a bind-mounted host folder (see
    docker-compose.yml) so it survives even if the `core_data` volume were
    ever removed."""
    try:
        db_file = DATA_DIR / "networth.db"
        if not db_file.exists():
            return
        today_dir = BACKUP_DIR / date.today().isoformat()
        dest = today_dir / "networth.db"
        if dest.exists():
            return
        today_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_file, dest)
        logger.info("Backed up database to %s", dest)
    except Exception as e:
        logger.warning("Daily backup failed: %s", e)


async def run_all_jobs():
    await refresh_all_prices()
    await catch_up_monthly_snapshots()
    maybe_run_daily_backup()


async def scheduler_loop():
    await run_all_jobs()
    while True:
        await asyncio.sleep(CHECK_INTERVAL_HOURS * 3600)
        await run_all_jobs()
