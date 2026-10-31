"""
Appends every transaction JSON Enable Banking sends -- one row per
transaction, across every linked bank/institution -- to the audit log in
DATA_DIR/audit-log/. Purely additive and independent of what sync.py decides
to do with a transaction (create it in core-networth, skip it as zero-amount,
etc.): this is a raw record of what the bank actually sent, not a mirror of
the app's own business logic. It stays on this machine, in clear text, and is
not part of any backup.

The log is a numbered series of CSV files: rows go to the highest-numbered
`transactions_log-NNNN.csv` until it reaches AUDIT_LOG_MAX_BYTES; then it is
closed, compressed to `transactions_log-NNNN.zip` and the next number is
started. Closed files are kept, all of them.

Columns aren't fixed up front. Different banks don't necessarily send the
same fields, and hand-picking a column list risks silently dropping
whatever wasn't anticipated -- instead, each transaction's JSON is
flattened (nested objects become dotted column names, e.g.
transaction_amount.amount; lists are joined into one pipe-separated
string), and a file's header grows the first time a field is seen in it.
"""
import csv
import logging
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AUDIT_LOG_MAX_BYTES, DATA_DIR

logger = logging.getLogger("bank-sync.csv_log")

AUDIT_LOG_DIR = DATA_DIR / "audit-log"
# The single, never-rotated log of earlier versions; moved into AUDIT_LOG_DIR
# as the next file of the series the first time a row is logged.
LEGACY_CSV_PATH = DATA_DIR / "transactions_log.csv"
_SEGMENT = re.compile(r"transactions_log-(\d{4,})\.(csv|zip)")

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


def _segment(number: int, kind: str) -> Path:
    return AUDIT_LOG_DIR / f"transactions_log-{number:04d}.{kind}"


def _numbers() -> dict[int, set[str]]:
    """Every file of the series in AUDIT_LOG_DIR: number -> {"csv", "zip"}."""
    found: dict[int, set[str]] = {}
    if AUDIT_LOG_DIR.is_dir():
        for p in AUDIT_LOG_DIR.iterdir():
            m = _SEGMENT.fullmatch(p.name)
            if m:
                found.setdefault(int(m.group(1)), set()).add(m.group(2))
    return found


def current_log() -> Path | None:
    """The CSV being written now, or None before the first row."""
    found = _numbers()
    if found:
        last = max(found)
        if found[last] == {"csv"}:
            return _segment(last, "csv")
    return LEGACY_CSV_PATH if LEGACY_CSV_PATH.is_file() else None


def _replace_atomically(target: Path, write) -> None:
    """Writes into a temp file next to `target`, then renames it over
    `target` -- so a concurrent GET /transactions-log.csv (a FileResponse,
    with no coordination of its own) never observes a half-written file,
    and a crash never leaves one."""
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp")
    os.close(fd)
    try:
        write(Path(tmp_path))
        os.replace(tmp_path, target)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _close(number: int) -> None:
    """Compresses file `number` of the series and removes the CSV. The zip is
    complete before the CSV goes, so an interruption leaves both, and the
    next call simply closes it again."""
    csv_path = _segment(number, "csv")

    def write(tmp: Path) -> None:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(csv_path, csv_path.name)

    _replace_atomically(_segment(number, "zip"), write)
    csv_path.unlink()
    logger.info("Audit log %s closed and compressed", csv_path.name)


def _file_for_next_row() -> Path:
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    found = _numbers()
    last = max(found, default=0)
    if LEGACY_CSV_PATH.is_file():
        last += 1
        os.replace(LEGACY_CSV_PATH, _segment(last, "csv"))
        found[last] = {"csv"}
        logger.info("Audit log moved into %s as %s", AUDIT_LOG_DIR, _segment(last, "csv").name)
    if last == 0:
        return _segment(1, "csv")
    kinds = found[last]
    if "csv" in kinds and ("zip" in kinds or _segment(last, "csv").stat().st_size >= AUDIT_LOG_MAX_BYTES):
        _close(last)
        return _segment(last + 1, "csv")
    return _segment(last, "csv") if "csv" in kinds else _segment(last + 1, "csv")


def log_transaction(institution: str, raw_transaction: dict) -> None:
    """Appends one row for `raw_transaction` -- the exact JSON object Enable
    Banking returned for it -- tagged with which link/institution it came
    from. Called once per genuinely new transaction (same dedup lifecycle
    as SyncedTransaction in sync.py), not once per sync cycle it happens to
    still be in the fetched date range."""
    row = {"institution": institution, "logged_at": datetime.now(timezone.utc).isoformat()}
    row.update(_flatten(raw_transaction))
    path = _file_for_next_row()

    if not path.is_file():
        header = FIXED_LEADING_COLUMNS + [c for c in row if c not in FIXED_LEADING_COLUMNS]

        def write_new(tmp: Path) -> None:
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=header)
                writer.writeheader()
                writer.writerow(row)

        _replace_atomically(path, write_new)
        return

    # Only the header row: the rows themselves are needed only on the rare
    # widening path below.
    with open(path, newline="", encoding="utf-8") as f:
        existing_header = next(csv.reader(f), [])

    new_columns = [c for c in row if c not in existing_header]
    if new_columns:
        # A field never seen before -- widen the header and rewrite the
        # file, padding every earlier row with blanks for the new column(s),
        # rather than dropping data the bank actually sent. Streamed row by
        # row: a file can be up to AUDIT_LOG_MAX_BYTES.
        header = existing_header + new_columns

        def write_widened(tmp: Path) -> None:
            with open(path, newline="", encoding="utf-8") as src, open(tmp, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=header)
                writer.writeheader()
                writer.writerows(csv.DictReader(src))
                writer.writerow(row)

        _replace_atomically(path, write_widened)
        logger.info("%s: new column(s) seen, header widened: %s", path.name, new_columns)
        return

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=existing_header)
        writer.writerow(row)
