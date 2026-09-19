"""
Appends every transaction JSON Enable Banking sends -- one row per
transaction, across every linked bank/institution -- to a single audit CSV
(DATA_DIR/transactions_log.csv). Purely additive and independent of what
sync.py decides to do with a transaction (create it in core-networth, skip
it as zero-amount, etc.): this is a raw record of what the bank actually
sent, not a mirror of the app's own business logic.

Columns aren't fixed up front. Different banks don't necessarily send the
same fields, and hand-picking a column list risks silently dropping
whatever wasn't anticipated -- instead, each transaction's JSON is
flattened (nested objects become dotted column names, e.g.
transaction_amount.amount; lists are joined into one pipe-separated
string), and the header grows the first time a field is seen. Cheap at
personal-finance transaction volumes.
"""
import csv
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR

logger = logging.getLogger("bank-sync.csv_log")

CSV_PATH = DATA_DIR / "transactions_log.csv"

# Always the first two columns, regardless of what the bank's JSON contains.
FIXED_LEADING_COLUMNS = ["institution", "logged_at"]


def _flatten(obj: Any, parent_key: str = "", sep: str = ".") -> dict:
    items: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
            items.update(_flatten(v, new_key, sep))
    elif isinstance(obj, list):
        parts = [str(_flatten(v)) if isinstance(v, (dict, list)) else str(v) for v in obj]
        items[parent_key] = " | ".join(parts)
    else:
        items[parent_key] = obj
    return items


def _atomic_write(rows_writer) -> None:
    """Writes into a temp file in the same directory, then atomically
    replaces CSV_PATH -- so a concurrent GET /transactions-log.csv (served
    via FileResponse, with no coordination of its own) can never observe a
    truncated/partial file mid-rewrite, only the old version or the new one
    in full."""
    fd, tmp_path = tempfile.mkstemp(dir=CSV_PATH.parent, prefix=".transactions_log.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            rows_writer(f)
        os.replace(tmp_path, CSV_PATH)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def log_transaction(institution: str, raw_transaction: dict) -> None:
    """Appends one row for `raw_transaction` -- the exact JSON object Enable
    Banking returned for it -- tagged with which link/institution it came
    from. Called once per genuinely new transaction (same dedup lifecycle
    as SyncedTransaction in sync.py), not once per sync cycle it happens to
    still be in the fetched date range."""
    row = {"institution": institution, "logged_at": datetime.now(timezone.utc).isoformat()}
    row.update(_flatten(raw_transaction))

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = CSV_PATH.is_file()
    existing_header: list[str] = []
    existing_rows: list[dict] = []

    if file_exists:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            existing_header = reader.fieldnames or []
            existing_rows = list(reader)

    new_columns = [c for c in row.keys() if c not in existing_header]

    if not file_exists:
        header = FIXED_LEADING_COLUMNS + [c for c in row.keys() if c not in FIXED_LEADING_COLUMNS]

        def _write(f):
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerow(row)

        _atomic_write(_write)
        return

    if new_columns:
        # A field never seen before -- widen the header and rewrite the
        # whole file, padding every earlier row with blanks for the new
        # column(s), rather than dropping data the bank actually sent.
        header = existing_header + new_columns

        def _write(f):
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for r in existing_rows:
                writer.writerow(r)
            writer.writerow(row)

        _atomic_write(_write)
        logger.info("transactions_log.csv: new column(s) seen, header widened: %s", new_columns)
        return

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=existing_header)
        writer.writerow(row)
