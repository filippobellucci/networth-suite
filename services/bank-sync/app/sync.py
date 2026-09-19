"""
The actual "watch a bank, create expenses automatically" logic. Each
ACTIVE link gets its transactions re-fetched (Enable Banking returns
transactions for a date range, not "what's new since last time"), and
SyncedTransaction is what keeps a second sync from creating the same
expense twice.

Every auto-captured transaction lands in core-networth with no category
(see CHANGELOG.md's Refund/Transaction entries for why that was the
explicit design choice) -- you tag it afterward in the Expenses page,
same as you would any manually-logged one.
"""
import asyncio
import logging
from datetime import datetime, date, timedelta

import httpx

from . import models, enable_banking, csv_log
from .database import SessionLocal
from .config import CORE_SERVICE_URL, MAX_HISTORICAL_DAYS
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


async def _push_to_core(cash_account_id: str, entry_date: str, direction: str, amount: float, note: str, category_id: str | None) -> str:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{CORE_SERVICE_URL}/cash-accounts/{cash_account_id}/transactions",
            json={
                "entry_date": entry_date,
                "direction": direction,
                "amount": round(amount, 2),
                "note": note or None,
                "category_id": category_id,
            },
        )
        r.raise_for_status()
        return r.json()["id"]


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
    new_count = 0
    failed_count = 0
    try:
        # Paginated: a bank can have more transactions than fit in one
        # response, in which case Enable Banking returns a
        # `continuation_key` to fetch the next page with -- looping until
        # it's absent, so a busy month can't silently lose transactions
        # past the first page.
        # Known limitation, not fixed here: if Enable Banking reports a
        # transaction while still PENDING (often without a stable id yet)
        # and again once BOOKED (with a real id assigned), the id-less
        # fallback branch of _external_id could generate two different
        # dedupe keys for the same real-world transaction, syncing it
        # twice. Filtering on booking status would need Enable Banking's
        # exact field name for it, which -- like the rest of this module,
        # see enable_banking.py's honesty note -- isn't verified against a
        # live account; guessing a wrong field name risks silently
        # dropping *every* transaction (if the guessed field is always
        # absent) rather than the rarer double-sync this would prevent, so
        # this is intentionally left as a known gap rather than guessed at.
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

        for t in all_txns:
            ext_id, is_stable = _external_id(t)
            if not is_stable:
                occurrence = fallback_seen.get(ext_id, 0)
                fallback_seen[ext_id] = occurrence + 1
                if occurrence:
                    ext_id = f"{ext_id}#{occurrence}"
            dedupe_key = f"{link.label}:{ext_id}"
            if db.get(models.SyncedTransaction, dedupe_key):
                continue

            # Raw audit trail: every transaction JSON the bank sends for
            # this link, logged once (same dedup lifecycle as
            # SyncedTransaction below), regardless of what happens next --
            # including transactions this loop ends up skipping as
            # zero-amount or unparseable.
            csv_log.log_transaction(link.label, t)

            amt_info = t.get("transaction_amount") or {}
            try:
                raw_amount = float(amt_info.get("amount", 0))
            except (TypeError, ValueError):
                continue
            amount = abs(raw_amount)
            if amount == 0:
                continue

            # Pass the *signed* amount through so the sign-based fallback in
            # _direction (used only when credit_debit_indicator is missing)
            # can actually distinguish income from expense -- amount itself
            # is always the absolute value from here on.
            direction = _direction(t, raw_amount)
            if direction is None:
                continue
            entry_date_str = t.get("booking_date") or t.get("value_date") or date.today().isoformat()
            try:
                entry_date_obj = date.fromisoformat(entry_date_str)
            except ValueError:
                entry_date_obj = date.today()
            note = _extract_note(t)
            category_id = resolver.resolve(t.get("merchant_category_code"))

            # Isolated per transaction: one rejected/failed push must not
            # stop every transaction after it in this page from being
            # processed. A failed transaction is neither logged to
            # SyncedTransaction nor counted as synced, so it stays inside
            # next cycle's `since` window and gets retried automatically.
            try:
                core_id = await _push_to_core(
                    link.cash_account_id, entry_date_str, direction, amount, note, category_id
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
                    amount=amount if direction == "INCOME" else -amount,
                    core_transaction_id=core_id,
                )
            )
            new_count += 1

        # Only advance the watermark past `since` when nothing failed --
        # otherwise the failed transaction's date would fall outside next
        # cycle's fetch window and be silently lost instead of retried.
        if failed_count == 0:
            link.last_synced_at = datetime.utcnow()
            link.last_error = None
        else:
            link.last_error = f"{failed_count} transaction(s) failed to sync this cycle -- will retry next cycle"
        db.commit()
        if new_count or failed_count:
            logger.info(
                "Link %s: captured %d new transaction(s), %d failed", link.label, new_count, failed_count
            )
        return new_count
    except Exception as e:
        link.last_error = str(e)[:2000]
        db.commit()
        logger.warning("Link %s: sync failed: %s", link.label, e)
        return 0


async def sync_all() -> dict[str, int]:
    db = SessionLocal()
    results = {}
    try:
        resolver = await build_resolver()
        links = db.query(models.BankLink).filter(models.BankLink.status == models.LinkStatus.ACTIVE).all()
        for link in links:
            results[link.label] = await sync_link(db, link, resolver)
    finally:
        db.close()
    return results
