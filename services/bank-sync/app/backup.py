"""
Export/restore of this service's own data, for the gateway's combined backup:

    bank-sync.zip
    ├── bank_sync.db           (links + the ledger of what was already synced)
    └── transactions_log.csv   (the raw audit log, when there is one)

The database matters more than it looks: SyncedTransaction is what stops a
sync from creating the same transaction twice. Lose it and the next sync
re-captures the whole fetch window -- up to MAX_HISTORICAL_DAYS -- as
duplicates of what Net Worth Suite already holds.

Same approach as core-networth's backup.py: SQLite's own backup API for a
consistent copy of the live file, a validation pass before anything live is
touched, a safety copy of the current data first, then create_all + the
column migrations so an older backup comes back at the current schema.
"""
import csv
import io
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

from .config import BACKUP_DIR, BACKUP_RETENTION_DAYS, DATA_DIR, DATABASE_URL
from .csv_log import CSV_PATH
from .database import Base, engine
from .migrate import run_lightweight_migrations
from shared.backup_retention import rotate_backups

logger = logging.getLogger("bank-sync.backup")

DB_NAME = "bank_sync.db"
CSV_NAME = "transactions_log.csv"
# The two tables this service has had since its first version -- a minimal
# "is this one of ours" check, so a backup taken before a newer table was
# added still restores.
EXPECTED_TABLES = {"bank_links", "synced_transactions"}


class InvalidBackupError(Exception):
    pass


def _db_path() -> Path:
    if not DATABASE_URL.startswith("sqlite:///"):
        raise InvalidBackupError("Backup/restore is only supported with the default SQLite backend.")
    return Path(DATABASE_URL.removeprefix("sqlite:///"))


def consistent_copy(source: Path, destination: Path) -> None:
    """A read snapshot via SQLite's backup API -- a plain file copy can catch
    the file mid-transaction and produce a backup that only turns out to be
    corrupt when it's needed."""
    source_conn = sqlite3.connect(source)
    dest_conn = sqlite3.connect(destination)
    try:
        with dest_conn:
            source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()


def backup_target(name: str) -> Path:
    """BACKUP_DIR/name, or the same under DATA_DIR if BACKUP_DIR can't be
    written -- a backup somewhere unexpected beats no backup."""
    try:
        target = BACKUP_DIR / name
        target.mkdir(parents=True, exist_ok=True)
        return target
    except OSError as e:
        fallback = DATA_DIR / "backups" / name
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning("BACKUP_DIR %s not writable (%s) -- using %s instead", BACKUP_DIR, e, fallback)
        return fallback


def _copy_to(folder: Path) -> None:
    db = _db_path()
    if db.exists():
        consistent_copy(db, folder / DB_NAME)
    if CSV_PATH.is_file():
        shutil.copy2(CSV_PATH, folder / CSV_NAME)


def export_bytes() -> bytes:
    db = _db_path()
    if not db.exists():
        raise InvalidBackupError("No database file found to export yet.")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        _copy_to(folder)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in (DB_NAME, CSV_NAME):
                if (folder / name).exists():
                    zf.write(folder / name, name)
        return buf.getvalue()


def _stats_for(db: Path, csv_bytes: bytes | None) -> dict:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        def count(table):
            try:
                return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                return None

        stats = {"bank_links": count("bank_links"), "synced_transactions": count("synced_transactions")}
    finally:
        conn.close()
    # Rows, not lines: a field can legitimately contain a newline.
    if csv_bytes is None:
        stats["audit_log_rows"] = None
    else:
        rows = sum(1 for _ in csv.reader(io.StringIO(csv_bytes.decode("utf-8", "replace"))))
        stats["audit_log_rows"] = max(0, rows - 1)  # minus the header
    return stats


def get_stats() -> dict:
    db = _db_path()
    if not db.exists():
        return {"bank_links": 0, "synced_transactions": 0, "audit_log_rows": None}
    return _stats_for(db, CSV_PATH.read_bytes() if CSV_PATH.is_file() else None)


def _read_archive(uploaded: bytes) -> tuple[bytes, bytes | None]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(uploaded))
    except zipfile.BadZipFile as e:
        raise InvalidBackupError(f"Not a valid bank-sync backup: {e}")
    names = zf.namelist()
    if DB_NAME not in names:
        raise InvalidBackupError(f"Not a bank-sync backup: {DB_NAME} is missing")
    return zf.read(DB_NAME), (zf.read(CSV_NAME) if CSV_NAME in names else None)


def _validate_db(path: Path) -> None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise InvalidBackupError(f"Not a readable SQLite database: {e}")
    try:
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError as e:
            raise InvalidBackupError(f"Not a valid SQLite database: {e}")
        if not result or result[0] != "ok":
            raise InvalidBackupError(f"Database failed integrity check: {result}")
        missing = EXPECTED_TABLES - tables
        if missing:
            raise InvalidBackupError(f"Not a bank-sync database -- missing table(s): {', '.join(sorted(missing))}")
    finally:
        conn.close()


def preview(uploaded: bytes) -> dict:
    db_bytes, csv_bytes = _read_archive(uploaded)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / DB_NAME
        path.write_bytes(db_bytes)
        _validate_db(path)
        return _stats_for(path, csv_bytes)


def restore(uploaded: bytes) -> dict:
    """
    Validates the archive, keeps a safety copy of the current data, swaps
    the backup in and brings it to the current schema. Nothing live is
    touched unless the archive checks out. The caller holds the sync lock,
    so no sync cycle writes to the database while it's being replaced.

    An archive without an audit log leaves the current one in place rather
    than deleting it: it's an append-only record, not state to roll back.
    """
    db_bytes, csv_bytes = _read_archive(uploaded)
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".db.tmp", dir=db.parent, delete=False) as tmp:
        tmp.write(db_bytes)
        tmp_path = Path(tmp.name)
    try:
        _validate_db(tmp_path)
        if db.exists() or CSV_PATH.is_file():
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            pre_restore_dir = backup_target(f"pre-restore-{stamp}")
            _copy_to(pre_restore_dir)
            rotate_backups(pre_restore_dir.parent, BACKUP_RETENTION_DAYS)

        engine.dispose()
        shutil.move(str(tmp_path), str(db))
        Base.metadata.create_all(bind=engine)
        run_lightweight_migrations(engine)

        if csv_bytes is not None:
            with tempfile.NamedTemporaryFile(dir=CSV_PATH.parent, prefix=".transactions_log.", delete=False) as t:
                t.write(csv_bytes)
            Path(t.name).replace(CSV_PATH)
        return get_stats()
    finally:
        tmp_path.unlink(missing_ok=True)


def maybe_run_daily_backup() -> None:
    """Once per calendar day: BACKUP_DIR/<today>/ gets a copy of the database
    and the audit log, then old daily/pre-restore folders are rotated (see
    shared.backup_retention). A day the service was off simply has none."""
    try:
        db = _db_path()
        if not db.exists():
            return
        today = backup_target(date.today().isoformat())
        if not (today / DB_NAME).exists():
            _copy_to(today)
            logger.info("Backed up bank-sync data to %s", today)
        rotate_backups(today.parent, BACKUP_RETENTION_DAYS)
    except Exception as e:  # a backup failing must never stop syncing
        logger.warning("Daily backup failed: %s", e)
