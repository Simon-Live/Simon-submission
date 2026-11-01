# ADR-0010: Compare repetition by repetition when the whole clips disagree on the count (analysis 1.3.0)
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-30

## Context
Real exercise clips hold several repetitions, and the trainer's count is rarely the follower's. On real
dumbbell lateral raises the trainer (Pexels 5319084) has 3 reps of about 3.4 s, one follower (40297504) has 8 fast
reps of about 1.3 s and another (8836968) has 2 slow reps of about 7.7 s. The whole-clip alignment is a
slope-limited DTW (½x to 2x), so it cannot follow a clip with a different count, and the movement guard
(ADR-0004) refused both followers on `timing_corr` (0.53 and 0.50 against 0.8336) while the residual passed. The
trainer against its own first two reps was refused too, which pins the cause on the repetition count. Compared one
repetition at a time, with each follower rep resampled to the expected rep's length and the frozen guard limits,
the lateral raises pass 8 of 8 and 2 of 2 (residual 0.35 to 0.45, `timing_corr` 0.94 to 0.98); the squat, Part
2's dance, class and stretch are refused in every window.

## Options Considered
### Option 1: widen the DTW band
- Pros: no new stage.
- Cons: a wider band lets different movements through (the guard's separation depends on the band); 8 reps
  against 3 is not a speed difference but a count difference.
- Effort: Low
### Option 2: cut both clips into repetitions and compare one at a time, only where the whole-clip guard refuses
- Pros: a pair the whole-clip guard accepts is analysed exactly as before, so seed 5, the held-out seeds and every
  golden stay byte-identical; the frozen guard limits and detection rules are untouched.
- Cons: a second analysis on refusals; the cut points need rules.
- Effort: Medium
### Option 3: always cut into repetitions
- Pros: one path.
- Cons: the synthetic dance clips are periodic (54 of the 108 seed 5 followers and the expected dance have two
  cycles of the arm measure), so segmentation alone cannot tell a dance's two beats from two repetitions, and
  every dance result would change.
- Effort: Medium

## Decision
Option 2.
- **Segmentation** (`part5/reps.py`): the measure with the largest robust range (p95 minus p5) is smoothed (0.25 s)
  and its turning points found with a zigzag filter (a turn needs 35% of the range). Cuts are the dips or the
  peaks, whichever gives more cycles (a tie goes to the dips), at the first frame of the extreme, at least 0.6 s
  apart. A measure that moves less than 15 degrees has no reps. Fewer than two cycles is one segment, the whole
  clip. The follower prefers the expected clip's measure and cut type when it moves that measure at least half as
  much as its own best. The constants come from seed 5 and the documented real takes only; the held-out seeds 29,
  31, 37, 47 and 53 were not used. Cutting in the middle of a rest, or at the start of the stretch near the
  extreme, was tried on the real lateral raises and made the reps disagree on phase, so it is not used.
- **Reference**: the expected clip's first complete rep, or the whole clip when it has one; recorded in
  `diagnostics.expected_reference`.
- **Per rep**: each follower rep is resampled to the reference's frame count, aligned, guarded and detected with
  the frozen limits. A rep also needs a matched span of at least 60% of itself: against a short reference the
  open ends of the alignment would otherwise let any long take match one lucky stretch (Part 2's dance against a
  stock squat rep passed without it).
- **Verdict**: accepted when a strict majority of follower reps pass, and at least one; otherwise
  `different_movement` as before. Faults are aggregated over the accepted reps: kept when found in at least half
  of them (always for one rep), reported once with the first occurrence's place on the follower's file clock,
  the median magnitude and `reps`. The score is the mean of the per-rep scores (`score.aggregate`), with
  `per_rep`.
- **Contract**: analysis 1.3.0, additive: `faults[].reps`, `diagnostics.guard.reps`, `diagnostics.expected_reference`,
  `score.per_rep`. A document without them keeps `schema_version` 1.2.0, so existing goldens do not move. The
  replay (`simon.replay.v1`) of such a take plays the whole follower take against the expected rep tiled once
  per follower rep and gains an optional `reps` list.

## Consequences
- **Positive**: real multi-rep takes are compared and scored; the stock squat followers, refused as whole clips,
  are now analysed.
- **Negative**: a refused take reports no per-rep numbers (adding them would change the refused goldens). A
  periodic different movement can still pass: the squat against Part 2's dance is borderline per rep (residual
  0.49, limit 0.5677) and is held back by the span-share rule, not by the guard limits.
- **Neutral**: the guard limits and detection rules are frozen as before (ADR-0003).

## Assumptions
- A rep is one cycle of the clip's most-moving measure; a clip whose main movement is not periodic is one
  segment and is compared whole.

## Amendment (2026-10-31, ADR-0017, TICKET-044): rep by rep whenever the example has two or more reps
Option 3 ("always cut into repetitions") was rejected here because the synthetic dance has two cycles, so every dance result
would change. The 2026-10-31 ruling on moalborati/simon#59 chose it for an example of two or more reps (a real take with several
reps was judged as one long take and scored 100 with no fault), and attempt 4 measured the cost on seed 5 and fixed what it
exposed: each follower rep is compared with the example rep that matches it (the follower's rep `k` with the example's rep
`k` when the follower has no more reps than the example, else the first, as decided here), the foot measures are compared
rep by rep, and persistence is judged in the rep (`min_frames_floor` 32). A rep verdict that does not accept the take leaves
the whole-clip comparison. The rest of this ADR (segmentation, per-rep guard, majority verdict, the half rule for faults)
is as decided. `docs/design/specs/rep-persistence.md` has the rule and the seed 5 record.
