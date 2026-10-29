"""
Opening a database written by an older version of the app.

These run on every startup against real user data, which makes them the
highest-consequence code in the repo per line: a migration that drops a
column or blanks a value destroys something no backup taken afterwards can
recover. Each case below is built as a genuinely old schema and then read
back through the ORM, because "the migration ran without raising" is not the
property that matters -- "the data is still there and still readable" is.
"""
from __future__ import annotations

import sqlite3

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def legacy_db(core_modules, tmp_path):
    """Builds a database, then hands back a helper to age its schema."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    path = tmp_path / "legacy.db"

    def build(alterations: list[str] = ()):
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False},
                               poolclass=NullPool)
        core_modules["models"].Base.metadata.create_all(bind=engine)
        engine.dispose()
        raw = sqlite3.connect(path)
        for statement in alterations:
            raw.executescript(statement)
        raw.commit()
        raw.close()
        return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False},
                             poolclass=NullPool)

    return build


def columns_of(engine, table) -> set[str]:
    from sqlalchemy import inspect

    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_a_new_column_is_added_and_existing_rows_stay_readable(core_modules, legacy_db):
    engine = legacy_db(['ALTER TABLE cash_accounts DROP COLUMN archived_at;'])
    with engine.connect() as conn:
        from sqlalchemy import text
        conn.execute(text("INSERT INTO portfolios (id, name, base_currency, archived) "
                          "VALUES ('p1', 'P', 'EUR', 0)"))
        conn.execute(text("INSERT INTO cash_accounts (id, portfolio_id, name, currency, kind) "
                          "VALUES ('c1', 'p1', 'Old account', 'EUR', 'CURRENCY')"))
        conn.commit()

    core_modules["migrate"].run_lightweight_migrations(engine)
    assert "archived_at" in columns_of(engine, "cash_accounts")

    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=engine)()
    account = session.get(core_modules["models"].CashAccount, "c1")
    assert account.name == "Old account"
    assert account.archived_at is None, "never archived, rather than unreadable"
    session.close()


def test_a_new_non_null_column_is_backfilled_with_its_default(core_modules, legacy_db):
    """ALTER TABLE ADD COLUMN leaves existing rows NULL. For a column the
    model declares non-optional, that row then fails schema validation the
    moment it is read back."""
    engine = legacy_db(['ALTER TABLE cash_accounts DROP COLUMN kind;'])
    with engine.connect() as conn:
        from sqlalchemy import text
        conn.execute(text("INSERT INTO portfolios (id, name, base_currency, archived) "
                          "VALUES ('p1', 'P', 'EUR', 0)"))
        conn.execute(text("INSERT INTO cash_accounts (id, portfolio_id, name, currency) "
                          "VALUES ('c1', 'p1', 'Old account', 'EUR')"))
        conn.commit()

    core_modules["migrate"].run_lightweight_migrations(engine)

    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=engine)()
    account = session.get(core_modules["models"].CashAccount, "c1")
    assert account.kind is not None, "an existing row must get the column's default"
    session.close()


def test_running_the_migrations_twice_changes_nothing(core_modules, legacy_db):
    engine = legacy_db([
        'ALTER TABLE assets DROP COLUMN category;',
        "INSERT INTO assets (id, name, asset_class, currency) VALUES ('a1', 'Old asset', 'ETF', 'EUR');",
    ])
    migrate = core_modules["migrate"]
    migrate.run_lightweight_migrations(engine)
    first = columns_of(engine, "assets")
    assert "category" in first
    migrate.run_lightweight_migrations(engine)
    migrate.run_lightweight_migrations(engine)
    assert columns_of(engine, "assets") == first

    from sqlalchemy import text
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM assets WHERE id='a1'")).fetchone()[0] == "Old asset"


def test_cash_transactions_investment_income_kind_migrates_an_old_backup(core_modules, legacy_db):
    """A backup taken before InvestmentIncomeKind existed has no such column
    on cash_transactions. Restoring it (simulated here by building the
    legacy schema and inserting a row the old way) must add the column,
    leave every existing row readable as ordinary income/expense, and be
    safe to run twice -- the exact situation a restored pre-AGE-3 backup is
    in."""
    engine = legacy_db([
        'ALTER TABLE cash_transactions DROP COLUMN investment_income_kind;',
        "INSERT INTO portfolios (id, name, base_currency, archived) VALUES ('p1', 'P', 'EUR', 0);",
        "INSERT INTO cash_accounts (id, portfolio_id, name, currency, kind) "
        "VALUES ('c1', 'p1', 'Old account', 'EUR', 'CURRENCY');",
        "INSERT INTO cash_transactions (id, account_id, entry_date, direction, amount) "
        "VALUES ('t1', 'c1', '2026-01-02', 'INCOME', 42.0);",
    ])
    migrate = core_modules["migrate"]

    migrate.run_lightweight_migrations(engine)
    migrate.run_lightweight_migrations(engine)  # idempotent: a restored backup may be migrated more than once
    assert "investment_income_kind" in columns_of(engine, "cash_transactions")

    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=engine)()
    txn = session.get(core_modules["models"].CashTransaction, "t1")
    assert txn.amount == 42.0, "the pre-existing row is still readable"
    assert txn.investment_income_kind is None, (
        "an old row is never guessed into being a dividend -- that's the user's call, not the migration's"
    )
    session.close()


def test_cash_transactions_import_fingerprint_migrates_an_old_backup(core_modules, legacy_db):
    """A backup taken before CSV import existed has no such column. Restoring
    it must add it, leave every existing row readable, and be safe to run
    twice -- same situation as investment_income_kind above."""
    engine = legacy_db([
        'ALTER TABLE cash_transactions DROP COLUMN import_fingerprint;',
        "INSERT INTO portfolios (id, name, base_currency, archived) VALUES ('p1', 'P', 'EUR', 0);",
        "INSERT INTO cash_accounts (id, portfolio_id, name, currency, kind) "
        "VALUES ('c1', 'p1', 'Old account', 'EUR', 'CURRENCY');",
        "INSERT INTO cash_transactions (id, account_id, entry_date, direction, amount) "
        "VALUES ('t1', 'c1', '2026-01-02', 'INCOME', 42.0);",
    ])
    migrate = core_modules["migrate"]

    migrate.run_lightweight_migrations(engine)
    migrate.run_lightweight_migrations(engine)
    assert "import_fingerprint" in columns_of(engine, "cash_transactions")

    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=engine)()
    txn = session.get(core_modules["models"].CashTransaction, "t1")
    assert txn.amount == 42.0, "the pre-existing row is still readable"
    assert txn.import_fingerprint is None, "a hand-entered row was never touched by CSV import"
    session.close()


def test_import_fingerprint_gets_a_unique_index_that_survives_a_second_migration_run(core_modules, legacy_db):
    """
    The column alone isn't the guarantee: two CSV imports of the same file
    racing each other could both pass the application-side duplicate check
    before either commits. This index is what turns the loser's INSERT into
    an error instead of a silent duplicate -- so it must actually be there,
    and running the migration again must not choke on an index that already
    exists (a restored backup is migrated on every startup, every time).
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    engine = legacy_db([
        "INSERT INTO portfolios (id, name, base_currency, archived) VALUES ('p1', 'P', 'EUR', 0);",
        "INSERT INTO cash_accounts (id, portfolio_id, name, currency, kind) "
        "VALUES ('c1', 'p1', 'Old account', 'EUR', 'CURRENCY');",
    ])
    migrate = core_modules["migrate"]
    migrate.run_lightweight_migrations(engine)
    migrate.run_lightweight_migrations(engine)  # idempotent: must not fail on the already-existing index

    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO cash_transactions (id, account_id, entry_date, direction, amount, import_fingerprint) "
            "VALUES ('t1', 'c1', '2026-01-02', 'EXPENSE', 10.0, 'fp-1')"
        ))
        conn.commit()
        with pytest.raises(IntegrityError):
            conn.execute(text(
                "INSERT INTO cash_transactions (id, account_id, entry_date, direction, amount, import_fingerprint) "
                "VALUES ('t2', 'c1', '2026-01-03', 'EXPENSE', 20.0, 'fp-1')"
            ))
            conn.commit()
        conn.rollback()

        # Two NULL fingerprints (every hand-entered or bank-synced row) must
        # never be treated as "the same" -- SQL NULLs are never equal.
        conn.execute(text(
            "INSERT INTO cash_transactions (id, account_id, entry_date, direction, amount) "
            "VALUES ('t3', 'c1', '2026-01-04', 'EXPENSE', 5.0)"
        ))
        conn.execute(text(
            "INSERT INTO cash_transactions (id, account_id, entry_date, direction, amount) "
            "VALUES ('t4', 'c1', '2026-01-05', 'EXPENSE', 6.0)"
        ))
        conn.commit()


def test_an_up_to_date_database_is_left_alone(core_modules, legacy_db):
    engine = legacy_db([])
    before = {t: columns_of(engine, t) for t in ("assets", "portfolios", "cash_accounts")}
    core_modules["migrate"].run_lightweight_migrations(engine)
    after = {t: columns_of(engine, t) for t in ("assets", "portfolios", "cash_accounts")}
    assert before == after


async def test_the_app_serves_a_migrated_database(api, core_modules, db_engine, feed):
    """The migration having run is not the point; the app reading what it
    produced is."""
    from sqlalchemy import text

    with db_engine.connect() as conn:
        conn.execute(text("INSERT INTO portfolios (id, name, base_currency, archived) "
                          "VALUES ('p-legacy', 'Legacy', 'EUR', 0)"))
        conn.execute(text("INSERT INTO cash_accounts (id, portfolio_id, name, currency, kind) "
                          "VALUES ('c-legacy', 'p-legacy', 'Old', 'EUR', 'CURRENCY')"))
        conn.execute(text("INSERT INTO cash_balance_entries (id, account_id, entry_date, balance) "
                          "VALUES ('b-legacy', 'c-legacy', '2026-01-02', 1234.5)"))
        conn.commit()

    core_modules["migrate"].run_lightweight_migrations(db_engine)

    response = await api.get("/portfolios/p-legacy/snapshot")
    assert response.status_code == 200, response.text[:300]
    assert response.json()["net_worth_base_ccy"] == 1234.5


# ------------------------------------------------- categories, rules and snapshots per portfolio
# The three tables as they were before each portfolio had its own: no
# portfolio_id, and merchant_rules unique on (pattern, match_type) alone.
_SHARED_EXPENSE_SCHEMA = """
DROP TABLE merchant_rules; DROP TABLE budgets; DROP TABLE expense_categories; DROP TABLE networth_snapshots;
CREATE TABLE expense_categories (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, color VARCHAR, created_at DATETIME);
CREATE TABLE budgets (id VARCHAR PRIMARY KEY, category_id VARCHAR NOT NULL UNIQUE REFERENCES expense_categories (id),
    amount FLOAT NOT NULL, currency VARCHAR NOT NULL, created_at DATETIME, over_alerted_month VARCHAR);
CREATE TABLE merchant_rules (id VARCHAR PRIMARY KEY, pattern VARCHAR NOT NULL, match_type VARCHAR(8) NOT NULL,
    category_id VARCHAR REFERENCES expense_categories (id), ignored BOOLEAN NOT NULL, created_at DATETIME,
    updated_at DATETIME, CONSTRAINT uq_merchant_rule_pattern UNIQUE (pattern, match_type));
CREATE TABLE networth_snapshots (id VARCHAR PRIMARY KEY, snapshot_date DATE NOT NULL, currency VARCHAR NOT NULL,
    net_worth FLOAT NOT NULL, invested_total FLOAT NOT NULL, cash_total FLOAT NOT NULL, source VARCHAR NOT NULL,
    created_at DATETIME);
INSERT INTO portfolios (id, name, base_currency, archived, created_at) VALUES
    ('old', 'Old', 'EUR', 0, '2025-01-01 00:00:00'), ('new', 'New', 'EUR', 0, '2026-10-20 00:00:00');
INSERT INTO cash_accounts (id, portfolio_id, name, currency, kind) VALUES
    ('c-old', 'old', 'Old bank', 'EUR', 'CURRENCY'), ('c-new', 'new', 'New bank', 'EUR', 'CURRENCY');
INSERT INTO expense_categories (id, name, color) VALUES
    ('spesa', 'Spesa', '#111111'), ('bar', 'Bar', '#222222'), ('unused', 'Unused', '#333333');
INSERT INTO cash_transactions (id, account_id, category_id, entry_date, direction, amount) VALUES
    ('t-old', 'c-old', 'spesa', '2026-01-10', 'EXPENSE', 50.0),
    ('t-new', 'c-new', 'spesa', '2026-10-21', 'EXPENSE', 20.0),
    ('t-bar', 'c-old', 'bar', '2026-02-10', 'EXPENSE', 5.0);
INSERT INTO budgets (id, category_id, amount, currency, over_alerted_month) VALUES
    ('b-spesa', 'spesa', 300.0, 'EUR', '2026-09');
INSERT INTO merchant_rules (id, pattern, match_type, category_id, ignored) VALUES
    ('r-spesa', 'esselunga', 'EXACT', 'spesa', 0), ('r-ignored', 'bellucci filippo', 'EXACT', NULL, 1);
INSERT INTO networth_snapshots (id, snapshot_date, currency, net_worth, invested_total, cash_total, source) VALUES
    ('s-before', '2026-09-30', 'EUR', 1000.0, 0.0, 1000.0, 'auto'),
    ('s-after', '2026-10-25', 'EUR', 1300.0, 0.0, 1300.0, 'manual');
"""


def _rows(engine, sql):
    from sqlalchemy import text

    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql)).all()]


def test_shared_categories_are_handed_to_the_portfolios_that_use_them(core_modules, legacy_db):
    """
    A category both portfolios' transactions use: the oldest portfolio keeps
    the row (and its id), the other gets a copy with its own budget and rule,
    and its transaction moves to the copy -- so each portfolio's spending by
    category, and its budget, stay exactly what they were.
    """
    engine = legacy_db([_SHARED_EXPENSE_SCHEMA])
    core_modules["migrate"].run_lightweight_migrations(engine)

    cats = _rows(engine, "SELECT portfolio_id, name, color, id FROM expense_categories ORDER BY portfolio_id, name")
    assert [c[:3] for c in cats] == [
        ("new", "Spesa", "#111111"), ("new", "Unused", "#333333"),
        ("old", "Bar", "#222222"), ("old", "Spesa", "#111111"), ("old", "Unused", "#333333"),
    ], "a category goes where it is used; an unused one to every portfolio"
    new_spesa = next(c[3] for c in cats if c[:2] == ("new", "Spesa"))
    assert ("old", "Spesa") == next(c[:2] for c in cats if c[3] == "spesa"), "the oldest portfolio keeps the id"

    assert _rows(engine, "SELECT id, category_id FROM cash_transactions ORDER BY id") == [
        ("t-bar", "bar"), ("t-new", new_spesa), ("t-old", "spesa")]
    assert sorted(_rows(engine, "SELECT category_id, amount, over_alerted_month FROM budgets")) == sorted([
        ("spesa", 300.0, "2026-09"), (new_spesa, 300.0, "2026-09")])
    assert sorted(_rows(engine, "SELECT portfolio_id, pattern, category_id, ignored FROM merchant_rules")) == sorted([
        ("old", "esselunga", "spesa", 0), ("new", "esselunga", new_spesa, 0),
        ("old", "bellucci filippo", None, 1), ("new", "bellucci filippo", None, 1)])


def test_a_combined_snapshot_goes_to_the_only_portfolio_that_held_anything(core_modules, legacy_db):
    """Before the second portfolio had any entry, the sum was the first one's
    alone. After, it can't be split: kept, without a portfolio."""
    engine = legacy_db([_SHARED_EXPENSE_SCHEMA])
    core_modules["migrate"].run_lightweight_migrations(engine)
    assert _rows(engine, "SELECT id, portfolio_id FROM networth_snapshots ORDER BY id") == [
        ("s-after", None), ("s-before", "old")]


def test_merchant_rules_lose_no_row_when_their_constraint_is_rebuilt(core_modules, legacy_db):
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import IntegrityError

    engine = legacy_db([_SHARED_EXPENSE_SCHEMA])
    core_modules["migrate"].run_lightweight_migrations(engine)
    constraints = inspect(engine).get_unique_constraints("merchant_rules")
    assert [c["column_names"] for c in constraints] == [["portfolio_id", "pattern", "match_type"]]
    assert "_merchant_rules_old" not in inspect(engine).get_table_names()

    with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(text("INSERT INTO merchant_rules (id, portfolio_id, pattern, match_type, ignored) "
                              "VALUES ('dup', 'old', 'esselunga', 'EXACT', 1)"))
        conn.rollback()


def test_handing_out_shared_rows_twice_changes_nothing(core_modules, legacy_db):
    """A restored backup is migrated on every startup."""
    engine = legacy_db([_SHARED_EXPENSE_SCHEMA])
    migrate = core_modules["migrate"]
    migrate.run_lightweight_migrations(engine)
    tables = ("expense_categories", "budgets", "merchant_rules", "networth_snapshots", "cash_transactions")
    first = {t: sorted(_rows(engine, f"SELECT * FROM {t}"), key=repr) for t in tables}
    migrate.run_lightweight_migrations(engine)
    assert {t: sorted(_rows(engine, f"SELECT * FROM {t}"), key=repr) for t in tables} == first


def test_shared_rows_wait_for_a_portfolio_to_exist(core_modules, legacy_db):
    """With no portfolio there is nobody to give a category to: it stays as
    it is, and the next startup after a portfolio exists hands it out."""
    from sqlalchemy import text

    engine = legacy_db(["INSERT INTO expense_categories (id, name) VALUES ('lonely', 'Lonely');"])
    migrate = core_modules["migrate"]
    migrate.run_lightweight_migrations(engine)
    assert _rows(engine, "SELECT portfolio_id FROM expense_categories") == [(None,)]

    with engine.connect() as conn:
        conn.execute(text("INSERT INTO portfolios (id, name, base_currency, archived) VALUES ('p1', 'P', 'EUR', 0)"))
        conn.commit()
    migrate.run_lightweight_migrations(engine)
    assert _rows(engine, "SELECT portfolio_id FROM expense_categories") == [("p1",)]


def test_an_existing_database_gets_the_lookup_indexes(core_modules, legacy_db):
    """create_all() never adds an index to a table that already exists, so a
    database from before them gets them from migrate.py -- twice is harmless."""
    from sqlalchemy import inspect

    engine = legacy_db([])
    migrate = core_modules["migrate"]
    migrate.run_lightweight_migrations(engine)
    migrate.run_lightweight_migrations(engine)
    names = {i["name"] for t in ("holding_entries", "cash_accounts", "cash_balance_entries", "cash_transactions")
             for i in inspect(engine).get_indexes(t)}
    assert {"ix_holding_entries_portfolio", "ix_cash_accounts_portfolio", "ix_cash_balance_entries_account",
            "ix_cash_transactions_account_date", "ix_cash_transactions_refund_of"} <= names
