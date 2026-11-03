# Spec: the own-reference range check and its seed 5 fit (draft)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.

Status on main (2026-11-02 wrap-up): this spec and ADR-0024 are kept on main as the record of a stopped family; the `--reference-kind` label (`reference-kind.md`, analysis 1.15.0), `scripts/fit_range_tau.py` and their tests stay on `lane/own-ref`, not merged.
Status: Draft, stopped on seed 5 by ADR-0024's stop clause (see "Seed 5 record"); nothing here is frozen or wired
Date: 2026-11-02
Request Type: new-feature (an additive fault family, opt-in)
Risk Level: high (a detection change, behind the held-out protocol)
Tickets: TICKET-093 (the finding), `lane/own-ref`, third commit. ADR: ADR-0024 (draft). Label: `reference-kind.md`. Measure fix it relies on: `measure-branch-cuts.md`.
Master spec: `part5-fault-analysis.md`. Protocol: ADR-0003, ADR-0017. Assumptions: ASM-002.

## Overview
When the reference is the follower's own correct rep (`--reference-kind own`), compare how far the follower moves each measure with
how far the reference moved it. A follower who moves much less or much more than their own rep did gets a `range` fault, "left knee
moved through a smaller range than in your own rep". The hub's VERDICT found this to be the one signal that separates incorrect from
correct reps in that condition (AUC 0.826 against Simon's 0.668 on 38 reps, a gain whose interval includes zero) and found nothing
against another person's rep. This spec writes the check down, the targets it must meet on seed 5 and the pairing the held-out gate
uses, before any number is looked at, and builds the one tool that touches seed 5: the fit. The check is not wired into the pipeline
by this spec; the wiring is the freeze commit's, after the 1.14.0 publish is recorded and a pre-freeze review.

## Why This Is Wrong (Dissent-First)
1. **A gain that may be zero.** Answer: ADR-0024's claim limit. Nothing here says the check improves anything.
2. **A synthetic series that cannot show a benefit.** The one range fault the generator plants, `knees_shallow`, is already found by
   position detection. Answer: the gate asks for safety (no false range fault, recall and precision not lower), and says so.
3. **A statistic that is noise for a limb in the frontal plane.** The sagittal angle of an arm held out to the side is set by jitter, so
   two correct reps can differ in span. Answer: T1 covers the committed takes; the real-data check reports the correct reps flagged;
   a guard on the length of the sagittal projection is a new parameter and so a new family.
4. **Two takes from one generator are closer than a person's two reps.** Answer: stated as a limit (ADR-0024 Pre-Mortem 4).

## The check (what the freeze will wire; the fit tool computes exactly this)
Inputs: the reference clip R and the follower take F, both after `normalise` and `hide_unseen`; the whole-clip alignment `align(R, F)`;
the body measures of both (`measures_of`); the profile's effective rules.
For each body measure `m` (the 22 of `measures.MEASURES`, left and right named separately) except `head_forward`:
1. `pairs(m)` = the values (R_m[i], F_m[exp_to_fol[i]]) over every reference frame `i` where both are finite. If there are fewer than 20,
   the measure is not judged.
2. `span_R` = P95 minus P5 of the reference values of `pairs(m)`, `span_F` = the same of the follower values (`numpy.percentile`,
   linear interpolation).
3. `t` = the effective `threshold_deg` of `m` (`rules["measures"][generic name]`, after the profile). The measure is judged only if
   `span_R >= c * t`. `c` is 1 unless the fit says otherwise.
4. `r = ln((span_F + t) / (span_R + t))`.
5. It fires when `|r| >= tau`: `less` for `r < 0`, `more` for `r > 0`. The same direction on both sides is one fault, side `both`.
6. A fired range fault is dropped when a position fault has the same generic measure, side and direction.
`upper_arm_forward` and the other three windowed measures are the ones `measures.compute` returns, already free of the 360 degree jump.
The statistic of a take is `max |r|` over its judged measures; the statistic of a measure is `r` itself.

Examples (the AC-OR-01 values): `span_R` 40, `span_F` 20, `t` 10 gives `ln(30/50) = -0.511`, direction `less`; equal spans give 0; `span_R` 40,
`span_F` 60 gives `ln(70/50) = +0.336`, `more`; `span_R` 6 with `t` 10 is not judged (the reference does not move it by one threshold).

## The fault in `faults[]` (decided at the freeze, written here so the review can read it)
`measure` (side-less generic name), `side`, `direction`, `magnitude_deg` = `span_F - span_R` rounded to 0.1, `peak_deg` the same,
`threshold_deg` = `t`, `check` = `"range"` (new, optional: absent means a position fault), `confidence` as for any fault, no frames and so no
`follower_runs` or timeline miss. Under score v3 it counts as a reported fault, so the ceiling of 89 for one and 79 for two or more
applies; no term is added. Plain words: "Your <side> <part> moved through a smaller range than in your own rep" (`less`) or "a larger
range" (`more`), written through the phrasing registry with the same word tests as every line.

## The own-reference pairing (the gate slice and the fit)
`pairing(labels)` is read off `labels.json`; no data is generated. A cell is (set, angle, lighting).
- the reference of a cell: its `<cell>_00_correct` take;
- the gated correct follower of a cell: its `<cell>_01_correct` take;
- every other take of the cell, the fault takes and the dropout copies, is a follower of that reference.
A take is never both a reference and a gated follower. A dropout copy of the reference is a follower, not a reference. The clean
`_00_correct` skeleton is passed as `--expected`, in the skeleton format the pipeline already reads.

## The fit (item 4 of the plan; the only code that reads seed 5 for this family)
`scripts/fit_range_tau.py --set fixtures/input/followers [--out out/range-fit]`:
1. Refuses (exit 2) any set whose `labels.json` names a seed other than 5; the message names 79, 83 and 89 as not to be touched.
2. For `c` in `(1, 2, 0.5)` in that order, computes `r` for every judged measure of every pair of the pairing (seed 5 has 12 cells, so
   12 references and 144 followers).
3. Per `c`: `a` = the largest `|r|` over every judged measure of the 12 correct followers; `b` = the smallest, over the 6 good-light
   `knees_shallow` takes, of the better side's `-r` on `knee_flexion` (each take counts once, by whichever of its two knees reads
   the more negative `r`); clean when `b - a >= 0.05`; `tau = round((a + b) / 2, 2)`.
4. Takes the first `c` that is clean. If none is clean it stops: the report says `stop`, names the numbers and writes no tau.
5. Reports T1 to T4 at the chosen tau (below), the table of every correct follower's statistic and every shallow take's, and the
   crossings on fault takes of other types, by type, with how many survive the dedupe.
6. Writes `out/range-fit/report.json` (gitignored) and prints it; deterministic, so a rerun is byte-identical.
The tool does not edit `rules.json`, does not wire anything and reads no other seed.

## Targets (the same as ADR-0024, repeated so the tests can point at them)
- **T1** none of the 12 correct own-reference followers crosses tau on any judged measure.
- **T2** each of the 6 good-light `knees_shallow` takes has `r <= -tau` on `knee_flexion`, one side at least. The low-light ones are reported.
- **T3** the fit is clean (`b - a >= 0.05`), tau at the middle of the gap.
- **T4** reported: crossings on other fault types, and those that survive the dedupe.
- **Stop clause** no clean fit for any `c`: stop and report. Nothing is loosened.

## The gate (what the freeze wires, on each scored seed, over the own slice; ADR-0024)
G1 no range fault on any of the 6 good-light correct followers. G2 `knees_shallow` recall with the check not below the recall without it, per
angle. G3 precision with the check not below the precision without it, per angle. G4 every teacher-reference slice and hash unchanged.
ADR-0017's gate is unchanged. A green result is "safety on a synthetic series".

## Acceptance Criteria
### AC-OR-01: the statistic
Given constructed spans (40 and 20 with `t` 10; equal; 40 and 60), Then `r` is -0.511, 0 and +0.336 and the directions are `less`, none and `more`.
### AC-OR-02: what is judged
Given a measure whose reference span is below `c * t`, one with fewer than 20 finite pairs, `head_forward`, and a measure with a NaN
follower, Then the first two and `head_forward` are not judged, and NaN pairs are left out of the spans.
### AC-OR-03: percentiles, not extremes
Given a follower series with one frame 90 degrees off, Then the span moves by no more than the 95th and 5th percentile allow (a 5% outlier
does not set it).
### AC-OR-04: the pairing
Given a `labels.json` of two sets, three angles and two lightings with 13 takes a cell, Then each cell has one reference (`_00_correct`)
and one gated correct follower (`_01_correct`), no take is both, every other take is a follower of its cell's reference, and a
dropout copy is a follower.
### AC-OR-05: the selection
Given tables of statistics, Then a gap of 0.05 or more picks tau at its middle rounded to 0.01, a smaller gap or none at `c` 1 tries 2
and then 0.5 in that order, and no clean `c` stops with no tau.
### AC-OR-06: the seed refusal
Given a set whose labels name seed 29, 73, 79, 83 or 89, Then the tool exits 2 and reads no take.
### AC-OR-07: determinism
Given the same set twice, Then the two reports are byte for byte equal.
### AC-OR-08: the check is not wired by this lane
Given any analysis made by this tree, whatever its `reference_kind`, Then no `faults[]` entry has `check` `range` and `rules.json` has no
`range` block (the label spec's AC-RK-02 holds: `own` changes nothing).

## Seed 5 record (the fit was run after ADR-0024 and this spec were committed, f2386c3)
`uv run python scripts/fit_range_tau.py` on `fixtures/input/followers` (seed 5): 12 cells, 144 pairs, 12 correct followers and 6
good-light `knees_shallow` takes. **Exit 3: the stop clause fired.** No cut gave a clean fit, so no tau was chosen and nothing was
wired, frozen or generated. A second run wrote the same bytes (`report.json` sha256
`825a11ac59754447e279e7c90358ea5adc4be8f52a0cd5d32ee989e9b6ce297d`); a first run, before the script printed this table, gave the same
`a`, `b` and exit code.

| cut | a (largest correct-follower \|r\|) | b (smallest good-light shallow take) | gap b - a | clean |
| --- | --- | --- | --- | --- |
| 1 | 0.4819 (exercise_side_low_01_correct, right_upper_arm_out) | 0.0409 (dance_side_good_04_knees_shallow-both) | -0.4410 | no |
| 2 | 0.4819 | 0.0409 | -0.4410 | no |
| 0.5 | 0.4819 | 0.0409 | -0.4410 | no |

The cut changes nothing here: the extremes are set by measures the reference moves by two thresholds or more. The table at cut 1:

| correct follower (the `_01_correct` take of each cell) | measures judged | largest \|r\| | measure |
| --- | --- | --- | --- |
| exercise_side_low_01_correct | 21 | 0.4819 | right_upper_arm_out |
| exercise_45_low_01_correct | 20 | 0.3137 | right_forearm_out |
| dance_side_low_01_correct | 20 | 0.3007 | right_foot_out |
| dance_side_good_01_correct | 18 | 0.2579 | right_forearm_out |
| dance_front_low_01_correct | 18 | 0.2487 | left_elbow_flexion |
| exercise_front_low_01_correct | 11 | 0.2352 | shoulder_tilt |
| dance_45_low_01_correct | 21 | 0.2294 | right_thigh_out |
| exercise_side_good_01_correct | 12 | 0.2049 | right_upper_arm_out |
| exercise_45_good_01_correct | 10 | 0.1735 | right_upper_arm_forward |
| dance_45_good_01_correct | 17 | 0.1406 | right_foot_out |
| exercise_front_good_01_correct | 8 | 0.1187 | left_elbow_flexion |
| dance_front_good_01_correct | 17 | 0.1154 | right_thigh_forward |

| knees_shallow take | left knee -r | right knee -r | better knee |
| --- | --- | --- | --- |
| dance_45_good_04_knees_shallow-both | 0.1038 | 0.1947 | 0.1947 |
| dance_45_low_04_knees_shallow-both | 0.1112 | 0.1119 | 0.1119 |
| dance_front_good_04_knees_shallow-both | 0.1623 | 0.0785 | 0.1623 |
| dance_front_low_04_knees_shallow-both | 0.4269 | 0.1506 | 0.4269 |
| dance_side_good_04_knees_shallow-both | 0.0252 | 0.0409 | 0.0409 |
| dance_side_low_04_knees_shallow-both | -0.1237 | 0.1721 | 0.1721 |
| exercise_45_good_04_knees_shallow-both | 0.5312 | 0.5012 | 0.5312 |
| exercise_45_low_04_knees_shallow-both | 0.5319 | 0.3159 | 0.5319 |
| exercise_front_good_04_knees_shallow-both | 0.4608 | 0.4456 | 0.4608 |
| exercise_front_low_04_knees_shallow-both | 0.6499 | 0.5247 | 0.6499 |
| exercise_side_good_04_knees_shallow-both | 0.5010 | 0.5308 | 0.5308 |
| exercise_side_low_04_knees_shallow-both | 0.5193 | 0.6692 | 0.6692 |

Both targets fail, and they fail from both sides. T1: at the smallest tau that keeps all 12 correct followers clear (0.4819) the
good-light shallow takes read 0.46 to 0.53 in the exercise set and 0.04 to 0.19 in the dance set, so only two of the six are seen
(exercise_45 at 0.5312 and exercise_side at 0.5308 are; exercise_front at 0.4608 is not). T2: at a tau that sees all six (0.04) every
correct follower crosses. T3 has no gap at any cut.

What the numbers say, stated and not acted on (the targets and the rule were fixed first, and nothing here changes them):
- The correct followers that read highest are the low-light ones (0.23 to 0.48). In good light they read 0.12 to 0.26, set by arm,
  forearm, foot and thigh measures: two correct reps of the generator differ in those spans by more than the planted dance knee
  fault changes the knee span.
- The planted fault is smaller in the dance set (11 to 17 degrees) than in the exercise set (35 to 39), and the dance takes read
  0.04 to 0.19 where the exercise takes read 0.46 to 0.53.
- Seen after the outcome, the exercise set at good light alone would show a gap (largest correct 0.2049, smallest shallow 0.4608,
  0.256). That is a different target set, chosen after the numbers, so it is not a fit this ADR allows; it is written here so that a
  new decision, if the proxy wants one, starts from the data and a new pre-registered plan, not from this fit.

Consequence under ADR-0024: the family stops. Seeds 79, 83 and 89 are not spent and stay unused; no pre-freeze review, freeze,
generation or merge follows from this family. The label (`docs/specs/reference-kind.md`) and the branch-cut fix
(`docs/design/specs/measure-branch-cuts.md`) do not depend on the check and stand on their own.

## Error Cases
| Condition | Behavior | AC Reference |
|-----------|----------|-------------|
| a set that names a seed other than 5 | exit 2, nothing read | AC-OR-06 |
| a reference or follower that will not load | exit 2 naming the file | AC-OR-06 |
| a cell without its `_00_correct` or `_01_correct` | exit 2 naming the cell | AC-OR-04 |

## Edge Cases
- A measure the reference holds still (span below `c * t`): not judged, never a fault.
- A follower that never leaves the start pose: every judged measure reads `less`; the check says so, and so does position detection.
- Both sides fire in the same direction: one fault, side `both`.
- A take analysed with a warning (a low match): whether the check is evaluated on it is decided at the freeze; the fit sees no such
  take in seed 5.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|----------|------------|--------|-------------|
| Performance | The fit finishes in the check's own budget | under 10 minutes for 144 pairs | AC-OR-07 |
| Reliability | Deterministic | byte-identical report | AC-OR-07 |
| Compatibility | No output of the default changes | `make check-5` stdout unchanged by the tool | AC-OR-08 |

## Negative Requirements
- MUST NOT generate, read, score or name-check as data any of seeds 79, 83, 89 before the freeze. Why: ADR-0024, ADR-0017.
- MUST NOT carry a REHAB24 number into tau or the cut. Why: the VERDICT: both are fitted on seed 5 only.
- MUST NOT edit `part5/rules.json` in this commit. Why: the detection hash and the freeze records stay valid.
- MUST NOT claim a benefit. Why: ADR-0024's claim limit.

## Non-Requirements
- Wiring the check into `pipeline.run`: the freeze commit.
- A guard for limbs in the frontal plane: a new parameter, so a new family.
- A UI control for the reference kind: nothing reads the label yet.

## Assumptions
ASM-002 (the generator is a fair proxy; its `_00_correct` take stands in for a student's own correct rep, with the limit that it shares the
generator's movement).

## Delivery Verification Plan
- `uv run pytest tests/test_range_fit.py` exit 0.
- `uv run python scripts/fit_range_tau.py --set fixtures/input/followers` exit 0 (a clean fit) or 3 (the stop clause), report recorded here.
- `python3 scripts/make_design_copies.py --check` exit 0.
- Not run in this lane: `make test`, the published-tree test, `make check-5` after item 4 (nothing in `part5/` changed).

### Device/Platform Strategy
Not applicable: a script and a document.

### Data
Seed 5 only (`fixtures/input/followers`). No held-out seed, no REHAB24 clip.

### Ratchet Initialization Plan
Not applicable.

## Dissent Review
### Concern 1: the margin 0.05 and the order of the cuts are choices
Kept: they are written before any number is seen, and the held-out series is the test of the fitted pair.
### Concern 2: 12 correct followers are few
Kept and stated: the gate is 0 of 6; no rate is claimed.

## Files (every new or changed source file; the write gate reads this table)
| File | Part | Published |
| --- | --- | --- |
| `scripts/fit_range_tau.py` (new) | fit | no (firm) |
| `tests/test_range_fit.py` (new) | fit | yes |
| `docs/design/specs/own-reference-range.md`, `docs/design/adr/ADR-0024-own-reference-range-family.md` | plan | yes |

## Deviations from PRD
None.
