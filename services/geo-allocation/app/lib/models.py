from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class FundMetadata:
    """Optional fund/ETF metadata, when it can be inferred from the file."""

    fund_name: Optional[str] = None
    isin: Optional[str] = None
    as_of_date: Optional[str] = None          # as stated in the file, not normalized
    source_provider: Optional[str] = None      # e.g. "amundi", "vanguard", "ishares"
    source_file: Optional[str] = None
    parser_name: Optional[str] = None          # name of the parser that produced the result

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class AllocationResult:
    """
    Result of a parse operation: geographic allocation normalized by country.

    ``weights`` is the {ISO 3166-1 alpha-2 code: fractional weight 0..1} map.
    Special codes reserved for non-country buckets (see countries.py):
      - "XX" = unclassifiable / cash / entries that could not be mapped
      - "EU" = "European Union" reported as such without a specific country
    """

    weights: Dict[str, float] = field(default_factory=dict)
    metadata: FundMetadata = field(default_factory=FundMetadata)
    unmapped_labels: Dict[str, float] = field(default_factory=dict)
    """Country labels found in the file that were NOT recognized by
    countries.normalize_country, with their weight. Useful for QA:
    if this dict is non-empty, total_weight() will be less than 1 by that
    amount, unless the labels ended up in the 'XX' bucket anyway."""

    def total_weight(self) -> float:
        return round(sum(self.weights.values()), 10)

    def to_dict(self) -> dict:
        return {
            "metadata": self.metadata.to_dict(),
            "weights": self.weights,
            "unmapped_labels": self.unmapped_labels,
            "total_weight": self.total_weight(),
        }
