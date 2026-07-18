# Net Worth Suite

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

A self-hosted, multi-portfolio net worth tracker — an interactive replacement for a spreadsheet-based
tracking sheet. Track multiple portfolios, holdings, cash accounts, live prices, ETF geographic
exposure, and pension fund projections, all from a single dashboard running entirely on your own
hardware.

Built as a set of independent, polyglot microservices behind a single API gateway, so it's easy to
extend with new modules over time without touching the rest of the system.

## Features

- **Multiple portfolios** — track as many portfolios as you want (personal, trading, retirement…), each with its own holdings, cash accounts, and history
- **Live prices & FX** — automatic price updates via `yfinance`, with manual price overrides for unlisted assets (real estate, private holdings…)
- **Full asset lifecycle** — add, edit, or remove any asset from a shared catalogue at any time
- **Net worth history** — computed automatically from a normalized time series, not copy-pasted month by month
- **ETF geographic allocation** — upload a fund/ETF factsheet and get its country breakdown; combine multiple funds into a single portfolio-wide exposure chart, weighted by actual position value
- **Pension fund projections** — model future value from contribution history and an expected annual return
- **Runs entirely locally** — no cloud dependency, no external accounts; your financial data never leaves your machine

## Architecture

```
frontend (React + TS)  ──▶  gateway (FastAPI, :8080)
                                 ├─▶ core-networth  (:8000)  portfolios, assets, cash, valuation
                                 ├─▶ price-feed     (:8001)  live prices + FX via yfinance
                                 ├─▶ geo-allocation (:8002)  ETF geographic allocation
                                 └─▶ pension-fund   (:8003)  pension fund projections
```

Every backend service is independent, with its own `Dockerfile`, database/storage, and REST API.
The frontend and any external caller only ever talk to the gateway — individual services are never
exposed outside the internal network. Nothing ties the architecture to Python specifically: a future
module written in Go, Rust, or Node.js integrates identically, as long as it speaks REST.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS, Recharts |
| Backend services | Python, FastAPI, SQLAlchemy (SQLite) |
| Price data | `yfinance` |
| Deployment | Docker Compose |

## Quick start

Requires [Docker](https://docs.docker.com/get-docker/) and Docker Compose.

```bash
git clone <this-repo-url>
cd networth-suite
docker compose up --build
```

- Frontend: http://localhost:4173
- Gateway/API: http://localhost:8080

## Local development (without Docker)

Backend services (each in its own terminal, or with any process manager you prefer):

```bash
cd services/core-networth   && pip install -r requirements.txt --break-system-packages && DATA_DIR=./data PRICE_FEED_URL=http://localhost:8001 uvicorn app.main:app --port 8000 --reload
cd services/price-feed      && pip install -r requirements.txt --break-system-packages && uvicorn app.main:app --port 8001 --reload
cd services/geo-allocation  && pip install -r requirements.txt --break-system-packages && DATA_DIR=./data uvicorn app.main:app --port 8002 --reload
cd services/pension-fund    && pip install -r requirements.txt --break-system-packages && uvicorn app.main:app --port 8003 --reload
cd gateway                  && pip install -r requirements.txt --break-system-packages && uvicorn app.main:app --port 8080 --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, points at VITE_GATEWAY_URL (default http://localhost:8080)
```

## Self-hosting on a home server

The project runs on any machine that supports Docker — a NAS, a mini PC, a Raspberry Pi (ARM64),
or a regular desktop left on at home. To make it reachable from other devices on your network:

1. Find the host machine's LAN IP address (`ip addr` / `ifconfig` on Linux/macOS, `ipconfig` on Windows).
2. In `docker-compose.yml`, update:
   - `gateway.environment.ALLOWED_ORIGINS` → add `http://<host-ip>:4173`
   - `frontend.build.args.VITE_GATEWAY_URL` → `http://<host-ip>:8080`
     (this must be reachable from the *browser* of the device you're using, not just from inside Docker)
3. `docker compose up --build -d`
4. Open `http://<host-ip>:4173` from any device on your network.

All services define `restart: unless-stopped`, so once the Docker daemon is running, containers come
back up automatically after a reboot.

### Backing up your data

All persistent state lives in two places:
- **`core_data` Docker volume** — the SQLite database of portfolios/assets/holdings (`networth.db`)
- **`services/geo-allocation/data/fund-files/`** — one uploaded Excel factsheet per asset, plus its parsed result

Back up these two locations (e.g. with `rsync`, or a scheduled job to a NAS) for a complete backup.

## Keeping your portfolio data out of git

This repo is meant to hold code, not your financial data. `.gitignore` already excludes:
- the contents of any `data/` folder anywhere in the tree (each service's local `DATA_DIR`)
- `*.db` / `*.sqlite` / `*.sqlite3` files, wherever they end up

So you can commit and push freely — a fresh `git clone` starts with an empty database and no
uploaded files, nothing personal ever leaves your machine through version control.

## Data model

Each portfolio tracks assets and cash as an append-only time series rather than a fixed grid of
rows and monthly columns:

- **Portfolio** — a named portfolio with its own base currency
- **Asset** — a catalogue entry (ETF, stock, bond, real estate, pension fund…) shared across portfolios
- **HoldingEntry** — "I held X units of asset A in portfolio P on date D"; adding a position creates
  a new entry, updating it creates a new entry dated today, removing it deletes that asset's entries
  in that portfolio
- **CashAccount / CashBalanceEntry** — the same principle applied to cash balances
- **Net worth** at any date is computed on demand (quantity × most recent available price, converted
  to the portfolio's base currency) rather than stored and copied by hand

## Extending with a new module

1. Create a new service under `services/<name>/` with its own `Dockerfile` (any language).
2. Expose REST endpoints (ideally with an OpenAPI schema, if the language supports it).
3. Register it in `gateway/app/registry.py` (one line) and add a `services:` block in `docker-compose.yml`.
4. The gateway automatically routes requests to it under `/api/<name>/...` — no frontend changes
   needed unless you also want a dedicated UI (a new page + entry in `Sidebar.tsx`).

## Project structure

```
networth-suite/
├── docker-compose.yml
├── gateway/                     # API gateway (FastAPI) + module registry
├── services/
│   ├── core-networth/           # portfolios, assets, cash, valuation (SQLite)
│   ├── price-feed/               # live prices + FX (yfinance)
│   ├── geo-allocation/           # ETF geographic allocation parsing + local file storage
│   └── pension-fund/             # pension fund projections
└── frontend/                     # React + TypeScript + Vite + Tailwind + Recharts
```

## License

MIT — see [LICENSE](./LICENSE).
