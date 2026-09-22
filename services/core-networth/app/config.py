import logging
import os
from pathlib import Path

logger = logging.getLogger("core-networth.config")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Where the daily copy and the pre-restore safety copy are written. The
# default is the path docker-compose bind-mounts, so a Docker deployment is
# unchanged -- but unlike DATA_DIR this used to be hardcoded, and "/backups"
# is at the filesystem root, which only root can create. Running the services
# directly on the host is a documented setup (see the README), and there this
# meant two silent failures at once: the daily backup job swallowed its own
# PermissionError and simply never ran, so the user believed they had
# automatic backups and had none; and Settings -> Restore answered a bare
# "Internal Server Error" with nothing to say why.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))


def backup_target(name: str) -> Path:
    """Creates and returns `BACKUP_DIR/name`, or the same folder under
    DATA_DIR when BACKUP_DIR cannot be written to.

    Falling back rather than failing is deliberate: the caller is either
    taking the daily copy or the safety copy that makes a restore undoable,
    and a backup written somewhere unexpected is worth incomparably more than
    no backup at all. DATA_DIR is guaranteed writable -- the database itself
    lives there -- and the warning names the path actually used, so it is
    never a silent substitution.
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

# NOTE: there is deliberately no BASE_CURRENCY setting here. The currency of
# every aggregated figure is a per-request parameter instead (`base_currency`
# / `currency` on the combined net worth, growth, XIRR and expense endpoints,
# defaulting to EUR), and each portfolio carries its own `base_currency`
# column -- so a single global environment variable had nothing left to
# control. One used to exist, read by nothing, which quietly did nothing when
# set.

# URL of the price-feed service, used to enrich holdings with live prices
PRICE_FEED_URL = os.environ.get("PRICE_FEED_URL", "http://price-feed:8001")

# A full database backup upload (Settings -> Restore) shouldn't need to be
# larger than this for a personal-finance SQLite database -- bounds how much
# an uploaded file is read entirely into memory before it's even validated.
MAX_BACKUP_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_BACKUP_UPLOAD_SIZE_BYTES", 200 * 1024 * 1024))
