# ADR-0004: Knee caving measure and the different-movement guard
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28

## Context
Two gaps found in the audit:
- Part 3's follower kit labels `knee_caving`; Part 5 has no knee valgus measure, so 0 of 3 kit takes
  are found and a common squat fault is invisible.
- The chain Part 2 pose3d, Part 3 `run --view part5`, Part 5 analyse runs to exit 0 on any movement.
  Cat-cow yoga against the squat reports 9 faults. DTW always finds a closest phase.
Operator decision 2 adds both to scope.

## Options Considered: knee caving
### Option K1: frontal plane projection angle (thigh and shank projected on the x-y plane)
- Pros: the clinical standard.
- Cons: at the bottom of a squat the thigh points forward, its frontal projection is short and noisy.
- Effort: Low
### Option K2: thigh inward rotation about the vertical axis (as Part 3's kit measures it)
- Pros: matches the kit's own size.
- Cons: rotation about vertical also changes with stance width; needs the bottom frame.
- Effort: Medium
### Option K3: knee offset inside the hip to ankle line
- Pros: defined in every frame; size independent; 0 for a straight leg.
- Cons: a new definition to explain.
- Effort: Low

## Options Considered: movement guard
### Option G1: span share only (warn under 0.6)
- Cons: cat-cow still matches a large span. Effort: Low
### Option G2: a movement classifier
- Cons: needs training data the part does not have; the README says rule maths. Effort: High
### Option G3: refuse nothing, warn
- Cons: Part 7 still shows a fault list for the wrong movement. Effort: Low
### Option G4: limits on the alignment residual and the timing correlation, calibrated
- Pros: uses statistics the pipeline already computes; calibrated on known populations.
- Cons: limits come from synthetic mismatch pairs plus one real case. Effort: Low

## Decision
K3 and G4.
- `knee_valgus` (left and right): for hip h, knee k, ankle a and `inward = -OUT[side]`,
  `d = ((k - h) - proj_{(a - h)}(k - h)) . inward`, `knee_valgus = degrees(atan2(d, |k - h|))`.
  Positive is knee caving. Label type `knee_caving` maps to it; Part 3's kit type `knee_caving` maps to
  it in the real-take adapter. The generator adds `knee_caving` as a sixth single-fault type, 15 to 25
  degrees, both sets.
- `part5.guard.check_movement` refuses when `residual > guard.max_residual` or
  `timing_corr < guard.min_timing_corr`. Limits live in `part5/rules.json` under `"guard"`, calibrated
  on seed 5: every tuning take against its own clip passes; every mismatch pair is refused (exercise
  takes against the dance clip, dance takes against the exercise clip, Part 2's `class` (cat-cow
  yoga), `dance` and `single` (a seated stretch) takes through Part 3 against the squat; `single` counts only once Part 2 publishes its seated-stretch output; while the committed `single/pose3d.json` is the provisional squat clip (sha256 `433ae2ed`), it is a matched squat pair, reported and never in the mismatch population (stakeholder-proxy, 2026-10-29)). Each limit sits at the midpoint of the gap. `span_share` stays a warning.
- A refused take writes `analysis.json` with `status.code: "different_movement"`, a plain-words
  `status.text`, `faults: []`, the statistics in `diagnostics.guard`; the CLI exits 3. Never a fault list.
- Part 7 must read `status` before `faults` (`CONTRACT.md`); a v1.0 reader that ignores `status` sees
  an empty list on a refusal.

## Consequences
- **Positive**: kit knee caving becomes measurable; a different movement is refused in plain words.
- **Negative**: the take grid grows to 9 takes per cell; every threshold is retuned once on seed 5.
- **Neutral**: `format` stays `simon.analysis.v1`; additions are optional fields (schema 1.1.0).

## Assumptions
- ASM-003: `knee_valgus` captures the kit's `knee_caving`.
- ASM-004: guard limits from synthetic mismatch pairs generalise to real different movements.
- ASM-005: Part 7 reads `status` before `faults`.

## Reversal Cost
Low: the guard is one call in the pipeline and two numbers in `rules.json`; the measure is additive.

## Pre-Mortem (MANDATORY)
1. The guard refuses a slow, sloppy real follower. Likelihood: M, Impact: M, Mitigation: limits keep
   every matched tuning take passing, low light and double faults included; held-out refusals counted.
2. Knee caving on the step touch is too small to detect, the held-out gate goes red. Likelihood: M,
   Impact: M, Mitigation: seed 5 includes dance knee caving, so tuning sees it first; never retune on
   held-out.
3. Part 7 ignores `status`. Likelihood: M, Impact: M, Mitigation: `doctor --for part7` and
   `CONTRACT.md` name the duty.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect)
Concerns:
- Populations may overlap: the limit then keeps every matched take passing and the overlap goes in
  `docs/thresholds.md`.
- K3 differs from the kit's own measure: the kit's sizes are reported, not compared number to number.
- Exit 3 is new: it is additive; exit 0 and 1 keep their meaning.

## Code Backlinks (updated as code is written)
- `part5/measures.py`, `part5/guard.py`, `part5/rules.json` (`guard`, `knee_valgus`),
  `part5/output.py` (`status`), `part5/cli.py` (exit 3)
