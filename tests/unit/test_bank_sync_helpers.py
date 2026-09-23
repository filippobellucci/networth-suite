"""
bank-sync's pure helpers.

The capture loop itself needs a bank, but these three pieces do not, and each
one of them has silently wedged automatic capture before:

  * an unusable date meant core rejected the transaction, so it was never
    marked synced, so the watermark never advanced past it, so the link
    stopped capturing anything new -- permanently, and with nothing on screen
    to say so;
  * a malformed optional YAML file took the whole service down, because the
    parse was unguarded inside a function that runs at the start of every
    sync cycle and inside the bank authorisation callback;
  * the audit CSV re-read and re-parsed every row it already held just to
    learn its own column names, once per logged transaction.
"""
from __future__ import annotations

import csv
import importlib
from datetime import date, timedelta

import pytest

from service_loader import service_module

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- MCC mapping
@pytest.fixture
def mcc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    module = service_module("bank_app", "mcc_categories")
    return module


def write_mapping(mcc, tmp_path, monkeypatch, text: str) -> None:
    """Points the module at a file this test owns.

    `raising=True` (the default) on purpose: if the constant is ever renamed,
    this fails loudly instead of quietly patching an attribute nothing reads
    and leaving every assertion below passing for the wrong reason.
    """
    path = tmp_path / "mcc_categories.yaml"
    path.write_text(text)
    monkeypatch.setattr(mcc, "MCC_CONFIG_PATH", path)


def test_a_valid_mapping_is_read(mcc, tmp_path, monkeypatch):
    write_mapping(mcc, tmp_path, monkeypatch,
                  'mcc_mappings:\n  "5411": Groceries\n  "5812": Restaurants\n')
    mapping = mcc.load_mcc_mapping()
    assert mapping == {"5411": "Groceries", "5812": "Restaurants"}


def test_a_numeric_code_is_normalised_to_a_string(mcc, tmp_path, monkeypatch):
    """YAML parses a bare 5411 as an int; the bank sends it as a string."""
    write_mapping(mcc, tmp_path, monkeypatch, "mcc_mappings:\n  5411: Groceries\n")
    assert mcc.load_mcc_mapping() == {"5411": "Groceries"}


def test_a_malformed_mapping_file_degrades_to_no_categorisation(mcc, tmp_path, monkeypatch):
    """One mistyped line in an entirely optional file used to stop all
    syncing and turn authorising a bank into a 500."""
    write_mapping(mcc, tmp_path, monkeypatch, "mcc_mappings:\n  - [unclosed\n   bad: : :\n")
    assert mcc.load_mcc_mapping() == {}, "an unreadable file must read as empty, not raise"


def test_a_file_that_is_not_a_mapping_is_ignored(mcc, tmp_path, monkeypatch):
    write_mapping(mcc, tmp_path, monkeypatch, "- just\n- a\n- list\n")
    assert mcc.load_mcc_mapping() == {}


def test_mcc_mappings_holding_the_wrong_type_is_ignored(mcc, tmp_path, monkeypatch):
    write_mapping(mcc, tmp_path, monkeypatch, "mcc_mappings: not-a-mapping\n")
    assert mcc.load_mcc_mapping() == {}


def test_a_missing_mapping_file_is_not_an_error(mcc, tmp_path, monkeypatch):
    monkeypatch.setattr(mcc, "MCC_CONFIG_PATH", tmp_path / "does-not-exist.yaml")
    assert mcc.load_mcc_mapping() == {}


# ------------------------------------------------------------------ audit CSV
@pytest.fixture
def csv_log(tmp_path, monkeypatch):
    """csv_log resolves its path from DATA_DIR at import time, so the module
    is reloaded against a temp directory rather than monkeypatched halfway."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    service_module("bank_app", "config")
    module = service_module("bank_app", "csv_log")
    importlib.reload(service_module("bank_app", "config"))
    importlib.reload(module)
    return module


def test_every_logged_transaction_appears_once(csv_log):
    for i in range(5):
        csv_log.log_transaction("Bank", {"entry_reference": f"tx{i}", "amount": i})
    rows = list(csv.DictReader(csv_log.CSV_PATH.open()))
    assert len(rows) == 5
    assert [r["entry_reference"] for r in rows] == [f"tx{i}" for i in range(5)]


def test_a_nested_transaction_is_flattened_into_columns(csv_log):
    csv_log.log_transaction("Bank", {
        "entry_reference": "tx1",
        "transaction_amount": {"amount": "12.50", "currency": "EUR"},
        "tags": ["a", "b"],
    })
    rows = list(csv.DictReader(csv_log.CSV_PATH.open()))
    assert rows[0]["transaction_amount.amount"] == "12.50"
    assert rows[0]["transaction_amount.currency"] == "EUR"
    assert "a" in rows[0]["tags"] and "b" in rows[0]["tags"]


def test_a_new_field_widens_the_header_without_losing_old_rows(csv_log):
    csv_log.log_transaction("Bank", {"entry_reference": "tx1", "amount": 1})
    csv_log.log_transaction("Bank", {"entry_reference": "tx2", "amount": 2, "brand_new": "x"})
    rows = list(csv.DictReader(csv_log.CSV_PATH.open()))
    assert len(rows) == 2
    assert rows[0]["entry_reference"] == "tx1"
    assert rows[1]["brand_new"] == "x"
    assert rows[0].get("brand_new") in ("", None), "the older row simply has no value there"


def test_logging_does_not_reread_the_whole_log_each_time(csv_log, monkeypatch):
    """The cost of logging one transaction grew with the size of the log,
    because every call parsed every existing row back just to learn the
    column names. Only the header should be read on the common path."""
    for i in range(50):
        csv_log.log_transaction("Bank", {"entry_reference": f"tx{i}", "amount": i})

    real_reader = csv.reader
    rows_seen = {"n": 0}

    class CountingReader:
        """Wraps the real reader rather than replacing it with a generator:
        csv.DictReader reaches for `.line_num` on whatever it is given, so a
        bare generator would raise on the header-widening path and turn a
        measurement into a crash."""

        def __init__(self, stream, *args, **kwargs):
            self._inner = real_reader(stream, *args, **kwargs)

        def __iter__(self):
            return self

        def __next__(self):
            row = next(self._inner)
            rows_seen["n"] += 1
            return row

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(csv_log.csv, "reader", CountingReader)
    csv_log.log_transaction("Bank", {"entry_reference": "tx50", "amount": 50})
    assert rows_seen["n"] <= 1, (
        f"appending one row read {rows_seen['n']} rows back; the header alone is enough"
    )

    # And the widening path, which legitimately does rewrite the file, still
    # works while instrumented -- so the measurement above is a measurement,
    # not an accident of the fake reader breaking early.
    rows_seen["n"] = 0
    csv_log.log_transaction("Bank", {"entry_reference": "tx51", "brand_new": "x"})
    assert rows_seen["n"] >= 1


# ------------------------------------------------------- capture-loop helpers
# sync.py reaches PyJWT[crypto], which cannot be imported on every machine.
# The helpers below are pure and worth testing wherever it can be.
sync = None
try:  # pragma: no cover - depends on the environment
    sync = service_module("bank_app", "sync")
except BaseException as exc:  # noqa: BLE001 - a broken crypto build raises, not imports
    SYNC_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    SYNC_IMPORT_ERROR = ""

needs_sync = pytest.mark.skipif(sync is None, reason=f"bank-sync's sync module unavailable ({SYNC_IMPORT_ERROR})")


@needs_sync
def test_an_unparseable_bank_date_is_filed_under_today():
    class Link:
        label = "Test bank"

    for raw in ("not-a-date", "", None, "31/12/2026", 20261231):
        got = sync._usable_date({"booking_date": raw}, Link(), "ext1")
        assert got == date.today()


@needs_sync
def test_a_future_bank_date_is_filed_under_today():
    """A scheduled payment dated ahead is normal for a bank to report, and
    core refuses future dates."""
    class Link:
        label = "Test bank"

    ahead = (date.today() + timedelta(days=30)).isoformat()
    assert sync._usable_date({"booking_date": ahead}, Link(), "ext1") == date.today()


@needs_sync
def test_a_normal_bank_date_is_kept():
    class Link:
        label = "Test bank"

    when = date.today() - timedelta(days=3)
    assert sync._usable_date({"booking_date": when.isoformat()}, Link(), "ext1") == when


@needs_sync
def test_an_unsigned_amount_still_finds_its_direction():
    """The signed amount used to be abs()'d before reaching this fallback, so
    a transaction with no credit/debit indicator was always income."""
    assert sync._direction({}, -12.5) == "EXPENSE"
    assert sync._direction({}, 12.5) == "INCOME"
