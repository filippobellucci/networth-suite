from __future__ import annotations
from typing import Dict, Sequence

from .models import AllocationResult


def aggregate(results: Sequence[AllocationResult], fund_weights: Sequence[float]) -> Dict[str, float]:
    """
    Aggregates multiple AllocationResult objects (e.g. the various ETFs in
    a portfolio) into a single {ISO2_code: weight} map representing the
    portfolio's combined geographic exposure.

    ``fund_weights``: the weight of each fund in the portfolio (same order
    as ``results``), in any scale -- they are normalized to sum to 1.
    """
    if not results:
        return {}

    total = sum(fund_weights)
    if total <= 0:
        raise ValueError("the sum of fund_weights must be positive")

    combined: Dict[str, float] = {}
    for result, fw in zip(results, fund_weights):
        share = fw / total
        for country, weight in result.weights.items():
            combined[country] = combined.get(country, 0.0) + weight * share

    return combined
