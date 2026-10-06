"""Shared helpers used by more than one router in `routers/`: lookups,
pagination, and the Idempotency-Key machinery for financial-mutation POSTs."""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models

logger = logging.getLogger("core-networth")


def _get_or_404(db: Session, model, row_id: str, label: str):
    """The row with this id, or a 404 saying which kind of thing wasn't found."""
    row = db.get(model, row_id)
    if not row:
        raise HTTPException(404, f"{label} not found")
    return row


def _paginate(query, limit: Optional[int], offset: int):
    """Shared by every list endpoint that accepts `limit`/`offset`: both are
    optional, and omitting `limit` returns every matching row."""
    query = query.offset(offset)
    return query.limit(limit) if limit is not None else query


# ---------------------------------------------------------------- Idempotency
# Optional `Idempotency-Key` header support for the financial-mutation POSTs
# most at risk from a client retrying a request it's unsure went through
# (create_cash_transaction, create_transfer, add_holding_entry): replaying
# the exact same key for the same endpoint returns the original response
# instead of creating a second transaction/transfer/holding entry. Without
# the header nothing changes.
IDEMPOTENCY_TTL_HOURS = 24


def _replay_or_conflict(db: Session, key: str, endpoint: str) -> Optional[dict]:
    """The stored response for a key already used, None if the key is not in
    use at all, or the reason it can't be replayed."""
    existing = db.get(models.IdempotencyKey, key)
    if existing is None:
        # Pruned by another request's cleanup between the two statements.
        # Nothing left to replay; let the caller run normally.
        return None
    if existing.endpoint != endpoint:
        # Same key, different operation: refused before touching anything,
        # rather than running the mutation and then failing on the key.
        raise HTTPException(409, "This Idempotency-Key was already used for a different operation")
    if not existing.response_body:
        # Reserved but not yet filled in: the original request committed its
        # mutation and is a statement away from recording the response.
        raise HTTPException(409, "A request with this Idempotency-Key is still being processed -- retry shortly")
    return json.loads(existing.response_body)


def _check_idempotency(db: Session, key: Optional[str], endpoint: str) -> Optional[dict]:
    if not key:
        return None
    # Opportunistic cleanup on each use -- cheap at personal-finance request
    # volumes, and avoids needing a separate scheduled job just for this.
    cutoff = datetime.utcnow() - timedelta(hours=IDEMPOTENCY_TTL_HOURS)
    db.query(models.IdempotencyKey).filter(models.IdempotencyKey.created_at < cutoff).delete()
    return _replay_or_conflict(db, key, endpoint)


def _commit_with_idempotency(db: Session, key: Optional[str], endpoint: str) -> Optional[dict]:
    """
    Commits the mutation together with its idempotency key, in the SAME
    transaction: whichever of two concurrent requests with one key commits
    first owns it, and the loser's INSERT violates the primary key, so its
    mutation rolls back with it instead of landing as a duplicate. The
    response body is filled in right afterwards (see _store_idempotency); a
    replay arriving in that gap is told to retry.

    Returns None when this request's own commit went through, or the
    response another request already stored when it won the key. An
    IntegrityError that is not about the key is re-raised untouched.
    """
    if key:
        db.add(models.IdempotencyKey(key=key, endpoint=endpoint, response_body=""))
    try:
        db.commit()
        return None
    except IntegrityError:
        db.rollback()
        replayed = _replay_or_conflict(db, key, endpoint) if key else None
        if replayed is None:
            raise
        logger.info("Idempotency key %r was already committed by a concurrent request; replaying it", key)
        return replayed


def _store_idempotency(db: Session, key: Optional[str], endpoint: str, response_dict: dict) -> None:
    """Fills in the response for the key reserved above, once the mutation's
    commit has produced it."""
    if not key:
        return
    row = db.get(models.IdempotencyKey, key)
    if row is None:
        # Pruned in the moment between the two commits -- rare, and only
        # costs this key its ability to replay.
        logger.warning("Idempotency key %r disappeared before its response could be recorded", key)
        return
    row.response_body = json.dumps(response_dict)
    db.commit()
