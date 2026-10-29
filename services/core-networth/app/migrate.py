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

Two changes need more than a new column, and run after it every startup:
`_rebuild_merchant_rules` (a table constraint SQLite can only change by
rebuilding the table) and `_give_shared_rows_to_portfolios` (rows from before
expense categories, merchant rules and snapshots belonged to a portfolio).
"""
import logging
import uuid

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

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


def _rebuild_merchant_rules(conn: Connection) -> None:
    """
    Rebuilds merchant_rules when its unique constraint is still the old
    (pattern, match_type) one: rules belong to a portfolio now, and two
    portfolios may each have a rule for the same merchant. SQLite can't alter
    a table constraint, so the table is renamed, created again from the model
    and refilled -- every row and column kept. A no-op once rebuilt.
    """
    constraints = inspect(conn).get_unique_constraints("merchant_rules")
    if any("portfolio_id" in c["column_names"] for c in constraints):
        return
    table = Base.metadata.tables["merchant_rules"]
    old_columns = {c["name"] for c in inspect(conn).get_columns("merchant_rules")}
    columns = ", ".join(f'"{c.name}"' for c in table.columns if c.name in old_columns)
    logger.info("Migrating: rebuilding merchant_rules with a per-portfolio unique constraint")
    conn.execute(text('ALTER TABLE "merchant_rules" RENAME TO "_merchant_rules_old"'))
    table.create(conn)
    conn.execute(text(f'INSERT INTO "merchant_rules" ({columns}) SELECT {columns} FROM "_merchant_rules_old"'))
    conn.execute(text('DROP TABLE "_merchant_rules_old"'))


def _copy_row(conn: Connection, table: str, row, **changes) -> str:
    """Inserts a copy of `row` with a fresh id and `changes` applied; returns the id."""
    values = {**row._mapping, **changes, "id": uuid.uuid4().hex[:12]}
    columns = ", ".join(f'"{k}"' for k in values)
    params = ", ".join(f":{k}" for k in values)
    conn.execute(text(f'INSERT INTO "{table}" ({columns}) VALUES ({params})'), values)
    return values["id"]


def _give_shared_rows_to_portfolios(conn: Connection) -> None:
    """
    Expense categories, merchant rules and net worth snapshots used to be
    shared by every portfolio; each now belongs to one. This hands out the
    rows still without a portfolio -- every row of a database (or a restored
    backup) from before the change, none afterwards, so running it again
    finds nothing to do.

    - A category goes to each portfolio whose transactions use it (to every
      portfolio, if none do). The oldest of those keeps the row, so its id
      stays valid; each other one gets a copy -- with copies of the
      category's budget and merchant rules -- and its transactions move to
      that copy. No transaction loses its category, and every portfolio's
      totals stay what they were.
    - A rule with no category (an ignored merchant) is copied to every
      portfolio.
    - A snapshot summed every portfolio. It goes to the one portfolio that
      held anything on or before its date; when several did, the sum can't
      be split, so it stays without a portfolio -- kept, never shown.
    """
    portfolios = [pid for (pid,) in conn.execute(text("SELECT id FROM portfolios ORDER BY created_at, id"))]
    if not portfolios:
        return

    for category in conn.execute(text("SELECT * FROM expense_categories WHERE portfolio_id IS NULL")).all():
        users = {pid for (pid,) in conn.execute(text(
            "SELECT DISTINCT a.portfolio_id FROM cash_transactions t "
            "JOIN cash_accounts a ON a.id = t.account_id WHERE t.category_id = :c"
        ), {"c": category.id})}
        owner, *others = [p for p in portfolios if p in users] or portfolios
        budgets = conn.execute(text("SELECT * FROM budgets WHERE category_id = :c"), {"c": category.id}).all()
        rules = conn.execute(text(
            "SELECT * FROM merchant_rules WHERE category_id = :c AND portfolio_id IS NULL"
        ), {"c": category.id}).all()
        logger.info("Migrating: expense category %s -> portfolio %s, copied to %d more", category.id, owner, len(others))
        for portfolio_id in others:
            copy_id = _copy_row(conn, "expense_categories", category, portfolio_id=portfolio_id)
            conn.execute(text(
                "UPDATE cash_transactions SET category_id = :copy WHERE category_id = :c "
                "AND account_id IN (SELECT id FROM cash_accounts WHERE portfolio_id = :p)"
            ), {"copy": copy_id, "c": category.id, "p": portfolio_id})
            for budget in budgets:
                _copy_row(conn, "budgets", budget, category_id=copy_id)
            for rule in rules:
                _copy_row(conn, "merchant_rules", rule, category_id=copy_id, portfolio_id=portfolio_id)
        conn.execute(text("UPDATE expense_categories SET portfolio_id = :p WHERE id = :c"), {"p": owner, "c": category.id})
        conn.execute(text(
            "UPDATE merchant_rules SET portfolio_id = :p WHERE category_id = :c AND portfolio_id IS NULL"
        ), {"p": owner, "c": category.id})

    # What is left: ignored merchants, and rules whose category no longer exists.
    for rule in conn.execute(text("SELECT * FROM merchant_rules WHERE portfolio_id IS NULL")).all():
        owner, *others = portfolios
        for portfolio_id in others:
            _copy_row(conn, "merchant_rules", rule, portfolio_id=portfolio_id)
        conn.execute(text("UPDATE merchant_rules SET portfolio_id = :p WHERE id = :r"), {"p": owner, "r": rule.id})

    for snapshot_id, snapshot_date in conn.execute(text(
        "SELECT id, snapshot_date FROM networth_snapshots WHERE portfolio_id IS NULL"
    )).all():
        holders = [pid for (pid,) in conn.execute(text(
            "SELECT portfolio_id FROM holding_entries WHERE entry_date <= :d "
            "UNION SELECT a.portfolio_id FROM cash_balance_entries b "
            "JOIN cash_accounts a ON a.id = b.account_id WHERE b.entry_date <= :d "
            "UNION SELECT a.portfolio_id FROM cash_transactions t "
            "JOIN cash_accounts a ON a.id = t.account_id WHERE t.entry_date <= :d"
        ), {"d": snapshot_date})]
        if len(portfolios) == 1:
            holders = portfolios
        if len(holders) == 1:
            conn.execute(text("UPDATE networth_snapshots SET portfolio_id = :p WHERE id = :s"),
                         {"p": holders[0], "s": snapshot_id})
        else:
            logger.warning("Snapshot %s of %s sums %d portfolios: left unassigned", snapshot_id, snapshot_date, len(holders))


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

        if "merchant_rules" in existing_tables:
            _rebuild_merchant_rules(conn)
        _give_shared_rows_to_portfolios(conn)
