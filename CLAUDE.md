# Working on Net Worth Suite

## What this project is

Net Worth Suite is a self-hosted, single-user personal finance app: net worth across several
portfolios (with historical valuation and XIRR), cash and expense tracking with budgets and
merchant rules, ETF geographic allocation, and optional automatic capture of bank transactions
(Open Banking). It runs on the owner's own machine; the data in it is real and private.

What matters most, in this order -- when two solutions compete, pick the one that respects these:

1. **Figures are right, or visibly flagged.** A wrong total that looks plausible is the worst
   possible failure. Money is converted at the rate of the day it refers to; a missing rate or
   price is surfaced, never silently replaced.
2. **The past is never rewritten.** Editing or removing something today must not change what any
   past date shows (accounts are archived, not deleted; refunds don't edit the expense).
3. **Data stays private and safe.** No cloud services, no telemetry; never commit data, `.env`,
   keys or bank configuration; every change to storage keeps existing data and backups usable.
4. **Simple to run and to change.** One `docker compose up`, plain code, no machinery that isn't
   needed yet.

Where things are: `core-networth` (portfolios, cash, expenses, valuation -- most of the logic),
`price-feed` (Yahoo Finance prices and FX), `geo-allocation` (ETF factsheet parsing), `bank-sync`
(optional bank capture), `gateway` (the only entry point for the frontend), `frontend` (React).
`README.md` describes features and setup, `DESIGN_NOTES.md` why the code is the way it is,
`CHANGELOG.md` what changed and when.

## How you work here

You are free to make whatever changes you judge best for the project: new features, refactors,
schema changes, dependency upgrades, restructuring, removing code. Nothing below needs anyone's
permission. What the rules below ask is that every change is done safely and leaves the code and
the documents in agreement: a change is not finished until the documents that describe what you
touched are updated in the same commit.

## 1. Before you change anything

- For every file you are about to modify, read its section in `DESIGN_NOTES.md`. It records the
  bugs behind code that looks arbitrary or over-careful. You may change that code; when you do,
  make sure the bug it guards against stays fixed (keep or add the test), and update the note.
- Look for an existing helper before writing one, and reuse it rather than copying it:
  - backend: `_get_or_404`, `_paginate`, `_commit_with_idempotency` (core-networth
    `app/helpers.py`); `_transactions_query` (core-networth `app/routers/expenses.py`);
    `price_client.fx_rate_at`; `reports.flows` / `month_start` / `month_end` /
    `add_months`; `valuation.resolve_cash_balance`;
  - frontend: `api/client.ts` (`request`, `filterParams`, `downloadFile`), `lib/errors.errorText`,
    `lib/format.ts`, `usePortfolioPicker` / `useLatestFetch`, `SnapshotBreakdown`,
    `RangeAreaChart`, `WarningCard`, `ResponsiveTable`, the `.field-label` / `.input` / `.btn-*` /
    `.card` CSS classes.

## 2. While you work

- Simplest code that does the job. No speculative options, no parameters nobody passes, no
  wrapper with a single caller unless it removes real duplication.
- If your change leaves something unused (a function, an export, a type, a CSS class, a
  dependency, a config variable, a file), delete it in the same change.
- Comments say what the code does now and why, in the present tense, briefly. Never "this used to",
  "previously", measurements or incident stories in code: those go in `DESIGN_NOTES.md`.
- **Database changes.** `migrate.py` adds missing columns automatically, so a new nullable column
  (or one with a scalar default) needs nothing more. Any other schema change -- renaming or
  dropping a column or table, changing a type, moving data -- is yours to make, together with its
  migration in `migrate.py`: it must keep existing data, be safe to run twice, and also bring an
  older backup up to date when it is restored. Cover it in `tests/integration/test_migrations.py`.
- **Services.** Each service has its own Dockerfile and requirements. Sharing code between them,
  merging or splitting services is allowed when it pays off; update every Dockerfile, build
  context, `docker-compose.yml`, the CI workflow and the README architecture to match.
- **Data fixes and compatibility code.** Add them when existing data or older backups need them,
  say in `DESIGN_NOTES.md` what they are for, and remove them once nothing needs them.
- **Dependencies.** Upgrade freely; run the whole suite (`./run-tests.sh all`) and check by hand
  whatever the tests don't cover (price-feed's calls to Yahoo Finance in particular).

## 3. Documents to update, and when

Update each one in the same commit as the change that makes it out of date.

| If your change... | Update |
|---|---|
| anything at all | `CHANGELOG.md` (format below) |
| fixes a bug, or makes a non-obvious choice | `DESIGN_NOTES.md`, under the file and function concerned: what went wrong / why this way |
| renames, moves or deletes code that has a `DESIGN_NOTES.md` entry | that entry (move or rename it; delete it if the code is gone -- the CHANGELOG keeps the history) |
| adds or changes a user-visible feature | `README.md` "What it does" |
| adds, renames or removes an environment variable | `.env.example`, `docker-compose.yml` and the configuration table in `README.md` -- all three must agree |
| adds a service or a port, changes how services talk to each other | `README.md` "Architecture" and "Project structure", `docker-compose.yml`, `gateway/app/registry.py`, the local-development commands in `README.md` |
| changes where data is stored, backups, or scheduled jobs | `README.md` "Your data" |
| changes bank-sync's behaviour, configuration or endpoints | `services/bank-sync/README.md` (its "How a sync works", "Configuration" and "Endpoints" sections) |
| adds a test tier, a fixture, or changes test counts noticeably | `tests/README.md` |
| changes the runtime versions (Python, Node) | the Dockerfiles, `.github/workflows/tests.yml` and the local-development section of `README.md` |
| changes a convention described in this file, or the project's purpose | this file (`CLAUDE.md`) |

Never create a new documentation file when one of these already covers the subject; extend the
right one. All documentation, comments and commit messages are in English.

### CHANGELOG.md format

- Newest first. One `## YYYY-MM-DD` heading per day; create today's if it doesn't exist, otherwise
  add to it.
- Each change is `### <Type> -- <title>`, Type one of: Added, Changed, Fixed, Removed, Refactored,
  Docs, Audit. Below it, a short description of what changed and why it matters to someone using
  or maintaining the app.
- Add the same entry to "Index by area" at the top (`- YYYY-MM-DD · <Type> -- <title>`), under
  every area it belongs to. If no area fits, add one.
- Never rewrite or delete past entries.

### DESIGN_NOTES.md format

- Sections by service, then by file (`### \`path/to/file\``), then `#### \`function\`` entries.
- An entry tells the story the code comment no longer does: the symptom, the cause, what was
  measured, what was tried. Keep the code comment to the current rule.

## 4. Tests

- Every behaviour change or bug fix comes with a test, in the cheapest tier that can see it (see
  `tests/README.md`). Check that the new test fails without your change.
- Run `./run-tests.sh fast` while working, `./run-tests.sh` and `./run-tests.sh lint` before
  committing, and `./run-tests.sh all` when the change touches the frontend, more than one
  service, the database schema or the dependencies. Don't commit with anything red.
- **A tier that cannot run is not a tier that passed.** On a machine without the project's Python
  dependencies, four tiers and `ruff` fail together with `No module named pytest`
  (`tests/README.md`, "If the Python tiers say `No module named pytest`"). Then CI is the gate:
  push the branch, read the run, and report the run id and each job's result. Say that the local
  run was impossible -- never report a local summary you did not get.

## 5. Before you say you're done

Go through this list and report it in your final message:

1. Does `./run-tests.sh` (and `lint`) pass? Paste the summary.
2. Is anything left unused by the change? Deleted.
3. `CHANGELOG.md`: entry added, index updated.
4. `DESIGN_NOTES.md`: entry added, moved or removed where needed.
5. `README.md`, `services/bank-sync/README.md`, `tests/README.md`, `.env.example`,
   `docker-compose.yml`, `CLAUDE.md`: updated where the table in section 3 says so -- or
   "not affected", with a word on why.
6. Anything you couldn't verify (behaviour the tests don't reach, a manual check you couldn't
   run): say so plainly.
7. Commit message: a one-line subject, then a body saying what changed and why.
8. Section 6: branch pushed, CI green on the exact commit you are about to merge.

## 6. Getting your work onto `main`

**You merge your own work. Nobody approves it for you: the tests are the gate.**

1. Work on your own branch, `agent/<your-name>/<slug>`, created from an up-to-date `origin/main`.
   If the shared checkout is on someone else's branch or is dirty, don't switch it and don't reset
   anything: `git worktree add ../networth-suite-<your-name> -b agent/<your-name>/<slug>
   origin/main` and work there.
2. Commit, then push the branch. The CI workflow runs on every push, on every branch.
3. Merge only when all four are true:
   - `./run-tests.sh` and `./run-tests.sh lint` pass locally (`all` when section 4 asks for it), or
     the tiers cannot run here at all and you said so -- see section 4;
   - the CI run for the **last commit of the branch** is green (`gh run list --branch <branch>`);
   - the checklist in section 5 is done, documents included;
   - nothing in the diff is data, `.env`, keys, bank configuration, a database file, `backups/`,
     or a build artefact.
4. Merge fast-forward, never with force:

   ```
   git fetch origin
   git rebase origin/main      # if this changes anything, push the branch and wait for CI again
   git push origin HEAD:main
   ```

   A rebase that moves your commits produces code no CI run has ever seen. Push the branch, wait
   for green, then merge. **Never merge a branch whose green CI run is on different code.**
5. Delete the branch, local and remote, once it is on `main`.

**If `main` is red, that comes before anything else you were doing.** Fix it forward when the fix
is small and obvious; otherwise `git revert` the commit that broke it, push the revert, and
continue the work on a branch. Never end your turn leaving `main` red.

Never: force-push anything, rewrite published history, merge a branch that isn't yours, merge with
a red or missing CI run, merge work in the middle of which you stopped.

The checkout at `../networth-suite-main` is a separate clone kept on `main`, used to validate what
has landed. Nobody develops there.

If something in this file conflicts with what the user asks, follow the user and point out the
conflict.
