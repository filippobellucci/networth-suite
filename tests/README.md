# The test suite

375 tests, in five tiers, built from thirteen full-codebase reviews. Almost
every one of them exists because something was actually broken once: the
docstrings say what, so a failure tells you which behaviour you changed
rather than only that an assertion went red.

```
./run-tests.sh fast      unit + frontend            ~2s     run this constantly
./run-tests.sh           everything but the browser ~40s    run this before committing
./run-tests.sh all       + the browser tier         ~90s    run this before releasing
./run-tests.sh lint      ruff, tsc, oxlint
```

One tier at a time, with arguments passed through to pytest:

```
./run-tests.sh integration -k refund -x
./run-tests.sh unit -q
```

## The tiers

| Tier | What it drives | Speed | Count |
|---|---|---|---|
| `unit` | Functions, imported directly. No database, no HTTP. | ~1s | 167 |
| `integration` | core-networth's ASGI app in-process, fresh database and controllable price feed per test. | ~7s | 113 |
| `system` | The real services as separate processes behind the real gateway. | ~30s | 40 |
| `e2e` | The built frontend in Chromium against the whole stack. | ~45s | 13 |
| `frontend` | The TypeScript pure functions, under vitest. | ~0.5s | 42 |

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
job, integration in another, and system plus browser in a third. Service
logs are uploaded when something fails.

## Known gaps

Worth stating plainly, so the suite is not mistaken for more than it is:

- **No real market data.** yfinance is never called; price-feed's own
  yfinance-facing code is exercised only through `TtlCache`. Anything
  specific to how Yahoo behaves is untested.
- **No real bank.** bank-sync's capture loop needs Enable Banking
  credentials. Its pure helpers are tested; `sync.py` skips itself where
  PyJWT's crypto backend will not import.
- **Not deployed via Docker Compose.** The services are started directly.
  The compose file is validated (`docker compose config`) but never run.
- **Chromium only.** At least one past bug (the backup download) was
  specific to Firefox and Safari.
