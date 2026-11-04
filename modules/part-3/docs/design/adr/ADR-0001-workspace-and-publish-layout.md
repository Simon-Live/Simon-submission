# ADR-0001: Firm workspace on a teammates' repo, one allowlisted publish path

> Copy of the maintainers' working ADR `docs/adr/ADR-0001-workspace-and-publish-layout.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Date: 2026-10-27. Status: accepted.

## Context
moalborati/simon-part-3-skeleton-consistency is shared with teammates and kept small so agents work with
little context. Firm propagation commits about 500 files (rules, agents, scripts) and normally pushes
and opens PRs on `origin`; firm chat polls `deploy.issues`. None of that may reach the team.

## Options Considered
### Option 1: work directly in the the team clone with origin
Simple, but every firm sync would push firm files upstream.
### Option 2: separate firm repo that vendors the part as a subtree
Clean split, but the part's files would live under a subdirectory, unlike where the README expects
them, and every upstream merge becomes a subtree operation.
### Option 3: clone with no origin, firm layer beside the part files, allowlisted publish
The part's files stay at the repo root where upstream expects them; local `main` carries the firm
layer on top; `scripts/simon-publish.sh` copies only `.simon-publish` paths to `upstream/main`.

## Decision
Option 3. Remote `upstream` with its push URL set to `DISABLED-use-scripts/simon-publish.sh`, no
`origin`, `integration_branch: main` local only, registry `deploy.repo: null`. The publish script
(its spec stays in the maintainers' workspace) fails closed on its allowlist and refuses a hard denylist, runs
`make check-3` in a clean worktree of `upstream/main` and reports its result in the commit body.

## Consequences
- Firm sync commits locally and never pushes; its pre-push gate can leave a sync branch to merge by
  hand (setup did a fast-forward of `firm-sync/v1.15.1-20261027T202737Z`).
- Teammates' changes arrive by `scripts/simon-publish.sh --pull`.
- Propagation adds a line to upstream's `.gitignore` (`qa/runs/`) and a notice to upstream's
  `CLAUDE.md`; the publish filter drops the first and the denylist never publishes the second.

## Assumptions
Teammates push to upstream `main` directly (the team `docs/COLLABORATION.md`), so `--pull` is needed before each publish.

## Reversal Cost
Low: add an `origin` and drop the script; nothing upstream depends on the layout.

## Pre-Mortem (MANDATORY)
A publish ships a firm file because an allowlist glob was too wide. Guard: the denylist runs after the
allowlist and refuses the whole publish; the dry run prints the file list first.

## Dissent (MANDATORY)
The firm hooks still read upstream `CLAUDE.md` with the firm notice prepended, which makes the agent
context slightly larger than upstream intends. Accepted: the notice is five lines and stays local.

## Code Backlinks (updated as code is written)
`scripts/simon-publish.sh`, `tests/publish/test-simon-publish.sh`, `.simon-publish`.
