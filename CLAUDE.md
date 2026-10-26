# Simon: agent instructions

Simon turns any movement routine (exercise, pilates, yoga, dance) into a live camera coach. Read [PLAN.md](PLAN.md) for the plan (milestones M1–M5, parts P0–P18, spikes S1–S5) and [docs/progress.md](docs/progress.md) for decisions made since.

## Coordination happens in GitHub Issues: follow docs/COLLABORATION.md

- Before working on a part, read its issue thread (`gh issue view <N> --comments`) and claim it with a `STATUS` comment + the `status:in-progress` label.
- Every comment you post starts with `🤖 **Agent** · Claude Code · Track <A|B|C> · <TYPE>` (`STATUS`, `QUESTION`, `DECISION`, `HANDOFF`, `BLOCKED`, `DONE?`).
- Ask team decisions as `QUESTION` + the `needs:human` label; don't guess.
- Work on a branch, open PRs with `Refs #N`, never close issues or merge your own PR.
- End each session with a `STATUS` comment on the issue you worked on.

## Commands

- `make validate-fixtures`: P0 done-check (schemas, both fixtures, rule checks).
- `make fixtures`: regenerate `fixtures/pushup.movement.json` and `fixtures/arm_phrase.movement.json`.
- `python import/budget_guard.py status`: Meta API spend. Every Meta API call goes through `import/budget_guard.py`.

## Conventions

- `schemas/movement.schema.json` is the contract between import and live. Changing it needs a version bump, a `docs/progress.md` note, and agreement from both the Track A and Track B owners on the issue.
- Never assume a specific movement in code: branch only on `movement.structure`, `follower_mirrors`, `music`, and rule definitions.
- `tools/measures.py` is the reference implementation of rule measures; live (TS) code must match it on the fixtures.
- Secrets live in `.env` (gitignored); never print or commit `MODEL_API_KEY`.
