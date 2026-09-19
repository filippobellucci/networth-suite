"""
Automatic categorization from the bank's own merchant_category_code (MCC),
a standardized code (ISO 18245) most banks/card networks attach to card
transactions -- e.g. "5411" is always "Grocery Stores/Supermarkets",
regardless of which bank or country. See mcc_categories.example.yaml for
the format and mcc_reference.md for a reference table of common codes.

This only maps a code to one of *your own* category NAMES (as already
created in Expense Categories) -- it never creates categories itself, and
a code with no mapping (or mapped to a category name that doesn't exist)
simply leaves the transaction uncategorized, same as before this feature
existed. Nothing here is required; an empty/missing mcc_categories.yaml
means every transaction stays uncategorized, exactly like before.
"""
import logging

import httpx
import yaml

from .config import CORE_SERVICE_URL, DATA_DIR

logger = logging.getLogger("bank-sync.mcc_categories")

# Derived from DATA_DIR (like LINKS_CONFIG_PATH in config.py) instead of a
# hardcoded "/data/..." path, so a deployment that overrides DATA_DIR via
# the environment doesn't silently lose access to this file.
MCC_CONFIG_PATH = DATA_DIR / "mcc_categories.yaml"


def load_mcc_mapping() -> dict[str, str]:
    """Returns {mcc_code: category_name}, both as given in the file."""
    if not MCC_CONFIG_PATH.is_file():
        return {}
    raw = yaml.safe_load(MCC_CONFIG_PATH.read_text()) or {}
    mappings = raw.get("mcc_mappings") or {}
    # YAML may parse a bare numeric-looking code as an int -- normalize to
    # string since that's how Enable Banking sends merchant_category_code.
    return {str(k): str(v) for k, v in mappings.items()}


async def fetch_category_name_to_id() -> dict[str, str]:
    """Live lookup against core-networth's own categories -- not cached
    across sync cycles, so renaming/deleting a category in Net Worth Suite
    is picked up on the very next sync without restarting this service."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{CORE_SERVICE_URL}/expense-categories")
        r.raise_for_status()
        categories = r.json()
    # Case-insensitive, since it's easy to type "groceries" in the YAML
    # file when the category is actually named "Groceries".
    return {c["name"].strip().lower(): c["id"] for c in categories}


class MccResolver:
    """
    Built once per sync cycle (see sync.py) so every link in that cycle
    shares the same category lookups instead of re-fetching
    /expense-categories once per transaction.
    """

    def __init__(self, mcc_to_name: dict[str, str], name_to_id: dict[str, str]):
        self._mcc_to_name = mcc_to_name
        self._name_to_id = name_to_id

    def resolve(self, merchant_category_code: str | None) -> str | None:
        if not merchant_category_code:
            return None
        category_name = self._mcc_to_name.get(str(merchant_category_code))
        if not category_name:
            return None
        category_id = self._name_to_id.get(category_name.strip().lower())
        if not category_id:
            logger.warning(
                "MCC %s maps to category %r in mcc_categories.yaml, but no category with that "
                "name exists in Net Worth Suite -- leaving uncategorized. Check spelling, or "
                "create the category first.",
                merchant_category_code,
                category_name,
            )
        return category_id


async def build_resolver() -> MccResolver:
    mcc_to_name = load_mcc_mapping()
    if not mcc_to_name:
        return MccResolver({}, {})
    name_to_id = await fetch_category_name_to_id()
    return MccResolver(mcc_to_name, name_to_id)
