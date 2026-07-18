from __future__ import annotations
from typing import List, Optional, Union
from pathlib import Path

from .readers import read_workbook
from .parsers import DEFAULT_PARSERS, BaseParser
from .models import AllocationResult
from .exceptions import NoParserFoundError

_REGISTERED_PARSERS: List[BaseParser] = list(DEFAULT_PARSERS)


def register_parser(parser: BaseParser, prepend: bool = True) -> None:
    """
    Registers an additional parser (e.g. for a new issuer), from a
    consumer project, without having to modify this library.

    ``prepend=True`` (default) gives it priority over the default parsers:
    useful when you want to override the behavior for a format that this
    library already recognizes, but differently from what you want.
    """
    if prepend:
        _REGISTERED_PARSERS.insert(0, parser)
    else:
        _REGISTERED_PARSERS.append(parser)


def get_parsers() -> List[BaseParser]:
    return list(_REGISTERED_PARSERS)


def _parse_sheets(sheets, source_file: Optional[str]) -> AllocationResult:
    for parser in _REGISTERED_PARSERS:
        try:
            if parser.can_parse(sheets):
                return parser.parse(sheets, source_file=source_file)
        except Exception:
            # a parser that "thinks" it can handle the file but fails to
            # do so must not block the attempt with the other parsers
            continue
    raise NoParserFoundError(
        "No registered parser is able to interpret the structure of this "
        f"file (sheets found: {list(sheets.keys())})."
    )


def parse_file(path: Union[str, "Path"]) -> AllocationResult:
    """Reads and parses an Excel file from the filesystem, returning an
    AllocationResult with weights normalized by country (ISO2 code)."""
    sheets = read_workbook(path)
    return _parse_sheets(sheets, source_file=str(path))


def parse_bytes(data: bytes, source_file: Optional[str] = None) -> AllocationResult:
    """Same as parse_file, but from in-memory content (e.g. HTTP upload)."""
    sheets = read_workbook(data)
    return _parse_sheets(sheets, source_file=source_file)
