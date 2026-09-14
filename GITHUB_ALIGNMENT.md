# Code state: local vs. GitHub — comparison and what's missing

Comparison done by actually cloning `https://github.com/filippobellucci/networth-suite` (main,
latest commit `5d458d3`, 2026-09-13) and diffing it file-by-file against the package delivered
today -- not a guess, a real comparison.

## Good news: most of the work IS already on GitHub

I compared the most critical files in person (`main.py`, `models.py`, `schemas.py`, `xirr.py`,
`valuation.py`, `format.ts`, `Transactions.tsx`) -- **they come out identical** between local and
GitHub. This means the following features are already correctly published:

- Mobile layout
- Expenses feature (categories, transactions, voucher accounts)
- Sidebar consolidation (Allocation, Expenses)
- Customizable color palettes
- Cash account archiving (instead of destructive deletion)
- Transfers between accounts
- Refunds (excluded from statistics)
- Pension Fund excluded from the XIRR calculation
- Comma and period support in numeric fields

## What's actually missing from GitHub

### 1. The entire `bank-sync` service -- never pushed, ever

I searched the **entire** commit history (not just the latest one) -- `services/bank-sync/` never
appears, in any commit, since the project started. This matters because during setup on the NAS,
the `docker-compose.yml` pointed to
`https://github.com/.../....git#main:services/bank-sync` for the build -- if the container started
successfully at that point, it was most likely running code that existed **only locally/
temporarily** at that moment, not a version actually saved on GitHub. In other words: **the
bank-sync currently running on your NAS may not correspond to any version ever saved on GitHub**,
including the most important fixes found recently (the date bug that would have crashed every
sync, the correct reading of `credit_debit_indicator`, pagination, and automatic MCC
categorization).

**Recommended action**: push again with today's package (which includes all these fixes), then
rebuild on the NAS to make sure the container is running the correct, most recent code.

### 2. `ROADMAP.md`

Present locally, absent on GitHub. Contains the planned future features -- doesn't block anything
functional, but worth aligning.

### 3. `docker-compose.yml` and `.gitignore`

Different between local and GitHub -- the differences are exactly the `bank-sync` service block and
its related exclusion rules (`links.yaml`, `secrets/`, `mcc_categories.yaml`). Direct consequence
of point 1, resolved by the same push.

### 4. A file that should have been removed but is still on GitHub

`services/core-networth/app/debug_xirr.py` -- a diagnostic script removed locally a while ago (no
longer imported anywhere in the app), but never removed from the remote repository. Harmless
(nothing runs it), but it's dead code worth cleaning up in the next push.

### 5. `README.md` — outdated on **both** sides

There's no local/remote mismatch here -- it's identical in both places, but it **no longer reflects
the real state of the project**: it only describes the original features (portfolios, live prices,
geographic allocation) and doesn't mention the mobile layout, expense management, transfers,
refunds, palette customization, or `bank-sync` anywhere. The "Architecture" section still shows
only 3 backend services (core-networth, price-feed, geo-allocation), without `bank-sync`. This
comparison document doesn't touch it, since a full rewrite is a separate deliverable -- see
`README.md` in this same package for the updated version.

## Summary of actions to align the two

1. `git add . && git commit -m "Add bank-sync service" && git push origin main` with this
   package's files -- brings in `bank-sync`, `ROADMAP.md`, updated `docker-compose.yml` and
   `.gitignore`, and removes `debug_xirr.py`.
2. Rebuild the `bank-sync` container on the NAS after pushing, to make sure it's running the
   correct version (with the date bug fix, `credit_debit_indicator`, pagination, and the new MCC
   categorization).
3. Push the updated `README.md` included in this package.
