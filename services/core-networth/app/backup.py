"""
Export/restore for core-networth's own SQLite database, used by the
in-app "Download full backup" / "Restore from backup" feature (Settings
page). Complements the existing *automatic* daily backup in scheduler.py --
this is the same idea, triggered on demand and downloadable, plus the
ability to load one back in.

Restore is the dangerous half, so it's deliberately conservative:
  1. Validate the uploaded file BEFORE touching anything live (integrity
     check + expected tables present). Reject and leave the running
     database untouched if it doesn't look right.
  2. Take an automatic safety copy of the *current* database first, into
     the same ./backups directory the daily job already uses (so it's
     already gitignored and already bind-mounted -- no new paths to
     remember to exclude).
  3. Swap the file in, then re-run the same lightweight migration used at
     every startup, so an older backup (missing a column added since) gets
     silently brought up to the current schema instead of erroring.
"""
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import DATA_DIR, DATABASE_URL
from .database import Base, engine
from .migrate import run_lightweight_migrations

BACKUP_DIR = Path("/backups")
DB_PATH = DATA_DIR / "networth.db"

# Only the tables present since the very first version of this app (see
# CHANGELOG: portfolios + assets have existed since point 1, "Full CRUD
# app"). This is deliberately a MINIMAL signature check, not "every table
# in the current schema" -- requiring every current table would mean any
# future schema addition permanently breaks restoring older (but perfectly
# legitimate) backups, which defeats the whole point of re-running
# create_all + migrations after restore below. This check only needs to
# rule out "this is clearly not one of our database files at all".
EXPECTED_TABLES = {"portfolios", "assets"}


class InvalidBackupError(Exception):
    pass


def _require_sqlite():
    if not DATABASE_URL.startswith("sqlite"):
        raise InvalidBackupError("Backup/restore is only supported with the default SQLite backend.")


def export_db_bytes() -> bytes:
    """Returns the current database file's raw bytes. A plain file read is
    fine for export (unlike restore, nothing here is destructive) and
    matches the same technique the existing daily backup already uses."""
    _require_sqlite()
    if not DB_PATH.exists():
        raise InvalidBackupError("No database file found to export yet.")
    return DB_PATH.read_bytes()


def _count_stats(conn: sqlite3.Connection) -> dict:
    """Row counts for the export manifest / restore preview, shared by
    get_stats() (live db) and preview_uploaded_db() (an uploaded db opened
    against a temp file) so the exact same table list can't drift between
    the two call sites (this drifting once caused a real bug -- see
    CHANGELOG.md)."""
    def count(table):
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            return None

    return {
        "portfolios": count("portfolios"),
        "assets": count("assets"),
        "holdings": count("holding_entries"),
        "cash_accounts": count("cash_accounts"),
        "snapshots": count("networth_snapshots"),
    }


def get_stats() -> dict:
    """Quick counts used to build the export manifest and to describe an
    uploaded file's contents in the restore preview."""
    with sqlite3.connect(DB_PATH) as conn:
        return _count_stats(conn)


def _validate_uploaded_db(path: Path) -> None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise InvalidBackupError(f"Not a readable SQLite database: {e}")

    try:
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as e:
            # SQLite only actually validates the file format on the first
            # real query, not at connect() time -- a non-SQLite file (or a
            # corrupt one) opens "successfully" above and only fails here.
            raise InvalidBackupError(f"Not a valid SQLite database: {e}")

        if not result or result[0] != "ok":
            raise InvalidBackupError(f"Database failed integrity check: {result}")

        try:
            existing_tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        except sqlite3.DatabaseError as e:
            raise InvalidBackupError(f"Not a valid SQLite database: {e}")

        missing = EXPECTED_TABLES - existing_tables
        if missing:
            raise InvalidBackupError(
                f"This doesn't look like a Net Worth Suite database -- missing table(s): {', '.join(sorted(missing))}"
            )
    finally:
        conn.close()


def preview_uploaded_db(uploaded_bytes: bytes) -> dict:
    """Validates an uploaded db and returns its stats, WITHOUT touching the
    live database at all -- used to show the user what they're about to
    restore before they confirm."""
    _require_sqlite()
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        tmp.write(uploaded_bytes)
        tmp.flush()
        tmp_path = Path(tmp.name)
        _validate_uploaded_db(tmp_path)
        with sqlite3.connect(tmp_path) as conn:
            return _count_stats(conn)


def restore_db(uploaded_bytes: bytes) -> dict:
    """Validates, safety-backs-up the current db, swaps in the uploaded
    one, re-migrates it to the current schema, and returns its stats.
    Raises InvalidBackupError (caller should turn this into a 400) if the
    uploaded file doesn't check out -- in that case nothing live is touched."""
    _require_sqlite()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".db.tmp", dir=DATA_DIR, delete=False) as tmp:
        tmp.write(uploaded_bytes)
        tmp_path = Path(tmp.name)

    try:
        _validate_uploaded_db(tmp_path)

        # Safety copy of the CURRENT database before overwriting anything,
        # timestamped (not date-only like the daily backup) so multiple
        # restores in the same day don't clobber each other's safety net.
        if DB_PATH.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            safety_dir = BACKUP_DIR / f"pre-restore-{stamp}"
            safety_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(DB_PATH, safety_dir / "networth.db")

        # Release any pooled connections before swapping the file out from
        # under them. New connections opened after this point (including
        # the migration call below) transparently pick up the new file --
        # the Engine is bound to the path, not to an open file handle.
        engine.dispose()

        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_path), str(DB_PATH))

        # Same two calls, same order, as a normal app startup (main.py) --
        # create_all first (in case an older backup predates a whole table
        # that only column-level migration wouldn't add back), then the
        # column-level migration for tables that already exist.
        Base.metadata.create_all(bind=engine)
        run_lightweight_migrations(engine)

        return get_stats()
    finally:
        # If we already moved it, this is a no-op (file no longer at tmp_path).
        tmp_path.unlink(missing_ok=True)
