import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

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
