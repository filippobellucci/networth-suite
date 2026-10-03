import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger("geo-allocation.config")

# `shared/` lives at the repo root, which sits a different number of
# directories above this file depending on how the service runs: several
# levels up here, one level up once Docker lays this out as a sibling of
# `app/` (see Dockerfile). Walking up from this file instead of hardcoding
# either depth makes both layouts resolve the same import.
for _ancestor in Path(__file__).resolve().parents:
    if (_ancestor / "shared" / "backup_retention.py").is_file():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

# Local folder (mounted as a Docker volume) where the uploaded fund/ETF
# factsheet Excel files are kept -- this is the single source of truth for
# "which file is currently associated with which asset". Re-uploading for
# the same asset_id overwrites the previous file, as requested.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
FUND_FILES_DIR = DATA_DIR / "fund-files"
FUND_FILES_DIR.mkdir(parents=True, exist_ok=True)

# asset_id always comes from core-networth's models.gen_id() (a short hex
# fragment) -- constraining it to this safe charset at every entry point
# closes off using it as an uncontrolled filesystem path segment (e.g. a
# ".." segment escaping FUND_FILES_DIR) while still accepting every real id.
ASSET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# A real ETF/fund factsheet is a few MB at most; this is a generous ceiling
# against an accidental (or malicious) oversized upload being read entirely
# into memory with no limit.
MAX_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", 25 * 1024 * 1024))

# A full-instance backup archive is naturally larger (every asset's
# factsheet combined) -- generous but still bounded, both for the raw
# upload and for what it's allowed to expand to on restore (zip-bomb guard).
MAX_BACKUP_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_BACKUP_UPLOAD_SIZE_BYTES", 200 * 1024 * 1024))
MAX_BACKUP_EXTRACTED_SIZE_BYTES = int(os.environ.get("MAX_BACKUP_EXTRACTED_SIZE_BYTES", 1024 * 1024 * 1024))


# Where the daily copy of the fund files and the pre-restore safety copy go.
# Defaults to the path docker-compose bind-mounts; see backup_target's
# fallback for a host where "/backups" can't be created.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))

# How many days of daily/pre-restore copies to keep as-is before thinning
# older ones down to one per calendar month (see shared/backup_retention.py).
# 0 or negative still always keeps the single most recent copy.
BACKUP_RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "30"))


def backup_target(name: str) -> Path:
    """Creates and returns `BACKUP_DIR/name`, or the same folder under
    DATA_DIR when BACKUP_DIR cannot be written to.

    Falling back rather than failing is deliberate: the caller is taking
    either the daily copy or the safety copy that makes a restore undoable,
    and a backup in an unexpected place is worth far more than no backup.
    The warning names the path actually used, so it is never silent.
    """
    try:
        target = BACKUP_DIR / name
        target.mkdir(parents=True, exist_ok=True)
        return target
    except OSError as e:
        fallback = DATA_DIR / "backups" / name
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "Backup directory %s is not usable (%s) -- writing to %s instead. "
            "Set BACKUP_DIR to somewhere writable to choose where these go.",
            BACKUP_DIR, e, fallback,
        )
        return fallback
