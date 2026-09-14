"""
Loads links.yaml -- the file YOU edit after downloading this project to
tell it which 4 (or however many) accounts to watch. See
links.example.yaml for the format and README.md for how to find each
value. Deliberately just a flat YAML file, not something configured
through the UI: these are one-time-setup values (which bank, which
Net Worth Suite account it feeds), not day-to-day data.
"""
import logging
from pathlib import Path

import yaml

from . import models
from .config import LINKS_CONFIG_PATH

logger = logging.getLogger("bank-sync.links_config")

REQUIRED_FIELDS = ["label", "aspsp_name", "aspsp_country", "portfolio_id", "cash_account_id"]


def load_links_config() -> list[dict]:
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
        return []
    raw = yaml.safe_load(path.read_text()) or {}
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
    """
    configured = load_links_config()
    for entry in configured:
        existing = db.get(models.BankLink, entry["label"])
        if existing:
            existing.aspsp_name = entry["aspsp_name"]
            existing.aspsp_country = entry["aspsp_country"]
            existing.portfolio_id = entry["portfolio_id"]
            existing.cash_account_id = entry["cash_account_id"]
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
    db.commit()
