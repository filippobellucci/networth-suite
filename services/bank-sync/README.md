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
bank-sync (this service, on your own machine, port 8003)
        |  the same API the Transactions page uses
        v
core-networth
```

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
   never created twice. That record is part of the backups: losing it would make the next sync
   re-create every recent transaction as a duplicate.
4. Every transaction the bank sends, exactly as sent, is appended to an audit CSV
   (`data/transactions_log.csv`) -- including ones that were skipped, such as zero amounts.

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

Names must match an existing Expense Category (case doesn't matter); bank-sync never creates
categories. The file is re-read on every sync, so changing it needs no restart.
`mcc_categories.example.yaml` is a starter mapping for the common cases, and
[`mcc_categories.md`](./mcc_categories.md) a table of about 150 common codes.

**By merchant name (Expenses → Merchants).** Some banks send no code at all -- Revolut, through
Enable Banking, leaves it empty on every card payment. The **Merchants** tab lists every
counterparty seen, with how many transactions and how much, under *To map*, *Mapped* and
*Ignored*:

- pick a category for a merchant and its uncategorized transactions get it at once, and every new
  one arrives with it;
- a *contains* rule (e.g. `unicoop`) covers every merchant whose name contains it -- every store of
  a chain; a merchant's own rule beats it, then the longest matching rule;
- *Ignore* takes a counterparty off the to-map list (your own name on a transfer, a shop where every
  purchase is something different).

Names that differ only in case or spacing are one merchant. When both apply, a mapped MCC wins over
the merchant's rule. The rules live in Net Worth Suite's database, so they are in its backups.

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

Start the stack (bank-sync starts fine with no links configured), then:

```bash
curl "http://<host>:8003/helper/aspsps?country=IT"    # the exact aspsp_name of your bank
curl "http://<host>:8003/helper/accounts"              # your portfolio_id / cash_account_id values
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

`cp mcc_categories.example.yaml mcc_categories.yaml` and adjust the category names
(`GET /helper/categories` lists yours with their exact spelling). `docker-compose.yml` mounts the
file on its own: if it didn't exist yet when the container started, it appears inside as an empty
directory (the log says so) -- create it, then recreate the container once.

## Day to day

- **Warnings in the app.** With `BANK_SYNC_URL` set on the gateway (as in `docker-compose.yml`), the
  Summary and Expenses pages warn when a consent expires within 7 days or has expired, when a link
  was never authorized, when no sync has succeeded for a while, and when the balances differ --
  each with a link to fix it.
- **Renewing consent.** Consent lasts `ACCESS_VALID_DAYS` (default 90; PSD2 and your bank may cap
  it). When it runs out the link shows `EXPIRED`: click **Re-authorize** -- same quick login, nothing
  is lost.
- **Errors.** A link in `ERROR` shows its last error on the status page; the full detail is in
  `docker compose logs bank-sync`.
- **Syncing now.** *Sync all now* on the status page (`GET /sync-now`) runs a cycle immediately.
- **Backups.** bank-sync's database and audit CSV are copied once a day to `./backups/bank/<date>/`
  and are part of the backup you download from Settings. Restoring keeps a safety copy of the
  current data (`pre-restore-<timestamp>/`) and then re-reads `links.yaml`.
- **Removing an account.** Delete its entry from `links.yaml` and restart: the link stops syncing.
  Put it back later and it resumes with its previous authorization, if still valid.

## Configuration

Environment variables of the `bank-sync` service (set them under its `environment:` in
`docker-compose.yml`; the first two come from `.env`):

| Variable | Default | Meaning |
|---|---|---|
| `ENABLE_BANKING_APP_ID` | -- | Your Enable Banking application id. |
| `PUBLIC_BASE_URL` | `http://localhost:8003` | Where your browser reaches this service (`BANK_SYNC_PUBLIC_BASE_URL` in `.env`). |
| `SYNC_INTERVAL_HOURS` | `6` | How often every active link is synced. |
| `MAX_HISTORICAL_DAYS` | `90` | How far back the first sync of a link goes. |
| `ACCESS_VALID_DAYS` | `90` | How long the consent requested from the bank lasts. |
| `PENDING_TRACK_DAYS` | `30` | How long a pending card payment is waited on. |
| `CORE_SERVICE_URL` | `http://core-networth:8000` | Where core-networth is. |

## Endpoints

| Endpoint | What it is |
|---|---|
| `GET /` | The status page: every link, its status, last sync, consent expiry, Authorize buttons. |
| `GET /status` | The same as JSON -- what the app's warnings read. |
| `GET /sync-now` | Runs a sync cycle now. |
| `GET /transactions-log.csv` | The raw audit CSV. |
| `GET /helper/aspsps?country=IT` | Banks Enable Banking supports in a country. |
| `GET /helper/accounts` | Your portfolios and cash accounts, with their ids. |
| `GET /helper/categories` | Your expense categories, with their exact names. |

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
