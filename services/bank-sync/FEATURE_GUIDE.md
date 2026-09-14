# Automatic expense management — detailed guide

This guide covers the full automatic expense capture feature introduced with the `bank-sync`
service: what it does, how it's built, and exactly how automatic categorization works. For
practical installation steps see `services/bank-sync/README.md`; for the MCC code table see
`services/bank-sync/mcc_categories.md`.

## 1. What it solves

Before this feature, every expense had to be entered by hand into Net Worth Suite. `bank-sync`
watches your bank accounts (Fineco, Revolut, PayPal, Trade Republic, or any other compatible
account) and inserts expenses/income on its own as soon as it finds them -- no action needed from
you beyond initial setup and a one-time login per bank.

## 2. Architecture

```
Your bank (Fineco, Revolut...)
        |  (real login, once every ~90 days)
        v
Enable Banking (Open Banking / PSD2, regulated cloud service)
        |  (periodic reads, read-only)
        v
bank-sync (new Docker service, runs on your own host machine)
        |  (same API already used by Transactions)
        v
Net Worth Suite (core-networth)
```

`bank-sync` is an independent service, with its own database (SQLite, like the other services),
that doesn't change any of Net Worth Suite's existing logic in any way -- it talks to
`core-networth` through the exact same endpoints the Transactions page already uses when you log
an expense by hand. This means every rule that already exists (Pension Fund doesn't accept
transactions, archived accounts don't accept new rows, etc.) automatically applies to
bank-sync-captured expenses too, with no need to duplicate that logic.

## 3. The sync cycle, step by step

1. Every `SYNC_INTERVAL_HOURS` (default 6 hours), `bank-sync` checks every **active** link.
2. For each one, it asks Enable Banking for the transaction list since the last sync (with
   pagination support, so nothing is lost if there are many at once).
3. For every transaction **never seen before** (tracked in an internal dedupe table, so a
   transaction can't end up inserted twice if it reappears within the same date window):
   - Determines expense vs. income from the bank's `credit_debit_indicator` field (not the sign
     of the amount -- some banks always send it unsigned; see the changelog for the bug this
     avoided).
   - Builds the note by joining every line of `remittance_information` available.
   - Looks for an automatic category via `merchant_category_code` (see section 4).
   - Calls the same transaction-creation endpoint the Transactions page already uses.
4. Marks the transaction as "already synced," so the next cycle doesn't re-insert it.

## 4. Automatic categorization, in detail

### How it works

Many card transactions arrive from the bank with a **standardized merchant type code**
(`merchant_category_code`, e.g. `"5411"` = grocery stores) -- the same code, defined by an
international standard (ISO 18245), regardless of which bank or country it comes from.

You maintain a file (`mcc_categories.yaml`) that says "code X maps to my category Y." On every
sync, `bank-sync`:

1. Reads the incoming transaction's code.
2. Looks it up in your mapping file.
3. If found, looks for that category (by name) among your existing Expense Categories.
4. If found, assigns that category automatically to the newly-created expense.
5. If any step fails (unmapped code, category doesn't exist, name mismatch) -- **no blocking
   errors**: the expense still gets created, simply without a category, exactly as it would have
   without this feature.

### Concrete example

```yaml
mcc_mappings:
  "5411": "Groceries"
  "5812": "Restaurants"
```

If a transaction arrives with `merchant_category_code: "5411"`, and you already have a category
named exactly "Groceries" in Net Worth Suite, that expense is created already categorized -- zero
manual work.

### Why not every transaction gets categorized

Not every transaction carries a `merchant_category_code`: bank transfers, cash withdrawals, or
non-card payments often don't have one at all -- those stay uncategorized, same as any manually
logged expense where you didn't pick one. That's expected behavior, not a defect.

### Extending the mapping

`mcc_categories.example.yaml` already includes a starter mapping for the most common categories
(groceries, restaurants, transport, bills, health, shopping, entertainment, travel). You can add
any other code by looking it up in `mcc_categories.md` (a table of roughly 150 common codes) -- the
full official list has around 700 codes; any code not covered there can still be added to the file
by hand, the system isn't limited to what's listed.

## 5. What it deliberately does NOT do

- **Doesn't invent categories**: it only maps to categories you've already created in Expense
  Categories. If the name in the file doesn't exactly match (case-insensitive, but spelling must
  match) an existing category, the expense stays uncategorized and a warning is logged.
- **Doesn't detect transfers or refunds automatically**: every captured transaction is always a
  plain expense or income. Moving money between your own accounts, or receiving a refund, still
  needs to be logged by hand via the Transfer/Refund options already in Transactions.
- **Doesn't pick between multiple accounts at the same bank**: if a bank session covers more than
  one account (e.g. several Revolut currency wallets), only the first one returned gets synced. For
  a specific account, point `cash_account_id` accordingly and re-authorize.

## 6. FAQ

**What happens if I rename or delete a category after writing the mapping?**
Nothing breaks -- on the next sync cycle, `bank-sync` re-reads your existing categories from Net
Worth Suite live (it doesn't cache them), so the change is picked up automatically, no restart
needed.

**Can I have different mappings for different banks?**
The MCC mapping is single and shared across every link (code "5411" always means grocery stores,
regardless of which bank generated it), but if a specific bank never sends
`merchant_category_code` for certain transactions, those simply stay uncategorized from that bank.

**How do I check it's working?**
The status page (`http://<host>:8003/`) shows the last sync time and any last error per link. The
container log (`docker logs networth-suite-bank-sync`) shows how many new transactions were
captured each cycle, and every failed MCC-mapping warning.
