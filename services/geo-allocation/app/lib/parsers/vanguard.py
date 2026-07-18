from __future__ import annotations
from typing import Dict, List, Optional

from .base import BaseParser
from ..models import AllocationResult, FundMetadata


class VanguardMarketAllocationParser(BaseParser):
    """
    Parser for Vanguard "Ripartizione di mercato" files: a table with
    columns Nazione | Regione | Fondo | Benchmark | Variazione +/-.
    We use the "Fondo" column (the fund's actual weight, not the
    benchmark's) as the country weight. Values are percentages in Italian
    format with a comma decimal separator ("61,76%").
    """

    name = "vanguard_market_allocation"

    def can_parse(self, sheets: Dict[str, List[list]]) -> bool:
        for rows in sheets.values():
            if self.find_header_row(rows, ["nazione", "fondo"]) is not None:
                return True
        return False

    def parse(self, sheets: Dict[str, List[list]], source_file: Optional[str] = None) -> AllocationResult:
        target_rows, header_idx = None, None
        for rows in sheets.values():
            idx = self.find_header_row(rows, ["nazione", "fondo"])
            if idx is not None:
                target_rows, header_idx = rows, idx
                break
        if target_rows is None:
            raise ValueError(f"{self.name}: 'Nazione'/'Fondo' header not found")

        header = [str(c).strip().lower() if c else "" for c in target_rows[header_idx]]
        col_country = next(i for i, h in enumerate(header) if "nazione" in h)
        # "Fondo" but not "Benchmark": take the first column whose header
        # is exactly "fondo" (avoids unwanted partial matches)
        col_weight = next(i for i, h in enumerate(header) if h == "fondo")

        weights: Dict[str, float] = {}
        unmapped: Dict[str, float] = {}
        for row in target_rows[header_idx + 1:]:
            if col_country >= len(row):
                continue
            country = row[col_country]
            if country is None or str(country).strip() == "":
                continue
            weight = self.parse_weight(row[col_weight]) if col_weight < len(row) else None
            if weight is None:
                continue
            self.accumulate_country_weight(weights, unmapped, country, weight)

        # fund name / as-of date, from the header rows above the table
        fund_name, as_of = None, None
        for row in target_rows[:header_idx]:
            for cell in row:
                if isinstance(cell, str) and "UCITS ETF" in cell:
                    fund_name = cell.strip()
                if isinstance(cell, str) and cell.lower().startswith("al "):
                    as_of = cell.strip()

        meta = FundMetadata(
            fund_name=fund_name,
            as_of_date=as_of,
            source_provider="vanguard",
            source_file=source_file,
            parser_name=self.name,
        )
        return self.build_result(weights, unmapped, meta)
