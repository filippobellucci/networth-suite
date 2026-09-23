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


def test_a_renamed_column_keeps_its_data(core_modules, legacy_db):
    """`instrument_type` became `category`. Adding the new column beside the
    old one instead of renaming it would silently blank every STOCK/BOND tag
    the user had set."""
    engine = legacy_db([
        'ALTER TABLE assets DROP COLUMN category;',
        'ALTER TABLE assets ADD COLUMN instrument_type VARCHAR;',
        "INSERT INTO assets (id, name, asset_class, currency, instrument_type) "
        "VALUES ('a1', 'Old asset', 'ETF', 'EUR', 'STOCK');",
    ])
    core_modules["migrate"].run_lightweight_migrations(engine)

    assert "category" in columns_of(engine, "assets")
    assert "instrument_type" not in columns_of(engine, "assets")
    with engine.connect() as conn:
        from sqlalchemy import text
        row = conn.execute(text("SELECT category FROM assets WHERE id='a1'")).fetchone()
    assert row[0] == "STOCK", "the tag must survive the rename, not be blanked"


def test_a_dropped_column_lets_new_rows_insert(core_modules, legacy_db):
    """`status_code` was always written as 200 and never read. It cannot just
    leave the model: on an existing database the column is still NOT NULL, so
    every new idempotency key would fail to insert."""
    engine = legacy_db([
        "ALTER TABLE idempotency_keys ADD COLUMN status_code INTEGER NOT NULL DEFAULT 200;",
    ])
    core_modules["migrate"].run_lightweight_migrations(engine)
    assert "status_code" not in columns_of(engine, "idempotency_keys")

    from sqlalchemy.orm import sessionmaker

    models = core_modules["models"]
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(models.IdempotencyKey(key="k1", endpoint="test", response_body="{}"))
    session.commit()
    assert session.query(models.IdempotencyKey).count() == 1
    session.close()


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
        'ALTER TABLE assets ADD COLUMN instrument_type VARCHAR;',
        "INSERT INTO assets (id, name, asset_class, currency, instrument_type) "
        "VALUES ('a1', 'Old asset', 'ETF', 'EUR', 'BOND');",
    ])
    migrate = core_modules["migrate"]
    migrate.run_lightweight_migrations(engine)
    first = columns_of(engine, "assets")
    migrate.run_lightweight_migrations(engine)
    migrate.run_lightweight_migrations(engine)
    assert columns_of(engine, "assets") == first

    from sqlalchemy import text
    with engine.connect() as conn:
        assert conn.execute(text("SELECT category FROM assets WHERE id='a1'")).fetchone()[0] == "BOND"


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
