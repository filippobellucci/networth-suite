"""
Reader for the "SpreadsheetML" format (Excel 2003 XML Spreadsheet).

Some issuers (e.g. iShares/BlackRock) distribute files with a ``.xls``
extension that are actually a single XML document using the
``urn:schemas-microsoft-com:office:spreadsheet`` namespace, and not a real
binary BIFF file nor a real .xlsx (zip) file. Neither ``xlrd`` nor
``python-calamine`` can read it, so here we use a dedicated XML parser,
minimal but sufficient to reconstruct rows/columns for every sheet,
including cells "skipped" via the ``ss:Index`` attribute (used to compress
empty cells).
"""
from __future__ import annotations
from typing import Dict, List
import xml.etree.ElementTree as ET

_NS = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}


def sniff(head_bytes: bytes) -> bool:
    """True if the first bytes of the file indicate a SpreadsheetML document."""
    text = head_bytes[:4096].decode("utf-8", errors="ignore")
    return "urn:schemas-microsoft-com:office:spreadsheet" in text and "<Workbook" in text


def _cell_value(cell: ET.Element):
    data = cell.find("ss:Data", _NS)
    if data is None:
        return None
    cell_type = data.get(f"{{{_NS['ss']}}}Type", "String")
    text = data.text
    if text is None:
        return None
    if cell_type == "Number":
        try:
            f = float(text)
            return int(f) if f.is_integer() else f
        except ValueError:
            return text
    return text


def read_workbook(path: str) -> Dict[str, List[list]]:
    """Returns {sheet_name: [[cell, ...], ...]} with rows made rectangular
    (padded with None) and cells positioned correctly even when the file
    uses ss:Index to skip empty cells."""
    tree = ET.parse(path)
    root = tree.getroot()
    sheets: Dict[str, List[list]] = {}

    for ws in root.findall("ss:Worksheet", _NS):
        name = ws.get(f"{{{_NS['ss']}}}Name", "Sheet")
        table = ws.find("ss:Table", _NS)
        rows: List[list] = []
        if table is None:
            sheets[name] = rows
            continue

        max_cols = 0
        raw_rows = []
        for row in table.findall("ss:Row", _NS):
            row_cells = []
            col_cursor = 0
            for cell in row.findall("ss:Cell", _NS):
                idx_attr = cell.get(f"{{{_NS['ss']}}}Index")
                if idx_attr is not None:
                    target_idx = int(idx_attr) - 1
                    while col_cursor < target_idx:
                        row_cells.append(None)
                        col_cursor += 1
                value = _cell_value(cell)
                row_cells.append(value)
                col_cursor += 1
            max_cols = max(max_cols, len(row_cells))
            raw_rows.append(row_cells)

        for r in raw_rows:
            if len(r) < max_cols:
                r.extend([None] * (max_cols - len(r)))
            rows.append(r)

        sheets[name] = rows

    return sheets
