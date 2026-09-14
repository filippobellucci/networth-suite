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
import logging
from datetime import datetime, date, timedelta

import httpx

from . import models, enable_banking
from .database import SessionLocal
from .config import CORE_SERVICE_URL
from .mcc_categories import MccResolver, build_resolver

logger = logging.getLogger("bank-sync.sync")


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


def _external_id(txn: dict) -> str:
    return (
        txn.get("entry_reference")
        or txn.get("transaction_id")
        or f"{txn.get('booking_date')}:{(txn.get('transaction_amount') or {}).get('amount')}:{_extract_note(txn)}"
    )


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
    if link.status != models.LinkStatus.ACTIVE or not link.eb_account_id:
        return 0

    if link.valid_until and link.valid_until < datetime.utcnow():
        link.status = models.LinkStatus.EXPIRED
        db.commit()
        logger.warning("Link %s: bank consent expired -- re-authorize from the status page", link.label)
        return 0

    since = (link.last_synced_at.date() if link.last_synced_at else date.today() - timedelta(days=7)) - timedelta(days=1)
    new_count = 0
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

        for t in all_txns:
            ext_id = _external_id(t)
            dedupe_key = f"{link.label}:{ext_id}"
            if db.get(models.SyncedTransaction, dedupe_key):
                continue

            amt_info = t.get("transaction_amount") or {}
            try:
                amount = abs(float(amt_info.get("amount", 0)))
            except (TypeError, ValueError):
                continue
            if amount == 0:
                continue

            direction = _direction(t, amount)
            if direction is None:
                continue
            entry_date_str = t.get("booking_date") or t.get("value_date") or date.today().isoformat()
            try:
                entry_date_obj = date.fromisoformat(entry_date_str)
            except ValueError:
                entry_date_obj = date.today()
            note = _extract_note(t)
            category_id = resolver.resolve(t.get("merchant_category_code"))

            core_id = await _push_to_core(link.cash_account_id, entry_date_str, direction, amount, note, category_id)

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

        link.last_synced_at = datetime.utcnow()
        link.last_error = None
        db.commit()
        if new_count:
            logger.info("Link %s: captured %d new transaction(s)", link.label, new_count)
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
