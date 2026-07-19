"""
Extra country-label aliases seen in real factsheets that the vendored
`fund_allocation_parser` library doesn't recognize out of the box (different
spelling/phrasing than what it already maps). Uses the library's own
`register_country_alias()` extension point, so the vendored library itself
stays untouched and easy to update later.

Add new entries here whenever an upload reports an unmapped country label.
"""
from .lib.countries import register_country_alias

EXTRA_ALIASES = {
    "corea": "KR",            # iShares factsheets sometimes shorten "Corea del Sud" to just "Corea"
    "sud africa": "ZA",       # two-word variant; the library already has the one-word "sudafrica"
    "tailandia": "TH",        # Italian spelling without the "h"; the library already has "thailandia"
}


def apply_extra_aliases() -> None:
    for label, iso2 in EXTRA_ALIASES.items():
        register_country_alias(label, iso2)
