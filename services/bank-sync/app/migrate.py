"""
Adds columns a newer models.py has to a database created by an older one.

Base.metadata.create_all() only creates *missing tables* -- a table that
already exists is left exactly as it was, so a column added to a model later
simply isn't there on an existing install, and the first query touching it
fails. Same approach as core-networth's migrate.py: each missing column is
added with `ALTER TABLE ... ADD COLUMN`, and existing rows are backfilled
with the column's scalar default so a nullable=False column never reads back
NULL.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .database import Base

logger = logging.getLogger("bank-sync.migrate")


def run_lightweight_migrations(engine: Engine) -> None:
    existing_tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table_name, table in Base.metadata.tables.items():
            if table_name not in existing_tables:
                continue  # brand new -- create_all() already made it whole
            existing_columns = {c["name"] for c in inspect(conn).get_columns(table_name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {col_type}'
                logger.info("Migrating: %s", ddl)
                conn.execute(text(ddl))
                default = column.default
                if default is not None and getattr(default, "is_scalar", False):
                    conn.execute(
                        text(f'UPDATE "{table_name}" SET "{column.name}" = :val WHERE "{column.name}" IS NULL'),
                        {"val": default.arg},
                    )
