"""
Loads links.yaml -- the file YOU edit after downloading this project to
tell it which 4 (or however many) accounts to watch. See
links.example.yaml for the format and README.md for how to find each
value. Deliberately just a flat YAML file, not something configured
through the UI: these are one-time-setup values (which bank, which
Net Worth Suite account it feeds), not day-to-day data.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from . import models
from .config import LINKS_CONFIG_PATH

logger = logging.getLogger("bank-sync.links_config")

REQUIRED_FIELDS = ["label", "aspsp_name", "aspsp_country", "portfolio_id", "cash_account_id"]


def load_links_config() -> Optional[list[dict]]:
    """
    Returns the configured links, or None when the file itself is missing or
    unreadable.

    The distinction matters: None means "we don't know what's configured",
    while [] means "the file says: nothing". Treating the two the same made a
    bind-mount glitch or a momentarily unreadable file look like the user had
    deleted every bank, which flipped every link to REMOVED and silently
    stopped syncing until someone noticed.
    """
    path = Path(LINKS_CONFIG_PATH)
    if not path.is_file():
        # Covers both "doesn't exist yet" and the classic Docker gotcha
        # where bind-mounting a not-yet-created host file creates an empty
        # DIRECTORY at that path instead -- either way, there's nothing
        # usable here yet.
        logger.warning(
            "No links.yaml file found at %s -- copy links.example.yaml to links.yaml, fill it "
            "in, and restart this container (see README.md step 5).",
            path,
        )
        return None
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        logger.warning("links.yaml at %s could not be read (%s) -- leaving existing links untouched", path, e)
        return None
    links = raw.get("links") or []
    valid = []
    for entry in links:
        missing = [f for f in REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            logger.warning("Skipping a links.yaml entry missing field(s) %s: %r", missing, entry)
            continue
        if str(entry["portfolio_id"]).startswith("REPLACE_ME") or str(entry["cash_account_id"]).startswith("REPLACE_ME"):
            logger.warning("Skipping link %r -- portfolio_id/cash_account_id still says REPLACE_ME", entry.get("label"))
            continue
        valid.append(entry)
    return valid


def sync_links_config_to_db(db) -> None:
    """
    Reconciles links.yaml into the bank_links table: creates a row (status
    PENDING) for any label not seen before, and updates the target
    portfolio/account if you changed it in the file -- but never touches
    `status`/`session_id`/etc. for a link that's already been authorized,
    so editing links.yaml can't accidentally wipe out a working connection.

    A label that *disappears* from links.yaml is flipped to REMOVED rather
    than deleted (keeps its SyncedTransaction history valid) and excluded
    from syncing (sync_all() only ever queries ACTIVE links) -- otherwise a
    bank removed from the file kept being polled and kept creating
    transactions forever. If the same label reappears later, its previous
    authorization (session_id/eb_account_id/valid_until) was never touched
    while REMOVED, so it resumes exactly where it left off instead of
    needing to be re-authorized from scratch.
    """
    configured = load_links_config()
    if configured is None:
        # The file couldn't be read at all -- see load_links_config. Doing
        # nothing keeps existing links (and their authorizations) intact.
        return
    configured_labels = {entry["label"] for entry in configured}

    for entry in configured:
        existing = db.get(models.BankLink, entry["label"])
        if existing:
            existing.aspsp_name = entry["aspsp_name"]
            existing.aspsp_country = entry["aspsp_country"]
            existing.portfolio_id = entry["portfolio_id"]
            existing.cash_account_id = entry["cash_account_id"]
            if existing.status == models.LinkStatus.REMOVED:
                if existing.session_id and existing.eb_account_id:
                    is_expired = existing.valid_until and existing.valid_until < datetime.utcnow()
                    existing.status = models.LinkStatus.EXPIRED if is_expired else models.LinkStatus.ACTIVE
                else:
                    existing.status = models.LinkStatus.PENDING
        else:
            db.add(
                models.BankLink(
                    label=entry["label"],
                    aspsp_name=entry["aspsp_name"],
                    aspsp_country=entry["aspsp_country"],
                    portfolio_id=entry["portfolio_id"],
                    cash_account_id=entry["cash_account_id"],
                    status=models.LinkStatus.PENDING,
                )
            )

    orphaned = (
        db.query(models.BankLink)
        .filter(models.BankLink.status != models.LinkStatus.REMOVED)
        .filter(~models.BankLink.label.in_(configured_labels))
        .all()
        if configured_labels
        else db.query(models.BankLink).filter(models.BankLink.status != models.LinkStatus.REMOVED).all()
    )
    for link in orphaned:
        logger.info("Link %s: no longer in links.yaml -- marking REMOVED, excluded from syncing", link.label)
        link.status = models.LinkStatus.REMOVED

    db.commit()
