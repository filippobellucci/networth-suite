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


def run_lightweight_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        # One-off renames: must run before the generic add-missing-columns
        # pass below, so the old column's data is preserved under the new name
        # instead of the new column being added empty alongside the old one.
        if "assets" in existing_tables:
            cols = {c["name"] for c in inspect(conn).get_columns("assets")}
            _rename_column_if_needed(conn, "assets", "instrument_type", "category", cols)

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
