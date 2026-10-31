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
`pydantic==2.9.2` used to pin `pydantic-core==2.23.4`, built with PyO3 0.22.2, which had no Python
3.14 ABI and shipped no 3.14 wheel: on 3.14 the install failed while compiling, with no fallback.
Measured 2026-10-05 on the owner's machine, whose system interpreter is 3.14.4 and which has no
`pip`, no `ensurepip`, no Docker and no root -- so four tiers and `ruff` failed there together with
`No module named pytest`, every time, on any diff. `.github/workflows/tests.yml` pinned `3.12` for
all three jobs for exactly this reason. How to report a run when the tiers cannot execute is in
`tests/README.md`.

AGE-39 (2026-10-11) bumped `pydantic` to `2.14.0` (`pydantic-core==2.50.0`) as ordinary dependency
maintenance, and that pin does ship a 3.14 wheel -- confirmed by installing it into an isolated
`pip --target` directory on the owner's own Python 3.14.4, with no venv or Docker, and running
`unit`, `integration`, `system` and `ruff` against it there, all green. That removes the one
specific blocker this note described, but the CI pin stays `3.12`: raising the *project's* Python
version is a separate decision (Dockerfiles, `.github/workflows/tests.yml`, and the local-dev
section of `README.md` would all need to move together, per `CLAUDE.md` §3), not something a
dependency bump should do as a side effect. The owner's machine still has no `pip`/`ensurepip` of
its own, so this does not change how `./run-tests.sh` is reported from there -- see
`tests/README.md`.

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

### `tests/e2e/conftest.py` -- `download_browser_page`, `tests/e2e/test_downloads.py`

`test_ui.py` only ever drives Chromium (`chromium_path`), and the one past bug that actually
differed by browser -- `api/client.downloadFile`'s detached `<a>`, ignored by Firefox (see
`frontend` below) -- had no test anywhere, on any browser, until now. Rather than parametrizing
the whole suite over three engines (a 3x slower job for checks that have never once differed by
browser), `download_browser_page` only backs `test_downloads.py`, which drives the two actual
callers of `downloadFile` -- the backup export and the transaction CSV export -- on Firefox and
WebKit. It skips with `pytest.skip` locally and fails with `pytest.fail` on CI when an engine
isn't installed, same reasoning as `chromium_path`'s own comment: a tier that silently doesn't
run is worse than one that's red. Each test asserts on the file Playwright actually received
(`download.path()`'s size and content), not just that the click raised no error -- a regression
in `downloadFile` would otherwise produce a `0`-byte "successful" download and nothing would fail.

### `tests/e2e/conftest.py` -- `_instrumented`

Most browser tests open a page with `goto(..., wait_until="networkidle")` and assert on it right
away. Playwright's networkidle is 500ms with no request in flight, and between the bundle arriving
and the app's first API call -- spent parsing and running the JavaScript -- there can be ~0.5s of
silence: the page counted as idle while still showing "Loading…". The Google Fonts requests the
page used to make filled that gap by accident; once the fonts were bundled (FE-04), four tests
failed one run in two. A second `wait_for_load_state("networkidle")` does not help -- it returns at
once when the state was already reached -- so the wrapper waits for the first `/api/` request and
then for 500ms with nothing in flight, counted from the page's own request events. The same
helper backs both fixtures, which used to set up their recorders in two copies.

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

### `shared/notify.py` (AGE-11, out-of-app alerts)

#### Why e-mail, and why here
A budget going over, a bank consent about to expire, a bank sync that keeps failing: all three
already show in the app, but only to someone who opens it that week. The task asked for a channel
that doesn't contradict CLAUDE.md principle 3 (no cloud service, no telemetry, data stays on the
owner's machine) -- which rules out a hosted push/notification service (Pushover, ntfy.sh's public
instance, a Telegram bot through Telegram's own servers) as the *default*, since every one of them
is a third party the message would have to pass through whether the owner wants that or not.

Plain SMTP, off unless `SMTP_HOST` is set, is the smallest thing that respects that: it sends
through a mail server the owner already chose (their own ISP, a self-hosted Postfix, or yes, a
commercial inbox if that's what they trust) rather than one this project picks for them, and it
costs nothing to add -- `smtplib` is the standard library, no new dependency. The alternative
seriously considered was writing to a file / webhook the owner's own automation could watch, but
that pushes the "get this off my machine" problem onto the owner instead of solving it, and nobody
self-hosting a personal finance app is without *some* mail relay they already use for everything
else on their network.

One module, imported by both core-networth and bank-sync (`shared/`, like `backup_retention.py` --
see above for why that means both Dockerfiles build from the repo root), rather than duplicating
the same six `SMTP_*` variables and the same `smtplib` call twice. `send()` never raises: a
misconfigured or unreachable mail server must cost only that alert, never take down the scheduler
cycle that happens to also run the daily backup and the price refresh. It also deliberately knows
nothing about *what* it's sending or *whether it already sent it* -- that bookkeeping (don't repeat
the same alert every cycle) is each caller's own, next to the data it's deciding about: see
`app/alerts.py` in core-networth and bank-sync below.

#### `send_async`
`send` uses `smtplib`, which blocks the calling thread for as long as the mail server takes to
answer -- up to the 10-second timeout when it is unreachable. Both schedulers call it from
coroutines on the service's only event loop, so a slow or dead mail server froze every request the
service was serving for that long (review finding W-18). `send_async` is `send` run through
`asyncio.to_thread`: same return value, same "off means no connection" rule, and the event loop
keeps serving meanwhile. `send` stays for synchronous code and is what the async variant runs, so
there is one implementation of the actual send.

#### `send` -- `SMTP_USE_SSL`
Only STARTTLS was supported (review point N-11), but many providers accept mail only on port 465
with implicit TLS, where the server expects a TLS handshake as the very first bytes: a plain
`smtplib.SMTP` connection to it just hangs until the timeout. `SMTP_USE_SSL` switches to
`smtplib.SMTP_SSL`, and when it is on `SMTP_USE_TLS` is ignored rather than rejected, since its
default is `true`: issuing STARTTLS inside an already encrypted connection is a protocol error,
and an owner who only set `SMTP_USE_SSL=true` and `SMTP_PORT=465` should get working mail. The
port is not changed automatically: it stays whatever `SMTP_PORT` says.

## core-networth

### `services/core-networth/app/main.py`

AGE-5 (2026-10-06) split this file -- 1,545 lines and 67 endpoints, too much to hold in head at
once -- into `app/helpers.py` (shared lookup/pagination/idempotency helpers) and one
`app/routers/*.py` module per area (portfolios, cash, expenses, budgets, networth, backup),
included from here with `app.include_router`. No endpoint changed path, method, response shape or
status code; `tests/integration/test_api_surface.py` is what proves that. The entries below moved
with their functions; only what stayed app-level (the validation-error handler, `/health`,
`/scheduler/run-now`, CORS, the lifespan task) stays documented here.

#### `_validation_error_handler`
Python's json parser accepts `NaN`/`Infinity` in a request body. Refusing such a value produced
a 422 whose body echoed the value back -- which JSON cannot encode -- so the 422 turned into a 500
while rendering. The refusal was right; only its report failed. The response shape is otherwise
the default handler's.

### `services/core-networth/app/helpers.py`

#### Idempotency (`_commit_with_idempotency`)
Checking for the key and then running the mutation used to be two steps, and two concurrent
replays of one key both passed the check before either committed -- so both ran. That is exactly
the case the header exists for (a client retrying while the original is still in flight).
Measured: 16 simultaneous replays of a single key created three transactions. Committing the key
in the same transaction as the mutation closed it.

A key reused for a *different* endpoint used to run the mutation and only then fail on the key's
primary key: a 500 for an operation that actually went through, which a retry would duplicate.

### `services/core-networth/app/routers/backup.py`

#### `_read_bounded`
Reading the upload whole and *then* checking its length meant the cap protected nothing: a
multi-gigabyte upload was already in memory when rejected, enough to get the process killed on a
small home server.

### `services/core-networth/app/routers/portfolios.py`

#### `delete_portfolio`
Deleting a portfolio cascades to its cash accounts and transactions -- including expenses that a
refund in another portfolio points at. A refund whose target is gone is skipped by
`compute_refund_adjustments`, so without un-linking it first it silently stopped counting as
income while still moving its account's balance. The ids are a subquery rather than bind
parameters because a busy ledger would hand SQLite one parameter per transaction, and how many it
accepts depends on how SQLite was built.

Since portfolios are kept apart, it also deletes the portfolio's own expense categories (with their
budgets), merchant rules and snapshots -- nothing else points at them. Not reachable from the
frontend, which archives instead.

#### `delete_asset`
Deleting only the asset row left its HoldingEntry rows behind with a dangling `asset_id`, which
raised AttributeError in valuation.py (`h.asset` is None) on the next snapshot/growth/XIRR.

Refused (409) while more than one portfolio holds the asset: the Asset Catalogue shows each
portfolio only the assets it holds plus the unheld ones, so a delete from one portfolio's catalogue
would otherwise have emptied a position in a portfolio that page doesn't even show.

#### `list_assets(portfolio_id)`
The catalogue stays one shared table -- an instrument's ticker, prices and geo factsheet are the
same whoever holds it, and duplicating assets per portfolio would have meant duplicating
geo-allocation's files too, a second service. What is per portfolio is the *view*: the assets it
has ever held (any HoldingEntry, so a position sold to zero stays findable) plus those nobody holds
yet, so a newly created asset can still be picked up by whichever portfolio buys it first. An asset
already held elsewhere is not offered: buying the same ETF in a second portfolio means creating it
again there, which prices identically (prices are keyed by ticker). The tag (`Asset.category`)
stays per asset.

### `services/core-networth/app/routers/cash.py`

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

### `services/core-networth/app/routers/expenses.py`

#### `_check_category` (a category of the transaction's own portfolio)
Every report, budget and merchant list filters by portfolio, and categories belong to one. A
transaction tagged with another portfolio's category would count in neither portfolio's
spending-by-category and in neither one's budget, while still moving its balance -- so creating,
editing and bulk-categorizing all refuse it, and so does a merchant rule. Transfers and refunds keep
their own same-portfolio rules (below); a transfer between two portfolios is still allowed, since
each side is a real movement of that portfolio's money and neither is spending.

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
The refunded expenses are read in one query (a subquery, not a list of ids, for SQLite's
bind-parameter cap), not one `db.get` per expense: every report runs this first.

#### `_plan_csv_import`, `CashTransaction.import_fingerprint` (CSV import, AGE-7)
- **Date format is a required input, never inferred.** `01/02/2026` is a valid date read either
  way, and the two readings are a month apart -- wrong in a way that looks completely plausible,
  moves spending into the wrong month, and shifts an XIRR flow's date. The caller (the frontend,
  from what the user confirms the file looks like) says which `strptime` pattern the file uses;
  a date that doesn't match it is discarded with a reason, never parsed a second way as a guess.
- **Currency mismatch is discarded, not converted.** `CashTransaction` has no currency of its own
  -- every amount is already in its account's currency (see the field's docstring) -- so a CSV
  column saying otherwise isn't something to convert at whatever that day's rate was, it's a sign
  the row belongs to a different account, or the mapping is wrong. Silently converting it would
  hide that mismatch behind a plausible-looking number.
- **Duplicate recognition, since the file has no id of its own to key on.** Re-running the same
  import (the file re-exported with a wider date range, say) must not double every transaction it
  already added. `import_fingerprint` hashes the fields that identify "the same bank line" --
  account, date, direction, amount, counterparty/note -- with a trailing `#1`, `#2`... for
  genuinely repeated same-day transactions (two identical vending-machine purchases) that a plain
  hash of those fields can't tell apart; the same unstable-id-plus-occurrence-count approach
  `bank-sync/app/sync.py`'s `_external_id`/`fallback_seen` uses for the same reason, independently
  here since CSV import has no external transaction id to start from at all.
- **The uniqueness is also enforced at the database layer** (see migrate.py's `_EXTRA_INDEXES`),
  not just checked before inserting: two imports of the same file racing each other (a frontend
  double-submit; the preview being confirmed twice) could otherwise both pass the pre-check before
  either commits. The partial unique index on `(account_id, import_fingerprint)` turns the loser's
  insert into an `IntegrityError` -- which rolls back its whole commit, so nothing lands half
  imported -- instead of a silent duplicate. A client retrying the exact same request (not a fresh
  double-submit) should instead reuse its `Idempotency-Key`, same as every other mutating POST.
- **Movements logged another way count as already present.** The fingerprint only knows rows a
  CSV import wrote. A statement re-covering days bank-sync had captured (or the user had logged)
  matched none of them and was offered in full, doubling those movements in the balance -- found
  by the 2026-10-25 audit, not by a user. Bank-sync names counterparties differently from a bank's
  CSV export and notes differ too, so the match is date + direction + amount only, counted: each
  existing non-imported transaction absorbs at most one statement line, so two identical
  purchases on the same day still need two existing rows before both are skipped. A bank-sync
  booking date that differs from the statement's date by a day is not matched -- that line is
  shown as "to import" in the preview, where the user can still see it.
- **The losing side of a race answers 409, not 500.** The unique index above makes the second
  commit fail with `IntegrityError`; `_commit_with_idempotency` re-raises one that isn't about
  the idempotency key, so `commit_transaction_import` turns it into a sentence. The integration
  fixture `db_engine` used to build its database with `create_all()` only, so this index -- added
  by `migrate.py`'s `_EXTRA_INDEXES` -- was absent from every integration test until it ran the
  migrations too.

### `services/core-networth/app/routers/networth.py`

#### No all-portfolios endpoints
Requested 2026-10-29: creating a second portfolio made the Summary, the snapshots, the budgets
and every expense report add the two together, when each portfolio is meant to be a world of its
own. The `/networth/combined*` endpoints (totals, history, growth, XIRR, intraday) and the gateway's
`/api/dashboard/summary` were removed rather than kept behind an "All portfolios" option: nothing in
the app asks for a sum any more, and their conversion logic (each portfolio converted at that day's
rate into a requested currency -- the bug behind their own history, see the CHANGELOG) was the most
delicate code in the file to keep alive for no caller. The expense reports (`/expenses/summary`,
`/expenses/monthly`, `/recurring`, `/budgets/progress`) take a required `portfolio_id` for the
same reason; `/transactions` keeps it optional, since an `account_id` alone already scopes it.

#### `portfolio_intraday(for_date)`
`for_date` was a string parsed with strptime, so `?for_date=nope` answered 500. Typing it as a
`date` lets FastAPI answer 422, like every other date parameter.

#### `take_networth_snapshot`
Overwriting a scheduler-made row kept `source="auto"`, so the table said the number came from the
month-end job when it didn't.

A snapshot is one portfolio's, always in its base currency (there is no currency to choose: the
old `{"currency": "EUR"}` body converted a sum of portfolios into it). The list returns every
currency of the portfolio, because a snapshot keeps the currency it was frozen in if the base
currency changes later; the Historical Net Worth chart plots only the current base currency's.

#### `take_networth_snapshot`, `scheduler.catch_up_monthly_snapshots` (`valuation.why_snapshot_cannot_be_frozen`)
Both froze whatever the combined totals of the time returned, including a holding counted as zero
for want of a price and an amount converted 1:1 for want of a rate. Everywhere else those are
transient and flagged; in a snapshot they are permanent and unflagged. The 2026-07-21 historical
fallback (today's price when a past day's close fails) made it less likely, not impossible: a
price-feed outage across a month-end still froze the month without its holdings. A month that
can't be valued completely is now postponed (the catch-up's "is this month missing?" check already
retries it every cycle), and a hand-taken one is refused with what is missing.

### `services/core-networth/app/valuation.py`

#### `AccountLedger.balance` (the opening balance plus what came after it)
- Same-day handling: a strict `entry_date > anchor date` silently dropped a transaction logged the
  same day as the opening balance -- the common case of creating an account and logging its first
  movement. `created_at` is nullable on both tables (rows from before the column existed), and
  missing data fails open: excluding same-day transactions is the exact bug the rule exists to
  avoid.
- Summed in SQL, then in memory: the first, row-by-row version loaded every transaction from the
  opening balance up to each chart point, so the work grew with the square of the history (a
  transaction's date is itself a chart point). Five years of daily expenses meant 1.7 million ORM
  rows per chart: 25s for `/history`, 33s for the since-removed `/networth/combined`, past the
  gateway's 30s timeout. Summing in SQL fixed the rows, not the queries -- see `PortfolioLedger`.
- Running sums are `Fraction`s of the stored floats, so a balance is the exact sum of what moved it,
  rounded once: a float running total would give a balance whose last digits depend on how many
  transactions came before it.

#### `PortfolioLedger` (one read, every date in memory)
Measured 2026-10-29 on a portfolio of 6 ETFs, a house, 5 accounts and 4 years of daily expenses
(3,705 transactions), prices already cached and no network latency at all: `/history` took 24s and
27,763 queries, `/xirr` 7s, the portfolio page 32s -- over the gateway's 30-second timeout as soon
as the real network is added. Each chart day re-ran the whole valuation: the holdings query, two
queries per account, ORM objects built for every row (72,000 per chart). SQLite itself was ~2s of
it; indexes alone saved 15%. Reading the same rows once (5 queries) and answering every date in
memory: `/history` 0.26s, `/xirr` 0.1-0.2s, the page 0.6s.

The per-date valuation code is unchanged (`compute_portfolio_snapshot` with a `ledger`); only
where it reads from is new. The two rules that pick a row -- the holding entry in force on a date,
the balance entry that anchors it -- keep the old queries' `ORDER BY` and take the first row in the
database's order, so rows equal on date and `created_at` (two pre-`created_at` rows on one day)
are still told apart as before: SQLite returns them oldest-inserted first, which a Python sort of
its own would not have reproduced. `tests/integration/test_ledger_equivalence.py` keeps the old
queries verbatim as the definition and compares every day of random ledgers; it caught that tie.
A note for whoever extends it: SQLAlchemy writes a column's default in place of a `None` given to
a model's constructor, so rows with no `created_at` have to be set to NULL after the insert -- the
first version of the test generated none and passed against a ledger that got them wrong.

#### `warm_prices`, `price_client.prefetch_closes`
The same chart asked price-feed for each ticker's (and each currency pair's) close on each day,
one request at a time, and price-feed asked Yahoo: after a restart (both caches are in memory) two
years of history were 5,110 Yahoo round trips, four years 10,227. Each ticker and pair is now
fetched once as a series (`/series`) covering every day asked for, and each day's answer is
derived exactly as `/on-date` derives it -- the last close in the ten days up to it -- and cached
under the same key `get_price_on_date` reads. A day with no close in that window is cached as
"none" for a minute only, enough for the valuation in progress not to ask for it day by day; a
ticker whose series can't be fetched (an older price-feed, Yahoo down) is simply left to the
day-by-day path, so the result never depends on the series being there.
`compute_asset_growth` (the asset page) does the same for its five period starts.

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

#### `ExpenseCategory.portfolio_id`, `MerchantRule.portfolio_id`, `NetWorthSnapshot.portfolio_id`
Each portfolio is kept apart (2026-10-29): its categories, merchant rules, budgets and snapshots
are its own, so a second portfolio's spending never lands in the first one's budget and a rule
written for one never categorizes the other's transactions. `Budget` has no column of its own: it
belongs to its category's portfolio, so the two can never disagree. The columns are nullable only
because `migrate.py` adds them to existing tables (and hands out the old rows, see there); every
write through the API sets them. `merchant_rules`' unique constraint now includes the portfolio,
since two portfolios may each map the same merchant.

#### `HoldingEntry.created_at` / `CashBalanceEntry.created_at`
Without a tie-breaker, "which edit wins" for two entries on the same `entry_date` was whatever
order SQLite returned them in: a second same-day balance update could appear not to have "taken"
even though it was saved.

#### `CashAccount.archived_at`
Deleting an account outright used to erase its contribution from every past date too, producing
a fake overnight swing the day it was removed (or re-added). Rows archived before local time was
settled on hold a UTC moment, so on a server not running UTC their date can be a day out --
harmless on the default Docker image, which is UTC.

### `services/core-networth/app/migrate.py`

#### `_EXTRA_INDEXES` (lookup indexes)
No table had an index beyond its primary key, so every per-account or per-portfolio query scanned
the table. They were worth 15% of the history chart while it ran thousands of queries; with the
ledger they keep its few reads, and the reports' date-range joins, from growing with the database.
Declared only here, not on the models, so a new database and an existing one get the very same
statements.

#### `_rebuild_merchant_rules`
SQLite cannot alter a table constraint, and the old `UNIQUE (pattern, match_type)` would have made
two portfolios mapping the same merchant impossible -- including the copies the migration below
makes. The table is renamed, created again from the model and refilled with every column both
versions have, inside the same transaction as the rest of the migration. It recognises an old table
by the constraint itself, so it runs once on a live database and once on every older backup restored.

#### `_give_shared_rows_to_portfolios`
Data from before categories, rules and snapshots belonged to a portfolio. Compatibility code in the
CLAUDE.md sense: it is a no-op on a migrated database, and is kept for as long as a backup from
before 2026-10-29 may be restored. The choices:

- **A category goes to every portfolio whose transactions use it**, so each one's spending by
  category, and its budget, read exactly as before. The oldest of them keeps the original row and
  id; each other one gets a copy, with copies of its budget and merchant rules, and has its own
  transactions moved onto the copy. Keeping the id for one portfolio means a `category_id` stored
  elsewhere -- bank-sync's record of what it captured -- still names a real category. For the
  others, bank-sync's "has the user changed the category since?" check sees a different id and
  leaves the category alone when a pending payment settles: the conservative side.
- **A category no transaction uses goes to every portfolio**: it is setup the user made, and there
  is no telling for which portfolio. An ignored-merchant rule (no category) likewise.
- **A snapshot summed every active portfolio.** It goes to the one portfolio that held anything on
  or before its date (any holding, balance or transaction entry) -- every snapshot of a database
  with a single portfolio, and every one taken before a second portfolio had any data. When several
  did, the sum cannot be split honestly; it keeps `portfolio_id` NULL, stays in the database and in
  backups, and is never shown. Archived portfolios count as holders too: when one was archived is
  not recorded, so it may still have been in the sum.
- **With no portfolio at all**, nothing is handed out, and the next startup after one is created
  does it.

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

### `services/core-networth/app/reports.py`

#### `flows` (the account's currency)
Each transaction's account was looked up with `db.get` -- free while the session still held the
account, but the session holds an object only while something else does, so on a busy ledger it
was a query per transaction: 1,165 for an all-time summary of two years, 575 for the monthly view.
The portfolio's account currencies are read once instead. `tests/integration/test_query_counts.py`
pins that the query count of every heavy endpoint stays the same on ten times the data.

### `services/core-networth/app/price_client.py`

#### Past closes are not stored on disk
Considered for the restart case (2026-10-29) and left out. A cold start now costs one `/series`
request per ticker and currency pair, run concurrently -- seconds once, against the 10,000 one-day
requests it replaced. Storing them would save those seconds and freeze a number that Yahoo does
revise: `history()` returns closes adjusted for dividends and splits, so a distributing ETF's past
closes all move when it next pays out. Kept in memory, they are re-read on every restart and every
series of one request shares one adjustment; stored, a chart would mix closes adjusted at
different times, with nothing on screen to say so.

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

#### No WAL journal
Considered with the speed work (2026-10-29) and left out: one user, short transactions, and every
heavy read now a handful of queries, so readers waiting on a writer is not where time goes. WAL
would put part of the live database in a `-wal` file next to it, and restore (`backup.restore_db`)
replaces `networth.db` alone -- a leftover `-wal` from the replaced database would then be applied
to the restored one.

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

#### `catch_up_monthly_snapshots`
One pass per active portfolio, each in its own base currency and starting from its own first
entry: a portfolio created this month gets no month-ends from before it existed, and an archived
one gets none at all, as it was left out of the sums before.

#### `scheduler_loop`
Without the catch-all, an error before a job's own `try` (opening a session against a database
whose file has gone away, say) ended the background task for good: nothing surfaced, the API kept
serving, and month-end snapshots and daily backups stopped until someone went looking for a backup
that was never taken.

### `services/core-networth/app/alerts.py` (AGE-11)

#### `check_budgets_over`
Runs once per active portfolio, since budgets are per portfolio; the e-mail names the portfolio as
well as the category (still no figure). An archived portfolio's budgets stay quiet.

Reuses `routers.budgets.budget_progress` rather than a second "how much has this category spent"
query -- the two used to disagree once, before budgets existed in their current form, on whether a
refund counted against the limit, and there is only one such calculation left on purpose now (see
`reports.flows`). Calling it directly as a plain function (not through FastAPI) means passing
`month=None` explicitly rather than leaving the parameter at its declared default -- that default is
a `Query(...)` object, meaningful only when FastAPI itself supplies it from the request; left in
place here it would be compared against a string in `budget_progress`'s own body and never equal
`None`.

`Budget.over_alerted_month` (the dedupe key, a plain "YYYY-MM" string) is deliberately never reset
to null when the budget stops being over, or when the month turns. Comparing it against *today's*
month string is enough on its own: last month's value simply stops matching as soon as the
calendar does, so next month's first overspend alerts again with nothing to clean up, and a
clean-then-over-again month also alerts (a different month string) even if nobody looked at the
alert meanwhile.

## bank-sync

### `backup.py`
bank-sync's database (SyncedTransaction, what stops a sync from capturing the same transaction
twice) was in no backup at all until it joined the gateway's combined backup.

#### `undo_restore` (BS-06)
The gateway's combined restore replaces core-networth, geo-allocation and bank-sync one after the
other; one failing after bank-sync's part left the services out of step, and the only way back was
copying `pre-restore-<timestamp>/bank_sync.db` by hand. `restore` now names the safety copy it made
(`pre_restore`, None when there was no database to copy) and `undo_restore` swaps it back in with
the same validation, swap and migrations (`_staged`, `_swap_in`), under the same `_sync_lock`, and
re-reads `links.yaml` as a restore does.

It makes no safety copy of its own. What it replaces is the archive just restored, which the caller
still holds; a `pre-restore-*` copy would become the newest entry in place of the one being undone,
and a `pre-undo-*` one would be a folder rotation never removes. The name is checked against
`shared.backup_retention.PRE_RESTORE_RE` and then resolved under each place `backup_target` may have
written it (`BACKUP_DIR`, or `DATA_DIR/backups` when that was not writable) with `is_relative_to`,
so nothing outside a safety copy can be swapped in.

### `sync._usable_date`
Both guarantees were learned the hard way. Core rejected the transaction, it was never marked
synced, the watermark never advanced past it, and the link silently stopped capturing anything
new: once because the bank's raw date string was sent as-is (a local format, or an object), once
because a scheduled/pending payment was dated in the future.

### `sync._sync_link_locked` -- idempotency keys and per-transaction commits (`_record`, `_idempotency_key`)
Until BS-02 (review finding W-17) every push went out without an `Idempotency-Key` and the
SyncedTransaction rows were committed once, at the end of the cycle. Two ways to get a duplicate in
core: a push that core applied but whose answer never arrived (a timeout) was counted as failed and
pushed again next cycle; and a restart or crash between a push and the final commit lost every row
of the cycle, so the next one pushed them all again. Each row is now committed as soon as core has
its effect, and the key makes the retry of a push whose answer was lost a replay.

The key is `bank-sync:<dedupe_key>`, stable across cycles. A VOIDED transaction that comes back is
the one case where the stable key is wrong: its first core transaction was deleted, and replaying
the first push (core keeps keys for 24 hours, so a hold released and re-presented the same day
would hit it) would record the deleted id and create nothing. It gets a key of its own,
`...:after-void:<created_at of the voided row>`, and that row is deleted only in the commit that
records its successor (`_record`): deleting it up front, as before, let the commit of any later
transaction in the same cycle take the deletion with it after a failed recapture, and the retry
then fell back to the first key.

The retry window is bounded by core's `IDEMPOTENCY_TTL_HOURS` (24): a failed push is retried on
the next cycle, so `SYNC_INTERVAL_HOURS` must stay below 24 for the replay to still be there. A
409 "still being processed" is an ordinary failed push, retried next cycle.

### `sync._mark_skipped`
Without it, skipped transactions (zero amount, no direction, unreadable amount) stayed unknown:
every cycle they passed the dedupe check again and were appended to the audit CSV once more --
one duplicate row per transaction per cycle.

### `main.py` -- two surfaces (`public_app`, `internal_app`) and `serve.py`
bank-sync's port has to be published on the host: the browser opens the status page there, and each
bank's login redirects the browser back to its `/callback`. Until BS-01 (review finding W-11) that
one port also served, with no authentication, the whole backup API (`/backup/export` handed out the
database, `/backup/restore` replaced it), the raw audit CSV of every bank transaction, the helpers
(every portfolio and cash account id) and `GET /sync-now`, a GET with side effects any page could
trigger with an `<img>` tag. The gateway's `API_KEY` did not cover any of it, since the gateway was
not in the path.

Why two apps in one process rather than the alternatives (decision D-01):
- *An API key on bank-sync's own routes* leaves everything open with an empty `API_KEY`, which is
  the default, and asks the owner to configure a second secret for a service only the gateway
  should be talking to.
- *Two processes or containers* would need the database, `_sync_lock` (a restore must not race a
  sync cycle) and `_auth_states` (the pending authorizations `/authorize` issues and `/callback`
  consumes) shared across processes. In one process they are just module globals.

So `main.py` builds two FastAPI apps on the same modules and `serve.py` runs one `uvicorn.Server`
for each with `asyncio.gather`. The startup work (reconciling `links.yaml`, starting the scheduler)
moved out of the lifespan and into `serve.main`: a lifespan on both apps would run it twice, and
two schedulers would sync every link twice per cycle. Shutdown needs nothing of its own: each
uvicorn server, when it stops on a signal, restores the handler installed before it and re-raises
the signal, so SIGTERM stops the second server, then the first (measured: both are down in under
half a second). `/health` is on both, so the gateway's aggregated health check and the browser can
each check the port they use. `/sync-now` became a POST on the internal app, and the status page
no longer links it or the audit CSV, since neither is reachable from the browser any more.

### `clients.py` and `enable_banking._private_key` (BS-04)
Until BS-04 (review finding W-27) every call built its own `httpx.AsyncClient` -- a new connection
for each pushed transaction, each `/cash-transactions` lookup, each page of bank transactions --
and every Enable Banking request read the PEM file again to sign its JWT. The clients are now
shared, one per event loop and held weakly by the loop object, the same rule as core-networth's
`price_client._clients` (see its entry for why not `id(loop)`). Creating them once in `serve.main`
was the alternative: it would leave every caller outside the running service (the unit tests, each
on its own loop) without a client, or with one bound to a loop that is gone. `serve.main` only
closes them at shutdown. Tests inject a fake core or bank by replacing `httpx.AsyncClient` with a
factory that adds an `httpx.MockTransport`, as `test_bank_sync_idempotency` does.

The key is cached with the file's `st_mtime_ns`: a key file replaced on disk takes effect on the
next request, as it did when the file was read every time, without a restart.

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
- Categories belong to a portfolio (2026-10-29), so the resolver is built per link, for the
  `portfolio_id` of its links.yaml entry. A cycle with several links fetches the categories once
  per link rather than once per cycle -- a few requests, against a lookup per transaction before
  the resolver existed. A links.yaml whose `portfolio_id` isn't the account's own portfolio finds
  the wrong portfolio's categories: core-networth refuses such a category on that account
  (`_check_category`), so an MCC-categorized transaction fails to push and is retried every cycle,
  showing as a failing sync, rather than being captured with a category no report would count.

### `csv_log.log_transaction`
Reading every row back just to learn the header happened on every logged transaction: the cost
grew with the whole log, and the entire audit trail sat in memory each time. The header-widening
rewrite streams the file for the same reason: a file can be up to `AUDIT_LOG_MAX_BYTES`.

### `csv_log` -- a rotating log, outside the backups (BS-03, decision D-03)
Review finding W-12: `transactions_log.csv` held every bank JSON in clear text, grew forever and
went into every backup -- the daily copies, the pre-restore copies, the zip downloaded from
Settings -- so the most sensitive data the app holds was also its most copied. The review proposed
masking account identifiers plus a time-based retention; the owner chose otherwise: the log stays
complete and in clear text, because it never leaves the machine, and is bounded per file rather
than in time -- a numbered series in `DATA_DIR/audit-log/`, each file closed at
`AUDIT_LOG_MAX_MB` (100), compressed to `.zip` (standard library, opens anywhere) and kept.

- `_close` writes the zip completely before deleting the CSV. An interruption leaves both; a
  number with both is a closing to finish, so the next call compresses it again and moves on.
- The pre-BS-03 `DATA_DIR/transactions_log.csv` is moved into the series as its next number on the
  first write after the upgrade (`current_log` reads it until then, so the download endpoint still
  works). This is the compatibility code: it can go once no installation has that file.
- An archive from before BS-03 still carries `transactions_log.csv`; `backup.restore` ignores it
  (it stays in that archive), so a restore never touches the log -- the owner's choice.

### `links_config.load_links_config`
Treating "unreadable file" like "empty file" made a bind-mount glitch look like the user had
deleted every bank: every link was flipped to REMOVED and syncing silently stopped.

### `app/alerts.py` (AGE-11)

#### `check_consent_expiry`
The dedupe key is `consent_warned_until`, set to the exact `valid_until` an "expiring soon" e-mail
was sent for, rather than a boolean cleared on re-authorization. `main.callback` is what sets a new
`valid_until` on re-authorization, and making this check depend on that staying in sync (clearing a
"warned" flag there too) would be one more thing a future change to the callback could forget.
Comparing the two datetimes directly needs nothing from the callback at all: a fresh, later
`valid_until` is automatically unequal to whatever was warned about before, so it's treated as
unwarned-about the moment it's set, with no reset step to miss.

The margin (`CONSENT_WARNING_DAYS`, 7) matches the in-app banner's own threshold
(`services/bank-sync/README.md` "Day to day") on purpose -- two different numbers for "about to
expire" would have the e-mail and the status page disagree about how urgent the same link is.

#### `note_sync_result`
A single failed cycle is not "repeating": `sync.py` already re-fetches a failed transaction's date
range on the next cycle on its own (see `sync._sync_link_locked`, "advance the watermark"), so one
bad cycle is the retry mechanism working, not a problem worth an e-mail about. `SYNC_FAILURE_ALERT_STREAK`
(3 consecutive cycles) is what separates "the bank's API hiccuped once" from "something is actually
stuck" without hardcoding a duration -- at the default `SYNC_INTERVAL_HOURS` (6) that's 18 hours,
long enough that a single rate limit or timeout never alerts, short enough that the owner still
finds out well before a week goes by unopened. `sync_failure_streak` and `sync_error_alerted` both
reset the moment a cycle succeeds, so a link that recovers and later breaks again gets a fresh
alert rather than staying silent forever after the first one.

## geo-allocation

### Country names and regions
- `country_names`: countries `regions.py` mapped had no display name, so the by-country chart
  showed the bare ISO code ("LU"), which made real exposure look like an unidentified leftover.
- `regions`: several European/Asian countries `normalize_country` recognizes had no region, so a
  fund's exposure to them (Luxembourg money-market holdings, Malta, Ukraine bonds...) fell into
  "Other / Unclassified". Namibia ("NA") likewise, after `countries.py` had been fixed to stop
  reading it as a missing value -- which had moved real exposure into "Other".
- `countries.normalize_country`'s bare-code fallback ("already a valid ISO alpha-2 code?") used to
  accept *any* two ASCII letters, not just ones this app actually names and regions. A typo, or a
  territory this app doesn't cover, sailed straight through as "a recognized country" -- counted in
  `total_weight()` as if fully classified -- and then fell into "Other / Unclassified" at the
  region-grouping step with nothing to tell it apart from real cash: the exact silent failure the
  two bugs above describe, just reached through a third path neither of them closed. The fallback
  now only accepts a bare code already present in `_COUNTRY_TO_ISO2.values()`; anything else is
  reported in `AllocationResult.unmapped_labels` like any other unrecognized label, which lowers
  `covered_weight_pct` and surfaces in the existing "Partial coverage" banner instead of disappearing.
  Covered by `test_a_bare_unknown_code_is_reported_rather_than_accepted_as_a_country`
  (`tests/unit/test_geo_parsers.py`).
- Country coverage across `countries._COUNTRY_TO_ISO2`, `regions.COUNTRY_TO_REGION`,
  `country_names.COUNTRY_NAMES` and the frontend's `isoNumericCodes.ts` crosswalk was extended with
  ~28 more real countries and common offshore fund domiciles (Uruguay, Ecuador, Panama, Costa Rica,
  Dominican Republic, Bahamas, Bermuda, Cayman Islands, British Virgin Islands, Puerto Rico,
  Montenegro, North Macedonia, Bosnia and Herzegovina, Albania, Moldova, Gibraltar, Jersey,
  Guernsey, Isle of Man, Sri Lanka, Macau, Mongolia, Mauritius, Tunisia, Ivory Coast, Senegal,
  Ghana, Botswana) -- the same class of gap as the two bugs above, closed proactively rather than
  waited out one real upload at a time. `tests/unit/test_geo_country_tables.py` only checks that
  the four tables agree with each other, not that any particular country is in them, so a future
  addition still needs to touch all four or that test (not this one) will catch the drift.

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

#### `/series`
Every daily close of a ticker over a span, in one Yahoo request, for core-networth's
`prefetch_closes` (see there for the 10,227 round trips it replaces). It reads the same `history()`
rows `/on-date` picks from, with the same unusable rows dropped and the same refusal of an unknown
quotation currency, so a close read out of it is the one `/on-date` would have answered.

#### `_ticker_currency`
The "USD" guess made when Yahoo's lookup failed used to be cached forever: one rate-limited reply
silently relabelled a Milan-listed EUR holding as USD for the life of the process -- and the
permanent `_historical_cache` entries built from it kept it so. Core then converted a price that
was never in dollars, wrong by the EUR/USD rate with nothing on screen to suggest it.

Keeping the guess for 15 minutes only did not fix that: `_fetch_price_on_date` put the guessed
currency into a past day's payload, and that payload is cached forever both here and in
core-networth's `price_client`. So there is no guess at all any more -- an unknown currency is
None, and every caller answers "no price", which core-networth shows as an unpriced holding.

#### `_fetch_ticker_price`
Its "primary" path read `fast_info.get("last_price")`; yfinance's `FastInfo.get()` only answers
its public camelCase keys (`lastPrice`), so the path never ran and every price came from the
5-day history fallback. The contract tests didn't notice because their `fast_info` double was an
attribute object that answered `last_price` too -- the double now mirrors the real `.get()`.
Correcting the key was not the fix: `last_price` is the last close of a full year of daily
history (a heavier download for the same number), so the history read that had been producing
every price is now the only path.

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

#### `proxy` (dropped `Content-Disposition`)
The function rebuilt the response it sent back from the upstream reply using only
`status_code`, `content` and `content-type` -- every other upstream header, `Content-Disposition`
included, was silently discarded. core-networth's transactions CSV export names its file
correctly (`transactions-<date>.csv`), but that name never survived the trip through this proxy:
the browser always saw the fallback filename from `frontend/src/api/client.ts`. Found alongside
the `CORSMiddleware` bug below (AGE-48) -- fixing CORS alone was not enough for this one route,
since the header was gone before CORS ever got a chance to expose it.

#### `CORSMiddleware` (`expose_headers`)
Configured with no `expose_headers`, so Starlette's default (`()`) applied: `Content-Disposition`
is not one of the handful of response headers a cross-origin `fetch()` can read without it being
explicitly exposed. Frontend and gateway sit on different ports by design
(`docker-compose.yml`: `4173` vs `8080`), so every browser request is cross-origin in practice,
not just under test. `downloadFile` in `frontend/src/api/client.ts` always read `null` from
`response.headers.get("Content-Disposition")` and fell back to its static filename: every backup
download was named `networth-suite-backup.zip` regardless of date, silently overwriting the
previous one, and every CSV export `transactions.csv`. Caught by AGE-10's new e2e download tier,
failing on Firefox and WebKit first only because no earlier test had ever checked a downloaded
filename -- Chromium was equally affected. `expose_headers=["Content-Disposition"]` fixes it;
covered by `tests/system/test_gateway.py`, which sends a real cross-origin `Origin` header.

## frontend

### `index.css` `.card` / `.glass` / `.app-frame`
The frosted blur and the translucent fill sit on a `::before` layer, not on the element. With
`backdrop-filter` on the element itself, every card becomes the containing block of its
`position: fixed` descendants, and `InfoTooltip` -- which positions its panel in viewport
coordinates from inside cards -- would open offset by the card's own position, often off-screen.
`isolation: isolate` keeps the `z-index: -1` layer inside the card instead of behind the page.

### `main.tsx` fonts
Inter and IBM Plex Mono came from Google Fonts in `index.html`, so every page load told Google
the app was in use, and the browser tier had to ignore failed requests to fonts.googleapis.com
when offline (W-13). They are bundled from `@fontsource` now, one import per weight in use. Each
weight's CSS declares every subset (Latin, Latin Extended, Cyrillic, Greek, Vietnamese) with its
`unicode-range`, so the browser downloads only the subsets a page's text needs; importing Latin
alone would have made a merchant name in, say, Polish fall back to a system font letter by letter.

### `chartHelpers.pointsInRange`
`new Date(p.date) >= cutoff` parsed the bare date as UTC midnight against a local cutoff carrying
the time of day, so the boundary day fell in or out depending on the viewer's timezone and the
hour -- "Week" showed six days east of UTC, eight west of it. Comparing "YYYY-MM-DD" strings fixed
it. Moved here from `RangeAreaChart` when the Summary's period sparklines needed the same window;
the unit test pins the late-evening-west-of-UTC case.

### `context/PortfolioContext` (one portfolio at a time)
Every page used to keep its own picker -- or none, and show a sum of every portfolio. One selection
for the whole app, in the top bar, is what makes "each portfolio sees only its own data" hold on
every tab at once. `RequirePortfolio` keys its children on the portfolio id, so picking another
portfolio mounts the page afresh: no list, half-filled form or late response of the previous
portfolio can be shown under the new one's name -- the stale-response bug every page with a picker
had to guard against separately (see `useLatestFetch`). The choice is kept in localStorage, a
per-viewer convenience; a stored id that is no longer an active portfolio (archived, or a backup
restored without it) falls back to the first one rather than to an empty page. Opening a
portfolio's page selects it, and switching while on one opens the newly picked portfolio's page,
so the detail page and the rest of the app never show two different portfolios.

### `Dashboard` invested share
The gauge divides invested by invested + other only when both are non-negative: an overdrawn
account would otherwise push the invested share past 100%, a plausible-looking but meaningless
figure.

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

### `Dashboard` -> `NetWorthChart fetchIntraday`
A fresh arrow function every render made useIntradayData re-fetch and flash "Loading hourly
prices…" on every unrelated re-render while on "Day". Memoized on the portfolio id, as on the
portfolio page.

### `Assets` search
A separate mount effect alongside the debounced one fired the first request twice, 300ms apart.

### `ExpenseHistory` (archived accounts)
Without them, rows showed "—" for the account and fell back to EUR formatting: an archived dollar
account's spending was shown, with no warning, as euros.

### `api/client.downloadFile`
"Download full backup" produced nothing on some browsers: a detached `<a>` is ignored by Firefox,
and revoking the URL immediately could pull the blob from under the queued download. It also
401'd whenever the gateway had an API_KEY, being the only call not sending it.

### `AddPositionForm`
An unreadable manual price became NaN, which JSON.stringify writes as null, so a manually-valued
asset (a house, an unlisted fund) was created worth nothing, the typed figure gone and no error
shown.

### `BalanceSection`
- Every write ran with no catch -- a rejected request left the promise unhandled, the row stuck
  in edit mode, and nothing on screen. An unparseable balance returned silently, so "Save" did
  nothing. `parseLocaleFloat(unitValue) || 0` turned a blank unit value into a voucher account
  worth €0.
- Account details (name/currency/tag) couldn't be changed after creation at all; delete +
  recreate lost the whole balance history.
- Positions are not listed here. From 2026-09-17 the Emergency Fund section also showed the
  positions tagged Emergency Fund, in a second table under its balances, and offered to add one;
  the same position then appeared twice on the page, once under Positions. Removed on request
  (2026-10-29): every position that isn't a cash-like balance is listed, and added, under Positions
  only, with its tag; the Emergency Fund total of the allocation still counts it, by the tag.
- An account tagged Stock or Bond -- both offered by the Tag picker -- counted in the totals but
  matched none of the three sections' filters, so it was listed nowhere and could be neither
  edited nor removed (W-31). `PortfolioDetail` gives it an "Other balances" section, filled by
  exclusion (every tag no other section covers) so a tag added later cannot fall through the same
  way, and shown only when it has an account. Its balance is not hand-updated: the Expenses log
  posts to every account except Pension Fund ones, so Transactions own it as they do Cash's.

### `lib/refunds.refundCandidates`
The refund picker's list was built inside the form's render by filtering the portfolio's whole
transaction list once per expense: quadratic, about 13 million steps for 3,700 transactions, and
run again on every keystroke anywhere in the form. It is one pass over the list now (refunds
summed into a map first, in the same order, so every remaining amount is the same float) and the
form memoizes it on the list. The whole list is still fetched, once when the Log opens and after
each change: ~0.2s for 3,700 rows, the price of keeping the picker's "already refunded" figures
computed from the same rows the backend nets.

### `PortfolioDetail` reload after an edit
Every add, edit or remove on the page reloads its figures; the reload used to set the page-wide
loading state, so the whole page was replaced by "Loading portfolio…" each time. It now does so
only when the portfolio on screen is a different one (first load, or another portfolio opened).
A single "overview" endpoint returning the snapshot, history, growth and XIRR together was
considered with the 2026-10-29 speed work and not built: once each of them reads the portfolio
once (see `PortfolioLedger`), the four requests cost ~0.5s together on four years of data, and
merging them would have traded four small, separately tested endpoints for ~0.1s.

### `TransactionLogForm`
- Refund picker resolved against active accounts only: an expense on a removed account showed a
  blank account name and defaulted to EUR, so the dropdown said to enter euros for what the server
  then rejected as "this expense is in USD".
- Switching portfolio mid-pick left a stale refund target queued to submit while the dropdown
  showed nothing selected. The portfolio is no longer picked here: switching it in the top bar
  remounts the whole page (see `PortfolioContext`), and the pick with it.
- Deleting an expense (or one of its refunds) -- in `TransactionList` -- left the refund picker
  here offering amounts computed from a transaction that no longer existed, until the parent
  page's `onTransactionsChanged` refresh came back; `AGE-9` split the single `Transactions.tsx`
  this used to be into this form and `TransactionList`, wiring that refresh as an explicit prop
  instead of a shared closure.
- Dividend/coupon/interest income (AGE-19, frontend half of AGE-3): `TransactionList`'s row
  replaces the Category cell with a short "◆ Dividend/Coupon/Interest" tag, the same slot a
  transfer or a refund already take over, rather than adding a column -- the list is already dense
  and a transaction with `investment_income_kind` set is rare enough that losing the category
  label there (it can still carry one; the backend doesn't forbid it) costs less than a wider
  table. `canMarkInvestmentIncome` (`lib/investmentIncome.ts`) mirrors the backend's
  `_validate_investment_income` (only an INCOME, never a refund) so the picker in both this form
  and `TransactionEditors.EditTransactionForm` only ever offers a combination the server accepts.
- A refund is logged on an account in the refunded expense's currency: the backend refuses any
  other (400, refunds aren't converted). The form's hint once said the opposite -- "enter the
  amount in USD, even when logged against a different-currency account" -- so the user typed the
  figure, submitted, and got the refusal (W-33). Picking an expense now limits the account picker
  to accounts in its currency and moves the selection to the first of them; with none left active,
  the picker says so and the submit is refused before reaching the server.

### `TransactionImport` (AGE-36 -- the UI for AGE-7's import endpoints)
- **The date format and the decimal separator both start unselected, with no preselected option.**
  The backend never guesses either one (see `_plan_csv_import` above) precisely because a wrong
  guess looks like a plausible date or amount instead of an obvious error; a frontend that
  defaulted the `<select>` to "DD/MM/YYYY" or "." would reintroduce exactly that silent guess one
  layer up, just before the user's own choice would have caught it. The "Preview import" button
  stays disabled until both (and the required date/amount columns) are picked.
- **There is no path from a chosen file to a write that skips `/import/preview`.** The "Import N
  transactions" button only exists once a preview response is in state, built from the exact same
  request body `/import` would then receive -- so what a confirm writes is never something the
  user has not already seen reported row by row.
- **The file's header row is split client-side only to populate the column pickers**, not to parse
  any data row -- that stays the server's job (`csv.DictReader`), which already handles quoting
  the simple `split(delimiter)` here does not try to. A wrong guess here just shows an unhelpful
  column list, which the user notices immediately when nothing in the dropdowns looks like their
  file's actual headers.
- **The whole flow is keyed on the account id** (see `Transactions.tsx` rendering `key={accountId}`)
  so switching accounts mid-import can't leave a half-filled mapping pointed at the account that
  was selected when the file was read.
- **The file is decoded by `lib/csv.decodeCsvBytes`, not `File.text()`.** `text()` always decodes
  UTF-8, and Italian bank exports are mostly Windows-1252: every "è" arrived as "�", in notes and
  in the counterparty names merchant rules match against. Strict UTF-8 first, Windows-1252 if the
  bytes aren't valid UTF-8 -- reliable because accented single-byte text almost never forms valid
  UTF-8 sequences. Its unit test leaves out bytes 0x80-0x9F (the euro sign among them): Node's
  `TextDecoder` reads those as Latin-1, unlike the browsers the code runs in.
- **Idempotency key is generated once per confirm action**, lazily on the first "Import N
  transactions" click, and reused on a retry of that same click; a fresh preview (changed mapping,
  or a new file) clears it, since that is a different action and must not replay an old commit's
  stored response.
- **The key comes from `lib/ids.newIdempotencyKey`, never `crypto.randomUUID()` directly.**
  `randomUUID` exists only in secure contexts (HTTPS or localhost); opened from another device at
  `http://<LAN IP>:4173`, as the README sets it up, the confirm click threw before its `try`, the
  button stayed on "Importing…" and nothing was imported (W-30). The helper falls back to
  `crypto.getRandomValues`, available in insecure contexts too, formatted as a v4 UUID; its unit
  test removes `randomUUID` from the global `crypto` to pin that path.

### `Assets` form `key`
Without remounting, "Edit" on a second asset with the form open kept the first asset's values in
the inputs, and saving wrote one asset over the other; "+ New asset" from an open edit form
created a duplicate.

### `PositionsSection` remove asset
A failed bulk delete was swallowed, and the row looked removed until the next refresh.

### Smaller ones
- `Transactions` (the Expenses log): four of its five list requests had no `.catch`, and the
  account list's fell back to `[]` silently -- a failing core-networth left empty pickers and an
  unhandled rejection, nothing on screen. They all report into one `loadError` warning now.
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
