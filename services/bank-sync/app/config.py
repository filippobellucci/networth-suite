import os
import sys
from pathlib import Path

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

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR}/bank_sync.db")

# Where the main app's core-networth service lives -- this is what actually
# receives the auto-captured transactions, via the same
# POST /cash-accounts/{id}/transactions endpoint the Transactions page uses.
CORE_SERVICE_URL = os.environ.get("CORE_SERVICE_URL", "http://core-networth:8000")

# --- Enable Banking application credentials ---
# Created in their Control Panel (enablebanking.com/cp/applications). The
# private key is the PEM file you generated alongside your app's public
# certificate -- keep it out of version control, mount it read-only.
ENABLE_BANKING_APP_ID = os.environ.get("ENABLE_BANKING_APP_ID", "")
ENABLE_BANKING_PRIVATE_KEY_PATH = os.environ.get(
    "ENABLE_BANKING_PRIVATE_KEY_PATH", "/secrets/enable_banking_private_key.pem"
)
ENABLE_BANKING_BASE_URL = os.environ.get("ENABLE_BANKING_BASE_URL", "https://api.enablebanking.com")

# The address YOUR OWN BROWSER can reach this service at, used to build the
# redirect_url each bank sends you back to after login. Must exactly match
# (scheme + host + port) what's reachable when you click "Authorize" -- see
# README.md. Enable Banking requires HTTPS here for production applications
# (sandbox tolerates HTTP).
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8003").rstrip("/")

# Where links.yaml lives -- see links.example.yaml for the format. Re-read
# on every startup so editing the file and restarting the container is
# enough to add/change a link.
LINKS_CONFIG_PATH = os.environ.get("LINKS_CONFIG_PATH", str(DATA_DIR / "links.yaml"))

# How far back to ask for transaction history the first time a link is
# authorized, and how long the bank's consent should stay valid before you
# have to re-authorize (PSD2 caps this -- 90 days is the common maximum
# banks honor, ask for less and some banks may grant it, ask for more and
# most will silently cap it anyway).
MAX_HISTORICAL_DAYS = int(os.environ.get("MAX_HISTORICAL_DAYS", "90"))
ACCESS_VALID_DAYS = int(os.environ.get("ACCESS_VALID_DAYS", "90"))

# How often the background sync loop checks every ACTIVE link for new
# transactions. Independent of ACCESS_VALID_DAYS -- this is just "how often
# do we poll", not "how long is the bank consent valid for".
SYNC_INTERVAL_HOURS = int(os.environ.get("SYNC_INTERVAL_HOURS", "6"))

# How long a card payment the bank still reports as pending keeps being
# re-checked for its booked version (final amount, MCC) before this service
# stops waiting and treats what it has as final. Most settle within a few
# days; hotel and car-rental holds can take weeks.
PENDING_TRACK_DAYS = int(os.environ.get("PENDING_TRACK_DAYS", "30"))

# Where the daily copy of this service's data goes (see backup.py), and the
# safety copy taken before a restore. A bind-mounted host folder in
# docker-compose.yml, like core-networth's and geo-allocation's; without one
# it defaults to a folder inside DATA_DIR, which is at least persistent.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(DATA_DIR / "backups")))
MAX_BACKUP_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_BACKUP_UPLOAD_SIZE_BYTES", 200 * 1024 * 1024))

# How many days of daily/pre-restore copies to keep as-is before thinning
# older ones down to one per calendar month (see shared/backup_retention.py).
# 0 or negative still always keeps the single most recent copy.
BACKUP_RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "30"))
