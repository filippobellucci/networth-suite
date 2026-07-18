class FundAllocationParserError(Exception):
    """Base class for all exceptions raised by the library."""


class UnreadableFileError(FundAllocationParserError):
    """The file cannot be opened/decoded by any of the available readers."""


class NoParserFoundError(FundAllocationParserError):
    """No registered parser recognizes the file's format/structure."""


class ParsingError(FundAllocationParserError):
    """A parser recognized the file but failed to extract data from it."""
