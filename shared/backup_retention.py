"""
Rotation for the daily backup folders the three backing-up services
(core-networth, geo-allocation, bank-sync) write under their BACKUP_DIR --
one `YYYY-MM-DD` folder per day, plus a `pre-restore-<timestamp>` safety
copy before every restore. One rule, shared, rather than copied three times:
each service's own scheduler/backup module calls `rotate_backups` after
writing its newest entry.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

_DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PRE_RESTORE_RE = re.compile(r"^pre-restore-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})$")


def _entry_timestamp(name: str) -> datetime | None:
    """The moment a backup folder's name represents, or None if `name` isn't
    one of ours -- rotation leaves anything it doesn't recognize alone."""
    if _DAILY_RE.match(name):
        return datetime.strptime(name, "%Y-%m-%d")
    match = _PRE_RESTORE_RE.match(name)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%S")
    return None


def rotate_backups(base_dir: Path, retention_days: int) -> list[Path]:
    """
    Deletes the backup folders directly under `base_dir` that the retention
    policy no longer needs, and returns the ones removed.

    Policy: every entry from the last `retention_days` days is kept as-is;
    anything older survives only as the single most recent entry in its
    calendar month. The most recent entry overall is never removed, even
    when `retention_days` is 0 or negative -- a restore must always have
    something to fall back on.

    The "last N days" is measured from the newest entry present, not from
    the real calendar date: every caller writes its newest entry and only
    then rotates, so the newest entry already *is* "now".
    """
    if not base_dir.is_dir():
        return []

    entries = []
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        timestamp = _entry_timestamp(child.name)
        if timestamp is not None:
            entries.append((timestamp, child))
    if not entries:
        return []

    entries.sort(key=lambda entry: entry[0])
    newest_timestamp, newest_path = entries[-1]
    cutoff = newest_timestamp - timedelta(days=max(retention_days, 0))

    keep = {newest_path}
    monthly_best: dict[tuple[int, int], tuple[datetime, Path]] = {}
    for timestamp, path in entries:
        if timestamp >= cutoff:
            keep.add(path)
            continue
        month_key = (timestamp.year, timestamp.month)
        current = monthly_best.get(month_key)
        if current is None or timestamp > current[0]:
            monthly_best[month_key] = (timestamp, path)
    keep.update(path for _, path in monthly_best.values())

    removed = []
    for _, path in entries:
        if path not in keep:
            shutil.rmtree(path)
            removed.append(path)
    return removed
