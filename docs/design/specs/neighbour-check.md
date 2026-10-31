# Spec: local neighbour check through Parts 2, 3 and 4 (`scripts/neighbour-check.sh`, never published)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature
Risk Level: routine
Master spec: `part5-fault-analysis.md`. Companion: `integration-contract.md`. Ticket: TICKET-012.
Use case: uc-integration-contract. Milestone: M1.
Revised 2026-10-31 for ADR-0012 (always analyse): a take that is not the example's movement is no longer refused
with exit 3, it is analysed with a `low_match` warning and graded F, so the mismatch rows expect `warned`.

## Overview
A firm-only script that clones the current upstream `main` of Parts 2, 3 and 4 into a temporary
directory and runs the real chain on their shared files: Part 2's committed `pose3d.json` outputs go
through Part 3 `run --view part5`, then `python -m part5 doctor --for part5`, then `python -m part5
analyse` against Part 4's expected clips and `part3-squat`. Part 6's `CONTRACT.md` is read to confirm the
Follow hand-off shape `{v, id, files: {keyframes, skeleton, animation, video}}`. Every step's exit code
goes into `progress/neighbour-check-<date>.json`. A red step is reported, never hidden.

## Why This Is Wrong (Dissent-First)
1. Running another part's CLI looks like using its code. Answer: it runs as a black-box tool in a temp
   clone; nothing is imported or copied into Part 5.
2. Upstream mains move; a green result today is not a promise. Answer: commits are recorded per run.
3. Network failure would look like a red chain. Answer: a fetch failure ends with a named blocker, not a
   red step.

## User Story
As the team at stitching time, I see whether today's Parts 2, 3 and 4 files go through Part 5.

## Steps (each recorded as `{step, command, exit, note}`)
1. Clone `moalborati/simon-part-2-images-to-3d`, `moalborati/simon-part-3-skeleton-consistency` and
   `moalborati/simon-part-4-animate-keyframes`, and read `moalborati/simon-part-6-recording-catalog` `CONTRACT.md`
   (shallow `git clone`; names confirmed with `gh repo list the team` on 2026-10-28). Record each commit.
2. For each committed Part 2 `pose3d.json` (single, class, dance): Part 3 `python3 -m part3 run --in ...
   --out <tmp> --view part5` in its clone.
3. `python -m part5 doctor <out> --for part5` on each.
4. `python -m part5 analyse` on every pair in the table below; each step passes when its outcome is the
   expected one: an exit code (`0`), or `warned` (exit 0, and the analysis that was written has a `low_match`
   warning and `score.grade` `F`, judged from the file).
5. Part 2's `fixtures/output/stock/<clip>/pose3d.json`, when Part 2 has published it, through Part 3
   `--view part5` and then the stock pairs below; before that, those rows are recorded as `skipped` with
   the reason, never as a pass.
6. `doctor` on Part 4's `animation.json` files and Part 3's `--view part4` output (expected clip role).
7. Hand-off shape in Part 6's `CONTRACT.md` matches `integration-contract.md`; mismatch is a red step.

### Expected outcome per pair (`analyse --expected <E> --follower <F>`)
| Follower F | Expected E | Expected outcome | Why |
|---|---|---|---|
| Part 2 `single` (a seated stretch) via Part 3 `--view part5` | Part 4 `part3-squat` | `warned`; exit 0 while the committed file is the provisional squat (sha256 `433ae2ed`) | not a squat; a `low_match` warning and grade F is the pass (the provisional squat is a matched pair) |
| Part 2 `single` via Part 3 `--view part5` | Part 4 `exercise` | `warned`; exit 0 while it is the provisional squat | not the exercise movement |
| Part 2 `class` (cat-cow yoga) via Part 3 `--view part5` | Part 4 `part3-squat` | `warned` | not a squat (AC-004) |
| Part 2 `dance` via Part 3 `--view part5` | Part 4 `part3-squat` | `warned` | not a squat |
| Part 2 `scored/single` (the seated stretch) via Part 3 `--view part5` | Part 4 `part3-squat` | `warned` | not a squat |
| Part 2 `scored/single` via Part 3 `--view part5` | Part 4 `exercise` | `warned` | not the exercise movement |
| Part 3 kit takes (`fixtures/input/contract/part3/followers/`, from #34) | Part 4 `part3-squat` | exit 0 | matched real pair |
| Stock 5034577 (front) via Parts 2 and 3 | stock 5034562 (side) | exit 0 | matched real pair (`real-takes.md`) |
| Stock 8837221 (three-quarter) via Parts 2 and 3 | stock 5034562 (side) | exit 0 | matched real pair |

Exit 1 or 2 on any row is red. A `warned` row is red when `analyse` exits anything but 0, or when the analysis
it wrote has no `low_match` warning or a grade other than F (a different movement graded as a match). Exit 3 is
no longer produced (ADR-0012) and is red on every row. A red row is reported with the exit code, the warning
codes, the grade and the guard statistics of the analysis that was written.

## API / Interface Contract
`scripts/neighbour-check.sh [--keep]`. Writes `progress/neighbour-check-<YYYYMMDD>.json`:
`{date, commits: {part2, part3, part4, part6}, steps: [...], passed, failed, skipped, blocker}`, each step
`{step, id, command, expected, exit, result, note}` with `expected` an exit code or `"warned"`. Exit 0 when every
step met its expectation, 1 when any step is red, 3 on a named blocker (network, clone). Temp dir under
`mktemp -d`, removed by a trap with `find -delete` on that exact prefix (never `rm -rf` on a variable);
`--keep` leaves it and prints the path.

## Acceptance Criteria
### AC-N01: chain recorded
Given a run, the JSON lists every step with its command and exit code and each repo's commit.
### AC-N02: red reported
Given a step that fails, overall exit is 1 and the JSON names it; nothing is retried silently.
### AC-N03: warned expected
Given Part 2's `single` (the seated stretch), `class` or `dance` against the squat, the step passes only
when `analyse` exits 0 and the analysis it wrote has a `low_match` warning and `score.grade` `F` (judged
from the file: an exit 0 with no warning, or a grade above F, is red, and so is an exit 3); given a matched pair
(the provisional squat `single` included, classified by its sha256), only when it exits 0.
### AC-N04: blocker named
Given no network, exit 3 with `blocker` naming the failed clone.
### AC-N05: never published
Given `scripts/simon-publish.sh --dry-run`, `scripts/neighbour-check.sh` is not listed.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| Clone fails | exit 3 | `neighbour-check: blocker: cannot clone <repo>` | AC-N04 |
| Part 3 run fails | step red, continue | `step <n>: exit <code>` | AC-N02 |

## Edge Cases
- Part 2 adds new output folders: every committed `pose3d.json` is included and named.
- Part 3 needs Python packages: run with its own documented setup; a setup failure is a red step.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | Run | under 10 minutes | AC-N01 |
| Security | No secrets | public read only through `gh` | AC-N04 |

## Negative Requirements
- MUST NOT import or copy code from another part into this repo. MUST NOT push or comment anywhere.
- MUST NOT hide a red step or mark a blocker as a pass.

## Non-Requirements
- Running Part 6 or Part 7 code.

## Assumptions
ASM-001 (neighbour file shapes). The repo names were listed with `gh repo list the team` on 2026-10-28.

## Delivery Verification Plan
- One run at the M1 close-out and one before delivery review; both JSON files committed in `progress/`.

## Dissent Review
### Concern 1: the chain depends on Part 3's Python setup
Kept: a setup failure is reported as red with the message, which is what stitching day needs to know.
### Concern 2: expectations hard-coded per step
Kept: the expectations are the use cases (a warning and grade F for a different movement), not tuned numbers.

## Deviations from PRD
None.
