from __future__ import annotations
import math
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from ..countries import normalize_country
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
          (or always, if force_percent=True)
        - percentage strings with a comma or dot decimal separator
          ("61,76%", "61.76%") -- always treated as percentage points
          regardless of force_percent, since the "%" is unambiguous
        - a NaN float (e.g. an Excel #REF!/#DIV/0! error cell surfaced as
          NaN by the reader) -- treated as "no value", like an empty cell

        ``force_percent=True`` must be used when the source column is
        explicitly labeled as a percentage (e.g. "Ponderazione (%)") and
        contains plain numeric values: in that case the ">1.5" heuristic
        cannot be relied upon, because with per-security (holdings) data
        the individual weight is almost always < 1.5 while still being
        expressed in percentage points (e.g. 1.27 means 1.27%, not 127%).
        See parse_weight_column for the equivalent decision made once for
        a whole *aggregated* (country-level) column instead of per cell.
        """
        if value is None:
            return None
        is_pct = False
        if isinstance(value, (int, float)):
            if isinstance(value, float) and math.isnan(value):
                return None
            v = float(value)
        else:
            s = str(value).strip()
            if s == "":
                return None
            is_pct = "%" in s
            s = s.replace("%", "").replace(" ", "")
            if "," in s and "." in s:
                # Both separators present -- whichever appears LAST is the
                # decimal point, the other is a thousands grouping to strip.
                # Unconditionally assuming Italian format (dot=thousands,
                # comma=decimal) here previously mis-parsed an English-style
                # value like "1,234.56" (meaning 1234.56) as "1.234".
                # Weight cells are essentially always < 100 in practice, so
                # this rarely triggers either way, but stays correct for
                # both conventions instead of hard-coding one.
                last_comma = s.rfind(",")
                last_dot = s.rfind(".")
                s = s.replace(".", "").replace(",", ".") if last_comma > last_dot else s.replace(",", "")
            else:
                s = s.replace(",", ".")
            try:
                v = float(s)
            except ValueError:
                return None
            if math.isnan(v):
                return None
        if is_pct or force_percent:
            return v / 100.0
        return v / 100.0 if v > 1.5 else v

    @staticmethod
    def parse_weight_column(raw_values: List) -> List[Optional[float]]:
        """Like parse_weight, but decides the numeric scale (fraction vs.
        percentage-points) once for the whole column instead of per cell --
        meant for an *aggregated country-level* table (one row per country),
        not a per-holding one.

        The plain per-cell ">1.5" heuristic in parse_weight silently breaks
        there when a country's weight is itself small (e.g. 0.8, meaning
        0.8%): read alone that number looks just like an already-a-fraction
        value and is left unscaled instead of divided by 100, inflating
        that one country's exposure ~100x.

        A whole table of country weights gives a much more reliable signal
        than any single cell: any real geographic allocation almost always
        has at least one country/region above 1.5% of the fund, so if *any*
        plain numeric cell in the column exceeds 1.5, every plain numeric
        cell in it is treated as percentage points. Cells already given as
        an explicit "61,76%" string are unaffected either way -- those are
        unambiguous regardless of the rest of the column.
        """
        def _plain_numeric(v) -> Optional[float]:
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return None if (isinstance(v, float) and math.isnan(v)) else float(v)
            s = str(v).strip()
            if not s or "%" in s:
                return None  # empty, or an explicit percent string handled separately
            try:
                n = float(s.replace(",", "."))
            except ValueError:
                return None
            return None if math.isnan(n) else n

        column_is_percentage_scale = any((n := _plain_numeric(v)) is not None and n > 1.5 for v in raw_values)
        return [BaseParser.parse_weight(v, force_percent=column_is_percentage_scale) for v in raw_values]

    @classmethod
    def accumulate_country_weight(
        cls,
        bucket: Dict[str, float],
        unmapped: Dict[str, float],
        country_label,
        weight: Optional[float],
    ) -> None:
        if weight is None or (isinstance(weight, float) and math.isnan(weight)):
            # A NaN weight (e.g. an Excel #REF!/#DIV/0! error cell surfaced
            # as a float by the reader) must never reach the running sum --
            # `nan + x` poisons the whole bucket to NaN, and build_result's
            # `abs(v) > 1e-12` cleanup then silently drops that ENTIRE
            # country/region, not just this one bad row.
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
