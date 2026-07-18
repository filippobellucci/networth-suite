"""
Persists, per asset_id, the last uploaded factsheet file plus its parsed
result, as a small folder on local disk:

    {FUND_FILES_DIR}/{asset_id}/source.<ext>       <- the original Excel file, as uploaded
    {FUND_FILES_DIR}/{asset_id}/allocation.json    <- cached parse result + metadata

Uploading again for the same asset_id replaces both files, so there is
always at most one factsheet associated with a given asset (uploading a new
file for an ETF replaces the old one).
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import FUND_FILES_DIR
from .lib import AllocationResult, FundMetadata


def _asset_dir(asset_id: str) -> Path:
    d = FUND_FILES_DIR / asset_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(asset_id: str, filename: str, content: bytes, result: AllocationResult) -> dict:
    d = _asset_dir(asset_id)

    # remove any previously stored source file (extension may differ, e.g. .xls -> .xlsx)
    for existing in d.glob("source.*"):
        existing.unlink()

    ext = Path(filename).suffix or ".xlsx"
    (d / f"source{ext}").write_bytes(content)

    record = {
        "asset_id": asset_id,
        "original_filename": filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "result": result.to_dict(),
    }
    (d / "allocation.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def load(asset_id: str) -> Optional[dict]:
    f = FUND_FILES_DIR / asset_id / "allocation.json"
    if not f.exists():
        return None
    return json.loads(f.read_text())


def delete(asset_id: str) -> bool:
    d = FUND_FILES_DIR / asset_id
    if not d.exists():
        return False
    for f in d.iterdir():
        f.unlink()
    d.rmdir()
    return True


def list_all() -> list:
    records = []
    if not FUND_FILES_DIR.exists():
        return records
    for d in FUND_FILES_DIR.iterdir():
        f = d / "allocation.json"
        if f.exists():
            records.append(json.loads(f.read_text()))
    return records


def source_file_path(asset_id: str) -> Optional[Path]:
    d = FUND_FILES_DIR / asset_id
    matches = list(d.glob("source.*"))
    return matches[0] if matches else None
