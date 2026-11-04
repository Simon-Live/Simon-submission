# ADR-0023: Score the body you have: a declared mask applied at scoring, after alignment
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted (TICKET-084, Part 5's share of hub TICKET-275; the operator's fan-out order on moalborati/simon#61)
Spec: `docs/design/specs/body-mask.md`.
Date: 2026-11-02
Amends: nothing. ADR-0011 (visibility) keeps hiding unseen joints before alignment; this decision adds a second, declared
mask that applies after it.

## Context
A follower who is seated, or who does not use a limb, gets faults and cues for the limb, and the 3D model (SAM 3D Body)
puts a mesh limb where the real one is absent or behind a chair. Hub TICKET-275 asks Part 5 to apply "the same NaN mask
that visibility.py hide_unseen already uses, on every frame of both trainer and follower, so masked chains are never scored
or cued", and to show that masking chain X leaves every other chain's score contributions and faults unchanged (AC-2).

Visibility's mask (ADR-0011) is applied to the joint positions before alignment (`pipeline.run`: `hide_unseen`, then
`align`). Applying a declared mask at the same place would make the alignment depend on it, and the alignment decides which
follower frame every measure of every chain is compared with. The question is where the declared mask applies, and so
whether alignment ignores the masked joints.

## Options Considered

### Option 1: mask the positions before alignment, like `hide_unseen`
- Pros: one mechanism for both masks; timing never reads a limb the follower declared.
- Cons: every chain's faults then depend on the mask through the alignment, so AC-2 can only hold approximately and the
  analysis with no mask is no longer the reference the masked one is compared with. It also changes repetition
  segmentation (`reps.segment` reads the expected measures, and a squat's reps are found on the knees), the movement guard
  and `vis.align_usable`, whose view measures are switched on only for a partial body.
- Effort: Low to write, High to make AC-2 hold.

### Option 2: mask the measure series after alignment, at detection and scoring
- Pros: alignment, the guard and segmentation are byte for byte the unmasked ones, so AC-2 holds by construction for every
  measure family the chain does not touch, and an analysis with no mask is unchanged. The NaN is the same: a measure is
  dropped exactly when NaN at a masked joint would make it NaN through `measures.compute`.
- Cons: timing and the guard still read the masked limb, which can be a held limb or an invented one.
- Effort: Low.

### Option 3: Option 2, with alignment and the guard also leaving the masked measures out
- Pros: timing reads only the limbs that are scored.
- Cons: it is Option 1's cost again for the alignment (every chain's faults depend on the mask). Measured below, it is not
  needed on the fixtures.
- Effort: Medium.

## Decision
Option 2. `mask.hide_masked(mask, series)` sets every measure that reads a masked joint to NaN on every frame of both
clips: in `pipeline.run` before whole-take detection, in `repwise._one_rep` before each rep's detection (and the
`continue_reported` pass, which reuses those series), and in `score_report.aligned_of`, which feeds the similarity term, the
misses' trainer range and the credit. `align`, `check_movement`, `reps.segment` and visibility read the whole body as before.

Should alignment also ignore the masked joints? Reasoning from the code, no, for three reasons, with the evidence measured
on the seed 5 fixtures (the held-arm construction is in `tests/test_body_mask_property.py`, which pins the guard and the
faults for the first take below; the Option 3 column was measured once with `align(..., usable)` and is not pinned):

1. **It would break AC-2.** The other chains' faults are read along `alignment.exp_to_fol`; any change of path moves them.
2. **One limb cannot pull the timing far.** `align._cost` caps each timing measure at `COST_CLIP_Z` (1 z unit) and takes the
   RMS over all of them (9 to 11 on these fixtures), and the second pass removes each measure's median offset, so a limb held
   at a fixed angle is mostly an offset. A held limb adds about the same cost to every follower frame matched with one
   expected frame, which barely changes the best path.
3. **Measured.** Four correct seed 5 takes with the follower's left elbow and wrist held at their first-frame offset from
   the shoulder, aligned on the whole body (what ships) and with the left arm's measures left out of timing (Option 3):

| Take | Residual, whole body | Residual, arm left out | Span, whole body | Span, arm left out |
|---|---|---|---|---|
| `dance_front_good_00_correct` | 0.4265 | 0.2089 | 3 to 121 | 3 to 120 |
| `dance_front_good_01_correct` | 0.4151 | 0.1707 | 13 to 115 | 12 to 115 |
| `exercise_front_good_00_correct` | 0.3984 | 0.2682 | 0 to 84 | 0 to 84 |
| `exercise_45_good_00_correct` | 0.3789 | 0.2228 | 0 to 76 | 0 to 76 |

   The matched span moves by at most one frame. With `--mask left_arm` each of the four held takes reports no fault and
   scores 100 (A); without it they report the held arm (one to four `upper_arm_out` and `upper_arm_forward` faults) and score
   33 to 87.

The guard is the cost of this choice: the residual of a held-arm take rises from 0.14 to 0.31 (the original takes) to 0.38
to 0.43, closer to `guard.max_residual` (0.5677); timing correlation stayed at 0.97 or more against a limit of 0.8336. None of
the four became a low match, but a take that moves less, or a limb with more timing measures, could. That is recorded as the
trigger to revisit (below), not changed now: a mask-aware guard needs its own residual, which means aligning a second time.

## Consequences
- **Positive**: the property the hub asked for holds by construction and is tested on four fixtures for every chain; no
  mask means no change; detection's rules and the score's params are untouched.
- **Negative**: a held or invented limb still costs guard margin (above). A fault on both sides that the mask splits is
  sized on the remaining side (spec, Dissent 3). A masked score compares only with scores under the same mask.
- **Neutral**: `diagnostics.alignment_measures` can name a masked measure, because timing read it; it is debugging output,
  not a fault, cue or insight.

## Assumptions
- None new. The declared mask is taken as honest input.

## Reversal Cost
Low. Without a mask nothing changed; removing the feature removes `hide_masked`'s three call sites, the `mask` argument, the
CLI flag, the API field and `body_mask` (an additive field a reader ignores).

## Pre-Mortem (MANDATORY)
It's 6 months from now and this decision was a disaster. Why?
1. Part 7's staging pair (hub AC-3) is a low match only because the held arm costs guard margin. Likelihood: L, Impact: M,
   Mitigation: the trigger below; the four held-arm takes measured here stayed under the limit.
2. An invented leg under a chair swings and drags the timing of a seated take. Likelihood: L, Impact: M, Mitigation: a seated
   trainer's legs barely move, so they are not timing measures (`align.timing_measures` keeps measures that move 5 degrees
   or more in the example); visibility still hides legs Part 2 marks unseen.
3. A rules change lets a leg measure explain an arm fault, so masking the leg changes the arm. Likelihood: L, Impact: M,
   Mitigation: a test fails when a chain's measures explain a measure outside the chain.

## Trigger to revisit
An AC-3 staging pair (or any real masked take) whose unmasked analysis is a low match only because of the masked limb. Then
Option 3 for the guard alone (the guard's residual from a second alignment that leaves the masked measures out), with AC-2
restated for it.

## Dissent (MANDATORY)
Reviewed by: the lane (implementer), against the hub ticket's Risk paragraph
Concerns:
- "Part 3 or 4 may invent lower-body motion before the mask": the mask applies at scoring, so invented motion is never
  scored; it can only reach the timing, measured above.
- "Visibility already does this": visibility hides what the camera did not see, before alignment; a declared limb may be
  fully in view, and hiding it before alignment would change every chain.
- "Why not a shin chain": a shin mask would drop `foot_out` and `knee_valgus`, which explain a thigh fault in
  `part5/rules.json`, so the thigh's chain would change (spec, Dissent 4).

## Code Backlinks (updated as code is written)
- `part5/mask.py` (the section of `part5/visibility.py` until the 1.14.0 round moved it): the chains, the presets,
  `hide_masked`, `BodyMask.block`, `validate_mask_block`.
- `part5/pipeline.py` `run`: the mask at whole-take detection; `part5/repwise.py` `_one_rep`: at each rep's detection.
- `part5/score_report.py` `aligned_of`: the score's series.
- `part5/output.py` `build_analysis`, `validate_analysis`: `body_mask`.
- `part5/cli.py` `--mask`; `part5/api.py` the `mask` field; `part5/doctor.py` the `--for part7` note.
