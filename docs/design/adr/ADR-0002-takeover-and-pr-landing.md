# ADR-0002: Takeover of Part 5 and landing the open PRs on local main
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28

## Context
Operator, 2026-10-28: "we now own simon part 2 and 5". Part 5 is in flight upstream: the team (repo
owner) and Muse (agent) built the pipeline through #33; three PRs are open:
- #37 (the team): resample the follower onto the expected clip's clock (#35). Approved by Muse; the
  requested last-frame fix is folded in at `d181e99`.
- #36 (the team): the real `make check-5` (#14). Muse requested a guard against vacuous slices; fixed
  at `4ca9a66`; re-approval pending.
- #34 (ours): input contract, Part 3 and Part 4 schemas, Part 3's 15 follower takes. Muse requested
  that `contracts-check` stop raising a traceback on a stale local checkout.
All three touch `docs/schemas.md` or `Makefile`. #37 changes `follower_frames` to index the original
file. The team convention on #18 is that the author merges after the other's approval. Deadlines:
stitch-ready by 2026-10-29, complete by 2026-11-02.

## Options Considered
### Option 1: wait for the authors to merge
- Pros: follows the #18 convention exactly.
- Cons: #36 waits on a re-approval and #34 on our own fix; M1 (stitch-ready within 24 h) slips; every
  later lane builds on a moving base.
- Effort: Low, with unbounded waiting
### Option 2: land the three PRs on local main ourselves, in a fixed order, keeping authorship
- Pros: one known base for every lane; the team's commits keep their authors; the publish carries them upstream.
- Cons: departs from author-merges; a teammate may object.
- Effort: Low
### Option 3: rebuild the changes ourselves on main
- Pros: no merge conflicts.
- Cons: erases the team's authorship and Muse's review history.
- Effort: Medium

## Decision
Option 2 (operator decision 1). Order: #37, then #36, then #34.
- Merge each PR branch (`upstream/feat/resample`, `upstream/feat/check-5`, `upstream/feat/input-contract`)
  into local main with `git merge --no-ff`, so the team's commits keep their authorship. When a squash
  is unavoidable, the commit carries `Co-authored-by: the team <team@simon.live>` (the git identity on the PR branches).
- #36 lands with Muse's requested change addressed (`4ca9a66`: a gated slice with no labelled faults or
  no correct takes fails).
- #34 lands with the stale-checkout traceback turned into a plain-language error and exit 2.
- Conflicts in `Makefile` and `docs/schemas.md` keep both sides (target lists and sections).
- `make test` and `make check-5` run once after the third merge.
- Publish with `scripts/simon-publish.sh --pull`, `--dry-run`, then a real run. Then comment on each
  PR with the main commit that carries it, and close it.

Upstream etiquette (operator decision 7):
- At run start, a STATUS claim on #17 and #18; DECISION comments for the scope additions.
- Every comment starts with `🤖 **Agent** · Claude Code · Track A · <TYPE>`, as in our earlier STATUS
  comment on #18. @mention no one.
- A teammate objection on a thread overrides the decision; it is followed and recorded in STATUS.md.
- Issues close at DONE as Parts 3 and 6 did.

## Consequences
- **Positive**: M1 lanes start from one base; authorship is kept.
- **Negative**: the PRs close without the author pressing merge; the PR comments say why and name the
  commit.
- **Neutral**: Muse's open review comments stay on the closed PRs for reference.

## Assumptions
- ASM-009: landing approved or fixed PRs ourselves is acceptable to the team.

## Reversal Cost
Medium: a landed PR can be reverted on main and republished, but teammates may have built on it.

## Pre-Mortem (MANDATORY)
1. Merge order wrong, `follower_frames` meaning differs between check-5 and contract tests.
   Likelihood: L, Impact: M, Mitigation: the fixed order and one test run after the third merge.
2. the team objects to the takeover of these PRs. Likelihood: M, Impact: M, Mitigation: the objection
   overrides; the PR comment names the commit and invites it.
3. A publish carries a half-resolved conflict. Likelihood: L, Impact: H, Mitigation: the publish runs
   `make check-5` in a clean worktree of `upstream/main` with the mirrored files.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect)
Concerns:
- Author-merges is the team's rule: the operator decided otherwise for the deadline; the comment on
  each PR says so plainly.
- #36's re-approval is pending: Muse's requested change is in `4ca9a66`; the landing records that.
- Closing PRs looks abrupt: each close comment names the main commit, so nothing is lost.

## Code Backlinks (updated as code is written)
- `part5/pipeline.py` (#37), `part5/check.py` (#36), `scripts/sync_contracts.py` (#34)
