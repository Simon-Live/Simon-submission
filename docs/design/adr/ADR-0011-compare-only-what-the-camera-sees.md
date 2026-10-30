# ADR-0011: Compare only what the camera sees (status `not_enough_visible`, `diagnostics.visibility`)
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-30

## Context
The operator's own seated selfie salute (staging job edfadd7f3848) was refused `different_movement`
(residual 0.7139 against 0.5677, `timing_corr` 0.0108 against 0.8336). Hips, knees and feet are out of frame in the
trainer entry and in the take. Part 2 writes `conf` 1.0 for a joint inside the image and exactly 0.3 for one the
model placed outside it (Part 2 `CONTRACT.md`, `joints.<name>.conf`). `part5.io` masks only joints below 0.3, so the
invented legs counted: the largest-range measures were the follower's right thigh (73 degrees) and foot (56). The
expected animation (Part 4) carries no `conf`, so its own visibility is unknown.

## Options Considered
### Option 1: mask the 0.3 joints on load
- Pros: one line.
- Cons: a measure with one hidden joint in 30% of the frames would still be computed; the expected clip has no
  `conf`, so its invented legs would still be compared; no clear refusal when almost nothing is seen.
### Option 2: decide usable measures per clip, compare on the intersection
- Pros: full-body pairs take the old path (byte-identical); the expected clip borrows the follower's set; a named
  refusal when too little is in frame.
- Cons: the head-and-shoulder part of a take carries few measures.
### Option 3: lower the guard limits for partial pairs
- Cons: tuned on one real take; rejected.

## Decision
Option 2 (`part5/visibility.py`).
- **Unseen joint.** A joint is unseen in a frame when its `conf` is the sentinel 0.3 and so is its left/right
  counterpart's. A conf below 0.3 is a missing joint, already NaN, and keeps its handling. The counterpart clause
  is deliberate: the far side of a side view is also marked 0.3 (Part 3's `squat_side_*` kit takes and the synthetic
  side takes), but its mirror is seen and those limbs have always been compared, so those sets stay byte-identical.
- **Usable measure.** In a clip, a measure is usable when every joint it reads is seen in at least
  `MIN_VISIBLE_SHARE = 0.8` of the frames (`part5.measures.MEASURE_JOINTS`; `upper_arm_forward` and `head_forward`
  read the hips through the trunk). The pair is compared on the measures usable in both clips. In the frames where a
  usable measure's joint is unseen it is NaN (`hide_unseen`).
- **Unknown visibility.** A clip with no `conf` (the Part 4 animation) takes the other clip's set. `part5 analyse
  --expected-visibility <skeleton.json|pose3d.json>` (and `run(..., expected_visibility=)`) intersects with the
  trainer's own Part 2 or Part 3 skeleton: Part 7 can pass `catalog/<entry>/skeleton.json`.
- **View measures.** A head-and-shoulders take has one full-body measure left (`shoulder_tilt`), too few to decide
  anything. Ten measures that read only face, shoulders and wrists (`part5.measures.VIEW_MEASURES`) join the
  alignment and the guard's statistics when a pair is partial. They are not detected, so no fault names them, and they
  are absent from a full-body pair.
- **Guard.** The limits stay frozen. The statistics now average over the usable measures.
- **Refusal.** Fewer than `MIN_USABLE_MEASURES = 3` usable measures (or none that can carry timing) gives status
  `not_enough_visible`, `faults: []`, `score: null`, exit 3, plain text asking for more of the body in frame.
- **Moving part.** A measure moves in the expected clip when its robust range (p95 minus p5) is above
  `MOVING_RANGE_DEG = 20`, counting only measures the example itself shows (its own conf and
  `--expected-visibility`, strict: every 0.3 joint is unseen, side views included). The constant is above the 15
  degrees `reps.py` needs for repetitions and above the 9 degree sway of the salute trainer's still head and
  shoulders; seed 5's expected clips and the real trainers move their main measures 40 degrees and more. When the
  pair is partial and none of the moving measures is usable in the pair, the take is refused
  `moving_part_out_of_frame`: `faults: []`, `score: null`, exit 3, text naming the body part from the joints of the
  moving measures ("Your right arm is mostly out of frame, so it can't be compared. Step back so your whole arm
  stays in view, then record again."). `diagnostics.visibility.moving_measures` and `moving_usable` are added.
  One usable moving measure is enough to compare, so a squat with its legs out of frame is still compared on its arms.
- **Output.** `diagnostics.visibility: {usable_measures, excluded, rule}` is added, and `schema_version` becomes
  `1.3.0`, only when the pair is partial; a full-body analysis is unchanged.
- **Repetition mode** (ADR-0010) uses the same usable measures.

## Consequences
- Seed 5, the held-out sets, the kit and every golden are unchanged (`make check-5`, `check-5-contract`).
- The real lateral-raise takes (knees and ankles at 0.3) change, as intended: their invented legs no longer count.
- Part 7 must read `status.code` `not_enough_visible` like `different_movement`: a refusal, exit 3.
- The operator's salute pair: the visible measures barely move (the hand is seen in 72% of the take, the elbow in
  21%), so the guard alone read it as `different_movement` (`timing_corr` 0.36, residual 0.4466 inside its limit). It
  now gets `moving_part_out_of_frame` naming the right arm. See `tests/test_visibility.py`.
