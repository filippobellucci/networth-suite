import logging
import os
from pathlib import Path

logger = logging.getLogger("core-networth.config")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Where the daily copy and the pre-restore safety copy are written. The
# default is the path docker-compose bind-mounts; running on the host, where
# "/backups" usually can't be created, see backup_target's fallback.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))


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
