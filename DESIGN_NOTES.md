# Design notes

Why the code is the way it is: the bugs, measurements and dead ends behind decisions that look
arbitrary or over-careful from the code alone. Code comments say what the code does now and why,
briefly; the history behind them lives here, by file. Read the section for a file before changing
it -- most entries describe a regression that removing the "odd" bit would bring back.

When a change fixes a bug or makes a non-obvious choice, add the story here (and the change itself
to CHANGELOG.md), and keep the code comment to the current rule.

## Packaging

### `services/*/requirements.txt`, `gateway/requirements.txt`
One Python environment per image, and CI has only one for all of them. `.github/workflows/tests.yml`
installs every service's requirements into the same interpreter, so a package declared by any one
service is importable by all of them; `docker compose build` gives each image only its own. A
missing requirement is therefore invisible to the whole suite and fatal in the container.

`python-multipart` is the one that keeps getting forgotten, because nothing imports it: FastAPI
needs it as soon as an endpoint takes `File(...)` or `Form(...)`, and raises from the `@app.post`
decorator, so the service dies at import with uvicorn printing `pip install python-multipart`.

Twice now. 2026-07-22, `core-networth` and `gateway`, when backup restore added file upload --
caught by hand because the three services were being run together. 2026-10-04, `bank-sync`, when
backup export/restore was added to it -- not caught: `main` was green, the container crash-looped
on the owner's NAS, the gateway reported the `bank` module `unreachable`, and automatic bank
capture was off. Only the second one was a silent failure, and only because nobody rebuilt the
images.

`tests/unit/test_service_requirements.py` now compares each image's code with its own requirements
file: declared third-party imports (parsed, not grepped -- `from` and `import` in prose produce
phantom packages), plus the `File()`/`Form()` rule that no import check can see. It is a stand-in;
the real cover -- building and starting the images in CI -- is the `compose` job below.

**The pins decide which interpreter can run the suite, and `3.12` is not a preference.**
`pydantic==2.9.2` pins `pydantic-core==2.23.4`, built with PyO3 0.22.2, which has no Python 3.14
ABI and ships no 3.14 wheel: on 3.14 the install fails while compiling, with no fallback. Measured
2026-10-05 on the owner's machine, whose system interpreter is 3.14.4 and which has no `pip`, no
`ensurepip`, no Docker and no root -- so four tiers and `ruff` fail there together with `No module
named pytest`, every time, on any diff. `.github/workflows/tests.yml` pins `3.12` for all three
jobs; raising that pin means raising `pydantic` first. How to report a run when the tiers cannot
execute is in `tests/README.md`.

## CI

### `.github/workflows/tests.yml`, `tests/compose/smoke.sh`

#### `compose` job
Every other job imports each service's Python modules directly or runs them as bare `uvicorn`
processes -- never through its Dockerfile, never through `docker-compose.yml`. Two real failures
slipped past that gap on 2026-10-04 with `main` green: `bank-sync` crash-looping on a missing
`python-multipart` (see Packaging, above) and a live deploy breaking on a `COPY` the build context
couldn't reach (see `shared/backup_retention.py`, below). CI cannot build from a remote Git URL
context (there is no clone to build from), so `smoke.sh` builds and starts the stack locally
instead, with no `.env` and no real credentials -- every variable `docker-compose.yml` reads has a
safe default, and bank-sync is documented to run with nothing configured -- and polls the
gateway's own `/health` rather than each service's directly: that is the one call that actually
crosses the chain the frontend depends on, and the one that would have caught `bank-sync`
answering every request while its own container looked "up". A container stuck `Restarting` fails
the same poll loop instead of hanging until the job's own timeout.

Verified against a real crash-loop, not just read: CI run `37276635499` built the stack with
gateway's `CMD` pointed at a module that doesn't exist (`app.mainn` instead of `app.main`). The
`compose` job failed in 3 seconds on `container(s) stuck restarting: gateway`, with the container's
own `Could not import module "app.mainn"` in the job log -- and only that job failed; `fast`,
`integration` and `system` stayed green, confirming no other tier can see this class of failure.

### `tests/unit/test_compose_build_contexts.py`

Stands in for the one thing `smoke.sh` cannot check: building from a remote Git URL context, the
way the owner's NAS actually deploys (`README.md`, "Building straight from GitHub"). It parses
`docker-compose.yml`'s build contexts, every Dockerfile's `COPY` paths, and that README table, and
fails if any two disagree -- the exact mismatch behind the 2026-10-04 deploy failure, now caught in
milliseconds. One thing worth remembering if this file is ever touched again: a Dockerfile's
`dockerfile:` path is resolved relative to its own `context:`, not to the repository root, per
Compose's own rule -- getting that wrong once made this check pass for the wrong reason instead of
catching anything.

## shared

### `shared/backup_retention.py`

#### `rotate_backups`
Before this existed, nothing in any of the three `backup.py` files (core-networth, geo-allocation,
bank-sync) ever deleted a daily `YYYY-MM-DD` or `pre-restore-<timestamp>` folder under
`BACKUP_DIR` -- searching for `retention`, `prune`, `max_backups` found nothing. On a machine left
running, `./backups/` only ever grew, and every restore added one more `pre-restore-*` copy, the
worst case since it happens on demand rather than once a day.

Policy chosen: every entry from the last `BACKUP_RETENTION_DAYS` days (default 30) is kept as-is;
older entries thin to one per calendar month. Plain "keep N days" would lose the ability to go back
more than a month at all, and "keep everything forever" is the bug this fixes; one-per-month after
the recent window is the smallest rule that keeps both a fine-grained recent history and a coarse
long-term one. The newest entry is never removed, whatever `BACKUP_RETENTION_DAYS` is set to
(including 0 or negative) -- a restore must always have a most recent copy to fall back to, and a
misconfigured env var must never be the reason there isn't one.

One module rather than the same logic copied into three `backup.py`/`scheduler.py` pairs. Because
of that, core-networth's, geo-allocation's and bank-sync's Dockerfiles now `COPY` this package in
and build with the repo root as context (see each service's Dockerfile and its entry in
`docker-compose.yml`) instead of just their own service folder -- a service-folder-only build
context cannot reach a file one level above it. Each service's `config.py` adds the repo root to
`sys.path` by walking up from its own file location (rather than hardcoding a depth), since that
differs between running from the repo directly (tests, local dev) and running inside the image
Docker builds (one level up, `shared/` copied as a sibling of `app/`).

That context change broke a live deployment the next day (2026-10-04). The host built from Git URLs
with one context per service folder (`...networth-suite.git#main:services/bank-sync`), from a
compose file kept outside this repository -- so nothing here could see it, and the test suite never
builds the images either (`tests/README.md`, "Known gaps"). The build stopped at
`COPY shared ./shared` with `failed to compute cache key: "/services/bank-sync/app": not found`, a
misleading message: `app` exists, what is missing is the prefix. Two things came out of it, both
worth keeping. The build-context mapping is now in `README.md` under "Building straight from
GitHub", where a deployer will look, instead of only here. And any change to these three
Dockerfiles' `COPY` paths is a breaking change for anyone building from a remote context, so it
belongs in CHANGELOG.md with that said out loud. `tests/unit/test_compose_build_contexts.py` (see
"CI", above) now checks the invariant itself: it fails if a Dockerfile's `COPY` paths stop
resolving under the context `docker-compose.yml` declares for it, or if README.md's table drifts
from either.

## core-networth

### `services/core-networth/app/main.py`

#### `_validation_error_handler`
Python's json parser accepts `NaN`/`Infinity` in a request body. Refusing such a value produced
a 422 whose body echoed the value back -- which JSON cannot encode -- so the 422 turned into a 500
while rendering. The refusal was right; only its report failed. The response shape is otherwise
the default handler's.

#### Idempotency (`_commit_with_idempotency`)
Checking for the key and then running the mutation used to be two steps, and two concurrent
replays of one key both passed the check before either committed -- so both ran. That is exactly
the case the header exists for (a client retrying while the original is still in flight).
Measured: 16 simultaneous replays of a single key created three transactions. Committing the key
in the same transaction as the mutation closed it.

A key reused for a *different* endpoint used to run the mutation and only then fail on the key's
primary key: a 500 for an operation that actually went through, which a retry would duplicate.

#### `_read_bounded`
Reading the upload whole and *then* checking its length meant the cap protected nothing: a
multi-gigabyte upload was already in memory when rejected, enough to get the process killed on a
small home server.

#### `delete_portfolio`
Deleting a portfolio cascades to its cash accounts and transactions -- including expenses that a
refund in another portfolio points at. A refund whose target is gone is skipped by
`compute_refund_adjustments`, so without un-linking it first it silently stopped counting as
income while still moving its account's balance. The ids are a subquery rather than bind
parameters because a busy ledger would hand SQLite one parameter per transaction, and how many it
accepts depends on how SQLite was built.

#### `delete_asset`
Deleting only the asset row left its HoldingEntry rows behind with a dangling `asset_id`, which
raised AttributeError in valuation.py (`h.asset` is None) on the next snapshot/growth/XIRR.

#### `list_cash_accounts(include_archived)`
Without it, the Expenses history couldn't resolve an archived account and fell back to EUR, so an
archived dollar account's spending was shown, silently, as euros.

#### `update_cash_account`
Didn't exist at first: fixing an account's name, currency or tag meant deleting and recreating it,
losing its balance history. The Pension Fund retag check closes a loophole: retag PENSION_FUND ->
CASH, log transactions, retag back -- which let real transaction history skew XIRR.

#### `delete_cash_account` (`archived_at = datetime.now()`)
It used to record UTC. Every date `archived_at.date()` is compared with (`date.today()`, a picked
`as_of`, an `entry_date` from the browser's calendar) is a local day, so for the hours each day when
the local and UTC dates differ the account either lingered in today's totals after removal
(server behind UTC) or vanished from yesterday's history too (server ahead) -- the retroactive
rewrite the column exists to prevent.

#### `_validate_refund_target` (same portfolio, same currency)
A USD refund against a EUR expense cancelled it 1:1, and a refund logged in another portfolio
shrank that portfolio's spending with money that never entered it. The Expenses page only ever
offered same-portfolio expenses; the API now enforces the same rule. A row that predates the rule
must still be editable -- refusing to let its note be fixed would leave it stuck for good.

#### `create_cash_transaction` (voucher without unit value)
Logging a voucher transaction before the account had a unit value froze `amount` at 0 forever,
producing a transaction that moved the unit-count balance but was invisible to
`/expenses/summary` and every money-value report.

#### `update_cash_transaction`
- Re-validating only the fields the payload touched let an edit of `direction` alone
  (INCOME -> EXPENSE) leave a refund link on what was now an expense, which
  `compute_refund_adjustments` then double-counted.
- Editing an expense that refunds point at -- turning it into income, or into a refund itself --
  left those refunds netted against a row `/expenses/summary` no longer counts as spending: their
  income silently stopped being reported while still moving the balance.
- Editing `amount` directly on a voucher account left the money figure in every report disagreeing
  with the unit count that actually moves the balance, with no way to tell which was right.

#### `compute_refund_adjustments` (refund whose expense is gone)
Falling through with nothing recorded made `/expenses/summary` read `excess_amounts.get(id, 0.0)`
as "fully absorbed" and drop the refund entirely: money that really came back, in no report.

#### `combined_net_worth` / `combined_totals`
Summing per-portfolio snapshots client-side counted, say, dollars as euros as soon as two
portfolios had different base currencies. Converting each point at today's rate (rather than that
day's) mixed the two: a USD portfolio's whole history moved every time EUR/USD did, redrawing
points already plotted.

#### `portfolio_intraday(for_date)`
`for_date` was a string parsed with strptime, so `?for_date=nope` answered 500. Typing it as a
`date` lets FastAPI answer 422, like every other date parameter.

#### `take_networth_snapshot`
Overwriting a scheduler-made row kept `source="auto"`, so the table said the number came from the
month-end job when it didn't.

### `services/core-networth/app/valuation.py`

#### `resolve_cash_balance`
- Same-day handling: a strict `entry_date > anchor date` silently dropped a transaction logged the
  same day as the opening balance -- the common case of creating an account and logging its first
  movement. `created_at` is nullable on both tables (rows from before the column existed), and
  SQLAlchemy rejects `>` against a Python None, so missing data fails open: excluding same-day
  transactions is the exact bug the block exists to avoid.
- Summed in SQL: the row-by-row version loaded every transaction from the opening balance up to
  each chart point, so the work grew with the square of the history (a transaction's date is
  itself a chart point). Five years of daily expenses meant 1.7 million ORM rows per chart: 25s
  for `/history`, 33s for `/networth/combined`, past the gateway's 30s timeout -- the Summary page
  answered 502 and never loaded.

#### `compute_portfolio_snapshot`
- Historical-price fallback: a failed historical fetch (very commonly the price-feed cache wiped
  by a container restart) used to count the position as zero -- catastrophic for the frozen
  month-end snapshot. `compute_asset_growth` already fell back to the latest price; this closed
  the same gap for portfolios. A fallback price is today's, so it is paired with today's FX rate.
- `fx_unavailable` exists because a total that silently mixed currencies looks perfectly plausible.

#### Intraday charts
- `compute_portfolio_intraday` used the asset record's currency for ticker prices: a US-listed
  fund recorded as EUR showed 1000 on the chart and 500 on the headline tile above it.
- Converting a past day's line at today's live rate (both intraday functions) made the chart
  disagree with that day's history point by the whole FX drift since; cash was likewise today's
  balance even for a past date.
- `compute_combined_intraday` counted a portfolio whose market hadn't opened yet as zero, so the
  combined line started at a fraction of the total and "jumped" when that market opened.

### `services/core-networth/app/xirr.py`

#### `_MIN_RATE`, `_xnpv`, `xirr`
- The case that exposed the floor: 36k contributed, 327 left, with its root at about -99.9995%.
- Discounting near -100% used to escape `xirr()` as an OverflowError -- a 500 from the XIRR
  endpoints -- for exactly the portfolio that most needs an answer.
- Newton-Raphson's "step too small to move" used to be returned as the answer even with the NPV
  far from zero; abandoning a step past the floor (instead of halving towards it) lost answers the
  older solver found.

#### `build_portfolio_cashflows`
- Archived accounts: without valuing them at 0 from the archive date, their balance simply
  vanished from the reconstruction while the end-of-window total (which excludes them) looked
  unexplained. Valued this way, archiving an account and re-adding a fresh one with the same money
  nets out instead of counting as two unrelated contributions.
- Vouchers: without converting the unit count, topping up 100 meal vouchers entered XIRR as a
  100 EUR contribution while showing as 800 EUR of value -- a several-hundred-percent "return".
- Dividends/coupons/interest (AGE-3): before `InvestmentIncomeKind` existed there was no way to
  log one except as a plain income transaction, which this function (correctly, for a plain
  income) reads as money moved in from outside -- a contribution. That made the one figure in the
  app meant to tell you whether an investment is doing well systematically *understate* it: real
  investment income lowered the solved rate instead of raising it, exactly backwards, and silently
  (both numbers looked plausible). A transaction with `investment_income_kind` set is now excluded
  from the delta here, so it reads as return; the balance itself, and every past day's valuation,
  are unchanged -- only how XIRR accounts for the one credit differs. Old data stays exactly as
  ambiguous as it always was: a plain income transaction already logged by hand is never guessed
  into being a dividend, because there is no way to tell a deposit from one without asking the
  user, and this fix doesn't touch rows it can't be sure about.

### `services/core-networth/app/models.py`

#### `HoldingEntry.created_at` / `CashBalanceEntry.created_at`
Without a tie-breaker, "which edit wins" for two entries on the same `entry_date` was whatever
order SQLite returned them in: a second same-day balance update could appear not to have "taken"
even though it was saved.

#### `CashAccount.archived_at`
Deleting an account outright used to erase its contribution from every past date too, producing
a fake overnight swing the day it was removed (or re-added). Rows archived before local time was
settled on hold a UTC moment, so on a server not running UTC their date can be a day out --
harmless on the default Docker image, which is UTC.

### `services/core-networth/app/schemas.py`

#### `_require_finite`
An infinite amount, once stored, made every figure it fed infinite -- not representable in JSON --
so `/networth/combined/totals`, the dashboard's headline number, answered 500 and kept doing so.
The row couldn't be found and deleted from the UI either, because the pages that would show it
broke on the same value. NaN was only caught by accident (SQLite refusing it in a NOT NULL
column). The fund parser already guarded its weights against the same poisoning.

#### `_reject_future_date`
A future-dated entry sorted after the closing "today" flow XIRR solves against (turning a healthy
account into a -98%/year return), and put a point past today on the history chart while the days
in between were never filled in. Rejecting the "one day ahead" dates outright was a confusing
error for users east of the server, who did nothing wrong.

#### `_normalize_currency`
An unhandled throw from Intl.NumberFormat blanked the whole page, with no way left to correct the
value that caused it; the API is the one place that can't be bypassed.

#### `_reject_explicit_null`
An explicit null reached `setattr(row, field, None)` and failed on the NOT NULL constraint at
commit: a 500 for a bad request. A portfolio's `archived` was worse -- the column is nullable, so
the write succeeded, and the row then couldn't be read back at all (the response types it `bool`).

### `services/core-networth/app/price_client.py`

#### `_clients`
Keyed by `id(loop)` first: nothing ever removed an entry (50 short-lived loops left 33 clients
held), and CPython reuses addresses -- 17 of 50 new loops landed on a dead loop's address and got
its client. Harmless only while that client was closed; one left open would fail every request
on the dead loop. Opening a client per call instead cost ~90ms each: ~600 days of history took
nearly a minute per chart, past the gateway's 30s timeout (see the module docstring).

### `services/core-networth/app/database.py`

#### `NullPool`
SQLAlchemy's default QueuePool allows 5 + 10 overflow connections; the 16th concurrent session
waits 30s and fails. `/history` holds its connection while valuing the portfolio once per tracked
day, so a few slow requests reached the ceiling -- then a 30-second hang and a QueuePool
TimeoutError as a 500, which the gateway reported as the module being unreachable. Measured: 20
concurrent mixed requests, 52 of 60 failed. NullPool is what SQLAlchemy itself used to do for
file-backed SQLite.

### `services/core-networth/app/config.py`

#### `BACKUP_DIR` / `backup_target`
`BACKUP_DIR` used to be hardcoded to `/backups`, at the filesystem root, which only root can
create. Running the services directly on the host (a documented setup) meant two silent failures:
the daily backup swallowed its PermissionError and never ran, so the user believed they had
automatic backups and had none; and Settings -> Restore answered a bare "Internal Server Error".

#### No `BASE_CURRENCY` setting
The currency of every aggregated figure is a per-request parameter (`base_currency`/`currency`,
default EUR) and each portfolio has its own `base_currency`. A global `BASE_CURRENCY` variable used
to exist, read by nothing, and did nothing when set.

### `services/core-networth/app/backup.py`

#### `consistent_copy`
Both the on-demand export and the daily backup used to copy the file directly, which can catch it
mid-transaction: the copy held a half-written page and only revealed itself as corrupt at restore.

#### `_stats_for`
Used `with sqlite3.connect(...)`, which only ends the transaction -- every call leaked an open
handle to the database file.

### `services/core-networth/app/scheduler.py`

#### `scheduler_loop`
Without the catch-all, an error before a job's own `try` (opening a session against a database
whose file has gone away, say) ended the background task for good: nothing surfaced, the API kept
serving, and month-end snapshots and daily backups stopped until someone went looking for a backup
that was never taken.

## bank-sync

### `backup.py`
bank-sync's database (SyncedTransaction, what stops a sync from capturing the same transaction
twice) was in no backup at all until it joined the gateway's combined backup.

### `sync._usable_date`
Both guarantees were learned the hard way. Core rejected the transaction, it was never marked
synced, the watermark never advanced past it, and the link silently stopped capturing anything
new: once because the bank's raw date string was sent as-is (a local format, or an object), once
because a scheduled/pending payment was dated in the future.

### `sync._mark_skipped`
Without it, skipped transactions (zero amount, no direction, unreadable amount) stayed unknown:
every cycle they passed the dedupe check again and were appended to the audit CSV once more --
one duplicate row per transaction per cycle.

### `main.callback`
- An account id that couldn't be resolved used to flip the link to ACTIVE anyway: identical to a
  healthy link on the status page, while sync's `not link.eb_account_id` guard no-op'd forever.
- `valid_until` had no offset added, so every link was flipped straight back to EXPIRED by the
  next sync cycle.

### `mcc_categories`
- A mistyped line in the optional mcc_categories.yaml used to escape `load_mcc_mapping`: since
  `build_resolver()` runs at the start of every cycle and in the authorization callback, it
  stopped all syncing and made authorizing a bank fail with a 500.
- A directory left by Docker in place of the file was skipped silently, looking like a mapping
  that never matched.
- A failed category lookup aborted the whole cycle before a single transaction was captured, and
  turned an authorization that had already succeeded into a 500.

### `csv_log.log_transaction`
Reading every row back just to learn the header happened on every logged transaction: the cost
grew with the whole log, and the entire audit trail sat in memory each time.

### `links_config.load_links_config`
Treating "unreadable file" like "empty file" made a bind-mount glitch look like the user had
deleted every bank: every link was flipped to REMOVED and syncing silently stopped.

## geo-allocation

### Country names and regions
- `country_names`: countries `regions.py` mapped had no display name, so the by-country chart
  showed the bare ISO code ("LU"), which made real exposure look like an unidentified leftover.
- `regions`: several European/Asian countries `normalize_country` recognizes had no region, so a
  fund's exposure to them (Luxembourg money-market holdings, Malta, Ukraine bonds...) fell into
  "Other / Unclassified". Namibia ("NA") likewise, after `countries.py` had been fixed to stop
  reading it as a missing value -- which had moved real exposure into "Other".

### `aggregate_portfolio_allocation` (coverage)
A fund that parsed to e.g. 85% (allowed by the 50% upload threshold) counted as fully covered, so
`covered_weight_pct` could say 100% while the regions summed to well under that.

### `parsers/base.parse_weight`
Assuming Italian format unconditionally read the English "1,234.56" as 1.234.

### `config.BACKUP_DIR`, `_read_bounded`
Same history as core-networth's: a hardcoded `/backups` silently disabled the daily backup on a
host install, and reading uploads whole before checking their size protected nothing.

## price-feed

### `services/price-feed/app/main.py`

#### `_ticker_currency`
The "USD" guess made when Yahoo's lookup failed used to be cached forever: one rate-limited reply
silently relabelled a Milan-listed EUR holding as USD for the life of the process -- and the
permanent `_historical_cache` entries built from it kept it so. Core then converted a price that
was never in dollars, wrong by the EUR/USD rate with nothing on screen to suggest it.

#### `_fetch_price_on_date`, `_fetch_intraday`
Caching today's partial bar (or today's intraday series) under the date's permanent key served
the partial value as if it were the finished day, forever -- the afternoon never appeared.

#### `/history` cache
`/history` was the only endpoint hitting yfinance on every request, even for the same chart
reloaded a few times.

#### No `/cache/clear`
One existed, documented as used by "Refresh prices" -- nothing ever called it. That action
passes `force=true` on the prices it refreshes, and every cache here expires on its own.

#### NaN closes
A NaN close left in a response crashed serialization with a 500 instead of falling through to
"no data" like an empty DataFrame.

## gateway

### `gateway/app/main.py`

#### Upload limits (`MAX_BACKUP_UPLOAD_SIZE_BYTES`, `MAX_PROXY_BODY_BYTES`)
The gateway read whole uploads (and, in the proxy, `await request.body()`) before the backend's own
caps ever ran, so those caps protected nothing: a 500MB post took the gateway from 50MB to 1.5GB of
RSS and still ended in the 413 it should have been refused with.

#### `delete_asset_and_cleanup`
Deleting an asset used to hit core-networth only, leaving the uploaded factsheet and parsed
allocation behind in geo-allocation every time -- private data with no way to clean it up short of
reaching into the container's filesystem.

#### `proxy` (`httpx.InvalidURL`)
It isn't an `httpx.HTTPError`, so it escaped the handler as a 500 for a malformed path.

## frontend

### `ErrorBoundary`, `lib/format.formatWithCurrency`
One malformed currency code stored on one account made Intl throw while drawing a table, and the
whole interface -- sidebar, navigation, everything -- vanished, including the page with the button
needed to correct it.

### `chartHelpers.subtractMonths`
`setMonth(getMonth() - 1)` on 31 March landed on 3 March, so the "Month" window was 28 days short
at the end of long months and disagreed with the "since ..." badge computed by the backend.

### `lib/format.parseLocaleFloat`
Each rule was a silent mis-parse first: "10,5" -> 10 (parseFloat); a pasted "1.234.567" -> 1.234
(a million-fold error, stored without complaint); "1 000 000" -> 1 (parseFloat stops at the
space); "1.5k" -> 1.5 and "10-20" -> 10 (not NaN, so no caller could tell). Trailing text such as
"250000 euro", once silently ignored, is now refused.

### `formatMoneyPrecise`
formatMoney's 3-decimal cap collapsed a price under half a cent to "0.00".

### `GeoAllocation` portfolio picker
The page kept its own copy of the picker, whose "select the first portfolio" check ran in a
callback that captured the first render's selection (permanently ""), so every reload after an
upload or delete snapped the picker back to the first portfolio.

### `Dashboard` -> `NetWorthChart fetchIntraday`
A fresh arrow function every render made useIntradayData re-fetch and flash "Loading hourly
prices…" on every unrelated re-render while on "Day".

### `Assets` search
A separate mount effect alongside the debounced one fired the first request twice, 300ms apart.

### `ExpenseHistory` (archived accounts)
Without them, rows showed "—" for the account and fell back to EUR formatting: an archived dollar
account's spending was shown, with no warning, as euros.

### `api/client.downloadFile`
"Download full backup" produced nothing on some browsers: a detached `<a>` is ignored by Firefox,
and revoking the URL immediately could pull the blob from under the queued download. It also
401'd whenever the gateway had an API_KEY, being the only call not sending it.

### `PortfolioDetail`
- Add position: an unreadable manual price became NaN, which JSON.stringify writes as null, so a
  manually-valued asset (a house, an unlisted fund) was created worth nothing, the typed figure
  gone and no error shown.
- Cash section: every write ran with no catch -- a rejected request left the promise unhandled,
  the row stuck in edit mode, and nothing on screen. An unparseable balance returned silently, so
  "Save" did nothing. `parseLocaleFloat(unitValue) || 0` turned a blank unit value into a voucher
  account worth €0.
- Account details (name/currency/tag) couldn't be changed after creation at all; delete +
  recreate lost the whole balance history.

### `Transactions`
- Refund picker resolved against active accounts only: an expense on a removed account showed a
  blank account name and defaulted to EUR, so the dropdown said to enter euros for what the server
  then rejected as "this expense is in USD".
- Switching portfolio mid-pick left a stale refund target queued to submit while the dropdown
  showed nothing selected.
- Deleting an expense (or one of its refunds) left the refund picker offering amounts computed
  from a transaction that no longer existed, until reload.
- Dividend/coupon/interest income (AGE-19, frontend half of AGE-3): the list row replaces the
  Category cell with a short "◆ Dividend/Coupon/Interest" tag, the same slot a transfer or a
  refund already take over, rather than adding a column -- the list is already dense and a
  transaction with `investment_income_kind` set is rare enough that losing the category label
  there (it can still carry one; the backend doesn't forbid it) costs less than a wider table.
  `canMarkInvestmentIncome` (`lib/investmentIncome.ts`) mirrors the backend's
  `_validate_investment_income` (only an INCOME, never a refund) so the picker in both the log form
  and the edit form only ever offers a combination the server accepts.

### `Assets` form `key`
Without remounting, "Edit" on a second asset with the form open kept the first asset's values in
the inputs, and saving wrote one asset over the other; "+ New asset" from an open edit form
created a duplicate.

### `PortfolioDetail` remove asset
A failed bulk delete was swallowed, and the row looked removed until the next refresh.

### Smaller ones
- `GeoAllocation` upload input: without clearing it, a rejected upload couldn't be retried by
  picking the same (fixed) file -- its value hadn't changed, so no event fired.
- `WorldMapChart`: on touch devices the map had no way to show a country's name/share at all.
- `isoNumericCodes`: countries missing here (Luxembourg, Ukraine...) appeared in the table and
  pie while the map left them unshaded, as if the allocation were zero.
- `InfoTooltip`: a fixed-guess height let long content overflow the top edge.
- `RangeAreaChart` / `WarningCard`: extracted from near-identical copies (two charts; four pages
  whose warning styles had started drifting apart).
- `api/client.errorMessage`: the unit tests run it against the real refusal bodies; that is how
  the `undefined` hole was found.

### `api/client.errorMessage`
Every page renders `e.message`, and a validation failure's array `detail` stringified to
"[object Object]": a ticker one character too long, a name over the length cap, an over-long
note -- nine refusals reachable from the forms, each telling the user nothing, on fields where the
UI doesn't say what the limit is.

### `lib/format.isThousandsGrouped`
Stripping a repeated separator unchecked turned the typo "1..2" into 12 and "1.23.456" into 123456.
