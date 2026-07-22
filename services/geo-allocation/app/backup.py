"""
Export/restore for geo-allocation's uploaded factsheet files (the
`FUND_FILES_DIR` tree: one folder per asset_id, each holding the original
uploaded Excel file plus its cached parsed result). Same on-demand
counterpart to the automatic daily backup in scheduler.py, plus the ability
to load one back in -- see core-networth/app/backup.py for the shared
design rationale (validate first, safety-copy before overwriting, then
restore).
"""
import io
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .config import FUND_FILES_DIR

BACKUP_DIR = Path("/backups")


class InvalidBackupError(Exception):
    pass


def export_zip_bytes() -> bytes:
    """Zips the whole fund-files tree into an in-memory archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if FUND_FILES_DIR.exists():
            for path in FUND_FILES_DIR.rglob("*"):
                if path.is_file():
                    zf.write(path, arcname=str(path.relative_to(FUND_FILES_DIR)))
    return buf.getvalue()


def get_stats() -> dict:
    if not FUND_FILES_DIR.exists():
        return {"assets_with_files": 0}
    count = sum(1 for d in FUND_FILES_DIR.iterdir() if d.is_dir() and (d / "allocation.json").exists())
    return {"assets_with_files": count}


def _validate_zip(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise InvalidBackupError(f"Not a valid zip archive: {e}")

    bad = zf.testzip()
    if bad is not None:
        raise InvalidBackupError(f"Corrupt entry in archive: {bad}")

    # Guard against zip-slip: every member must resolve to somewhere inside
    # the target directory once extracted, never escape it via "../".
    # Path.is_relative_to (not a string-prefix check) so a sibling directory
    # that merely starts with the same characters isn't mistaken for "inside".
    base = FUND_FILES_DIR.resolve()
    for member in zf.namelist():
        target = (FUND_FILES_DIR / member).resolve()
        if not target.is_relative_to(base):
            raise InvalidBackupError(f"Archive contains an unsafe path: {member}")

    return zf


def preview_uploaded_zip(data: bytes) -> dict:
    """Validates an uploaded archive and reports what it contains, without
    touching anything on disk."""
    zf = _validate_zip(data)
    asset_ids = {name.split("/")[0] for name in zf.namelist() if "/" in name}
    return {"assets_with_files": len(asset_ids)}


def restore_from_zip(data: bytes) -> dict:
    zf = _validate_zip(data)

    if FUND_FILES_DIR.exists() and any(FUND_FILES_DIR.iterdir()):
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        safety_dir = BACKUP_DIR / f"pre-restore-{stamp}" / "fund-files"
        safety_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(FUND_FILES_DIR, safety_dir, dirs_exist_ok=True)

    if FUND_FILES_DIR.exists():
        shutil.rmtree(FUND_FILES_DIR)
    FUND_FILES_DIR.mkdir(parents=True, exist_ok=True)
    zf.extractall(FUND_FILES_DIR)

    return get_stats()
