# ADR-0001: Development workspace on the the team Part 7 repo, one allowlisted publish path

> Copy of `docs/adr/ADR-0001-workspace-and-publish-layout.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted
Date: 2026-10-28

## Context
moalborati/simon-part-7-stitching-app is an empty scaffold at `90aa473` (`.gitignore`, `CLAUDE.md`,
`Makefile` with a failing `check-7` stub, `README.md`, `fixtures/input/.gitkeep`). Issue #1 is open and
unclaimed. The development workspace adds its own tooling (process rules, scripts, tickets) on local `main` (`7827c19`).
None of that tooling may reach the team. Parts 2, 3, 5 and 6 already use the same layout.

## Options Considered
### Option 1: work in a clone with an `origin` that pushes
- Pros: simplest. Cons: every tooling sync would push workspace files to the team's repo. Effort: Low.
### Option 2: a separate workspace repo that vendors the part as a subtree
- Pros: clean split. Cons: part files move away from where the Makefile and README expect them;
  every upstream merge becomes a subtree operation. Effort: Medium.
### Option 3: clone with no origin, workspace tooling beside the part files, allowlisted publish
- Pros: part files stay where upstream expects them; a publish script (workspace-only) copies only
  `.simon-publish` paths onto `upstream/main`. Cons: one more script to trust. Effort: Low (the
  Part 5 script is generic).

## Decision
Option 3. Remote `upstream` with pushing disabled, no `origin`, `main` local only. The publish script is the Part 5
workspace script with four changes: the upstream URL, `Refs #1`, no upstream-owned file under
the scripts folder and a default check timeout of 7200 s, because the publish check is
`make -s check-7`, which runs the whole chain on the GPU. The candidate's `make -s test` must pass or
the publish is refused; a red `check-7` is published and reported in the commit body.

Allowlist (`.simon-publish`): `Makefile README.md .gitignore pyproject.toml uv.lock part7/** web/**
tests/test_*.py tests/conftest.py CONTRACT.md contracts/** fixtures/** videos/manifest.json
videos/*/SOURCE.md parts.lock.json demo/** docs/app.md`. Upstream `CLAUDE.md` is never published
from here.

## Consequences
- **Positive**: tooling syncs commit locally and never push; teammates see only part files.
- **Negative**: teammates' changes arrive only through the publish script's `--pull`.
- **Neutral**: a publish runs `check-7` in a temporary worktree, which takes as long as one full
  check (it reuses the pinned clones and the downloaded videos under `~/.local/state/simon-part-7/`).

## Assumptions
- ASM-001: uv in `~/.local/bin` is found by scripts that prepend that directory to `PATH`.
- ASM-002: nobody else pushes to the Part 7 upstream during the run; `--pull` still runs first.

## Reversal Cost
Low: add an `origin` and drop the script; nothing upstream depends on the layout.

## Pre-Mortem (MANDATORY)
1. A publish ships a workspace-only file through a wide glob. Likelihood: L, Impact: M. Mitigation: the
   denylist runs after the allowlist and refuses the whole publish (tests AC-P4, AC-P13).
2. A key reaches upstream inside a log or fixture. Likelihood: L, Impact: H. Mitigation: every operator
   key name is refused by name and `sk-`, `hf_` and `AKIA` shapes by content (AC-P16, AC-P17).
3. The publish check times out on a slow GPU day. Likelihood: M, Impact: L. Mitigation: a red or
   timed-out check is reported in the commit body; tests still gate.

## Dissent (MANDATORY)
Reviewed at setup (architect review), 2026-10-28.
- Running `check-7` as the publish check makes each publish slow. Accepted: the commit body then
  carries the real metrics, and publishes are few (M1, M3, final).
- `demo/**` publishes the submission video into a code repo. Accepted: the hackathon needs it next to
  the code; the run keeps it under 50 MB (GitHub's warning size), see [`demo.md`](../specs/demo.md).

## Code Backlinks (updated as code is written)
- `.simon-publish` (the allowlist); the publish script and its tests are workspace-only.
