# Changelog

## Editable tag on Cash / Emergency Fund / Pension Fund

- The "+ Add" form for Cash, Emergency Fund, and Pension Fund now includes a **Tag** dropdown, the
  same way adding a new asset already lets you pick Stock/Bond. It defaults to match the section
  you opened it from (e.g. Cash → Cash) but is fully editable to any of the five categories —
  so a balance can be filed under a different tag than the section it was created from if that
  better reflects how you think about it.
- Each section's table now shows a **Tag** column (badge, matching the Positions table's style),
  so it's clear at a glance what every balance is actually tagged as, independent of which section
  it's listed under.
- No backend changes were needed for this — `CashAccount.category` already accepted any
  `AllocationCategory` value; this only exposes that flexibility in the UI.

## Unified allocation categories, Emergency Fund, and simplified Pension Fund

- **Removed the `pension-fund` microservice** (contribution history + projection modeling). Pension
  funds are now tracked exactly like a cash balance — a name and a balance you update by hand
  whenever you check the provider's site — reusing the existing Cash mechanism instead of a
  separate data model. The service, its Docker Compose entry, and its gateway registry entry are
  gone; the "Pension Fund" nav tab and page are replaced by a Pension Fund section on the
  portfolio page.
- **New: Emergency Fund section**, shown above Cash on the portfolio page. Same mechanism as Cash
  (name + a balance you update over time), just tagged separately so it doesn't blend into
  everyday spending money.
- **Unified tagging system.** `Asset.instrument_type` (Stock/Bond only) and the untagged Cash
  model are replaced by a single `AllocationCategory`: **Stock, Bond, Cash, Emergency Fund,
  Pension Fund** — applied to both tradable positions (`Asset.category`) and cash-like balances
  (`CashAccount.category`, defaulting to Cash). The Positions table's "Tag" column and the
  Geographic Allocation Stock/Bond filter both now read from this same field.
- **New tab: Portfolio Allocation**, placed above Geographic Allocation. Shows a donut chart plus
  a legend (amount + %) of how much of a portfolio sits in each of the five categories, computed
  from the portfolio's current snapshot (positions and cash-like balances alike). Anything
  untagged falls into an "Uncategorized" slice rather than being silently dropped.
- Geographic Allocation's Stock/Bond filter query parameter was renamed from `instrument_type` to
  `category` on the gateway endpoint, matching the new terminology.
- Migration: `Asset.instrument_type` is renamed (not just added) to `Asset.category` via
  `ALTER TABLE ... RENAME COLUMN`, so existing Stock/Bond tags are preserved rather than reset.
  `CashAccount.category` is added as nullable; existing cash accounts with no value there are
  treated as Cash everywhere in the app (matches what they always were).

## Data persistence clarification (docs only, no code changes to runtime behavior)

- Investigated a report of portfolio data surviving a fresh `git clone`. Confirmed via `git
  ls-files` that the repo itself was clean — no database or uploaded files were ever tracked by
  git. The actual cause: Docker Compose derives its volume name from the project (folder) name,
  so re-cloning into a folder with the same name reattaches to the **same pre-existing Docker
  volume** rather than starting empty. This is correct, intentional Docker behavior (you want your
  portfolio to survive `docker compose up --build` after pulling code updates) and required no
  code fix — only clarifying documentation.
- README: added a "Starting over with a clean instance" note under the backup section, documenting
  `docker compose down -v` for when a genuinely empty database is wanted (testing, discarding
  sample data), while being explicit that this should not be part of a normal update workflow.
- README: moved the local-development (non-Docker) `DATA_DIR` out of the repo tree
  (`~/.networth-suite/...` instead of `./data`) as defense-in-depth against ever accidentally
  `git add`-ing a real local database — unrelated to the Docker volume question above, but found
  and fixed during the same investigation.
- README: expanded the "keeping your data out of git" section with the untrack/history-rewrite
  commands, for the (unrelated, hypothetical) case where a data file does end up committed in the
  future.

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
