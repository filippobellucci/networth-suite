# The test suite

About 577 tests, in five tiers, plus one CI job that isn't pytest at all. Almost every one of them
exists because something was actually broken once: the docstrings say what, so a failure tells you
which behaviour you changed rather than only that an assertion went red. (The longer story behind
each fix is in `DESIGN_NOTES.md`.)

```
./run-tests.sh fast      unit + frontend            ~3s     run this constantly
./run-tests.sh           everything but the browser ~40s    run this before committing
./run-tests.sh all       + the browser tier         ~2min   run this before releasing
./run-tests.sh lint      ruff, tsc, oxlint
./run-tests.sh compose   build + start docker-compose.yml, needs Docker, a few minutes
```

One tier at a time, with arguments passed through to pytest:

```
./run-tests.sh integration -k refund -x
./run-tests.sh unit -q
```

## If the Python tiers say `No module named pytest`

Four of the five tiers (`unit`, `integration`, `system`, `e2e`) and the `ruff` half of `lint` are
pytest under whichever `python3` is on `PATH`. On a machine with no project dependencies installed
they all fail at once with `No module named pytest`, and only `frontend`, `tsc` and `oxlint` run.
That is the environment, not the branch: a diff cannot cause it, and it does not mean the suite is
red.

Install what CI installs -- Python 3.12, then every `services/*/requirements.txt`,
`gateway/requirements.txt` and `tests/requirements.txt` (`.github/workflows/tests.yml`). Two things
make that fail where you might not expect:

- **`pydantic==2.9.2` does not build on Python 3.14.** It pins `pydantic-core==2.23.4`, built with
  PyO3 0.22.2, which has no 3.14 ABI, and there is no prebuilt wheel to fall back on. Use 3.12, as
  CI does.
- **`python3 -m venv` is not enough without `ensurepip`.** It creates the environment and then has
  no way to install into it.

**When the tiers cannot run at all, CI is the gate, and the task says so.** Push the branch and
read the run: CI runs on every push on every branch, with the real Python 3.12 and real services.
Quote the run id and the per-job result instead of a local summary, and say plainly that the local
run was impossible -- `CLAUDE.md` §5.6 asks for exactly that. What is still worth doing by hand is
everything that needs no dependencies: `bash -n` on shell scripts, `py_compile` on Python files,
and the frontend tier.

## The tiers

| Tier | What it drives | Speed | Count |
|---|---|---|---|
| `unit` | Functions, imported directly. No database, no HTTP. | ~2s | 268 |
| `integration` | core-networth's ASGI app in-process, fresh database and controllable price feed per test. | ~10s | 187 |
| `system` | The real services as separate processes behind the real gateway. | ~20s | 42 |
| `e2e` | The built frontend in Chromium against the whole stack. | ~70s | 20 |
| `frontend` | The TypeScript pure functions, under vitest. | ~1s | 60 |

Two unit tests skip themselves when run as root, which ignores the
permission bits they depend on (`test_backup_location.py`).

The split is about what each tier can *see*. Connection-pool exhaustion, a
proxy that mangles a path, a backup that loses an entity: none of these
exist in-process, so they live in `system`. Everything visible without a
browser is tested without one, because a slow suite stops being run.

## Writing a test for a new feature

1. **Put it in the cheapest tier that can see the behaviour.** If a pure
   function can be extracted, test that. Reach for `system` only when the
   property genuinely involves more than one process.

2. **Say what breaks if it regresses**, in a docstring or an assertion
   message. `assert totals["net_worth"] == 3000` is a fact; "1000 EUR +
   1000 USD at 2.0" is the reason, and it survives someone changing the
   fixture.

3. **Make the failure specific.** `await ok(response)` (in `helpers.py`)
   prints the server's own message instead of `assert 422 == 200`.

4. **Set up through the API**, not by inserting rows, so a change to
   validation is felt by the tests that depend on it.

5. **Date everything relative to today** (`days_ago(5)`), never with a
   literal date. A suite pinned to 2024 quietly stops testing "a year ago".

### Check that a new test can fail

The most common defect in a test suite is a test that cannot fail. Before
trusting a new one, break the thing it covers and watch it go red. Two of
the tests here were written wrong the first time and passed anyway -- one
patched a constant that did not exist (so it measured nothing), one asserted
`raising=False` on a rename. Both were caught by deliberately checking, not
by reading.

## The fixtures

| Fixture | Gives you |
|---|---|
| `api` | httpx client on core-networth's ASGI app, its own database |
| `feed` | the price feed, under your control (see below) |
| `db_engine`, `db_session` | that same database, directly |
| `core_modules` | the service's modules, for testing a function in isolation |
| `stack` | the four real processes; `.gateway_url`, `.core_url`, `.gateway_log()` |
| `gw`, `core_http` | clients for the running gateway and core |
| `page` | a Chromium page with console errors and failed requests recorded |

### The price feed

`FakeFeed` replaces `price_client._get_json`, the single HTTP boundary
between core-networth and price-feed. Everything above that line -- the
caching, the `"EURUSD=X"` pair-ticker construction, the "a 404 means
unavailable" handling -- stays in the test, because that is where the bugs
were.

```python
feed.set_price("TESTUSD", 100.0, currency="USD")
feed.set_fx("USD", "EUR", live=2.0, historical=4.0)   # deliberately different
feed.set_intraday("TESTUSD", date.today(), [100.0, 101.0])
```

Live and historical rates differ on purpose. Four separate bugs were a
figure converted at the wrong moment's rate, and they are only
distinguishable when the two rates are not the same number.

## Running it in CI

`.github/workflows/tests.yml` runs the fast tiers and the linters in one
job, integration in another, system plus browser in a third, and a fourth,
`compose`, builds and starts the real `docker-compose.yml` (see below).
Service logs are uploaded when something fails.

One thing to know about the `fast`/`integration`/`system` jobs: they install
**every** service's `requirements.txt` into a single Python environment,
while Docker gives each image an environment holding only its own. A
dependency a service forgot to declare is therefore importable here and
absent in the container. That gap has shipped twice, so
`test_service_requirements.py` compares each image's code against its own
requirements file -- statically, in milliseconds. It is a stand-in for
building the images, not a substitute -- the real cover is the `compose` job.

### The `compose` job

`tests/compose/smoke.sh` -- also runnable by hand as `./run-tests.sh
compose`, given a local Docker -- builds all six images with the build
context `docker-compose.yml` declares for each, starts the stack with no
`.env` file (every variable it reads has a safe default; bank-sync is
documented to run with nothing configured), waits for the gateway's own
aggregated `/health` to report every registered module `ok`, and fails fast
if any container gets stuck `Restarting` instead of waiting out a fixed
timeout. Logs are dumped and the stack torn down (`docker compose down
--volumes`) on success or failure alike. No real data, credentials or
external services are involved.

`tests/unit/test_compose_build_contexts.py` complements it statically: it
checks that `docker-compose.yml`'s build contexts, every Dockerfile's `COPY`
paths and README.md's "Building straight from GitHub" table all agree, which
is the one thing the `compose` job itself cannot exercise -- CI has no
remote Git URL to build from, which is how the app is actually deployed on
the owner's NAS.

## Known gaps

Worth stating plainly, so the suite is not mistaken for more than it is:

- **No real market data.** yfinance is never called. `test_price_feed_contract.py`
  fakes `yf.Ticker` (`fast_info`, `history()`) with shapes modelled on real,
  not ideal, Yahoo answers and exercises the five bugs `DESIGN_NOTES.md`
  already paid for once: the currency guess cached forever, today's partial
  bar/series cached as the finished day (both `_fetch_price_on_date` and
  `_fetch_intraday`), a NaN `last_price`, and a NaN `Close` row -- plus a
  ticker Yahoo has nothing for and a request that fails outright. What is
  still untested is yfinance's own HTTP layer underneath that boundary (the
  real request/response cycle, cookie/crumb handling, rate-limit backoff)
  and the `/history` endpoint's cache-every-request behaviour.
- **No real bank.** bank-sync's capture loop runs against a fake Enable
  Banking and a fake core-networth (`test_bank_sync_pending.py`), never a
  real bank. On a machine where PyJWT's crypto backend won't import, the
  tests that need `sync.py` skip themselves with that reason. The `compose`
  job never configures a real `links.yaml` either, so bank-sync only ever
  starts unconfigured there.
- **The compose smoke test never builds from a remote Git URL.** That is how
  the app is actually deployed (README.md, "Building straight from
  GitHub"), and CI has no clone to point a remote context at.
  `test_compose_build_contexts.py` is the static stand-in -- it catches a
  Dockerfile/context/README mismatch, not everything a real remote build
  could still hit.
- **The frontend image is only built, never health-checked.** It has no
  `/health` endpoint for the `compose` job to poll, so a frontend container
  stuck restarting is caught (nothing should be `Restarting` at all), but a
  frontend that starts and serves garbage would not be.
- **Chromium only.** At least one past bug (the backup download) was
  specific to Firefox and Safari.
