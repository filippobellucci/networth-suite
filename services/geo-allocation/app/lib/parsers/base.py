from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from ..countries import normalize_country, SPECIAL_OTHER
from ..models import AllocationResult, FundMetadata


class BaseParser(ABC):
    """
    Contract that every issuer-specific parser must implement.

    ``can_parse`` must be cheap and based exclusively on the structure of
    the already-read workbook (sheet names / expected headers), NEVER on
    the file name, to stay robust against renaming.
    """

    name: str = "base"

    @abstractmethod
    def can_parse(self, sheets: Dict[str, List[list]]) -> bool:
        ...

    @abstractmethod
    def parse(self, sheets: Dict[str, List[list]], source_file: Optional[str] = None) -> AllocationResult:
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def find_header_row(rows: List[list], required_headers: List[str], max_scan: int = 60) -> Optional[int]:
        """Returns the index of the first row that contains (case-insensitive,
        as a substring) all the required labels, in any column."""
        wanted = [h.lower() for h in required_headers]
        for i, row in enumerate(rows[:max_scan]):
            cells = [str(c).strip().lower() for c in row if c is not None]
            if all(any(w in c for c in cells) for w in wanted):
                return i
        return None

    @staticmethod
    def parse_weight(value, force_percent: bool = False) -> Optional[float]:
        """Converts a weight cell to a 0..1 fraction, handling:
        - values already given as a fraction (0.72)
        - values given in "percentage points" (72.5 -> 0.725) when > 1.5
        - percentage strings with a comma or dot decimal separator
          ("61,76%", "61.76%")

        ``force_percent=True`` must be used when the source column is
        explicitly labeled as a percentage (e.g. "Ponderazione (%)") and
        contains plain numeric values: in that case the ">1.5" heuristic
        cannot be relied upon, because with per-security (holdings) data
        the individual weight is almost always < 1.5 while still being
        expressed in percentage points (e.g. 1.27 means 1.27%, not 127%),
        unlike a table that is already aggregated by country.
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            v = float(value)
            if force_percent:
                return v / 100.0
            return v / 100.0 if v > 1.5 else v
        s = str(value).strip()
        if s == "":
            return None
        is_pct = "%" in s
        s = s.replace("%", "").replace(" ", "")
        # Italian number format: dot = thousands separator, comma = decimal
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", ".")
        try:
            v = float(s)
        except ValueError:
            return None
        if is_pct:
            return v / 100.0
        return v / 100.0 if v > 1.5 else v

    @classmethod
    def accumulate_country_weight(
        cls,
        bucket: Dict[str, float],
        unmapped: Dict[str, float],
        country_label,
        weight: Optional[float],
    ) -> None:
        if weight is None:
            return
        code = normalize_country(country_label)
        if code is None:
            key = str(country_label).strip()
            unmapped[key] = unmapped.get(key, 0.0) + weight
            return
        bucket[code] = bucket.get(code, 0.0) + weight

    @staticmethod
    def build_result(
        weights: Dict[str, float],
        unmapped: Dict[str, float],
        metadata: FundMetadata,
    ) -> AllocationResult:
        # drop numeric noise and near-zero-weight keys
        cleaned = {k: v for k, v in weights.items() if abs(v) > 1e-12}
        return AllocationResult(weights=cleaned, metadata=metadata, unmapped_labels=unmapped)
