# Net Worth Suite — Implementation workflow

> **For the model reading this file.** This is the owner's work plan: every fix and open point that came out of the architectural review of commit `aa9fbec` (2026-10-29), to be implemented **all of them**, **one task at a time**, **one chat at a time**, in the fixed order below. Do not ask the owner what to work on: the state of the work is the YAML block in §B and the procedure is §A. Ask the owner **only** for the decisions §B marks as open (with the multiple-choice question tool when available) and for what to do when a task is blocked.
>
> `CLAUDE.md` still governs *how* work is done (tests, documents, merging); this file decides *what* is done and *in which order*. Line numbers quoted in the task cards refer to `aa9fbec`: code moves, so **always locate code by symbol name**, never by line.

---

## A. Autopilot protocol

### A.0 Origin

This file was added to the repository by the `WF-00` commit, so no bootstrap step is needed: the first session starts directly with `continua`. `WF-xx` commits are maintenance of this workflow, not tasks: reconciliation (§A.3) ignores them.

### A.1 Owner commands

The owner writes in Italian; the English forms are accepted too. Reply to the owner in Italian.

| The owner writes | You do |
|---|---|
| `continua` / `continue` | §A.2 → §A.8: implement the next tasks until a stop rule (§A.7) fires |
| `stato` / `status` | §A.2 and §A.3, then report: tasks done / total, next task, open decisions, new points. No changes |
| `salta <ID>` / `skip <ID>` | mark the task `skipped` with reason "skipped on request" (commit `<ID>: skipped on request`), then ask whether to continue |
| `decisione D-xx = <option>` / `decision D-xx = <option>` | record or change the decision in §B (commit `WF: record D-xx`); if it changes a decision already applied, list the completed tasks that depend on it and ask whether to reopen them |
| `ferma dopo questo` / `stop after this` | finish the current task and close the session (§A.8) |
| anything else | an ordinary request, outside this protocol |

### A.2 Synchronise

1. `git fetch origin` and start from an up-to-date `origin/main`.
2. Read `CLAUDE.md` in full and this file **from `origin/main`**: the copy in the repository is the only valid one, even if the owner attaches another.
3. Working branch: if the session environment assigns you a branch, use it (reset onto `origin/main` if it holds no unmerged work of yours); otherwise `agent/claude/<task-slug>` as in `CLAUDE.md` §6.

### A.3 Reconcile the state

1. List what git says is done: `git log origin/main --format='%H %s'`, keeping subjects that start with a task ID (`^([A-Z]+-\d+):`) present in `state.tasks`. Ignore `WF-xx` and unknown IDs.
2. Compare with `state.tasks` in §B:
   - commit found but status not `done` → set `done` and `commit: <hash>`;
   - status `done` with `commit: pending` → replace with the hash found;
   - status `done` and no commit found → set it back to `todo` and explain in `note`.
3. Put any correction in the first commit of the session.
4. Compute `next_task`: the lowest `order` among `todo` tasks whose `deps` are all `done` or `skipped`.
5. If no task is `todo`: tell the owner the workflow is complete, suggest a fresh architectural review, and stop.

### A.4 Before each task

1. **Decisions.** If the task has `decision: D-xx` and `state.decisions.D-xx` is `null`, ask the owner now. Offer the options of §2, recommended one first and labelled "(Recommended)", each with a one-line consequence. Record the answer in §B in the task's commit.
2. **D-09** (merge policy) is asked at the first run of §A.4 if still `null`, whatever the task.
3. **Already done?** If `CHANGELOG.md` or the code shows the behaviour already exists (another change may have fixed it), mark the task `done` with `note: "already satisfied by <hash or description>"` without touching code.
4. **Check the card.** Do the symbols exist? Is the problem still there (write the test: if it does not fail, the problem is gone)? If the card is partly outdated, update the card in this file in the task's commit and say so in the report. If it is entirely outdated, ask the owner whether to skip it.

### A.5 Implement the task

Follow §0.3 (common rules) and §0.4 (definition of done). In addition:

- Commit subject: `<ID>: <summary>`; the body cites the reference (`Refs: W-xx`).
- CHANGELOG entry title: `### <Type> -- <ID>: <title>`, and the same in "Index by area".
- In the **same commit**, update §B: `status: done`, `commit: pending` (the hash only exists after the commit; the next session's reconciliation fills it in), `note` if useful, and `next_task`.
- If a task needs several commits, only the last one sets `done`; earlier ones use subject `<ID>: <...> (part n)` and leave `in-progress`.
- Merge according to D-09 (§A.6) **before** starting the next task: every task starts from an up-to-date `main`.

### A.6 Merge

- **D-09 = a** (the `CLAUDE.md` default): push the branch, wait for green CI on its last commit, rebase onto `origin/main` if needed (and wait for CI again), fast-forward `main`, delete the branch. If the environment does not allow pushing to `main`, switch to mode b for this session and tell the owner.
- **D-09 = b**: all tasks of the session go on one branch as separate commits; at the end of the session open **one** PR (title `WF: <first ID>…<last ID>`), give the owner its link and stop. The next session starts only after the merge: if §A.3 finds the PR still open, remind the owner and stop.
- Either way: never merge with red or missing CI; never force-push.

### A.7 Stop rules

Stop and go to §A.8 at the first of:

1. the last task of a WP is done;
2. `state.settings.max_tasks_per_session` tasks are done (default 5);
3. a task is blocked (§A.9);
4. the conversation has grown long enough to risk mistakes: a fresh chat is better;
5. the owner wrote `ferma dopo questo`.

### A.8 Close the session

1. Append to `state.sessions` an entry `{date, tasks, outcome, next_task}` (in a `WF: session log` commit if it did not go into the last task commit).
2. Reply to the owner **in Italian**, briefly: tasks done (ID and title), CI result, PRs if any, decisions recorded, new points added, next task. End with: *"Per proseguire apri una nuova chat e scrivi: continua"*.

### A.9 Blocks and failures

- Red tests you cannot fix within the task's scope, CI red for external reasons, an environment that cannot run the tests: do not force it. Set `status: blocked` with a precise `note`, commit the state (without half-done code), and ask the owner with a multiple-choice question: *retry with a different approach* / *skip the task* / *stop here*.
- `main` red at the start of the session: fix that first (`CLAUDE.md` §6), then resume the workflow.
- Python tiers that cannot run locally: CI is the gate (`tests/README.md`), as `CLAUDE.md` §4 says.

### A.10 New points found while working

Do not fix them outside the task's scope (unless they block it). Add them to this file in the task's commit: a new reference `N-14`, `N-15`, …; a full card (format §0.6) in the right module's chapter with a free ID (e.g. `CN-25`); a manifest line in §1 with a consistent `order` (decimals allowed, e.g. `32.5`); a row in §16; a `todo` entry in §B; an entry in `state.new_points`.

---

## B. Workflow state (updated by the sessions — the source of truth together with `git log`)

```yaml
state:
  workflow_version: 2
  baseline_commit: aa9fbec
  next_task: FE-01
  settings:
    max_tasks_per_session: 5
  decisions:   # null = ask the owner at the first task that needs it
    D-01: a   # owner: the internal port must be remappable from docker-compose.yml (BANK_SYNC_INTERNAL_PORT)
    D-02: null
    D-03: d   # owner: rotating log in DATA_DIR/audit-log/, 100 MB per file, closed files zipped and all kept, clear text, not in backups
    D-04: null
    D-05: null
    D-06: null
    D-07: null
    D-08: null
    D-09: a
    D-10: null
  tasks:       # status: todo | in-progress | done | skipped | blocked; commit: hash on main | pending | null
    SH-01: {status: done, commit: a7aefc3, note: "callers not switched: BS-05 and CN-13 do it"}
    SH-02: {status: done, commit: 2aa2f8c, note: null}
    BS-01: {status: done, commit: e6e0f35, note: "internal port configurable as BANK_SYNC_INTERNAL_PORT (owner request with D-01)"}
    BS-02: {status: done, commit: 6702568, note: "re-captured VOIDED transactions get their own key (after-void); found N-14 -> CN-25"}
    BS-03: {status: done, commit: efce2f6, note: "implemented as D-03 = d (owner): card rewritten accordingly"}
    BS-04: {status: done, commit: 6625674, note: "per-loop shared clients in app/clients.py (the price_client pattern); key cached by st_mtime_ns"}
    BS-05: {status: done, commit: 5b6fcb1, note: null}
    BS-06: {status: done, commit: pending, note: "only the DB is put back: the audit log left the backups with BS-03 (card updated); no new safety copy on undo"}
    FE-01: {status: todo, commit: null, note: null}
    FE-02: {status: todo, commit: null, note: null}
    FE-03: {status: todo, commit: null, note: null}
    FE-04: {status: todo, commit: null, note: null}
    CN-01: {status: todo, commit: null, note: null}
    CN-02: {status: todo, commit: null, note: null}
    CN-03: {status: todo, commit: null, note: null}
    CN-04: {status: todo, commit: null, note: null}
    CN-05: {status: todo, commit: null, note: null}
    CN-06: {status: todo, commit: null, note: null}
    CN-07: {status: todo, commit: null, note: null}
    CN-08: {status: todo, commit: null, note: null}
    CN-09: {status: todo, commit: null, note: null}
    CN-10: {status: todo, commit: null, note: null}
    CN-11: {status: todo, commit: null, note: null}
    CN-12: {status: todo, commit: null, note: null}
    CN-13: {status: todo, commit: null, note: null}
    CN-14: {status: todo, commit: null, note: null}
    CN-15: {status: todo, commit: null, note: null}
    CN-16: {status: todo, commit: null, note: null}
    CN-17: {status: todo, commit: null, note: null}
    CN-18: {status: todo, commit: null, note: null}
    CN-19: {status: todo, commit: null, note: null}
    CN-20: {status: todo, commit: null, note: null}
    CN-21: {status: todo, commit: null, note: null}
    CN-25: {status: todo, commit: null, note: null}
    CN-22: {status: todo, commit: null, note: null}
    CN-23: {status: todo, commit: null, note: null}
    CN-24: {status: todo, commit: null, note: null}
    BS-07: {status: todo, commit: null, note: null}
    PF-01: {status: todo, commit: null, note: null}
    PF-02: {status: todo, commit: null, note: null}
    PF-03: {status: todo, commit: null, note: null}
    GA-01: {status: todo, commit: null, note: null}
    GA-02: {status: todo, commit: null, note: null}
    GA-03: {status: todo, commit: null, note: null}
    GA-04: {status: todo, commit: null, note: null}
    GA-05: {status: todo, commit: null, note: null}
    GA-06: {status: todo, commit: null, note: null}
    GW-01: {status: todo, commit: null, note: null}
    GW-02: {status: todo, commit: null, note: null}
    GW-03: {status: todo, commit: null, note: null}
    GW-04: {status: todo, commit: null, note: null}
    GW-05: {status: todo, commit: null, note: null}
    GW-06: {status: todo, commit: null, note: null}
    GW-07: {status: todo, commit: null, note: null}
    FE-05: {status: todo, commit: null, note: null}
    FE-06: {status: todo, commit: null, note: null}
    FE-07: {status: todo, commit: null, note: null}
    FE-08: {status: todo, commit: null, note: null}
    FE-09: {status: todo, commit: null, note: null}
    FE-10: {status: todo, commit: null, note: null}
    FE-11: {status: todo, commit: null, note: null}
    FE-12: {status: todo, commit: null, note: null}
    FE-13: {status: todo, commit: null, note: null}
    FE-14: {status: todo, commit: null, note: null}
    FE-15: {status: todo, commit: null, note: null}
    RF-01: {status: todo, commit: null, note: null}
    RF-02: {status: todo, commit: null, note: null}
    RF-03: {status: todo, commit: null, note: null}
    RF-04: {status: todo, commit: null, note: null}
    RF-05: {status: todo, commit: null, note: null}
    RF-06: {status: todo, commit: null, note: null}
    RF-07: {status: todo, commit: null, note: null}
    OPS-01: {status: todo, commit: null, note: null}
    OPS-02: {status: todo, commit: null, note: null}
    OPS-03: {status: todo, commit: null, note: null}
    OPS-04: {status: todo, commit: null, note: null}
    OPS-05: {status: todo, commit: null, note: null}
    OPS-06: {status: todo, commit: null, note: null}
    DOC-01: {status: todo, commit: null, note: null}
    DOC-02: {status: todo, commit: null, note: null}
    OPT-01: {status: todo, commit: null, note: null}
    OPT-02: {status: todo, commit: null, note: null}
    OPT-03: {status: todo, commit: null, note: null}
    OPT-04: {status: todo, commit: null, note: null}
    OPT-05: {status: todo, commit: null, note: null}
  new_points:      # N-14… added by the sessions (§A.10)
    - {id: N-14, found_in: BS-02, task: CN-25, summary: "a key reserved by a request that died before storing its response answers 409 until the TTL, then the retry creates a duplicate"}
  sessions:        # {date, tasks, outcome, next_task} (§A.8)
    - {date: 2026-10-31, tasks: [SH-01, SH-02], outcome: "WP-01 done; D-09 = a recorded; both merged fast-forward after green CI", next_task: BS-01}
    - {date: 2026-10-31, tasks: [BS-01], outcome: "D-01 = a recorded (internal port remappable via BANK_SYNC_INTERNAL_PORT); merged fast-forward after green CI; stopped for a fresh chat (A.7.4)", next_task: BS-02}
    - {date: 2026-10-31, tasks: [BS-02, BS-03], outcome: "D-03 = d recorded (owner's own option: size-rotated zipped local log, not in backups); new point N-14 -> CN-25; both merged fast-forward after green CI; stopped for a fresh chat (A.7.4)", next_task: BS-04}
    - {date: 2026-10-31, tasks: [BS-04, BS-05, BS-06], outcome: "WP-02 done (BS-07 runs after CN-19); each merged fast-forward after green CI; stopped at the end of the WP (A.7.1)", next_task: FE-01}
```

---

## 0. Common rules

### 0.1 Layout of this file

```
§A  Autopilot protocol (commands, reconciliation, decisions, merge, stop rules, blocks)
§B  Workflow state (YAML, updated by the sessions)
§0  Common rules, definition of done, card format
§1  Manifest: every task with its global order and dependencies
§2  Decisions (D-xx) with the recommended option
§3  Execution sequence and cross-module dependencies
§4… One chapter per module with its task cards
§16 Traceability: review finding (W-xx / N-xx) → tasks
```

### 0.2 Identifiers

- `W-01 … W-48`: weaknesses numbered in the architectural review (its §15).
- `N-01 … N-13`: open points from the review outside the W list (its feature cards and §16), numbered here; new ones continue from `N-14`.
- Tasks: module prefix + number. `SH` shared, `BS` bank-sync, `CN` core-networth, `PF` price-feed, `GA` geo-allocation, `GW` gateway, `FE` frontend, `RF` structural refactoring, `OPS` infrastructure/CI, `DOC` documentation clean-up, `OPT` final evolutions.
- Decisions: `D-01 …`.
- The binding order is `order` in the manifest (§1, §3.1).

### 0.3 Rules common to every task

1. **Before starting**: §A.2–§A.4.
2. Read `CLAUDE.md` in full and, for every file you will touch, its section in `DESIGN_NOTES.md` (each card names the relevant ones).
3. **Branch**: §A.2.
4. **Test first**: write the test that reproduces the problem in the cheapest tier given, check that it **fails** on the current code, then fix and check that it passes (`CLAUDE.md` §4).
5. Run `./run-tests.sh fast` while working; `./run-tests.sh` and `./run-tests.sh lint` before committing; `./run-tests.sh all` when the task touches the frontend, more than one service, the database schema or dependencies. If the Python tiers cannot run (`No module named pytest`), CI is the gate: say so explicitly (`tests/README.md`).
6. **Documents in the same commit**: always `CHANGELOG.md` (entry + index by area); `DESIGN_NOTES.md` for every bug fixed or non-obvious choice; README / `.env.example` / `docker-compose.yml` / `services/bank-sync/README.md` / `tests/README.md` when the table in `CLAUDE.md` §3 requires it. Each card lists the expected ones.
7. **Database schema**: new nullable columns, or columns with a scalar default, need nothing; any other change (unique indexes, constraints, data) goes in `migrate.py`, idempotent, valid on old backups too, covered in `tests/integration/test_migrations.py`.
8. **New environment variables**: `.env.example`, `docker-compose.yml` and the README "Configuration" table must agree.
9. **Do not widen the scope**: do what the card asks. A new problem goes through §A.10.
10. **Merge**: §A.6, according to D-09.

### 0.4 Definition of done (every task)

- [ ] A new test that fails without the change and passes with it.
- [ ] The required suite is green (or CI is green when local runs are impossible, with the run id).
- [ ] Every acceptance criterion of the card is met.
- [ ] The listed documents are updated in the same commit.
- [ ] Nothing is left unused (`CLAUDE.md` §2).
- [ ] §B updated in the same commit (§A.5).
- [ ] At the end of the session, the report of §A.8 (which includes the `CLAUDE.md` §5 checklist).

### 0.5 What the owner writes

Nothing beyond the §A.1 commands. In a new chat, **`continua`** is enough: everything else is in this file or is asked through the §A.4 questions.

### 0.6 Card format

```
### <ID> · <title>
- Ref: W-xx / N-xx        Severity: Critical|High|Medium|Low        Size: S|M|L
- Depends on: <tasks>     Unblocks: <tasks>
- Files: <paths, symbols>
- DESIGN_NOTES to read: <sections>
- Problem: <verified fact>
- What to do: <numbered steps>
- Constraints / watch out: <invariants to keep, known traps>
- Tests: <tier, file, what to assert>
- Documents: <what to update>
- Acceptance: <verifiable conditions>
```

Indicative size: S < half a day, M ≈ one day, L > one day.

---

## 1. Task manifest (compact, machine-readable)

```yaml
# order = position in the single execution sequence; deps = tasks to finish first
# decision = decision to ask the owner if §B has not recorded it yet
wp:
  WP-01: {module: shared, title: "Common foundations"}
  WP-02: {module: bank-sync, title: "Security and reliability of bank capture"}
  WP-03: {module: core-networth, title: "Correct figures, untouched past"}
  WP-04: {module: core-networth, title: "Robustness, performance, supporting APIs"}
  WP-05: {module: price-feed, title: "Quote currencies and caches"}
  WP-06: {module: geo-allocation, title: "Safe upload, storage and restore"}
  WP-07: {module: gateway, title: "Proxy, security, distributed restore"}
  WP-08: {module: frontend, title: "Bugs, incompleteness warnings, UX (FE-01…FE-04 run right after WP-02)"}
  WP-09: {module: cross, title: "Structural refactoring"}
  WP-10: {module: infra, title: "Containers, CI, observability"}
  WP-11: {module: docs, title: "Final clean-up"}
  WP-12: {module: final, title: "Final evolutions (some need a decision)"}
tasks:
  - {id: SH-01, wp: WP-01, order: 1, ref: [W-18], sev: High, size: S, deps: []}
  - {id: SH-02, wp: WP-01, order: 2, ref: [N-11], sev: Low, size: S, deps: []}
  - {id: BS-01, wp: WP-02, order: 3, ref: [W-11], sev: Critical, size: M, deps: [], decision: D-01}
  - {id: BS-02, wp: WP-02, order: 4, ref: [W-17], sev: Critical, size: M, deps: []}
  - {id: BS-03, wp: WP-02, order: 5, ref: [W-12], sev: High, size: S, deps: [], decision: D-03}
  - {id: BS-04, wp: WP-02, order: 6, ref: [W-27], sev: Medium, size: S, deps: []}
  - {id: BS-05, wp: WP-02, order: 7, ref: [W-18], sev: Medium, size: S, deps: [SH-01]}
  - {id: BS-06, wp: WP-02, order: 8, ref: [W-19], sev: High, size: S, deps: []}
  - {id: FE-01, wp: WP-08, order: 9, ref: [W-30], sev: High, size: S, deps: []}
  - {id: FE-02, wp: WP-08, order: 10, ref: [W-31], sev: High, size: S, deps: [], decision: D-07}
  - {id: FE-03, wp: WP-08, order: 11, ref: [W-33, N-08], sev: Medium, size: S, deps: []}
  - {id: FE-04, wp: WP-08, order: 12, ref: [W-13], sev: Medium, size: S, deps: []}
  - {id: CN-01, wp: WP-03, order: 13, ref: [W-03], sev: High, size: S, deps: []}
  - {id: CN-02, wp: WP-03, order: 14, ref: [W-01], sev: High, size: S, deps: []}
  - {id: CN-03, wp: WP-03, order: 15, ref: [W-02], sev: High, size: M, deps: [CN-02], decision: D-02}
  - {id: CN-04, wp: WP-03, order: 16, ref: [W-01], sev: High, size: M, deps: [CN-02]}
  - {id: CN-05, wp: WP-03, order: 17, ref: [W-01, W-04], sev: High, size: M, deps: [CN-02]}
  - {id: CN-06, wp: WP-03, order: 18, ref: [W-01], sev: High, size: M, deps: [CN-02]}
  - {id: CN-07, wp: WP-03, order: 19, ref: [W-05], sev: Medium, size: S, deps: []}
  - {id: CN-08, wp: WP-03, order: 20, ref: [W-06], sev: High, size: M, deps: [], decision: D-04}
  - {id: CN-09, wp: WP-03, order: 21, ref: [W-09], sev: Medium, size: S, deps: [], decision: D-06}
  - {id: CN-10, wp: WP-03, order: 22, ref: [W-10, N-13], sev: Low, size: S, deps: [], decision: D-05}
  - {id: CN-11, wp: WP-03, order: 23, ref: [N-01], sev: Medium, size: S, deps: []}
  - {id: CN-12, wp: WP-03, order: 24, ref: [W-34], sev: Medium, size: S, deps: []}
  - {id: CN-13, wp: WP-04, order: 25, ref: [W-18], sev: High, size: L, deps: [SH-01, CN-04, CN-05, CN-06]}
  - {id: CN-14, wp: WP-04, order: 26, ref: [W-19], sev: High, size: M, deps: []}
  - {id: CN-15, wp: WP-04, order: 27, ref: [W-21], sev: Medium, size: M, deps: []}
  - {id: CN-16, wp: WP-04, order: 28, ref: [W-22], sev: Medium, size: M, deps: []}
  - {id: CN-17, wp: WP-04, order: 29, ref: [W-24], sev: Medium, size: S, deps: []}
  - {id: CN-18, wp: WP-04, order: 30, ref: [W-25], sev: Medium, size: S, deps: [CN-17]}
  - {id: CN-19, wp: WP-04, order: 31, ref: [W-29], sev: Low, size: S, deps: []}
  - {id: CN-20, wp: WP-04, order: 32, ref: [W-35], sev: Medium, size: M, deps: []}
  - {id: CN-21, wp: WP-04, order: 33, ref: [W-36], sev: Medium, size: S, deps: [CN-20]}
  - {id: CN-25, wp: WP-04, order: 33.5, ref: [N-14], sev: Low, size: S, deps: [CN-21]}
  - {id: CN-22, wp: WP-04, order: 34, ref: [N-02], sev: Low, size: S, deps: []}
  - {id: CN-23, wp: WP-04, order: 35, ref: [W-45], sev: Low, size: S, deps: []}
  - {id: CN-24, wp: WP-04, order: 36, ref: [W-26], sev: Medium, size: S, deps: []}
  - {id: BS-07, wp: WP-02-tail, order: 37, ref: [W-29], sev: Low, size: S, deps: [CN-19]}
  - {id: PF-01, wp: WP-05, order: 38, ref: [W-07], sev: Medium, size: M, deps: []}
  - {id: PF-02, wp: WP-05, order: 39, ref: [W-26], sev: Medium, size: S, deps: []}
  - {id: PF-03, wp: WP-05, order: 40, ref: [W-45], sev: Low, size: S, deps: []}
  - {id: GA-01, wp: WP-06, order: 41, ref: [W-18], sev: Medium, size: S, deps: []}
  - {id: GA-02, wp: WP-06, order: 42, ref: [W-15], sev: Low, size: S, deps: []}
  - {id: GA-03, wp: WP-06, order: 43, ref: [N-05], sev: Low, size: S, deps: []}
  - {id: GA-04, wp: WP-06, order: 44, ref: [W-19], sev: High, size: M, deps: []}
  - {id: GA-05, wp: WP-06, order: 45, ref: [W-20], sev: Low, size: S, deps: []}
  - {id: GA-06, wp: WP-06, order: 46, ref: [W-45], sev: Low, size: S, deps: []}
  - {id: GW-01, wp: WP-07, order: 47, ref: [W-27], sev: Medium, size: S, deps: []}
  - {id: GW-02, wp: WP-07, order: 48, ref: [W-14], sev: Medium, size: S, deps: [GW-01]}
  - {id: GW-03, wp: WP-07, order: 49, ref: [N-06], sev: Low, size: S, deps: []}
  - {id: GW-04, wp: WP-07, order: 50, ref: [N-07, W-45], sev: Low, size: S, deps: []}
  - {id: GW-05, wp: WP-07, order: 51, ref: [W-28], sev: Low, size: S, deps: [GW-01]}
  - {id: GW-06, wp: WP-07, order: 52, ref: [W-19], sev: High, size: M, deps: [CN-14, GA-04, BS-06]}
  - {id: GW-07, wp: WP-07, order: 53, ref: [W-20], sev: Low, size: S, deps: [GA-05]}
  - {id: FE-05, wp: WP-08, order: 54, ref: [W-32], sev: Medium, size: M, deps: []}
  - {id: FE-06, wp: WP-08, order: 55, ref: [W-01], sev: High, size: M, deps: [CN-04, CN-05, CN-06, FE-05]}
  - {id: FE-07, wp: WP-08, order: 56, ref: [W-02], sev: High, size: S, deps: [CN-03]}
  - {id: FE-08, wp: WP-08, order: 57, ref: [W-09], sev: Medium, size: S, deps: [CN-09]}
  - {id: FE-09, wp: WP-08, order: 58, ref: [W-34], sev: Medium, size: S, deps: [CN-12]}
  - {id: FE-10, wp: WP-08, order: 59, ref: [W-25], sev: Medium, size: S, deps: [CN-18]}
  - {id: FE-11, wp: WP-08, order: 60, ref: [W-35], sev: Medium, size: M, deps: [CN-20]}
  - {id: FE-12, wp: WP-08, order: 61, ref: [W-36], sev: Medium, size: S, deps: [FE-01, CN-21]}
  - {id: FE-13, wp: WP-08, order: 62, ref: [W-21], sev: Medium, size: S, deps: [CN-15]}
  - {id: FE-14, wp: WP-08, order: 63, ref: [W-38], sev: Low, size: M, deps: []}
  - {id: FE-15, wp: WP-08, order: 64, ref: [W-45], sev: Low, size: S, deps: []}
  - {id: RF-01, wp: WP-09, order: 65, ref: [W-40], sev: Medium, size: S, deps: [CN-06, CN-17]}
  - {id: RF-02, wp: WP-09, order: 66, ref: [W-41], sev: Medium, size: S, deps: [CN-03, CN-20]}
  - {id: RF-03, wp: WP-09, order: 67, ref: [W-39], sev: Medium, size: M, deps: [RF-01, RF-02]}
  - {id: RF-04, wp: WP-09, order: 68, ref: [W-42], sev: Medium, size: M, deps: [CN-14, GA-04, BS-06]}
  - {id: RF-05, wp: WP-09, order: 69, ref: [W-43], sev: Medium, size: M, deps: [RF-03]}
  - {id: RF-06, wp: WP-09, order: 70, ref: [W-44], sev: Low, size: S, deps: [CN-16]}
  - {id: RF-07, wp: WP-09, order: 71, ref: [W-37], sev: Low, size: L, deps: [RF-05, FE-05]}
  - {id: OPS-01, wp: WP-10, order: 72, ref: [N-03, N-04], sev: Low, size: S, deps: []}
  - {id: OPS-02, wp: WP-10, order: 73, ref: [W-16, W-48], sev: Low, size: M, deps: [OPS-01, BS-01]}
  - {id: OPS-03, wp: WP-10, order: 74, ref: [W-47], sev: Low, size: S, deps: [BS-01]}
  - {id: OPS-04, wp: WP-10, order: 75, ref: [W-46, N-09], sev: Low, size: M, deps: [CN-13]}
  - {id: OPS-05, wp: WP-10, order: 76, ref: [N-10], sev: Low, size: S, deps: []}
  - {id: OPS-06, wp: WP-10, order: 77, ref: [W-45], sev: Low, size: S, deps: []}
  - {id: DOC-01, wp: WP-11, order: 78, ref: [W-45], sev: Low, size: S, deps: []}
  - {id: DOC-02, wp: WP-11, order: 79, ref: [W-45], sev: Low, size: M, deps: [OPS-04]}
  - {id: OPT-01, wp: WP-12, order: 80, ref: [W-08], sev: Medium, size: L, deps: [RF-03], decision: D-08}
  - {id: OPT-02, wp: WP-12, order: 81, ref: [W-23], sev: Low, size: M, deps: []}
  - {id: OPT-03, wp: WP-12, order: 82, ref: [N-12], sev: Low, size: M, deps: [BS-02]}
  - {id: OPT-04, wp: WP-12, order: 83, ref: [W-38], sev: Low, size: L, deps: [], decision: D-10}
  - {id: OPT-05, wp: WP-12, order: 84, ref: [W-38], sev: Low, size: S, deps: []}
```

---

## 2. Decisions

Each decision has a **recommended** option. The session asks the owner when it reaches the first task that needs it (§A.4), records the answer in `state.decisions`, and never asks again.

| ID | Needed by | Question | Options | Recommended |
|---|---|---|---|---|
| D-01 | BS-01 | How to take bank-sync's internal endpoints off the public port? | (a) two uvicorn servers in one process: public `:8003` (`/`, `/authorize/*`, `/callback`, `/health`), internal `:8004` not published (everything else); (b) apply `API_KEY` to everything except `/authorize`, `/callback`, `/health` (still open with an empty `API_KEY`, the default); (c) an external reverse proxy, documented | **(a)** |
| D-02 | CN-03 | A cross-currency transfer when no rate is available | (a) refuse with 409; (b) optional `received_amount` field (the amount actually credited), 409 only when both the rate and the field are missing | **(b)** |
| D-03 | BS-03 | The raw audit log of bank transactions | (a) keep it, mask account identifiers, add a configurable retention; (b) off by default; (c) remove it; (d) *owner's choice*: a local folder, files rotated by size (100 MB) and zipped when closed, all kept, clear text, not in backups | **(a)**, default retention 365 days -- **chosen: (d)** |
| D-04 | CN-08 | The app's time zone | (a) a `TZ` variable in compose (default `Europe/Rome`), every "today" computed in that zone, future dates refused instead of clipped; (b) document only | **(a)** |
| D-05 | CN-10 | Should a deleted automatic snapshot be recreated? | (a) no: a tombstone ("skipped" date), no backfill; (b) yes, but the UI warns it will be recomputed from current data | **(a)** |
| D-06 | CN-09 | Changing the currency of an account/asset that has history | (a) forbidden (400) when balances/transactions/manual prices exist; (b) allowed with an explicit confirmation (`confirm_rewrite_history=true`) | **(a)** |
| D-07 | FE-02 | Accounts tagged STOCK/BOND (invisible today) | (a) an "Other balances" section in PortfolioDetail for categories no section covers; (b) stop offering STOCK/BOND | **(a)** ((b) does not fix existing accounts) |
| D-08 | OPT-01 | Money from `float` to `Decimal`/Money | (a) yes, full migration; (b) no, document the choice in DESIGN_NOTES | **(b)**, unless there is a concrete error case |
| D-09 | first task | Merge policy | (a) as `CLAUDE.md` §6: the session fast-forwards `main` after green CI, no owner step; (b) one PR per session, the owner merges before the next session | **(a)**: no manual step |
| D-10 | OPT-04 | Interface language | (a) Italian and English with a switcher; (b) Italian only | **(a)** |

---

## 3. Execution sequence and dependencies

### 3.1 Single execution sequence

```
  1. SH-01
  2. SH-02
  3. BS-01
  4. BS-02
  5. BS-03
  6. BS-04
  7. BS-05
  8. BS-06
  9. FE-01
 10. FE-02
 11. FE-03
 12. FE-04
 13. CN-01
 14. CN-02
 15. CN-03
 16. CN-04
 17. CN-05
 18. CN-06
 19. CN-07
 20. CN-08
 21. CN-09
 22. CN-10
 23. CN-11
 24. CN-12
 25. CN-13
 26. CN-14
 27. CN-15
 28. CN-16
 29. CN-17
 30. CN-18
 31. CN-19
 32. CN-20
 33. CN-21
 33.5 CN-25
 34. CN-22
 35. CN-23
 36. CN-24
 37. BS-07
 38. PF-01
 39. PF-02
 40. PF-03
 41. GA-01
 42. GA-02
 43. GA-03
 44. GA-04
 45. GA-05
 46. GA-06
 47. GW-01
 48. GW-02
 49. GW-03
 50. GW-04
 51. GW-05
 52. GW-06
 53. GW-07
 54. FE-05
 55. FE-06
 56. FE-07
 57. FE-08
 58. FE-09
 59. FE-10
 60. FE-11
 61. FE-12
 62. FE-13
 63. FE-14
 64. FE-15
 65. RF-01
 66. RF-02
 67. RF-03
 68. RF-04
 69. RF-05
 70. RF-06
 71. RF-07
 72. OPS-01
 73. OPS-02
 74. OPS-03
 75. OPS-04
 76. OPS-05
 77. OPS-06
 78. DOC-01
 79. DOC-02
 80. OPT-01
 81. OPT-02
 82. OPT-03
 83. OPT-04
 84. OPT-05
```

FE-01…FE-04 (frontend bugs with no backend dependency, two of them serious) run right after bank-sync. BS-07 runs after CN-19, which it needs.

### 3.2 Cross-module dependencies

| Downstream task | Needs | Why |
|---|---|---|
| BS-05 | SH-01 | uses the non-blocking e-mail send |
| BS-07 | CN-19 | uses the account balance endpoint |
| CN-03, CN-04, CN-05, CN-06 | CN-02 | use the "rate with outcome" API |
| CN-13 | SH-01, CN-04…06 | moves to threads the synchronous parts those tasks changed |
| GW-06 | CN-14, GA-04, BS-06 | the distributed restore uses the undo endpoints |
| GW-07 | GA-05 | uses the orphan clean-up endpoint |
| FE-06 | CN-04, CN-05, CN-06, FE-05 | shows the incompleteness flags |
| FE-07 | CN-03 | received amount field |
| FE-08 | CN-09 | message for the locked currency |
| FE-09 | CN-12 | per-currency totals |
| FE-10 | CN-18 | refund candidates endpoint |
| FE-11 | CN-20 | composite endpoints |
| FE-12 | FE-01, CN-21 | idempotency keys |
| FE-13 | CN-15 | job status |
| OPS-02, OPS-03 | BS-01 | bank-sync's new ports/mounts |
| RF-04 | CN-14, GA-04, BS-06 | moves the modified backup code into `shared/` |

### 3.3 One chat at a time

The protocol assumes a single chat works on the workflow at any time. If the owner opens several in parallel, reconciliation (§A.3) only notices afterwards: in that case the session stops and asks.

---

## 4. WP-01 · shared — Common foundations

Context: `shared/` is copied into the core, geo and bank-sync images (repository-root build context, `COPY shared ./shared`). It holds `backup_retention.py` and `notify.py`.

### SH-01 · E-mail sending that does not block the event loop
- Ref: W-18 · Severity: High · Size: S
- Depends on: — · Unblocks: BS-05, CN-13
- Files: `shared/notify.py` (`send`); callers: `services/core-networth/app/alerts.py` (`check_budgets_over`), `services/bank-sync/app/alerts.py` (`check_consent_expiry`, `note_sync_result`).
- DESIGN_NOTES to read: `shared/notify.py`, core-networth `alerts.py`, bank-sync `app/alerts.py`.
- Problem: `send` uses synchronous `smtplib` (10 s timeout) and is called from coroutines: the whole service stalls while it sends.
- What to do:
  1. Add `async def send_async(subject, body) -> bool` to `notify.py`, running `send` through `asyncio.to_thread`.
  2. Do not switch the callers yet (BS-05 and CN-13 do), unless trivial and in the same service: then say so in the CHANGELOG.
- Constraints: `send` keeps its semantics (False and no connection when the channel is off; never raises).
- Tests: unit `tests/unit/test_notify.py`: `send_async` returns what `send` returns with a fake SMTP; with the channel off it attempts no connection.
- Documents: CHANGELOG (Changed), DESIGN_NOTES `shared/notify.py` (why the async variant exists).
- Acceptance: `send_async` exists and is tested; nothing changes for current callers.

### SH-02 · SMTPS support (implicit TLS, port 465)
- Ref: N-11 · Severity: Low · Size: S · Depends on: —
- Files: `shared/notify.py`, `.env.example`, `docker-compose.yml` (core and bank-sync), README "Configuration".
- Problem: STARTTLS only; many providers use 465 with implicit TLS.
- What to do: new variable `SMTP_USE_SSL` (default `false`); when true use `smtplib.SMTP_SSL` and ignore `SMTP_USE_TLS`.
- Tests: unit with a fake `SMTP_SSL`.
- Documents: the three environment-variable sources (§0.3.8), CHANGELOG (Added).
- Acceptance: mail can be sent through 465; the default is unchanged.

---

## 5. WP-02 · bank-sync — Security and reliability of bank capture

Context: `services/bank-sync/app/{main,sync,enable_banking,backup,csv_log,alerts}.py`. Read `services/bank-sync/README.md` and the "bank-sync" section of `DESIGN_NOTES.md` first. Existing tests: `tests/unit/test_bank_sync_*.py`, `tests/system/test_backup_restore.py`, `tests/system/test_gateway.py`.

### BS-01 · Separate the public surface from the internal one — DECISION D-01
- Ref: W-11 · Severity: **Critical** · Size: M
- Depends on: — · Unblocks: OPS-02, OPS-03
- Files: `services/bank-sync/app/main.py` (every route), `services/bank-sync/Dockerfile` (`CMD`), `docker-compose.yml` (`bank-sync` service, the gateway's `BANK_SYNC_URL`), `tests/conftest.py` (`stack` fixture, `BANK_SYNC_URL`), `gateway/app/registry.py` (only if the default changes).
- DESIGN_NOTES to read: bank-sync `main.callback`, `backup.py`.
- Problem: port 8003 is published on the host and serves, unauthenticated, `/backup/export`, `/backup/restore`, `/backup/preview`, `/backup/stats`, `/transactions-log.csv`, `/helper/*`, `/status`, `/sync-now` (a GET with side effects). The gateway's `API_KEY` does not cover it.
- What to do (recommended option D-01a):
  1. Split the routes into two `APIRouter`s: **public** (`GET /`, `GET /authorize/{label}`, `GET /callback`, `GET /health`) and **internal** (everything else, plus `GET /health`).
  2. Build two FastAPI apps sharing state and locks in one process (`public_app`, `internal_app`); the lifespan work (re-reading `links.yaml`, the scheduler) must run **once**.
  3. Start them with a small entrypoint (`app/serve.py`) creating two `uvicorn.Server`s (ports 8003 and 8004) run with `asyncio.gather`; update the Dockerfile `CMD`.
  4. `docker-compose.yml`: publish 8003 only, `expose: ["8004"]`; `BANK_SYNC_URL: http://bank-sync:8004` on the gateway.
  5. Make `/sync-now` a `POST` on the internal app and drop the "Sync all now" link from the public status page (it stays reachable from the app through the gateway).
  6. The public status page no longer links `/transactions-log.csv` (now internal).
  7. Update `tests/conftest.py`: start bank-sync through the new entrypoint, `BANK_SYNC_URL` on the internal port.
- Constraints: `PUBLIC_BASE_URL/callback` does not change (it is registered with Enable Banking). `_sync_lock` and `_auth_states` must be shared by both apps (same module). The scheduler must not start twice.
- Tests:
  - system (new, in `tests/system/test_gateway.py` or a new `test_bank_sync_surface.py`): on the public port `GET /backup/export`, `/transactions-log.csv`, `/helper/accounts`, `/status` → 404; `/authorize/<label>` and `/callback` reachable; through the gateway `/api/bank/status` works.
  - unit: `POST /sync-now` on the internal app; `GET /sync-now` → 405.
- Documents: `services/bank-sync/README.md` ("Endpoints" with a public/internal column; "Setup" steps 3 and 5 — the helpers are now called through the gateway: `curl http://<host>:8080/api/bank/helper/accounts`, with `X-API-Key` if set), README "Architecture"/"Project structure" (internal port), `docker-compose.yml`, `gateway/app/registry.py` if the default changes, CHANGELOG (Fixed, areas bank-sync + security), DESIGN_NOTES (new bank-sync `main` entry: why two surfaces).
- Acceptance: from the host network only the 4 public routes are reachable; everything else only from the Docker network; the UI (bank-sync alerts, combined backup) works as before; `./run-tests.sh all` green.

### BS-02 · No duplicates when a cycle is interrupted: idempotency and per-transaction commits
- Ref: W-17 · Severity: **Critical** · Size: M
- Depends on: — · Unblocks: OPT-03
- Files: `services/bank-sync/app/sync.py` (`_push_to_core`, `_sync_link_locked`), `services/core-networth/app/helpers.py` (`IDEMPOTENCY_TTL_HOURS`, read only unless step 3 applies).
- DESIGN_NOTES to read: bank-sync `sync._usable_date`, `sync._mark_skipped`; core `helpers` (Idempotency).
- Problem: each transaction is created in core with a `POST` before its `SyncedTransaction` row is committed (a single `db.commit()` at the end of the cycle); a crash, restart or timeout after core has written but before that commit makes the next cycle create it again. `_push_to_core` sends no `Idempotency-Key`, which core already supports on `POST /cash-accounts/{id}/transactions`.
- What to do:
  1. `_push_to_core` takes `idempotency_key` and sends it as the `Idempotency-Key` header. Key: `f"bank-sync:{dedupe_key}"` (stable across cycles, unique per transaction).
  2. After each successful push, `db.add(SyncedTransaction(...))` and **`db.commit()` at once** (not at the end of the cycle). The same for `_mark_skipped`, `_settle_pending`, `_void`: every state change of a row is committed as soon as its effect in core has happened. The `last_synced_at` watermark still moves only at the end of a clean cycle.
  3. Check that core's idempotency TTL (24 h) covers the worst retry case (next cycle = `SYNC_INTERVAL_HOURS`, default 6). If `SYNC_INTERVAL_HOURS` may exceed 24 h, document it or make the TTL configurable; by default nothing needs to change.
  4. Treat core's 409 "still being processed" as a transient failure (retried next cycle, not counted as created).
- Constraints: do not change the `dedupe_key` format (existing data depends on it); the unstable-fallback logic (`#n`) stays identical.
- Tests (unit, `tests/unit/test_bank_sync_pending.py` or a new `test_bank_sync_idempotency.py`, with a fake core):
  - the fake core always receives the same `Idempotency-Key` for the same bank transaction across two cycles;
  - an exception after pushing the 2nd of 3 transactions: the first 2 are in the ledger, and the next cycle does not make the fake core *create* them again (or sends the same key and gets the stored response);
  - a network timeout after core wrote: the retry uses the same key.
- Documents: `services/bank-sync/README.md` "How a sync works" (step 3: idempotency, per-transaction commit), DESIGN_NOTES bank-sync `sync` (the duplicate scenario), CHANGELOG (Fixed).
- Acceptance: no interruption scenario produces two core transactions for one bank transaction.

### BS-03 · Bank audit log: rotated by size, local only — DECISION D-03
- Ref: W-12 · Severity: High · Size: S
- Files: `services/bank-sync/app/csv_log.py`, `config.py` (`AUDIT_LOG_MAX_BYTES`), `backup.py` (the log leaves the archive), `main.py` (`/transactions-log.csv`), `.env.example`, `docker-compose.yml`, README.
- Problem: `transactions_log.csv` holds every bank JSON in clear text (including any IBAN/account number), grows forever, and is part of the backups.
- What to do (D-03 = d, the owner's choice; the card originally described option a: masking and a time-based retention):
  1. The log moves to `DATA_DIR/audit-log/` as a numbered series `transactions_log-NNNN.csv`; the old `DATA_DIR/transactions_log.csv` becomes the next file of the series on the first write.
  2. When the current file reaches `AUDIT_LOG_MAX_MB` (default 100; `BANK_SYNC_AUDIT_LOG_MAX_MB` in `.env`) it is closed, compressed to `.zip` and the next number is started; closed files are all kept.
  3. Clear text: no masking (the log never leaves the machine).
  4. The log is no longer in any backup (export, daily copy, pre-restore copy); a restore does not touch it; an older archive's `transactions_log.csv` is ignored.
- Constraints: the content of a row and the growing header are unchanged; an interrupted closing must leave no data lost.
- Tests: unit on `csv_log`: the folder and numbering; a full file is zipped and followed by the next with every row once; the legacy file becomes the first; an interrupted closing is finished. Unit on `backup`: the log is in no archive or copy, a restore leaves it alone.
- Documents: environment variables (three sources), `services/bank-sync/README.md` ("How a sync works" step 4, "Configuration", "Endpoints", "Backups"), README "Your data", CHANGELOG (Changed, privacy area), DESIGN_NOTES `csv_log`.
- Acceptance: no file of the log exceeds the limit by more than one row; no backup contains bank transaction JSON.

### BS-04 · Shared HTTP clients; private key read once
- Ref: W-27 · Severity: Medium · Size: S
- Files: `services/bank-sync/app/sync.py` (`_push_to_core`, `_get_from_core`, `_patch_in_core`, `_delete_from_core`, `_app_balance`), `mcc_categories.py` (`fetch_category_name_to_id`), `main.py` (`helper_*`), `enable_banking.py` (`_request`, `_private_key`).
- Problem: a new `httpx.AsyncClient` for every call; the private key is re-read from disk on every request.
- What to do: one client for core and one for Enable Banking, created in the lifespan (or lazily per event loop, as `core/price_client._client`) and closed on shutdown; cache the private key (re-read if the file changes: compare `st_mtime`).
- Constraints: tests use fake clients/monkeypatching: keep a simple injection point.
- Tests: unit: two consecutive calls reuse the same client; the key is read once.
- Documents: CHANGELOG (Changed), DESIGN_NOTES if the per-loop pattern is chosen.
- Acceptance: no client is created per request.

### BS-05 · Non-blocking e-mail alerts in the sync cycle
- Ref: W-18 · Severity: Medium · Size: S · Depends on: SH-01
- Files: `services/bank-sync/app/alerts.py`, `sync.py` (calls to `note_sync_result`, `check_consent_expiry`).
- What to do: make `note_sync_result` and `check_consent_expiry` coroutines using `notify.send_async`; `await` them in the callers.
- Tests: unit `tests/unit/test_bank_sync_alerts.py` adapted (async).
- Documents: CHANGELOG (Changed).
- Acceptance: no synchronous `notify.send` inside bank-sync coroutines.

### BS-06 · Undo the last restore (for the distributed restore)
- Ref: W-19 · Severity: High · Size: S · Unblocks: GW-06
- Files: `services/bank-sync/app/backup.py`, `main.py` (internal routes).
- Problem: if the combined restore fails after bank-sync was restored, the only way back is by hand from the `pre-restore-…` folder.
- What to do:
  1. `restore()` returns, besides the stats, the name of the safety copy it created (`pre_restore`).
  2. New internal endpoint `POST /backup/undo-restore {"pre_restore": "<folder name>"}`: validate that the folder exists under `BACKUP_DIR` and is a `pre-restore-*` folder, then restore the DB from it (the audit CSV is no longer in any backup since BS-03) with the same procedure as `restore` (under `_sync_lock`, `engine.dispose`, migrations, re-reading `links.yaml`). It must not overwrite the chain with a new pre-restore copy: either create none, or create one named `pre-undo-…` that rotation ignores — choose and document.
- Constraints: path traversal (folder name validated with a regex and resolved with `is_relative_to`).
- Tests: unit: restore then undo-restore gives back the original stats; a malicious folder name → 400.
- Documents: `services/bank-sync/README.md` "Endpoints", DESIGN_NOTES bank-sync `backup.py`, CHANGELOG (Added).
- Acceptance: the gateway can undo a bank-sync restore with one call.

### BS-07 · Balance reconciliation without valuing the whole portfolio (runs after CN-19)
- Ref: W-29 · Severity: Low · Size: S · Depends on: CN-19
- Files: `services/bank-sync/app/sync.py` (`_app_balance`).
- What to do: use core's `GET /cash-accounts/{id}/balance` (CN-19) instead of `GET /portfolios/{id}/snapshot`.
- Tests: unit with a fake core exposing the new endpoint.
- Documents: CHANGELOG (Changed).
- Acceptance: reconciliation triggers no price-feed calls.

---

## 6. WP-03 · core-networth A — Correct figures, untouched past

Context: `services/core-networth/app/`. Principles 1 and 2 of `CLAUDE.md`. Main tests: `tests/integration/test_valuation.py`, `test_xirr.py`, `test_reports.py`, `test_networth_snapshots.py`, `test_cash_ledger.py`; `tests/fake_feed.py` supports different live and historical rates and unpriceable tickers (`forget`).

### CN-01 · Never freeze a past snapshot valued at today's price
- Ref: W-03 · Severity: High · Size: S
- Files: `app/valuation.py` (`why_snapshot_cannot_be_frozen`, `compute_portfolio_snapshot`), `app/scheduler.py` (`_catch_up_portfolio_snapshots`), `app/routers/networth.py` (`take_networth_snapshot`).
- DESIGN_NOTES to read: `routers/networth.py` (`why_snapshot_cannot_be_frozen`), `valuation.py` (`compute_portfolio_snapshot`).
- Problem: with `price_source == "historical_fallback"` the position has a price (today's) and the check does not block: a past month-end can be frozen at current prices.
- What to do: in `why_snapshot_cannot_be_frozen`, if `snap.as_of < today` and a position has `price_source == "historical_fallback"`, return a reason ("no historical price for …: today's price was used"). A manual snapshot (date = today) is unaffected (today never uses the fallback).
- Tests: integration `test_networth_snapshots.py`: a past month-end where the `feed` has a live but no historical price for the ticker → `catch_up_monthly_snapshots` does not create it; once the historical price exists, it does.
- Documents: DESIGN_NOTES (the existing `why_snapshot_cannot_be_frozen` entry), CHANGELOG (Fixed, snapshots area).
- Acceptance: no `auto` snapshot can include `historical_fallback` prices.

### CN-02 · Exchange rates with an outcome: the basis for flagging incomplete figures
- Ref: W-01 · Severity: High · Size: S · Unblocks: CN-03, CN-04, CN-05, CN-06
- Files: `app/price_client.py` (`fx_rate_at`), every caller of `fx_rate_at` (`valuation.compute_portfolio_intraday`, `xirr._resolve_price`, `xirr.build_portfolio_cashflows`, `routers/expenses.create_transfer`, `convert_to_transfer`), `reports.flows` (uses `get_fx_rate_on_date` + `or 1.0`).
- Problem: `fx_rate_at` returns `1.0` when the rate is missing, and the caller cannot tell.
- What to do:
  1. New `fx_rate_checked(from, to, day) -> tuple[float, bool]` (same historical/live logic; `(1.0, False)` when missing).
  2. Keep `fx_rate_at` as a wrapper only while it still has callers after CN-03…06; otherwise delete it at the end of CN-06 (no unused code).
  3. In `reports.flows` replace `get_fx_rate_on_date(...) or 1.0` with the new function (no output change in this task: CN-06 returns the flag).
- Tests: unit/integration: `fx_rate_checked` gives `(rate, True)` when present, `(1.0, False)` when missing, `(1.0, True)` for the same currency.
- Documents: DESIGN_NOTES `price_client.py`, CHANGELOG (Refactored).
- Acceptance: one function tells whether a rate was found; no regression.

### CN-03 · Cross-currency transfers: never store a 1:1 conversion — DECISION D-02
- Ref: W-02 · Severity: High · Size: M · Depends on: CN-02 · Unblocks: FE-07, RF-02
- Files: `app/schemas.py` (`TransferCreate`, `ConvertToTransfer`), `app/routers/expenses.py` (`create_transfer`, `convert_to_transfer`).
- DESIGN_NOTES to read: `routers/expenses.py` (all entries), `schemas.py`.
- Problem: with a missing rate the receiving leg is stored as `amount × 1.0`: a **permanent** error in the balance.
- What to do (D-02b):
  1. Optional `received_amount: Optional[float]` in `TransferCreate` and `ConvertToTransfer` (validated with `_round_and_check_positive`).
  2. Same currency: `received_amount` must equal `amount` if given (400 otherwise).
  3. Different currencies: use `received_amount` if given; otherwise `fx_rate_checked(from, to, entry_date)`; if not found → **409** "No exchange rate for X→Y on <date>: enter the amount received".
  4. Existing transfers are untouched.
- Constraints: `create_transfer`'s idempotency is unchanged (the key covers the new request with the new field).
- Tests: integration `test_cash_ledger.py`: (a) rate present → as before; (b) rate missing, no `received_amount` → 409 and **no row created**; (c) rate missing with `received_amount` → receiving leg exactly that amount; (d) the same for `convert-to-transfer`.
- Documents: DESIGN_NOTES `routers/expenses.py` (new `create_transfer` entry), README "What it does" (transfers: amount received), CHANGELOG (Fixed).
- Acceptance: no path stores an undeclared 1:1 conversion.

### CN-04 · History, growth and intraday say when they are incomplete
- Ref: W-01 · Severity: High · Size: M · Depends on: CN-02 · Unblocks: FE-06, CN-13
- Files: `app/schemas.py` (`NetWorthPoint`, `NetWorthHistory`), `app/valuation.py` (`compute_portfolio_growth`, `_build_growth_stats`, `compute_portfolio_intraday`), `app/routers/networth.py` (`portfolio_history`, `portfolio_intraday`).
- Problem: history points and growth report neither `fx_unavailable` nor unpriced positions; intraday uses `fx_rate_at` (silent 1:1).
- What to do:
  1. `NetWorthPoint`: `complete: bool = True` (False when that day had `fx_unavailable` or an `unavailable` position); `NetWorthHistory`: `incomplete_dates: list[date]` (handy for the UI).
  2. Growth: `complete: bool` per period (start and current both complete) and at the root.
  3. Intraday: use `fx_rate_checked`; response with `fx_unavailable: bool` and `missing_prices: list[str]` (tickers with neither data nor fallback).
  4. Fields are **added**, never removed: the current frontend keeps working.
- Tests: integration `test_valuation.py`/`test_intraday.py`: missing historical rate on a date → that point `complete=False`; forgotten ticker → `complete=False`; everything present → `True`.
- Documents: DESIGN_NOTES `valuation.py`, CHANGELOG (Added — history, growth and intraday say when a figure is incomplete).
- Acceptance: every time-based figure carries its own completeness flag.

### CN-05 · XIRR: no silently dropped flows, same price rules as valuation
- Ref: W-01, W-04 · Severity: High · Size: M · Depends on: CN-02 · Unblocks: FE-06
- Files: `app/xirr.py` (`_resolve_price`, `build_portfolio_cashflows`, `compute_portfolio_xirr`).
- DESIGN_NOTES to read: `xirr.py` (all).
- Problem: a quantity change with no price is dropped; missing rates count as 1:1 without a signal; the start/end valuations may use `historical_fallback` while intermediate flows do not.
- What to do:
  1. `build_portfolio_cashflows` also returns a list of `problems` (asset unpriced on a date, FX pair missing on a date).
  2. `_resolve_price` uses `fx_rate_checked` and the same fallback chain as `compute_portfolio_snapshot` (historical → live as `historical_fallback`), recording the fallback as an "approximate" problem.
  3. `compute_portfolio_xirr`: per period, with blocking problems (missing price) return `{"start_date", "rate_pct": null, "incomplete": true, "reason": …}`; with approximations only, return the rate with `approximate: true` and `reason`.
- Constraints: the solver (`xirr()`) does not change; `test_xirr_solver.py` stays green.
- Tests: integration `test_xirr.py`: a purchase on a date with neither historical nor live price → `rate_pct null`, `incomplete true`; missing rate → `incomplete`/`approximate` per the rule; the clean case is unchanged.
- Documents: DESIGN_NOTES `xirr.py build_portfolio_cashflows`, CHANGELOG (Fixed, XIRR area).
- Acceptance: XIRR is never shown as exact when computed with missing data.

### CN-06 · Reports, budgets and recurring payments say when a rate was missing; no e-mail on incomplete data
- Ref: W-01 · Severity: High · Size: M · Depends on: CN-02 · Unblocks: FE-06, CN-13, RF-01
- Files: `app/reports.py` (`flows` and callers), `app/schemas.py` (`ExpenseSummary`, `MonthlyFlow`, `RecurringReport`, `BudgetProgress`), `app/routers/expenses.py` (`expenses_summary`, `expenses_monthly`, `recurring_payments`), `app/routers/budgets.py` (`budget_progress`), `app/alerts.py`.
- What to do:
  1. `flows` also returns the set of pairs/dates without a rate (e.g. a `FlowSet(flows, fx_missing)` or a tuple).
  2. Add `fx_unavailable: bool` (and optionally `fx_missing: list[str]` like "USD→EUR 2026-03-04") to the summary, recurring and budget-progress responses; for the monthly report, `fx_unavailable` per row.
  3. `alerts.check_budgets_over`: if an item is OVER but its computation was incomplete, do **not** send the e-mail (retry next cycle).
  4. Delete `fx_rate_at` if it has no callers left (see CN-02 step 2).
- Tests: integration `test_reports.py`, `test_budget_alerts.py`: missing historical rate for a USD expense in an EUR portfolio → `fx_unavailable true`; no e-mail sent.
- Documents: DESIGN_NOTES `reports.py flows`, `alerts.py`; CHANGELOG (Fixed).
- Acceptance: no report or alert presents a total with 1:1 conversions as certain.

### CN-07 · Asset growth: never an invented zero price
- Ref: W-05 · Severity: Medium · Size: S
- Files: `app/valuation.py` (`compute_asset_growth`, `_build_growth_stats`).
- Problem: when the price is missing, `value_at` returns `0.0` → a plausible −100% growth.
- What to do: `value_at` returns `None`; `_build_growth_stats` treats `None` (start or current) as a period that cannot be computed (`None`), like portfolio growth.
- Tests: integration: asset whose ticker the feed forgot → periods `None`, never −100%.
- Documents: CHANGELOG (Fixed), DESIGN_NOTES `valuation.py`.
- Acceptance: 0.0 is never used as a price.

### CN-08 · An explicit time zone; no silently moved dates — DECISION D-04
- Ref: W-06 · Severity: High · Size: M
- Files: `docker-compose.yml` (`TZ` on core, bank-sync, geo, gateway, price-feed), `.env.example`, README "Configuration"; `app/schemas.py` (`_reject_future_date`); every `date.today()`/`datetime.now()` in core (`grep -rn "date.today\|datetime.now" services/core-networth/app`); bank-sync (`_usable_date`, `alerts`); price-feed (`date.today()` for "finished day").
- DESIGN_NOTES to read: `schemas.py _reject_future_date`, `routers/cash.py delete_cash_account`, `models.py CashAccount.archived_at`, frontend `lib/format` (`toLocalISODate`).
- Problem: the containers run in UTC; in the first hours of the night (Italian time) the owner's "today" is the server's "tomorrow" and is **clipped** to yesterday without warning; the budgets' current month and the snapshots' month-end are UTC.
- What to do (D-04a):
  1. A `TZ` variable (default `Europe/Rome`) passed to every service in compose; check that `python:3.12-slim` has zone data (`/usr/share/zoneinfo`); if not, add the `tzdata` Python package to the requirements and use `zoneinfo`.
  2. In core, one helper `app/clock.py` with `today()` and `now_local()` reading the configured zone; replace every direct use (per `CLAUDE.md`, look for existing helpers first).
  3. `_reject_future_date`: with the zone aligned, **refuse** dates `> today()` instead of clipping, with a clear message.
  4. `archived_at` stays local time (now consistent with the configured zone).
- Constraints: existing data is not migrated. Other `datetime.utcnow()` uses (technical timestamps) stay UTC (see DOC-02).
- Tests: unit `tests/unit/test_dates_and_schedule.py`: with zone `Europe/Rome` and a fake clock at 00:30 local (23:30 UTC the day before), a local "today" date is accepted and stored unchanged; a future date is refused with 422.
- Documents: environment variables (three sources), README "Configuration" and "Your data" (job times), DESIGN_NOTES `schemas._reject_future_date`, CHANGELOG (Fixed).
- Acceptance: the server never changes a date the owner entered.

### CN-09 · The currency of accounts and assets with history cannot change — DECISION D-06
- Ref: W-09 · Severity: Medium · Size: S · Unblocks: FE-08
- Files: `app/routers/cash.py` (`update_cash_account`), `app/routers/portfolios.py` (`update_asset`).
- Problem: changing `currency` reinterprets past balances, transactions and manual prices in the new currency (it rewrites the past).
- What to do (D-06a): 400 when the currency changes and the account has at least one balance or transaction; 400 when the asset has at least one holding entry with `manual_price`. The message explains the alternative (a new account/asset).
- Tests: integration `test_archiving.py` or `test_cash_ledger.py`: currency change on an empty account → ok; with history → 400 and nothing changed; asset with manual prices → 400; asset with a ticker only → ok (price-feed returns prices with their own currency).
- Documents: DESIGN_NOTES `routers/cash.py update_cash_account`, `routers/portfolios.py`; CHANGELOG (Fixed, "the past is never rewritten").
- Acceptance: no currency change can rewrite history.

### CN-10 · Deleted automatic snapshots are not recreated with different data — DECISION D-05
- Ref: W-10, N-13 · Severity: Low · Size: S
- Files: `app/models.py` (new table or column), `app/migrate.py` (if needed), `app/routers/networth.py` (`delete_networth_snapshot`), `app/scheduler.py` (`_catch_up_portfolio_snapshots`).
- Problem: deleting a past `auto` snapshot makes the scheduler recreate it from current data; changing the base currency recomputes every month in the new currency.
- What to do (D-05a):
  1. Table `skipped_snapshot_dates(portfolio_id, snapshot_date, currency)` (a new table: `create_all` creates it; no data migration).
  2. Deleting a snapshot with `source="auto"` inserts a tombstone; the catch-up skips tombstoned dates.
  3. Base-currency change: the catch-up in the new currency starts from the change date, not from the portfolio's first date (use the simplest correct option — e.g. a `base_currency_since` column set by the PATCH — and document it).
- Tests: integration `test_networth_snapshots.py`: delete an auto snapshot → not recreated next cycle; change the base currency → no retroactive snapshots in the new currency.
- Documents: DESIGN_NOTES `scheduler.catch_up_monthly_snapshots`, README "Your data" (behaviour), CHANGELOG (Changed); `tests/integration/test_migrations.py` only if a column with data is added.
- Acceptance: a frozen snapshot never reappears with different values.

### CN-11 · `/transactions` and the export without a scope do not return other portfolios
- Ref: N-01 · Severity: Medium · Size: S
- Files: `app/routers/expenses.py` (`list_transactions`, `export_transactions_csv`, `_transactions_query`).
- DESIGN_NOTES to read: `routers/networth.py` "No all-portfolios endpoints" (it says `/transactions` keeps `portfolio_id` optional because `account_id` is enough).
- Problem: with neither `portfolio_id` nor `account_id`, every portfolio's transactions come back.
- What to do: 422 when both are missing; when both are given, check that the account belongs to the portfolio (400 otherwise).
- Tests: integration `test_portfolio_isolation.py`: no parameter → 422; another portfolio's account → 400.
- Documents: DESIGN_NOTES (update the entry above), CHANGELOG (Fixed, isolation area).
- Acceptance: no read endpoint returns several portfolios' data together.

### CN-12 · Merchants: totals per currency
- Ref: W-34 · Severity: Medium · Size: S · Unblocks: FE-09
- Files: `app/schemas.py` (`MerchantOut`), `app/routers/expenses.py` (`list_merchants`).
- Problem: `expense_total`/`income_total` add up amounts of accounts in different currencies.
- What to do: add `totals: list[{currency, expense_total, income_total}]` (the account's currency); make `expense_total`/`income_total` nullable and `null` unless every transaction is in one currency, to be removed in FE-09 if nothing uses them any more.
- Tests: integration `test_merchants.py`: one merchant on an EUR and a USD account → two `totals` entries, aggregate fields `null`.
- Documents: CHANGELOG (Fixed).
- Acceptance: nothing is summed across currencies.

---

## 7. WP-04 · core-networth B — Robustness, performance, supporting APIs

Context: WP-03 must be complete (CN-13 reworks code CN-04…06 changed).

### CN-13 · No synchronous I/O on the event loop
- Ref: W-18 · Severity: High · Size: L · Depends on: SH-01, CN-04, CN-05, CN-06
- Files: `app/routers/networth.py`, `app/routers/budgets.py` (`budget_progress`), `app/routers/expenses.py` (`create_transfer`, `convert_to_transfer`, `expenses_summary`, `expenses_monthly`, `recurring_payments`), `app/routers/portfolios.py` (`asset_growth`), `app/alerts.py`, `app/scheduler.py`.
- DESIGN_NOTES to read: `database.py NullPool`, `valuation.py PortfolioLedger`, `price_client.py _clients`.
- Problem: `async def` endpoints run synchronous SQLAlchemy queries and (alerts) SMTP on the loop; with a single uvicorn worker one heavy request blocks all others.
- What to do:
  1. Endpoints that never `await`: declare them `def` (FastAPI runs them in the threadpool).
  2. Endpoints that `await` (prices): run DB-only blocks in `await run_in_threadpool(...)` — notably building `PortfolioLedger`, `compute_refund_adjustments`, the `reports.flows` query, the final writes. The `Session` must be used by one thread at a time (sequential use is fine, `check_same_thread=False` is already set).
  3. `alerts.py`: `notify.send_async`.
  4. Do not introduce async SQLAlchemy in this task.
- Constraints: `test_query_counts.py` stays green (same number of queries).
- Tests: system (new, in `tests/system/test_gateway.py` or a dedicated file): while `/portfolios/{id}/history` of a large ledger runs, core's `/health` answers within ~200 ms (generous threshold; mark `slow` if needed). OPS-04 later enables the `ASYNC` lint to prevent regressions.
- Documents: DESIGN_NOTES (new "event loop" entry), CHANGELOG (Fixed, performance).
- Acceptance: no known blocking call remains in a core coroutine.

### CN-14 · Restore isolated from concurrent requests, and undoable
- Ref: W-19 · Severity: High · Size: M · Unblocks: GW-06, RF-04
- Files: `app/backup.py` (`restore_db`), `app/routers/backup.py`, `app/main.py` (middleware), `app/scheduler.py` (`run_all_jobs`).
- DESIGN_NOTES to read: `backup.py`, `database.py` (No WAL journal).
- Problem: during a restore other requests or the scheduler may write to the file being replaced (writes lost on the old inode) or read mixed state; there is no programmatic undo.
- What to do:
  1. A "maintenance gate" in core: an async lock plus an in-flight request counter. A middleware answers **503** (`Retry-After`) to new requests during a restore (except `/health`); the restore waits for in-flight requests to finish (reasonable timeout, then 503 to the restore caller).
  2. The scheduler skips its cycle while the gate is closed.
  3. `restore_db` returns the name of the `pre-restore-…` folder it created.
  4. Endpoint `POST /backup/undo-restore {"pre_restore": "<name>"}`: the same procedure as a restore, from that copy (name validated with a regex + `is_relative_to`).
- Tests: integration/system: a slow request in flight + a restore → the request completes, then the file is replaced; a new request during the restore → 503; undo-restore gives back the original stats; a malicious name → 400.
- Documents: DESIGN_NOTES `backup.py`, README "Your data" (undo), CHANGELOG (Fixed + Added).
- Acceptance: no write can be lost during a restore; the gateway can undo it.

### CN-15 · A reliable, observable scheduler
- Ref: W-21 · Severity: Medium · Size: M · Unblocks: FE-13
- Files: `app/main.py` (lifespan), `app/scheduler.py`, `app/models.py`/`app/migrate.py` (unique index), new endpoint `GET /scheduler/status`.
- Problem: the `create_task` result is not kept; no UNIQUE constraint on `(portfolio_id, snapshot_date, currency)`; `refresh_all_prices` is sequential with n² FX pairs; job outcomes are invisible (a missed backup is silent).
- What to do:
  1. Keep the task reference (app attribute or module variable) and cancel it in the lifespan shutdown.
  2. Migration: remove existing duplicates (per key keep the latest `manual` row, otherwise the latest) and `CREATE UNIQUE INDEX IF NOT EXISTS` on `networth_snapshots(portfolio_id, snapshot_date, currency) WHERE portfolio_id IS NOT NULL`.
  3. `refresh_all_prices`: pairs only `{asset and account currencies} → {portfolio base currencies}`; concurrent requests with `asyncio.gather` (bounded, e.g. a semaphore of 5).
  4. Record in memory (optionally in a `job_runs` table) for each job: last start, last outcome, last error, last successful backup (date and path). `GET /scheduler/status` returns them.
  5. A reduced status endpoint for geo and bank-sync: add it here or record it as a new point (§A.10).
- Tests: integration `test_migrations.py` (duplicates removed, index created, idempotent); unit on the job state; integration on `/scheduler/status` after `run-now`.
- Documents: DESIGN_NOTES `scheduler.py`, `migrate.py`; README "Your data" (where to see job outcomes); CHANGELOG (Added/Fixed).
- Acceptance: duplicates impossible at DB level; job outcomes can be queried.

### CN-16 · Referential integrity enforced by SQLite
- Ref: W-22 · Severity: Medium · Size: M · Unblocks: RF-06
- Files: `app/database.py` (`connect` listener with `PRAGMA foreign_keys=ON`), `app/models.py` (`ondelete` where needed), `app/migrate.py` (`_rebuild_merchant_rules` — renaming with FKs on), `app/routers/portfolios.py` (`delete_portfolio`, `delete_asset`), `routers/expenses.py` (category/transaction deletes), `app/backup.py` (restore validation).
- Problem: foreign keys are declared but not enforced; cascades exist only in the ORM and do not apply to `query().delete()`.
- What to do:
  1. Before enabling the pragma, a **check** migration for orphan rows (`PRAGMA foreign_key_check`): log them and, where the meaning is clear, fix them (e.g. `refund_of_id` pointing at a missing expense → NULL, as delete paths already do); never delete financial data: if unresolvable orphans remain, do not enable the pragma and log a clear error.
  2. Enable the pragma through the listener (also for the engine the tests build: align `tests/conftest.py`).
  3. Check that the routers' delete order works with FKs on; during `_rebuild_merchant_rules` turn FKs off temporarily (`PRAGMA foreign_keys=OFF` on the migration connection) as SQLite's procedure requires.
- Tests: `test_migrations.py`: an old DB with a resolvable orphan → fixed; integration: existing deletes (portfolio, asset, category, transaction with refunds) still green; inserting a transaction with a missing `account_id` → error.
- Documents: DESIGN_NOTES `database.py`, `migrate.py`; CHANGELOG (Changed); `tests/README.md` if the fixture changes.
- Acceptance: the database refuses dangling references; existing data stays intact.

### CN-17 · Refund adjustments limited to what is needed
- Ref: W-24 · Severity: Medium · Size: S · Unblocks: CN-18, RF-01
- Files: `app/routers/expenses.py` (`compute_refund_adjustments` and callers), `app/routers/budgets.py`, `app/alerts.py`.
- Problem: every report reads **every** refund in the database (all portfolios, all periods).
- What to do: `compute_refund_adjustments(db, portfolio_id)` restricted to the portfolio's expenses and their refunds (join on accounts). The computation stays independent of the report window (a refund outside the period reduces an expense inside it: documented behaviour).
- Constraints: legacy rows with a refund across portfolios (from before the "same portfolio" rule) must count as today: check with a query and, if any exist, also include refunds pointing at the portfolio's expenses from outside accounts.
- Tests: integration `test_reports.py` (same totals as before); `test_query_counts.py` (constant queries as **other** portfolios grow).
- Documents: DESIGN_NOTES `compute_refund_adjustments`, CHANGELOG (Changed, performance).
- Acceptance: a report's cost does not depend on other portfolios' data.

### CN-18 · Refund candidates endpoint
- Ref: W-25 · Severity: Medium · Size: S · Depends on: CN-17 · Unblocks: FE-10
- Files: `app/routers/expenses.py`, `app/schemas.py`.
- Problem: the frontend downloads the whole portfolio ledger just to build the refund picker.
- What to do: `GET /refund-candidates?portfolio_id=&q=&limit=&offset=` → refundable expenses (not transfers, not refunds) with `remaining` computed server-side (same logic as `compute_refund_adjustments`), account name and currency (archived accounts too), ordered as today (with something left first, then newest); search on note/counterparty.
- Tests: integration: `remaining` consistent with `/expenses/summary`; expenses on archived accounts included; pagination.
- Documents: CHANGELOG (Added), DESIGN_NOTES `lib/refunds` (move the rationale).
- Acceptance: the frontend can fill the picker without downloading every transaction.

### CN-19 · Account balance endpoint
- Ref: W-29 · Severity: Low · Size: S · Unblocks: BS-07
- Files: `app/routers/cash.py`, `app/valuation.py` (`AccountLedger`).
- What to do: `GET /cash-accounts/{id}/balance?as_of=` → `{balance, currency, kind, unit_value, as_of_event}` using `AccountLedger.load` for that account only (no price-feed call).
- Tests: integration: same value as the snapshot's `cash_positions[].balance`.
- Documents: CHANGELOG (Added).
- Acceptance: an account's balance is available without valuing the portfolio.

### CN-20 · Composite endpoints for operations the client splits today
- Ref: W-35 · Severity: Medium · Size: M · Unblocks: CN-21, FE-11, RF-02
- Files: `app/routers/portfolios.py`, `app/routers/cash.py`, `app/schemas.py`.
- Problem: "remove position" = N DELETEs from the client; "new position with a new asset" = 2 POSTs (an orphan asset if the second fails); "new account with an opening balance" = 2 POSTs.
- What to do:
  1. `DELETE /portfolios/{pid}/positions/{asset_id}`: delete all of the asset's holding entries in the portfolio in one transaction.
  2. `POST /portfolios/{pid}/holdings` accepts, instead of `asset_id`, an `asset` object (the `AssetCreate` fields): asset and entry created in one transaction.
  3. `CashAccountCreate`: optional `initial_balance` and `initial_balance_date` (default today) → account and anchor in one transaction.
- Tests: integration: each operation is atomic (force a validation error in the second part → nothing created).
- Documents: CHANGELOG (Added), DESIGN_NOTES `PositionsSection`/`AddPositionForm` (why).
- Acceptance: each user action is a single atomic request.

### CN-21 · Idempotency everywhere money is created
- Ref: W-36 · Severity: Medium · Size: S · Depends on: CN-20 · Unblocks: FE-12
- Files: `app/routers/expenses.py` (`convert_to_transfer`), the CN-20 endpoints (`POST holdings` with an inline asset, `POST cash-accounts` with an opening balance).
- What to do: apply `_check_idempotency` / `_commit_with_idempotency` / `_store_idempotency` as the existing endpoints do.
- Tests: integration `test_idempotency.py`: the same key twice → one creation, the same response.
- Documents: CHANGELOG (Changed), DESIGN_NOTES `helpers.py` (endpoint list).
- Acceptance: every POST that creates financial data accepts `Idempotency-Key`.

### CN-25 · An idempotency key is never left "still being processed"
- Ref: N-14 (found in BS-02) · Severity: Low · Size: S · Depends on: CN-21
- Files: `services/core-networth/app/helpers.py` (`_commit_with_idempotency`, `_store_idempotency`, `_replay_or_conflict`), every endpoint that calls them (`expenses.create_cash_transaction`, `create_transfer`, `commit_transaction_import`, `portfolios.add_holding_entry`, the CN-21 ones).
- DESIGN_NOTES to read: core `helpers.py` (Idempotency); bank-sync `sync._sync_link_locked` (idempotency keys).
- Problem: the mutation and its key are committed together with an empty `response_body`, and the response is stored by a second commit. A process that dies between the two leaves the key reserved: every retry gets 409 "still being processed" until `IDEMPOTENCY_TTL_HOURS` (24) prunes it, and the retry after that creates the record a second time. bank-sync retries every cycle with the same key, so after a core crash in that gap the link reports a failing sync for a day and then captures the transaction twice.
- What to do: write the response into the key row **in the same commit** as the mutation: `db.flush()`, build the response from the flushed rows, set `response_body`, one `db.commit()`; drop `_store_idempotency`. Keep the IntegrityError path (the loser of a race replays the winner's stored response).
- Constraints / watch out: the response built before the commit must equal what a `db.refresh` after it gives (server-side defaults such as `created_at`: set them in Python or refresh after the flush); the "different operation" 409 stays.
- Tests: integration `test_idempotency.py`: a failure injected after the mutation's commit point no longer leaves an empty `response_body`; the same key twice still gives one creation and the same response; the concurrent-replay test stays green.
- Documents: DESIGN_NOTES `helpers.py` (Idempotency), CHANGELOG (Fixed).
- Acceptance: no code path leaves an `IdempotencyKey` row with an empty `response_body` after its request ends.

### CN-22 · CSV export at the stored precision
- Ref: N-02 · Severity: Low · Size: S
- Files: `app/routers/expenses.py` (`export_transactions_csv`).
- Problem: amounts stored with 4 decimals are exported with 2 (`:.2f`).
- What to do: export without losing precision (e.g. up to 4 decimals, trailing zeros dropped).
- Tests: integration `test_reports.py` (export): `12.3456` comes out as `-12.3456`.
- Documents: CHANGELOG (Fixed).
- Acceptance: the export column adds up to the database total.

### CN-23 · Consistent budget currency validation
- Ref: W-45 · Severity: Low · Size: S
- Files: `app/schemas.py` (`BudgetCreate`, `BudgetUpdate`).
- What to do: use `_normalize_currency` (trim, upper case, 3 letters) instead of `min/max_length` + `upper()`.
- Tests: unit `tests/unit/test_input_validation.py`: `"E1R"` → 422; `" eur "` → `"EUR"`.
- Documents: CHANGELOG (Fixed).
- Acceptance: budgets accept exactly the currency codes every other schema accepts.

### CN-24 · Bounded price cache in core
- Ref: W-26 · Severity: Medium · Size: S
- Files: `app/price_client.py` (`_cache`, `_cached`, `_store`).
- DESIGN_NOTES to read: `price_client.py` (Past closes are not stored on disk).
- What to do: an entry limit (e.g. 200,000) with LRU eviction of the least used "forever" entries; expired entries removed on read. No new dependency if an `OrderedDict` is enough.
- Constraints: the `feed` fixture empties `_cache` with `.clear()`: keep that API.
- Tests: unit `tests/unit/test_price_cache.py` (or new): past the limit the least recent entries leave; TTL semantics unchanged.
- Documents: DESIGN_NOTES `price_client.py`, CHANGELOG (Changed).
- Acceptance: the cache cannot grow without bound.

---

## 8. WP-05 · price-feed — Quote currencies and caches

Context: `services/price-feed/app/main.py`. Tests: `tests/unit/test_price_feed_contract.py` (fake `yf.Ticker`), `tests/unit/test_price_cache.py`. No real Yahoo call in tests; `CLAUDE.md` asks for manual checks of price-feed's Yahoo calls on dependency changes.

### PF-01 · Normalise minor-unit currencies (GBp, ILA, ZAc)
- Ref: W-07 · Severity: Medium · Size: M
- Files: `main.py` (`_ticker_currency`, `_fetch_ticker_price`, `_fetch_price_on_date`, `price_series`, `_fetch_intraday`, `price_history`).
- DESIGN_NOTES to read: price-feed `main.py` (`_ticker_currency`, NaN closes).
- Problem: tickers quoted in pence (`GBp`, London), agorot (`ILA`) or South African cents (`ZAc`) produce nonexistent FX pairs (`GBpEUR=X`) → `fx_unavailable` and values 100× off.
- What to do: a table `{"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ILA": ("ILS", 100), "ZAc": ("ZAR", 100)}`; every endpoint returning prices divides by the factor and returns the major currency, through **one** helper used by all endpoints.
- Constraints: core's caches hold prices already served: the change reaches core on its restart (document it); manual prices are not touched.
- Tests: unit `test_price_feed_contract.py`: a ticker with `fast_info.currency == "GBp"` and Close 1500 → `price 15.0, currency "GBP"` on `/latest`, `/on-date`, `/series`, `/intraday`, `/history`.
- Documents: DESIGN_NOTES `_ticker_currency`, CHANGELOG (Fixed).
- Acceptance: a London ETF quoted in GBp is valued correctly in EUR.

### PF-02 · Size-bounded caches
- Ref: W-26 · Severity: Medium · Size: S
- Files: `main.py` (`TtlCache`).
- What to do: a `maxsize` parameter with LRU eviction; expired entries removed on read; per-cache limits (e.g. historical 200,000, others 5,000).
- Tests: unit `test_price_cache.py`: eviction past the limit; "forever" TTL and write-time TTL unchanged.
- Documents: DESIGN_NOTES price-feed, CHANGELOG (Changed).
- Acceptance: no cache can grow without bound.

### PF-03 · The `range` parameter shadows the builtin
- Ref: W-45 · Severity: Low · Size: S
- Files: `main.py` (`price_history`).
- What to do: `period: str = Query("1y", alias="range")` — the public URL keeps `?range=`.
- Tests: unit/contract: `/history?range=max&interval=1d` works as before.
- Documents: CHANGELOG (Refactored).
- Acceptance: same API, no shadowed builtin.

---

## 9. WP-06 · geo-allocation — Safe upload, storage and restore

Context: `services/geo-allocation/app/`. Tests: `tests/unit/test_geo_parsers.py`, `test_geo_country_tables.py`, `test_backup_archives.py`, the system backup tests.

### GA-01 · Factsheet parsing off the event loop
- Ref: W-18 · Severity: Medium · Size: S
- Files: `main.py` (`upload_allocation_file`, `backup_restore`, `backup_preview`).
- What to do: `result = await run_in_threadpool(parse_bytes, content, source_file=...)`; the same for `backup.restore_from_zip`/`preview_uploaded_zip` and `storage.save_upload`.
- Tests: existing unit/integration green; optionally a concurrency test (health answers during a simulated slow parse).
- Documents: CHANGELOG (Fixed).
- Acceptance: no CPU-bound or disk-bound work runs on the loop.

### GA-02 · A safe XML parser
- Ref: W-15 · Severity: Low · Size: S
- Files: `app/lib/readers/spreadsheetml.py`, `services/geo-allocation/requirements.txt`.
- What to do: `defusedxml.ElementTree.parse` instead of `xml.etree.ElementTree.parse` (add `defusedxml`, pinned).
- Constraints: `tests/unit/test_service_requirements.py` checks the dependency is declared in the service's requirements.
- Tests: unit: a SpreadsheetML file with DTD entities is refused (`UnreadableFileError`); valid ones still work.
- Documents: CHANGELOG (Fixed, security), DESIGN_NOTES geo-allocation.
- Acceptance: untrusted XML is parsed with `defusedxml`.

### GA-03 · Atomic writes of stored files
- Ref: N-05 · Severity: Low · Size: S
- Files: `app/storage.py` (`save_upload`).
- Problem: `source.<ext>` and `allocation.json` are written in place; a crash leaves truncated files; old `source.*` files are deleted before the new one is written.
- What to do: write temp files in the same folder and `os.replace`; delete old `source.*` only afterwards; allow only `.xlsx/.xls/.xlsb/.ods/.xml` extensions (otherwise `.xlsx`).
- Tests: unit: a disallowed extension is stored as `.xlsx`; final content correct.
- Documents: CHANGELOG (Fixed).
- Acceptance: a crash never leaves a half-written factsheet.

### GA-04 · Atomic, undoable restore
- Ref: W-19 · Severity: High · Size: M · Unblocks: GW-06, RF-04
- Files: `app/backup.py` (`restore_from_zip`), `app/main.py`.
- Problem: the restore deletes `fund-files` and then extracts; an error midway leaves the folder partial.
- What to do:
  1. Extract into a temporary **sibling** folder of `FUND_FILES_DIR` (same filesystem); only when extraction is complete: rename the old folder away, the new one into `fund-files`, delete the old one.
  2. Return the name of the `pre-restore-…` copy.
  3. `POST /backup/undo-restore {"pre_restore": "<name>"}` (same name validation as CN-14/BS-06).
- Tests: unit `test_backup_archives.py`: a zip bomb midway → `fund-files` intact; undo-restore restores.
- Documents: DESIGN_NOTES geo-allocation backup, CHANGELOG (Fixed + Added).
- Acceptance: a failed restore changes nothing.

### GA-05 · Orphan factsheet clean-up endpoint
- Ref: W-20 · Severity: Low · Size: S · Unblocks: GW-07
- Files: `app/main.py`, `app/storage.py`.
- What to do: `POST /allocation/prune {"keep": [asset_id, …]}` → removes folders of assets not listed; returns the removed ids. Refuse an empty list unless `confirm_all=true` (protection against wrong calls).
- Tests: unit: removes only unlisted ones; empty list → 400.
- Documents: CHANGELOG (Added).
- Acceptance: orphans can be removed with one call.

### GA-06 · Country table clean-up
- Ref: W-45 · Severity: Low · Size: S
- Files: `app/lib/countries.py`.
- What to do: remove unreachable keys (`"perù"`, `"regno unito "` — they cannot match after `_canonicalize`; check `"peru"` and `"regno unito"` exist); rewrite the "used to…" comment (around lines 236-243 at `aa9fbec`) in the present tense, moving the story to DESIGN_NOTES if it is not there.
- Tests: unit `test_geo_country_tables.py` green; add a test that every `_COUNTRY_TO_ISO2` key equals `_canonicalize(key)`.
- Documents: CHANGELOG (Refactored).
- Acceptance: every key in the table can match.

---

## 10. WP-07 · gateway — Proxy, security, distributed restore

Context: `gateway/app/{main,registry,backup}.py`. Tests: `tests/system/test_gateway.py`, `test_api_key.py`, `test_backup_restore.py`.

### GW-01 · Shared HTTP client and parallel health
- Ref: W-27 · Severity: Medium · Size: S · Unblocks: GW-02, GW-05
- Files: `main.py` (every `httpx.AsyncClient(...)`).
- What to do: one `AsyncClient` created in the app lifespan and closed on shutdown; per-request timeouts as today (3/30/60 s); `/health` queries the modules with `asyncio.gather`.
- Tests: existing system tests green; unit: `/health` with one slow module does not add up timeouts.
- Documents: CHANGELOG (Changed, performance).
- Acceptance: no client created per request.

### GW-02 · Forward an allowlist of headers
- Ref: W-14 · Severity: Medium · Size: S · Depends on: GW-01
- Files: `main.py` (`proxy`).
- Problem: the proxy forwards every header except `host` and `content-length` (including `X-API-Key`, `Cookie`, `Authorization`, `Origin`).
- What to do: forward only `content-type`, `accept`, `accept-language`, `idempotency-key` (plus any header a module is shown to use: search the services for `Header(`).
- Tests: system `test_gateway.py`: the module does not receive `X-API-Key` or `Cookie`; `Idempotency-Key` still arrives (idempotency test through the gateway).
- Documents: DESIGN_NOTES gateway `proxy`, CHANGELOG (Fixed, security).
- Acceptance: modules only see the headers they need.

### GW-03 · The API-key 401 carries CORS headers
- Ref: N-06 · Severity: Low · Size: S
- Files: `main.py` (order of `add_middleware(CORSMiddleware)` and `@app.middleware("http") require_api_key`).
- Problem: in Starlette the last middleware added is the outermost: the gate sits outside CORS, so its 401 has no `Access-Control-Allow-Origin` and the browser shows an opaque CORS error.
- What to do: register the gate before CORS (so CORS is outermost and decorates the 401 too); keep the `OPTIONS` exemption only if still needed (check).
- Tests: system `test_api_key.py`: a request from an allowed origin with a wrong key → 401 **with** `access-control-allow-origin`.
- Documents: DESIGN_NOTES gateway `CORSMiddleware`, CHANGELOG (Fixed).
- Acceptance: a wrong key shows as a readable 401 in the browser.

### GW-04 · Error messages faithful to the upstream
- Ref: N-07, W-45 · Severity: Low · Size: S
- Files: `main.py` (`portfolio_geo_allocation`).
- Problem: any non-200 from core becomes "Portfolio not found"; a non-200 from geo silently becomes an empty result; the docstring talks about EUR values (they are base-currency values).
- What to do: core 404 → 404 "Portfolio not found"; other statuses → 502 with the upstream detail; geo non-200 → 502 (the UI then shows an error, not "no data"); fix the docstring.
- Tests: system: geo down → 502 on the aggregated endpoint (today: an empty list).
- Documents: CHANGELOG (Fixed).
- Acceptance: errors are never shown as empty data.

### GW-05 · Streaming responses for large files
- Ref: W-28 · Severity: Low · Size: S · Depends on: GW-01
- Files: `main.py` (`proxy` for `text/csv`/`application/zip`/`application/octet-stream` responses; `backup_export`).
- What to do: `client.stream(...)` + `StreamingResponse` in the proxy for download content types; for `backup_export`, write the combined zip to a temp file and serve it with `FileResponse` (+ background clean-up).
- Tests: system `test_backup_restore.py` and the CSV download green; e2e `test_downloads.py` green.
- Documents: CHANGELOG (Changed).
- Acceptance: large downloads are not held whole in memory by the proxy.

### GW-06 · Distributed restore: validate everything, then restore, undo on failure
- Ref: W-19 · Severity: High · Size: M · Depends on: CN-14, GA-04, BS-06
- Files: `main.py` (`backup_restore`), `backup.py`.
- What to do:
  1. Phase 1 — validation: send each part to its `/backup/preview` (core, geo, bank if present); any failure → 400 with nothing touched.
  2. Phase 2 — restore core → geo → bank in sequence, collecting the returned `pre_restore` names.
  3. If a step fails: call `/backup/undo-restore` on the services already restored (reverse order) and answer 502 with each service's final state ("restored then undone", "undo failed: …").
- Tests: system `test_backup_restore.py`: a zip whose geo part passes preview but fails restore (monkeypatched/test service) → core goes back to its previous state; a zip with an invalid core part → nothing touched.
- Documents: README "Your data" (restore guarantees), DESIGN_NOTES gateway `backup_restore`, CHANGELOG (Fixed).
- Acceptance: after a failed restore the instance is as before (or each service's state is stated).

### GW-07 · Orphan clean-up after asset deletion
- Ref: W-20 · Severity: Low · Size: S · Depends on: GA-05
- Files: `main.py` (new endpoint `POST /api/maintenance/prune-geo`, also used by `delete_asset_and_cleanup` when the geo delete fails).
- What to do: an endpoint reading `GET core /assets` (all ids) and calling `geo /allocation/prune {"keep": ids}`; optionally exposed in Settings by the frontend.
- Tests: system: an asset deleted while geo was down → after the clean-up its factsheet is gone.
- Documents: README (maintenance), CHANGELOG (Added).
- Acceptance: no factsheet outlives its asset for long.

---

## 11. WP-08 · frontend — Bugs, incompleteness warnings, UX

Context: `frontend/src`. Helpers to reuse (`CLAUDE.md` §1): `api/client.ts` (`request`, `filterParams`, `downloadFile`), `lib/errors.errorText`, `lib/format.ts`, `usePortfolio`/`useSelectedPortfolio`/`RequirePortfolio`, `useLatestFetch`, `SnapshotBreakdown`, `RangeAreaChart`, `chartHelpers.pointsInRange`, `WarningCard`, `ResponsiveTable`, the CSS classes `.field-label`, `.input`, `.btn-*`, `.card`, `.glass`, `.meter`, `.data-table`. Tests: Vitest for pure functions only (`src/**/*.test.ts`); page behaviour with Playwright (`tests/e2e/test_ui.py`). Every task here needs `./run-tests.sh all`.

FE-01…FE-04 have no backend dependency and run right after WP-02 (§3.1); the other tasks come after the backend tasks they need.

### FE-01 · An idempotency key outside HTTPS too
- Ref: W-30 · Severity: High · Size: S · Unblocks: FE-12
- Files: `src/components/TransactionImport.tsx` (`handleConfirm`), new `src/lib/ids.ts`.
- Problem: `crypto.randomUUID()` exists only in secure contexts (HTTPS or `localhost`); from `http://<LAN IP>:4173` (the README's setup) it throws `TypeError` and the import cannot be confirmed.
- What to do: `newIdempotencyKey()` in `lib/ids.ts`: `crypto.randomUUID` when present, otherwise 16 bytes from `crypto.getRandomValues` (available in insecure contexts) formatted as a v4 UUID. Use it in `TransactionImport`.
- Tests: Vitest `lib/ids.test.ts`: with `randomUUID` removed from the global object it still returns a valid v4 UUID, different each call.
- Documents: DESIGN_NOTES `TransactionImport`, CHANGELOG (Fixed).
- Acceptance: no direct use of `crypto.randomUUID` left in the code.

### FE-02 · Accounts tagged STOCK/BOND visible on the portfolio page — DECISION D-07
- Ref: W-31 · Severity: High · Size: S
- Files: `src/pages/PortfolioDetail.tsx` (`emergencyFund`/`cash`/`pension` filters), `src/components/BalanceSection.tsx` (`BALANCE_TAGS`).
- Problem: an account tagged STOCK or BOND counts in the totals but appears in no section, so it can be neither edited nor removed.
- What to do (D-07a): a fourth "Other balances" section showing accounts whose category no other section covers (computed by exclusion, so future categories are covered too), with `allowManualUpdate` consistent with the rule for accounts with transactions.
- Tests: e2e `test_ui.py`: an account created through the API with `category: "STOCK"` → visible on the page and removable.
- Documents: DESIGN_NOTES `BalanceSection`, CHANGELOG (Fixed), README "What it does" if sections are described.
- Acceptance: every account of a portfolio is listed on its page.

### FE-03 · Interface texts that match the real behaviour
- Ref: W-33, N-08 · Severity: Medium · Size: S
- Files and fixes:
  1. `components/TransactionLogForm.tsx`: "Converted to X at today's rate on arrival" → "at the rate of the transaction date" (FE-07 changes it again: keep them consistent).
  2. `components/TransactionLogForm.tsx`: the hint about logging a refund on an account in another currency contradicts the backend (400): replace it with a note that the account must be in the same currency, and filter the refund's accounts by currency.
  3. `pages/ExpenseBudgets.tsx`: "across all your portfolios" → "for this portfolio".
  4. `pages/Settings.tsx` (Architecture section): bank-sync is also reached directly (bank callback); mention the bank module.
  5. `pages/ExpenseMerchants.tsx`: comment "category id is always a UUID" → a 12-character hex id.
  6. `pages/ExpenseCategories.tsx`: the delete confirmation must say that the category's budget and merchant rules are deleted too.
- Tests: e2e: at least case 2 (the form does not allow a cross-currency refund).
- Documents: CHANGELOG (Fixed), DESIGN_NOTES `TransactionLogForm` for point 2.
- Acceptance: no text describes a behaviour the code does not have.

### FE-04 · Self-hosted fonts
- Ref: W-13 · Severity: Medium · Size: S
- Files: `frontend/index.html`, `frontend/package.json`, `src/index.css` or `main.tsx`.
- Problem: every page load contacts Google Fonts (principle 3: no cloud services).
- What to do: `@fontsource/inter` and `@fontsource/ibm-plex-mono` (only the weights in use: 300–700 and 400–600) imported in the bundle; remove the Google `<link>`s.
- Tests: e2e: no request to `fonts.googleapis.com`/`fonts.gstatic.com` on load (the `page` fixture records requests).
- Documents: CHANGELOG (Changed, privacy).
- Acceptance: the app makes no third-party request.

### FE-05 · Tell "error" apart from "no data"
- Ref: W-32 · Severity: Medium · Size: M · Unblocks: FE-06, RF-07
- Files: `src/hooks/usePortfolioData.ts` (`useLatestFetch`), `src/pages/Dashboard.tsx`, `src/pages/PortfolioDetail.tsx`, `src/pages/GeoAllocation.tsx`, `src/components/BudgetAlerts.tsx`, `src/components/SnapshotBreakdown.tsx`.
- Problem: a history/growth/XIRR error shows as "Not enough history yet"; a `useLatestFetch` error stays "Loading…" for ever.
- What to do: `useLatestFetch` returns `{data, error, loading}` (update every caller); pages show a `WarningCard` with the message on errors, and "no data" only for an empty response.
- Tests: e2e: with price-feed/geo unavailable (or a `page.route` answering 502), the page shows an error, not "Loading…" or "Not enough history".
- Documents: DESIGN_NOTES `hooks/usePortfolioData`, CHANGELOG (Fixed).
- Acceptance: every failed load is visible as a failure.

### FE-06 · Show when a figure is incomplete or approximate
- Ref: W-01 · Severity: High · Size: M · Depends on: CN-04, CN-05, CN-06, FE-05
- Files: `src/types/index.ts`, `components/NetWorthChart.tsx`/`RangeAreaChart.tsx`, `components/XirrLine.tsx`, `pages/Dashboard.tsx`, `pages/PortfolioDetail.tsx`, `pages/ExpenseHistory.tsx`, `pages/ExpenseBudgets.tsx`, `pages/ExpenseRecurring.tsx`, `components/MonthlyFlowChart.tsx`, `components/BudgetAlerts.tsx`.
- What to do:
  1. Types updated with the new fields (`complete`, `incomplete_dates`, `fx_unavailable`, `approximate`, `incomplete`, `reason`).
  2. Chart: incomplete points marked (e.g. tooltip "incomplete: missing price/FX") and a `WarningCard` above the chart when the visible range has incomplete dates.
  3. Growth/XIRR: a "≈" or "n/a" badge with an explanation when `approximate`/`incomplete`.
  4. Expense reports, budgets, recurring, monthly: `WarningCard` when `fx_unavailable`.
- Tests: e2e `test_ui.py`: with a missing historical rate (stub feed), the history and the expense summary show the warning.
- Documents: CHANGELOG (Added), README "What it does" (incomplete figures are flagged).
- Acceptance: no figure computed from missing data appears without a signal.

### FE-07 · Cross-currency transfer: amount received
- Ref: W-02 · Severity: High · Size: S · Depends on: CN-03
- Files: `components/TransactionLogForm.tsx`, `components/TransactionEditors.tsx` (`ConvertToTransferForm`), `api/client.ts` (`createTransfer`, `convertToTransfer`).
- What to do: when currencies differ, an optional "Amount received (XXX)" field; on the server's 409 for a missing rate, highlight the field as required with the server's message.
- Tests: e2e: different currencies with a missing rate → readable error; with the received amount the transfer succeeds.
- Documents: CHANGELOG (Added).
- Acceptance: a cross-currency transfer never relies on an invented rate.

### FE-08 · Currency locked for accounts/assets with history
- Ref: W-09 · Severity: Medium · Size: S · Depends on: CN-09
- Files: `components/BalanceSection.tsx` (edit details), `pages/Assets.tsx` (`AssetForm`).
- What to do: disable the currency field when the account/asset has history (from the 400 response, or a flag in the account response if CN-09 adds one), with an explanation; show the server's message.
- Tests: e2e: an attempted change → message, currency unchanged.
- Documents: CHANGELOG (Changed).
- Acceptance: the UI never offers a change the server forbids without explaining why.

### FE-09 · Merchants: totals per currency
- Ref: W-34 · Severity: Medium · Size: S · Depends on: CN-12
- Files: `pages/ExpenseMerchants.tsx`, `types/index.ts`.
- What to do: show `totals[]` with each currency (`formatMoneyPrecise(value, currency)`); stop using the aggregate `expense_total`/`income_total` (and remove them from core's schema in the same change if nothing else uses them, see CN-12).
- Tests: e2e or Vitest on a formatting helper.
- Documents: CHANGELOG (Fixed).
- Acceptance: no merchant total mixes currencies or defaults to EUR.

### FE-10 · Refund picker from the dedicated endpoint
- Ref: W-25 · Severity: Medium · Size: S · Depends on: CN-18
- Files: `pages/Transactions.tsx` (drop the unbounded `listTransactions({portfolio_id})`), `components/TransactionLogForm.tsx`, `lib/refunds.ts` (delete with its test if unused).
- What to do: the picker calls `/refund-candidates` with search and pagination (a search input in the form).
- Tests: e2e: the picker shows remaining amount and account as before; opening the Log makes no `/transactions` call without `limit`.
- Documents: DESIGN_NOTES `lib/refunds` → move/delete, CHANGELOG (Changed, performance).
- Acceptance: the Log never downloads the whole ledger.

### FE-11 · Composite operations as one request
- Ref: W-35 · Severity: Medium · Size: M · Depends on: CN-20
- Files: `components/PositionsSection.tsx` (`removeAssetFromPortfolio`), `components/AddPositionForm.tsx`, `components/BalanceSection.tsx` (`handleAdd`), `api/client.ts`.
- What to do: use `DELETE /portfolios/{pid}/positions/{asset_id}`, `POST holdings` with an inline `asset`, `POST cash-accounts` with `initial_balance`.
- Tests: existing e2e on positions and accounts green; new: a failure in the second part → nothing created.
- Documents: DESIGN_NOTES `PositionsSection`, `AddPositionForm`, `BalanceSection`; CHANGELOG (Changed).
- Acceptance: no user action leaves half-created data.

### FE-12 · Idempotency-Key on every creation of financial data
- Ref: W-36 · Severity: Medium · Size: S · Depends on: FE-01, CN-21
- Files: `api/client.ts` (`addHolding`, `createCashTransaction`, `createTransfer`, `convertToTransfer`, `createCashAccount`), the calling forms.
- What to do: a key generated when the form opens (or at the first submit), reused on retries of the same submit, regenerated after a success.
- Tests: Vitest on a small "key per attempt" helper; e2e: a fast double submit → one transaction.
- Documents: CHANGELOG (Changed), DESIGN_NOTES `api/client`.
- Acceptance: a retried or doubled submit never duplicates money.

### FE-13 · Job and backup status in "Modules & Status"
- Ref: W-21 · Severity: Medium · Size: S · Depends on: CN-15
- Files: `pages/Settings.tsx`, `api/client.ts`.
- What to do: a section showing the last outcome of the price refresh, snapshots, backup (date and folder) and alerts; a backup older than 2 days highlighted in red.
- Tests: e2e: after `run-now` the section shows today's backup.
- Documents: README "Your data" (where to see the outcome), CHANGELOG (Added).
- Acceptance: a missed backup is visible in the app.

### FE-14 · UX limits whose backend already exists
- Ref: W-38 · Severity: Low · Size: M
- Files: `components/AddPositionForm.tsx`, `components/PositionsSection.tsx`, `components/BalanceSection.tsx`, `pages/Portfolios.tsx`, `pages/Assets.tsx`.
- What to do:
  1. A date picker (max today) when adding a position.
  2. The list of a position's holding entries, with edit/delete of a single entry (`PATCH/DELETE /holdings/{id}` exist).
  3. Currency: a free 3-letter input with suggestions (EUR/USD/GBP/CHF) instead of a closed select, for portfolios, assets and accounts.
- Tests: e2e for points 1 and 2.
- Documents: README "What it does", CHANGELOG (Added).
- Acceptance: backdated positions and single-entry corrections are possible from the UI.

### FE-15 · Clean-up
- Ref: W-45 · Severity: Low · Size: S
- Files: `lib/chartTheme.ts` (`PALETTE_ACCENT` duplicates `PALETTES` in `context/PaletteContext.tsx`: derive it from there), history-telling comments in `components/BalanceSection.tsx` (~101-103) and `pages/Assets.tsx` (~208-216), to be rewritten in the present tense (the story goes to DESIGN_NOTES).
- Tests: `./run-tests.sh fast`, lint.
- Documents: CHANGELOG (Refactored).
- Acceptance: one palette table; comments describe the present.

---

## 12. WP-09 · Structural refactoring

### RF-01 · Report logic out of the routers
- Ref: W-40 · Severity: Medium · Size: S · Depends on: CN-06, CN-17 · Unblocks: RF-03
- Files: `app/routers/budgets.py` (`budget_progress`), `app/routers/expenses.py` (`compute_refund_adjustments`, `_category_namer`), `app/reports.py`, `app/alerts.py`.
- Problem: `alerts.py` calls an HTTP handler (`budget_progress`, with the `month=None` trick for its `Query`); `budgets.py` imports from `expenses.py`.
- What to do: move the computation into `reports.py` (`budget_progress(db, portfolio_id, month)`, `refund_adjustments(db, portfolio_id)`, `category_namer(db)`); routers and alerts call the service.
- Tests: integration unchanged (a pure move); update test imports.
- Documents: DESIGN_NOTES (move the entries), `CLAUDE.md` §1 if listed helpers move or are renamed, CHANGELOG (Refactored).
- Acceptance: no module outside `routers/` imports a router.

### RF-02 · Account eligibility rules in one place
- Ref: W-41 · Severity: Medium · Size: S · Depends on: CN-03, CN-20
- Files: `routers/expenses.py` (`create_cash_transaction`, `create_transfer`, `_check_importable_account`, `convert_to_transfer`), `routers/cash.py` (`add_cash_balance`), the CN-20 composite endpoints.
- What to do: `require_account_accepts(acc, operation)` with `operation ∈ {transaction, transfer, import, balance, convert}` and a rules table (archived, pension, voucher); messages unchanged (tests check them).
- Tests: integration unchanged; unit on the table.
- Documents: CHANGELOG (Refactored), `CLAUDE.md` §1 (a new helper to reuse).
- Acceptance: each eligibility rule is written once.

### RF-03 · Split `routers/expenses.py`
- Ref: W-39 · Severity: Medium · Size: M · Depends on: RF-01, RF-02
- What to do: `routers/categories.py`, `routers/merchants.py`, `routers/transactions.py` (CRUD, bulk, convert, list/export), `routers/transfers.py`, `routers/csv_import.py`, `routers/expense_reports.py` (summary, monthly, recurring, refund candidates). Register them in `main.py`. No URL or behaviour change.
- Constraints: `CLAUDE.md` lists `_transactions_query` in `routers/expenses.py`: update the reference.
- Tests: the whole suite green with only import changes in tests.
- Documents: DESIGN_NOTES (rename sections per file), `CLAUDE.md` §1, CHANGELOG (Refactored).
- Acceptance: no router file has more than one area of responsibility.

### RF-04 · Common service code in `shared/`
- Ref: W-42 · Severity: Medium · Size: M · Depends on: CN-14, GA-04, BS-06
- What to do: extract `backup_target(base, data_dir, name, logger)`, `consistent_copy`, `read_bounded(upload, limit)`, `run_column_migrations(engine, Base)`, `InvalidBackupError`, the `pre-restore-*` name validation and the `sys.path` bootstrap (where possible without circular imports). The gateway does not use `shared/` (its build context): either change its build context or keep its `_read_bounded` and document why.
- Tests: unit on each helper; the whole suite; `tests/unit/test_compose_build_contexts.py` and `test_service_requirements.py` green.
- Documents: README "Architecture" (what `shared/` holds), DESIGN_NOTES `shared/`, CHANGELOG (Refactored).
- Acceptance: none of these helpers exists in more than one copy (or the exception is documented).

### RF-05 · Frontend types generated from OpenAPI
- Ref: W-43 · Severity: Medium · Size: M · Depends on: RF-03
- What to do: a script exporting core's OpenAPI (import the app, `app.openapi()`) and generating types with `openapi-typescript` into `frontend/src/types/api.gen.ts`; `types/index.ts` re-exports/adapts; a CI step regenerates and fails if the file changes.
- Tests: `tsc -b` green; the new CI step.
- Documents: `tests/README.md` (the new check), README "Local development" (how to regenerate), CHANGELOG (Added).
- Acceptance: a backend schema change that the frontend types do not reflect fails CI.

### RF-06 · Schema version
- Ref: W-44 · Severity: Low · Size: S · Depends on: CN-16
- Files: `app/migrate.py`, `app/models.py`, `services/bank-sync/app/migrate.py`.
- What to do: a `schema_meta(key, value)` table with an integer `schema_version` written at the end of the migrations; at startup, if the DB version is **higher** than the code's, log an error and refuse to start (downgrade protection); on restore, refuse a backup newer than the code.
- Tests: `test_migrations.py`: a DB with a future version → startup refused with a clear message; restoring a future backup → 400.
- Documents: DESIGN_NOTES `migrate.py`, CHANGELOG (Added).
- Acceptance: old code never opens a newer database.

### RF-07 · Server state with TanStack Query
- Ref: W-37 · Severity: Low · Size: L · Depends on: RF-05, FE-05
- What to do: introduce `@tanstack/react-query`; migrate one page at a time (Dashboard, PortfolioDetail, Transactions…), with per-portfolio keys and targeted invalidation after writes; remove `useLatestFetch` and the anti-race refs once unused.
- Tests: full e2e after every migrated page.
- Documents: `CLAUDE.md` §1 (frontend helpers), DESIGN_NOTES (`PortfolioContext`, pages), CHANGELOG (Refactored).
- Acceptance: one mechanism for server state, with cancellation and invalidation.

---

## 13. WP-10 · Infrastructure, containers, CI

### OPS-01 · Real health checks and configured logging
- Ref: N-03, N-04 · Severity: Low · Size: S · Unblocks: OPS-02
- Files: every service's `main.py`, the gateway's `/health`.
- What to do: `/health` checks local dependencies (core: `SELECT 1`; bank: its DB; geo: data folder writable; price-feed stays "ok" and gains an optional `/health/deep` trying a cached ticker); `logging.basicConfig(level=INFO)` with a uniform format in core and geo (today their `logger.info` lines are not printed).
- Tests: system: an unreadable DB → health 503.
- Documents: CHANGELOG (Changed).
- Acceptance: a broken service reports itself as unhealthy.

### OPS-02 · Unprivileged containers, healthchecks, ordered start
- Ref: W-16, W-48 · Severity: Low · Size: M · Depends on: OPS-01, BS-01
- Files: every `Dockerfile`, `docker-compose.yml`, `tests/compose/smoke.sh` / `wait_for_stack.py`.
- What to do: a non-root user (`useradd`, `USER`), minding the permissions of existing volumes (`core_data` was created by root: an entrypoint that `chown`s once, or documented steps); `healthcheck:` in compose; `depends_on: {service: {condition: service_healthy}}`.
- Constraints: existing installations must upgrade without losing access to their data (test the upgrade on a volume created by the previous version).
- Tests: the CI `compose` job.
- Documents: README "Quick start"/"Your data" (permissions), DESIGN_NOTES (CI/compose), CHANGELOG (Changed).
- Acceptance: no service runs as root; start order follows health.

### OPS-03 · bank-sync configuration mounted as a folder
- Ref: W-47 · Severity: Low · Size: S · Depends on: BS-01
- Files: `docker-compose.yml`, `services/bank-sync/app/config.py`, `mcc_categories.py`, `links_config.py`, `.gitignore`, `.dockerignore`, `services/bank-sync/README.md`.
- Problem: mounting single files that do not exist makes Docker create directories in their place.
- What to do: `./services/bank-sync/config:/config:ro` with `links.yaml` and `mcc_categories.yaml` inside; for compatibility, read the old paths too for one version, with a log warning, and document the move.
- Tests: unit on `links_config`/`mcc_categories` with the new path; the compose job.
- Documents: `services/bank-sync/README.md` (Setup), README "Your data", `.gitignore`/`.dockerignore`, CHANGELOG (Changed).
- Acceptance: a missing config file never turns into a directory.

### OPS-04 · Stricter lint and strict TypeScript
- Ref: W-46, N-09 · Severity: Low · Size: M · Depends on: CN-13
- What to do: ruff with `B`, `ASYNC`, `DTZ`, `UP` (one at a time, fixing or with justified `noqa`); `strict: true` in `frontend/tsconfig.app.json` and removal of `any` (typed Recharts formatters, the `as any` in `AddPositionForm`/`Assets`).
- Tests: `./run-tests.sh lint` green; CI.
- Documents: `tests/README.md` (lint), `run-tests.sh` and the CI workflow updated together, CHANGELOG (Changed).
- Acceptance: the stricter rules pass on the whole codebase.

### OPS-05 · Dependency audit in CI
- Ref: N-10 · Severity: Low · Size: S
- What to do: a CI job running `pip-audit` on every `requirements.txt` and `npm audit --omit=dev --audit-level=high` on the frontend; warning-only at first, blocking after a clean-up.
- Documents: `tests/README.md`, CHANGELOG (Added).
- Acceptance: known vulnerabilities are reported on every push.

### OPS-06 · Pinned `serve` version
- Ref: W-45 · Severity: Low · Size: S
- Files: `frontend/Dockerfile` (`npm install -g serve@<version>`).
- Tests: the compose job.
- Documents: CHANGELOG (Changed).
- Acceptance: the frontend image build is reproducible.

---

## 14. WP-11 · Final documentation and code clean-up

### DOC-01 · Outdated documentation
- Ref: W-45 · Severity: Low · Size: S
- Files: `tests/README.md` (mentions `pydantic==2.9.2`, now `2.14.0`: reword without a specific version or update it), any reference left to old behaviour after WP-02…WP-10 (search for "8003", "sync-now", "today's rate", "across all your portfolios").
- Documents: CHANGELOG (Docs).
- Acceptance: no document describes behaviour that no longer exists.

### DOC-02 · Deprecated `datetime.utcnow()`
- Ref: W-45 · Severity: Low · Size: M · Depends on: OPS-04 (the `DTZ` rule lists them)
- Files: `models.py` (column defaults), `helpers.py`, bank-sync `models.py`, `sync.py`, `alerts.py`, `links_config.py`, `main.py`.
- What to do: a helper `utcnow_naive()` = `datetime.now(timezone.utc).replace(tzinfo=None)` (the DB stores naive UTC datetimes: **do not** change the stored format); replace every use.
- Tests: the full suite; `test_migrations.py` unchanged.
- Documents: CHANGELOG (Refactored).
- Acceptance: no `utcnow()` left; stored values identical.

---

## 15. WP-12 · Final evolutions (some need a decision)

### OPT-01 · Money as Decimal / Money — DECISION D-08
- Ref: W-08 · Size: L · Depends on: RF-03
- What to do if approved: `Numeric` money columns with data conversion (SQLite still stores REAL/TEXT; the change is mostly in the Python domain), a `Money(amount: Decimal, currency)` value object, Pydantic `Decimal`, JSON serialisation as string or number (decide: it affects the frontend). Plan it as several tasks: model → valuation → reports → API → frontend, added through §A.10.
- If not approved: a DESIGN_NOTES entry "Why float" with the existing mitigations (`_round3/_round4`, `Fraction` in the ledger); mark the task `done` with that note.

### OPT-02 · Optimistic concurrency
- Ref: W-23 · Size: M
- What to do: `updated_at` (or `version`) on editable entities; `PATCH` with `If-Match` or an `expected_version` field; 409 on conflict; the frontend reloads and warns.
- Tests: integration: two PATCHes from the same version → the second gets 409.
- Documents: DESIGN_NOTES, CHANGELOG (Added).

### OPT-03 · bank-sync: choose the account when a session holds several
- Ref: N-12 · Size: M · Depends on: BS-02
- What to do: an optional `account_iban_last4` or `account_name` in `links.yaml` to pick the account from the `/sessions` response; without it, today's behaviour. Update `services/bank-sync/README.md` ("What it deliberately doesn't do").
- Tests: unit on the account selection.
- Documents: bank-sync README, CHANGELOG (Added).

### OPT-04 · Internationalisation and automatic layout — DECISION D-10
- Ref: W-38 · Size: L
- What to do: an Italian interface (i18n with dictionaries, `Intl` with a configurable locale) as decided in D-10; the mobile layout proposed automatically on first run from the viewport width (the manual choice stays).
- Tests: Vitest on the dictionaries' completeness (every key in every language); e2e with each locale.
- Documents: README "What it does", CHANGELOG (Added).

### OPT-05 · Restoring an archived account
- Ref: W-38 · Size: S
- What to do: `POST /cash-accounts/{id}/unarchive` (clears `archived_at`; check that valuation does not bring the account back into the period it was archived, or state it); an "Archived accounts" list in PortfolioDetail.
- Tests: integration on valuation before/after unarchiving; e2e on the list.
- Documents: README "What it does", DESIGN_NOTES `CashAccount.archived_at`, CHANGELOG (Added).

---

## 16. Traceability (no open point left out)

| Ref | Short description | Tasks |
|---|---|---|
| W-01 | FX 1:1 not flagged outside the snapshot | CN-02, CN-04, CN-05, CN-06, FE-06 |
| W-02 | Transfers stored at 1:1 | CN-03, FE-07 |
| W-03 | Auto snapshot at today's price | CN-01 |
| W-04 | XIRR drops unpriced flows | CN-05 |
| W-05 | Asset growth with a zero price | CN-07 |
| W-06 | Time zone / clipped dates | CN-08 |
| W-07 | GBp/ILA/ZAc | PF-01 |
| W-08 | float for money | OPT-01 |
| W-09 | Currency change rewrites history | CN-09, FE-08 |
| W-10 | Deleted snapshot recreated | CN-10 |
| W-11 | bank-sync exposed without auth | BS-01 |
| W-12 | Bank audit log in clear text, unbounded, in backups | BS-03 |
| W-13 | Google Fonts | FE-04 |
| W-14 | Headers forwarded unfiltered | GW-02 |
| W-15 | Unsafe XML parser | GA-02 |
| W-16 | Root containers, no healthcheck | OPS-02 |
| W-17 | bank-sync duplicates | BS-02 |
| W-18 | Event loop blocked | SH-01, BS-05, CN-13, GA-01 |
| W-19 | Restore not isolated / not undoable | CN-14, GA-04, BS-06, GW-06 |
| W-20 | Orphan factsheets | GA-05, GW-07 |
| W-21 | Scheduler not observable | CN-15, FE-13 |
| W-22 | FKs not enforced | CN-16 |
| W-23 | Optimistic concurrency | OPT-02 |
| W-24 | Global refund scan | CN-17 |
| W-25 | Whole ledger downloaded in the Log | CN-18, FE-10 |
| W-26 | Unbounded caches | PF-02, CN-24 |
| W-27 | No HTTP pooling | GW-01, BS-04 |
| W-28 | Buffered responses | GW-05 |
| W-29 | Costly reconciliation | CN-19, BS-07 |
| W-30 | `crypto.randomUUID` | FE-01 |
| W-31 | STOCK/BOND accounts invisible | FE-02 |
| W-32 | Errors shown as "no data" | FE-05 |
| W-33 | Inconsistent UI texts | FE-03 |
| W-34 | Merchant totals in mixed currencies | CN-12, FE-09 |
| W-35 | Non-atomic composite operations | CN-20, FE-11 |
| W-36 | Idempotency-Key barely used | CN-21, FE-12 |
| W-37 | Server state handled by hand | RF-07 |
| W-38 | UX limits | FE-14, OPT-04, OPT-05 |
| W-39 | `expenses.py` too large | RF-03 |
| W-40 | Domain depending on routers | RF-01 |
| W-41 | Duplicated eligibility rules | RF-02 |
| W-42 | Duplication across services | RF-04 |
| W-43 | Hand-written types | RF-05 |
| W-44 | Unversioned migrations | RF-06 |
| W-45 | Minor clean-ups | CN-23, PF-03, GA-06, GW-04, FE-15, OPS-06, DOC-01, DOC-02 |
| W-46 | Minimal lint | OPS-04 |
| W-47 | Single-file bind mounts | OPS-03 |
| W-48 | No readiness | OPS-02 |
| N-01 | `/transactions` without scope | CN-11 |
| N-02 | Export with 2 decimals | CN-22 |
| N-03 | Shallow health checks | OPS-01 |
| N-04 | Logging not configured in core/geo | OPS-01 |
| N-05 | Non-atomic writes in geo | GA-03 |
| N-06 | 401 without CORS headers | GW-03 |
| N-07 | Upstream errors masked by the gateway | GW-04 |
| N-08 | Incomplete category-delete confirmation | FE-03 |
| N-09 | TypeScript not strict, `any` | OPS-04 |
| N-10 | No dependency audit | OPS-05 |
| N-11 | No SMTPS | SH-02 |
| N-12 | bank-sync: first account only | OPT-03 |
| N-13 | Base-currency change → retroactive backfill | CN-10 |
| N-14 | Idempotency key stuck "still being processed" (found in BS-02) | CN-25 |

---

*End of the workflow. Origin: read-only architectural review of commit `aa9fbec`. Each card describes the code at that commit: verify before changing.*
