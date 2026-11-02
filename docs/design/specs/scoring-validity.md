# Spec: scoring validity, the dose-response bench, the skeleton-level invariance table and the score properties (`make bench-score`)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Implemented
Date: 2026-11-02
Request Type: new-feature
Risk Level: routine
Master spec: `part5-fault-analysis.md`. Score: `score-v3.md` (ADR-0019). Ticket: TICKET-082 (Part 5's share of the hub's
rubric ticket 272). Failures this work cannot fix without the frozen files go to TICKET-083.

## Overview
Part 5 reports a score out of 100 and a list of faults. This spec says how its validity is measured without a GPU and
without another part's code: planted joint-angle errors of 0 to 30 degrees run through Part 5's own pipeline
(`part5.pipeline.run` with `part5.score_report.score_block`), the invariances that need no Part 2 rerun (frame rate,
mirror, trim, translation, yaw, scale), and property tests on the score. The results are published in
`docs/evaluation.md`, failures included. Nothing here changes a rule, a threshold or a score parameter.

Measured:
1. **Dose-response.** How `score.value`, `score.grade` and the matching fault move as one joint's angle error grows
   from 0 to 30 degrees, and the planted angle at which the matching fault first fires.
2. **Invariance.** How far `score.value` moves, and whether the set of faults changes, when a take is transformed in a
   way that should not change the verdict.
3. **Properties.** Claims about the score that must hold for any input, checked by `hypothesis` with a fixed seed.

Out of scope: the video-level invariances (re-encode, 720p against 1080p, a 10% crop). They change what Part 2 sees, so
they need Part 2 GPU reruns. They belong to whoever runs Parts 2 to 5 together (Part 7), using `make bench-score` and its
`metrics.json` as the scorer. Also out of scope: real takes, the foot measures and the feet side files (the bench runs
the body measures only), the other profiles, and any held-out set.

## Why This Is Wrong (Dissent-First)
1. A rotation planted in a synthetic take is not a person's error. The takes come from one generator (ASM-002), so a
   clean dose-response shows the score is coherent on that model, not that it is right for a real follower. The doc says
   so next to every table.
2. A score that falls monotonically can still be wrong: it can fall for the wrong fault, or fire a second fault at
   large angles. The rows therefore record the matching fault and every other fault, not only the value.
3. Some invariances are not claims the code makes. The measures are defined in the subject's frame (x subject left, z
   anterior; ASM-001), so a yaw of the whole skeleton is outside the contract and may move the score by design. The
   table still reports it, as found, with the contract stated beside it; it is neither hidden nor loosened.

## User Story
As the engineer who wires Parts 2 to 5 together, I want to see how the score reacts to a known error and to changes that
should not matter, so that I can tell a real regression from noise and know which claims about the score are measured.

## Definitions
- **Planted error of d degrees** on a joint: the joint's distal segment is rotated about the joint by d degrees in every
  frame of the take (the whole take, with no ramp), reusing the geometry of `scripts/make_dummy_followers.py`.

  | Joint | Rotated | Reused | Matching fault (side `left` or `both`; `center` for the trunk) |
  |---|---|---|---|
  | knee | the left ankle about the left knee, about the thigh-by-shin axis of the deepest frame, so the knee bends d degrees more | `rotate`, `unit`, `cross`, `sub`, `angle_at` | `knee_flexion` |
  | hip | the left knee and ankle about the left hip, away from the midline | `swing_out` through `fault_foot_out` | `foot_out` or `thigh_out` |
  | elbow | the left wrist about the left elbow, forward | `fault_elbow_bent` | `elbow_flexion` |
  | trunk | the head, shoulders and arms about the hip midpoint, forward | `fault_trunk_lean` | `trunk_lean_forward` |

- **Realised degrees**: the median over frames of the absolute change in the joint's own measure (`knee_flexion`,
  `thigh_out`, `elbow_flexion`, `trunk_lean_forward`) between the take and the planted take.
- **Matching fault**: a reported fault with one of the joint's measures, direction `more`, and the joint's side.
- **First fire** of a take: the smallest planted angle on the grid at which the matching fault is reported, or `null`.
  The joint's first fire is the lower median of its takes' first fires (an angle on the grid), with their minimum and
  maximum; a take that never fires counts as above the grid. `stable` is true when a take's matching fault is reported at every larger step.
- **Fault set** of an analysis: the set of `(measure, side, direction)` of `faults[]`.
- **Score spread** of a transform: over the takes, the signed range and the largest absolute value of
  `score.value(transformed) - score.value(untransformed)`.
- **Fault-set equality**: the fault set of the transformed take equals that of the untransformed take (after the
  side swap and the sign swap of the lateral measures, for the mirror).

## Design
- **Takes.** Seed 5 only, read through `fixtures/input/followers/labels.json`; the helper `tests/retimed.py`
  (`picked_takes`) refuses any other seed. Good light, `variant` `clean`, take numbers 00 to 08. The dose-response uses
  the correct takes of the exercise set (numbers 00 and 01, front, 45 and side: 6 takes). The invariance table uses all
  nine takes of each cell (correct and faulted) of the exercise and dance sets: 54 takes. No held-out file is read.
- **Pipeline.** `part5.pipeline.run(expected, follower, rules=None, score=score_block)` with the shipped rules and no
  feet file. A transformed or planted follower is passed in memory (`{"path": ..., "doc": ...}`); only the frame-rate
  rows go through `tests/retimed.py` `retime`, which writes a temporary file.
- **Dose-response grid.** 0, 2.5, 5, ..., 30 degrees (13 steps), 4 joints, 6 takes: 312 rows.
- **Transforms** (all on the follower, unless the row says both):

  | Row | Transform | Claim |
  |---|---|---|
  | `fps_60` | linear resample to 60 frames per second (`retime`) | exact: the pipeline resamples the follower to the example's clock |
  | `fps_24` | linear resample to 24 frames per second (a non-integer ratio) | extra row, reported, no claim of exactness |
  | `mirror_follower` | x negated, left and right joints swapped | same score and the fault set with sides swapped, for a left-right symmetric example (an example that scores 100 against its own mirror); the rows are grouped by that |
  | `mirror_both` | the same on the example and the follower | exact: same score, fault set with sides swapped |
  | `trim_0.5s` | the first 0.5 s (15 frames) removed, times rebased to 0 | same verdict when the take's idle lead-in is at least 15 frames; rows are grouped by that, and the group with a shorter lead-in (the first moves of the squat are cut too) makes no claim |
  | `trim_lead_in` | only the take's own idle lead-in removed (takes with none are skipped) | exact; an extra row, the cleaner form of the trim |
  | `translate_5mm` | +0.005 m on every axis of every joint | exact: within the 1 cm the loader recentres (`io.HIP_TOLERANCE_M`) |
  | `translate_0.5m` | +0.5 m on x | refused with `InputError` (the hip midpoint must be at the origin) |
  | `yaw_5`, `yaw_15`, `yaw_45` | rotation about the vertical axis through the hip midpoint | exact (the hub's claim); the frame is the subject's (ASM-001), so a miss is a finding about the contract, see Dissent 3 |
  | `yaw_45_both` | the same on the example and the follower | exact (the hub's claim), same note |
  | `scale_0.8`, `scale_1.25` | every position multiplied | exact: the measures are angles |

  "Exact" means a spread of 0 and equal fault sets. The table reports the numbers whatever the claim; a row that misses
  its claim is a found failure.
- **Properties** (`tests/test_score_properties.py`; `hypothesis` with `derandomize=True`, `deadline=None` and a small
  `max_examples`; the file runs in under 60 s):

  | Id | Statement |
  |---|---|
  | P1 `score_is_in_0_to_100` | for any take, planted error up to 60 degrees and added joint noise, `score.value` is an integer in 0..100 and `score.grade` is the band of the value |
  | P2 `equal_to_trainer_scores_100` | an example compared with itself scores 100, grade A, and reports no fault |
  | P3 `translation_invariance` | a translation within 1 cm leaves the score and the faults unchanged; a larger one is an `InputError` saying the hip midpoint must be at the origin |
  | P4 `yaw_invariance` | a yaw of the follower about the vertical leaves the score and the faults unchanged |
  | P5 `scale_invariance` | a uniform scale of the follower leaves the score and the faults unchanged |
  | P6 `mirror_swaps_sides_only` | mirroring both clips gives the same score and the same faults with left and right swapped (the two lateral measures change direction) |
  | P7 `nan_joints_are_a_typed_error` | a NaN or infinite coordinate anywhere, in either clip, is an `InputError` that names the frame and the first bad joint, never another exception |
  | P8 `empty_frames_are_hidden_not_invented` | frames with every joint null are measured as missing: with at most 40% of a correct take's frames empty the analysis is valid, scores 100 and reports no fault; with at least 60% empty it carries `no_usable_measures`, scores at most 59 and reports no fault (the documented limit is half, `MIN_AVAILABLE` in `part5/pipeline.py`; the margins keep the test off the boundary) |

## Acceptance Criteria
### AC-SV01: planting is exact enough to read
Given a seed 5 correct take and a planted error of d degrees on any of the four joints, every row records the realised
degrees beside d, and 0 degrees plants nothing (the follower is unchanged). The test pins the committed take within 1
degree of d at 2.5, 15 and 30 degrees; `docs/evaluation.md` reports the largest gap over all 312 rows, which is
the harness's precision and not a property of the score (the chart's axis is the planted degrees).
### AC-SV02: the dose-response rows
Given the grid above, `make bench-score` records one row per joint, take and step with: planted and realised degrees,
`score.value`, `score.grade`, the number of faults, whether the matching fault is reported (with its measure, side,
direction and magnitude), and the other faults reported. A take that is not seed 5, or a labelled take whose file is
missing, ends the run with exit 2 and a named message.
### AC-SV03: first fire
Given the rows, the bench computes each take's first fire and each joint's median, minimum and maximum, and `stable`.
### AC-SV04: the metrics file
`make bench-score` writes `out/bench-score/metrics.json` (`format` `simon.part5.bench-score.v1`) with `sha` (the commit
of the tree), `dirty`, `command`, `exit_code`, the grid, every dose-response row, the first fires, every invariance row,
the invariance summary and the findings. Two runs of one tree write the same bytes. Exit 0 when every row ran, 1 when a
row could not run (it is recorded with its error), 2 for a usage error or an input that is not seed 5.
### AC-SV05: the chart
The bench writes `out/bench-score/dose-response.svg` and `docs/evaluation/dose-response.svg` (the committed copy): score
against planted degrees, one line per joint (the mean of the takes), the first fire marked on each line and labelled in
degrees, the grade bands as reference lines, direct labels instead of a legend, markers and dashes as well as colour,
a title that states the finding, axis labels with units and a `<title>` and `<desc>`.
### AC-SV06: the score does not rise as the error grows
Given the committed take `exercise_front_good_00_correct`, `score.value` is non-increasing in the planted degrees for each
of the four joints (`tests/test_score_monotone.py`, no GPU). A joint that is not monotone is not loosened: the test is
`xfail(strict=True)` with the reason `TICKET-083: <what>` and the numbers are in `docs/evaluation.md`.
### AC-SV07: the invariance table
Given the 54 takes, the bench records, for every row of the transform table, each take's untransformed and transformed
score, grade and fault set, and the summary per transform and group: takes, largest absolute change, mean and signed
range, takes whose value changed, takes whose fault set changed, takes refused with their error, and a verdict in words
(`exact`, `score moved`, `fault set changed`, `refused`).
### AC-SV08: the properties
`tests/test_score_properties.py` holds P1 to P8, each a named test, derandomized, under 60 s together. A failing
property is fixed with a regression fixture when the fix touches none of `part5/rules.json`, `part5/detect.py`,
`part5/profiles.json` or the score params; otherwise it is `xfail(strict=True)` with `TICKET-083: <what>`.
### AC-SV09: the published evaluation
`docs/evaluation.md` holds the dose-response table (first fire per joint; score at 0, 10, 20 and 30 degrees), the
invariance table, the property list with its results and every failure with its numbers, and says which claims are
not measured here (the video-level ones). It carries no figure that is not in `metrics.json` or a test output.
`make bench-score` writes the figures of the tables of sections 1 and 2 beside the chart copy, as
`docs/evaluation/first_fire.summary.json` (`dose_response.first_fire`: its summary and each take's first fire, with the
score at 0, 10, 20 and 30 degrees: mean, range and grades) and `docs/evaluation/invariance.summary.json`
(`invariance.summary`), both committed, with the score's version and params hash and no commit sha, so a later run
rewrites them byte for byte unless a figure moved. Test: `tests/test_evaluation_doc.py` renders those tables from the
summaries as the doc writes a figure and compares them cell by cell, both ways, and fails when the summaries are not of
the shipped score or the committed take's first fires differ from the pipeline's (review B3 of 1.13.0). The prose of
sections 1 and 2 is held the same way (TICKET-088 N2): each summary also carries `figures`, the numbers the prose states
beyond the tables (section 1: the rows with and without the matching fault, the drop at the first fire, the cost of a later
step, the second fault, the realised gaps; section 2: per row group the correct takes that moved or gained a fault, each
set's takes that moved, and the one take that moved or changed its fault set where there is one), and the test renders
each sentence that states a measured figure from the summaries and finds it in the doc. The rule thresholds section 1 quotes
are read from `part5/rules.json` and the 5 frames section 2 says the smoothing spans from `part5/normalise.py`'s `smooth`;
the rest of the numbers in those sections define the bench (the grid, the transforms), not its results. The section 3 table holds the property list, whose figures are the parameters of
`tests/test_score_properties.py`.
### AC-SV10: frozen surfaces
`part5/rules.json`, `part5/detect.py`, `part5/profiles.json` and the score params are unchanged, and `make check-5`
prints the same bytes on stdout as at the parent commit.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| `labels.json` is not seed 5 | exit 2, nothing written | `bench-score: seed <n> is not the tuning set (5)` | AC-SV02 |
| A take file of the pool is missing | exit 2 | `bench-score: missing take <path>` | AC-SV02 |
| One row raises an `InputError` or `AnalysisError` | row recorded with `error`, run continues, exit 1 | `bench-score: row <id>: <error>` | AC-SV04 |
| The translated take is outside 1 cm | recorded as `refused` with the `InputError` text, not an error | (none) | AC-SV07 |
| Unknown option | exit 2 | argparse usage | AC-SV04 |

## Edge Cases
- A knee planted on a frame where the leg is straight: the rotation axis is fixed from the deepest frame, so it is
  defined in every frame (AC-SV01).
- A trim that removes part of the movement (a take whose lead-in is shorter than 0.5 s): the row records the lead-in so
  the reader can separate it (AC-SV07).
- A planted error that fires a second fault (the hip at 30 degrees also reports `knee_valgus`): recorded as an extra
  fault, never dropped (AC-SV02).

## Non-Functional Requirements
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | `make bench-score` | under 5 minutes on the shared host | AC-SV04 |
| Performance | `tests/test_score_properties.py` | under 60 s | AC-SV08 |
| Reliability | determinism | same tree, same `metrics.json` bytes; `derandomize=True` | AC-SV04, AC-SV08 |
| Security | no key, no network, no GPU, no other part's code | n/a | AC-SV10 |

## Negative Requirements
- MUST NOT change `part5/rules.json`, `part5/detect.py`, `part5/profiles.json` or a score param. Why: the score is
  frozen under the held-out protocol (ADR-0019).
- MUST NOT loosen an assertion, a tolerance or a grid to make a row pass. Why: the work reports failures as found.
- MUST NOT read `fixtures/input/heldout/` or any seed other than 5. Why: held-out sets are single use (ADR-0003).
- MUST NOT write to `fixtures/output/` or edit `CONTRACT.md` or `contracts/`.

## Non-Requirements
- The video-level invariances and any Part 2 rerun: Part 7's job with this bench as the scorer.
- A new score, a new rule, or a repair of a found failure that needs a frozen file: TICKET-083.
- Real takes and the foot measures.

## Assumptions
- ASM-001: the input is in the subject's frame with the hip midpoint at the origin, so a translation or a yaw of the
  whole skeleton is outside the contract.
- ASM-002: synthetic takes from one generator are a proxy for real ones; the dose-response is read within that limit.

## Delivery Verification Plan
- Files covered: `scripts/make_score_validity.py`, `scripts/make_bench_score.py`, `scripts/make_bench_score_chart.py` (named
  `make_*` because the publish allowlist carries `scripts/make_*.py` and the published tests import them),
  `tests/test_score_validity.py`, `tests/test_score_monotone.py`, `tests/test_score_properties.py`, the `bench-score` target of `Makefile`,
  `docs/evaluation.md`, `docs/evaluation/dose-response.svg`, `docs/evaluation/first_fire.summary.json`,
  `docs/evaluation/invariance.summary.json`, `tests/test_evaluation_doc.py` (AC-SV09, review B3 of 1.13.0), the `make bench-score` row of `README.md` (review R11).
- Run once at the end: `uv run make test`; `uv run make check-5` with stdout compared byte for byte against a run of
  the parent commit in a `git archive` export; `uv run make bench-score`; `uv run pytest -q tests/test_score_properties.py`
  with its wall time; `python scripts/make_design_copies.py --check`. Each exit code is reported.
- No UI, no device and no account is involved.

## Dissent Review
Reviewed by: the lane author, to be audited by the consolidated review.
### Concern 1: a tolerance chosen after the numbers
Challenge: any "within N points" would be fitted to what the run showed.
Mitigation: the claims above are exact (spread 0, equal fault sets) and fixed before the run. A row that misses is
reported with its numbers. Resolution: ADDRESSED_IN_SPEC.
### Concern 2: the bench passes because it plants what the detector looks for
Challenge: the geometry is the generator's, which the thresholds were tuned on (seed 5).
Mitigation: the takes are correct takes (nothing tuned on a planted fault), the sizes sweep through the thresholds, and the
extra faults are recorded. The limit is stated in the doc. Resolution: ACCEPTED_RISK.
### Concern 3: a yaw failure is a contract fact, not a bug
Challenge: reporting it as a failure may mislead Part 7.
Mitigation: the table prints the contract next to the row; if the property fails it is `xfail` with the ticket and the
reason, which keeps the fact visible and fails loudly the day it stops holding (`strict`). Resolution: ADDRESSED_IN_SPEC.

## Deviations from PRD
None.
