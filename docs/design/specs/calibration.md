# Spec: calibration on seed 5, frozen rules, held-out attempts on seeds 29, 31, 37, then 67, 71, 73 (#15)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADRs: ADR-0003, ADR-0004, ADR-0017. Tickets: TICKET-015 (guard limits),
TICKET-016 (refresh and retune), TICKET-017 (dropout variant), TICKET-018 (held-out and gate), TICKET-044
(attempt 4, the first seed of the second series).
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
- Amendment (operator ruling 2026-10-31, TICKET-040): after a green, confirmed attempt, a new measure is a new approach
  family and needs its own held-out score on the next unused seed. Attempt 3 (seed 37, foot keypoints) was that case;
  it was red (`docs/thresholds.md`), so the held-out seeds are used up.
- Amendment (stakeholder-proxy ruling 2026-10-31T22:25Z, moalborati/simon#59, ADR-0017): the held-out order becomes 29, 31,
  37, then the second series 67, 71, 73, fixed before any detection change. Each seed of the second series is generated
  once (`make heldout-data SEED=<n>`, with feet as seed 37 was) after its attempt's freeze commit and scored once; no
  tool reads it before that freeze. Where this spec names seed 37 as the last seed, the last seed is 73. The gate
  thresholds do not change, and seed 37's red attempt stays in `attempts[]`, `fixtures/heldout-attempts.json` and
  `docs/thresholds.md`. Attempt 4 (TICKET-044) is one approach family scored on seed 67; after a green attempt the
  confirmation takes the next unused seed of the series; a foot-measure fix (TICKET-040) is its own family on the next
  unused seed after that. Seeds 59 and 61 stay reserved for the score (ADR-0007). The ruling, verbatim:
  "moalborati/simon#59 accepted under option (b), amended. A second held-out series is fixed as seeds 67, 71, 73 (59 and 61
  stay reserved for score retries, ADR-0007) in a new ADR committed before any detection change. Item 3 (near-miss
  diagnostics, analysis 1.8.0) lands first and changes no detection (seed 37 check-5 stdout and detection hashes
  unchanged). Items 1, 2 and 4 form one approach family tuned on seed 5 only, frozen, then scored once on seed 67 with
  every result published and seed 37's red kept. Item 5 is an answer only. The RDL take is reported by reference, never
  tuned on. Part 7 is messaged before detection changes. TICKET-040 no longer waits on an operator ruling: a
  foot-measure fix is its own family on the next unused seed of this series. Ends green and confirmed or DEGRADED with
  the new numbers by end of 2026-11-02."
- Amendment (pre-freeze review B3 and recheck residual 4; stakeholder-proxy ruling, confidence medium): `make check-5`
  judges a seed that is already scored by its own `detection_sha256` line in its attempt record alone, never by the
  one under "Score", and **a scored seed of the second series (67, 71, 73) must have that line**: a missing one is
  refused (exit 2) before any take is analysed (`check.require_frozen`, `check.SECOND_SERIES`). **Known limit, as ruled:** "a
  deliberate revert of rules.json to a retired attempt's bytes under later code is not caught by the per-attempt
  detection line; check-5's reproduce-the-recorded-numbers check after analysis is the guard; no part5 code-diff
  requirement (stakeholder-proxy ruling)". The line hashes the detection rules, not the code. What catches a retired seed
  scored again is `require_unchanged_scores`, which refuses (exit 2) a scored seed whose numbers differ from its recorded
  attempt; only numbers that reproduce the record to the last digit pass, which is the limit. Both halves are pinned in
  `tests/test_check_freeze.py` (`test_r4_*`).

## Sweeps (`part5/calibrate.py`, offline, deterministic)
- Since attempt 4 (ADR-0017, `rep-persistence.md`) every take of the set goes through `pipeline.run` at each candidate
  value (`PipelineRuns`, in parallel, the take's foot side files included), so an example of two or more reps is compared
  rep by rep and the foot labels are in the slices, as `make check-5` sees them; the sweep used cached whole-clip
  alignments before. The two foot thresholds are not swept (`--feet` owns them, TICKET-040; attempt 4 holds them). Since
  attempt 5 `--feet` is a re-sweep of the values in force and follows the rule below (a current value that ties at the
  best objective strictly inside its plateau is kept, the plain choice is printed beside it), and the rules it runs under
  carry the foot measures' `max_jitter_deg` steadiness limits (`docs/design/specs/foot-keypoints-attempt-5.md`), which it does not sweep.
- Thresholds: per measure, `threshold_deg` over a grid of 1 degree steps around the current value; then
  `min_frames_floor_body` (steps of 4 frames, six each side, extended once; a duration, written as frames at 30 fps, that
  a deviation must hold in a rep whatever its length, at most `floor_share` (three quarters) of the rep; the floor of the
  body measures, see "The floor splits" below), `min_fraction`, `min_run_frames`, `min_overlap`. Objective on the seed 5
  good-light slices, per angle:
  first precision 0.85 or more with 0 faults on correct takes at every angle, then the highest minimum
  recall across angles. The values tied at the best objective form a plateau; the frozen value is the
  middle of its longest contiguous run, rounded up to the grid step (equal runs: the one with the larger
  values); a plateau that reaches the grid edge extends the grid once; a fully flat key keeps its current
  value. `docs/thresholds.md` records both plateau ends and the grid per key.
  **How the rules combine** (recheck residuals 1 to 3; `sweep.sweep_param` and `sweep.choose` are the code, tested in
  `tests/test_calibrate.py`): (1) the grid is evaluated, and **if the tied plateau reaches an end of the grid that is not
  a bound of the key itself** (its `low` or `high`) **the grid is extended once, before anything is chosen**, whichever way
  the choice would go (a current value that would be kept included), so the plateau ends, and "strictly inside" with
  them, are not cut short by a grid that stopped too early; a flat grid is not extended, since nothing on it moves the
  objective. (2) **A flat key** (every value ties) **keeps its current value, wherever it sits on the grid, a grid bound
  included.** This rule is tried first and wins over the next: the plateau of a flat key is the whole grid, whose ends
  are the limits of the search and not drops of the objective, so "strictly inside the plateau" means nothing for it and
  never moves it to the middle. (3) On a re-sweep, a current value that ties and is strictly inside the longest run is
  kept (below). (4) Anything else goes to the middle of the longest run, rounded up. **The plain rule** printed beside
  every key (the `plain rule` column of `docs/thresholds.md`) is rules (1), (2) and (4) on the same rows, without (3):
  the flat rule, else the middle of the longest tied run, after the same one extension. It is what a first calibration
  would choose, so a key where it differs from the chosen value is a key the re-sweep rule kept. (Residual 1: the first
  record of this column was computed on the unextended grid and, for a flat key, as a middle; both were wrong.)
  **Re-sweeps (attempt 4, decided on
  seed 5 before any attempt 4 seed, a change of selection rule alone and never a retry; stakeholder-proxy, 2026-11-01,
  confidence medium):** on a re-sweep a key whose current value ties at the best objective **and lies strictly inside the
  longest contiguous run of the plateau (not at either end of it)** keeps it; any other key, a value that is worse, a tied
  value at either end of the run, or one on a shorter tied run, moves to the middle of the longest run (rounded up to the
  grid step). A re-sweep thus changes only what new rules made wrong, instead of recentring every key on a plateau seed 5
  cannot narrow, and never leaves a value on the edge of its plateau. The sweep prints, beside each chosen value, what the
  plain rule would choose, and `docs/thresholds.md` records it, so the effect of the rule is on the record.
  (The first form of this rule kept any current value that still had the best objective, edge included; it was replaced
  before the freeze.)
- **The floor splits by measure class (recheck N2; stakeholder-proxy ruling, confidence medium, verbatim):** "the floor
  splits by measure class before the freeze; foot measures keep 32 frames at 30 fps (a duration, at most 0.75 of a rep);
  body measures get their own floor of the same form, re-swept on seed 5 within the values that keep the 27 retimed seed 5
  takes at attempt 3's 24 of 24 in every row (the 00:05Z selection rule inside that range, 8 if nothing higher qualifies),
  pinned by a test, one delta recheck; if seed 5's gate-shaped criteria fail in that range or the delta is not merged and
  approved by 2026-11-01T20:00Z, freeze as it stands under (a) with the fast-rep limit recorded and pinned by a test."
  `default.min_frames_floor` (32) is the foot measures' floor and is held, not swept; `default.min_frames_floor_body` is
  the body measures' floor, swept from its starting value 8 (attempt 3's) over `min_frames_floor_body` 4 to 120 in steps
  of 4, **restricted to the qualifying range**: the values at which every one of the six rows of the retimed takes
  (`tests/retimed.py`: the 27 good-light seed 5 exercise takes 00 to 08 at 15, 10 and 5 fps, as a 2 s and a 1.5 s squat at
  30 fps, and as a 1.5 s squat at 15 fps; 24 planted faults per row) finds all 24. `scripts/retimed_floor.py KEY` prints
  the range of a key; `sweep.RETIMED_TOPS` holds the top of it for the keys the sweep would otherwise carry past it (the
  body floor, `upper_arm_out` and `min_fraction`), so a swept key never reaches a value that loses a retimed fault.
  `tests/test_retimed.py` pins the rows at the shipped rules and that the value above each top loses a fault. The seed 5
  gate-shaped criteria at good light (precision 0.85 or more and 0 faults on correct takes at every angle, recall 0.75
  or more, every correct take an A) must hold in the range; they do (`docs/thresholds.md`). The retimed takes are
  derived from seed 5 and are not held-out data.
  (Amended 2026-10-29 before
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
Given `attempts[]`, each seed appears at most once, seeds follow the order 29, 31, 37, 67, 71, 73 (the first
series, then the second, ADR-0017) with none skipped across both series, each was generated by one commit,
and regenerating it at that commit reproduces it byte for byte. A retry's rationale names an approach family
different from every earlier attempt's. (Amended 2026-10-31, ADR-0017; it read 29, 31, 37.)
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
If the gate is still red after the last seed (73 since the 2026-10-31 amendment, ADR-0017; it was 37), or the
run's deadline passes first: publish the honest result, post STATUS (not DONE?)
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

## Amendments
- 2026-10-31 (TICKET-042, `docs/design/specs/profiles.md`, ADR-0016): profiles are never calibrated. Their values are set by hand,
  the per-profile precision and recall are reported on seed 5 only (`make report-profiles`), no profile is run on a
  held-out seed, and no held-out seed is spent on one. The frozen detection rules and score params are not read
  differently by any profile.
- 2026-10-31 (stakeholder-proxy ruling 2026-10-31T22:25Z, moalborati/simon#59, ADR-0017): a second held-out series, seeds
  67, 71 and 73, follows seed 37 (Held-out protocol, the amendment quoting the ruling; AC-T03; Degraded ending). The
  order across both series is 29, 31, 37, 67, 71, 73 with none skipped. Nothing else in the protocol changes.

## Deviations from PRD
None.
