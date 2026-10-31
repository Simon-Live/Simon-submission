# ADR-0001: Firm workspace on a teammates' repo, one allowlisted publish path

> Copy of `docs/adr/ADR-0001-workspace-and-publish-layout.md` from the maintainers' working repo at `e846ede`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-28

## Context
moalborati/simon-part-2-images-to-3d is shared with the team (owner) and Muse (agent) and kept small so
agents work with little context. Firm propagation commits several hundred files (rules, agents,
scripts) and normally pushes and opens PRs on `origin`. None of that may reach the team. The same layout
already serves Parts 3, 5 and 6 of this project.

## Options Considered
### Option 1: work directly in the the team clone with origin
- Pros: simplest. Cons: every firm sync would push firm files upstream. Effort: Low.
### Option 2: separate firm repo that vendors the part as a subtree
- Pros: clean split. Cons: the part's files move under a subdirectory, unlike where the README and the
  Makefile expect them; every upstream merge becomes a subtree operation. Effort: Medium.
### Option 3: clone with no origin, firm layer beside the part files, allowlisted publish
- Pros: part files stay where upstream expects them; local `main` carries the firm layer on top;
  `scripts/simon-publish.sh` copies only `.simon-publish` paths to `upstream/main`. Cons: one more
  script to trust. Effort: Low (the Part 6 script is generic).

## Decision
Option 3. Remote `upstream` with its push URL set to `DISABLED-use-scripts/simon-publish.sh`, no
`origin`, `integration_branch: main` local only, registry `deploy.repo: null`. The publish script
(spec `simon-publish.md (maintainers' tooling spec, not published)`) fails closed on its allowlist, refuses a hard denylist, runs its
check command in a clean worktree of `upstream/main` and reports the result in the commit body. The
allowlist names every path upstream owns on 2026-10-28 so the mirror never deletes a teammate's file.

## Consequences
- **Positive**: firm sync commits locally and never pushes; teammates see only part files.
- **Negative**: teammates' changes arrive only by `scripts/simon-publish.sh --pull`.
- **Neutral**: propagation adds `qa/runs/` to upstream's `.gitignore` and a notice to `CLAUDE.md`; the
  publish filter drops the first and the denylist never publishes the second.

## Assumptions
- ASM-008: teammates may still push to upstream `main`, so `--pull` runs before each publish.

## Reversal Cost
Low: add an `origin` and drop the script; nothing upstream depends on the layout.

## Pre-Mortem (MANDATORY)
1. A publish ships a firm file because a glob was too wide. Likelihood: L, Impact: M. Mitigation: the
   denylist runs after the allowlist and refuses the whole publish; the dry run prints the list first.
2. A publish deletes a teammate's new top-level file. Likelihood: L, Impact: M. Mitigation: paths outside
   the allowlist are never touched (test AC-P6).
3. A teammate pushes between fetch and push. Likelihood: M, Impact: L. Mitigation: one refetch and retry.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect role)
- The firm notice makes the local `CLAUDE.md` slightly larger than upstream intends: accepted, it stays local.
- Firm tool tests (`tests/test-*.sh`) share `tests/` with part tests: the allowlist names `tests/test_*.py`
  and `tests/conftest.py` only.
- The publish check starts as `make -s test` (ADR-0006): accepted until scored outputs are committed.

## Code Backlinks (updated as code is written)
- `scripts/simon-publish.sh`, `tests/publish/test-simon-publish.sh`, `.simon-publish`.
