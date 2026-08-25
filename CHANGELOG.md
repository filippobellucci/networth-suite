# Changelog

## Fix: "Update" balance button still showed on Cash/Emergency Fund, Pension Fund never excluded

Two follow-ups from real usage of the new Expenses feature:

- **The manual "Update" balance button was never actually removed.** The plan when transactions
  became the source of truth for a cash account's balance was for this button to disappear from
  Cash and Emergency Fund (their balance is now derived from transactions, not edited by hand) --
  that part of the plan was implemented on the backend but the frontend button was left in place.
  `BalanceSection` (`pages/PortfolioDetail.tsx`) now takes an `allowManualUpdate` prop: `false` for
  Cash and Emergency Fund (with a short note explaining the balance is managed by Transactions
  now), still `true` (default) for Pension Fund.
- **Pension Fund is now explicitly excluded from the transaction ledger**, in both places:
  - Frontend: the account dropdown on the Transactions page (`pages/Transactions.tsx`) no longer
    lists Pension Fund accounts, so there's no way to log a transaction against one from the UI.
  - Backend: `POST /cash-accounts/{id}/transactions` now rejects with a 400 if the target account's
    category is `PENSION_FUND`, regardless of what called it -- so the rule holds even if a future
    UI change forgot to filter it out client-side. Pension Fund keeps working exactly as before:
    a name and a balance updated by hand.

## New: Expenses frontend (Transactions, Expense Categories, Expense History)

Second half of the Expenses feature -- the UI on top of last change's backend ledger. Three new
sidebar sections, deliberately kept as separate pages (matching how Portfolio Allocation/Currency
Exposure/Geographic Allocation are already split, rather than one page with tabs):

- **Transactions** (`pages/Transactions.tsx`): an always-visible entry form (Portfolio → Account,
  cascading; Income/Expense toggle; amount; date; optional category and note) -- no popup, matches
  the "+ New portfolio" style already used elsewhere. After logging one, only amount/category/note
  reset so a run of same-day entries doesn't require re-picking the account each time. Shows the
  selected account's most recent transactions underneath for immediate feedback.
- **Expense Categories** (`pages/ExpenseCategories.tsx`): plain CRUD list (name + color swatch),
  mirroring the Asset Catalogue page's layout. This is the only place categories are managed --
  the Transactions form just picks from what exists here.
- **Expense History** (`pages/ExpenseHistory.tsx`): quick date-range presets (This month/This
  year/All time/Custom) plus an optional portfolio filter, feeding three stat cards (Income/
  Expense/Net), a spending-by-category pie chart + legend table (same shape as Portfolio
  Allocation), and a full movements table below with inline delete.
- New API client methods and TypeScript types for expense categories, cash transactions, and the
  summary endpoint (`api/client.ts`, `types/index.ts`) -- no gateway changes needed, everything
  routes through the existing generic `/api/core/*` proxy.
- Built entirely on the mobile-responsive primitives from the earlier layout work
  (`ResponsiveTable`, `SegmentedControl`) rather than raw tables/button rows, so all three pages
  are mobile-friendly from the start instead of needing a follow-up fix pass like Geographic
  Allocation did.

## New: expense tracking backend (income/expense ledger for cash accounts)

First half of the new Expenses feature -- backend only, no frontend yet. Extends
`core-networth` directly rather than adding a new microservice, since a cash account's balance
and the transactions that move it are the same bounded context and shouldn't be split across two
services that would each need to agree on "what is the current balance".

- **New `ExpenseCategory` model + endpoints** (`POST/GET/PATCH/DELETE /expense-categories`): a
  spending-category taxonomy (Groceries, Bills, Entertainment...), deliberately separate from the
  existing `AllocationCategory` (Stock/Bond/Cash/...) used in Portfolio Allocation -- one tags
  *what* money was spent on, the other tags *where* money sits. Deleting a category un-tags its
  transactions (sets `category_id` to null) instead of deleting them.
- **New `CashTransaction` model + endpoints**: an income/expense ledger entry against a specific
  cash account (`POST/GET /cash-accounts/{id}/transactions`, `PATCH/DELETE /cash-transactions/{id}`),
  plus a flat, filterable `GET /transactions` (by portfolio/account/category/date range) to back a
  future history view. `amount` is always positive; `direction` (INCOME/EXPENSE) says which way it
  moves the balance -- rejected with a 422 if amount is zero or negative.
- **Cash account balances are now derived, not edited directly**: `valuation.resolve_cash_balance()`
  computes a cash account's balance as of any date as *the most recent manually-set balance entry
  on or before that date (its "opening balance", 0 if none exists yet) plus every transaction dated
  after it, up to that date*. `compute_portfolio_snapshot` (used everywhere a cash balance is shown
  or valued, including historical dates) now goes through this instead of reading the latest balance
  entry directly. The existing "Update" balance flow keeps working unchanged (it just becomes a new
  opening-balance anchor); nothing forces switching to transactions, but from the first transaction
  onward a cash account effectively "belongs" to the ledger.
- **New `GET /expenses/summary`**: total income/expense and a per-category breakdown over a date
  range, across accounts that may be in different currencies -- each transaction is converted to
  the requested currency using that day's historical FX rate, same approach as historical net worth
  valuation.
- `distinct_entry_dates()` (feeds the historical net worth chart's date range) now also considers
  transaction dates, so a day where a balance moved only via a transaction isn't skipped.
- No new microservice, no gateway changes needed (the gateway's generic `/api/core/*` proxy already
  reaches every new endpoint), no manual migration needed (new tables are picked up automatically by
  the existing `Base.metadata.create_all()` on startup).
- Verified end-to-end against a live SQLite instance: account creation, opening balance, income/expense
  transactions, current AND historical balance resolution, category deletion preserving transactions,
  positive-amount validation, and the summary endpoint's per-category totals.
- Frontend (new "Expenses" section in the sidebar: entry form, category management, history/report
  view) is the next step, not included in this change.

## Fix: two remaining mobile overflow spots found in real-device testing

Real testing on an iPhone (Safari, over Tailscale) surfaced two spots the previous mobile pass
missed:

- **Chart range controls** (`components/NetWorthChart.tsx`, `components/AssetPriceChart.tsx`): the
  €/% toggle and Day/Week/Month/Year/Max range buttons were left as raw button rows instead of
  going through the new `SegmentedControl` — they looked fine at desk but overflowed the screen
  edge on an actual phone (visible on both the Dashboard and Historical Net Worth charts). Now
  both use `SegmentedControl`, so they collapse into dropdowns on mobile like every other
  filter row.
- **Geographic Allocation's filter row** (`pages/GeoAllocation.tsx`): converting the four controls
  (Chart/Map, By country/region, All/Stocks/Bonds, portfolio picker) to individual dropdowns
  fixed each one individually, but the row containing all four still never wrapped — four
  dropdowns side by side still don't fit a phone's width. On mobile they now stack vertically,
  full width, instead of staying in one unwrapped row.

## New: mobile-friendly tables and filter controls across every page

Follow-up to the mobile layout toggle: real device testing (Safari on iPhone, over Tailscale)
showed every data table clipping or truncating its rightmost column on a narrow screen, and every
row of filter/toggle buttons (Geographic Allocation's Chart/Map, By country/region, All/Stocks)
overflowing the screen width.

- **New `ResponsiveTable` component** (`components/ResponsiveTable.tsx`): takes a column/row
  config once and renders a normal `<table>` on desktop (byte-for-byte the same markup as before)
  or, on mobile, one stacked card per row with each column shown as a label:value line — no
  horizontal scrolling, no clipped columns, at the cost of taller rows. Applied to every table in
  the app: Asset Catalogue, Historical Net Worth, the Positions and Cash/Emergency Fund/Pension
  Fund tables in a portfolio's detail page, and the category/currency/country breakdown legends in
  Portfolio Allocation, Currency Exposure, and Geographic Allocation.
- **New `SegmentedControl` component** (`components/SegmentedControl.tsx`): the same button-group
  toggle on desktop, but a native `<select>` on mobile instead of a row of buttons that no longer
  fits. Applied to Geographic Allocation's three filter rows (Chart/Map, By country/By region,
  All/Stocks/Bonds).
- **New `ViewModeContext`** (`context/ViewModeContext.tsx`) + `useIsMobile()` hook, wired up in
  `App.tsx`, so any page can read the current desktop/mobile layout without prop-drilling through
  the router.
- Purely additive: every page's own state, editing logic (inline balance/name/tag editing in the
  Cash table), and data-fetching is untouched — only how each table/filter row is *rendered*
  changed, driven by the existing `viewMode` toggle from the previous change.

Addresses the "Mobile-responsive layout" item from the roadmap. The desktop layout is completely
unchanged — the fixed sidebar and `max-w-5xl` content column render exactly as before. A new
toggle button was added to the bottom of the sidebar (next to the existing dark/light switch) that
flips the whole app into a mobile layout, intended for opening the site in Safari on iPhone (there
is no native app).

- **Manual only, not persisted, no auto-detection**: deliberately no viewport-width or user-agent
  detection — every fresh page load always starts in desktop mode, and switching to mobile is a
  one-tap action the user repeats each time, by request (auto-detection was considered and
  explicitly rejected as an unnecessary source of breakage).
- **Mobile layout**: the sidebar becomes a hidden drawer (`Sidebar.tsx`, `viewMode="mobile"`) that
  slides in from the left as a `fixed` overlay with a dimmed backdrop, opened via a hamburger
  button in a new slim topbar (`App.tsx`) that also shows the current page's title (derived from
  the active route via `NAV_ITEMS` + `matchPath`). Tapping a nav link or the backdrop closes the
  drawer. Main content drops the fixed `max-w-5xl` and switches to full-width with tighter padding.
- **Scope**: only the app shell (`App.tsx` + `Sidebar.tsx`) changed in this pass — no individual
  page (tables, charts) was touched yet. Pages that turn out to be awkward on a narrow screen
  (e.g. wide tables) are a separate follow-up, not covered here.

## Fix: a NaN closing price from Yahoo Finance crashed historical price lookups with a 500

Reported from the first real deployment on TrueNAS: the Historical Net Worth chart went flat,
showing today's total on every single day instead of each day's real value. Root-caused from the
actual `price-feed` container logs (not guessed): `GET /on-date?ticker=...` was returning `500
Internal Server Error` for every ticker, with `ValueError: Out of range float values are not JSON
compliant: nan` in the traceback -- Yahoo Finance had returned a row for the requested date with a
`NaN` closing price (a data gap, not an actual non-trading day), and the code passed that value
straight through into the JSON response instead of treating it as "no usable data for this date".

- This is what triggered the `historical_fallback` mechanism from the previous fix (which
  substitutes today's live price when the historical fetch fails) on *every single date requested*,
  which is exactly why the whole chart went flat at today's value instead of showing each day's
  real number -- the previous fix was working as designed, but was masking this deeper, newly
  surfaced bug rather than the transient network issue it was built for.
- **Fix**: added a shared `_drop_unusable_rows()` helper in `price-feed` that filters out any
  history row with a `NaN` close before picking "the latest available price" -- the exact same
  handling already used for a genuine non-trading day (weekend/holiday), just extended to also
  cover a data gap on a day that *was* a trading day. Applied consistently everywhere a price is
  read from a yfinance history DataFrame: the `/on-date` historical lookup, the `/latest` 5-day
  fallback path (including a NaN guard on the primary `fast_info` path too), the `/intraday`
  hourly series, and the `/history` daily series -- all four had the identical latent
  vulnerability, only one had actually been triggered yet.
- **Nothing was permanently lost**: the live Historical Net Worth chart is recomputed fresh on
  every page load, not stored -- once this fix is deployed, the chart will automatically show the
  correct real values for every past day again on the next visit. No retroactive recovery script
  needed (unlike the earlier frozen month-end-snapshot bug, which really did need a manual
  re-take after the fact).
- **Verified end-to-end**, reproducing the exact real-world scenario (a history DataFrame whose
  requested-date row has a NaN close, mocking yfinance rather than guessing): confirmed the OLD
  code genuinely crashes with 500 in this scenario, confirmed the FIXED code correctly falls back
  to the nearest earlier day with a real close instead (both at the function level and through a
  real FastAPI `TestClient` HTTP call), and confirmed the response is genuinely JSON-serializable
  afterwards (matching Starlette's actual `allow_nan=False` behavior, not just plain `json.dumps`'s
  more lenient default).

## Fix: a failed historical price fetch counted a position as worth zero — including in frozen snapshots

Reported from a real automatic month-end snapshot: Invested showed €0 even though real holdings
exist, Cash was correct. Root-caused together: the live growth chart and the frozen snapshot both
call the exact same valuation function (`compute_portfolio_snapshot`) — there's no separate,
weaker "snapshot" code path. What actually happened is a timing coincidence: the automatic snapshot
ran right after a `docker compose down -v` + `up --build`, which wipes price-feed's in-memory-only
cache, so every ticker needed a fresh Yahoo Finance fetch all at once — and that specific attempt
hit a real network timeout (visible in the container logs at the time). Browsing the live chart
afterwards looked fine only because the cache had since warmed back up, by which point the bad
number was already permanently frozen into the snapshot.

- **The actual code gap**: `compute_asset_growth` (the per-asset price chart) already had a
  fallback for exactly this — if a historical price fetch fails, it uses the latest available
  price as an approximation instead of returning zero. `compute_portfolio_snapshot` (used by the
  live growth chart, the portfolio value, AND both the manual and automatic net worth snapshots)
  had no equivalent fallback: a failed fetch simply meant that position contributed zero to the
  total, with no distinction between "genuinely worth nothing" and "couldn't check right now".
- **Fix**: added the same fallback to `compute_portfolio_snapshot` — when a historical price fetch
  fails, fall back to the latest live price rather than zero, tagged with a new
  `price_source: "historical_fallback"` (distinct from a real `"historical"` price) so it's
  identifiable rather than silently indistinguishable from an exact historical value. When this
  fallback is used, the FX conversion also uses today's live rate instead of the historical date's
  rate, since the price itself is already an approximation from today — pairing it with a
  historical-date rate would have been an inconsistent mix of the two.
- Added a small "≈" indicator with an explanatory tooltip next to any position using this
  fallback, so it's visibly distinguishable from an exact price rather than silently blended in.
- **Deliberately unchanged**: if *both* the historical fetch and the live-price fallback fail
  (a genuine total outage), the position is still marked `"unavailable"` and contributes zero —
  there's no third data source to fall back to, so zero (with the existing red "n/a" badge) is
  honestly the best available answer in that specific case.
- **Verified** with three scenarios against the real function (mocking the price-feed client, not
  just reading the code): (1) historical fetch fails but live succeeds — confirmed it now falls
  back correctly instead of zeroing out; (2) historical fetch succeeds (the normal case) — confirmed
  no regression, behaves exactly as before; (3) both fail — confirmed it still degrades gracefully
  to "unavailable" rather than crashing or fabricating a number.
- Not addressed in this pass (separate, smaller idea not yet actioned): still no protection against
  the frozen month-end snapshot committing if *even the fallback* fails for every position at once
  — this fix substantially narrows that window (now two independent fetches need to fail together,
  not one) but doesn't eliminate it entirely.

## Renamed "Cash" to "Other" in the Summary/Portfolio net worth stat

The top-level "Invested / Cash" stat's second figure sums *all* cash-like accounts regardless of
category (Cash, Emergency Fund, and Pension Fund alike — confirmed in `valuation.py`, the
`cash_total` loop has no category filter), so labeling it "Cash" was misleading whenever a
portfolio has an Emergency Fund or Pension Fund account too. Renamed to "Other" in both places it
appears (Summary/Dashboard and each Portfolio Detail page). Left every other "Cash" label alone —
the `BalanceSection` titled "Cash" (the actual Cash-category account list) and the category-tag
explanation text in Portfolio Allocation's tooltip both correctly refer to the literal Cash tag,
not this aggregate.

## Fix: updating a cash balance (or holding) twice in one day could silently show the wrong value

Reported from a screenshot: pressing "Update" on a cash account, entering a new balance, saving —
the displayed value didn't change. Correctly suspected the database might actually have the right
value while only the display was wrong; confirmed that diagnosis exactly.

- **Root cause**: `CashBalanceEntry`/`HoldingEntry` rows use a random UUID fragment as their id
  (not sortable by creation order), and every "current value" query only ordered by
  `entry_date DESC` with no secondary sort. When two entries share the same `entry_date` — exactly
  what happens every time "Update" is used more than once on the same calendar day — which row
  SQLite returns first for that tie is not guaranteed by anything, so "the current balance" could
  silently resolve to an earlier same-day edit instead of the latest one.
- Confirmed with a raw query against real data: the old query (`entry_date DESC` only) returned an
  earlier same-day update (3050.123) instead of the actual latest one (3064.456) — reproducing the
  exact reported symptom.
- This wasn't limited to the cash balance display. The same pattern (order by `entry_date` with no
  tie-break) also existed in: the Positions table's "current holding per asset" lookup, a manual
  asset's price-history deduplication ("later rows win" only worked if the DB happened to return
  same-day rows in creation order, which isn't guaranteed), and — more seriously — XIRR's cashflow
  reconstruction, where processing same-day entries in the wrong order doesn't just misattribute
  that one day's cashflow but corrupts the running quantity/balance carried forward into every
  subsequent date's delta calculation.
- **Fix**: added a real `created_at` timestamp column to both `HoldingEntry` and
  `CashBalanceEntry`, and added it as an explicit secondary sort key everywhere "the current value"
  or "the next delta" is derived from same-dated rows (`valuation.py`'s cash/holding lookups and
  asset price history, `xirr.py`'s cashflow reconstruction, plus the holdings history listing for
  consistent display ordering). Nullable, since existing rows from before this column existed have
  no reliable value to backfill (`migrate.py` only backfills scalar defaults, not a callable like
  `datetime.utcnow`) — NULL sorts before any real timestamp, which is an acceptable fallback for
  old data and doesn't affect new entries going forward.
- **Verified end-to-end** with the real service running: reproduced the exact bug (two same-day
  balance updates, confirmed the old query returns the stale one), confirmed the fix returns the
  latest update instead, confirmed the same fix works for holdings (a manually-priced asset edited
  twice in one day), and confirmed the migration path itself: simulated an old database missing the
  new columns, restarted the service, confirmed the columns get added automatically, existing data
  stays readable, and new writes get a real timestamp.
- **On the "allow up to 3 decimal places" request**: already fully supported end-to-end (backend
  validation already rounds to 3 decimals via the existing `_round3` validator, and the display
  formatter already allows up to 3 decimal places) — no code change was needed for this specifically.
  Verified directly in the same test: a balance entered as `3064.456` round-trips through the API
  and back out with all three decimals intact. The perceived "3 decimals not accepted" was almost
  certainly the same display bug above (a stale, differently-rounded value showing instead of the
  freshly-entered one), not a real precision limit.

## Info tooltip on the "n/a" price badge, explaining wrong-exchange-suffix ticker failures

Prompted by a real report: two tickers failed to fetch a price (`IS3N.MI`, a `.FRA` ticker). Root
cause for both was the same and confirmed by checking Yahoo Finance directly: neither suffix
exists there. `IS3N` (iShares Core MSCI EM IMI UCITS ETF USD Acc) is listed on Yahoo as
`IS3N.DE` (Xetra), `IS3N.F` (Frankfurt floor), or `IS3N.MU` (Munich) — never `.MI`. `.FRA` isn't a
Yahoo suffix at all; Xetra/Frankfurt is `.DE`. Not a code bug — a data-entry issue, but one the app
didn't help self-diagnose in the exact place it shows up.

- The Positions table already showed a small red "n/a" badge next to a price that failed to
  resolve, and Portfolio Detail already had a page-level banner explaining the likely cause
  (missing/wrong exchange suffix, with `.MI`/`.DE`/`.AS` examples) — but the banner is easy to miss
  once scrolled past, and gives no in-context link back to which specific position is affected when
  several are on the page.
- Added a "?" tooltip directly on the "n/a" badge itself (same `InfoTooltip` pattern used
  throughout the app), explaining: Yahoo Finance couldn't find a quote for the exact ticker; the
  most common cause is a missing/wrong exchange suffix, with examples (`.MI` Milan, `.DE`
  Xetra/Frankfurt, `.AS` Amsterdam, `.PA` Paris) and a note that the same fund can be cross-listed
  under different suffixes on different exchanges — suggests checking `finance.yahoo.com` directly
  to confirm which one Yahoo actually lists it under; also notes that if the ticker does look
  correct, it could be a temporary Yahoo Finance connectivity issue rather than a wrong symbol
  (`price-feed`'s own logs show the underlying error either way).
- Verified with a real `tsc -b` + `vite build` after the change.

## Audit round 3: exhaustive re-test, no new bugs found

Asked to re-verify everything once more, more thoroughly, given how many real bugs the first two
rounds had turned up. Rebuilt the test environment from scratch and ran a much wider battery of
scenarios against the three real services running together, this time with strict assertions
(the test fails loudly if any count or value is even slightly off) rather than eyeballing output:

- **Rich, realistic dataset**: 2 portfolios, 3 assets, 3 holdings, 3 cash accounts covering all
  three categories (Cash/Emergency Fund/Pension Fund), 2 net worth snapshots in different
  currencies, 2 geo-allocation files — export, heavy modification (added a portfolio, deleted a
  cash account, deleted an asset with a holding via the gateway's delete route, added a
  differently-currencied snapshot), preview (confirmed no-op), restore, then asserted every single
  piece reverted exactly: portfolio names, all 3 assets including the deleted one, cash accounts
  with their correct categories, the exact currency-by-currency snapshot breakdown (the newly
  added one gone, the original one back), and both geo-allocation files.
- **Restoring twice in a row**: confirmed two separate, correctly timestamped safety-backup
  folders were created (not overwritten by each other).
- **Partial failure**: killed geo-allocation mid-restore. Confirmed core-networth's restore had
  already completed successfully and the error message correctly explained that only the
  geo-allocation half needed a retry — then confirmed retrying (once geo was back up) completed
  the restore fully, including the previously-missed geo-allocation file.
- **Empty-state edge cases**: exporting and restoring a completely empty install works cleanly;
  restoring an empty backup onto a non-empty install correctly wipes everything back to zero
  without erroring; the app remains fully usable immediately afterwards either way.
- Re-confirmed invalid-file rejection still works unchanged throughout all of the above.

No new bugs found this round. `docker-compose.yml`'s backup bind mounts re-checked against the
hardcoded `/backups` path used in both services' backup code and confirmed consistent.

## Audit round 2: four more real bugs found in the new backup/restore code

Asked to recheck everything once more before considering it done. Found and fixed four issues,
each reproduced with a real failing test before fixing, then re-verified fixed:

- **A genuinely old backup would have been permanently unrestorable.** Validation required every
  *current* table to be present, but a backup taken before some future table existed would fail
  that check and get rejected outright -- meaning the `create_all` fix below could never actually
  run for the case it was built for. Narrowed the check to just `portfolios` + `assets` (present
  since the very first version), which is enough to rule out "this clearly isn't one of our
  files" without blocking legitimate older backups from being accepted and then migrated up.
  Reproduced by dropping a table from a real db, confirming it was wrongly rejected, then
  confirming it's accepted and the table cleanly recreated after the narrowing fix.
- **Restoring an old backup missing a whole table (not just a column) wouldn't have recreated
  it.** The post-restore step only re-ran the column-level migration, never `Base.metadata.create_all`
  -- fine for a missing column, not for a missing table entirely. Now runs both, in the same order
  already used at every normal app startup.
- **A non-SQLite file uploaded as the database part crashed with a raw 500** instead of a clean
  400. SQLite only actually validates the file format on the first real query, not at connection
  time, and the query-time errors weren't caught -- only the (rarely-failing) connect() call was.
  Reproduced the 500, then fixed by catching `sqlite3.DatabaseError` around the actual queries too.
- **`core-networth`'s `/backup/export` could have thrown an unhandled 500** instead of a clean 400
  if called with no database file present yet (belt-and-suspenders fix -- `preview`/`restore`
  already handled this correctly, `export` was the one endpoint that didn't).

Also, smaller fixes made alongside the same pass:
- The zip-slip guard in `geo-allocation`'s restore used a string-prefix check, which a
  similarly-named sibling directory could in principle have slipped past; switched to
  `Path.is_relative_to` for an exact containment check. Re-verified the same malicious-path test
  still gets rejected and a legitimate archive still passes.
- The uploaded database's temp file is now written inside the same data directory instead of the
  system temp folder, so the final swap is a same-filesystem atomic rename instead of a
  cross-device copy (matters if the data directory is a separate Docker volume from `/tmp`).
- The Settings page didn't reset the file `<input>`'s value when a preview failed, which meant
  re-selecting the exact same filename afterwards (e.g. after fixing and re-exporting under the
  same name) wouldn't fire `onChange` in the browser and would leave the user stuck.

Re-verified after all of the above: a full round trip (portfolio, asset, holding, cash account
with a balance, snapshot, and a geo-allocation file all present) exported, modified, previewed
(confirmed no-op), and restored -- confirmed every piece reverted exactly, and the app remained
fully functional afterwards (created new data successfully post-restore). Also re-confirmed
garbage files and structurally-wrong zips are still cleanly rejected with nothing touched.

## New: Export / restore a full backup from the UI

Settings → Backup & Restore. Complements the existing automatic daily backups (which only ever
live inside Docker volumes/bind mounts) with an on-demand, downloadable, and restorable version.

- **What's included**: `core-networth`'s database (portfolios, assets, holdings, cash accounts,
  net worth snapshots) and `geo-allocation`'s uploaded ETF factsheets. `price-feed` is deliberately
  excluded, same as the daily backup — it's only cache, not real data.
- **Export**: a single downloadable `.zip` containing `manifest.json` (export timestamp + stats)
  plus each service's own data, orchestrated by the gateway (`GET /api/backup/export`) since
  the two services have no shared database and shouldn't need to know about each other.
- **Restore**, deliberately conservative since it's destructive:
  1. The uploaded file is validated (SQLite integrity check + expected tables present, valid zip
     structure) *before* anything live is touched — an invalid file is rejected with nothing changed.
  2. An automatic safety copy of the *current* data is taken first, into the same `./backups/`
     directory the daily job already uses (`pre-restore-<timestamp>/`) — already gitignored,
     already bind-mounted, no new paths to remember.
  3. The database file is swapped in, then the same lightweight migration used at every startup is
     re-run, so an older backup missing a column added since is silently brought up to date.
  4. The frontend shows a preview (export date + counts: portfolios, assets, holdings, cash
     accounts, snapshots, ETF factsheets) *before* asking for confirmation, reading the manifest
     straight out of the uploaded file without calling either backend service.
- **Bugs caught while testing with the real services actually running together (not just by
  reading the code)**:
  - `python-multipart` was missing from `core-networth`'s and `gateway`'s `requirements.txt` --
    neither had ever needed file uploads before this. Both crashed on startup with a clear error;
    added the dependency to both.
  - `core-networth`'s snapshot table is actually named `networth_snapshots`, not
    `net_worth_snapshots` as first written in the new backup code -- caught because the export
    manifest showed `snapshots: null` instead of a real count.
- **Verified end-to-end** with all three services actually running together (not mocked): a full
  round trip (export → modify data → preview, confirmed it changes nothing → restore → confirmed
  data reverted exactly to the exported state, including the geo-allocation file) and rejection of
  both a garbage file and a well-formed zip with the wrong internal structure, confirming neither
  touches any live data.

## Code audit fixes: asset deletion, cash account editing, cross-service cleanup

A full read-through of every backend route, schema, and cascade rule (requested after all the
originally planned features were implemented), looking for gaps the changes so far should have
covered but didn't. Found and fixed three things, each verified against real running code, not
just by inspection:

- **Fixed: deleting an asset that's held anywhere threw a 500 and never actually deleted it.**
  `Asset.holdings` (unlike `Portfolio.holdings`/`Portfolio.cash_accounts`) had no ORM cascade, and
  there's no SQLite foreign-key enforcement configured either. Deleting an asset made SQLAlchemy
  try to null out `HoldingEntry.asset_id` on every holding referencing it to keep them
  "orphaned-but-valid" — except that column is `NOT NULL`, so the delete failed with an
  `IntegrityError` before anything was removed. This directly contradicted the UI's own
  confirmation dialog ("It will be removed from every portfolio it appears in"). Fixed by
  explicitly bulk-deleting the asset's `HoldingEntry` rows before deleting the asset itself.
  Verified with two isolated fresh-session reproductions (matching the real one-session-per-request
  pattern): confirmed the old code actually throws `IntegrityError`, then confirmed the fixed code
  deletes both the asset and its holdings cleanly with no error, and that the portfolio's snapshot
  computation still works afterwards.
- **New: `PATCH /cash-accounts/{id}`.** Portfolio, Asset, and HoldingEntry all had a way to edit
  their fields after creation; `CashAccount` (also used for Emergency Fund and Pension Fund)
  didn't — the only way to fix a typo in its name, change its currency, or re-tag its category was
  to delete and recreate it, losing its whole balance history. Added `CashAccountUpdate` schema +
  route, plus `api.updateCashAccount` and a new "Edit" control (separate from the existing balance
  "Update") on each Cash/Emergency Fund/Pension Fund row in `PortfolioDetail.tsx`, letting name,
  currency, and tag be changed in place. Verified via a real `TestClient` run: renamed, re-tagged,
  and changed currency on an account, confirmed all three persisted and the account kept the same
  id (so a balance added afterwards is still attached to the same history).
- **New: deleting an asset also cleans up its `geo-allocation` factsheet, if any.** That service
  has no knowledge of asset deletions in `core-networth` (separate microservice, no shared
  database), so a deleted asset's uploaded Excel file + parsed allocation record used to stay
  behind forever with no way to clean it up short of reaching into the container's filesystem.
  Added a dedicated `DELETE /api/core/assets/{id}` route in the gateway (declared before the
  generic proxy) that deletes from `core-networth` first, then best-effort deletes the matching
  record from `geo-allocation` — a 404 there (no file was ever uploaded, the common case) is not
  treated as an error. Verified end-to-end with all three real services actually running
  (core-networth + geo-allocation + gateway, each pointed at the others via env vars): simulated an
  uploaded factsheet, deleted the asset through the gateway, confirmed both the asset and the
  factsheet record were gone (404 on both), and separately confirmed the common no-file-uploaded
  case still returns a clean 204 with nothing to clean up.

## Info tooltips across the rest of the app

Extends the XIRR "?" tooltip pattern to every other spot where a non-obvious concept is shown
without explanation, per the list reviewed together (Dashboard/Portfolio Detail's live-chart and
Day-view items intentionally excluded from this round):

- **Historical Net Worth** (page title): explains these are frozen points in time, separate from
  the always-re-valued live chart elsewhere.
- **Currency Exposure** (page title): explains it shows quotation currency, not a fund
  look-through, with the EUR-ETF-holding-USD-stocks example.
- **Geographic Allocation**: one tooltip on the Chart/Map toggle (only shown in Map view) explaining
  the shading is relative to the largest single-country exposure, not an absolute scale; one on
  the Stock/Bond/All filter explaining what it does and doesn't include.
- **Portfolio Allocation** (page title): explains the category tag (Stock/Bond/Cash/Emergency
  Fund/Pension Fund) is freely set per asset/account, not locked to which section created it.
- **Asset Detail**: a tooltip next to the range buttons, shown only for manually-priced assets,
  explaining why there's no "Day" view (no hourly data can exist for a hand-entered price).
- **Portfolio Detail → Pension Fund** section: explains it's tracked exactly like a cash balance
  (name + balance, updated by hand), with no contribution/projection modeling — and that this was
  a deliberate simplification after a separate pension-projection feature was tried and removed.
- `BalanceSection` (shared by Emergency Fund/Cash/Pension Fund) gained an optional `tooltip` prop
  so future sections can opt into the same pattern without duplicating the header markup.
- Verified with a real `tsc -b` + `vite build` after all edits, and re-reviewed the
  Geographic Allocation JSX by hand (it went through a couple of intermediate multi-step edits)
  to confirm every div/tag stayed balanced despite the build already passing.

## Fix (round 2): XIRR tooltip still ran off-screen — real cause was a wrong height guess

- The previous fix decided "open above or below the button" using a **guessed** fixed panel
  height (160px). The real content (5 paragraphs) renders far taller than that on a narrow
  screen, so the guess was wrong and the panel still opened upward and overflowed the top —
  confirmed by a real screenshot showing exactly this on `localhost:4173`.
- Replaced the guess with an actual **measure-then-place** approach: the panel first mounts
  invisibly (`visibility: hidden`) at its real final width so text wraps exactly as it will when
  shown, its true rendered height is read directly from the DOM (`offsetHeight`), and *then* the
  side (above/below) and final position are chosen from that real number — with the position
  clamped to the viewport regardless of which side gets picked. Re-runs on scroll/resize using
  the already-measured height (no re-flicker).
- **Testing note, disclosed rather than glossed over**: I could not verify this visually in a
  real browser this round — the sandbox here has no network access to Playwright's browser
  download servers, only a short allowlist of package registries. I verified it compiles and
  builds cleanly (`tsc -b`, `vite build`) and re-checked the placement logic against the same
  scenarios as before (including a long-content/narrow-viewport/button-near-bottom case matching
  the reported screenshot), but the actual on-screen result on your machine still needs a real
  check — please confirm on `localhost:4173` again.

## Fix: XIRR info tooltip ran off-screen near the top of the page

- The tooltip panel always opened upward and stayed horizontally centered under the "?" via pure
  CSS (`bottom-full`, centered) — fine in the middle of a page, but the "?" sits right under the
  chart near the top of Summary/portfolio pages, so the panel routinely got clipped by the top of
  the viewport (unreadable first lines) and could also overflow left/right near narrow viewports.
- Rewrote `InfoTooltip` to compute its position dynamically from the button's actual
  `getBoundingClientRect()`: flips to open **downward** when there isn't enough room above,
  and clamps its horizontal position to stay within the viewport with an 8px margin on
  narrow/edge cases. Recalculates on scroll and resize while open. Added a `max-h-[70vh]` +
  scroll as a last-resort safety net for unusually small viewports.
- Traded away the small pointer arrow that used to visually connect the panel to the "?" — with
  dynamic flipping/clamping it would need its own offset calculation to stay aligned, and wasn't
  worth the added complexity for a tooltip that's already visually anchored right next to the icon.
- Verified the positioning math directly (not just by inspection): a standalone script
  reproducing the exact same calculation confirmed correct placement across 6 scenarios — button
  near the very top (the reported bug), near the bottom, near the left/right edges, a normal
  mid-page case, and a narrow mobile viewport — all landing within bounds. Also re-confirmed with
  a real `tsc -b` + `vite build` that the change compiles and bundles cleanly.

## XIRR info tooltip

- Added a "?" info icon next to the "Annualized return (XIRR)" label on Summary and each
  portfolio page, opening a short explanatory panel on hover, keyboard focus, or tap. Covers what
  the number means (money-weighted return, separate from money added/withdrawn), why 1Y and
  All-time can show the same value (less than a year of history so far), why the rate can look
  very large with only a few days/weeks of real history, and the known cash-vs-interest
  simplification.
- New reusable `InfoTooltip` component (`components/InfoTooltip.tsx`) — no icon library
  dependency, plain CSS/SVG-free circled "?" using the existing theme tokens. Works via
  hover *and* click/keyboard focus (closes on outside click or Escape), since hover-only would
  leave touch and keyboard users with no way to open it — relevant given mobile layout is on the
  roadmap.
- Prompted by walking through a real case together: a portfolio only 3 days old showed +155% on
  both 1Y and All-time. Traced with a new read-only diagnostic script
  (`services/core-networth/app/debug_xirr.py`, run via
  `docker compose exec core-networth python -m app.debug_xirr <portfolio_id|combined>`) that
  prints the exact reconstructed cashflows (date, amount, source asset/account) for a portfolio
  and independently re-verifies the solved rate's NPV — confirmed the XIRR math itself was
  correct (NPV check landed on 0.000000); the large number was simply a ~0.7% gain over 3 days
  annualized, the same effect that already keeps XIRR off the Day/Week/Month views. Decision made
  together: leave the calculation as-is (it self-corrects as real history accumulates) and make
  it understandable in the UI instead of adding a minimum-history threshold.

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

Implements the "Real return (CAGR / XIRR)" roadmap item.

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
