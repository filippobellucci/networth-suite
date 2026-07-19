# Changelog

## Price feed reliability

- Upgraded `yfinance` from 0.2.44 to 1.5.1 — the old pin predated several Yahoo Finance API
  changes and was silently failing on most tickers.
- `price-feed` no longer swallows fetch errors silently: failures are now logged with the actual
  reason (bad ticker, rate limiting, network issue), visible via `docker compose logs price-feed`.
- Added a fallback path: if the fast quote lookup fails, the service retries using recent daily
  history before giving up.
- Added a `force` flag on `/prices/latest` and `/fx/latest` to bypass the 15-minute cache.
- **New: "Refresh prices" button** on the portfolio page, which forces a full price/FX recalculation
  for that portfolio instead of waiting for the cache to expire.
- When a price can't be resolved, the portfolio page now shows an explanatory banner (most common
  cause: a non-US ticker missing its exchange suffix, e.g. `.MI`, `.DE`, `.AS`).

## Cash accounts

- Cash accounts are now shown as a table matching the Positions layout — Account, Currency,
  Balance, and **converted Value** per row — instead of a name-and-balance list with only an
  aggregate total.
- New `cash_positions` field on the portfolio snapshot API, computed per account (balance × FX
  rate to the portfolio's base currency).

## Geographic allocation

- Replaced the horizontal bar chart with a **donut/pie chart** plus a percentage legend.
- Fixed several unmapped country labels from real factsheets ("Corea", "Sud Africa", "Tailandia")
  by registering extra aliases through the parsing library's own `register_country_alias()` hook,
  so the vendored library itself stays untouched.
- **New: group by macro-region.** A "By country" / "By region" toggle collapses the per-country
  breakdown into five regions (Americas, Europe, Asia, Africa, Oceania) using a new ISO2 → region
  mapping (`services/geo-allocation/app/regions.py`). Same API shape either way — the aggregation
  endpoint accepts a `group_by=country|region` parameter.
- **New: Stock / Bond exposure split.** Assets can now be tagged with an `instrument_type`
  (Stock or Bond), independent of their asset class, so ETFs that are pure equity or pure bond
  funds can be filtered separately. The geo-allocation view has an "All / Stocks / Bonds" toggle
  that filters which positions feed into the aggregation, weighted by each position's current
  value. The tag is set from the Asset Catalogue or inline when adding a new position, and shown
  as a badge in both the Positions table and the allocation file list.

## Positions table

- Added a dedicated **Ticker** column (previously shown inline next to the asset name).
- Added a **Tag** column showing the Stock/Bond badge, if set.

## Database migrations

- Added a lightweight auto-migration step (`services/core-networth/app/migrate.py`) that runs on
  every service startup: it compares each SQLAlchemy model's columns against the actual SQLite
  schema and adds any missing ones with `ALTER TABLE ... ADD COLUMN`. This was needed because
  `Base.metadata.create_all()` only creates missing tables, never alters existing ones — without
  this, adding `Asset.instrument_type` broke every existing database with a hard `sqlite3.OperationalError:
  no such column` on startup. The migration is additive-only, safe on existing data, and idempotent
  (a no-op on an already up-to-date database), so it will keep covering any future column additions
  without needing a full migrations framework.

## Files touched

```
gateway/app/main.py
services/core-networth/app/models.py
services/core-networth/app/schemas.py
services/core-networth/app/valuation.py
services/core-networth/app/migrate.py                 (new)
services/price-feed/app/main.py
services/price-feed/requirements.txt
services/geo-allocation/app/main.py
services/geo-allocation/app/country_aliases.py         (new)
services/geo-allocation/app/regions.py                 (new)
frontend/src/api/client.ts
frontend/src/types/index.ts
frontend/src/pages/PortfolioDetail.tsx
frontend/src/pages/Assets.tsx
frontend/src/pages/GeoAllocation.tsx
```
