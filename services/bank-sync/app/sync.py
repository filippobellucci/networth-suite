"""
The actual "watch a bank, create expenses automatically" logic. Each
ACTIVE link gets its transactions re-fetched (Enable Banking returns
transactions for a date range, not "what's new since last time"), and
SyncedTransaction is what keeps a second sync from creating the same
expense twice.

A transaction is categorized on capture when mcc_categories.yaml says how
(see mcc_categories.py); otherwise it lands uncategorized and you tag it
afterward in the Expenses page, same as any manually-logged one.

Card payments usually arrive first as *pending* (status PDNG) and are
booked a few days later -- possibly for a different amount, and with an MCC
the pending version didn't carry. They're captured right away, so they show
up the same day, then re-read every cycle until booked: amount and category
are corrected then, and one that's cancelled or vanishes is removed again.
"""
import asyncio
import logging
from datetime import datetime, date, timedelta

import httpx

from . import alerts, models, enable_banking, csv_log
from .database import SessionLocal
from .config import CORE_SERVICE_URL, MAX_HISTORICAL_DAYS, PENDING_TRACK_DAYS
from .mcc_categories import MccResolver, build_resolver

logger = logging.getLogger("bank-sync.sync")

# Guards sync_all()/sync_link() against overlapping runs -- the manual
# "Sync all now" link and the background scheduler loop each start their own
# SessionLocal(), so without this two concurrent runs could both pass the
# SyncedTransaction dedupe check for the same bank transaction before either
# commits, pushing it to core-networth twice.
_sync_lock = asyncio.Lock()


def _direction(txn: dict, amount: float) -> str | None:
    """
    `credit_debit_indicator` (CRDT/DBIT) is the field actually meant for
    this -- some banks return `transaction_amount.amount` as an unsigned
    string (see the official example in enablebanking.com's own API docs,
    where a DBIT transaction's amount has no minus sign), so relying on the
    sign of `amount` alone would silently misclassify those as income.
    Falls back to the amount's sign only if the indicator is ever missing.
    """
    indicator = (txn.get("credit_debit_indicator") or "").upper()
    if indicator == "CRDT":
        return "INCOME"
    if indicator == "DBIT":
        return "EXPENSE"
    if amount == 0:
        return None
    return "INCOME" if amount > 0 else "EXPENSE"


def _extract_note(txn: dict) -> str:
    info = txn.get("remittance_information")
    if isinstance(info, list) and info:
        # Some banks split the description across multiple lines (e.g.
        # ["Card payment 11.04.2026", "K-Market Tapiola"]) -- join them all
        # instead of keeping only the first, so nothing meaningful is lost
        # from what actually ends up in the Note field.
        return " — ".join(str(line) for line in info if line)[:500]
    if isinstance(info, str):
        return info[:500]
    return (txn.get("creditor", {}) or {}).get("name") or (txn.get("debtor", {}) or {}).get("name") or ""


def _external_id(txn: dict) -> tuple[str, bool]:
    """Returns (id, is_stable). `is_stable` is True when the id came from a
    real bank-assigned identifier; False when it's our own best-effort
    fallback built from date/amount/note, which two distinct transactions
    can share (e.g. two identical same-day vending-machine purchases with
    no note) -- the caller disambiguates same-cycle collisions of the
    unstable kind so they aren't merged into a single synced transaction."""
    stable_id = txn.get("entry_reference") or txn.get("transaction_id")
    if stable_id:
        return stable_id, True
    amt = (txn.get("transaction_amount") or {}).get("amount")
    fallback = (
        f"{txn.get('booking_date')}:{txn.get('value_date')}:{amt}:"
        f"{txn.get('merchant_category_code')}:{_extract_note(txn)}"
    )
    return fallback, False


def _usable_date(txn: dict, link: "models.BankLink", ext_id: str) -> date:
    """
    The date to file this transaction under, guaranteed usable by
    core-networth: a real date, never in the future.

    A date core rejects would keep the transaction from ever being marked
    synced, and the link's watermark from advancing past it. Banks do send
    dates in local formats (or as objects), and pending/scheduled payments
    dated in the future. Anything unusable is filed today, with a warning
    naming the original.
    """
    raw = txn.get("booking_date") or txn.get("value_date") or ""
    today = date.today()
    try:
        parsed = date.fromisoformat(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Link %s: transaction %s has an unusable date %r -- filing it under today instead",
            link.label, ext_id, raw,
        )
        return today
    if parsed > today:
        logger.info(
            "Link %s: transaction %s is dated %s (not yet due) -- filing it under today instead",
            link.label, ext_id, parsed,
        )
        return today
    return parsed


def _mark_skipped(db, dedupe_key: str, link: "models.BankLink", ext_id: str) -> None:
    """
    Records a transaction this loop deliberately did not push (cancelled,
    zero amount, no direction, unreadable amount) as already handled.

    Otherwise they'd come back every cycle inside the fetch window, pass the
    dedupe check again, and be appended to the audit CSV once more.
    """
    db.add(
        models.SyncedTransaction(
            id=dedupe_key,
            bank_link_label=link.label,
            external_id=ext_id,
            entry_date=date.today(),
            amount=0.0,
            core_transaction_id=None,  # nothing was created in core-networth
        )
    )


# core-networth caps a counterparty at this length; a longer name would have
# every push of that transaction rejected, so it's cut here instead.
COUNTERPARTY_MAX_LEN = 200


def _counterparty(txn: dict, direction: str | None) -> str:
    """
    Who the money went to (the creditor, on money going out) or came from
    (the debtor, on money coming in) -- the merchant on a card payment, the
    sender of a transfer. The other party is always the account holder, so
    it says nothing about the transaction. "" when the bank names nobody.
    """
    party_key = "debtor" if direction == "INCOME" else "creditor"
    name = ((txn.get(party_key) or {}).get("name") or "").strip()
    return name[:COUNTERPARTY_MAX_LEN]


async def _push_to_core(
    cash_account_id: str, entry_date: str, direction: str, amount: float, note: str,
    category_id: str | None, counterparty: str = "",
) -> tuple[str, str | None]:
    """Returns the new transaction's id, and the category core-networth
    gave it -- the one sent, or, without one, its merchant rule's for the
    counterparty."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{CORE_SERVICE_URL}/cash-accounts/{cash_account_id}/transactions",
            json={
                "entry_date": entry_date,
                "direction": direction,
                "amount": round(amount, 2),
                "note": note or None,
                "category_id": category_id,
                "counterparty": counterparty or None,
            },
        )
        r.raise_for_status()
        body = r.json()
        return body["id"], body.get("category_id")


async def _get_from_core(core_transaction_id: str) -> dict | None:
    """The transaction as core-networth has it now, or None if it's gone
    (deleted by hand from the Expenses page)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{CORE_SERVICE_URL}/cash-transactions/{core_transaction_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def _patch_in_core(core_transaction_id: str, changes: dict) -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.patch(f"{CORE_SERVICE_URL}/cash-transactions/{core_transaction_id}", json=changes)
        r.raise_for_status()


async def _delete_from_core(core_transaction_id: str) -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.delete(f"{CORE_SERVICE_URL}/cash-transactions/{core_transaction_id}")
        if r.status_code != 404:  # already gone is exactly what was wanted
            r.raise_for_status()


# Enable Banking's `status` values (ISO 20022 entry status). Checked against
# a live Revolut account: a card payment first arrives as PDNG -- with its
# MCC left empty -- under the same entry_reference it keeps once booked.
PENDING_STATUSES = {"PDNG", "HOLD", "SCHD"}
VOID_STATUSES = {"CNCL", "RJCT"}

# A pending transaction missing from this many consecutive complete fetches
# is treated as cancelled. More than one, so a single odd response from the
# bank can't remove an expense that really happened.
PENDING_MISSING_CYCLES = 2


def _bank_status(txn: dict) -> str:
    """Upper-cased, "" when absent. Absent is treated as booked, exactly as
    every transaction was before statuses were looked at."""
    return str(txn.get("status") or "").upper()


def _parse_amount(txn: dict) -> float | None:
    """The bank's signed amount, or None when it can't be read as a number."""
    try:
        return float((txn.get("transaction_amount") or {}).get("amount", 0))
    except (TypeError, ValueError):
        return None


def _signed_amount(amount: float, direction: str) -> float:
    return amount if direction == "INCOME" else -amount


def _is_client_error(e: Exception) -> bool:
    return isinstance(e, httpx.HTTPStatusError) and 400 <= e.response.status_code < 500


async def _void(synced: "models.SyncedTransaction", link: "models.BankLink", why: str) -> bool:
    """
    Removes the core transaction of a pending payment that never went
    through (a released card hold, a cancelled payment): it moved no money,
    so leaving it would keep a phantom expense in the balance and in the
    statistics. Returns False when core couldn't be reached, to retry next
    cycle.
    """
    if synced.core_transaction_id:
        try:
            await _delete_from_core(synced.core_transaction_id)
        except Exception as e:
            logger.warning(
                "Link %s: could not remove voided pending transaction %s from core-networth: %s",
                link.label, synced.external_id, e,
            )
            return False
    logger.warning(
        "Link %s: pending transaction %s (%.2f on %s) %s -- removed from Net Worth Suite",
        link.label, synced.external_id, synced.amount, synced.entry_date, why,
    )
    synced.state = models.SyncState.VOIDED
    synced.core_transaction_id = None
    return True


async def _settle_pending(synced: "models.SyncedTransaction", t: dict, link: "models.BankLink", resolver: MccResolver) -> bool:
    """
    Brings a transaction captured while pending up to date with what the
    bank reports for it now, and stops tracking it once it's booked.

    Only what the bank can change is touched -- the amount (a tip, a hold
    settling for less, an FX conversion) and the category (an MCC that only
    arrives on booking) -- and each only while core still holds the value
    this service itself last put there. Anything you already changed by
    hand stays yours. Returns False when core couldn't be reached, so the
    cycle is counted as failed and this is retried.
    """
    synced.missing_count = 0
    status = _bank_status(t)
    if status in VOID_STATUSES:
        return await _void(synced, link, f"was cancelled by the bank ({status})")

    raw_amount = _parse_amount(t) or 0.0
    amount = round(abs(raw_amount), 2)
    direction = _direction(t, raw_amount) if amount else None

    changes: dict = {}
    if direction is not None and synced.core_transaction_id:
        signed = _signed_amount(amount, direction)
        category_id = resolver.resolve(t.get("merchant_category_code"))
        amount_changed = abs(signed - synced.amount) >= 0.005
        category_changed = category_id is not None and category_id != synced.category_id
        if amount_changed or category_changed:
            try:
                current = await _get_from_core(synced.core_transaction_id)
            except Exception as e:
                logger.warning("Link %s: could not read back transaction %s: %s", link.label, synced.external_id, e)
                return False
            if current is None:
                # Deleted by hand -- that's a decision about it, not something to undo.
                synced.state = models.SyncState.FINAL
                return True
            current_signed = _signed_amount(float(current["amount"]), current["direction"])
            if amount_changed and abs(current_signed - synced.amount) < 0.005:
                changes["amount"] = amount
                changes["direction"] = direction
            if category_changed and current.get("category_id") in (None, synced.category_id):
                changes["category_id"] = category_id
        if changes:
            try:
                await _patch_in_core(synced.core_transaction_id, changes)
            except Exception as e:
                if not _is_client_error(e):
                    logger.warning("Link %s: could not update transaction %s: %s", link.label, synced.external_id, e)
                    return False
                # Refused on its merits (e.g. it's now part of a transfer or
                # has refunds against it) -- retrying won't change that.
                logger.warning(
                    "Link %s: core-networth refused updating transaction %s with %s (%s) -- leaving it as is",
                    link.label, synced.external_id, changes, e,
                )
                synced.state = models.SyncState.FINAL
                return True
            if "amount" in changes:
                synced.amount = signed
            if "category_id" in changes:
                synced.category_id = changes["category_id"]
            logger.info("Link %s: updated pending transaction %s: %s", link.label, synced.external_id, changes)

    if status not in PENDING_STATUSES:
        synced.state = models.SyncState.FINAL
        # The booked version is new information (final amount, an MCC that
        # wasn't there while pending) -- worth its own row in the audit log.
        csv_log.log_transaction(link.label, t)
    return True


async def sync_link(db, link: "models.BankLink", resolver: MccResolver) -> int:
    """Returns how many new transactions were captured."""
    async with _sync_lock:
        return await _sync_link_locked(db, link, resolver)


async def _sync_link_locked(db, link: "models.BankLink", resolver: MccResolver) -> int:
    if link.status != models.LinkStatus.ACTIVE or not link.eb_account_id:
        return 0

    if link.valid_until and link.valid_until < datetime.utcnow():
        link.status = models.LinkStatus.EXPIRED
        db.commit()
        logger.warning("Link %s: bank consent expired -- re-authorize from the status page", link.label)
        return 0

    # First sync (no last_synced_at yet) backfills MAX_HISTORICAL_DAYS, the
    # same window the consent screen asked the bank for; later syncs just
    # re-cover since the last successful run, with a 1-day overlap buffer
    # in case a transaction posted after the last check but dated that day.
    since = (
        link.last_synced_at.date() if link.last_synced_at else date.today() - timedelta(days=MAX_HISTORICAL_DAYS)
    ) - timedelta(days=1)

    # Transactions still pending at the bank are re-read every cycle until
    # booked, so the window reaches back to the oldest of them -- except
    # ones pending for longer than PENDING_TRACK_DAYS, which stop being
    # waited on and keep what they have.
    pending_q = db.query(models.SyncedTransaction).filter(
        models.SyncedTransaction.bank_link_label == link.label,
        models.SyncedTransaction.state == models.SyncState.PENDING,
    )
    track_from = date.today() - timedelta(days=PENDING_TRACK_DAYS)
    for stale in pending_q.filter(models.SyncedTransaction.entry_date < track_from).all():
        logger.info(
            "Link %s: transaction %s still pending after %d days -- no longer waiting for it to be booked",
            link.label, stale.external_id, PENDING_TRACK_DAYS,
        )
        stale.state = models.SyncState.FINAL
    db.flush()  # the session doesn't autoflush: without this the query below still sees them as pending
    oldest_pending = min((r.entry_date for r in pending_q.all()), default=None)
    if oldest_pending is not None:
        since = min(since, oldest_pending - timedelta(days=1))

    new_count = 0
    failed_count = 0
    try:
        # Paginated: a bank can have more transactions than fit in one
        # response, in which case Enable Banking returns a
        # `continuation_key` to fetch the next page with -- looping until
        # it's absent, so a busy month can't silently lose transactions
        # past the first page.
        continuation_key = None
        all_txns = []
        while True:
            data = await enable_banking.get_transactions(
                link.eb_account_id, date_from=since.isoformat(), continuation_key=continuation_key
            )
            all_txns.extend(data.get("transactions", []))
            continuation_key = data.get("continuation_key")
            if not continuation_key:
                break

        # Counts how many times each unstable fallback id has been seen so
        # far in *this* batch, so two genuinely different transactions that
        # happen to share the same date/amount/note (no bank-assigned id to
        # tell them apart) get distinct dedupe keys instead of the second
        # one being silently treated as a re-fetch of the first.
        fallback_seen: dict[str, int] = {}
        seen_keys: set[str] = set()

        for t in all_txns:
            ext_id, is_stable = _external_id(t)
            if not is_stable:
                occurrence = fallback_seen.get(ext_id, 0)
                fallback_seen[ext_id] = occurrence + 1
                if occurrence:
                    ext_id = f"{ext_id}#{occurrence}"
            dedupe_key = f"{link.label}:{ext_id}"
            seen_keys.add(dedupe_key)
            status = _bank_status(t)

            synced = db.get(models.SyncedTransaction, dedupe_key)
            if synced is not None:
                if synced.state == models.SyncState.PENDING:
                    if not await _settle_pending(synced, t, link, resolver):
                        failed_count += 1
                    continue
                if synced.state != models.SyncState.VOIDED or status in VOID_STATUSES:
                    continue
                # A pending transaction given up as vanished has come back
                # after all -- capture it afresh, as the real one it is.
                db.delete(synced)
                db.flush()

            # Raw audit trail: every transaction JSON the bank sends for
            # this link, logged once (same dedup lifecycle as
            # SyncedTransaction below), regardless of what happens next --
            # including transactions this loop ends up skipping as
            # zero-amount or unparseable.
            csv_log.log_transaction(link.label, t)

            # Rounded here, to the same 2 decimals _push_to_core sends, so
            # that what is checked is what core-networth will actually be
            # asked to store. A sub-cent entry (an interest or FX-rounding
            # crumb) rounds to 0.00, which core rejects as non-positive --
            # checking the unrounded value let it through and then failed on
            # every cycle forever.
            raw_amount = _parse_amount(t) or 0.0
            amount = round(abs(raw_amount), 2)
            # The *signed* amount, so the sign-based fallback in _direction
            # (used only when credit_debit_indicator is missing) can tell
            # income from expense -- amount itself is always the absolute
            # value from here on.
            direction = _direction(t, raw_amount) if amount else None
            if status in VOID_STATUSES or direction is None:
                # Cancelled or rejected before we ever saw it (no money
                # moved), or nothing usable to push: an unreadable or zero
                # amount, or no way to tell which way it went.
                _mark_skipped(db, dedupe_key, link, ext_id)
                continue
            entry_date_obj = _usable_date(t, link, ext_id)
            entry_date_str = entry_date_obj.isoformat()
            note = _extract_note(t)
            counterparty = _counterparty(t, direction)
            category_id = resolver.resolve(t.get("merchant_category_code"))

            # Isolated per transaction: one rejected/failed push must not
            # stop every transaction after it in this page from being
            # processed. A failed transaction is neither logged to
            # SyncedTransaction nor counted as synced, so it stays inside
            # next cycle's `since` window and gets retried automatically.
            try:
                core_id, category_id = await _push_to_core(
                    link.cash_account_id, entry_date_str, direction, amount, note, category_id, counterparty
                )
            except Exception as e:
                failed_count += 1
                logger.warning(
                    "Link %s: failed to push transaction %s to core-networth: %s", link.label, ext_id, e
                )
                continue

            db.add(
                models.SyncedTransaction(
                    id=dedupe_key,
                    bank_link_label=link.label,
                    external_id=ext_id,
                    entry_date=entry_date_obj,
                    amount=_signed_amount(amount, direction),
                    core_transaction_id=core_id,
                    category_id=category_id,
                    counterparty=counterparty,
                    state=models.SyncState.PENDING if status in PENDING_STATUSES else models.SyncState.FINAL,
                    missing_count=0,
                )
            )
            new_count += 1

        # A pending transaction the bank stopped reporting was cancelled
        # (or re-issued under a new id once booked, which the loop above has
        # just captured as new). Only reached after a complete fetch -- an
        # interrupted one raises into the handler below instead -- and every
        # pending row lies inside the fetched window by construction of
        # `since`, so absence here really is absence at the bank.
        db.flush()
        for pending in pending_q.all():
            if pending.id in seen_keys or pending.state != models.SyncState.PENDING:
                continue
            pending.missing_count = (pending.missing_count or 0) + 1
            if pending.missing_count >= PENDING_MISSING_CYCLES:
                if not await _void(pending, link, "is no longer reported by the bank"):
                    failed_count += 1

        # Only advance the watermark past `since` when nothing failed --
        # otherwise the failed transaction's date would fall outside next
        # cycle's fetch window and be silently lost instead of retried.
        if failed_count == 0:
            link.last_synced_at = datetime.utcnow()
            link.last_error = None
        else:
            link.last_error = f"{failed_count} transaction(s) failed to sync this cycle -- will retry next cycle"
        alerts.note_sync_result(link, failed=failed_count > 0)
        db.commit()
        if failed_count == 0:
            # Only after a clean cycle: with a transaction still waiting to be
            # retried, the two balances are known to differ by it.
            await reconcile_balance(db, link)
        if new_count or failed_count:
            logger.info(
                "Link %s: captured %d new transaction(s), %d failed", link.label, new_count, failed_count
            )
        return new_count
    except Exception as e:
        link.last_error = str(e)[:2000]
        alerts.note_sync_result(link, failed=True)
        db.commit()
        logger.warning("Link %s: sync failed: %s", link.label, e)
        return 0


# Which of the balances a bank reports to compare against, best first.
# "Available" types come first: Net Worth Suite captures card payments while
# they're still pending, and an available balance already has them taken
# off, where a booked one doesn't yet. Revolut reports only ITAV.
BALANCE_TYPE_PREFERENCE = ["ITAV", "CLAV", "XPCD", "ITBD", "CLBD", "OPAV", "OPBD", "PRCD", "INFO"]


def _pick_balance(balances: list[dict]) -> tuple[float, str, str] | None:
    """(amount, currency, type) of the most useful balance, or None."""
    usable = []
    for b in balances or []:
        amount_info = b.get("balance_amount") or {}
        try:
            amount = float(amount_info.get("amount"))
        except (TypeError, ValueError):
            continue
        btype = str(b.get("balance_type") or "").upper()
        rank = BALANCE_TYPE_PREFERENCE.index(btype) if btype in BALANCE_TYPE_PREFERENCE else len(BALANCE_TYPE_PREFERENCE)
        usable.append((rank, amount, str(amount_info.get("currency") or ""), btype or "?"))
    if not usable:
        return None
    _, amount, currency, btype = min(usable, key=lambda u: u[0])
    return amount, currency, btype


async def _app_balance(link: "models.BankLink") -> tuple[float, str] | None:
    """The linked cash account's current balance as Net Worth Suite computes
    it, in the account's own currency -- from the portfolio's snapshot."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{CORE_SERVICE_URL}/portfolios/{link.portfolio_id}/snapshot")
        r.raise_for_status()
    for cash in r.json().get("cash_positions", []):
        if cash.get("account_id") == link.cash_account_id:
            return float(cash["balance"]), cash.get("currency") or ""
    return None


async def reconcile_balance(db, link: "models.BankLink") -> None:
    """
    Records the bank's balance for the account next to Net Worth Suite's
    own, so a difference -- a transaction deleted by mistake, an opening
    balance that was never right -- shows up instead of quietly persisting.
    Purely informational: it never changes anything in Net Worth Suite, and
    a failure here costs only the check, never the sync.
    """
    try:
        picked = _pick_balance((await enable_banking.get_balances(link.eb_account_id)).get("balances"))
        app = await _app_balance(link)
    except Exception as e:
        logger.warning("Link %s: could not check the balance: %s", link.label, e)
        return
    if picked is None or app is None:
        logger.info("Link %s: no balance to compare (bank: %s, app: %s)", link.label, picked, app)
        return
    link.bank_balance, link.bank_balance_currency, link.bank_balance_type = picked
    link.app_balance, link.app_balance_currency = app
    link.balance_checked_at = datetime.utcnow()
    db.commit()
    if link.bank_balance_currency == link.app_balance_currency and abs(link.bank_balance - link.app_balance) >= 0.01:
        logger.warning(
            "Link %s: the bank reports %.2f %s (%s), Net Worth Suite has %.2f",
            link.label, link.bank_balance, link.bank_balance_currency, link.bank_balance_type, link.app_balance,
        )


async def sync_all() -> dict[str, int]:
    db = SessionLocal()
    results = {}
    try:
        resolver = await build_resolver()
        links = db.query(models.BankLink).filter(models.BankLink.status == models.LinkStatus.ACTIVE).all()
        for link in links:
            results[link.label] = await sync_link(db, link, resolver)
        alerts.check_consent_expiry(db)
    finally:
        db.close()
    return results
