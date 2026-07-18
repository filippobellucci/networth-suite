from __future__ import annotations
from typing import Dict, List, Optional

from .base import BaseParser
from ..models import AllocationResult, FundMetadata


class AmundiIndexCompositionParser(BaseParser):
    """
    Parser for Amundi "Composizione dell'indice ... " files, which contain
    a dedicated "Ripartizione Geografica" sheet with a two-column table:
    Paesi | Peso (already a country-aggregated breakdown).
    """

    name = "amundi_index_composition"
    SHEET_NAME = "Ripartizione Geografica"

    def can_parse(self, sheets: Dict[str, List[list]]) -> bool:
        return self.SHEET_NAME in sheets

    def parse(self, sheets: Dict[str, List[list]], source_file: Optional[str] = None) -> AllocationResult:
        rows = sheets[self.SHEET_NAME]
        header_idx = self.find_header_row(rows, ["paesi", "peso"])
        if header_idx is None:
            raise ValueError(f"{self.name}: 'Paesi'/'Peso' header not found")

        header = [str(c).strip().lower() if c else "" for c in rows[header_idx]]
        col_country = next(i for i, h in enumerate(header) if "paes" in h)
        col_weight = next(i for i, h in enumerate(header) if "peso" in h)

        weights: Dict[str, float] = {}
        unmapped: Dict[str, float] = {}
        for row in rows[header_idx + 1:]:
            if col_country >= len(row):
                continue
            country = row[col_country]
            if country is None or str(country).strip() == "":
                continue
            weight_raw = row[col_weight] if col_weight < len(row) else None
            weight = self.parse_weight(weight_raw)
            if weight is None:
                # long legal-notice rows after the table: stop only if the
                # "weight" cell isn't numeric at all and the text is long
                if isinstance(country, str) and len(country) > 80:
                    break
                continue
            self.accumulate_country_weight(weights, unmapped, country, weight)

        meta = FundMetadata(
            source_provider="amundi",
            source_file=source_file,
            parser_name=self.name,
        )
        # fund/index name, if present in the rows above the table
        for row in rows[:header_idx]:
            cells = [c for c in row if c]
            if len(cells) >= 2 and isinstance(cells[0], str) and "indice" in cells[0].lower():
                meta.fund_name = str(cells[1])

        return self.build_result(weights, unmapped, meta)


class AmundiHoldingsParser(BaseParser):
    """
    Parser for Amundi "Titoli detenuti dal fondo" files: a security-by-
    security list with a "Paese" (country) column and a "Peso" (weight,
    0..1 fraction) column per individual security. The country-level
    allocation is obtained by summing the weights of the individual
    securities by country.
    """

    name = "amundi_holdings"
    SHEET_NAME = "Titoli detenuti dal fondo"

    def can_parse(self, sheets: Dict[str, List[list]]) -> bool:
        return self.SHEET_NAME in sheets

    def parse(self, sheets: Dict[str, List[list]], source_file: Optional[str] = None) -> AllocationResult:
        rows = sheets[self.SHEET_NAME]
        header_idx = self.find_header_row(rows, ["paese", "peso"])
        if header_idx is None:
            raise ValueError(f"{self.name}: 'Paese'/'Peso' header not found")

        header = [str(c).strip().lower() if c else "" for c in rows[header_idx]]
        col_country = next(i for i, h in enumerate(header) if h == "paese" or "paese" in h)
        col_weight = next(i for i, h in enumerate(header) if h == "peso" or "peso" in h)
        col_name = next((i for i, h in enumerate(header) if "nome" in h), None)
        col_isin = next((i for i, h in enumerate(header) if "isin" in h), None)

        weights: Dict[str, float] = {}
        unmapped: Dict[str, float] = {}
        fund_name = None

        for row in rows[header_idx + 1:]:
            if col_country >= len(row):
                continue
            country = row[col_country]
            weight = self.parse_weight(row[col_weight]) if col_weight < len(row) else None
            if weight is None:
                continue
            self.accumulate_country_weight(weights, unmapped, country, weight)

        for row in rows[:header_idx]:
            cells = [c for c in row if c]
            if len(cells) >= 2 and isinstance(cells[0], str) and "nome del fondo" in cells[0].lower():
                fund_name = str(cells[1])

        isin = None
        for row in rows[:header_idx]:
            cells = [c for c in row if c]
            if len(cells) >= 2 and isinstance(cells[0], str) and "isin" in cells[0].lower():
                isin = str(cells[1])

        meta = FundMetadata(
            fund_name=fund_name,
            isin=isin,
            source_provider="amundi",
            source_file=source_file,
            parser_name=self.name,
        )
        return self.build_result(weights, unmapped, meta)
