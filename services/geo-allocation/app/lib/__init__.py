"""
fund_allocation_parser
=======================

Library to extract and aggregate, by country, the geographic allocations
disclosed in the Excel files published by fund/ETF issuers (Amundi,
Vanguard, iShares, ...).

Every parser always returns a {ISO_3166-1_alpha-2_code: weight} map, with
the weight expressed as a fraction between 0 and 1. Normalization of
country names (Italian/English/other variants) to an ISO code is
centralized in ``countries.py`` so that weights coming from different
sources, in different languages, can be summed together unambiguously --
and ``countries.register_country_alias`` is the one extension point this
library still exposes (see app/country_aliases.py, its only user).
"""

from .models import AllocationResult, FundMetadata
from .exceptions import (
    FundAllocationParserError,
    NoParserFoundError,
    UnreadableFileError,
)
from .registry import parse_bytes
from .aggregator import aggregate

__all__ = [
    "AllocationResult",
    "FundMetadata",
    "FundAllocationParserError",
    "NoParserFoundError",
    "UnreadableFileError",
    "parse_bytes",
    "aggregate",
]
