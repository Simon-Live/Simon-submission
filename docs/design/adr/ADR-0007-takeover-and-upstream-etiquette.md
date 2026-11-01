# ADR-0007: Taking over an in-flight part; how we talk and publish upstream

> Copy of `docs/adr/ADR-0007-takeover-and-upstream-etiquette.md` from the maintainers' working repo at `f43deee`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted (stakeholder-proxy, 2026-10-28)
Date: 2026-10-28

## Context
The operator said on 2026-10-28 "we now own simon part 2 and 5". the team owns the repo; Muse (agent)
and an earlier Claude Code session worked it through threads #17 (checklist) and #18 (team chat), with
#46 (API-only pipeline) open. Our PR #47 (contract) is open and approved by Muse. the team
`docs/COLLABORATION.md` sets Track A, the robot header and the claim rule. Parts 3 and 6 closed their
issues at DONE with operator approval; the registry records the same approval for this part.

## Options Considered
### Option 1: work silently and publish at the end
- Pros: no noise. Cons: teammates may duplicate work or be surprised. Effort: Low.
### Option 2: claim at the start, decide in the open, publish by milestone
- Pros: teammates see the plan and can object. Cons: more comments. Effort: Low.

## Decision
Option 2.
- At the start: a STATUS claim comment on #17 and #18 (robot header, Track A, one-prompt unattended run,
  the milestone plan).
- Merge PR #47's content into local `main`, publish it through `scripts/simon-publish.sh`, then comment on
  #47 with the publish commit and close it.
- DECISION comments: on #46 (B and C both built behind a lifter registry, default by measurement, Muse's 3D
  bar adopted) and on #18 (the t_ms rule and `mirrored`, as locked in `docs/design/specs/integration-contract.md`).
- A teammate objection on a thread overrides a decision; it is followed and recorded in STATUS.md.
- Publish is a direct push to `main` via `scripts/simon-publish.sh` after `--pull`.
- At DONE: DONE? on #17 with the evidence; close #17, #18 and #46 with a closing note. @mention no one.
- Every comment is written to a file and posted with `gh issue comment <n> -R moalborati/simon-part-2-images-to-3d
  --body-file <file>`; texts are in the goal brief.

## Consequences
- **Positive**: decisions are visible where the team reads them.
- **Negative**: the team may disagree after the fact; the override rule handles it.
- **Neutral**: Muse's in-flight #46 work is absorbed into the registry, credited in the DECISION text.

## Assumptions
- ASM-008 (teammates may still push to `main`).

## Reversal Cost
Low for comments; Medium for a publish (a revert commit through the same script).

## Pre-Mortem (MANDATORY)
1. the team objects to closing issues. Likelihood: L, Impact: M. Mitigation: reopen and record.
2. Muse pushes a conflicting change mid-run. Likelihood: M, Impact: M. Mitigation: `--pull` before each publish;
   conflicts resolved on local `main` keeping both sides' intent.
3. A comment leaks the staging URL or login. Likelihood: L, Impact: H. Mitigation: the brief bans it; texts
   are reviewed before posting.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect role)
- COLLABORATION.md says not to close issues: the operator approval for this part overrides, as for Parts 3 and 6.
- Merging our own PR looks self-serving: Muse approved it on the PR.
- Direct push skips review: the publish body carries the check result and the commit list.

## Code Backlinks (updated as code is written)
- `goals/complete-simon-part-2.md` "Upstream comment texts".
