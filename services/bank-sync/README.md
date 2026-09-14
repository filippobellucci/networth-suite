# Bank Sync

Automatically captures expenses/income from your bank accounts into Net Worth Suite, via
[Enable Banking](https://enablebanking.com)'s Open Banking (PSD2) API. Every auto-captured
transaction lands in the Expenses feature **with no category** -- you tag it afterward, same as
any manually-logged transaction.

> **Honesty note**: `app/enable_banking.py` is written against Enable Banking's published
> documentation, not tested against a real bank connection (that's not something possible from a
> generic dev environment). The overall flow (register app → authorize with a bank → poll for
> transactions) is correct, but if your first real authorization attempt fails with a 4xx error,
> check the container logs (the raw API response is logged) against
> [their current API reference](https://enablebanking.com/docs/api/reference/) -- exact field
> names in requests/responses are the part most likely to have drifted since this was written.

## 1. Register an Enable Banking application

1. Go to <https://enablebanking.com/sign-in/>, sign in with your email (one-time link).
2. In the Control Panel, go to **API applications** → create a new application.
3. Generate an RSA key pair for it (their Control Panel walks you through this -- "Generate in
   the browser and export private key" is the simplest option). **Save the private key file** --
   you'll mount it into this service.
4. Register the app for the **Production** environment (Sandbox only returns fake data).
5. Set the redirect URL to `http://<wherever-you-reach-this-service>:8003/callback` -- see step 4
   below for what that address actually is in your setup.
6. Whitelist your own accounts (**Restricted Mode**) rather than going through a full commercial
   TPP review -- this is what makes the free personal-use tier work without a licence.
7. Note your **application id** (shown in the Control Panel) -- this is `ENABLE_BANKING_APP_ID`.

## 2. Place the credentials where Docker can mount them

```
services/bank-sync/secrets/enable_banking_private_key.pem   <- the private key from step 1.3
```

This folder is gitignored on purpose -- never commit your private key.

## 3. Find your bank names and account ids

Start the stack once with an empty/default `links.yaml` (or none at all -- the service starts up
fine either way, it just has nothing to sync), then:

```bash
curl "http://<your-host>:8003/helper/aspsps?country=IT"     # find the exact aspsp_name for your bank
curl "http://<your-host>:8003/helper/accounts"               # list your portfolio_id / cash_account_id values
```

## 4. Decide what address you'll authorize from

`PUBLIC_BASE_URL` (set in `docker-compose.yml`, or override with the `BANK_SYNC_PUBLIC_BASE_URL`
environment variable) must be an address **your browser** can reach when you click "Authorize" --
this is where each bank redirects you back to after login. Options, same tradeoffs as the rest of
Net Worth Suite's own network setup:

- Your host machine's LAN IP, e.g. `http://192.168.1.10:8003` -- only works from your home network.
- A Tailscale address, e.g. `https://host.your-tailnet.ts.net:8003` -- works from anywhere, but
  Enable Banking requires **HTTPS** for production applications (unlike sandbox), so you'll need
  `tailscale serve` or a reverse proxy terminating TLS in front of this port.

Whatever you choose, it must **exactly match** what you registered as the redirect URL in step 1.5.

## 5. Configure and link each account

1. `cp links.example.yaml links.yaml`, fill in every `REPLACE_ME`.
2. `docker compose up -d --build bank-sync` (or redeploy however you normally do).
3. Open `http://<your-host>:8003/` -- you'll see one row per entry in `links.yaml`, status
   `PENDING`.
4. Click **Authorize** next to each one, log into that bank, confirm consent. You're redirected
   back and the status should flip to `ACTIVE`, with an immediate first sync.
5. Repeat for all 4 accounts. Each is independent -- a problem with one doesn't affect the others.

## 6. (Optional) Automatic categorization by merchant type

Copy `mcc_categories.example.yaml` to `mcc_categories.yaml` and map merchant category codes to
your existing Expense Category names -- run `GET /helper/categories` to see the exact names to
use. See `mcc_categories.md` for a reference table of common codes. Leave the file empty or
missing and every captured transaction stays uncategorized, same as before this existed.

## 7. Ongoing operation

- Syncs automatically every `SYNC_INTERVAL_HOURS` (default 6).
- The bank's consent expires after `ACCESS_VALID_DAYS` (default 90, capped by PSD2/your bank
  regardless of what's requested) -- the status page shows "Consent valid until" per link and
  flips to `EXPIRED` when it passes. Click **Re-authorize** to renew (same quick login, no data
  lost).
- `GET /sync-now` on the status page triggers an immediate sync of every active link, if you don't
  want to wait for the schedule.
- If a link shows `ERROR`, the status page shows the last error message; check the container logs
  for the full detail.
- Every transaction fetched from any linked bank is also appended, as-is, to a single audit CSV
  (`data/transactions_log.csv`) tagged with which institution it came from -- download it from the
  status page or `GET /transactions-log.csv`. Independent of what ends up in Net Worth Suite: a
  transaction skipped as zero-amount, or filtered out for any other reason, still gets a row here.

## What this service intentionally does NOT do

- No categorization beyond the optional `mcc_categories.yaml` mapping -- a code with no mapping
  (or the vast majority of manual transfers/cash withdrawals, which don't carry an MCC at all)
  stays uncategorized. Categorize the rest from the Expenses page as usual.
- No account picker if a bank session returns multiple accounts (e.g. several Revolut currency
  wallets) -- it syncs the first one returned. Point a `links.yaml` entry's `cash_account_id` at a
  different Net Worth Suite account and re-authorize if you need a specific one.
- No transfer/refund detection -- an auto-captured transaction is always a plain expense or
  income. Use the Transactions page's Transfer/Refund options by hand for those, same as today.
