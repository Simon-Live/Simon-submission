# Spec: calibration on seed 5, frozen rules, held-out attempts on seeds 29, 31, 37 (#15)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADRs: ADR-0003, ADR-0004. Tickets: TICKET-015 (guard limits),
TICKET-016 (refresh and retune), TICKET-017 (dropout variant), TICKET-018 (held-out and gate).
Milestone: M2.

## Overview
Every threshold in `part5/rules.json` (per-measure `threshold_deg`, `min_fraction`, `min_run_frames`,
`min_overlap`, `smooth_frames`, the new `knee_valgus` entry and the `guard` limits) is tuned on the seed 5
tuning set only. The rules file and the code are then frozen in one commit, the hash written in
`docs/thresholds.md`. Only after that commit is the next unused held-out seed generated, once, and scored,
once, by `make check-5`. Every attempt's result is published as measured; no held-out number is ever
used to tune.

## Why This Is Wrong (Dissent-First)
1. A sweep over many parameters on 216 takes can still overfit the tuning seed. Answer: a coarse grid,
   precision first then recall, and the held-out number is the honest one.
2. Refreshing the expected clips after tuning would invalidate the tuning. Answer: refresh first
   (TICKET-016), regenerate seed 5, then tune.
3. A red held-out result tempts a "small fix". Answer: a threshold nudge is never a retry. Only a distinct
   approach family earns a new attempt, on a new seed, with the red result published beside it; after
   seed 37 the DEGRADED ending is the only response.

## User Story
As the team, I want thresholds chosen on data the gate never sees, so that a green check means skill.

## Order (fixed)
1. TICKET-016: copy Part 4 main expected clips, record the commit; regenerate seed 5
   (`make dummy-data`, with `knee_caving` from TICKET-014 and the 9-take grid).
2. TICKET-015: guard statistics on seed 5 plus the mismatch pairs; limits chosen (below).
3. TICKET-016: threshold sweep on seed 5 (below); `rules.json` and `docs/thresholds.md` committed in one
   commit whose message says "frozen".
4. TICKET-017 and TICKET-018: held-out attempts under the protocol below.

## Held-out protocol (ADR-0003)
- Thresholds, guard limits and method changes are tuned on seed 5 only.
- Held-out seeds are fixed now, in order 29, 31, 37.
- Each attempt freezes `rules.json` and the code in one commit, writes the hash and a one-paragraph
  rationale to `docs/thresholds.md`, then generates the next unused seed once
  (`make heldout-data SEED=<n>`, which passes `--dropout-variant`) and scores it once (`make check-5`).
- Every attempt's result, pass or fail, is published in `docs/thresholds.md` and in the `make check-5`
  JSON under `attempts[]`, and appended once to `fixtures/heldout-attempts.json` (seed, freeze commit, `rules_sha256`, approach family, per-slice numbers,
  passed).
- A seed once scored is retired: never regenerated, rescored or used for tuning.
- A retry is allowed only for a distinct approach family (a new measure, a different alignment or
  persistence rule), never a threshold nudge alone. The rationale paragraph names the family.
- Still red after the last seed: DEGRADED with every attempt's numbers.
- After a green attempt, confirm on the next unused seed (report both). A red confirmation counts as a
  red attempt; a green attempt on seed 37 is reported with "no seed left to confirm".

## Sweeps (`part5/calibrate.py`, offline, deterministic)
- Thresholds: per measure, `threshold_deg` over a grid of 1 degree steps around the current value; then
  `min_fraction`, `min_run_frames`, `min_overlap`. Objective on the seed 5 good-light slices, per angle:
  first precision 0.85 or more with 0 faults on correct takes at every angle, then the highest minimum
  recall across angles. The values tied at the best objective form a plateau; the frozen value is the
  middle of its longest contiguous run, rounded up to the grid step (equal runs: the one with the larger
  values); a plateau that reaches the grid edge extends the grid once; a fully flat key keeps its current
  value. `docs/thresholds.md` records both plateau ends and the grid per key. (Amended 2026-10-29 before
  any held-out seed, decided by stakeholder-proxy, confidence medium: "ties go to the larger threshold"
  put every labelled measure at seed 5's recall cliff. A later change of selection rule alone is a
  threshold nudge, never a retry.) Low light is reported in the sweep, not used to choose.
- Guard: `residual` and `timing_corr` for every seed 5 take against its own expected clip (all lights,
  all faults) and for the mismatch pairs: every exercise take against the dance clip, every dance take
  against the exercise clip, and Part 2's committed `class` (cat-cow yoga), `dance` and `single` (a
  seated stretch) takes through Part 3 `--view part5` against the squat; `single` counts only once Part 2 publishes its seated-stretch output; while the committed `single/pose3d.json` is the provisional squat clip (sha256 `433ae2ed`), it is a matched squat pair, reported and never in the mismatch population (stakeholder-proxy, 2026-10-29). The sweep
  table prints the exclusion and its reason; the squat `single` against `part3-squat` is reported with
  its guard statistics as a matched reference, never tuned on. Each limit sits at the midpoint of the gap; if the populations overlap, the limit
  keeps every matched tuning take passing and the overlap is reported.
- `python -m part5.calibrate --set fixtures/input/followers [--guard] [--write-thresholds]` prints the
  sweep table and, with `--write-thresholds`, writes `docs/thresholds.md`.

## `docs/thresholds.md` (published)
Chosen values per key with the reason (the sweep row that chose it); the guard limits with both
populations' ranges and the gap; the seed 5 per-slice table at the chosen values; the expected clip
commit; a statement that held-out numbers were not used to tune. Then one section per attempt, in seed
order: the freeze commit, `rules_sha256`, the date, the one-paragraph rationale (approach family and why),
and, after scoring, the held-out table as measured, pass or fail.

## Acceptance Criteria
### AC-T01: tuning reads seed 5 only
Given `calibrate`, when run, then it refuses a `--set` whose `labels.json` seed is not 5 (exit 2).
### AC-T02: frozen before each held-out attempt
Given git history, for every entry in `attempts[]`, the commit that generates that seed's
`fixtures/input/heldout/labels.json` comes after the attempt's freeze commit, no `part5/` or
`rules.json` change sits between the two, and the attempt's `rules_sha256` in `docs/thresholds.md`
equals the hash of `rules.json` at the freeze commit.
### AC-T03: each held-out seed generated and scored once
Given `attempts[]`, each seed appears at most once, seeds follow the order 29, 31, 37 with none skipped,
each was generated by one commit, and regenerating it at that commit reproduces it byte for byte. A
retry's rationale names an approach family different from every earlier attempt's.
### AC-T04: guard separation
Given the chosen limits, every seed 5 matched take passes and every mismatch pair is a low match (analysed with a warning and grade F, ADR-0012), or the
overlap is listed in `docs/thresholds.md` with the takes named.
### AC-T05: deterministic sweep
Given two sweep runs, the printed tables are identical.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| `--set` is not seed 5 | exit 2 | `calibrate: tuning reads seed 5 only (got <n>)` | AC-T01 |
| No mismatch fixture | exit 2 | `calibrate: <file> missing; run the neighbour check or TICKET-015 fixtures` | AC-T04 |

## Edge Cases
- `knee_valgus` undetectable on the dance set: the sweep reports it; the threshold is chosen on what
  seed 5 shows; the held-out number is reported as measured.
- A measure whose best threshold sits at the grid edge: extend the grid once and note it.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | Full sweep | under 30 minutes, detached | AC-T05 |
| Reliability | Determinism | identical tables | AC-T05 |

## Negative Requirements
- MUST NOT read, print or use held-out numbers before the attempt's freeze commit. Why: ADR-0003.
- MUST NOT regenerate, rescore or tune on a scored seed, skip a seed, or retry with a threshold nudge
  alone. Why: ADR-0003.
- MUST NOT drop a red attempt from `docs/thresholds.md` or `attempts[]`.

## Degraded ending
If the gate is still red after the last seed (37): publish the honest result, post STATUS (not DONE?)
with every attempt's numbers, write STATUS.md, end with `STATUS: DEGRADED` and the per-slice numbers of
every attempt.

## Non-Requirements
- Cross-validation folds; learned models.

## Assumptions
ASM on seed independence and on the expected clip refresh (`docs/assumptions/`).

## Delivery Verification Plan
- `git log --oneline -- part5/ fixtures/input/heldout/labels.json` shows each freeze commit before its
  seed's generation commit.
- `make check-5` on the current held-out seed; `docs/thresholds.md` committed with every attempt.

## Dissent Review
### Concern 1: a midpoint guard limit is fragile on real takes
Kept: real takes are reported with their guard stats, so a wrong refusal is visible on stock and kit.
### Concern 2: precision first may starve recall at the side angle
Kept: the objective is #15's stated order; the per-angle recall is printed.

## Deviations from PRD
None.
