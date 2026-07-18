import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", f"sqlite:///{DATA_DIR}/networth.db"
)

# Base currency used for all aggregated/converted values shown in the UI
BASE_CURRENCY = os.environ.get("BASE_CURRENCY", "EUR")

# URL of the price-feed service, used to enrich holdings with live prices
PRICE_FEED_URL = os.environ.get("PRICE_FEED_URL", "http://price-feed:8001")
