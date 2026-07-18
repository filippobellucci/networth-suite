from __future__ import annotations
from typing import Dict, List, Optional

from .base import BaseParser
from ..models import AllocationResult, FundMetadata


class ISharesHoldingsParser(BaseParser):
    """
    Parser for iShares/BlackRock "Fund Holdings" files (sheet
    "Partecipazioni" or "Holdings"): a security-by-security list with
    "Area Geografica"/"Location" and "Ponderazione (%)"/"Weight (%)"
    columns. There is no country-aggregated sheet: the allocation is
    obtained by summing the weight of each individual security by
    geographic area.
    """

    name = "ishares_holdings"
    CANDIDATE_SHEETS = ("Partecipazioni", "Holdings", "All Holdings")

    def _find_sheet(self, sheets: Dict[str, List[list]]):
        for name in self.CANDIDATE_SHEETS:
            if name in sheets:
                idx = self.find_header_row(sheets[name], ["area geografica", "ponderazione"])
                if idx is not None:
                    return name, idx
                idx = self.find_header_row(sheets[name], ["location", "weight"])
                if idx is not None:
                    return name, idx
        for name, rows in sheets.items():
            idx = self.find_header_row(rows, ["area geografica", "ponderazione"])
            if idx is not None:
                return name, idx
            idx = self.find_header_row(rows, ["location", "weight"])
            if idx is not None:
                return name, idx
        return None, None

    def can_parse(self, sheets: Dict[str, List[list]]) -> bool:
        name, _ = self._find_sheet(sheets)
        return name is not None

    def parse(self, sheets: Dict[str, List[list]], source_file: Optional[str] = None) -> AllocationResult:
        sheet_name, header_idx = self._find_sheet(sheets)
        if sheet_name is None:
            raise ValueError(f"{self.name}: no sheet with area/weight columns found")

        rows = sheets[sheet_name]
        header = [str(c).strip().lower() if c else "" for c in rows[header_idx]]

        col_country = next(
            (i for i, h in enumerate(header) if "area geografica" in h or h == "location"), None
        )
        col_weight = next(
            (i for i, h in enumerate(header) if "ponderazione" in h or "weight" in h), None
        )
        if col_country is None or col_weight is None:
            raise ValueError(f"{self.name}: expected columns not found in header {header}")

        weights: Dict[str, float] = {}
        unmapped: Dict[str, float] = {}
        for row in rows[header_idx + 1:]:
            if col_country >= len(row):
                continue
            country = row[col_country]
            # the column is explicitly "Ponderazione (%)": numeric values
            # are always percentage points, even when < 1.5 (small holdings)
            weight = self.parse_weight(row[col_weight], force_percent=True) if col_weight < len(row) else None
            if weight is None:
                continue
            self.accumulate_country_weight(weights, unmapped, country, weight)

        fund_name, isin, as_of = None, None, None
        for sname in sheets:
            if sname.lower() in ("introduzione", "introduction", "overview"):
                for row in sheets[sname]:
                    cells = [c for c in row if c not in (None, "")]
                    if len(cells) >= 2 and isinstance(cells[0], str):
                        label = cells[0].lower()
                        if label == "isin":
                            isin = str(cells[1])
        for row in rows[:header_idx]:
            cells = [c for c in row if c not in (None, "")]
            if len(cells) == 1 and isinstance(cells[0], str) and "ishares" in cells[0].lower():
                fund_name = cells[0].strip()
            if len(cells) >= 2 and isinstance(cells[0], str) and "holdings as of" in cells[0].lower():
                as_of = str(cells[1])

        meta = FundMetadata(
            fund_name=fund_name,
            isin=isin,
            as_of_date=as_of,
            source_provider="ishares",
            source_file=source_file,
            parser_name=self.name,
        )
        return self.build_result(weights, unmapped, meta)
