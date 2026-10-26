# Simon: agent instructions

Simon compares a follower's 3D movement against a trainer's recorded expected movement and says what differed. **Scope is the 7 parts in [docs/MINI-APPS.md](docs/MINI-APPS.md)** (defined by Mo on #1/#27); [PLAN.md](PLAN.md) just points there. Read [docs/progress.md](docs/progress.md) for decisions made since. Pick work from the part issues (label `mini-app`); do not work from superseded part lists.

## Coordination happens in GitHub Issues: follow docs/COLLABORATION.md

- Before working on a part, read its issue thread (`gh issue view <N> --comments`) and claim it with a `STATUS` comment + the `status:in-progress` label.
- Every comment you post starts with `🤖 **Agent** · Claude Code · Track <A|B|C> · <TYPE>` (`STATUS`, `QUESTION`, `DECISION`, `HANDOFF`, `BLOCKED`, `DONE?`).
- Ask team decisions as `QUESTION` + the `needs:human` label; don't guess.
- Each part is built in its own repo (table in docs/MINI-APPS.md); this repo is coordination and docs only. Push directly to `main` (no PRs unless the team asks): stage only your own files, `git pull --rebase`, then push. Commit messages say `Refs #N`. Never close issues.
- End each session with a `STATUS` comment on the issue you worked on.

## Commands

- In a part repo: `make check-<n>` is that part's done-check.
- `python import/budget_guard.py status`: Meta API spend. Every Meta API call goes through `import/budget_guard.py`.

## Conventions

- Never assume a specific movement in code: parts branch only on the shared-file formats in docs/MINI-APPS.md.
- Secrets live in `.env` (gitignored); never print or commit `MODEL_API_KEY`.
