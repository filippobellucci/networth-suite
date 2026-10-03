# Net Worth Suite

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

A self-hosted net worth tracker: portfolios, cash, expenses and budgets in one app that runs
entirely on your own machine. It started as the replacement for a spreadsheet, and keeps the
spreadsheet's honesty -- every figure is computed from what you entered, at the prices and
exchange rates of the day it refers to.

It is a set of small independent services behind one API gateway, with a React frontend.

## What it does

**Net worth**
- Any number of portfolios, each in its own base currency, holding assets from a shared catalogue
  (ETFs, stocks, bonds, crypto, real estate, ...).
- Live prices and exchange rates from Yahoo Finance; a manual price for anything unlisted.
- History that is right about the past: each past day is valued at that day's closing prices and
  exchange rates, not today's.
- Growth over a day, week, month, year or since the start, an hourly chart for the current day,
  and the real money-weighted return (XIRR) over the last year and since inception.
- Frozen net worth snapshots: take one by hand, and month-ends are filled in automatically.

**Cash and other balances**
- Accounts updated by hand or by their transactions, tagged as Cash, Emergency Fund or Pension
  Fund (a pension fund's growth counts as return, not as money added).
- Meal-voucher accounts, counted in units and valued at the unit price.
- Removing an account never rewrites the past: it leaves today's totals but stays in history.

**Allocation**
- By category (stocks, bonds, cash, emergency fund, pension fund) and by currency.
- Geographic exposure: upload an ETF factsheet (Amundi, iShares, Vanguard) and see the portfolio's
  exposure by country or region, as a chart or a world map, optionally stocks-only or bonds-only.

**Expenses**
- An income and expense log with categories, transfers between your own accounts, and refunds
  (netted against the expense they refund); edit any entry, categorize several at once, turn a
  one-sided entry into a transfer, search, filter and export to CSV.
- Merchant rules: map a merchant (or every merchant whose name contains a word) to a category once.
- Monthly budgets per category, with a warning when one is nearly or fully used.
- Recurring payments found automatically -- subscriptions, their monthly cost, price increases.
- Spending and income by category, and income, spending and savings rate month by month.

**Automatic capture from your bank** (optional) -- the `bank-sync` service logs your bank
transactions on its own through Open Banking (PSD2), categorizes what it can and warns you before
a bank consent expires. See [`services/bank-sync/README.md`](./services/bank-sync/README.md).

**And** light and dark themes with five accent colours, a mobile layout, one-click backup and
restore of everything, an optional API key for the gateway, and no cloud: your data never leaves
your machine.

## Quick start

Requires [Docker](https://docs.docker.com/get-docker/) with Docker Compose.

```bash
git clone <this-repo-url> networth-suite
cd networth-suite
docker compose up --build
```

Open http://localhost:4173. The API gateway is on http://localhost:8080.

Everything restarts on its own after a reboot (`restart: unless-stopped`), and rebuilding after a
code update (`docker compose up --build`) keeps your data.

## Configuration

Every setting is optional. Copy `.env.example` to `.env` (gitignored) and uncomment what you need;
Docker Compose reads it automatically. Rebuild after a change: `docker compose up --build -d`.

| Variable | Default | What it is for |
|---|---|---|
| `VITE_GATEWAY_URL` | `http://localhost:8080` | The gateway address as **your browser** reaches it. |
| `ALLOWED_ORIGINS` | `http://localhost:4173,http://localhost:5173` | Where the frontend is opened from (CORS). |
| `API_KEY` | empty | If set, every gateway request needs it (header `X-API-Key`); the frontend is built with it. |
| `MAX_UPLOAD_SIZE_BYTES` | `26214400` (25 MB) | The largest ETF factsheet that may be uploaded. |
| `ENABLE_BANKING_APP_ID` | empty | bank-sync only -- see its README. |
| `BANK_SYNC_PUBLIC_BASE_URL` | `http://localhost:8003` | bank-sync only -- see its README. |

**Using it from other devices at home.** Find the host's LAN IP (e.g. `192.168.1.10`) and set
`VITE_GATEWAY_URL=http://192.168.1.10:8080` and `ALLOWED_ORIGINS=http://192.168.1.10:4173`, then
open `http://192.168.1.10:4173` from any device on the network. Any machine that runs Docker will
do: a NAS, a mini PC, a Raspberry Pi (ARM64).

**Exposing it beyond your network** (port forwarding, a reverse proxy): there are no user
accounts -- it is a single-user app -- so set `API_KEY` to a long random string. The key is built
into the frontend, so anyone who can load the frontend can read it: it is a barrier, not real
authentication.

## Your data

| Where | What |
|---|---|
| `core_data` Docker volume | The main database: portfolios, assets, balances, transactions, budgets, rules. |
| `services/geo-allocation/data/` | The uploaded ETF factsheets and their parsed results. |
| `services/bank-sync/data/` | bank-sync's links, the record of what it has captured, its audit CSV. |
| `./backups/` | The automatic daily backups (below). |

**Automatic jobs.** The services run their own small schedulers: once at startup -- so a machine
switched on once a day still gets them -- and then every few hours.
- Prices and exchange rates are refreshed.
- A missed month-end net worth snapshot is filled in, valued at that day's real prices (marked
  "Auto" in Historical Net Worth).
- Once a day, each service copies its data to `./backups/core/`, `./backups/geo/` and
  `./backups/bank/`, in a folder per date. A day the machine was off simply has no copy. Point a
  NAS sync job or `rsync` at `./backups/` for copies on another machine.

To run them now: `curl -X POST http://localhost:8080/api/core/scheduler/run-now` (and
`/api/geo/scheduler/run-now`).

**Backup and restore.** *Modules & Status* → *Download full backup* saves a single zip with
everything (including bank-sync's data, when it is in use). *Restore from backup* shows what the
file contains before anything is touched, and each service keeps a safety copy of its current data
(`./backups/<service>/pre-restore-<timestamp>/`) before replacing it.

**Starting over.** The `core_data` volume survives rebuilds and even a fresh clone into a folder
with the same name -- deliberately. To wipe everything: `docker compose down -v`, then
`docker compose up --build`.

**Your data stays out of git.** `.gitignore` excludes every `data/` folder's contents, `*.db`
files, `./backups/`, `.env`, and bank-sync's `links.yaml`, `mcc_categories.yaml` and `secrets/`.
It cannot untrack a file that was committed before; if that ever happens, remove it with
`git rm --cached` and consider the copy in the history exposed.

## Local development

The services can run directly on your machine, without Docker. Python 3.12 and Node 22:

```bash
python3 -m venv .venv && source .venv/bin/activate
for req in services/*/requirements.txt gateway/requirements.txt tests/requirements.txt; do
  pip install -r "$req"
done
npm install --prefix frontend
```

Then, each in its own terminal (data goes to `~/.networth-suite/`, outside the repo):

```bash
D=~/.networth-suite
(cd services/core-networth  && DATA_DIR=$D/core BACKUP_DIR=$D/backups/core PRICE_FEED_URL=http://localhost:8001 uvicorn app.main:app --port 8000 --reload)
(cd services/price-feed     && uvicorn app.main:app --port 8001 --reload)
(cd services/geo-allocation && DATA_DIR=$D/geo BACKUP_DIR=$D/backups/geo uvicorn app.main:app --port 8002 --reload)
(cd gateway && CORE_SERVICE_URL=http://localhost:8000 PRICE_FEED_URL=http://localhost:8001 \
               GEO_ALLOCATION_URL=http://localhost:8002 uvicorn app.main:app --port 8080 --reload)
npm --prefix frontend run dev    # http://localhost:5173
```

`BACKUP_DIR` defaults to `/backups`, the path Docker mounts, which an ordinary user usually can't
create; without it the services fall back to a folder inside `DATA_DIR` and log where the backup
went. To run bank-sync too: `DATA_DIR=$D/bank CORE_SERVICE_URL=http://localhost:8000 uvicorn
app.main:app --port 8003` from `services/bank-sync`, and `BANK_SYNC_URL=http://localhost:8003` on
the gateway.

Before changing a file, read its section in [`DESIGN_NOTES.md`](./DESIGN_NOTES.md): it explains
the bugs behind code that looks over-careful. Every change gets an entry in
[`CHANGELOG.md`](./CHANGELOG.md).

## Tests

```bash
./run-tests.sh fast    # unit + frontend, a few seconds -- while you work
./run-tests.sh         # everything but the browser, ~40s -- before committing
./run-tests.sh all     # + the browser tier, ~2 min -- before a release
./run-tests.sh lint    # ruff, tsc, oxlint
```

About 520 tests in five tiers, from pure functions up to the built frontend driven in Chromium
against the whole stack. Nothing reaches the network: the price feed is replaced by one the tests
control. They run on every push (`.github/workflows/tests.yml`). [`tests/README.md`](./tests/README.md)
explains the tiers, the fixtures and how to add a test.

## Architecture

```
browser ──▶ frontend (React, :4173)
        ──▶ gateway (FastAPI, :8080) ──▶ core-networth  (:8000)  portfolios, assets, cash, expenses, valuation
                                     ──▶ price-feed     (:8001)  prices and exchange rates (yfinance)
                                     ──▶ geo-allocation (:8002)  ETF factsheet parsing, geographic exposure
                                     ──▶ bank-sync      (:8003)  optional: capture from the bank

bank-sync ──▶ core-networth          (creates transactions through the same API as the app)
```

Each service has its own Dockerfile, storage and REST API. The browser only talks to the gateway,
which forwards `/api/<module>/...` to the module and combines several of them where a page needs it
(the dashboard, geographic exposure, backups). bank-sync is the one service also reachable directly,
because each bank's login sends your browser back to it.

The main database stores **time series**, not a grid of monthly columns: a holding is "I held X
units of A on date D", a balance is set on a date and moved by the transactions after it, and the
figure for any day is computed when it is asked for. Transfers and refunds are ordinary
transactions with a link (`transfer_id`, `refund_of_id`), left out of the reports or netted in them.

**Adding a module.** Create `services/<name>/` with a Dockerfile and a REST API, in any language;
add one entry to `gateway/app/registry.py` and a service to `docker-compose.yml`. The gateway then
serves it under `/api/<name>/...`.

## Project structure

```
networth-suite/
├── docker-compose.yml, .env.example
├── run-tests.sh           one command for the whole test suite
├── CHANGELOG.md           every change, by date and by area
├── DESIGN_NOTES.md        why the code is the way it is, by file
├── CLAUDE.md              conventions for working on the code
├── gateway/               API gateway and module registry (FastAPI)
├── services/
│   ├── core-networth/     portfolios, assets, cash, expenses, valuation (SQLite)
│   ├── price-feed/        prices and exchange rates (yfinance)
│   ├── geo-allocation/    ETF factsheet parsing and storage
│   └── bank-sync/         optional automatic capture from the bank (Enable Banking)
├── frontend/              React, TypeScript, Vite, Tailwind, Recharts
└── tests/                 unit, integration, system and browser tests
```

## License

MIT -- see [LICENSE](./LICENSE).
