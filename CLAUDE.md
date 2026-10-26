# Simon: agent instructions

Simon compares a follower's 3D movement against a trainer's recorded expected movement and says what differed. **Scope is the 7 parts in [docs/MINI-APPS.md](docs/MINI-APPS.md)** (defined by Mo on #1/#27); [PLAN.md](PLAN.md) just points there. Read [docs/progress.md](docs/progress.md) for decisions made since. Pick work from the part issues (label `mini-app`); do not work from superseded part lists.

## Coordination happens in GitHub Issues: follow docs/COLLABORATION.md

- Before working on a part, read its issue thread (`gh issue view <N> --comments`) and claim it with a `STATUS` comment + the `status:in-progress` label.
- Every comment you post starts with `🤖 **Agent** · Claude Code · Track <A|B|C> · <TYPE>` (`STATUS`, `QUESTION`, `DECISION`, `HANDOFF`, `BLOCKED`, `DONE?`).
- Ask team decisions as `QUESTION` + the `needs:human` label; don't guess.
- Push directly to `main` (no PRs unless the team asks): stage only your own files, run `make validate-fixtures`, `git pull --rebase`, then push. Commit messages say `Refs #N`. Never close issues.
- End each session with a `STATUS` comment on the issue you worked on.

## Commands

- `make validate-fixtures`: P0 done-check (schemas, both fixtures, rule checks).
- `make fixtures`: regenerate `fixtures/pushup.movement.json` and `fixtures/arm_phrase.movement.json`.
- `python import/budget_guard.py status`: Meta API spend. Every Meta API call goes through `import/budget_guard.py`.

## Conventions

- `schemas/movement.schema.json` is the catalog-entry/spec contract. Changing it needs a version bump and a `docs/progress.md` note.
- Never assume a specific movement in code: branch only on the shared-file schemas and rule definitions.
- `tools/measures.py` is the reference implementation of rule measures; live (TS) code must match it on the fixtures.
- Secrets live in `.env` (gitignored); never print or commit `MODEL_API_KEY`.
