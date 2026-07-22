"""
Combines core-networth's and geo-allocation's individual backups into one
downloadable zip, and splits an uploaded one back apart for restore.

    backup.zip
    ├── manifest.json        (exported_at + stats from both services)
    ├── core/networth.db     (raw file from core-networth's own export)
    └── geo/fund-files.zip   (geo-allocation's own export, nested as-is)

Building the manifest and splitting the zip back apart both happen here in
the gateway rather than in either service, since this is the one place that
already knows about both of them -- neither service needs to know the other
exists.
"""
import io
import json
import zipfile
from datetime import datetime, timezone


class InvalidBackupError(Exception):
    pass


def build_combined_zip(core_db_bytes: bytes, geo_zip_bytes: bytes, core_stats: dict, geo_stats: dict) -> bytes:
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "app": "networth-suite",
        "core": core_stats,
        "geo": geo_stats,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("core/networth.db", core_db_bytes)
        zf.writestr("geo/fund-files.zip", geo_zip_bytes)
    return buf.getvalue()


def read_manifest(uploaded_bytes: bytes) -> dict:
    try:
        zf = zipfile.ZipFile(io.BytesIO(uploaded_bytes))
    except zipfile.BadZipFile as e:
        raise InvalidBackupError(f"Not a valid backup file: {e}")

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
    try:
        zf = zipfile.ZipFile(io.BytesIO(uploaded_bytes))
    except zipfile.BadZipFile as e:
        raise InvalidBackupError(f"Not a valid backup file: {e}")

    names = zf.namelist()
    if "core/networth.db" not in names or "geo/fund-files.zip" not in names:
        raise InvalidBackupError(
            "This doesn't look like a complete Net Worth Suite backup file "
            "(missing core/networth.db or geo/fund-files.zip)."
        )
    return zf.read("core/networth.db"), zf.read("geo/fund-files.zip")
