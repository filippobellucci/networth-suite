"""
bank-sync's handling of card payments that arrive pending and are booked later.

A real Revolut account showed the shape of it: a card payment first comes
through Enable Banking with status PDNG and its merchant_category_code left
empty, under the same entry_reference it keeps once booked. The service used
to capture it on first sight and never look at it again, so whatever only the
booked version carries -- the final amount, the MCC -- was lost for good, and
a hold that was released instead of booked stayed an expense forever.

Enable Banking and core-networth are both faked here: the bank is a list of
transaction dicts, core a dict of the transactions it holds.
"""
from __future__ import annotations

import itertools
import os
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from service_loader import service_module

pytestmark = pytest.mark.unit

try:  # sync.py reaches PyJWT[crypto], which cannot be imported on every machine
    sync = service_module("bank_app", "sync")
except BaseException as exc:  # noqa: BLE001 - a broken crypto build raises, not imports
    sync = None
    SYNC_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    SYNC_IMPORT_ERROR = ""

if sync is None:
    if os.environ.get("CI"):  # see test_bank_sync_helpers: on CI this must fail, not skip
        raise RuntimeError(f"bank-sync's sync module could not be imported on CI: {SYNC_IMPORT_ERROR}")
    pytest.skip(f"bank-sync's sync module unavailable ({SYNC_IMPORT_ERROR})", allow_module_level=True)

models = service_module("bank_app", "models")
database = service_module("bank_app", "database")
mcc = service_module("bank_app", "mcc_categories")
migrate = service_module("bank_app", "migrate")

TODAY = date.today()


def days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def card_payment(ref: str, amount: str, merchant: str, status: str = "PDNG", mcc_code: str | None = None,
                 on: str | None = None) -> dict:
    return {
        "entry_reference": ref,
        "transaction_amount": {"currency": "EUR", "amount": amount},
        "creditor": {"name": merchant},
        "debtor": {"name": "FILIPPO BELLUCCI"},
        "bank_transaction_code": {"code": "CARD_PAYMENT"},
        "credit_debit_indicator": "DBIT",
        "status": status,
        "booking_date": on or days_ago(0),
        "remittance_information": [merchant],
        "merchant_category_code": mcc_code,
    }


class FakeCore:
    def __init__(self):
        self.txns: dict[str, dict] = {}
        self.patches: list[tuple[str, dict]] = []
        self.rules: dict[str, str] = {}  # normalized counterparty -> category, like core's merchant rules
        self.down = False
        self._ids = itertools.count(1)

    def _check(self):
        if self.down:
            raise sync.httpx.ConnectError("core-networth unreachable")

    async def push(self, cash_account_id, entry_date, direction, amount, note, category_id, counterparty=""):
        self._check()
        core_id = f"core-{next(self._ids)}"
        if category_id is None:
            category_id = self.rules.get(" ".join(counterparty.split()).casefold())
        self.txns[core_id] = {"id": core_id, "amount": round(amount, 2), "direction": direction,
                              "category_id": category_id, "entry_date": entry_date, "note": note,
                              "counterparty": counterparty}
        return core_id, category_id

    async def get(self, core_id):
        self._check()
        return dict(self.txns[core_id]) if core_id in self.txns else None

    async def patch(self, core_id, changes):
        self._check()
        if core_id not in self.txns:
            request = sync.httpx.Request("PATCH", f"http://core/cash-transactions/{core_id}")
            raise sync.httpx.HTTPStatusError("404", request=request, response=sync.httpx.Response(404, request=request))
        self.patches.append((core_id, changes))
        self.txns[core_id].update(changes)

    async def delete(self, core_id):
        self._check()
        self.txns.pop(core_id, None)


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/bank_sync.db")
    database.Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    link = models.BankLink(label="Revolut", aspsp_name="Revolut", aspsp_country="IT", portfolio_id="p1",
                           cash_account_id="acc1", status=models.LinkStatus.ACTIVE, eb_account_id="eb1")
    db.add(link)
    db.commit()

    bank: dict = {"txns": [], "date_from": []}

    async def get_transactions(account_id, date_from=None, continuation_key=None):
        bank["date_from"].append(date_from)
        return {"transactions": [dict(t) for t in bank["txns"]]}

    core = FakeCore()
    logged: list[dict] = []
    monkeypatch.setattr(sync.enable_banking, "get_transactions", get_transactions)
    monkeypatch.setattr(sync, "_push_to_core", core.push)
    monkeypatch.setattr(sync, "_get_from_core", core.get)
    monkeypatch.setattr(sync, "_patch_in_core", core.patch)
    monkeypatch.setattr(sync, "_delete_from_core", core.delete)
    monkeypatch.setattr(sync.csv_log, "log_transaction", lambda label, t: logged.append(t))

    # Balance reconciliation: what the bank and core report, per test.
    bank["balances"] = {"balances": [{"balance_amount": {"amount": "100.00", "currency": "EUR"},
                                      "balance_type": "ITAV"}]}
    app_balance = {"value": (100.0, "EUR")}

    async def get_balances(account_id):
        if isinstance(bank["balances"], Exception):
            raise bank["balances"]
        return bank["balances"]

    async def fake_app_balance(link):
        return app_balance["value"]

    monkeypatch.setattr(sync.enable_banking, "get_balances", get_balances)
    monkeypatch.setattr(sync, "_app_balance", fake_app_balance)

    resolver = mcc.MccResolver({"5411": "Spesa"}, {"spesa": "cat-spesa", "bar": "cat-bar"})

    class World:
        pass

    w = World()
    w.db, w.link, w.bank, w.core, w.logged = db, link, bank, core, logged

    async def run():
        return await sync._sync_link_locked(db, link, resolver)

    w.sync = run
    w.app_balance = app_balance
    w.row = lambda ref: db.get(models.SyncedTransaction, f"Revolut:{ref}")
    yield w
    db.close()


async def test_a_pending_payment_is_captured_right_away_and_tracked(world):
    world.bank["txns"] = [card_payment("tx1", "1.08", "Unicoop Firenze-Ponsacco")]
    assert await world.sync() == 1
    (core_txn,) = world.core.txns.values()
    assert core_txn["amount"] == 1.08 and core_txn["direction"] == "EXPENSE"
    assert world.row("tx1").state == models.SyncState.PENDING


async def test_booking_brings_in_the_final_amount_and_the_mcc_category(world):
    world.bank["txns"] = [card_payment("tx1", "1.08", "Unicoop")]
    await world.sync()
    world.bank["txns"] = [card_payment("tx1", "1.18", "Unicoop", status="BOOK", mcc_code="5411")]
    assert await world.sync() == 0, "the booked version is the same payment, not a new one"

    (core_txn,) = world.core.txns.values()
    assert core_txn["amount"] == 1.18
    assert core_txn["category_id"] == "cat-spesa"
    row = world.row("tx1")
    assert row.state == models.SyncState.FINAL
    assert row.amount == -1.18 and row.category_id == "cat-spesa"
    assert [t["status"] for t in world.logged] == ["PDNG", "BOOK"], "the booked version gets its own audit row"


async def test_a_category_set_by_hand_meanwhile_is_left_alone(world):
    world.bank["txns"] = [card_payment("tx1", "1.08", "Unicoop")]
    await world.sync()
    core_id = world.row("tx1").core_transaction_id
    world.core.txns[core_id]["category_id"] = "cat-bar"  # the user tagged it in the Expenses page

    world.bank["txns"] = [card_payment("tx1", "1.10", "Unicoop", status="BOOK", mcc_code="5411")]
    await world.sync()
    assert world.core.txns[core_id]["category_id"] == "cat-bar"
    assert world.core.txns[core_id]["amount"] == 1.10, "the amount was still the service's own, so it follows the bank"


async def test_an_amount_changed_by_hand_meanwhile_is_left_alone(world):
    world.bank["txns"] = [card_payment("tx1", "20.00", "Hotel")]
    await world.sync()
    core_id = world.row("tx1").core_transaction_id
    world.core.txns[core_id]["amount"] = 25.0

    world.bank["txns"] = [card_payment("tx1", "18.00", "Hotel", status="BOOK")]
    await world.sync()
    assert world.core.txns[core_id]["amount"] == 25.0
    assert world.row("tx1").state == models.SyncState.FINAL


async def test_a_booking_that_changes_nothing_does_not_touch_core(world):
    world.bank["txns"] = [card_payment("tx1", "2.50", "Antichi Sapori Cafe'")]
    await world.sync()
    world.bank["txns"] = [card_payment("tx1", "2.50", "Antichi Sapori Cafe'", status="BOOK")]
    await world.sync()
    assert world.core.patches == []
    assert world.row("tx1").state == models.SyncState.FINAL


async def test_a_pending_payment_the_bank_cancels_is_removed(world):
    world.bank["txns"] = [card_payment("tx1", "50.00", "Benzinaio")]
    await world.sync()
    world.bank["txns"] = [card_payment("tx1", "50.00", "Benzinaio", status="CNCL")]
    await world.sync()
    assert world.core.txns == {}
    assert world.row("tx1").state == models.SyncState.VOIDED


async def test_a_pending_payment_that_vanishes_is_removed_only_after_two_cycles(world):
    world.bank["txns"] = [card_payment("tx1", "50.00", "Benzinaio")]
    await world.sync()
    world.bank["txns"] = []

    await world.sync()
    assert len(world.core.txns) == 1, "one missing response isn't enough to remove a real expense"
    await world.sync()
    assert world.core.txns == {}
    assert world.row("tx1").state == models.SyncState.VOIDED


async def test_reappearing_resets_the_missing_count(world):
    world.bank["txns"] = [card_payment("tx1", "50.00", "Benzinaio")]
    await world.sync()
    world.bank["txns"] = []
    await world.sync()
    world.bank["txns"] = [card_payment("tx1", "50.00", "Benzinaio")]
    await world.sync()
    world.bank["txns"] = []
    await world.sync()
    assert len(world.core.txns) == 1


async def test_a_voided_payment_that_comes_back_is_captured_again(world):
    world.bank["txns"] = [card_payment("tx1", "50.00", "Benzinaio")]
    await world.sync()
    world.bank["txns"] = []
    await world.sync()
    await world.sync()
    world.bank["txns"] = [card_payment("tx1", "50.00", "Benzinaio", status="BOOK")]
    assert await world.sync() == 1
    assert len(world.core.txns) == 1
    assert world.row("tx1").state == models.SyncState.FINAL


async def test_a_booked_payment_that_disappears_is_never_removed(world):
    world.bank["txns"] = [card_payment("tx1", "9.99", "Netflix", status="BOOK")]
    await world.sync()
    world.bank["txns"] = []
    for _ in range(3):
        await world.sync()
    assert len(world.core.txns) == 1


async def test_a_payment_cancelled_before_it_was_ever_seen_is_not_captured(world):
    world.bank["txns"] = [card_payment("tx1", "50.00", "Benzinaio", status="RJCT")]
    assert await world.sync() == 0
    assert world.core.txns == {}
    world.bank["txns"] = []
    await world.sync()
    assert world.row("tx1").state == models.SyncState.FINAL


async def test_a_transaction_without_a_status_is_treated_as_booked(world):
    txn = card_payment("tx1", "3.00", "Edicola")
    del txn["status"]
    world.bank["txns"] = [txn]
    await world.sync()
    assert world.row("tx1").state == models.SyncState.FINAL


async def test_a_pending_payment_deleted_by_hand_stops_being_tracked(world):
    world.bank["txns"] = [card_payment("tx1", "1.08", "Unicoop")]
    await world.sync()
    world.core.txns.clear()
    world.bank["txns"] = [card_payment("tx1", "1.20", "Unicoop", status="BOOK", mcc_code="5411")]
    await world.sync()
    assert world.core.txns == {}, "deleting it was a decision, not something to undo"
    assert world.row("tx1").state == models.SyncState.FINAL


async def test_core_being_down_while_settling_is_retried_next_cycle(world):
    world.bank["txns"] = [card_payment("tx1", "1.08", "Unicoop")]
    await world.sync()
    watermark = world.link.last_synced_at

    world.bank["txns"] = [card_payment("tx1", "1.20", "Unicoop", status="BOOK")]
    world.core.down = True
    await world.sync()
    assert world.row("tx1").state == models.SyncState.PENDING
    assert world.link.last_synced_at == watermark and world.link.last_error

    world.core.down = False
    await world.sync()
    (core_txn,) = world.core.txns.values()
    assert core_txn["amount"] == 1.20
    assert world.row("tx1").state == models.SyncState.FINAL


async def test_the_fetch_window_reaches_back_to_the_oldest_pending_payment(world):
    world.bank["txns"] = [card_payment("tx1", "80.00", "Hotel", on=days_ago(6))]
    await world.sync()
    world.link.last_synced_at = datetime.utcnow()
    await world.sync()
    assert world.bank["date_from"][-1] == days_ago(7), "a 1-day window would never see its booking"


async def test_a_payment_pending_for_too_long_is_no_longer_waited_on(world, monkeypatch):
    monkeypatch.setattr(sync, "PENDING_TRACK_DAYS", 5)
    world.bank["txns"] = [card_payment("tx1", "80.00", "Hotel", on=days_ago(6))]
    await world.sync()
    world.bank["txns"] = []
    for _ in range(3):
        await world.sync()
    assert len(world.core.txns) == 1, "given up on, not removed"
    assert world.row("tx1").state == models.SyncState.FINAL


# -------------------------------------------------------------- counterparty
async def test_the_merchant_is_sent_as_the_counterparty(world):
    world.bank["txns"] = [card_payment("tx1", "7.20", "Unicoop Firenze-Ponsacco")]
    await world.sync()
    (core_txn,) = world.core.txns.values()
    assert core_txn["counterparty"] == "Unicoop Firenze-Ponsacco"
    assert world.row("tx1").counterparty == "Unicoop Firenze-Ponsacco"


async def test_income_is_sent_with_its_sender_not_the_account_holder(world):
    topup = card_payment("tx1", "500.00", "FILIPPO BELLUCCI", status="BOOK")
    topup.update(credit_debit_indicator="CRDT", debtor={"name": "ACME SPA"}, creditor={"name": "FILIPPO BELLUCCI"})
    world.bank["txns"] = [topup]
    await world.sync()
    (core_txn,) = world.core.txns.values()
    assert core_txn["direction"] == "INCOME" and core_txn["counterparty"] == "ACME SPA"


async def test_the_category_core_gives_by_merchant_rule_is_remembered(world):
    """So booking -- which only corrects what bank-sync itself set -- treats
    it as the service's own and doesn't mistake it for a choice made by hand."""
    world.core.rules["unicoop"] = "cat-spesa"
    world.bank["txns"] = [card_payment("tx1", "1.08", "Unicoop")]
    await world.sync()
    assert world.row("tx1").category_id == "cat-spesa"
    world.bank["txns"] = [card_payment("tx1", "1.10", "Unicoop", status="BOOK")]
    await world.sync()
    (core_txn,) = world.core.txns.values()
    assert core_txn["amount"] == 1.10 and core_txn["category_id"] == "cat-spesa"


async def test_a_very_long_counterparty_is_cut_to_what_core_accepts(world):
    world.bank["txns"] = [card_payment("tx1", "1.00", "X" * 500)]
    await world.sync()
    (core_txn,) = world.core.txns.values()
    assert len(core_txn["counterparty"]) == sync.COUNTERPARTY_MAX_LEN


# ------------------------------------------------------- balance reconciliation
async def test_a_clean_sync_records_both_balances(world):
    world.bank["balances"] = {"balances": [
        {"balance_amount": {"amount": "250.00", "currency": "EUR"}, "balance_type": "CLBD"},
        {"balance_amount": {"amount": "243.15", "currency": "EUR"}, "balance_type": "ITAV"},
    ]}
    world.app_balance["value"] = (240.0, "EUR")
    await world.sync()
    link = world.link
    assert (link.bank_balance, link.bank_balance_type) == (243.15, "ITAV"), "available beats booked"
    assert link.app_balance == 240.0 and link.balance_checked_at is not None


async def test_a_balance_check_failing_never_fails_the_sync(world):
    world.bank["balances"] = RuntimeError("bank down")
    world.bank["txns"] = [card_payment("tx1", "1.00", "Unicoop")]
    assert await world.sync() == 1
    assert world.link.last_error is None and world.link.balance_checked_at is None


async def test_no_balance_check_after_a_cycle_with_failures(world):
    world.core.down = True
    world.bank["txns"] = [card_payment("tx1", "1.00", "Unicoop")]
    await world.sync()
    assert world.link.balance_checked_at is None


def test_balance_types_are_picked_by_preference():
    pick = sync._pick_balance
    assert pick([]) is None
    assert pick([{"balance_amount": {"amount": "x"}, "balance_type": "ITAV"}]) is None
    assert pick([{"balance_amount": {"amount": "5", "currency": "EUR"}, "balance_type": "WEIRD"},
                 {"balance_amount": {"amount": "7", "currency": "EUR"}, "balance_type": "CLBD"}]) == (7.0, "EUR", "CLBD")
    assert pick([{"balance_amount": {"amount": "5", "currency": "EUR"}}]) == (5.0, "EUR", "?")


# ------------------------------------------------------------------ migration
def test_an_existing_database_gains_the_new_columns(tmp_path):
    """create_all() never alters a table that already exists, so without the
    migration every query on an existing install would fail."""
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE synced_transactions (id VARCHAR PRIMARY KEY, bank_link_label VARCHAR NOT NULL, "
            "external_id VARCHAR NOT NULL, entry_date DATE NOT NULL, amount FLOAT NOT NULL, "
            "core_transaction_id VARCHAR, created_at DATETIME)"
        ))
        conn.execute(text(
            "INSERT INTO synced_transactions VALUES ('Revolut:tx0', 'Revolut', 'tx0', '2026-09-01', -5.0, 'c0', NULL)"
        ))
        conn.execute(text(
            "CREATE TABLE bank_links (label VARCHAR PRIMARY KEY, aspsp_name VARCHAR NOT NULL, aspsp_country VARCHAR NOT NULL,"
            " portfolio_id VARCHAR NOT NULL, cash_account_id VARCHAR NOT NULL, status VARCHAR(11) NOT NULL,"
            " session_id VARCHAR, eb_account_id VARCHAR, valid_until DATETIME, last_synced_at DATETIME,"
            " last_error TEXT, created_at DATETIME)"
        ))
        conn.execute(text(
            "INSERT INTO bank_links (label, aspsp_name, aspsp_country, portfolio_id, cash_account_id, status)"
            " VALUES ('Revolut', 'Revolut', 'IT', 'p', 'a', 'ACTIVE')"
        ))
    database.Base.metadata.create_all(bind=engine)
    migrate.run_lightweight_migrations(engine)
    migrate.run_lightweight_migrations(engine)  # a second start changes nothing

    db = sessionmaker(bind=engine)()
    row = db.get(models.SyncedTransaction, "Revolut:tx0")
    assert row.state == models.SyncState.FINAL, "rows from before this existed are treated as booked"
    assert row.missing_count == 0 and row.category_id is None
    assert row.counterparty is None
    link = db.get(models.BankLink, "Revolut")
    assert link.status == models.LinkStatus.ACTIVE and link.bank_balance is None and link.balance_checked_at is None
    db.close()


async def test_the_app_balance_is_read_from_the_portfolio_snapshot(monkeypatch):
    import httpx

    def handler(request):
        assert request.url.path == "/portfolios/p1/snapshot"
        return httpx.Response(200, json={"cash_positions": [
            {"account_id": "other", "balance": 1.0, "currency": "EUR"},
            {"account_id": "acc1", "balance": 321.5, "currency": "EUR"},
        ]})

    real = httpx.AsyncClient
    monkeypatch.setattr(sync.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    class Link:
        portfolio_id, cash_account_id = "p1", "acc1"

    assert await sync._app_balance(Link()) == (321.5, "EUR")
    Link.cash_account_id = "missing"
    assert await sync._app_balance(Link()) is None
