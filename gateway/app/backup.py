"""
Combines each service's own backup into one downloadable zip, and splits an
uploaded one back apart for restore.

    backup.zip
    ├── manifest.json        (exported_at + stats from every service)
    ├── core/networth.db     (raw file from core-networth's own export)
    ├── geo/fund-files.zip   (geo-allocation's own export, nested as-is)
    └── bank/bank-sync.zip   (bank-sync's own export -- only when it's deployed)

Building the manifest and splitting the zip back apart both happen here in
the gateway rather than in any one service, since this is the one place that
already knows about all of them -- no service needs to know the others exist.
A backup without bank/ (taken before bank-sync was part of it, or on an
instance without it) is still complete: restoring it just leaves bank-sync's
data as it is.
"""
import io
import json
import zipfile
from datetime import datetime, timezone


class InvalidBackupError(Exception):
    pass


BANK_PATH = "bank/bank-sync.zip"


def build_combined_zip(
    core_db_bytes: bytes,
    geo_zip_bytes: bytes,
    core_stats: dict,
    geo_stats: dict,
    bank_zip_bytes: bytes | None = None,
    bank_stats: dict | None = None,
) -> bytes:
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "app": "networth-suite",
        "core": core_stats,
        "geo": geo_stats,
    }
    if bank_zip_bytes is not None:
        manifest["bank"] = bank_stats or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("core/networth.db", core_db_bytes)
        zf.writestr("geo/fund-files.zip", geo_zip_bytes)
        if bank_zip_bytes is not None:
            zf.writestr(BANK_PATH, bank_zip_bytes)
    return buf.getvalue()


def _open(uploaded_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(uploaded_bytes))
    except zipfile.BadZipFile as e:
        raise InvalidBackupError(f"Not a valid backup file: {e}")


def bank_part(uploaded_bytes: bytes) -> bytes | None:
    """bank-sync's own archive inside a combined backup, or None when the
    backup has none. Call after split_combined_zip has validated the file."""
    zf = _open(uploaded_bytes)
    return zf.read(BANK_PATH) if BANK_PATH in zf.namelist() else None


def read_manifest(uploaded_bytes: bytes) -> dict:
    zf = _open(uploaded_bytes)
    if "manifest.json" not in zf.namelist():
        raise InvalidBackupError(
            "This doesn't look like a Net Worth Suite backup file (no manifest.json found)."
        )
    try:
        return json.loads(zf.read("manifest.json"))
    except (json.JSONDecodeError, KeyError) as e:
        raise InvalidBackupError(f"Backup file's manifest is unreadable: {e}")


def split_combined_zip(uploaded_bytes: bytes) -> tuple[bytes, bytes]:
    """Returns (core_db_bytes, geo_zip_bytes). Raises InvalidBackupError if
    either part is missing -- restore should not run half a backup."""
    zf = _open(uploaded_bytes)
    names = zf.namelist()
    if "core/networth.db" not in names or "geo/fund-files.zip" not in names:
        raise InvalidBackupError(
            "This doesn't look like a complete Net Worth Suite backup file "
            "(missing core/networth.db or geo/fund-files.zip)."
        )
    return zf.read("core/networth.db"), zf.read("geo/fund-files.zip")
