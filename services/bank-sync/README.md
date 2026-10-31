# Bank Sync

An optional service that watches your bank accounts and logs their expenses and income in Net
Worth Suite on its own, through [Enable Banking](https://enablebanking.com)'s Open Banking (PSD2)
API. Without it every expense is entered by hand; with it you set up each account once, log into
each bank about every 90 days, and the rest is automatic.

It does nothing until it is configured, so it is safe to leave running.

```
Your bank (Fineco, Revolut, ...)
        |  login once every ~90 days
        v
Enable Banking (regulated Open Banking provider, read-only access)
        |  periodic reads
        v
bank-sync (this service, on your own machine)
        |  the same API the Transactions page uses
        v
core-networth
```

It listens on two ports. **8003**, published on the host, serves only what your browser needs:
the status page, the Authorize button and the bank's redirect back (`/callback`). **8004** serves
everything else -- backups, helpers, the status the app's warnings read, a manual sync -- and is
not published: only the gateway reaches it, over the Docker network, so it is covered by the
gateway's `API_KEY` like every other module. Set `BANK_SYNC_INTERNAL_PORT` in `.env` to move it
to another port; the gateway follows.

bank-sync has its own small database and never touches Net Worth Suite's data directly: it creates
transactions through the same endpoint the Transactions page uses, so every existing rule applies
to what it captures too (Pension Fund accounts accept no transactions, removed accounts accept no
new rows, and so on).

## How a sync works

Every `SYNC_INTERVAL_HOURS` (default 6), and once at startup, for every **active** link:

1. It asks Enable Banking for the account's transactions since the last successful sync (the
   first sync goes back `MAX_HISTORICAL_DAYS`, default 90), page by page.
2. Each transaction it has never seen is created in Net Worth Suite:
   - income or expense from the bank's `credit_debit_indicator` (some banks send unsigned amounts);
   - the note from every line of `remittance_information`;
   - the counterparty -- the merchant you paid, or who paid you;
   - a category, when one can be decided (see below).
3. It remembers what it has captured, so a transaction that shows up again in the next fetch is
   never created twice. Each transaction is recorded the moment Net Worth Suite has it, not at
   the end of the sync, and is sent with an `Idempotency-Key` derived from the bank's id for it:
   if a sync is interrupted after Net Worth Suite saved a transaction but before bank-sync heard
   back (a timeout, a restart), the retry on the next sync gets the transaction already created
   instead of a second one. That record is part of the backups: losing it would make the next
   sync re-create as duplicates the recent transactions it captured more than a day before.
4. Every transaction the bank sends, exactly as sent, is appended to an audit log in
   `data/audit-log/` -- including ones that were skipped, such as zero amounts. The log is a
   numbered series of CSV files: once `transactions_log-0001.csv` reaches `AUDIT_LOG_MAX_MB`
   (default 100 MB) it is closed, compressed to `transactions_log-0001.zip`, and logging continues
   in `transactions_log-0002.csv`. Closed files are all kept. The log is in clear text (account
   numbers included), stays on this machine and is **not** part of any backup. A log left by an
   earlier version at `data/transactions_log.csv` is moved into the folder as the next file the
   first time a transaction is logged.

**Pending card payments.** A card payment usually appears first as *pending* and is booked a few
days later, sometimes for a different amount (a tip, a hotel or fuel hold) and sometimes only then
with its merchant code. bank-sync captures it right away, re-reads it on every sync until it is
booked, and then updates the amount and the category -- each only if you haven't changed it by
hand. A pending payment the bank cancels, or that disappears from the bank's list for two syncs in
a row, is removed again, since that money never moved. One still pending after
`PENDING_TRACK_DAYS` (default 30) is kept as it is.

**Balance check.** After every sync without errors it reads the bank's own balance for the account
(the *available* balance when the bank reports one) and compares it with Net Worth Suite's. A
difference of a cent or more shows up as a warning in the app -- a transaction deleted by mistake,
an opening balance that was never right. It never changes anything by itself.

## How transactions get a category

Two independent mechanisms; a transaction neither of them covers stays uncategorized, and you
categorize it from the Expenses page as usual. A category you set by hand is never overwritten.

**By merchant code (MCC).** Many card payments carry a standard *merchant category code*
(ISO 18245) -- `5411` is a supermarket whatever the bank or the country. `mcc_categories.yaml`
maps codes to the names of categories you have already created:

```yaml
mcc_mappings:
  "5411": "Groceries"
  "5812": "Restaurants"
```

Names must match an existing Expense Category of the portfolio the link logs into (case doesn't
matter) -- each portfolio has its own categories; bank-sync never creates categories. The file is re-read on every sync, so changing it needs no restart.
`mcc_categories.example.yaml` is a starter mapping for the common cases, and
[`mcc_categories.md`](./mcc_categories.md) a table of about 150 common codes.

**By merchant name (Expenses → Merchants).** Some banks send no code at all -- Revolut, through
Enable Banking, leaves it empty on every card payment. The **Merchants** tab lists every
counterparty seen in the selected portfolio, with how many transactions and how much, under *To map*, *Mapped* and
*Ignored*:

- pick a category for a merchant and its uncategorized transactions get it at once, and every new
  one arrives with it;
- a *contains* rule (e.g. `unicoop`) covers every merchant whose name contains it -- every store of
  a chain; a merchant's own rule beats it, then the longest matching rule;
- *Ignore* takes a counterparty off the to-map list (your own name on a transfer, a shop where every
  purchase is something different).

Names that differ only in case or spacing are one merchant. When both apply, a mapped MCC wins over
the merchant's rule. Like categories, merchant rules belong to a portfolio: a link's transactions
are matched only against the rules of its own portfolio. The rules live in Net Worth Suite's
database, so they are in its backups.

## Setup

### 1. Register an Enable Banking application

1. Sign in at <https://enablebanking.com/sign-in/> with your email (one-time link).
2. In the Control Panel, under **API applications**, create a new application.
3. Generate its RSA key pair ("Generate in the browser and export private key" is the simplest
   option) and **save the private key file**.
4. Register it for the **Production** environment (Sandbox only returns fake data).
5. Set the redirect URL to `<PUBLIC_BASE_URL>/callback` -- see step 4 for what that address is.
6. Use **Restricted Mode** and whitelist your own accounts: that is what makes the free
   personal-use tier work without a commercial licence.
7. Note the **application id**: it is `ENABLE_BANKING_APP_ID`.

### 2. Put the credentials in place

```
services/bank-sync/secrets/enable_banking_private_key.pem    # the private key from step 1.3
```

and `ENABLE_BANKING_APP_ID=<your application id>` in the project's `.env`. The `secrets/` folder
is gitignored -- never commit the key.

### 3. Find your bank's name and your account ids

Start the stack (bank-sync starts fine with no links configured), then ask through the gateway
(add `-H "X-API-Key: <your key>"` if you set `API_KEY`):

```bash
curl "http://<host>:8080/api/bank/helper/aspsps?country=IT"    # the exact aspsp_name of your bank
curl "http://<host>:8080/api/bank/helper/accounts"              # your portfolio_id / cash_account_id values
```

### 4. Choose the address you will authorize from

Each bank sends your browser back to `PUBLIC_BASE_URL` after login, so it must be an address
**your browser** can reach, and exactly the redirect URL registered in step 1.5. Set it with
`BANK_SYNC_PUBLIC_BASE_URL` in `.env` (default `http://localhost:8003`):

- the host's LAN IP, e.g. `http://192.168.1.10:8003` -- works from your home network only;
- a Tailscale address or a reverse-proxied domain -- works from anywhere. Enable Banking requires
  **HTTPS** for production applications, so put `tailscale serve` or a TLS-terminating proxy in
  front of the port.

### 5. Link each account

1. `cp links.example.yaml links.yaml` and fill in every `REPLACE_ME` (one entry per account).
2. `docker compose up -d --build bank-sync`.
3. Open `http://<host>:8003/`: one row per entry of `links.yaml`, status `PENDING`.
4. Click **Authorize**, log into the bank and confirm. You come back to the status page with the
   link `ACTIVE`, and a first sync runs straight away.

Each link is independent: a problem with one doesn't affect the others.

### 6. (Optional) Categorization by merchant code

`cp mcc_categories.example.yaml mcc_categories.yaml` and adjust the category names. Each
portfolio has its own expense categories, and a link categorizes with those of the portfolio it logs
into (its `portfolio_id`): `GET /api/bank/helper/categories?portfolio_id=<id>` on the gateway
lists them with their exact spelling. A name that portfolio doesn't have leaves the transaction uncategorized. `docker-compose.yml` mounts the
file on its own: if it didn't exist yet when the container started, it appears inside as an empty
directory (the log says so) -- create it, then recreate the container once.

## Day to day

- **Warnings in the app.** With `BANK_SYNC_URL` set on the gateway (as in `docker-compose.yml`), the
  Summary and Expenses pages warn when a consent expires within 7 days or has expired, when a link
  was never authorized, when no sync has succeeded for a while, and when the balances differ --
  each with a link to fix it.
- **The same two warnings by e-mail.** With `SMTP_HOST` set (see the root
  [`README.md`](../../README.md) "Configuration"), a consent expiring within 7 days and a sync that
  has failed 3 cycles in a row each send one e-mail -- once per problem, not every cycle, and again
  if it comes back after being resolved. Off by default; no SMTP configured means no outbound
  connection at all. The message names the link, never a balance or account id.
- **Renewing consent.** Consent lasts `ACCESS_VALID_DAYS` (default 90; PSD2 and your bank may cap
  it). When it runs out the link shows `EXPIRED`: click **Re-authorize** -- same quick login, nothing
  is lost.
- **Errors.** A link in `ERROR` shows its last error on the status page; the full detail is in
  `docker compose logs bank-sync`.
- **Syncing now.** `curl -X POST http://<host>:8080/api/bank/sync-now` (with `X-API-Key` if set)
  runs a cycle immediately and answers with how many transactions each link captured.
- **Backups.** bank-sync's database is copied once a day to `./backups/bank/<date>/` and is part
  of the backup you download from Settings; the audit log in `data/audit-log/` is not (copy that
  folder yourself if you want it elsewhere). Restoring keeps a safety copy of the
  current data (`pre-restore-<timestamp>/`) and then re-reads `links.yaml`; its answer names
  that copy, and `POST /backup/undo-restore` with that name puts the previous data back.
- **Removing an account.** Delete its entry from `links.yaml` and restart: the link stops syncing.
  Put it back later and it resumes with its previous authorization, if still valid.

## Configuration

Environment variables of the `bank-sync` service (set them under its `environment:` in
`docker-compose.yml`; `ENABLE_BANKING_APP_ID`, `PUBLIC_BASE_URL`, `INTERNAL_PORT` and `AUDIT_LOG_MAX_MB` come from `.env`):

| Variable | Default | Meaning |
|---|---|---|
| `ENABLE_BANKING_APP_ID` | -- | Your Enable Banking application id. |
| `PUBLIC_BASE_URL` | `http://localhost:8003` | Where your browser reaches this service (`BANK_SYNC_PUBLIC_BASE_URL` in `.env`). |
| `SYNC_INTERVAL_HOURS` | `6` | How often every active link is synced. Keep it below 24: a transaction whose sync was interrupted is retried on the next sync, and Net Worth Suite recognises a retry for 24 hours. |
| `MAX_HISTORICAL_DAYS` | `90` | How far back the first sync of a link goes. |
| `ACCESS_VALID_DAYS` | `90` | How long the consent requested from the bank lasts. |
| `PENDING_TRACK_DAYS` | `30` | How long a pending card payment is waited on. |
| `AUDIT_LOG_MAX_MB` | `100` | The size at which the audit log's current file is closed and compressed, and the next one started (`BANK_SYNC_AUDIT_LOG_MAX_MB` in `.env`). |
| `CORE_SERVICE_URL` | `http://core-networth:8000` | Where core-networth is. |
| `PUBLIC_PORT` | `8003` | The public port: status page, authorization, `/callback`. Published by `docker-compose.yml`. |
| `INTERNAL_PORT` | `8004` | The internal port, for the gateway only (`BANK_SYNC_INTERNAL_PORT` in `.env`). Never publish it. |

## Endpoints

*Public* endpoints are on port 8003, the one your browser opens. *Internal* ones are on port 8004,
reachable only through the gateway as `/api/bank/...` (e.g. `/api/bank/status`); the public port
answers 404 to them.

| Endpoint | Port | What it is |
|---|---|---|
| `GET /` | public | The status page: every link, its status, last sync, consent expiry, Authorize buttons. |
| `GET /authorize/{label}` | public | Starts a link's bank login. |
| `GET /callback` | public | Where the bank sends your browser back after login. |
| `GET /health` | both | Liveness check. |
| `GET /status` | internal | The status page as JSON -- what the app's warnings read. |
| `POST /sync-now` | internal | Runs a sync cycle now. |
| `GET /transactions-log.csv` | internal | The audit log file being written now (closed ones are only in `data/audit-log/`). |
| `GET /helper/aspsps?country=IT` | internal | Banks Enable Banking supports in a country. |
| `GET /helper/accounts` | internal | Your portfolios and cash accounts, with their ids. |
| `GET /helper/categories?portfolio_id=<id>` | internal | One portfolio's expense categories, with their exact names. |
| `GET /backup/export`, `GET /backup/stats`, `POST /backup/preview`, `POST /backup/restore` | internal | This service's share of the combined backup, called by the gateway. |
| `POST /backup/undo-restore` | internal | Body `{"pre_restore": "<name>"}`: puts back the data a restore replaced, from the `pre-restore-<timestamp>` safety copy whose name that restore returned (`pre_restore` in its answer). For the gateway, when a combined restore fails after bank-sync's part. Makes no safety copy of its own. |

## What it deliberately doesn't do

- **Create categories.** It only uses the ones you have; an unknown name in the MCC mapping leaves
  the transaction uncategorized and logs a warning.
- **Recognize transfers or refunds.** Every captured transaction is a plain income or expense. When
  money moved between two of your own accounts and only one of them is linked, open the Log and
  turn the captured entry into a transfer (**Make it a transfer**): the other side is created on
  the account you pick, and neither counts as spending or income.
- **Choose among several accounts at one bank.** If a bank session covers more than one account
  (e.g. several Revolut currency wallets), the first one returned is synced.

## If something doesn't work

`app/enable_banking.py` follows Enable Banking's documentation and has been used against live
accounts, but their exact field names can change and banks differ in what they fill in. If an
authorization or a sync fails with a 4xx error, the raw response is in the container log: compare
it with [their API reference](https://enablebanking.com/docs/api/reference/).
