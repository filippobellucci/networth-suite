from .base import BaseParser
from .amundi import AmundiIndexCompositionParser, AmundiHoldingsParser
from .vanguard import VanguardMarketAllocationParser
from .ishares import ISharesHoldingsParser

DEFAULT_PARSERS = [
    AmundiIndexCompositionParser(),
    AmundiHoldingsParser(),
    VanguardMarketAllocationParser(),
    ISharesHoldingsParser(),
]

__all__ = [
    "BaseParser",
    "AmundiIndexCompositionParser",
    "AmundiHoldingsParser",
    "VanguardMarketAllocationParser",
    "ISharesHoldingsParser",
    "DEFAULT_PARSERS",
]
