"""
Unified Excel reader.

The "xlsx" files published by some issuers (observed e.g. with Amundi
files) contain slightly invalid internal XML (colors not in aRGB format)
that makes ``openpyxl`` fail. We therefore use ``python-calamine`` (a Rust
parser, very tolerant, supports xls/xlsx/xlsb/ods) as the primary engine,
with a fallback to a dedicated parser for the "SpreadsheetML" format
(Excel 2003 XML, typical of some BlackRock/iShares files with a .xls
extension) and finally to ``openpyxl`` for the rare cases where calamine
is not enough.

The output is always normalized to: Dict[str(sheet_name), List[List[Any]]]
"""
from __future__ import annotations
from typing import Dict, List
import io

from ..exceptions import UnreadableFileError
from . import spreadsheetml


def _read_with_calamine(data: bytes) -> Dict[str, List[list]]:
    from python_calamine import CalamineWorkbook

    wb = CalamineWorkbook.from_filelike(io.BytesIO(data))
    sheets = {}
    for name in wb.sheet_names:
        sheets[name] = wb.get_sheet_by_name(name).to_python()
    return sheets


def _read_with_openpyxl(data: bytes) -> Dict[str, List[list]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    try:
        sheets = {}
        for name in wb.sheetnames:
            ws = wb[name]
            sheets[name] = [list(row) for row in ws.iter_rows(values_only=True)]
        return sheets
    finally:
        # read_only mode keeps the underlying archive open until closed
        # explicitly.
        wb.close()


def read_workbook(data: bytes) -> Dict[str, List[list]]:
    """
    Reads an Excel file (xls/xlsx/xlsb/ods, or a pseudo-.xls SpreadsheetML
    XML file) and returns {sheet_name: row_matrix}.

    Tries, in order: calamine -> spreadsheetml (if the sniff detects XML)
    -> openpyxl. Raises UnreadableFileError if all of them fail.
    """
    errors = []

    if spreadsheetml.sniff(data):
        try:
            return spreadsheetml.read_workbook(data)
        except Exception as e:  # pragma: no cover - fallback path
            errors.append(f"spreadsheetml: {e!r}")

    try:
        return _read_with_calamine(data)
    except Exception as e:
        errors.append(f"calamine: {e!r}")

    try:
        return _read_with_openpyxl(data)
    except Exception as e:
        errors.append(f"openpyxl: {e!r}")

    try:
        return spreadsheetml.read_workbook(data)
    except Exception as e:
        errors.append(f"spreadsheetml: {e!r}")

    raise UnreadableFileError(
        "Could not read the file with any of the available readers:\n"
        + "\n".join(errors)
    )
