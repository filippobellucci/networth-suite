"""
Lightweight auto-migration for the SQLite database.

`Base.metadata.create_all()` only creates tables that don't exist yet -- it
never alters existing tables, so adding a new column to a model (like
`CashAccount.kind`) does nothing for a database that was already
created before that column existed, and every query touching it then fails
with "no such column".

This is a single-user, locally-run app with no separate migrations tool
(Alembic would be overkill here), so instead: on startup, compare each
model's columns against what's actually in the database and add whatever
is missing with `ALTER TABLE ... ADD COLUMN`. New columns must be nullable
(or have a server-side default) for this to work with existing rows, which
holds for everything added so far.

The same gap applies to indexes: `create_all()` only adds them to a table it
creates from scratch, never to one that already exists. `_EXTRA_INDEXES`
below is for the rare case a change needs one on an existing table --
written as plain, idempotent DDL (`CREATE ... IF NOT EXISTS`), run every
startup like the column loop.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .database import Base

logger = logging.getLogger("core-networth.migrate")

# (table, DDL) run every startup, after the column loop so a column it
# depends on is guaranteed to exist first. Each statement must be safe to
# run on a database that already has it -- "IF NOT EXISTS" -- since a
# restored backup may be migrated more than once.
#
# cash_transactions.import_fingerprint: CSV import (routers/expenses.py)
# checks this ahead of inserting to skip a row already imported, but two
# imports of the same file racing each other could both pass that check
# before either commits. This unique index turns the second INSERT into an
# IntegrityError instead of a silent duplicate -- partial, so the many
# existing rows with import_fingerprint NULL (everything not from a CSV
# import) never collide with each other.
_EXTRA_INDEXES = [
    (
        "cash_transactions",
        'CREATE UNIQUE INDEX IF NOT EXISTS "uq_cash_transactions_import_fingerprint" '
        'ON "cash_transactions" ("account_id", "import_fingerprint") '
        "WHERE import_fingerprint IS NOT NULL",
    ),
]


def run_lightweight_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
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

        for table_name, ddl in _EXTRA_INDEXES:
            if table_name not in existing_tables:
                # create_all() runs before this function every time it's
                # called (see main.py), so the table already exists by now
                # unless the caller skipped that step -- same defensive
                # guard as the column loop above, for the same reason.
                continue
            logger.info("Migrating: %s", ddl)
            conn.execute(text(ddl))
