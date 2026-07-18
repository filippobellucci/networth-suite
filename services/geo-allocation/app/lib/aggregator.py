from __future__ import annotations
from typing import Dict, Iterable, Optional, Sequence, Tuple

from .models import AllocationResult


def aggregate(
    results: Sequence[AllocationResult],
    fund_weights: Optional[Sequence[float]] = None,
    normalize: bool = True,
) -> Dict[str, float]:
    """
    Aggregates multiple AllocationResult objects (e.g. the various ETFs in
    a portfolio) into a single {ISO2_code: weight} map representing the
    portfolio's combined geographic exposure.

    ``fund_weights``: the weight of each fund in the portfolio (same order
    as ``results``). If omitted, each fund is weighted 1/N (simple
    average). The weights don't need to sum to 1: they are normalized
    automatically, unless ``normalize=False``.

    Example:
        r1 = parse_file("msci_world.xlsx")   # 70% of the portfolio
        r2 = parse_file("em_markets.xlsx")   # 30% of the portfolio
        aggregate([r1, r2], fund_weights=[0.7, 0.3])
        # -> {'US': 0.55, 'CN': 0.09, ...}
    """
    n = len(results)
    if n == 0:
        return {}

    if fund_weights is None:
        fund_weights = [1.0 / n] * n
    elif len(fund_weights) != n:
        raise ValueError("fund_weights must have the same length as results")

    if normalize:
        total = sum(fund_weights)
        if total <= 0:
            raise ValueError("the sum of fund_weights must be positive")
        fund_weights = [w / total for w in fund_weights]

    combined: Dict[str, float] = {}
    for result, fw in zip(results, fund_weights):
        for country, weight in result.weights.items():
            combined[country] = combined.get(country, 0.0) + weight * fw

    return combined


def merge_unmapped(results: Iterable[AllocationResult]) -> Dict[str, float]:
    """Diagnostic utility: merges all unrecognized labels (summing their
    weights) across multiple results, to help decide which aliases to add
    via countries.register_country_alias."""
    merged: Dict[str, float] = {}
    for r in results:
        for label, weight in r.unmapped_labels.items():
            merged[label] = merged.get(label, 0.0) + weight
    return merged
