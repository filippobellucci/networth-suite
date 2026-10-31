"""
bank-sync never creates one bank transaction twice in core-networth, however
a cycle is interrupted.

Each push used to go out without an Idempotency-Key, and the ledger row that
says "already captured" was committed once, at the end of the cycle. A push
that timed out after core had written, or a restart between a push and that
final commit, left the ledger without the row, so the next cycle created the
transaction again.

core-networth is faked at the HTTP level here (an httpx MockTransport behind
the real `_push_to_core`), replaying a key it has already seen the way the
real one does, so what is checked is the request bank-sync actually sends.
"""
from __future__ import annotations

import itertools
import json
import os
import re
from datetime import date

import pytest
from sqlalchemy import create_engine
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

httpx = sync.httpx
RealAsyncClient = httpx.AsyncClient


class Crash(BaseException):
    """The process dying mid-cycle: nothing in sync.py catches it."""


def payment(ref: str, amount: str = "10.00", status: str = "BOOK") -> dict:
    return {
        "entry_reference": ref,
        "transaction_amount": {"currency": "EUR", "amount": amount},
        "creditor": {"name": "Esselunga"},
        "credit_debit_indicator": "DBIT",
        "status": status,
        "booking_date": date.today().isoformat(),
        "remittance_information": ["Esselunga"],
    }


class FakeCore:
    """The cash-transaction endpoints of core-networth, with its idempotency
    rules: a key seen before replays its stored response; a key whose first
    request has not finished yet gets a 409."""

    def __init__(self):
        self.txns: dict[str, dict] = {}
        self.stored: dict[str, dict] = {}   # Idempotency-Key -> response body
        self.keys_sent: list[str | None] = []
        self.in_flight: set[str] = set()    # keys answered with "still being processed"
        self.after_write = None             # raised once a POST has been written, before it answers
        self.before_write = None            # raised as a POST arrives, before anything is written
        self._ids = itertools.count(1)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and re.fullmatch(r"/cash-accounts/[^/]+/transactions", request.url.path):
            return self._create(request)
        m = re.fullmatch(r"/cash-transactions/([^/]+)", request.url.path)
        if m and request.method == "DELETE":
            self.txns.pop(m.group(1), None)
            return httpx.Response(204)
        if m and request.method == "GET":
            txn = self.txns.get(m.group(1))
            return httpx.Response(200, json=txn) if txn else httpx.Response(404)
        return httpx.Response(404)

    def _create(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("Idempotency-Key")
        self.keys_sent.append(key)
        if self.before_write:
            exc, self.before_write = self.before_write, None
            raise exc
        if key in self.in_flight:
            return httpx.Response(409, json={"detail": "A request with this Idempotency-Key is still being processed"})
        if key in self.stored:
            return httpx.Response(201, json=self.stored[key])
        body = json.loads(request.content)
        core_id = f"core-{next(self._ids)}"
        txn = {"id": core_id, **body}
        self.txns[core_id] = txn
        if key:
            self.stored[key] = txn
        if self.after_write:
            exc, self.after_write = self.after_write, None
            raise exc
        return httpx.Response(201, json=txn)


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/bank_sync.db")
    database.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    db = Session()
    db.add(models.BankLink(label="Fineco", aspsp_name="Fineco", aspsp_country="IT", portfolio_id="p1",
                           cash_account_id="acc1", status=models.LinkStatus.ACTIVE, eb_account_id="eb1"))
    db.commit()
    db.close()

    bank: dict = {"txns": []}

    async def get_transactions(account_id, date_from=None, continuation_key=None):
        return {"transactions": [dict(t) for t in bank["txns"]]}

    async def no_reconcile(db, link):
        return None

    core = FakeCore()
    transport = httpx.MockTransport(core.handle)
    monkeypatch.setattr(sync.httpx, "AsyncClient", lambda **kw: RealAsyncClient(transport=transport, **kw))
    monkeypatch.setattr(sync.enable_banking, "get_transactions", get_transactions)
    monkeypatch.setattr(sync.csv_log, "log_transaction", lambda label, t: None)
    monkeypatch.setattr(sync, "reconcile_balance", no_reconcile)
    resolver = mcc.MccResolver({}, {})

    class World:
        pass

    w = World()
    w.bank, w.core = bank, core
    w.session = None

    async def run():
        """One sync cycle, in a session of its own -- as after a restart."""
        if w.session is not None:
            w.session.close()
        w.session = Session()
        link = w.session.get(models.BankLink, "Fineco")
        return await sync._sync_link_locked(w.session, link, resolver)

    def ledger() -> set[str]:
        with Session() as fresh:
            return {r.external_id for r in fresh.query(models.SyncedTransaction).all()}

    w.sync, w.ledger = run, ledger
    yield w
    if w.session is not None:
        w.session.close()


async def test_every_push_carries_a_key_stable_across_cycles(world):
    world.bank["txns"] = [payment("tx1")]
    world.core.before_write = httpx.ConnectError("core-networth unreachable")
    assert await world.sync() == 0
    assert await world.sync() == 1
    assert world.core.keys_sent == ["bank-sync:Fineco:tx1", "bank-sync:Fineco:tx1"]


async def test_a_push_that_timed_out_after_core_wrote_is_not_created_again(world):
    world.bank["txns"] = [payment("tx1")]
    world.core.after_write = httpx.ReadTimeout("no answer in time")
    assert await world.sync() == 0, "the push failed as far as bank-sync could tell"
    assert world.ledger() == set()

    assert await world.sync() == 1
    assert len(world.core.txns) == 1
    assert world.ledger() == {"tx1"}


async def test_each_capture_is_in_the_ledger_as_soon_as_core_has_it(world):
    world.bank["txns"] = [payment("tx1"), payment("tx2"), payment("tx3")]

    original = world.core._create
    pushes = itertools.count(1)

    def crash_on_third(request):
        if next(pushes) == 3:
            raise Crash()
        return original(request)

    world.core._create = crash_on_third
    with pytest.raises(Crash):
        await world.sync()
    assert world.ledger() == {"tx1", "tx2"}, "what core already holds survives the crash"

    world.core._create = original
    assert await world.sync() == 1
    assert len(world.core.txns) == 3
    assert world.ledger() == {"tx1", "tx2", "tx3"}


async def test_a_crash_after_core_wrote_but_before_the_ledger_commit_is_replayed(world):
    world.bank["txns"] = [payment("tx1"), payment("tx2")]
    world.core.after_write = Crash()
    with pytest.raises(Crash):
        await world.sync()
    assert len(world.core.txns) == 1 and world.ledger() == set()

    assert await world.sync() == 2
    assert len(world.core.txns) == 2, "tx1 was replayed by its key, not created again"


async def test_a_key_still_being_processed_is_retried_next_cycle(world):
    world.bank["txns"] = [payment("tx1")]
    world.core.in_flight.add("bank-sync:Fineco:tx1")
    assert await world.sync() == 0
    assert world.ledger() == set() and world.core.txns == {}
    with world.session as s:
        assert s.get(models.BankLink, "Fineco").last_synced_at is None, "the window is kept for the retry"

    world.core.in_flight.clear()
    assert await world.sync() == 1
    assert len(world.core.txns) == 1


async def test_a_voided_payment_that_comes_back_is_created_again_despite_the_replay(world):
    world.bank["txns"] = [payment("tx1", status="PDNG")]
    await world.sync()
    world.bank["txns"] = [payment("tx1", status="CNCL")]
    await world.sync()
    assert world.core.txns == {}, "the hold was released, its transaction removed"

    world.bank["txns"] = [payment("tx1")]
    world.core.after_write = Crash()
    with pytest.raises(Crash):
        await world.sync()
    assert await world.sync() == 1
    assert len(world.core.txns) == 1, "a new key for the new capture, replayed after the crash"
    first_key, *recaptures = world.core.keys_sent
    assert recaptures[0] == recaptures[1] != first_key


async def test_a_failed_recapture_keeps_the_voided_row_for_its_retry(world):
    world.bank["txns"] = [payment("tx1", status="PDNG")]
    await world.sync()
    world.bank["txns"] = [payment("tx1", status="CNCL")]
    await world.sync()

    # The recapture fails; a later transaction's commit must not take the
    # voided row with it, or the retry would fall back to the first key --
    # whose replay is the transaction already removed.
    world.bank["txns"] = [payment("tx1"), payment("tx2")]
    world.core.before_write = httpx.ConnectError("core-networth unreachable")
    assert await world.sync() == 1
    assert await world.sync() == 1
    assert len(world.core.txns) == 2
