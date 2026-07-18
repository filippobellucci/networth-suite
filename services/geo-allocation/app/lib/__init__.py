"""
fund_allocation_parser
=======================

Library to extract and aggregate, by country, the geographic allocations
disclosed in the Excel files published by fund/ETF issuers (Amundi,
Vanguard, iShares, ...).

Quick usage
-----------
    from fund_allocation_parser import parse_file

    result = parse_file("my_fund.xlsx")
    print(result.weights)          # {'US': 0.7255, 'JP': 0.0567, ...}
    print(result.as_percentages()) # {'US': 72.55, 'JP': 5.67, ...}

Every parser always returns a {ISO_3166-1_alpha-2_code: weight} map, with
the weight expressed as a fraction between 0 and 1. Normalization of
country names (Italian/English/other variants) to an ISO code is
centralized in ``countries.py`` so that weights coming from different
sources, in different languages, can be summed together unambiguously.
"""

from .models import AllocationResult, FundMetadata
from .exceptions import (
    FundAllocationParserError,
    NoParserFoundError,
    UnreadableFileError,
)
from .registry import parse_file, parse_bytes, register_parser, get_parsers
from .aggregator import aggregate

__all__ = [
    "AllocationResult",
    "FundMetadata",
    "FundAllocationParserError",
    "NoParserFoundError",
    "UnreadableFileError",
    "parse_file",
    "parse_bytes",
    "register_parser",
    "get_parsers",
    "aggregate",
]

__version__ = "0.1.0"
