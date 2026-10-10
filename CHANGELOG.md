# Changelog

Every change to Net Worth Suite, newest first. Each day is a `##` heading, and each change made
that day a `###` entry labelled **Added**, **Changed**, **Fixed**, **Removed**, **Refactored**,
**Docs** or **Audit** (a review pass, with whatever it found). The index right below lists every
entry by area, so everything ever done to, say, XIRR or bank-sync can be read in one go.

Why a piece of code is the way it is -- the bug a line guards against -- is kept per file in
[`DESIGN_NOTES.md`](./DESIGN_NOTES.md); this file is the record of *when* and *what* changed.

## 2026-10-10

### Fixed -- Downloaded backup and CSV export always used the generic filename, never the dated one (AGE-48)

Found while Socrate wrote `tests/e2e/test_downloads.py` (AGE-10): not a Firefox/WebKit quirk, a
CORS bug in the gateway that hits every browser, Chromium included. `gateway/app/main.py`'s
`CORSMiddleware` never exposed `Content-Disposition` to cross-origin `fetch()` calls -- and in
production the frontend and the gateway sit on different ports by design (`docker-compose.yml`:
`4173` vs `8080`), so that is every request. `frontend/src/api/client.ts`'s `downloadFile` read
that header to name the file and, finding nothing, always fell back to its static name: every
backup downloaded as `networth-suite-backup.zip` regardless of the day, silently overwriting the
previous one in the owner's Downloads folder, and every transactions export as `transactions.csv`
instead of `transactions-<date>.csv`. Added `expose_headers=["Content-Disposition"]` to the
middleware. The transactions export has a second, independent cause: it is served through the
gateway's generic proxy (`proxy()`), which rebuilt its `Response` with only the upstream
`content-type` and dropped every other header -- so the filename never left the gateway even with
CORS fixed. `proxy()` now forwards `Content-Disposition` when the module sets one.
`tests/system/test_gateway.py` adds two tests with a real cross-origin `Origin` header, one per
download, so this cannot regress silently again.

## 2026-10-09

### Added -- CSV import is now reachable from the app, not just the API (AGE-36)

AGE-7 (2026-10-07) added the import endpoints, but nothing in the UI could reach them -- a user
could only import a bank statement with `curl`. Expenses -> Log now has an "Import CSV" button on
the selected account (not shown for meal-voucher accounts, which don't accept CSV import at all):
pick a file, map its columns, and pick the date format and decimal separator -- both start
unselected, with no preselected guess, same as the backend (see `DESIGN_NOTES.md`). "Preview
import" shows the same report the commit would produce, row by row -- how many would be written,
and for every duplicate or error row, the reason, not just a count. Only from that preview can
"Import N transactions" commit, with a client-generated `Idempotency-Key` reused if that one
request is retried, so a double click (or a retried network failure) can't write the same file
twice.

### Added -- Out-of-app e-mail alerts for a budget exceeded, a bank consent expiring, a sync that keeps failing (AGE-11)

Until now a budget going over, a bank consent about to expire or a bank sync stuck failing only
showed up inside the app -- someone who doesn't open it for a week found out after the fact, or
not at all. `shared/notify.py` adds a plain SMTP e-mail channel, off by default (`SMTP_HOST` unset
means no outbound connection and no change in behaviour at all) and shared by core-networth and
bank-sync rather than built twice. With it configured:

- core-networth's scheduler (`app/alerts.py`) sends one e-mail the first time a budget's spending
  for the current month crosses its limit -- `Budget.over_alerted_month` keeps it from repeating
  every cycle, and resets on its own at the next calendar month.
- bank-sync's scheduler (`app/alerts.py`) sends one e-mail when a consent will expire within 7
  days (same margin the in-app warning already uses), and one when a sync has failed 3 cycles in a
  row -- both only once per problem, and again if the problem returns after being resolved
  (`BankLink.consent_warned_until`, `sync_failure_streak`, `sync_error_alerted`).

No message carries a balance, an amount or an account identifier -- only which budget or which
bank link the alert is about -- since an e-mail passes through machines that aren't the owner's
own. See `README.md` "Configuration" and "Your data", `services/bank-sync/README.md` "Day to day",
and `DESIGN_NOTES.md` for why e-mail and not a hosted push service. New environment variables
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO`, `SMTP_USE_TLS`
(`.env.example`, `docker-compose.yml`).

## 2026-10-08

### Added -- Contract tests for price-feed's own talk to Yahoo (AGE-6)

`price-feed/app/main.py`'s code that actually calls `yf.Ticker` (`_fetch_ticker_price`,
`_ticker_currency`, `_fetch_price_on_date`, `_fetch_intraday`) was exercised only through
`TtlCache` in isolation (`test_price_cache.py`) -- the five real bugs `DESIGN_NOTES.md` lists
under `price-feed` had no test keeping them fixed. `tests/unit/test_price_feed_contract.py` fakes
`yf.Ticker` at the boundary with shapes modelled on real, not ideal, Yahoo answers (a `fast_info`
missing `currency` entirely, a NaN `last_price`, a NaN `Close` row mid-frame, a frame still only
half full because the trading day is in progress) and pins each fix: the currency guess expires
instead of sticking forever, today's partial bar/series is never cached as the finished day in
either `_fetch_price_on_date` or `_fetch_intraday`, a NaN price falls through to the history
fallback instead of shipping, and a NaN close row is dropped instead of served. A sixth test pins
the general contract (CLAUDE.md principle 1): a ticker Yahoo has nothing for, or a request that
fails outright, comes back as a 404, never a crash or a fabricated number. No test reaches the
network -- `yf` is stubbed at import time, same as `test_price_cache.py` -- and each of the five
was verified to fail by reverting its one-line fix by hand (see the task for the exact edit and
the error each produced). Adds 7 tests, +0.3s to the unit tier.

### Fixed -- Geo-allocation: an unrecognized country code could silently count as classified (AGE-8)

A country label that merely *looked* like an ISO alpha-2 code (two ASCII letters -- a typo, or a
territory this app doesn't cover) was accepted outright by `normalize_country`'s bare-code
fallback as "a recognized country", counted in `total_weight()` as fully classified, and then fell
into "Other / Unclassified" at the region-grouping step with nothing to tell it apart from real
cash -- the same silent-"Other" failure that had already bitten the project twice before, reached
through a third, unguarded path. The fallback now only accepts a bare code this app already knows
how to name and region; anything else is reported in `unmapped_labels` like any other unrecognized
label, which lowers `covered_weight_pct` and surfaces through the existing "Partial coverage"
warning instead of disappearing. Also extended country coverage across `countries.py`,
`regions.py`, `country_names.py` and the frontend's `isoNumericCodes.ts` crosswalk with ~28 more
real countries and common offshore fund domiciles (Uruguay, Panama, Cayman Islands, Bermuda,
British Virgin Islands, Puerto Rico, Montenegro, North Macedonia, Bosnia and Herzegovina, Sri
Lanka, Macau, Mauritius, Tunisia, Ivory Coast and others -- see `DESIGN_NOTES.md`), so fewer real
exposures hit the gap this fix closes in the first place.

## 2026-10-07

### Refactored -- `PortfolioDetail.tsx` and `Transactions.tsx` split into components (AGE-9)

Both pages had grown past the size an agent keeps in head: `PortfolioDetail.tsx` was 1,128 lines,
`Transactions.tsx` 823. No behaviour changed -- same fields, columns, sorting and filters.

`PortfolioDetail.tsx` (now 194 lines) keeps the page's own state (snapshot/history/growth/XIRR
reload) and renders three already-independent pieces that used to be functions in the same file:
`components/PositionsSection.tsx` (185 lines, plus the shared `removeAssetFromPortfolio` helper),
`components/BalanceSection.tsx` (608 lines, the Cash/Emergency Fund/Pension Fund sections), and
`components/AddPositionForm.tsx` (165 lines, used by both).

`Transactions.tsx` (now 99 lines) keeps only the data every section needs (accounts, categories,
the selected account, the portfolio-wide transaction list the refund picker reads) and renders
`components/TransactionLogForm.tsx` (367 lines: the create form, including the refund/transfer
pickers) and `components/TransactionList.tsx` (471 lines: search, filters, bulk categorize,
inline edit/convert-to-transfer, CSV export, pagination -- the toolbar row next to "Export CSV"
is where AGE-36's CSV import button belongs). The two talk to the page only through explicit
props and callbacks (`onLogged`, `onTransactionsChanged`, a `reloadKey` counter) -- no new shared
state.

### Added -- CSV import of bank statement transactions (AGE-7)

`GET /transactions/export.csv` had no counterpart for the other direction: every account
`bank-sync` doesn't cover meant entering a statement's transactions by hand, one at a time. Two
new endpoints on `core-networth`, `POST /cash-accounts/{id}/transactions/import/preview` and
`POST /cash-accounts/{id}/transactions/import`, both taking the raw CSV text, a `column_mapping`
(which column is the date, amount, and optionally currency/description/counterparty) and the
file's `date_format` as an explicit `strptime` pattern -- day/month order is never guessed, since
getting it wrong silently backdates every row by a plausible-looking month. `preview` parses and
reports what would happen without writing anything; `commit` runs the identical parsing and writes
only the rows marked "import" in one transaction, so a file is never left half-imported.

Re-importing the same file does not create duplicate transactions: each imported row gets an
`import_fingerprint` (a hash of account/date/direction/amount/counterparty/note, with an occurrence
counter for genuinely repeated same-day transactions) and a row already present under that
fingerprint is reported as a duplicate and skipped. A new partial unique index on
`cash_transactions(account_id, import_fingerprint)` (`migrate.py`) backs this at the database
level too, in case two imports of the same file race each other. A row whose CSV-given currency
doesn't match the account's own currency is discarded with a reason rather than converted --
`CashTransaction` has no currency of its own, every amount is already in its account's currency.
Existing merchant rules apply to imported counterparties exactly as they do to hand-entered ones.

The upload/preview UI is a separate, frontend task -- see the endpoint shapes above and
`DESIGN_NOTES.md`.

## Index by area

### Expenses, transactions and budgets

- 2026-10-10 · Fixed -- Downloaded backup and CSV export always used the generic filename, never the dated one (AGE-48)
- 2026-10-09 · Added -- CSV import is now reachable from the app, not just the API (AGE-36)
- 2026-10-09 · Added -- Out-of-app e-mail alerts for a budget exceeded, a bank consent expiring, a sync that keeps failing (AGE-11)
- 2026-10-07 · Refactored -- `PortfolioDetail.tsx` and `Transactions.tsx` split into components (AGE-9)
- 2026-10-07 · Added -- CSV import of bank statement transactions (AGE-7)
- 2026-10-04 · Added -- Dividend/coupon/interest income is now settable and visible in the frontend
- 2026-10-04 · Added -- Dividend/coupon/interest income, correctly counted as return in XIRR
- 2026-10-02 · Added -- Budgets, recurring payments, monthly savings, search, CSV export, balance check
- 2026-10-01 · Added -- Fix transactions after the fact, transfers from one-sided entries, bank-sync in backups and alerts
- 2026-10-01 · Added -- Categorize by merchant -- Expenses -> Merchants
- 2026-09-09 · Added -- Decimal input accepts "," as well as "." -- and a Refund transaction type
- 2026-08-30 · Added -- Transfers between cash accounts, excluded from expense statistics
- 2026-08-26 · Fixed -- A transaction logged the same day as the opening balance was silently ignored
- 2026-08-26 · Added -- Meal vouchers (quantity-based cash accounts)
- 2026-08-25 · Added -- Expense category colors are now assigned automatically, no fixed limit
- 2026-08-25 · Fixed -- "Update" balance button still showed on Cash/Emergency Fund, Pension Fund never excluded
- 2026-08-25 · Added -- Expenses frontend (Transactions, Expense Categories, Expense History)
- 2026-08-25 · Added -- Expense tracking backend (income/expense ledger for cash accounts)

### bank-sync (automatic capture from the bank)

- 2026-10-09 · Added -- Out-of-app e-mail alerts for a budget exceeded, a bank consent expiring, a sync that keeps failing (AGE-11)
- 2026-10-04 · Fixed -- bank-sync would not start: `python-multipart` missing from its requirements
- 2026-10-02 · Added -- Budgets, recurring payments, monthly savings, search, CSV export, balance check
- 2026-10-01 · Added -- Fix transactions after the fact, transfers from one-sided entries, bank-sync in backups and alerts
- 2026-10-01 · Added -- Categorize by merchant -- Expenses -> Merchants
- 2026-09-28 · Fixed -- Bank-sync follows pending card payments until booked
- 2026-09-14 · Added -- Bank-sync logs every transaction to a single raw audit CSV
- 2026-09-14 · Added -- Bank-sync auto-categorizes via merchant_category_code, full note text, plus a real bug fix
- 2026-09-14 · Fixed -- Bank-sync now reads the real Enable Banking transaction format correctly
- 2026-09-14 · Added -- `bank-sync` service -- automatic expense capture via Open Banking

### Valuation, prices and XIRR

- 2026-10-08 · Added -- Contract tests for price-feed's own talk to Yahoo (AGE-6)
- 2026-10-04 · Added -- Dividend/coupon/interest income is now settable and visible in the frontend
- 2026-10-04 · Added -- Dividend/coupon/interest income, correctly counted as return in XIRR
- 2026-08-27 · Added -- Pension Fund accounts count as an investment in XIRR, not a cash contribution
- 2026-08-27 · Audit -- The XIRR issue was residual data damage, not a remaining bug -- plus a new "backdate a balance" capability
- 2026-08-26 · Fixed -- XIRR (annualized return) could show a large, wrong negative number
- 2026-08-26 · Fixed -- Snapshot/history/growth/xirr crashed with a 500 on portfolios with older cash accounts
- 2026-08-20 · Fixed -- A NaN closing price from Yahoo Finance crashed historical price lookups with a 500
- 2026-08-01 · Fixed -- A failed historical price fetch counted a position as worth zero — including in frozen snapshots
- 2026-07-29 · Fixed -- Updating a cash balance (or holding) twice in one day could silently show the wrong value
- 2026-07-21 · Added -- XIRR info tooltip
- 2026-07-21 · Added -- Real return: XIRR (money-weighted annualized return)
- 2026-07-20 · Fixed -- Every ETF's price chart showed "Not Found"
- 2026-07-20 · Added -- Week range button, and real hourly prices on "Day" (broker-style chart)
- 2026-07-20 · Added -- Growth stats per period, and the live chart now always reaches today
- 2026-07-20 · Added -- Real historical prices (live chart is now actually accurate over time)
- 2026-07-19 · Changed -- Price feed reliability, cash and allocation tables, Stock/Bond tag, automatic column migrations

### Portfolios, accounts and allocation

- 2026-10-08 · Fixed -- Geo-allocation: an unrecognized country code could silently count as classified (AGE-8)
- 2026-10-07 · Refactored -- `PortfolioDetail.tsx` and `Transactions.tsx` split into components (AGE-9)
- 2026-09-17 · Added -- Positions can be tagged Emergency Fund, and added directly from that section
- 2026-08-26 · Fixed -- Removing a cash account retroactively rewrote past net worth history
- 2026-07-29 · Changed -- Renamed "Cash" to "Other" in the Summary/Portfolio net worth stat
- 2026-07-20 · Changed -- Geographic Allocation: chart and country table as two separate cards
- 2026-07-20 · Changed -- Geographic Allocation: contained chart layout, and a world map view
- 2026-07-20 · Added -- Per-asset price chart and Currency Exposure
- 2026-07-19 · Added -- Editable tag on Cash / Emergency Fund / Pension Fund
- 2026-07-19 · Added -- Unified allocation categories, Emergency Fund, and simplified Pension Fund
- 2026-07-19 · Changed -- Price feed reliability, cash and allocation tables, Stock/Bond tag, automatic column migrations

### Interface, charts and mobile

- 2026-08-26 · Added -- Palettes now recolor the whole theme, not just the accent -- plus a Gray palette
- 2026-08-26 · Added -- Consolidated sidebar (11 -> 7 pages) and customizable accent palette
- 2026-08-26 · Fixed -- Clicking a SegmentedControl button inside a form submitted it early
- 2026-08-25 · Fixed -- Two remaining mobile overflow spots found in real-device testing
- 2026-08-25 · Added -- Mobile-friendly tables and filter controls across every page
- 2026-07-29 · Added -- Info tooltip on the "n/a" price badge, explaining wrong-exchange-suffix ticker failures
- 2026-07-21 · Added -- Info tooltips across the rest of the app
- 2026-07-21 · Fixed -- (round 2) XIRR tooltip still ran off-screen — real cause was a wrong height guess
- 2026-07-21 · Fixed -- XIRR info tooltip ran off-screen near the top of the page
- 2026-07-21 · Added -- XIRR info tooltip
- 2026-07-21 · Added -- Chart Y-axis auto-zoom on Day/Week/Month/Year, plus an absolute/percentage toggle
- 2026-07-21 · Fixed -- Live chart silently skipped days instead of accumulating them
- 2026-07-19 · Added -- Dark mode "Deep Ink"
- 2026-07-19 · Changed -- Palette correction: cream panels, deeper brown ink
- 2026-07-19 · Changed -- Visual redesign "Ledger Light"
- 2026-07-19 · Added -- Value column decimals and in-app balance editing
- 2026-07-19 · Added -- Chart time-range filter and 3-decimal currency precision

### Backups, data and automation

- 2026-10-10 · Fixed -- Downloaded backup and CSV export always used the generic filename, never the dated one (AGE-48)
- 2026-10-03 · Added -- Backup rotation: `./backups/` no longer grows forever
- 2026-10-01 · Added -- Fix transactions after the fact, transfers from one-sided entries, bank-sync in backups and alerts
- 2026-07-22 · Audit -- Audit round 2 -- four more real bugs found in the new backup/restore code
- 2026-07-22 · Added -- Export / restore a full backup from the UI
- 2026-07-20 · Added -- Automation: price refresh, monthly snapshot catch-up, and daily backups
- 2026-07-19 · Added -- New tab: Historical Net Worth (frozen manual snapshots)
- 2026-07-19 · Docs -- Data persistence clarification (docs only, no code changes to runtime behavior)

### Codebase: refactors, audits, docs

- 2026-10-08 · Added -- Contract tests for price-feed's own talk to Yahoo (AGE-6)
- 2026-10-07 · Refactored -- `PortfolioDetail.tsx` and `Transactions.tsx` split into components (AGE-9)
- 2026-10-06 · Refactored -- `core-networth/app/main.py` split into one router per area
- 2026-10-06 · Docs -- A test tier that cannot run is not a tier that passed
- 2026-10-04 · Added -- CI builds and starts the real `docker-compose.yml`, not just the Python modules
- 2026-10-04 · Docs -- Test counts in `tests/README.md` match what CI reports
- 2026-10-04 · Fixed -- bank-sync would not start: `python-multipart` missing from its requirements
- 2026-10-04 · Docs -- How to build from a Git URL: which services need the repository root as context
- 2026-10-03 · Docs -- Agents merge their own work onto `main`, with CI as the gate
- 2026-10-03 · Docs -- CLAUDE.md introduces the project and lets agents change anything, safely
- 2026-10-03 · Docs -- CLAUDE.md spells out which documents every kind of change must update
- 2026-10-03 · Docs -- Repository cleanup: README rewritten, bank-sync docs in one place, stale files removed
- 2026-10-03 · Docs -- Code comments say what is, `DESIGN_NOTES.md` says what was
- 2026-10-03 · Removed -- Dead tools, one-off migrations, FastAPI lifespan, shared frontend helpers
- 2026-10-03 · Refactored -- Second accidental-complexity pass (no behavior change)
- 2026-09-14 · Changed -- Generalized every host-specific reference so the project runs identically on a NAS or a plain PC
- 2026-09-14 · Docs -- Everything in English, README rewritten to match the current feature set
- 2026-09-14 · Audit -- Full codebase sweep for bugs and dead code
- 2026-08-26 · Refactored -- Accidental-complexity cleanup pass (no behavior change)
- 2026-07-22 · Audit -- Audit round 3 -- exhaustive re-test, no new bugs found
- 2026-07-21 · Fixed -- Code audit: asset deletion, cash account editing, cross-service cleanup

## 2026-10-06

### Refactored -- `core-networth/app/main.py` split into one router per area

`main.py` had grown to 1,545 lines and 67 endpoints -- the file every change to core-networth had
to touch, and the one an agent was most likely to get wrong because it no longer fit in context.
Split into `app/helpers.py` (the shared `_get_or_404`/`_paginate`/idempotency helpers) and one
`app/routers/*.py` per area -- `portfolios` (portfolios, assets, holding entries), `cash` (cash
accounts, balances), `expenses` (categories, merchants, transactions, transfers, summary/monthly,
recurring), `budgets`, `networth` (snapshots, history, growth, XIRR, intraday, frozen manual
snapshots) and `backup` -- each an `APIRouter` included from `main.py`, which now only holds app
setup (CORS, the lifespan task, the validation-error handler, `/health`, `/scheduler/run-now`).

No endpoint's path, method, response shape or status code changed, and neither did the gateway or
`gateway/app/registry.py`, which only ever proxy by URL prefix.
`tests/integration/test_api_surface.py` is unmodified and is exactly the net this was meant to be
caught by if it had. `DESIGN_NOTES.md`'s entries for the functions that moved moved with them, and
`CLAUDE.md` §1's helper pointers now name their new files.

### Docs -- A test tier that cannot run is not a tier that passed

`CLAUDE.md` §4 and §6 ask for `./run-tests.sh` green locally before a commit and before a merge. On
the owner's machine that is impossible and has been all along: the system interpreter is Python
3.14.4 with no `pip`, no `ensurepip`, no Docker and no root, so `unit`, `integration`, `system`,
`e2e` and the `ruff` half of `lint` all fail together with `No module named pytest`. Only
`frontend`, `tsc` and `oxlint` run. Installing the requirements there does not work either:
`pydantic==2.9.2` pins `pydantic-core==2.23.4`, whose PyO3 0.22.2 has no 3.14 ABI and no wheel.

The gap was found on 2026-10-05 while B1 was being merged, reported in that task, and written down
nowhere -- so the next person to open a task with "`./run-tests.sh all` green, summary pasted" in
its acceptance criteria would spend the time rediscovering it. Worse, the rule as written rewards
reporting a local summary nobody could have produced.

`tests/README.md` gains the symptom, the two reasons an install fails where you would not expect it
(the pydantic pin, and `venv` without `ensurepip`), and what to do instead: CI runs on every push
on every branch with the real 3.12, so quote the run id and each job's result and say plainly that
the local run was impossible. `CLAUDE.md` §4 says the same in one line and §6's merge condition now
points at it, and `DESIGN_NOTES.md` records the measurement under the requirements files -- which is
also the entry to read before raising the Python version anywhere, since the pydantic pin has to
move first.

Nothing about what CI checks changed; this only stops the local half of the gate from being
reported as passed when it never ran.

## 2026-10-04

### Added -- CI builds and starts the real `docker-compose.yml`, not just the Python modules

`docker compose up --build` is the only documented way to install this app, and until now nothing
ever ran it: every tier starts the services as bare Python processes or imports their modules
directly (`tests/README.md`, "Known gaps"). Two real failures got past that gap in one day,
2026-10-04 -- the `python-multipart` crash-loop above, and a live deploy breaking on a Dockerfile
`COPY` that the build context couldn't reach (see the Docs entry below) -- while `main` stayed
green both times.

A new CI job, `compose` (`tests/compose/smoke.sh`, also runnable by hand as
`./run-tests.sh compose`), builds all six images with the context `docker-compose.yml` itself
declares, starts the stack with no `.env` and no real credentials (every variable the compose file
reads has a safe default, and bank-sync is documented to run with nothing configured), then polls
the gateway's own aggregated `/health` until every registered module answers `ok` -- the same check
that would have caught bank-sync's crash-loop, since a container stuck `Restarting` fails the same
poll loop, with a time limit instead of hanging the job. Logs are dumped and the stack torn down
(`docker compose down --volumes`) whether the job passes or fails.

Building from a remote Git URL -- how the owner's NAS actually deploys -- isn't something CI can
do (no clone to build from). `tests/unit/test_compose_build_contexts.py` is the stand-in: it parses
`docker-compose.yml`'s build contexts, each Dockerfile's `COPY` paths and README.md's "Building
straight from GitHub" table, and fails if any of the three disagree -- exactly the drift behind the
2026-10-04 deploy failure, now caught in milliseconds instead of on the owner's machine. Confirmed
against the regression: pointing `bank-sync`'s context back at its own folder (as the broken deploy
did) fails the test with `COPY services/bank-sync/requirements.txt` does not exist under build
context `services/bank-sync`.

`tests/README.md`'s "Known gaps" entry on this is rewritten rather than removed: the frontend image
still only gets built, not health-checked (it has no `/health` to poll), and bank-sync is never
exercised with a real configured link.

### Docs -- Test counts in `tests/README.md` match what CI reports

The per-tier table and the total at the top of `tests/README.md` had drifted from the suite. Unit
is 254 with the requirements tests added the same day, and the frontend tier had already moved from
57 to 60 without the table following. The total goes from 546 to 549. Counts taken from CI run
`37227679247`.

The numbers are read by hand when a tier changes, so they are the first thing to go stale; a count
that disagrees with the suite makes the document unusable for deciding where a new test belongs.

### Fixed -- bank-sync would not start: `python-multipart` missing from its requirements

`bank-sync` crash-looped on every start, in any freshly built image. The backup export/restore
endpoints added on 2026-10-01 take `file: UploadFile = File(...)`, and FastAPI refuses to build
such a route without `python-multipart`: it raises from the `@app.post("/backup/preview")`
decorator, so the module never finishes importing and uvicorn exits with `pip install
python-multipart`. The dependency was simply never added to
`services/bank-sync/requirements.txt`. One line fixes it.

What the owner saw: the gateway's `/health` reporting `"bank": "unreachable"`, a red banner in the
app, and automatic bank transaction capture silently not running -- with the container in
`Restarting (1)` and `main` green the whole time.

Green CI is explained, and is the more interesting half. The workflow installs *every* service's
requirements into one Python environment, so `python-multipart` -- declared by `core-networth`,
`geo-allocation` and `gateway` -- was importable when the suite imported `bank-sync`. Docker does
the opposite: one environment per image, with only that image's requirements. No tier in a
536-test suite could see this.

It is also the second time, with the same package: `core-networth` and `gateway` were missing it on
2026-07-22, found by hand. So `tests/unit/test_service_requirements.py` now checks each image
against its own requirements file -- every declared third-party import (AST-parsed, because `from`
and `import` inside a docstring produce packages that don't exist), plus the rule no import check
can see: a unit with a `File()` or `Form()` parameter must declare `python-multipart`. Ten tests,
milliseconds, and the missing line fails one of them by name.

That is a stand-in, not the cure. The cure is building and starting the images in CI, which the
suite still does not do (`tests/README.md`, "Known gaps"); a Dockerfile that breaks for any other
reason is still invisible here.

### Docs -- How to build from a Git URL: which services need the repository root as context

The backup-rotation change of 2026-10-03 moved `core-networth`, `geo-allocation` and `bank-sync` to
a repository-root build context, because all three now `COPY` the top-level `shared/` package. This
repository's own `docker-compose.yml` was updated with it and CI stayed green, but a deployment that
builds from Git URLs with one context per service folder
(`...networth-suite.git#main:services/bank-sync`) broke the next day: the build stops at
`COPY shared ./shared` with `failed to compute cache key: "/services/bank-sync/app": not found`.
Inside a `services/bank-sync` context the paths `shared/` and `services/` do not exist, so the
message names a folder that is in fact present and the real cause is the context.

Nothing in the build changed -- `docker compose up --build` from a clone worked before and works
now. What was missing was the instruction: the rule lived only in `DESIGN_NOTES.md`, which is read
before editing code, not before deploying. `README.md` now has "Building straight from GitHub,
without a clone" with the context and Dockerfile of all six services in one table, the failure
message to recognise, and the note that relative bind mounts need host paths of their own when there
is no clone. `DESIGN_NOTES.md` records the incident under `shared/backup_retention.py`, including
that a change to those three Dockerfiles' `COPY` paths is a breaking change for remote-context
deployments and has to say so here.

The underlying gap stays open: the suite never builds the images and never runs the compose file
(`tests/README.md`, "Known gaps"), so a Dockerfile/context mismatch cannot be caught by CI today.

### Added -- Dividend/coupon/interest income, correctly counted as return in XIRR

Dividends, coupons and interest had no transaction type of their own: the only way to log one was
as a plain income, which XIRR (correctly, for a plain income) reads as money moved in from
outside -- a contribution. That made real investment income *lower* the solved annualized return
instead of raising it, the one figure in the app meant to answer "is this doing well", and it did
so silently, since both the inflated contribution and the deflated return look plausible on their
own.

A `CashTransaction` can now carry `investment_income_kind` (`DIVIDEND`, `COUPON` or `INTEREST`),
valid only on an INCOME row and never together with `refund_of_id`. `build_portfolio_cashflows`
(`app/xirr.py`) excludes it from the reconstructed contribution, so it reads as return instead; the
account balance, and every past day's valuation, are exactly as before -- only how XIRR accounts
for that one credit changes. A plain income transaction already logged by hand is left exactly as
it was: nothing is reclassified automatically, since there's no way to tell a deposit from a
dividend without asking, and that choice belongs to whoever logged it, not to this change.

Backend only. The frontend still has no way to pick `investment_income_kind` when logging or
editing a transaction, or to show it in the ledger/CSV export -- see the handoff note on AGE-3 for
the endpoint and response shape.

### Added -- Dividend/coupon/interest income is now settable and visible in the frontend

The backend side of this (above) had nothing to show for it: `investment_income_kind` was
reachable only by calling the API directly, so no one could actually log a dividend as a dividend
and see the correct, un-distorted XIRR. Logging an income now offers an optional "Income type"
picker (Dividend / Coupon / Interest, or "Not investment income" by default) in both the
transaction form on the Expenses -> Log tab and the edit form on an existing transaction; it never
appears on an expense or on a refund, matching the backend's own rule that the two are mutually
exclusive. The transaction list marks a row carrying one with a short "◆ Dividend/Coupon/Interest"
tag in place of its category, the same way a transfer or a refund already stand out there.

## 2026-10-03

### Docs -- Agents merge their own work onto `main`, with CI as the gate

Until now every branch waited for the owner to authorize the merge, and the owner became the
bottleneck of a workflow that is otherwise unattended. `CLAUDE.md` gains a section 6: you develop
on `agent/<name>/<slug>`, push, and merge your own branch onto `main` fast-forward once the suite
passes locally and the CI run for the exact commit you are merging is green. No human approval
step. What replaces it: CI is checked on the commit being merged, not on an earlier one, so a
rebase that moves your commits sends you back for another green run; force-pushing and rewriting
published history stay forbidden; a red `main` outranks whatever else you were doing, and the
answer to a merge that broke it is `git revert` on `main`, not a repair held back on a branch.
A separate clone of `main` at `../networth-suite-main` is where what has landed gets validated,
and an agent whose branch can't be checked out in the shared tree adds a `git worktree` instead of
switching or resetting somebody else's work.

### Added -- Backup rotation: `./backups/` no longer grows forever

core-networth, geo-allocation and bank-sync each copy their data to `./backups/<service>/<date>/`
once a day, plus a `pre-restore-<timestamp>/` safety copy before every restore -- and until now
nothing ever removed one: on a machine left running, the folder only ever grew, and a database
growing alongside it turned "disk full" into the failure mode, which also stops the backups meant
to prevent exactly that.

All three now rotate `./backups/<service>/` right after writing their newest entry (daily backup
or pre-restore copy): every entry from the last `BACKUP_RETENTION_DAYS` days (default 30) is kept
as-is, older entries are thinned to one per calendar month, and the single most recent entry is
never removed, even if the setting is 0 or negative. The rule lives once, in `shared/`, rather than
copied into each service's `backup.py` -- their Dockerfiles now build from the repo root so that
package can be copied into all three images. New variable `BACKUP_RETENTION_DAYS`, in
`.env.example`, `docker-compose.yml` and the README configuration table.

### Docs -- CLAUDE.md introduces the project and lets agents change anything, safely

For agents working on the repository without a person to ask. `CLAUDE.md` now opens with what the
app is, the principles that decide between two solutions (figures right or visibly flagged, the
past never rewritten, private data kept safe, simplicity), and where each part lives. The "stop
and ask" gates are gone: schema changes, cross-service code, compatibility code and dependency
upgrades are all allowed, each with what it must come with (a data-preserving migration that also
upgrades restored backups, updated Dockerfiles and CI, a note on what the compatibility code is
for, the whole suite plus a manual price-feed check). The end-of-task report also states anything
that couldn't be verified.

### Docs -- CLAUDE.md spells out which documents every kind of change must update

`CLAUDE.md`, which Claude Code reads at the start of every session, now holds the full working
rules: read the `DESIGN_NOTES.md` section of a file before changing it, reuse the shared helpers
(listed), delete whatever a change leaves unused, keep history out of code comments, and -- in a
table -- which document to update for which kind of change (CHANGELOG, DESIGN_NOTES, README
sections, bank-sync README, tests README, `.env.example`/`docker-compose.yml`). It ends with the
checklist to report before a task counts as done. The aim is that code and documents never drift
apart again, so no clean-up pass is needed to realign them.

### Docs -- Repository cleanup: README rewritten, bank-sync docs in one place, stale files removed

- **README rewritten** around what the app does today (budgets, merchants, recurring payments,
  XIRR, backups...), with a configuration table, a "your data" section and local-development
  commands that actually start a working stack (the gateway needs the services' local URLs).
- **bank-sync**: `FEATURE_GUIDE.md` merged into its README -- how a sync works, how categorization
  works, setup, day-to-day, configuration and endpoints in one document. Outdated statements fixed
  (transactions do get categories; captured entries can be turned into transfers; the module has
  been used against live accounts).
- **This changelog** reorganized: entries grouped by date with a type (Added, Fixed, ...), and an
  index by area at the top. Every entry's text is unchanged.
- **Removed**: the Vite template's `frontend/README.md` and `.gitignore` (the useful lines moved to
  the root `.gitignore`), and two unused icons in `frontend/public/`.
- **Fixed references**: `BACKUP_DIR` dropped from `.env.example` (Docker Compose never passed it on,
  so it did nothing there); host-specific mentions (a NAS, a specific board) generalized; a
  docstring pointing at a file that doesn't exist; the browser test visiting two routes that no
  longer exist instead of Historical Net Worth; `tests/README.md` counts and known gaps.
- **CI on Python 3.12**, the version the Docker images run (the suite passes on both).

### Docs -- Code comments say what is, `DESIGN_NOTES.md` says what was

The code's comments had become a running history -- what each line used to do, the bug that
followed, the measurements behind the fix -- often longer than the code they described. That
history now lives in `DESIGN_NOTES.md`, organized by service and file; the comments keep the
current rule and its reason. `CLAUDE.md` asks for the relevant section of the notes to be read
before changing a file, and for new history to go there rather than into comments. Comments and
docstrings only: the code with them stripped is identical before and after (checked per file, on
the Python AST and on the esbuild output for TypeScript).

### Removed -- Dead tools, one-off migrations, FastAPI lifespan, shared frontend helpers

- **Removed `core-networth/app/debug_xirr.py`** -- this time for real (the entry further down said
  so, but the file stayed). Never imported, untested, and it re-implemented the XIRR windowing the
  app already does; the cashflows it printed are easier to inspect from a test.
- **geo-allocation's parser library is the service's own now**: its stand-alone CLI
  (`cli.py`, `__main__.py`) and `parse_file` are gone, so the spreadsheet readers take the
  uploaded bytes only (no file-path branch, no temporary file for SpreadsheetML), and
  `aggregate` always takes the fund weights it was always given.
- **One-off migrations removed**: the `assets.instrument_type -> category` rename and the
  `idempotency_keys.status_code` drop only mattered to databases from before those changes, and
  so did bank-sync's backfill of counterparties from the audit CSV. The generic
  add-missing-columns migration stays, so a backup taken from now on still restores into any
  later version. A database (or backup) older than those changes is no longer upgraded.
- **FastAPI `lifespan`** instead of the deprecated `@app.on_event("startup")` in core-networth,
  geo-allocation and bank-sync -- same startup work (scheduler, links.yaml reconciliation).
- **Frontend**: the form-field label style is one `.field-label` class instead of the same six
  utilities written 40 times (computed styles checked identical in Chromium), and every caught
  error is shown through one `errorText()` instead of 28 hand-written variants.

### Refactored -- Second accidental-complexity pass (no behavior change)

Duplication and dead branches removed across every service and the frontend: about 250 fewer
lines of code, plus two unused devDependencies.
The whole suite (unit, integration, system, browser, frontend, linters) passes unchanged, and the
two rewritten areas without direct tests were compared before/after: the Allocation page's
Category and Currency tabs render the same text and colours in Chromium, and bank-sync records
the same rows for cancelled, zero, unreadable and direction-less transactions.

- **One FX helper**, `price_client.fx_rate_at`: "that day's rate for a past day, today's live rate
  otherwise, 1.0 when none" was written out eight times (transfers, convert-to-transfer, combined
  history, both intraday charts, three XIRR paths). `valuation._resolve_fx` stays separate: it also
  reports when a rate was missing.
- **XIRR**: `compute_portfolio_xirr` and `compute_combined_xirr` share `_xirr_by_window` instead of
  each repeating the year/since-inception loop.
- **core-networth endpoints**: `_get_or_404` replaces ~40 copies of fetch-then-404 (and the
  one-off `_budget_or_404`); the idempotency key is staged inside `_commit_with_idempotency` (the
  separate `_reserve_idempotency` was always called on the line before it); the per-account
  transaction list reuses `_transactions_query`; taking a net worth snapshot updates or creates
  through one code path.
- **core-networth scheduler**: month-end arithmetic uses `reports.month_start`/`month_end` instead
  of a private copy, and the daily backup reads `backup.DB_PATH`.
- **bank-sync**: the four identical "skip this transaction" branches are one; the amount is parsed
  by one `_parse_amount` shared with the pending-settlement path; the links.yaml reconciliation
  no longer special-cases an empty file (SQLAlchemy handles an empty `NOT IN`).
- **gateway / geo-allocation / price-feed**: one zip opener in the gateway's backup helpers; a
  coverage branch that could never be false removed; `fast_info` field access and date-parameter
  parsing each written once.
- **Frontend**: the Category and Currency tabs of Allocation share `SnapshotBreakdown` (they were
  ~150 duplicated lines); both downloads (backup, transactions CSV) go through one `downloadFile`;
  `listTransactions` reuses `filterParams`; `autoprefixer` and `postcss` dropped from
  devDependencies (Tailwind 4 runs through its Vite plugin; the built CSS is byte-identical).

## 2026-10-02

### Added -- Budgets, recurring payments, monthly savings, search, CSV export, balance check

All of it counts money the way `/expenses/summary` always has -- transfers between your own
accounts left out, refunds netted against what they refund, each amount converted at its own
day's rate -- now through one shared `reports.flows` instead of a copy per report.

- **Income by category.** `/expenses/summary` adds `income_by_category`; History shows it under
  the spending breakdown.
- **Month by month** (`GET /expenses/monthly?months=12`): income, spending, what was left and the
  savings rate (share of income not spent; null for a month without income) per calendar month,
  empty months included. History shows it as a bar chart (income/spending, colours validated for
  colour-blind separation in both themes) and a table.
- **Budgets** (`/budgets` CRUD, `GET /budgets/progress?month=YYYY-MM`): one monthly limit per
  category, across all portfolios, in its own currency. Progress is OK / NEAR (from 90%) / OVER,
  with `elapsed_pct` so a bar shows whether spending runs ahead of the month. New **Budgets** tab
  (month navigation, edit, remove); a banner at the top of Expenses names this month's budgets
  that are nearly or fully used. Deleting a category deletes its budget.
- **Recurring payments** (`GET /recurring`): subscriptions found in the last ~13 months of
  spending -- grouped by counterparty (or by note when logged by hand), a weekly / monthly /
  quarterly / yearly rhythm, amounts within ±25% of the typical one -- with monthly cost, next
  expected date, whether it's still active, and price changes. New **Recurring** tab with the
  monthly total and a callout for subscriptions that got more expensive.
- **Search and filters** on both transaction lists (`q` in the note or counterparty, literal and
  case-insensitive; `category_id`, `from_date`/`to_date`, `min_amount`/`max_amount`,
  `direction`), with a search box and a filter panel in the Log.
- **CSV export** (`GET /transactions/export.csv`, same filters): signed amounts in each account's
  own currency, category, counterparty, note, transfer/refund links; a UTF-8 BOM so Excel reads
  accents. **Export CSV** in the Log (what's filtered) and in History (the selected range).
- **Balance check** (bank-sync): after every clean sync, the bank's balance for the account
  (available balance preferred) is stored next to Net Worth Suite's and reported by `/status`;
  the app warns when they differ by a cent or more. Informational only.

## 2026-10-01

### Added -- Fix transactions after the fact, transfers from one-sided entries, bank-sync in backups and alerts

**Editing transactions (Expenses -> Log).** The API could always edit a transaction, but the app
offered only create and delete -- so a bank-synced expense with the wrong (or no) category could
only be fixed by deleting it, and bank-sync never re-imports one it has already captured.
- Every row (except transfer legs, which are edited as a pair) has **Edit**: date, amount
  (quantity on a voucher account), category, note. Only changed fields are sent.
- **All / Uncategorized** filter on the list: `uncategorized=true` on
  `GET /cash-accounts/{id}/transactions` and `GET /transactions` (no category, not a transfer leg,
  not a refund).
- Checkboxes + **Apply to selected**: `POST /cash-transactions/bulk-categorize`, all or nothing
  (an unknown id or a transfer leg refuses the whole request).

**Turning a one-sided entry into a transfer.** With only one account linked, a top-up from
another of your own accounts arrives as income; logging the other side as a fresh transfer
counted the linked side twice, and logging it as an expense counted it as spending.
- `POST /cash-transactions/{id}/convert-to-transfer {other_account_id}` creates only the missing
  leg (an EXPENSE on the source for an INCOME, and vice versa), on the same date, converted into
  the other account's currency at that day's rate, and links both by `transfer_id` -- out of the
  income/expense statistics, like any transfer. Refused for transfer legs, refunds, expenses with
  refunds, voucher/pension/removed accounts.
- **⇄ Transfer** action on each row of the Log.

**bank-sync's data in backups.** Its database is the ledger that stops a sync from re-creating
transactions it already captured; it was in no backup.
- bank-sync: `GET /backup/export|stats`, `POST /backup/preview|restore` (validated, safety copy of
  the current data first, schema migrated, `links.yaml` re-applied, sync lock held throughout), and
  a daily copy into `BACKUP_DIR` (`./backups/bank/` in `docker-compose.yml`).
- gateway: the combined backup carries `bank/bank-sync.zip` when bank-sync is registered, and
  restores it last; a backup without it (older, or from an instance without bank-sync) restores
  everything else and leaves bank-sync as it is. Settings shows it in the restore preview.

**Bank sync alerts.** A consent lasts 90 days and syncing silently stops when it runs out.
- bank-sync: `GET /status` (links, consent expiry, last sync, last error, re-authorize URLs).
- gateway: bank-sync registered as module `bank` when `BANK_SYNC_URL` is set (it is, in
  `docker-compose.yml`) -- an instance without bank-sync neither shows it as unreachable nor
  tries to back it up.
- Summary and Expenses show a banner when a consent expires within 7 days or has expired, a link
  failed or was never authorized, no sync has succeeded for max(24h, 3 sync intervals), or the
  last sync reported a problem -- each with a link to re-authorize or to bank-sync's page.

### Added -- Categorize by merchant -- Expenses -> Merchants

Revolut, through Enable Banking, never sends a merchant category code (checked on a live account:
empty on every card payment, pending and booked alike), so `mcc_categories.yaml` can't categorize
anything from it. The merchant's name, though, always arrives -- so that's what this categorizes by.

- **core-networth:** `CashTransaction` gains `counterparty` (who the money went to / came from, as
  the bank named them) and `counterparty_key` (the same, case- and whitespace-normalized). New
  `MerchantRule` table: an EXACT rule for one counterparty, or a CONTAINS rule for every
  counterparty containing a piece of text (every store of a chain), mapped to a category or marked
  ignored. EXACT wins, then the longest CONTAINS.
  - A transaction created with a counterparty and no category gets its rule's category.
  - Saving a rule also categorizes that merchant's earlier *uncategorized* transactions (on by
    default, `apply_to_past`); one categorized by hand is never touched. Changing a rule's
    category can optionally move the transactions still in the old one (`recategorize_previous`).
  - New endpoints: `GET /merchants` (every counterparty seen, with counts, totals and status),
    `GET/POST /merchant-rules`, `PATCH/DELETE /merchant-rules/{id}`. `PATCH /cash-transactions/{id}`
    accepts `counterparty`. Deleting a category deletes its rules, putting their merchants back
    to map.
- **bank-sync:** sends the counterparty with every transaction -- the creditor on money going out,
  the debtor on money coming in -- and remembers the category core gave it. Transactions captured
  before this get their counterparty filled in once from `transactions_log.csv`.
- **frontend:** new **Merchants** tab under Expenses: the merchants to map / mapped / ignored, a
  category picker per merchant, and the "contains" rules. The Log tab shows a transaction's
  counterparty under its note when the two differ.

## 2026-09-28

### Fixed -- Bank-sync follows pending card payments until booked

Found on a live Revolut account: card payments arrive through Enable Banking first as pending
(`status: PDNG`) with `merchant_category_code` empty, under the same `entry_reference` they keep
once booked. The service captured them on first sight and never looked again, so the MCC-based
categorization could never apply to them, a final amount different from the pending one was lost,
and a hold released instead of booked stayed an expense forever.

- **Pending payments are now tracked until booked.** `SyncedTransaction` gains `state`
  (`FINAL`/`PENDING`/`VOIDED`), `category_id` and `missing_count`; the fetch window reaches back to
  the oldest payment still pending. On booking, the amount and category are updated in
  core-networth -- each only while core still holds the value bank-sync itself put there, so
  anything changed by hand is kept. A payment the bank reports as `CNCL`/`RJCT`, or that is absent
  from two consecutive complete fetches, is removed; one pending longer than `PENDING_TRACK_DAYS`
  (new setting, default 30) is kept as is. A transaction without a `status` is treated as booked,
  as before. The booked version gets its own row in the audit CSV.
- **core-networth: new `GET /cash-transactions/{id}`**, which bank-sync uses to read a transaction
  back before correcting it.
- **bank-sync now migrates its own database** (`app/migrate.py`, same approach as
  core-networth's): `create_all()` never adds columns to an existing table. Existing rows become
  `FINAL`.
- `mcc_categories.yaml` present as a *directory* -- what Docker leaves when a single-file mount's
  source didn't exist at container start -- is now logged instead of silently ignored.
- Transactions captured before this change aren't re-read: those already in Net Worth Suite keep
  whatever category they have.

## 2026-09-17

### Added -- Positions can be tagged Emergency Fund, and added directly from that section

Requested: an ETF-like position (e.g. a money-market fund such as XEON) should be trackable as
part of the Emergency Fund, not just plain cash balances -- and the Emergency Fund section itself
should let you add such a position, not only a cash balance.

- **`Asset.category` (the "Tag" already shared between Positions and cash-like balances) now
  offers `EMERGENCY_FUND`** as a selectable option, both in the Asset Catalogue's edit form and in
  the "+ New asset" inline form under Positions. Nothing changed on the backend: `Asset.category`
  was already an unrestricted `AllocationCategory` column and the Allocation "Breakdown" view
  already aggregated positions and cash balances by the same tag -- the only gap was the frontend
  never offering this specific value in those two dropdowns.
- **The Emergency Fund section's own "+ Add" button now offers a `Cash balance` / `Position`
  toggle.** Choosing "Position" reuses the exact same add-position flow as the Positions section
  (existing asset, or create a new one with quantity and either a live ticker or a manual price),
  with the new asset's tag preselected to Emergency Fund -- purely a convenience default, never
  forced: it's an ordinary editable dropdown, so any other tag (or none) can be chosen instead, and
  picking an *existing* asset never touches its tag (an asset is shared across portfolios, so
  silently retagging it from inside one portfolio's Emergency Fund form would retag it everywhere
  else it's held -- deliberately not done).
- Positions tagged Emergency Fund now also render in a small table directly under the Emergency
  Fund section's cash balances (Asset/Ticker/Quantity/Price/Value, with its own Remove), without
  introducing a new top-level page section -- the Positions section above still lists every
  holding regardless of tag; this is a filtered, additional view on the same data, not a second
  place that data lives.
- Verified end-to-end against a running backend instance: creating an asset tagged
  `EMERGENCY_FUND`, adding a holding of it, and adding an ordinary Emergency Fund cash balance in
  parallel both correctly contribute to the portfolio's `net_worth_base_ccy`. Frontend `tsc
  --noEmit` and `vite build` both clean.

## 2026-09-14

### Added -- Bank-sync logs every transaction to a single raw audit CSV

Requested: every transaction JSON that passes through Open Banking should also be recorded in one
general CSV, common to every linked institution, with all the JSON's fields populated as columns
plus one extra column naming which bank/institution it came from.

- **New `app/csv_log.py`**: appends one row per transaction to `data/transactions_log.csv`.
  Deliberately not tied to what `sync.py` decides to do with a transaction (create it in
  core-networth, skip it as zero-amount, etc.) -- it's called right after the existing dedup check
  passes, so it's a raw, complete record of every unique transaction a linked bank ever sent, not a
  mirror of the app's own filtering.
- **Columns aren't fixed up front**: each transaction's JSON is flattened (nested objects become
  dotted column names, e.g. `transaction_amount.amount`; lists like `remittance_information`
  join into one pipe-separated string) and the header widens automatically the first time a new
  field is seen, padding every earlier row with a blank for it -- rather than hand-picking a
  column list that risks silently dropping whatever a given bank happens to send that others
  don't. `institution` (the link's label) and `logged_at` are always the first two columns.
- New `GET /transactions-log.csv` endpoint and a link on the status page to download it directly.
- Verified end-to-end: two different mocked banks sending differently-shaped transactions (one
  with an extra field the other never sent) correctly widen the CSV header without losing the
  earlier bank's already-written row; re-syncing the same transaction on a second cycle does not
  produce a duplicate CSV row, matching the same dedup lifecycle as the rest of the sync.

### Changed -- Generalized every host-specific reference so the project runs identically on a NAS or a plain PC

Requested: make sure nothing committed to the repo assumes a specific piece of hardware, since
this should run equally well on a NAS or a regular PC.

- Found and generalized three "NAS"-specific mentions (`services/bank-sync/README.md`,
  `FEATURE_GUIDE.md`, a `docker-compose.yml` comment) to "your host machine," and a leftover
  reference to a specific mini-PC model ("UDOO x86 II") in two `docker-compose.yml` comments --
  neither was ever functionally NAS/UDOO-specific, just worded that way.
- **`ALLOWED_ORIGINS` and `VITE_GATEWAY_URL`** (previously hardcoded in `docker-compose.yml`,
  requiring a direct edit to deploy on a real network) now read from `${VAR:-default}`, matching
  the pattern `bank-sync`'s env vars already used -- both configurable via a `.env` file without
  touching `docker-compose.yml` at all.
- **New `.env.example`** at the repo root documenting every configurable variable across the whole
  project (frontend/gateway networking + bank-sync), with `.env` itself gitignored so real LAN
  IPs/addresses never end up committed.
- `README.md`'s self-hosting section updated to show the `.env` approach as the primary path,
  keeping direct `docker-compose.yml` edits documented as still working for anyone who prefers that.
- Confirmed via `docker compose config`-equivalent validation (`yaml.safe_load` + service list
  check) that the file is still syntactically valid after the substitution changes.
- No NAS-specific paths or files exist anywhere in the committed repo to begin with -- everything
  in `docker-compose.yml` uses relative paths, and the genuinely NAS-specific deployment details
  (TrueNAS storage pool paths, the Tailscale-app `serve.json` config) only ever lived in the
  user's personal, separately-delivered, never-committed setup guide.

### Docs -- Everything in English, README rewritten to match the current feature set

- Translated the three Italian-language documents to English:
  `services/bank-sync/GUIDA_FEATURE.md` -> `services/bank-sync/FEATURE_GUIDE.md`,
  `ALLINEAMENTO_GITHUB.md` -> `GITHUB_ALIGNMENT.md`, and the section headers in
  `services/bank-sync/mcc_categories.md`. Verified the whole repo (code + docs) is now free of
  Italian text.
- **`README.md` rewritten** to actually reflect the current project, not just the original feature
  set: Features now lists expense tracking (transactions/categories/transfers/refunds), the
  archive-not-delete behavior for cash accounts, automatic expense capture via `bank-sync`,
  customizable palettes, and the mobile layout. Architecture diagram gained `bank-sync` as an
  optional fourth service. Added a dedicated "Automatic expense capture" section pointing to
  `services/bank-sync/README.md` and the new `FEATURE_GUIDE.md`. Data model section now covers
  `CashTransaction` (including `transfer_id`/`refund_of_id`) and cash account archiving. Project
  structure and the "keeping data out of git" section both updated for `bank-sync`'s own files.

### Audit -- Full codebase sweep for bugs and dead code

Systematic pass across every service (`pyflakes` for unused imports/variables/names, manual review
of the highest-risk recently-touched logic: refunds, transfers, archiving, XIRR, bank-sync's sync
cycle) plus a full frontend lint (`oxlint`) and a final regression run of every scenario tested
throughout this project.

- **Found**: dead code in `geo-allocation` (never touched this session) -- an unused `Tuple`
  import, an unused `SPECIAL_OTHER` import, two unused local variables (`col_name`/`col_isin`) in
  the Amundi holdings parser, and an XML tree parsed and immediately discarded in the SpreadsheetML
  reader. All removed; none were bugs (nothing downstream ever read them), confirmed with a
  functional smoke test of the Amundi parser after the change.
- **Not found**: no further logic bugs in the refund/transfer/archiving/XIRR/bank-sync code --
  deliberately re-checked several specific scenarios by hand (refund chronological ordering,
  deleting a transfer/refund leg, an archived account combined with a refund, whether XIRR treating
  a lent-and-never-returned amount as a real capital outflow is correct -- it is, since that money
  genuinely isn't available to the investor anymore) without finding anything new.
- Full regression (cash + transactions, vouchers, Pension Fund transaction rejection, archiving,
  transfers, partial + over-refunds, snapshot/history/growth/xirr) and a full frontend
  typecheck+build re-run clean after the geo-allocation cleanup, confirming no regressions.

### Added -- Bank-sync auto-categorizes via merchant_category_code, full note text, plus a real bug fix

Two requested changes, found and fixed a genuine pre-existing bug while testing them end-to-end.

- **Full note text**: `remittance_information` can be multiple lines (e.g. a bank splitting "Card
  payment 11.04.2026" and the merchant name into two entries) -- `_extract_note` previously kept
  only the first line; now joins every line with " — " so nothing is silently dropped from what
  lands in the Note field.
- **New `mcc_categories.yaml`** (see `mcc_categories.example.yaml`, gitignored like `links.yaml`):
  maps a bank's `merchant_category_code` (a standardized ISO 18245 code, e.g. "5411" = grocery
  stores, the same code regardless of bank or country) to one of your existing Expense Category
  *names*. `app/mcc_categories.py` resolves that name to a real `category_id` by querying
  `/expense-categories` fresh on every sync cycle (so renaming/deleting a category is picked up
  immediately, no restart needed) -- a code with no mapping, or mapped to a category name that
  doesn't exist, simply leaves the transaction uncategorized exactly like before this feature,
  logging a warning rather than failing the sync.
- New `GET /helper/categories` endpoint lists your existing category names verbatim, to copy into
  `mcc_categories.yaml` without guessing spelling/casing.
- **Found and fixed while testing the above end-to-end** (the first time this project ran a full
  `sync_all()` cycle through the real database rather than testing helper functions in isolation):
  `SyncedTransaction.entry_date` is a SQL `Date` column, but `sync.py` was storing the raw string
  Enable Banking sends (e.g. `"2026-09-01"`) instead of converting it to a Python `date` object --
  SQLite rejected this outright, meaning **every sync would have crashed** the moment it tried to
  record a captured transaction, in the previously-delivered code. Fixed by parsing the string with
  `date.fromisoformat()` before storing it.
- Verified with a full mocked end-to-end run (fake Enable Banking response using the official
  documented format, fake core-networth calls): correct EXPENSE/INCOME split, joined note text, MCC
  5411 correctly resolving to a real category id while an uncoded transaction stays uncategorized,
  and a second run confirming dedupe still works -- this is the first time this project actually
  exercised `sync_all()` end-to-end through the database rather than testing its pieces separately,
  which is exactly how the date bug above surfaced.

### Fixed -- Bank-sync now reads the real Enable Banking transaction format correctly

Found while showing the user a real example of Enable Banking's transaction JSON (pulled from their
own published API documentation, not guessed): their official example shows a DBIT (expense)
transaction with an **unsigned** amount (`"49.90"`, no minus sign) -- `credit_debit_indicator`
(`CRDT`/`DBIT`) is the field actually meant to carry the sign, not the amount itself. The original
`sync.py` assumed the amount's own sign determined income vs. expense, which would have
misclassified every expense as income for any bank that behaves like this official example.

- `sync.py` now determines direction from `credit_debit_indicator` first, only falling back to the
  amount's sign if that field is ever missing -- verified against the exact official example
  (unsigned DBIT amount) plus a defensive fallback case.
- **Added pagination support**: the official docs also show a `continuation_key` field for
  fetching additional pages of transactions, which the original code never read -- a bank with more
  transactions than fit in one response would have silently lost everything past the first page.
  `sync_link` now loops through every page before processing.
- No other behavior changed: still uncategorized, still deduped the same way, still pushes through
  the same core-networth endpoint.

### Added -- `bank-sync` service -- automatic expense capture via Open Banking

New optional service, `services/bank-sync/`, that watches your bank accounts through
[Enable Banking](https://enablebanking.com)'s Open Banking (PSD2) API and automatically creates
expense/income transactions in Net Worth Suite -- no more logging every card payment by hand.
Committed to the repo ready to configure after cloning, not tied to any specific bank/account (see
`links.example.yaml`).

- **`links.yaml`** (gitignored -- you create your own from `links.example.yaml`) declares which
  accounts to watch: a label, the bank ("ASPSP") name/country, and which Net Worth Suite
  portfolio/cash account each one feeds. Re-read on every container restart; editing it updates the
  account mapping for an already-authorized link **without** resetting its authorization -- verified
  this explicitly, since a naive reload could otherwise silently un-link a working connection every
  time the file changes.
- **Authorization flow**: a small server-rendered status page (`http://<host>:8003/`) lists every
  configured link with its status (PENDING/AUTHORIZING/ACTIVE/EXPIRED/ERROR) and an
  Authorize/Re-authorize button that starts the real bank login flow (redirects to the bank's own
  page, never touches your credentials). A `/callback` endpoint completes it and flips the link to
  ACTIVE, running an immediate first sync so you see results right away instead of waiting for the
  schedule.
- **Sync loop**: every `SYNC_INTERVAL_HOURS` (default 6), re-fetches each ACTIVE link's
  transactions and creates any not seen before as a plain expense/income (sign of the amount decides
  which) via the same `POST /cash-accounts/{id}/transactions` endpoint the Transactions page uses --
  **always uncategorized**, per the earlier design decision that auto-capture shouldn't guess
  categories. A dedupe table (`SyncedTransaction`) prevents re-creating the same transaction on every
  poll, since Enable Banking returns a date range, not "what's new."
- **Consent expiry**: PSD2 caps how long a bank's consent lasts (commonly 90 days); the status page
  shows "valid until" per link and flips to EXPIRED when it passes, with a one-click re-authorize
  (same quick bank login, no data lost).
- New Docker service in the root `docker-compose.yml`, same pattern as every other service here
  (local build context, its own data volume, `expose`/`ports` as needed) -- safe to leave running
  unconfigured, since an empty/missing `links.yaml` just means it has nothing to do.
- **Honesty note carried into the code and README**: `app/enable_banking.py` is written against
  Enable Banking's published API docs, not tested against a real bank connection (not something
  reproducible in a generic dev sandbox) -- the auth-code-exchange flow and endpoints are correct in
  shape, but exact request/response field names are the part most likely to need a small adjustment
  once tried against a real account; the README says so explicitly rather than overstating certainty.
- Verified everything that *is* testable without live bank credentials end-to-end: config loading
  (including the Docker "bind-mounting a missing file creates a directory" gotcha, made non-fatal),
  link creation from `links.yaml`, the status page, graceful (non-crashing) failure when credentials
  are missing or a link/callback references an unknown label, and that editing `links.yaml` updates
  an authorized link's account mapping without resetting its status.

## 2026-09-09

### Added -- Decimal input accepts "," as well as "." -- and a Refund transaction type

Two requested fixes, the first quick, the second with a real architectural subtlety worth
explaining.

**Decimal separator ("," or ".")** -- every numeric input a person types by hand (amounts,
quantities, unit values, manual balances) only understood a period; typing "10,5" silently became
10 (plain `parseFloat` truncates at the first non-numeric character instead of rejecting it), which
is worse than an error since nothing looked wrong at entry time. Fixed with a new
`parseLocaleFloat` helper (`lib/format.ts`) used everywhere `parseFloat` was previously called on
a user-typed string (9 call sites across `PortfolioDetail.tsx` and `Transactions.tsx`): "10,5" and
"10.5" both parse to 10.5, and if both separators appear (e.g. "1.234,56" or "1,234.56") whichever
comes last is treated as the decimal point. Verified against 9 cases including both conventions'
thousands grouping and edge cases like a lone leading comma.

**Refund transaction type** -- lending money (logged as an expense) and getting some or all of it
back later previously had to be logged as a plain, unrelated income, which numerically balanced out
fine but broke category/monthly spending analysis: the original expense kept showing its full
amount forever, even after being paid back.

The tempting fix -- editing the original expense's stored amount down -- was deliberately rejected:
it would retroactively change historical account balances (the same mistake already fixed once for
archived accounts), since a balance computed for a date between the original expense and the refund
would wrongly show the money as already back. Instead:

- **New `CashTransaction.refund_of_id`**, set on a refund (an ordinary INCOME row, dated whenever
  the money actually arrived -- balances are completely unaffected by this feature, exactly as
  correct) pointing at the EXPENSE it offsets. Enforced: only an INCOME can be a refund; it must
  target a real EXPENSE, not a transfer leg or another refund.
- **New `compute_refund_adjustments()`**, computed fresh on every `/expenses/summary` call: nets
  every refund against its expense in chronological order (so several partial refunds against the
  same expense apply correctly), floored at 0. A refund that exceeds what was left owed counts its
  leftover portion as genuine income instead. Verified against the exact three cases requested:
  lend 10, refund 5 -> counts as 5; refund a further 5 (10 total) -> counts as 0, disappears from
  the category breakdown entirely; lend 10, refund 15 -> counts as 0 expense plus 5 income.
- Deleting a refunded expense un-links its refunds (they become full, ordinary income) rather than
  silently losing that money from the statistics; deleting a refund simply restores its expense to
  full value on the next computation, since nothing is cached -- everything here is computed live
  from the current transaction table.
- **Frontend** (`pages/Transactions.tsx`): the Expense/Income/Transfer toggle gained a fourth
  option, Refund -- picking it shows a picker of past expenses (with how much of each is still
  outstanding) instead of a category, and a live hint under the amount field explaining what the
  entry will do ("clears the €5 left; the extra €2 counts as income"). The recent-transactions list
  and Expense History's movements table both label a refund distinctly ("↩ Refund").
- Verified end-to-end: all three requested scenarios, balances staying correct throughout, refund
  validation rejecting wrong directions/targets, the deletion edge cases above, and a full
  regression sweep of every other cash/voucher/archiving/transfer/XIRR scenario tested so far in
  this project -- all still pass.

## 2026-08-30

### Added -- Transfers between cash accounts, excluded from expense statistics

Reported: moving money between your own accounts (e.g. topping up the Emergency Fund from Cash) had
no proper representation -- the only way was logging an expense on one account and an income on the
other, which correctly moved both balances but polluted the Expenses statistics: that money looked
like real spending and real income, breaking monthly category breakdowns and totals for something
that was never actually spent or earned.

- **New `POST /transfers`**: takes a source account, a destination account, an amount, a date, and
  an optional note; creates a linked pair of ordinary `CashTransaction` rows (an EXPENSE on the
  source, an INCOME on the destination, sharing a new `transfer_id` column) so both accounts'
  balances update exactly like any other transaction. Rejects: transferring to the same account,
  either account being archived, Pension Fund (stays hand-updated only, same rule as transactions),
  or a Voucher-kind account. Cross-currency transfers convert the arriving amount using that day's
  historical (or live, if today) FX rate, the same historical/live split used everywhere else in
  the app.
- **`/expenses/summary` now excludes any row with a `transfer_id`** -- moving your own money between
  your own buckets no longer counts as income or expense in totals or category breakdowns, while a
  real expense/income logged the same day is still counted correctly.
- **Deleting one leg deletes both** -- leaving one side of a transfer behind would look like a real,
  one-sided expense or income that never happened. Editing a transfer leg via `PATCH` is rejected
  outright (delete and re-create instead), to avoid the two legs quietly drifting out of sync.
- No XIRR changes were needed: a same-date transfer between two accounts in the same portfolio
  produces two cashflow entries (one from each account) that cancel each other out in the money-
  weighted return calculation, exactly as they should.
- **Frontend** (`pages/Transactions.tsx`): the Expense/Income toggle gained a third option,
  Transfer -- picking it swaps the single "Account" field for "From account"/"To account" (drawn
  from the same portfolio, Voucher accounts excluded) and hides the Category field, which doesn't
  apply. The recent-transactions list and Expense History's movements table (`pages/
  ExpenseHistory.tsx`) both show a transfer with a neutral "⇄ Transfer" label and color instead of
  the usual green/red, so it reads clearly as neither a gain nor a loss.
- Verified end-to-end: balance correctly moves between both accounts, the transfer is invisible to
  `/expenses/summary` while a real same-day expense still counts, deleting either leg removes both,
  editing a leg is rejected, transfers to Pension Fund/Voucher/same-account are all rejected, a
  cross-currency transfer executes without error, and a full regression sweep of every other cash/
  voucher/archiving/XIRR scenario tested so far in this project still passes unchanged.

## 2026-08-27

### Added -- Pension Fund accounts count as an investment in XIRR, not a cash contribution

Requested: a Pension Fund's balance changes mainly because the fund itself performed well or
badly, not because money was freely deposited or withdrawn -- treating every balance bump as an
external "contribution" (as any other cash account) understates its true return and dilutes the
portfolio's overall XIRR.

- `xirr.py`'s cashflow reconstruction now skips Pension Fund accounts entirely when generating
  interim contribution/withdrawal events -- mirroring how a stock holding's price appreciation is
  never itself a cashflow. Its value is still fully included in the start/end snapshot totals (as
  before), so the difference between those is what correctly reads as its return.
- Verified: a Pension Fund that grew from €10,000 to €10,500 over a year with no transactions now
  correctly shows a ~4.7-5% XIRR contribution, instead of that €500 counting as "money added" and
  diluting the rate toward zero. A real deposit into an ordinary (non-Pension-Fund) cash account
  still correctly counts as a contribution, not a return -- unchanged. Full regression sweep of
  every other cash/voucher/archiving scenario re-confirmed unaffected.

### Audit -- The XIRR issue was residual data damage, not a remaining bug -- plus a new "backdate a balance" capability

Traced the still-wrong XIRR (reported after the archiving fix) directly against the live database
via a diagnostic dump: every cash account except one had exactly one balance entry, dated the day
they were re-created -- confirming the original hard-delete (from *before* the archiving fix
existed) had already permanently erased that history. The archiving fix itself is working
correctly; it just can't repair damage that happened before it shipped, since the old rows are
genuinely gone.

- **No further backend change was needed** for the XIRR number itself -- the fix from the previous
  entry is correct and already deployed; the remaining bad number is a data problem, not a code one.
- **Found and fixed a real gap while diagnosing this**: the "Update" balance flow
  (`pages/PortfolioDetail.tsx`) always wrote today's date, with no way to enter a **backdated**
  balance from the UI at all -- meaning there was no way to actually fix a situation like this one
  without direct database/API access. Added a date field (defaulting to today, capped at today)
  next to the amount when editing a balance, so a corrective backdated entry -- like "this account
  actually held €X back on this earlier date" -- can be entered directly from the app.

## 2026-08-26

### Fixed -- XIRR (annualized return) could show a large, wrong negative number

Reported: the portfolio's dollar-value change was positive (+€6,072, +25.1%) while its Annualized
Return (XIRR) showed -37.9% -- an impossible combination for a portfolio that hasn't had a real
loss.

Two distinct bugs in `xirr.py`'s cashflow reconstruction, found together:

- **Caused by yesterday's archiving fix**: `build_portfolio_cashflows` queried every `CashAccount`
  for a portfolio regardless of `archived_at`, and read its raw balance-entry history unconditionally.
  Archiving preserves that history on purpose (see yesterday's fix) -- but this function had no
  concept of "this account stopped counting on this date," so an old, archived account's opening
  balance and a newly-recreated replacement account's opening balance were both counted as separate,
  unrelated contributions, even though it's the same money. This inflated the apparent amount
  "invested" far beyond the portfolio's actual current value, producing a large fake loss.
- **Pre-existing, independent of archiving**: the same function only ever read `CashBalanceEntry`
  (manual balance edits), never `CashTransaction` (the Expenses feature's income/expense ledger). Any
  money movement logged as a transaction instead of a manual balance edit was invisible to the
  interim cashflow reconstruction, while the final "today's value" (from `compute_portfolio_snapshot`,
  which correctly includes transactions) was not -- a mismatch that further distorts the rate for
  anyone using Transactions instead of manually editing balances.

Fixed by rebuilding each account's cashflow contribution from `resolve_cash_balance` -- the same
function that already powers every other balance display in the app -- instead of a second,
separately-maintained "how a balance changes" implementation:

- Every date a `CashBalanceEntry` **or** a `CashTransaction` exists for an account is now a real
  event; the balance at each is computed via `resolve_cash_balance`, so transactions are no longer
  invisible to XIRR.
- An archived account's value is treated as dropping to exactly 0 from its archive date onward
  (matching `compute_portfolio_snapshot`'s own exclusion rule), which surfaces as a genuine
  withdrawal cashflow at the close date -- so archiving an account and re-adding a fresh one with
  the same money now nets out to roughly zero distortion, instead of counting as two separate
  contributions.
- Verified against the exact reported shape of the bug (archive an account, recreate it with the
  same balance -- XIRR now comes back at ~0%, not a large fake loss) and against an income
  transaction correctly counting as a real contribution, plus a full regression sweep of every
  cash/voucher/archiving scenario tested so far in this project and a `snapshot`/`history`/`growth`/
  `xirr` sweep -- all still pass.

### Fixed -- Removing a cash account retroactively rewrote past net worth history

Reported scenario: deleting the entire Cash section of a portfolio (to restructure it) and
re-adding it produced a portfolio chart showing a fake +16.7% gain overnight, when the real change
was roughly -0.8%.

Cause: `DELETE /cash-accounts/{id}` hard-deleted the account, cascading to its full balance and
transaction history. The per-portfolio history chart (`/portfolios/{id}/history`, unlike the
separate frozen "Historical Net Worth" snapshots) recomputes every past date live from whatever
accounts currently exist -- so deleting an account erased its contribution from every historical
date shown, not just today. Re-creating the account with a fresh opening balance dated "today" then
made that balance look like it appeared out of nowhere overnight.

- **`CashAccount` gained `archived_at`** (nullable, null = active). `DELETE /cash-accounts/{id}` now
  sets this instead of deleting the row -- the account disappears from `GET
  /portfolios/{id}/cash-accounts` and from every current/future valuation immediately, but its
  existing balance and transaction rows are untouched, so any `as_of` date strictly before the
  archive date still values correctly using them.
- `compute_portfolio_snapshot` (`valuation.py`) now includes an archived account only for dates
  strictly before its `archived_at` day -- excluded from that day onward, today included, so
  removing an account takes effect right away without silently rewriting the past.
- Archived accounts reject new balances/transactions with a 400 (defence in depth; they're also no
  longer selectable anywhere in the UI once archived).
- The "Remove" confirmation in `PortfolioDetail.tsx`'s Cash table now says plainly that history is
  kept, instead of implying an unqualified delete.
- Verified against the exact reported scenario end-to-end: a cash account's history stays correct
  for a past date after being "removed," today's total correctly drops to zero immediately, and
  re-creating a replacement account doesn't distort the archived one's old history -- plus a full
  regression sweep confirming ordinary (never-archived) accounts and `snapshot`/`history`/`growth`/
  `xirr` are all unaffected.
- Note: the identical class of issue (hard-delete retroactively erasing history) still exists for
  removing an asset position from a portfolio -- that flow already warns explicitly ("This will
  delete all history for this position") rather than silently doing it, but wasn't changed here
  since it wasn't the reported case; worth the same archiving treatment if it becomes a problem in
  practice.

### Added -- Palettes now recolor the whole theme, not just the accent -- plus a Gray palette

Follow-up to the palette feature: the light/dark backgrounds themselves (the warm cream/parchment
in light mode, warm dark brown in dark mode) stayed fixed regardless of which palette was chosen --
only the brass/gold accent button color changed. Every background and text token now shifts with
the palette too, and a 6th, fully neutral Gray palette was added.

- Every palette's full set (`--color-ink`, `--color-ink-raised`, `--color-panel`,
  `--color-panel-hairline`, `--color-parchment`, `--color-parchment-dim`, `--color-ink-text`,
  `--color-muted`, plus the accent pair) is now computed via **HSL hue rotation** from the original
  brass theme, keeping the exact lightness/saturation of each token and only changing its hue to
  match the palette's accent -- rather than hand-picked, so the contrast ratios already tuned in
  the brass theme carry over unchanged to every other palette. `--color-gain`/`--color-loss` stay
  fixed across all palettes since they carry their own meaning (profit/loss), not the app's theme
  color.
- **New Gray palette**: the same hue-rotation technique with saturation forced to zero, giving a
  true neutral black/white/gray theme in both light and dark mode.
- `lib/chartTheme.ts` rewritten to carry a full `grid`/`muted`/`panelBg`/`text`/`accent` set per
  palette (previously only `accent` varied) so charts, tooltips, and the world map match the CSS
  exactly rather than only their accent line matching while their background/grid stayed brass-toned.
- Verified via full rebuild + typecheck and by inspecting the compiled CSS output directly: all 6
  palettes x 2 modes (10 non-default combinations, since brass needs no override) produced the
  expected 10 CSS custom properties each, in the correct `.dark`-then-`[data-palette]` source order
  needed for the specificity trick this stylesheet already relies on.

### Added -- Consolidated sidebar (11 -> 7 pages) and customizable accent palette

Two related UI changes, chosen after reviewing several navigation restructuring options.

**Sidebar consolidation** -- Portfolio Allocation, Currency Exposure, and Geographic Allocation
merge into a single **Allocation** page with Category/Currency/Geography tabs; Transactions,
Expense Categories, and Expense History merge into a single **Expenses** page with
Log/Categories/History tabs. Sidebar drops from 11 items to 7: Summary, Portfolios, Asset
Catalogue, Allocation, Historical Net Worth, Expenses, Settings.

- `pages/Allocation.tsx` and `pages/Expenses.tsx` are thin wrappers: a `SegmentedControl` tab
  switcher over the existing page components, now stripped of their own duplicate `<h1>` headers
  (their useful explanatory tooltips were relocated to the relevant sub-heading rather than
  dropped -- e.g. the Stock/Bond/Cash tag explanation now lives on Allocation's "Breakdown"
  heading).
- Tab state is deliberately plain `useState`, not the URL or `localStorage` -- every tab always
  starts on Category/Log when you navigate to the page, refresh included, as decided explicitly
  rather than persisted.
- `components/Sidebar.tsx` and `App.tsx` updated to the new 7-item nav and 2 new routes
  (`/allocation`, `/expenses`); the 6 old routes are gone. No other page linked to them directly
  (checked before removing), and the mobile drawer's title-lookup logic (`App.tsx`'s
  `CurrentPageTitle`) needed no changes since it already matches on the current route generically.
- Caught and fixed one new mobile-overflow risk before shipping: `ExpenseCategories`'s header row
  (title + "+ New category" button) had no `flex-wrap`, and the title text got longer once it
  stopped being a page's own `<h1>` and became a plain description sentence -- the exact shape of
  bug that previously hit Geographic Allocation. Added `flex-wrap gap-3` up front instead of
  waiting for a bug report.
- Verified via full rebuild + typecheck, a line-by-line review of all 6 surgically-edited files for
  orphaned tags or leftover text (found and fixed two stale "Portfolio Allocation" mentions in
  `Assets.tsx` and `GeoAllocation.tsx`), and confirming no other page held a stale link to a
  removed route. (No headless browser was available in this environment to click through the
  mobile drawer directly; verification relied on the fact that the drawer/hamburger mechanism
  itself was not touched, only the number of items it lists, and that the new in-page tabs reuse
  `SegmentedControl`, already proven mobile-safe from earlier fixes.)

**Customizable accent palette** -- the app's accent color (previously a fixed brass/gold, in both
light and dark mode) is now a choice of 5 presets: Brass (default), Teal, Bordeaux, Slate Blue,
Forest.

- New `context/PaletteContext.tsx`, same pattern as the existing `ThemeContext` (persisted to
  `localStorage`, applied via an attribute -- `data-palette` -- on `<html>`).
- `index.css` gained 4 new override blocks (one per non-default palette), each only touching
  `--color-brass`/`--color-brass-dim` in both light and dark mode -- every other token (gain/loss,
  ink, panel) stays fixed, since those carry their own meaning rather than being "the app's color".
  Declared after `.dark` in source order so `[data-palette=X].dark` wins over plain `.dark` at
  equal specificity, the same trick `.dark` itself already relied on.
- `lib/chartTheme.ts`'s `getChartTheme` now takes the current palette and swaps the chart accent
  (and the first slot of the 15-color categorical ramp) to match; every one of its 7 call sites
  across the app was updated. `PortfolioAllocation.tsx`'s category color map had its own separate
  hardcoded "Stock" color that happened to equal the accent -- also updated to track the palette,
  otherwise it would've stayed gold regardless of the chosen palette.
- Picker added to Settings as a new "Appearance" section: 5 swatches, each showing the color as it
  actually renders in the current light/dark mode.
- Verified the compiled CSS output directly (not just the source): confirmed all 8 palette rules
  survived the Tailwind/lightningcss build unmangled, with the correct `.dark`-then-`[data-palette]`
  source order preserved.

### Refactored -- Accidental-complexity cleanup pass (no behavior change)

A dedicated pass to remove dead code and duplication accumulated during development, with no
intended change to any observable behavior. Every scenario exercised across this whole project's
test history was re-run after each change and again at the end (cash/voucher transactions, same-day
balance resolution, historical valuation, category auto-coloring, Pension Fund's transaction
rejection, and a full `snapshot`/`history`/`growth`/`xirr` sweep) -- all pass unchanged.

- **Removed 4 dead imports** (`xirr.py`'s `timedelta`, `geo-allocation/main.py`'s `Dict`/`Optional`,
  `geo-allocation/storage.py`'s `FundMetadata`, `gateway/main.py`'s `Optional`) -- confirmed via
  `pyflakes` across every backend service, not by inspection.
- **De-duplicated Pydantic validators** in `schemas.py`: `_round_unit_value` and
  `_round_and_check_positive` were each written out twice, once per Create/Update pair. Pulled out
  as module-level functions (alongside the pre-existing `_round3`) and bound with
  `field_validator(...)(fn)`, the same pattern the file already used elsewhere.
- **Extracted a shared `_resolve_fx` helper** in `valuation.py` for the "historical rate for a past
  date, today's rate otherwise, fall back to 1.0" logic that was repeated three times (holdings,
  cash accounts, combined dashboard net worth). The one genuine difference between call sites --
  holdings additionally treat a historical-fallback price as "not historical" for FX purposes --
  is now an explicit `effective_historical` argument at that call site rather than duplicated
  branching logic.
- **Extracted shared chart logic** into `components/chartHelpers.tsx`: the range-cutoff math,
  hour/percentage formatters, the `toPercentage` transform, the intraday-fetch `useEffect` (now a
  `useIntradayData` hook), and the growth badge JSX were byte-for-byte identical between
  `NetWorthChart.tsx` and `AssetPriceChart.tsx`. Extracted only the verified-identical pieces;
  deliberately left each chart's own Y-axis domain policy, available range set, tooltip labels, and
  money-formatting choice in place, since those differ for good reason (net worth vs a single
  asset's price) and merging them risked changing what actually renders. Verified with a full
  rebuild -- output bundle size dropped slightly (702.58 KB -> 701.64 KB), consistent with removed
  duplication and no added logic.
- **Removed `debug_xirr.py`**: a read-only diagnostic script, never imported by the running app,
  runnable only by hand inside the container. No longer needed day-to-day; removed to reduce the
  repo's surface. (Its own docstring's usage instructions are now only in this changelog's history,
  not in the codebase.)

### Fixed -- Snapshot/history/growth/xirr crashed with a 500 on portfolios with older cash accounts

The previous same-day fix introduced a regression that broke every existing portfolio outright:
`resolve_cash_balance` compared `CashTransaction.created_at > anchor.created_at`, but
`created_at` is nullable on both models (rows created before that column existed have none --
by design, see their docstrings), and SQLAlchemy raises immediately if `>` is used against a
Python `None` instead of `is_()`/`is_not()`. Any portfolio with a cash account whose opening
balance predated the `created_at` column -- i.e. any portfolio that existed before this feature,
which is all of them -- hit this on every snapshot, cascading into `/snapshot`, `/history`,
`/growth`, and `/xirr` all returning 500.

Fixed by treating a missing `created_at` on either side as "unknown, include the transaction"
rather than attempting the comparison -- consistent with the goal of the same-day fix in the first
place (fail open, not closed, since silently excluding a real transaction is the bug being fixed).
Verified against the exact failure mode (an anchor balance entry with `created_at` explicitly
`NULL`, same day as a transaction) plus a full re-run of every other balance scenario and a sweep
of `/history`, `/growth`, and `/xirr` to confirm none of them 500 anymore.

### Fixed -- A transaction logged the same day as the opening balance was silently ignored

The exact scenario of creating an account and immediately logging its first transaction (very
common -- e.g. setting up a new meal-voucher account and logging today's lunch right after)
produced a portfolio balance that never moved: the transaction showed up correctly in Transactions'
recent list and in Expense History, but `resolve_cash_balance` (`valuation.py`) excluded it from
the actual balance calculation.

Cause: the anchor balance and same-day transactions were compared with a strict `entry_date >
anchor.entry_date`, which is false when both share the same date -- so any transaction dated the
same day as the account's opening balance was silently dropped from the sum, regardless of account
kind. This bug predates meal vouchers (it affects ordinary Cash accounts too) but had gone
unnoticed because earlier testing happened to use different dates for the opening balance and its
first transaction.

Fixed by falling back to `created_at` to order same-day events: a transaction now counts if it's
dated after the anchor, or dated the same day but recorded later that day. Verified with the exact
same-day scenario for both a VOUCHER and a CURRENCY account, plus a full re-run of every earlier
cross-day balance test to confirm nothing regressed.

### Fixed -- Clicking a SegmentedControl button inside a form submitted it early

Clicking "Vouchers" on the new Cash-account form submitted the form immediately with whatever was
still in the other fields (usually empty), creating a stray blank account and closing the form —
instead of just switching the toggle. Cause: `SegmentedControl`'s buttons had no explicit
`type="button"`, so inside a `<form>` the browser defaulted them to `type="submit"`. Fixed in the
shared component itself, so it's fixed everywhere `SegmentedControl` is used, including the same
latent bug on the Income/Expense toggle in Transactions (not yet reported, but the same code path).
If you hit the stray empty account from before this fix, delete it with its "Remove" link -- the
fix stops new ones from being created but doesn't clean up an existing bad row.

### Added -- Meal vouchers (quantity-based cash accounts)

Adds a second kind of cash account for balances tracked as a count of identical-value units
instead of a currency amount -- meal vouchers being the motivating case, but generically useful
for anything similar. Extends the existing Cash/Transactions/Expenses system rather than adding a
parallel one, so meal-voucher spending shows up in the same net worth totals and expense reports
as everything else, with no separate infrastructure to maintain.

- **`CashAccount.kind`** (`CURRENCY` | `VOUCHER`, default `CURRENCY`) + **`unit_value`**: a VOUCHER
  account's balance is a unit count, and `unit_value` (editable any time) is what a single unit is
  worth. Offered only for new Cash-section accounts (`pages/PortfolioDetail.tsx`'s "+ Add" form
  gained a Currency/Vouchers toggle) -- not Emergency Fund or Pension Fund, since Pension Fund
  doesn't accept transactions at all and Emergency Fund isn't the intended use case.
- **`CashTransaction.quantity`**: for a VOUCHER account, you log a quantity (e.g. "2 vouchers spent
  at lunch") instead of a euro amount. The backend computes `amount = quantity * unit_value` at
  that moment and freezes it on the row -- if `unit_value` changes later (a new voucher contract,
  say), past transactions keep reporting the euro value they actually had; only transactions logged
  after the change use the new rate. Verified end-to-end: quantity in/out correctly moves the
  running balance, the frozen amount survives a later `unit_value` change, and the balance shown
  everywhere (Portfolio, Summary, Expense History) is always quantity × *today's* unit_value.
- **Net worth**: a voucher account's contribution is `quantity * unit_value`, computed through the
  same FX/valuation pipeline as any other cash account (trivially a no-op when its currency matches
  the portfolio's base currency, as vouchers normally would).
- **Transactions page**: selecting a voucher account swaps the "Amount" field for "Quantity", with
  a live "= €14.00" preview underneath as you type. The recent-transactions list and Expense
  History's movements table both annotate voucher rows with "(2×)" next to the euro amount.
- No new expense-report code needed -- a voucher transaction's frozen euro amount flows through
  `/expenses/summary` and `/transactions` exactly like a normal one, category tagging included.

## 2026-08-25

### Added -- Expense category colors are now assigned automatically, no fixed limit

The category color picker (8 fixed swatches, defaulting to the same one on every new category
unless manually changed) was guaranteed to produce duplicate colors once you had more than a
handful of categories -- exactly what happened testing this with a long real category list, two
categories sharing a color merge visually in the Expense History pie chart.

- **Colors are no longer picked by hand.** `POST /expense-categories` now assigns one automatically
  server-side, spreading hues using the golden angle (~137.508°) -- the standard technique for
  placing points around a color wheel one at a time so each new color lands as far as possible
  from every one already assigned. No cap: this scales to as many categories as you create, unlike
  a fixed swatch list. Verified colors stay distinct across the first several categories created.
  `color` was removed from `ExpenseCategoryCreate`/`ExpenseCategoryUpdate` entirely -- the API
  ignores any color a client sends and always computes its own.
- The category form (`pages/ExpenseCategories.tsx`) no longer shows a color picker at all; a short
  note explains the color is chosen automatically. Renaming a category leaves its color untouched.

### Fixed -- "Update" balance button still showed on Cash/Emergency Fund, Pension Fund never excluded

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

### Added -- Expenses frontend (Transactions, Expense Categories, Expense History)

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

### Added -- Expense tracking backend (income/expense ledger for cash accounts)

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

### Fixed -- Two remaining mobile overflow spots found in real-device testing

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

### Added -- Mobile-friendly tables and filter controls across every page

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

## 2026-08-20

### Fixed -- A NaN closing price from Yahoo Finance crashed historical price lookups with a 500

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

## 2026-08-01

### Fixed -- A failed historical price fetch counted a position as worth zero — including in frozen snapshots

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

## 2026-07-29

### Changed -- Renamed "Cash" to "Other" in the Summary/Portfolio net worth stat

The top-level "Invested / Cash" stat's second figure sums *all* cash-like accounts regardless of
category (Cash, Emergency Fund, and Pension Fund alike — confirmed in `valuation.py`, the
`cash_total` loop has no category filter), so labeling it "Cash" was misleading whenever a
portfolio has an Emergency Fund or Pension Fund account too. Renamed to "Other" in both places it
appears (Summary/Dashboard and each Portfolio Detail page). Left every other "Cash" label alone —
the `BalanceSection` titled "Cash" (the actual Cash-category account list) and the category-tag
explanation text in Portfolio Allocation's tooltip both correctly refer to the literal Cash tag,
not this aggregate.

### Fixed -- Updating a cash balance (or holding) twice in one day could silently show the wrong value

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

### Added -- Info tooltip on the "n/a" price badge, explaining wrong-exchange-suffix ticker failures

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

## 2026-07-22

### Audit -- Audit round 3 -- exhaustive re-test, no new bugs found

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

### Audit -- Audit round 2 -- four more real bugs found in the new backup/restore code

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

### Added -- Export / restore a full backup from the UI

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

## 2026-07-21

### Fixed -- Code audit: asset deletion, cash account editing, cross-service cleanup

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

### Added -- Info tooltips across the rest of the app

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

### Fixed -- (round 2) XIRR tooltip still ran off-screen — real cause was a wrong height guess

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

### Fixed -- XIRR info tooltip ran off-screen near the top of the page

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

### Added -- XIRR info tooltip

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

### Added -- Chart Y-axis auto-zoom on Day/Week/Month/Year, plus an absolute/percentage toggle

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

### Fixed -- Live chart silently skipped days instead of accumulating them

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

### Added -- Real return: XIRR (money-weighted annualized return)

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

## 2026-07-20

### Changed -- Geographic Allocation: chart and country table as two separate cards

- The chart/map and the country breakdown table were inside one continuous card with just a
  margin between them, which didn't read as clearly separated as intended. They're now two
  distinct cards with a real gap between them, matching the layout style used everywhere else in
  the app for stacked sections (Positions / Cash / Emergency Fund, etc.).
- Verified via the actual rendered DOM, not just visually: confirmed two separate `.card` elements
  with a 32px gap between them, not one container with internal spacing.

### Changed -- Geographic Allocation: contained chart layout, and a world map view

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

### Fixed -- Every ETF's price chart showed "Not Found"

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

### Added -- Per-asset price chart and Currency Exposure

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

### Added -- Week range button, and real hourly prices on "Day" (broker-style chart)

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

### Added -- Growth stats per period, and the live chart now always reaches today

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

### Added -- Automation: price refresh, monthly snapshot catch-up, and daily backups

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

### Added -- Real historical prices (live chart is now actually accurate over time)

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

## 2026-07-19

### Added -- Dark mode "Deep Ink"

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

### Added -- New tab: Historical Net Worth (frozen manual snapshots)

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

### Changed -- Palette correction: cream panels, deeper brown ink

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

### Changed -- Visual redesign "Ledger Light"

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

### Added -- Value column decimals and in-app balance editing

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

### Added -- Chart time-range filter and 3-decimal currency precision

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

### Added -- Editable tag on Cash / Emergency Fund / Pension Fund

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

### Added -- Unified allocation categories, Emergency Fund, and simplified Pension Fund

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

### Docs -- Data persistence clarification (docs only, no code changes to runtime behavior)

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

### Changed -- Price feed reliability, cash and allocation tables, Stock/Bond tag, automatic column migrations

#### Price feed reliability

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

#### Cash accounts

- Cash accounts are now shown as a table matching the Positions layout — Account, Currency,
  Balance, and **converted Value** per row — instead of a name-and-balance list with only an
  aggregate total.
- New `cash_positions` field on the portfolio snapshot API, computed per account (balance × FX
  rate to the portfolio's base currency).

#### Geographic allocation

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

#### Positions table

- Added a dedicated **Ticker** column (previously shown inline next to the asset name).
- Added a **Tag** column showing the Stock/Bond badge, if set.

#### Database migrations

- Added a lightweight auto-migration step (`services/core-networth/app/migrate.py`) that runs on
  every service startup: it compares each SQLAlchemy model's columns against the actual SQLite
  schema and adds any missing ones with `ALTER TABLE ... ADD COLUMN`. This was needed because
  `Base.metadata.create_all()` only creates missing tables, never alters existing ones — without
  this, adding `Asset.instrument_type` broke every existing database with a hard `sqlite3.OperationalError:
  no such column` on startup. The migration is additive-only, safe on existing data, and idempotent
  (a no-op on an already up-to-date database), so it will keep covering any future column additions
  without needing a full migrations framework.

#### Files touched

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
