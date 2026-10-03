import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("core-networth.config")

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

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Where the daily copy and the pre-restore safety copy are written. The
# default is the path docker-compose bind-mounts; running on the host, where
# "/backups" usually can't be created, see backup_target's fallback.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))

# How many days of daily/pre-restore copies to keep as-is before thinning
# older ones down to one per calendar month (see shared/backup_retention.py).
# 0 or negative still always keeps the single most recent copy.
BACKUP_RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "30"))


def backup_target(name: str) -> Path:
    """Creates and returns `BACKUP_DIR/name`, or the same folder under
    DATA_DIR when BACKUP_DIR cannot be written to.

    Falling back rather than failing is deliberate: a backup written
    somewhere unexpected beats no backup. DATA_DIR is writable (the database
    lives there), and the warning names the path actually used.
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

DATABASE_URL = os.environ.get(
    "DATABASE_URL", f"sqlite:///{DATA_DIR}/networth.db"
)

# URL of the price-feed service, used to enrich holdings with live prices
PRICE_FEED_URL = os.environ.get("PRICE_FEED_URL", "http://price-feed:8001")

# A full database backup upload (Settings -> Restore) shouldn't need to be
# larger than this for a personal-finance SQLite database -- bounds how much
# an uploaded file is read entirely into memory before it's even validated.
MAX_BACKUP_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_BACKUP_UPLOAD_SIZE_BYTES", 200 * 1024 * 1024))
