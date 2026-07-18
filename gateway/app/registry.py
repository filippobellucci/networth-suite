"""
Module registry: the single place that lists which backend 'mattoncini' exist
and where to reach them. To add a brand-new module later (in ANY language),
you only need to:
  1. Give it a REST API and a Dockerfile.
  2. Add one entry here (and one service block in docker-compose.yml).
  3. The gateway will proxy /api/<prefix>/* to it automatically -- no other
     code changes needed, and the frontend just calls /api/<prefix>/...
"""
import os

MODULES = {
    "core": {
        "base_url": os.environ.get("CORE_SERVICE_URL", "http://core-networth:8000"),
        "description": "Portfolios, assets, holdings, cash, net worth valuation",
    },
    "prices": {
        "base_url": os.environ.get("PRICE_FEED_URL", "http://price-feed:8001"),
        "description": "Live prices, FX rates, price history",
    },
    "geo": {
        "base_url": os.environ.get("GEO_ALLOCATION_URL", "http://geo-allocation:8002"),
        "description": "Regional allocation parsing (wraps your Excel-parsing library)",
    },
    "pension": {
        "base_url": os.environ.get("PENSION_FUND_URL", "http://pension-fund:8003"),
        "description": "Pension fund contribution tracking & projections",
    },
}
