# Changelog

## Dark mode: "Deep Ink"

- Added a light/dark toggle in the sidebar footer (sun/moon icon + switch). Defaults to the
  system's `prefers-color-scheme` on first visit, then remembers your choice in `localStorage`
  from then on — the choice persists across reloads and restarts.
- New dark palette ("Deep Ink"): near-black page background, bright gold accent, warm cream text
  — implemented as a `.dark` class override on `<html>` for the same CSS custom properties the
  light theme already used, so every component that referenced them (`bg-panel`, `text-brass`,
  etc.) picked up dark mode automatically with no per-component changes.
- A small inline script in `index.html` applies the `dark` class before React even mounts, so
  there's no flash of the wrong theme on load.
- Recharts elements (tooltips, axes, gridlines, pie/area fills) can't read CSS variables, so they
  now pull from a new `getChartTheme(isDark)` helper (`frontend/src/lib/chartTheme.ts`) instead of
  hardcoded hex — covers `NetWorthChart`, `GeoAllocation`, and `PortfolioAllocation`, including
  fully re-tuned categorical palettes (country slices, category slices) for both modes.
- Verified at the DOM level, not just visually: confirmed `html` picks up the `dark` class on
  toggle, `localStorage` updates, the computed `body` background actually resolves to the new
  dark color, and the class survives a page reload.

## New tab: Historical Net Worth (frozen manual snapshots)

- Added a "Historical Net Worth" tab (below Geographic Allocation) with a **"+ Take snapshot"**
  button, a chart, and a table of past snapshots sorted newest-first — replaces the manual
  Google Sheets tracking shown in your screenshot.
- This is deliberately a **separate, frozen** history from the existing live chart on the
  Summary/Portfolio pages. Pressing the button records the combined net worth (across all
  portfolios, converted to EUR) as a permanent number tied to today's date; it never gets
  recalculated afterwards, unlike the live chart which always re-values every holding at
  whatever the current price happens to be. Taking a snapshot again on the same day overwrites
  that day's row instead of creating a duplicate, so pressing it twice by mistake is harmless.
- The live chart elsewhere is untouched on purpose, per your call to keep its current
  "always re-priced at today's rate" behavior rather than freezing it.
- New backend: `NetWorthSnapshot` model/table plus `POST /networth-snapshots`,
  `GET /networth-snapshots`, `DELETE /networth-snapshots/{id}` on the core service (reachable via
  the gateway's existing generic `/api/core/...` proxy — no gateway changes needed). No automatic
  end-of-month scheduling yet, as agreed — that's a natural next step if wanted later.

## Palette correction: cream panels, deeper brown ink

- The card/panel background was reading as near-white (`#FFFDF7`) instead of a visible cream —
  replaced with `#DCCDAE`, the exact color you get from blending the brass accent at 35% opacity
  over that old background (i.e. literally "the chart's own color," now reused as the panel
  background instead of just its fill).
- Text and the brass accent were pushed to a noticeably darker brown: body text from `#242019` to
  `#1F1608`, the brass accent from `#9C7326` to `#6B4E14` (also used for the net worth chart's
  line/fill, active nav state, links, and buttons). Muted text and hairline borders were deepened
  to match (`#75694C`, `#C7B78D`) so they stay legible against the new, more saturated panel color.
- Page background, sidebar, favicon, and the chart/tooltip colors in `NetWorthChart.tsx`,
  `GeoAllocation.tsx`, and `PortfolioAllocation.tsx` were all updated together so the whole app
  reads as one consistent tone instead of some surfaces staying on the old paler colors.
- Verified with real screenshots (Summary and Portfolio Allocation pages) again rather than just
  trusting the hex math.

## Visual redesign: "Ledger Light"

- Full theme switch from the original dark "ledger at dusk" palette to a light paper-and-ink
  direction: warm cream page background, white/cream cards with hairline borders (no shadows),
  dark ink body text, and a deeper brass gold as the single accent color (readable against light
  surfaces, where the old bright gold tuned for a dark background would have washed out).
  `Fraunces` (serif, headings/numbers) + `Inter` (sans, UI) + `IBM Plex Mono` (tabular figures)
  are unchanged.
- Only `frontend/src/index.css`'s CSS custom properties and a handful of hardcoded chart colors
  needed to change — every component already referenced the theme through semantic Tailwind
  classes (`bg-panel`, `text-brass`, `border-panel-hairline`, etc.), so the rest of the app picked
  up the new palette automatically with no component-level changes.
- Recharts elements (tooltips, axes, gridlines, area/pie fills) can't read CSS variables directly,
  so their hardcoded hex values were updated by hand in `NetWorthChart.tsx`, `GeoAllocation.tsx`,
  and `PortfolioAllocation.tsx`, including a full re-tuning of both categorical color palettes
  (country slices, category slices) for contrast against a light background instead of a dark one.
- Verified by rendering the built app with seeded sample data (Summary, portfolio detail, and
  Portfolio Allocation pages) rather than just eyeballing the CSS — caught nothing broken, but
  worth calling out since color-only refactors are easy to get subtly wrong.

## Value column decimals and in-app balance editing

- Fixed: "Value" columns (Positions, Cash/Emergency Fund/Pension Fund) and the big Net Worth /
  Invested / Cash figures were still showing 0 decimals — the previous change only reached the
  per-unit price/balance columns. `formatMoney` now shows up to 3 decimals everywhere too, trimmed
  back to a clean whole number when there's nothing after the decimal point (needed
  `minimumFractionDigits: 0` explicitly, since `Intl.NumberFormat` otherwise defaults a currency's
  minimum to 2). `formatMoneyPrecise` is now just an alias — the two had converged.
- Replaced the browser's native `prompt()` dialog for updating a Cash / Emergency Fund / Pension
  Fund balance with in-app inline editing: click "Update" and the balance cell turns into a text
  field with Save/Cancel right there in the table (Enter to save, Escape to cancel), matching the
  app's own styling instead of a Chrome dialog.

## Chart time-range filter and 3-decimal currency precision

- The net worth chart (both the combined Summary view and each portfolio's own chart) now has a
  **Day / Month / Year / Max** filter above it. Selecting a range recomputes the chart from the
  already-loaded history client-side — no extra request needed. Defaults to "Max" (previous
  behavior). If a range has no data points, the chart shows a clear "No data in this range yet"
  message instead of rendering empty.
- All monetary inputs (manual price on a position, cash/emergency fund/pension fund balances) now
  accept up to **3 decimal places**. Anything beyond that is rounded server-side at the point of
  entry via a Pydantic validator, so precision stays consistent regardless of what a client sends
  — not just trimmed for display. Precise currency display (`formatMoneyPrecise`, used for
  per-unit prices and balances) was bumped from 2 to 3 decimals to match; the large rounded
  figures (net worth, invested, cash totals, position/balance "Value" columns) are unchanged.

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
README.md
docker-compose.yml
gateway/app/registry.py
gateway/app/main.py
services/core-networth/app/models.py
services/core-networth/app/schemas.py
services/core-networth/app/valuation.py
services/core-networth/app/migrate.py
services/pension-fund/                                 (removed)
services/price-feed/app/main.py
services/price-feed/requirements.txt
services/geo-allocation/app/main.py
services/geo-allocation/app/country_aliases.py
services/geo-allocation/app/regions.py
frontend/src/api/client.ts
frontend/src/types/index.ts
frontend/src/lib/format.ts
frontend/src/components/Sidebar.tsx
frontend/src/components/NetWorthChart.tsx
frontend/src/App.tsx
frontend/src/pages/PortfolioDetail.tsx
frontend/src/pages/Assets.tsx
frontend/src/pages/GeoAllocation.tsx
frontend/src/pages/PortfolioAllocation.tsx              (new)
frontend/src/pages/Settings.tsx
frontend/src/pages/Pension.tsx                          (removed)
```
