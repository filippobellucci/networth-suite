import os
from pathlib import Path

# Local folder (mounted as a Docker volume) where the uploaded fund/ETF
# factsheet Excel files are kept -- this is the single source of truth for
# "which file is currently associated with which asset". Re-uploading for
# the same asset_id overwrites the previous file, as requested.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
FUND_FILES_DIR = DATA_DIR / "fund-files"
FUND_FILES_DIR.mkdir(parents=True, exist_ok=True)
