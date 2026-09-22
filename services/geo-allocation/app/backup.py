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
import zlib
from datetime import datetime, timezone
from pathlib import Path

from .config import FUND_FILES_DIR, MAX_BACKUP_EXTRACTED_SIZE_BYTES, backup_target



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


def _safe_target(base: Path, name: str) -> Path:
    """
    Where `name` extracts to under `base`, refusing anything that escapes it
    (zip-slip via "../" or an absolute path).

    Path.is_relative_to on the *resolved* path, not a string-prefix check, so
    a sibling directory that merely starts with the same characters isn't
    mistaken for "inside".

    Used by both the up-front validation and the loop that actually writes,
    so the check on the writing line can't drift from the one that accepted
    the archive.
    """
    target = (base / name).resolve()
    if not target.is_relative_to(base.resolve()):
        raise InvalidBackupError(f"Archive contains an unsafe path: {name}")
    return target


def _validate_zip(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise InvalidBackupError(f"Not a valid zip archive: {e}")

    bad = zf.testzip()
    if bad is not None:
        raise InvalidBackupError(f"Corrupt entry in archive: {bad}")

    # Guard against zip-slip: every member must land inside the target
    # directory once extracted, never escape it via "../".
    total_uncompressed = 0
    for info in zf.infolist():
        _safe_target(FUND_FILES_DIR, info.filename)
        total_uncompressed += info.file_size

    # Zip-bomb guard, first pass: reject an archive that *declares* more than
    # the limit. The declared size is only a header field the uploader
    # controls, so it's a cheap early exit, not the actual protection --
    # that's _extract_bounded below, which counts real decompressed bytes.
    if total_uncompressed > MAX_BACKUP_EXTRACTED_SIZE_BYTES:
        raise InvalidBackupError(
            f"Archive would extract to {total_uncompressed} bytes, over the "
            f"{MAX_BACKUP_EXTRACTED_SIZE_BYTES}-byte limit"
        )

    return zf


def _extract_bounded(zf: zipfile.ZipFile, destination: Path) -> None:
    """
    Extracts every member while counting the bytes actually written, and
    aborts the moment the total exceeds the limit.

    `extractall()` trusts nothing at all, and the pre-check above trusts the
    archive's own headers -- a crafted zip can declare a few kilobytes and
    decompress to gigabytes, filling the disk of the machine this runs on.
    Streaming with a running total is the only count that can't be lied to.
    """
    written = 0
    for info in zf.infolist():
        # _validate_zip already rejected anything escaping the target
        # directory; re-checked here so the guard sits on the line that
        # actually writes, and can't be lost if these two ever drift apart.
        target = _safe_target(destination, info.filename)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zf.open(info) as source, open(target, "wb") as out:
                while chunk := source.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_BACKUP_EXTRACTED_SIZE_BYTES:
                        raise InvalidBackupError(
                            f"Archive expands past the {MAX_BACKUP_EXTRACTED_SIZE_BYTES}-byte limit -- "
                            "extraction stopped"
                        )
                    out.write(chunk)
        except (zipfile.BadZipFile, zlib.error, EOFError) as e:
            # Damage that only shows up while decompressing (a bad CRC, a
            # corrupt deflate stream, a truncated member) -- a rejected
            # upload, not a server error.
            raise InvalidBackupError(f"Corrupt entry in archive ({info.filename}): {e}")


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
        safety_dir = backup_target(f"pre-restore-{stamp}") / "fund-files"
        safety_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(FUND_FILES_DIR, safety_dir, dirs_exist_ok=True)

    if FUND_FILES_DIR.exists():
        shutil.rmtree(FUND_FILES_DIR)
    FUND_FILES_DIR.mkdir(parents=True, exist_ok=True)
    _extract_bounded(zf, FUND_FILES_DIR)

    return get_stats()
