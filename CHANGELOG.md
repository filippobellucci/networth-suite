# Changelog

## Chart Y-axis: auto-zoom on Day/Week/Month/Year, plus an absolute/percentage toggle

- Fixed: a small daily move (e.g. +0.3%) was invisible on the Day/Week/Month/Year charts because
  the Y-axis always started at €0, same as "Max" — against a Max-sized axis, a realistic day's
  movement barely registers as a flat line.
- **Day/Week/Month/Year now auto-zoom** to the visible data's own range instead of starting at
  zero, so a small move actually reads as a move. **Max stays anchored at €0 on purpose** (kept
  exactly as before) — it's meant to read as "grown from nothing," which auto-zooming would
  undercut.
- **New €/% toggle**, available on every range including Max, switching the whole chart (line,
  Y-axis, tooltip) between absolute currency values and percentage change from the first visible
  point in the current view. Percentage mode always auto-zooms, Max included, since "grown from
  nothing" isn't a meaningful frame once you're already looking at a relative percentage.
- Applied identically to the per-asset price chart (`AssetPriceChart`) for consistency — it
  already auto-zoomed on every range (a price chart starting at €0 isn't meaningful the way net
  worth starting at €0 is, so that part was left as-is), it just gained the same €/% toggle.
- Verified directly against the rendered chart's actual SVG tick labels (not just by reading the
  code): confirmed Max still reads `€0, €30,000, €60,000...`, confirmed Week auto-zooms to a tight
  `€100,298–€100,302`-style range instead of starting at zero, and confirmed the percentage toggle
  correctly re-labels that same range as `+0.0%, +1.0%, +2.0%...`.

## Fix: live chart silently skipped days instead of accumulating them

- The "always include today" fix from a previous round only ever appended a single point for
  *whichever day happened to be "today"* at request time, and that point was never actually
  stored anywhere — it was recomputed fresh on every request. So the day after it was added, that
  point simply stopped existing (nothing "yesterday" about it was persisted) and got replaced by a
  new point for the new "today", with nothing filling the day in between. Visually this looked
  like the chart jumping straight past a day (e.g. from the 19th to the 21st, skipping the 20th)
  every time a day passed without a real position/balance change.
- Fixed by filling in **every** day from the last real entry through today, not just the latest
  one (`valuation.with_trailing_days_filled`, used by both `/portfolios/{id}/history` and
  `/networth/combined`). Each day's point becomes real and stable the moment it's first computed
  and stays that way — it doesn't get silently dropped once a new day arrives. Historical gaps
  *between* two real entries are untouched (that sparse-with-straight-line-interpolation behavior
  was never the bug).
- Verified directly: reproduced the exact reported scenario (last real entry 2 days ago) and
  confirmed the history response now includes all three days with no gap, for both the
  single-portfolio and combined endpoints. Also checked a wider 30-day gap resolves in ~0.06s, to
  make sure filling in trailing days doesn't introduce a real-world performance problem.

## Real return: XIRR (money-weighted annualized return)

- New "Annualized return (XIRR)" line on the Summary and each portfolio page, showing **1Y** and
  **All-time** rates, colored with the existing gain/loss palette. Deliberately not shown for
  Day/Week/Month — an annualized rate computed over a few days or weeks produces mathematically
  correct but practically meaningless numbers (a +0.5% week "annualizes" to several hundred
  percent).
- Chose **XIRR over plain CAGR** specifically because this app's net worth constantly changes from
  both market movement *and* money added/withdrawn — CAGR ("value A to value B over N years")
  can't tell those apart and would overstate returns every time money is added. XIRR handles
  contributions/withdrawals at their actual dates correctly.
- There's no transaction ledger in this app (no "deposited €5,000 on March 3rd" record) — cashflows
  are **inferred** from the periodic snapshots already stored: a quantity or cash-balance change
  between two consecutive entries becomes a contribution or withdrawal, priced at that entry's
  actual date using the same real historical-price infrastructure the rest of the app already
  relies on. The starting value at the period's start date becomes an initial outflow, and today's
  current value becomes the final inflow.
- **Known limitation, disclosed to and accepted by the user before implementing**: a cash account
  balance increase is indistinguishable from "interest earned" vs. "money deposited" — both get
  treated as a contribution. This only affects cash; ticker/manual-priced asset quantity changes
  are unambiguous. Properly separating the two would require an actual transaction ledger, which
  is a much larger feature not in scope here.
- New `app/xirr.py` in `core-networth`: a from-scratch Newton-Raphson XIRR solver (no new
  dependency) plus the cashflow-reconstruction logic, and two new endpoints,
  `GET /portfolios/{id}/xirr` and `GET /networth/combined/xirr`, mirroring the existing `/growth`
  endpoints' shape and conventions (bounded "Max" period, per-portfolio and combined variants).
- Verified rigorously, not just by inspection:
  - 5 synthetic solver unit tests (simple known-rate cases, a multi-contribution case, and the
    "no valid answer" edge cases), each checked against the exact expected rate or against a
    brute-force NPV recomputation at the solved rate.
  - A realistic contribution scenario (buy 1 unit, add 1 more unit 6 months later, reprice today)
    verified against the API's answer using a **completely independent bisection-method
    calculation** written separately from the app's own solver — both landed on exactly 33.13%.
  - Confirmed the same figure renders correctly on the actual portfolio page (not just the raw
    API response).

## Geographic Allocation: chart and country table as two separate cards

- The chart/map and the country breakdown table were inside one continuous card with just a
  margin between them, which didn't read as clearly separated as intended. They're now two
  distinct cards with a real gap between them, matching the layout style used everywhere else in
  the app for stacked sections (Positions / Cash / Emergency Fund, etc.).
- Verified via the actual rendered DOM, not just visually: confirmed two separate `.card` elements
  with a 32px gap between them, not one container with internal spacing.

## Geographic Allocation: contained chart layout, and a world map view

- **Layout fix**: the pie chart and the country/region breakdown were side-by-side, so the chart's
  size and the list's readability fought each other (a long country list stretched the whole row).
  The chart is now fixed-size and centered on its own; the breakdown is a proper table (with a
  Country/Weight header row) directly below it, always readable regardless of how many countries
  are in the list.
- **New: World map view.** A "Chart / Map" toggle next to "By country / By region" switches the
  pie chart for a choropleth world map — each country shaded by its weight in the portfolio
  (relative to the largest single-country exposure, so smaller allocations stay visible instead of
  washing out next to one dominant country), with a hover tooltip showing the exact percentage.
  Only available when grouped "By country" (region codes like "AMERICAS" aren't real countries, so
  there's nothing to shade on a map for that view).
  - Built with `d3-geo` + `topojson-client` rendering `world-atlas`'s bundled TopoJSON directly to
    SVG paths — no extra charting library needed beyond what's already used for the app's other
    charts.
  - `world-atlas` identifies countries by ISO 3166-1 **numeric** codes (e.g. "840" for the US),
    not the ISO2 codes ("US") used everywhere else in this app. Added a small static crosswalk
    (`lib/isoNumericCodes.ts`) covering the same country set as the backend's `country_names.py`,
    generated once from a verified reference library rather than hand-typed, then hardcoded rather
    than bundled as a runtime dependency.
  - The map component is **lazy-loaded**: `d3-geo`, `topojson-client`, and ~100KB of map data
    (131KB gzipped as its own chunk) only download when someone actually opens Geographic
    Allocation and switches to Map view, not as part of the app's main bundle.
- Verified end-to-end with real fixture data: confirmed the table now renders below the chart with
  proper headers, and confirmed the map actually draws (178 country paths rendered from the
  topology), shaded correctly by the same allocation data as the pie chart and country table.

## Fix: every ETF's price chart showed "Not Found"

- Root cause: `price-feed`'s own routes were defined with a redundant `/prices/` prefix
  (`/prices/history`, `/prices/intraday`, etc.) — the *same word* as the gateway's module name for
  that service. The gateway's generic proxy strips the module segment (`prices`) from the URL and
  forwards the rest as-is, so a request to `/api/prices/history` arrived at price-feed as `/history`,
  which didn't exist — a 404 before price-feed's actual logic ever ran. `core-networth` and
  `geo-allocation` never hit this because their own internal routes don't repeat their module name
  (`/portfolios/...`, `/allocation/...`, not `/core/portfolios/...` or `/geo/allocation/...`).
  This bug specifically only affected the two *new* direct frontend-to-price-feed calls added for
  the per-asset price chart — everything else (portfolio prices) goes through core-networth
  server-to-server and was never affected.
- Fixed by dropping the redundant prefix from price-feed's route definitions (`/latest`,
  `/on-date`, `/intraday`, `/batch`, `/history`), matching how every other service is structured,
  and updating `core-networth`'s `price_client.py` (the one other caller) to match. No frontend
  changes needed — its calls were already correct for what the *fixed* routing does.
- Verified the fix directly: the same request that used to 404 (routing failure) now reaches
  price-feed's real logic and fails at the Yahoo Finance network call instead (502, expected in
  this offline dev environment) — proof the request lands on the right endpoint now. On a real
  internet connection this returns actual price data.

## Per-asset price chart and Currency Exposure

Implements two roadmap items together: "Per-asset price chart" and "Currency exposure".

- **Per-asset price chart** — asset names in the Asset Catalogue and in a portfolio's Positions
  table now link to a new `/assets/:id` detail page, with the same Day/Week/Month/Year/Max chart
  and growth-stat pattern already used for net worth (reused, not duplicated logic-for-logic, via
  a new `AssetPriceChart` component mirroring `NetWorthChart`'s structure).
  - Ticker-based assets: daily/monthly history and hourly "Day" data come straight from
    `price-feed`'s existing endpoints (`/prices/history`, `/prices/intraday`) — called directly
    from the frontend through the gateway, no new backend code needed for this part.
  - Manually-priced assets (real estate, unlisted holdings): a new `core-networth` endpoint,
    `GET /assets/{id}/manual-price-history`, returns every manually-entered price for that asset
    across all portfolios over time — deduplicating same-date entries. These assets have no "Day"
    button (no hourly data exists for a manual price), so the chart only offers Week/Month/Year/Max.
  - New `GET /assets/{id}/growth` computes day/week/month/year/max price change, reusing the same
    `_build_growth_stats` helper already powering portfolio growth — same historical-accuracy
    guarantees, same "max bounded by earliest tracked date" logic, just valuing a single asset's
    price instead of a whole portfolio's net worth.
  - New `GET /assets/{id}` endpoint (a single-asset fetch was missing; only list/search existed).
- **Currency Exposure** — new page showing what share of a portfolio's value is priced in each
  currency (a donut chart + legend, visually identical to Portfolio Allocation, just grouped by
  currency instead of category). No backend changes — the data (`price_currency` per position,
  `currency` per cash balance) was already in the existing portfolio snapshot response.
  - Deliberately **not** a true look-through: this reflects the currency each position/balance is
    quoted or held in, not what a fund holds underneath (a EUR-listed ETF can still hold
    USD-denominated stocks internally) — noted directly on the page since it changes what the
    chart actually means.
- Verified end-to-end via the actual rendered pages: confirmed Currency Exposure's EUR/USD split
  matches the seeded data, and Asset Detail correctly plots the manual price history, computes the
  right growth figure, and correctly hides the "Day" button for a non-ticker asset.

## Week range button, and real hourly prices on "Day" (broker-style chart)

- Added a **Week** button between Day and Month. Like Month/Year, it's a client-side filter of
  the already-loaded daily points (last 7 days) — no backend change needed for this one. Growth
  stats gained a matching "week" period (today vs. 7 days ago).
- **Day now shows real hourly granularity** instead of just the single most-recent daily point.
  New `price-feed` endpoint `GET /prices/intraday` pulls 60-minute bars from Yahoo Finance for a
  given ticker/date; cached forever for past days, short-TTL (like live prices) for today since
  the trading day is still filling in. New `core-networth` endpoints
  `GET /portfolios/{id}/intraday` and `GET /networth/combined/intraday` compose these into an
  hourly net-worth line for a whole portfolio (or all of them combined).
- Three deliberate simplifications, matching how real broker apps behave, not bugs:
  - **Cash and FX are held flat for the day** — only the priced/ticker portion of the portfolio
    moves with real intraday price action. A cash balance has no intraday granularity to begin
    with, and hourly FX lookups weren't worth the added complexity for one day's view.
  - **A ticker with no data yet at a given hour carries forward the previous trading day's
    close** (e.g. before that market opens), same as a broker keeps showing the last traded
    price rather than a gap. Verified this carry-forward logic directly with a synthetic
    two-market scenario (one ticker opening at 9:00, another at 15:30) before wiring it into the
    real endpoint.
  - **Only market hours have data.** Nights, weekends, and holidays show little or nothing, same
    as any trading app — the "Day" chart shows "No hourly data for today yet" rather than a
    misleading flat/empty line when that's the case.
  - A portfolio with no ticker-based holdings at all still contributes its flat current total to
    the combined hourly line rather than silently vanishing from it.
- `NetWorthChart` gained an optional `fetchIntraday` callback prop; only "Day" uses it, and only
  when a parent page supplies one (Dashboard and Portfolio pages do; Historical Net Worth's chart
  is untouched, same reasoning as the growth-stats change above).
- Verified end-to-end via the actual rendered page (not just the API): Week correctly recomputes
  the growth stat to "since 7 days ago" and refilters the chart; Day correctly triggers the new
  intraday fetch and shows the graceful no-data state cleanly with no crash when Yahoo Finance
  isn't reachable (expected in this dev environment) — on a real connection this shows actual
  hourly bars instead.

## Growth stats per period, and the live chart now always reaches today

- Fixed: the live net worth chart's last point was whatever date something was last entered or
  updated, so it visibly lagged behind today even though the headline net worth figure was already
  current (prices refresh independently of chart points). Both `/portfolios/{id}/history` and
  `/networth/combined` now always include a point for today, computed with live prices, appended
  if it isn't already the latest entry date.
- **New: growth stats next to the Day/Month/Year/Max buttons.** Selecting a range now shows how
  much the portfolio actually grew over it — start value, current value, absolute and percentage
  change (e.g. "+€1,234 (+4.7%) since Jun 20, 2026") — colored with the existing gain/loss palette.
  Computed using real historical prices for the period's start date (today − 1 day / 1 month /
  1 year, or the earliest tracked date for "Max"), not just whatever data point happened to
  already exist, via `valuation.compute_portfolio_growth` / `compute_combined_growth` and two new
  endpoints: `GET /portfolios/{id}/growth` and `GET /networth/combined/growth`.
- Month/year subtraction correctly clamps day-of-month overflow (e.g. Mar 31 minus one month lands
  on Feb 28/29, not an invalid Feb 31) and clamps every period's start date to never go earlier
  than the portfolio's actual first tracked entry.
- `NetWorthChart` (shared by the Summary and Portfolio pages) gained an optional `growth` prop;
  it picks the stat matching whichever range button is currently selected. The Historical Net
  Worth page's chart is untouched — growth stats there would need a different basis (comparing
  frozen snapshots rather than live valuations) and weren't in scope this round.
- Verified with real historical data (an 8-month-old entry, updated 2 months ago): confirmed via
  the actual rendered page text — not just the API response — that switching between Day/Month/
  Year/Max updates both the displayed growth figure and the chart's visible range correctly, and
  that "Day" now genuinely shows a point for today instead of "no data in this range."

## Automation: price refresh, monthly snapshot catch-up, and daily backups

Implements the "Automation" section of the roadmap, designed around one specific constraint: the
machine this runs on is powered on roughly once a day, sometimes skipping days entirely — nothing
here assumes the machine (or the site) is ever continuously open.

- **New lightweight in-process scheduler** (`app/scheduler.py` in both `core-networth` and
  `geo-allocation`) — no extra dependency (no APScheduler), just a background `asyncio` task that
  runs all jobs once immediately on startup, then re-checks every 6 hours in case the process
  stays up longer. Doesn't block API availability while it runs.
- **Price refresh**: on every startup, force-refreshes the live price for every ticker in the
  Asset catalogue and every currency pair actually in use. Note: there's no meaningful "missing
  days" backlog to replay for a *live* price (it only ever represents "right now") — what matters
  is that it's fresh the moment it's next needed, which the startup-triggered run guarantees.
  Genuine historical accuracy for specific past dates was already solved separately (see the
  "Real historical prices" entry above) and is untouched by any of this.
- **Monthly net worth snapshot catch-up**: on every startup, checks every completed month since
  your first tracked position for a snapshot; any gap gets backfilled **dated and priced as of
  that exact month-end**, using the real historical price lookup, not the date it happened to run.
  Power the machine off for three months and turn it back on: you get three correctly-dated,
  correctly-priced snapshots, not one lumped onto today. Capped at 36 months back as a sanity
  bound. New `NetWorthSnapshot.source` field ("manual" | "auto") shown as a badge in the
  Historical Net Worth table, so it's always clear which points were backfilled.
- **Daily backup**: copies the SQLite database (`core-networth`) and uploaded fund files
  (`geo-allocation`) into a dated folder under `./backups/` once per calendar day, checked on
  every startup. Deliberately *not* retroactive, per your call — a day the machine was off simply
  has no backup for that day.
- `docker-compose.yml`: added a `./backups/core` and `./backups/geo` bind mount to the respective
  services. `.gitignore` updated to exclude the whole `backups/` folder (same private-data
  treatment as everything else — verified with the same isolated-repo `git add -A` test used for
  every other data path in this project).
- New `POST /scheduler/run-now` on both services (reachable via the gateway's existing generic
  proxy, e.g. `/api/core/scheduler/run-now`) to trigger all jobs immediately instead of waiting —
  useful for testing or right after adding a backlog of historical data.
- Found and fixed a real migration bug while testing this: a new `NOT NULL` column with a
  Python-side default (`NetWorthSnapshot.source`) was being added to existing databases as `NULL`
  by the lightweight migrator, which isn't a valid value per the schema and broke reading old
  snapshot rows. Generalized `migrate.py` to backfill any newly-added column's Python-side default
  onto existing rows automatically, rather than leaving them `NULL` — fixes this specific case and
  prevents the same class of bug for any future column addition.

## Real historical prices (live chart is now actually accurate over time)

- Fixed the most significant known limitation: the live net worth chart used to re-value every
  past point at *today's* price, only the quantity differed by date. A holding's chart contribution
  for e.g. six months ago would jump around whenever today's price changed, which isn't what
  "history" should mean.
- `price-feed` gained a new `GET /prices/on-date?ticker=...&date=YYYY-MM-DD` endpoint: returns the
  actual closing price on (or the last trading day before) that date — handling weekends/holidays
  by walking back up to 10 days to find the nearest prior close. Unlike the 15-minute cache used
  for live prices, results here are **cached forever**: a past closing price never changes, so
  there's no reason to ever re-fetch it.
- `core-networth`'s valuation logic now branches on whether it's pricing "today" (unchanged: live
  price, 15-min cache, respects the "Refresh prices" button) or a past date (new: exact historical
  close, permanently cached). Applies to both asset prices and FX rates, so multi-currency
  portfolios get accurate historical conversion too, not just accurate historical prices.
  `HoldingPosition.price_source` can now report `"historical"` in addition to the existing
  `"live"` / `"manual"` / `"unavailable"`.
- Manually-priced positions (real estate, unlisted assets) were already accurate for history, since
  each dated entry already stores the price you entered at the time — verified this still works
  correctly alongside the new ticker-based logic (tested with two manual-price entries six months
  apart, confirmed the history endpoint returns the correct distinct value for each date rather
  than collapsing to one).
- Verified the on-or-before-date matching logic with a synthetic trading calendar (correctly picks
  the prior Friday's close for a Saturday request), and confirmed the new endpoint fails gracefully
  (clean 404/422, no crash) on bad tickers or malformed dates.

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
