class FundAllocationParserError(Exception):
    """Base class for all exceptions raised by the library."""


class UnreadableFileError(FundAllocationParserError):
    """The file cannot be opened/decoded by any of the available readers."""


class NoParserFoundError(FundAllocationParserError):
    """No registered parser recognizes the file's format/structure.

    A parser that recognizes a file but then fails to extract data from it
    does not raise a distinct exception: registry._parse_sheets catches
    whatever it raised, keeps trying the remaining parsers, and reports every
    such near-miss in this error's message."""
