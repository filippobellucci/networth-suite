# Working on Net Worth Suite

You are working on Net Worth Suite. The repository was just cleaned up so that the code and every
document describing it agree. Your job, in every task, is to keep it that way: a change is not
finished until the documents that describe what you touched are updated in the same commit.

## 1. Before you change anything

- For every file you are about to modify, read its section in `DESIGN_NOTES.md`. It records the
  bugs behind code that looks arbitrary or over-careful; removing the "odd" bit usually brings the
  bug back. If you still think it should change, say why.
- Look for an existing helper before writing one. Shared pieces already exist and must be reused,
  not copied:
  - backend: `_get_or_404`, `_transactions_query`, `_commit_with_idempotency` (core-networth
    `main.py`); `price_client.fx_rate_at`; `reports.flows` / `month_start` / `month_end` /
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
- Database: the only migration is "add the missing columns" (`migrate.py`). A new column must be
  nullable or have a scalar default. Renaming or dropping a column, or changing a type, has no
  migration path: stop and ask before doing it.
- Every service is independent (its own Dockerfile and requirements). Don't share code across
  services without asking.
- Don't add compatibility shims or one-off data fixes without asking.

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
| changes a convention described in this file | this file (`CLAUDE.md`) |

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
  committing, and `./run-tests.sh all` when the change touches the frontend or more than one
  service. Don't commit with anything red.

## 5. Before you say you're done

Go through this list and report it in your final message:

1. Does `./run-tests.sh` (and `lint`) pass? Paste the summary.
2. Is anything left unused by the change? Deleted.
3. `CHANGELOG.md`: entry added, index updated.
4. `DESIGN_NOTES.md`: entry added, moved or removed where needed.
5. `README.md`, `services/bank-sync/README.md`, `tests/README.md`, `.env.example`,
   `docker-compose.yml`, `CLAUDE.md`: updated where the table in section 3 says so -- or
   "not affected", with a word on why.
6. Commit message: a one-line subject, then a body saying what changed and why.

If something in this file conflicts with what the user asks, follow the user and point out the
conflict.
