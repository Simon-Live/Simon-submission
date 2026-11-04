# ADR-0001: Firm workspace on a teammates' repo, one allowlisted publish path
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28

## Context
moalborati/simon-part-5-fault-analysis is shared with the team (team) and Muse (agent) and kept small
so agents work with little context. Firm propagation commits several hundred files (rules, agents,
scripts, firm tool tests) and normally pushes and opens PRs on `origin`; firm chat polls
`deploy.issues`. None of that may reach the team.

Part 5 differs from Parts 3 and 6 in two places:
- Upstream owns files inside paths the firm treats as its own: `scripts/make_dummy_followers.py`,
  `scripts/make_output_examples.py`, and PR #34 adds `scripts/sync_contracts.py` (its Makefile targets
  `contracts-check` and `contracts-sync` call it). Upstream also owns `docs/schemas.md` and, from #15,
  `docs/thresholds.md`.
- Upstream keeps its pytest files at the `tests/` root (`tests/test_*.py`). Firm propagation put
  `tests/test-*.sh` and `tests/lib/` beside them.

## Options Considered
### Option 1: work directly in the the team clone with origin
- Pros: simple.
- Cons: every firm sync would push firm files upstream.
- Effort: Low
### Option 2: separate firm repo that vendors the part as a subtree
- Pros: clean split.
- Cons: the part's files leave the repo root where the README expects them; every upstream merge
  becomes a subtree operation.
- Effort: High
### Option 3: clone with no origin, firm layer beside the part files, allowlisted publish
- Pros: the part stays at the root; local `main` carries the firm layer; one script decides what leaves.
- Cons: the allowlist and the denylist must know about upstream's files inside firm paths.
- Effort: Low

## Decision
Option 3, as Parts 3 and 6. Remote `upstream` with its push URL set to
`DISABLED-use-scripts/simon-publish.sh`, no `origin`, `integration_branch: main` local only, registry
`deploy.repo: null`. `scripts/simon-publish.sh` (spec `docs/design/specs/simon-publish.md`) is Part 6's
generic script with the Part 5 URL and three additions:
- `DENY_EXCEPT`: exactly `scripts/make_*.py` and `scripts/sync_contracts.py`, and only when the file
  sits directly under `scripts/`. Any other file under `scripts/` is a firm file and is refused.
- `DENY_GLOBS`: `tests/test-*.sh` is refused; `tests/lib/`, `tests/publish/`, `tests/staging/` and
  `tests/neighbour/` are denied prefixes. `tests/test_*.py` publishes.
- `docs/` is not denylisted; only `docs/specs/`, `docs/adr/` and `docs/assumptions/` are. So
  `docs/schemas.md` and `docs/thresholds.md` need no exception, only an allowlist line.
The denylist runs after the allowlist and refuses the whole publish. The publish runs `make check-5`
in a clean worktree of `upstream/main` and reports its exit code in the commit body with `Refs #17`.

Deviation from the setup brief: it named the exception as exactly `scripts/make_*.py`.
`scripts/sync_contracts.py` was added because landing #34 puts it on main and the published Makefile
targets need it upstream.

## Consequences
- **Positive**: firm files never leave; teammates see only part files; the denylist is tested
  (`tests/publish/test-simon-publish.sh`, 53 checks).
- **Negative**: a new upstream-owned file under `scripts/` needs an exception and a test before it can
  publish.
- **Neutral**: firm sync commits locally and never pushes. Teammates' changes arrive by
  `scripts/simon-publish.sh --pull`. Propagation adds `qa/runs/` to `.gitignore` and a notice to
  `CLAUDE.md`; the publish filter drops the first and the denylist never publishes the second.

## Assumptions
- Teammates push to upstream `main` directly or merge PRs there, so `--pull` runs before each publish.

## Reversal Cost
Low: add an `origin` and drop the script; nothing upstream depends on the layout.

## Pre-Mortem (MANDATORY)
1. A publish ships a firm file because an allowlist glob was too wide. Likelihood: L, Impact: H,
   Mitigation: the denylist refuses the whole publish; test P13 allowlists `scripts/**`, `docs/**` and
   `tests/**` and checks every firm file is refused.
2. An upstream-owned file under `scripts/` is silently withheld. Likelihood: M, Impact: M, Mitigation:
   the dry run prints the file list; `make check-5` runs in the publish worktree and fails when a needed
   file is missing.
3. A nested file such as `scripts/make_dir/x.py` passes the exception. Likelihood: L, Impact: M,
   Mitigation: the exception requires the file to sit directly under `scripts/` (test P13).

## Dissent (MANDATORY)
Reviewed by: setup lane (architect)
Concerns:
- Exceptions inside a firm prefix weaken a simple rule: accepted; the list is two globs and tested.
- The firm hooks read upstream `CLAUDE.md` with the firm notice prepended: accepted; the notice stays
  local.
- `package.json` (the Playwright pin for staging verify) never goes upstream, so upstream cannot run
  the browser verify: accepted; staging is firm-only and `make check-5` needs no browser.

## Code Backlinks (updated as code is written)
- `scripts/simon-publish.sh`, `DENY_EXCEPT`, `DENY_GLOBS`, `denied()`
- `tests/publish/test-simon-publish.sh`, AC-P1 to AC-P13
- `.simon-publish`
