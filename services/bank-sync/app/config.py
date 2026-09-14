import os
from pathlib import Path

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
