"""
Lightweight auto-migration for the SQLite database.

`Base.metadata.create_all()` only creates tables that don't exist yet -- it
never alters existing tables, so adding a new column to a model (like
`Asset.instrument_type`) does nothing for a database that was already
created before that column existed, and every query touching it then fails
with "no such column".

This is a single-user, locally-run app with no separate migrations tool
(Alembic would be overkill here), so instead: on startup, compare each
model's columns against what's actually in the database and add whatever
is missing with `ALTER TABLE ... ADD COLUMN`. New columns must be nullable
(or have a server-side default) for this to work with existing rows, which
holds for everything added so far.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from .database import Base

logger = logging.getLogger("core-networth.migrate")


def _rename_column_if_needed(conn, table_name: str, old_name: str, new_name: str, existing_columns: set) -> None:
    """SQLite (3.25+, bundled with Python 3.12+) supports RENAME COLUMN directly.
    Used for the one-off Asset.instrument_type -> Asset.category rename so
    existing STOCK/BOND tags aren't lost (a plain ADD COLUMN would leave the
    old data stranded in a column nothing reads anymore)."""
    if old_name in existing_columns and new_name not in existing_columns:
        ddl = f'ALTER TABLE "{table_name}" RENAME COLUMN "{old_name}" TO "{new_name}"'
        logger.info("Migrating: %s", ddl)
        conn.execute(text(ddl))


def _drop_idempotency_status_code(conn, existing_tables: set) -> None:
    """
    One-off drop of `idempotency_keys.status_code`, which was always written
    as 200 and never read back. It can't just be removed from the model: on a
    database created before this change the column is still there and still
    NOT NULL, so every new idempotency row would fail to insert.

    SQLite's own DROP COLUMN (3.35+) handles it in place. If this SQLite build
    is older, the table is simply recreated empty instead -- its contents are
    disposable by design (retry keys older than IDEMPOTENCY_TTL_HOURS are
    pruned anyway, and losing them at most means a retry within that window
    re-runs instead of replaying its stored response).
    """
    if "idempotency_keys" not in existing_tables:
        return
    columns = {c["name"] for c in inspect(conn).get_columns("idempotency_keys")}
    if "status_code" not in columns:
        return

    try:
        logger.info("Migrating: dropping unused column idempotency_keys.status_code")
        conn.execute(text('ALTER TABLE "idempotency_keys" DROP COLUMN "status_code"'))
    except OperationalError:
        logger.info("DROP COLUMN unsupported here -- recreating idempotency_keys instead")
        conn.execute(text('DROP TABLE "idempotency_keys"'))
        Base.metadata.tables["idempotency_keys"].create(bind=conn)


def run_lightweight_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        # One-off renames/drops: must run before the generic add-missing-columns
        # pass below, so the old column's data is preserved under the new name
        # instead of the new column being added empty alongside the old one.
        if "assets" in existing_tables:
            cols = {c["name"] for c in inspect(conn).get_columns("assets")}
            _rename_column_if_needed(conn, "assets", "instrument_type", "category", cols)
        _drop_idempotency_status_code(conn, existing_tables)

        for table_name, table in Base.metadata.tables.items():
            if table_name not in existing_tables:
                # Brand new table -- create_all() already handled it.
                continue

            existing_columns = {col["name"] for col in inspect(conn).get_columns(table_name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue

                col_type = column.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {col_type}'
                logger.info("Migrating: %s", ddl)
                conn.execute(text(ddl))

                # A plain `ALTER TABLE ... ADD COLUMN` leaves existing rows
                # NULL in the new column -- fine for columns the model marks
                # Optional, but if the model has a scalar Python-side
                # `default=...` (e.g. a new nullable=False column), backfill
                # existing rows with it now instead of leaving them NULL and
                # failing schema validation the moment they're read back out.
                default = column.default
                if default is not None and getattr(default, "is_scalar", False):
                    backfill_ddl = f'UPDATE "{table_name}" SET "{column.name}" = :val WHERE "{column.name}" IS NULL'
                    logger.info("Backfilling default for %s.%s = %r", table_name, column.name, default.arg)
                    conn.execute(text(backfill_ddl), {"val": default.arg})
