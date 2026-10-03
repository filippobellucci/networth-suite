# Working on Net Worth Suite

## Before changing code

Read the section of `DESIGN_NOTES.md` for every file you are about to change. It holds the history
behind code that looks arbitrary or over-careful: most entries describe a bug that removing the
"odd" bit would bring back.

## Comments

- A comment says what the code does now and why, in the present tense, briefly.
- History -- what used to break, measurements, approaches that were tried -- goes in
  `DESIGN_NOTES.md`, under the file it concerns, not in the code.
- Every change gets an entry at the top of `CHANGELOG.md`.

## Checking a change

`./run-tests.sh fast` while working, `./run-tests.sh` before committing, `./run-tests.sh all`
(browser tier included) before a release, `./run-tests.sh lint` for ruff, tsc and oxlint. How to
write a test, and which tier it belongs in: `tests/README.md`.
