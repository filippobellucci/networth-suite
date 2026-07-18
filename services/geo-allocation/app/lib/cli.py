"""
Minimal CLI: python -m fund_allocation_parser <file1.xlsx> [file2.xlsx ...]

Prints one JSON object per file to stdout, so the library can be invoked
as an external process (subprocess) even from projects written in other
languages (Java, C#, ...), which only need to be able to read JSON from
stdout.
"""
from __future__ import annotations
import argparse
import json
import sys

from .registry import parse_file
from .exceptions import FundAllocationParserError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="fund_allocation_parser",
        description="Extracts the geographic allocation by country from fund/ETF Excel files.",
    )
    ap.add_argument("files", nargs="+", help="Paths of the Excel files to parse")
    ap.add_argument("--ndigits", type=int, default=6, help="Decimal digits for weights in the output")
    args = ap.parse_args(argv)

    outputs = []
    exit_code = 0
    for f in args.files:
        try:
            result = parse_file(f)
            outputs.append(result.to_dict())
        except FundAllocationParserError as e:
            outputs.append({"error": str(e), "source_file": f})
            exit_code = 1

    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
