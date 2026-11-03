# ADR-0025: The guard cross-person family, a movement guard that does not cap a correct take by another body, tested first on a constructed population (draft, targets fixed before any constructed number)
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: draft, a research lane; STOPPED at step 4 by clause S1 (see "Outcome of the step 4 measurement"). Nothing is frozen, wired or merged, and no
seed has been generated. Seeds 79, 83 and 89 are unspent.
Date: 2026-11-02

## Context
TICKET-101 reports that `low_match` caps real followers who are correct. The movement guard (`part5/guard.py`) caps a take when
`residual` is above `guard.max_residual` (0.5677) or `timing_corr` is below `guard.min_timing_corr` (0.8336). Both limits are the
midpoints of the gap on seed 5 between matched pairs (`docs/thresholds.md`, "Guard limits": matched residual at most 0.5231, mismatch
at least 0.6122; matched `timing_corr` at least 0.9110, mismatch at most 0.7562). A seed 5 matched pair is one synthetic body: the
expected clip performed again by a rescaled, retimed, noisy copy of itself. Nothing in the set that fixed the limits is a different
person.

What the real evidence says (numbers only; the data stay outside this repository):
- The hub's group dance run (RESULTS.md, sha256 `b5329de928bb0aae4a74e5bba45e93ebe6624c7f26c335df2040083fbc7eb4fb`): clip 3 (four
  followers) residual 0.5557 to 0.586 and `timing_corr` 0.6197 to 0.7566; clip 1 residual 0.65 to 0.69, `timing_corr` -0.08 to 0.31;
  every scored follower capped. Three of clip 3's four `timing_corr` values are at or below seed 5's mismatch maximum (0.7562) and the
  fourth is 0.0004 above it, so no re-fit of the two limits on seed 5 uncaps them with any margin while keeping every seed 5 mismatch
  capped. A fix has to change the signal.
- REHAB24-6 on the hub's pipeline skeletons (measured in step 1, `docs/research/guard-cross-person.md`): of 23 correct reps scored
  against another person's correct rep, 9 are capped; scored against the same person's own correct rep, 2 of 23. Median residual 0.513
  against 0.298; median `timing_corr` 0.939 against 0.974.
- The hub's pose error report (REPORT.md, sha256 `06a1ab354576360c0ca9e6a100dc82893a409a5c4a3c1c08c30c5b609d12e835`, with its table
  sum_rehab.md, sha256 `6c65e680a2b1d13cc7a924d32a6447155cf237e79a356b7ddffb3db413f38845`): the error that hurts Part 5 is a per-take
  constant offset in arm angles (elbow bias SD 12.7 and 14.7 degrees across clips, `upper_arm_forward` 8.9 and 15.3, `upper_arm_out`
  5.6 and 5.1).
- Part 7's reported numbers (TICKET-101): its negative, pexels-5034562, is capped on the null path (no residual, no `timing_corr`), so a
  null must stay a cap; two real correct takes are uncapped (residual 0.5083 and 0.422).

One fact shapes the plan. `part5.align.align` already removes a constant offset: it aligns once, takes the median follower minus
expected offset of each timing measure along that path, removes it and aligns again, and the residual it reports is the second pass.
So the hub's dominant error source may be largely invisible to the residual, and a population built from it may not reproduce the cap.
That is a result this plan is allowed to reach (stop clause S1), not a risk it hides.

The rulings behind this lane (STATUS.md, Decisions): 2026-11-02T13:46Z Q2 (a finding whose diagnosis names a structural cause seed 5
can prove is its own approach family: targets before tuning, seed 5 only, an independent review before any freeze, seeds 79, 83 and
89 checked unused) and the own-reference family's stop at 16:05Z, whose ADR-0024 this one copies in structure: the targets and the
stop clauses are written before any number of the new population exists.

What exists when this draft is written: the step 1 measurement (`scripts/guard_cross_person_cause.py`, `docs/research/guard-cross-person.md`),
which reads the current guard only, and `docs/design/specs/guard-cross-person.md`. The generator flag and its tests are written in the working
tree and are committed after this ADR; the tests ran on the expected clips and a few fixture takes (bytes, ranges, the measure each draw
moves) and computed no guard statistic. No constructed seed 5 set has been generated, and no guard statistic of one exists.

## Why This Is Wrong (Dissent-First)
1. **A constructed population proves only what it is built from.** If it is adjusted until the current guard caps it, a candidate
   that uncaps it has learned the construction. Answer: every range below comes from a report that predates the construction, none from
   a guard outcome; a construction that fails the reproduction test stops the family and is not adjusted.
2. **The aligner may already remove the cause.** See the Context. Answer: stop clause S1 covers it; the record then says the hub's
   offsets do not explain the cap, which is itself a finding for TICKET-101.
3. **Cross-body is not cross-person.** The hub's diagnosis finds style on limbs the exercise does not use and range of motion 1.8 to
   2.05 times the trainer's, which the construction does not model. Answer: the construction models what the pose error report
   quantifies (offsets, proportions, lag) and nothing else; a pass says "this guard survives that construction", never "real cross
   person takes pass". The real-data reads are reported after the fit and never tuned on.
4. **Loosening a guard lets weak mismatches through.** Seed 5's mismatch set is 111 pairs from two expected clips and three Part 2 clips.
   Answer: every one of them must stay capped with margin, a null stays a cap, and the gate's slices must not move; no claim reaches
   past that set.

Verdict: PROCEED to the pre-registration and the construction, nothing more. None of the four blocks writing the targets.

## Options Considered
**Option A: record the finding and leave the guard.** Pros: no detection change. Cons: real followers by another person stay capped at F.
Effort: Low. This is the outcome if a stop clause fires.
**Option B: re-fit the two limits.** Rejected before any run: three of clip 3's four `timing_corr` values (0.6197 to 0.7566) are at or
below the seed 5 mismatch maximum (0.7562), the fourth 0.0004 above it, and step 1 finds 6 of 23 real cross-person correct reps with a
residual inside the mismatch range. It stays in the evaluation as the control C0 so the record shows it.
**Option C: scope the limit by pair kind (same body against another person).** Part 5 cannot tell whose rep a clip is; the caller would
have to declare it, as `--reference-kind` on `lane/own-ref` does for the own reference. Not chosen here; it needs a ruling and a declared
input, and it is a different family (a rule by declaration, not a signal).
**Option D: new signals (chosen to test).** Cons: the signals can only be judged on a construction (see Dissent 1 and 3). Effort: Medium.

## Decision
### (a) The constructed cross-body population
One option on the synthetic generator, `scripts/make_dummy_followers.py --cross-body [--cross-body-offset-scale S]`, seed 5 only,
written under `out/guard-cross-person/<name>/` with the names `c1`, `c2`, `abl-offsets-x1`, `abl-offsets-x2`, `abl-lags` and `abl-scales`
(the gitignore keeps `out/` out of the tree; the flag refuses to write under `fixtures/`, and refuses any seed but 5, naming 79, 83 and 89). Every take of the set is made another body's. The draws come from a random stream keyed
by the take id (`seed/take_id/cross-body`), so no other draw moves and the committed seed 5 and seed 73 sets are the same bytes without
the flag (a test).

| draw (per take) | range | source |
| --- | --- | --- |
| arm length scale (elbow and wrist about the shoulder) | uniform 0.936 to 1.069 | the hub's bodies.json (sha256 `e0381122f9b9ad99b5801f21344cbf4acda32afb70925245f64b97de21e238bc`, nine people): arm length over stature, divided by its median; smallest and largest |
| leg length scale (knee and ankle about the hip) | uniform 0.906 to 1.025 | the same, leg length |
| shoulder width scale (shoulders about their midpoint along the shoulder line, the arms riding along) | uniform 0.913 to 1.070 | the same, shoulder width |
| `elbow_flexion` offset, left and right | normal, mean 0, SD 12.7 and 14.7 degrees, cut at 2 SD | REPORT.md, sum_rehab.md "between-clip SD of bias" |
| `upper_arm_forward` offset, left and right | SD 8.9 and 15.3 | the same |
| `upper_arm_out` offset, left and right | SD 5.6 and 5.1 | the same |
| lag of each of left arm, right arm, left leg, right leg against the trunk | uniform -0.2 to +0.2 s | the hub's diagnosis (diagnosis.md, sha256 `2904405949ac502761f859a6a64b7c2db6f868d44dbfc4c5ebcb84d619f7b5aa`, section 2: each frame slid 6 frames, 0.2 s) |

An offset is a constant rotation of the limb chain at every frame (the arm about the shoulder, the forearm about the elbow), so it moves
its own measure by the drawn amount and leaves the others alone. A lag reads the limb's joints, relative to their shoulder or hip, in the
source frame the limb's own clock shows, so bone lengths stay and one DTW path cannot absorb it. Bone scales change no angle measure.

Two populations, declared now: **C1** has offset scale 1 (a take's own offset, the report's SD as written). **C2** has offset scale
square root of 2 (the offset between two clips when each carries its own, the case of a real pair, since the synthetic reference
carries none). Each has 24 correct takes; the 84 fault takes of the set are written and not used. The constructed correct pairs are the
24 correct takes of a set, each against its own expected clip (the matched pair shape).

**Ablations (reported only, decide nothing).** `--cross-body-parts` applies a subset of the three kinds of draw (`scales`, `offsets`,
`lags`; the others are neutral and the remaining draws are the full population's). At step 4, whatever the reproduction test says, the
current guard is measured on the offsets-only population (offset scales 1 and square root of 2), the lags-only population and the
scales-only population, so the record names which draw caps which pair.

**Reproduction test (S1's condition).** A population reproduces the real pattern when, with the current guard unchanged (limits 0.5677
and 0.8336), both hold on its 24 pairs:
- R1: at least 9 of the 24 are capped (REHAB24-6, another person's rep: 9 of 23; the group dance clip 3: 4 of 4);
- R2: the median `residual` lies in 0.36 to 0.64 (the first to third quartile of the REHAB24-6 correct cross-person reps, 0.360 to 0.639,
  which holds clip 3's 0.556 to 0.586) and the median `timing_corr` in 0.62 to 0.97 (clip 3's lowest value to the REHAB third quartile,
  0.966).

### (b) The candidate signals
Both are computed from the alignment `part5.align.align` returns, on the same measures the guard uses (`alignment.measures`), and are
NaN where the pair has no alignment or no measurable value.
- **`residual_c`, the residual with each measure's constant offset removed.** In the alignment's z features (the measure over the expected
  clip's spread), take the follower minus expected difference at every cell of the final path, subtract its median over the path for each
  measure, cap each squared difference at 1 as the alignment's cost does, take the root of the mean over measures, and average over the
  path cells.
- **`timing_corr_lag`, the lag-tolerant timing correlation.** For each timing measure, the largest Pearson correlation between the expected
  series and the follower series read along the path and shifted by k frames, for k from -K to +K, K = round(0.2 s times the expected clip's
  frame rate) = 6; then the median over measures, as the guard does. The value at k = 0 is the guard's own, so it is never lower.

Candidates (each rule caps when a statistic is past its limit or is NaN):
| id | residual statistic | timing statistic |
| --- | --- | --- |
| C0 (control) | `residual` | `timing_corr` |
| C1 | `residual_c` | `timing_corr` |
| C2 | `residual` | `timing_corr_lag` |
| C3 | `residual_c` | `timing_corr_lag` |

**The fit (seed 5 only).** For a candidate, both limits (a for the residual statistic, b for the timing statistic) are free. Candidate
limits are the midpoints between adjacent distinct values of each statistic over the seed 5 matched, mismatch and constructed pairs. A pair
of limits is feasible when, with the margin m = 0.025 on each limit: every matched pair is uncapped with both limits tightened by m (residual
statistic at most a minus m, timing statistic at least b + m), and every mismatch pair is capped with both limits loosened by m (residual
statistic above a + m or timing statistic below b minus m; a NaN counts as capped, so a candidate with a NaN matched pair has no feasible pair). Among feasible pairs the fit
takes, in this order: the one that leaves the most constructed correct pairs uncapped (with the limits tightened by m) in the population
where it leaves fewest; then the most in total; then the larger smallest slack (a matched pair's slack is the smaller of a minus its
residual statistic and its timing statistic minus b, a mismatch pair's the larger of its residual statistic minus a and b minus its timing
statistic, the smallest taken over the matched and mismatch pairs); then the smaller a; then the smaller b. Nothing else is free: not K,
not m, not the cap of 1.

### (c) The targets, written before any constructed number exists
All on seed 5 (matched 108 pairs, mismatch 111 pairs, constructed 24 pairs per reproduced population).
- **T1 (mismatch stays capped):** every seed 5 mismatch pair is capped, with margin m.
- **T2 (matched stays uncapped):** every seed 5 matched pair is uncapped, with margin m. No take the gate scores is newly capped, so no
  slice of `make check-5` moves from a guard change (the proof at a freeze is `make check-5` stdout byte-identical, including the rep by rep
  path, which this lane does not run).
- **T3 (a null stays a cap):** the candidate rule caps a pair whose statistic is NaN or missing (a unit test), and a pair with no alignment
  is capped by the pipeline before the guard (`part5/pipeline.py`, `_unaligned`), so Part 7's negative, capped on the null path, is not
  something any signal change can uncap.
- **T4 (the share):** at least 80 percent of the constructed correct pairs, 20 of 24, are uncapped with margin m, in every constructed
  population that passed the reproduction test.
- **T5 (reported only, decides nothing):** the candidate signals on the REHAB24-6 pairs (both conditions), Part 7's reported pair numbers
  and the number of constructed pairs capped by each limit, read after the fit and never tuned on. The group dance clips are not in this
  repository and are not recomputed.

### (d) Stop clauses
- **S1 (the construction does not reproduce the real pattern):** neither C1 nor C2 passes the reproduction test (R1 and R2). The family
  stops: no candidate is fitted, no ranges are changed, the record says which of R1 and R2 failed and by how much. If one of the two
  passes, the fit uses that one only.
- **S2 (no candidate separates with margin):** no candidate has a feasible pair of limits that meets T1, T2 and T4. The family stops; the
  table is the record, and nothing is loosened to make a fit.
A construction constant, a range, K, m, the share or a target changed after a constructed number exists is a new plan with its own
targets, not an edit of this one.

### Later steps (named, none done here)
1. An independent review of this ADR, the scripts and the numbers before any freeze, by an opus reviewer (a sonnet reviewer while opus is
   limited, the model named in the record).
2. A spec on main for any `part5/` module a surviving candidate needs, before it is written.
3. Part 7 told on the bus before any merge (the guard's output changes `match`, `capped_by` and scores).
4. The freeze commit: the wiring in `part5/`, the limits from seed 5, the sha256 of `rules.json` and the detection rules, written to
   `docs/thresholds.md` with the rationale.
5. Seed 79 generated once and scored once by `make check-5`, then retired (ADR-0017's protocol and gate unchanged); seeds 83 and 89 as
   ADR-0024's table lays out.
6. 1.15.0 publishes only on a green attempt; a red one is recorded and posted.
No seed of the third series (79, 83, 89) is generated, read or scored by this lane.

### The claim limit
The most this lane can show is that a guard built on the candidate signals keeps every seed 5 separation and uncaps a population built from
the hub's pose error numbers. It cannot show that real cross-person takes pass. Every record says so.

### What does not change
`part5/guard.py`, `part5/rules.json`, ADR-0003's and ADR-0017's protocol and gate, every committed fixture, the score parameters.

## Outcome of the step 4 measurement (2026-11-02, run after the commits that fixed the targets and wrote the flag)
Each of the six populations was generated once (seed 5, `out/guard-cross-person/`) and the current guard, unchanged, was measured on its 24
correct takes (`scripts/eval_guard_candidates.py reproduce`). **Stop clause S1 fired.** R1 needs at least 9 of 24 capped; C1 has 1 and C2 has 1,
both by `timing_corr` and none by the residual. R2 is met by both (median residual 0.4276 and 0.4284, median `timing_corr` 0.9507 and 0.9498). The
four ablations cap 0, 0, 1 (lags only) and 0; the largest constructed residual is 0.5670 (C2), 0.0007 under the limit. The numbers and the
labels hashes are in `docs/research/guard-cross-person.md`, "Step 4".

Under the clause: no candidate was fitted, no construction constant, range, K, m, share or target was changed, nothing is frozen, no review
was started, and seeds 79, 83 and 89 stay unspent. The candidate signals' code (the two functions of (b) and the fit of (b) and (c)) was drafted
in the working tree while the heavy-command queue was waiting, unit-tested on synthetic rows and two committed seed 5 takes, and never run on a
constructed number; it was removed from the tree after S1 fired and is not in this branch. What the numbers say is a result for TICKET-101: the
hub's reported draws (per-take arm offsets, proportions, a 0.2 s limb lag) raise the residual by 0.09 and the aligner takes most of the
offsets out, so they do not make a correct take look like the real cross-person caps, which are lunge and squat reps. A second plan would have to
draw the causes this one omits (range of motion, posture on unused limbs) from the reports with its own ranges, targets and stop clauses before any
number, and needs a ruling; it is not started here.

## Consequences
- **Positive:** a pre-registered test of whether a signal change can address TICKET-101; either result is a recorded answer.
- **Negative:** a constructed population is a thin stand-in for people; the family may stop at S1 and learn only that the report's offsets
  do not explain the cap.
- **Neutral:** an opt-in generator flag, a cause script and an evaluation script; no `part5/` change.

## Assumptions
- ASM-002 (the generator is a fair proxy for unseen synthetic takes) holds for the constructed takes only as far as the construction
  follows the hub's reports.
- None of seeds 79, 83 or 89 has been generated, read or scored by this lane.

## Reversal Cost
Low: documents, scripts and an opt-in flag; no seed spent, nothing frozen.

## Pre-Mortem (MANDATORY)
It's 6 months from now and this decision was a disaster. Why?
1. The construction reproduces the cap by accident (the lags, not the offsets) and the candidate is read as a fix for the offsets.
   Likelihood: M, Impact: M, Mitigation: the record names which draw caps each pair (an ablation per draw is reported in the step 4 record).
2. `timing_corr_lag` raises mismatch pairs' correlation too (a maximum over 13 lags of noise), the seed 5 gap closes and the margin test
   fails. Likelihood: M, Impact: L, Mitigation: that is S2, and it is the result.
3. The fit uses the constructed pairs to place the limits, so T4 is partly circular. Likelihood: H, Impact: M, Mitigation: stated; the
   independent review and seed 79 are the test, and seed 79 holds no constructed population.
4. A real clip later differs from the construction (range of motion, style on unused limbs) and the guard still caps it. Likelihood: H,
   Impact: M, Mitigation: the claim limit; the real-data read is reported, never claimed ahead of the measurement.
5. A `part5/` change lands between a freeze and the generation of seed 79. Likelihood: L, Impact: M, Mitigation: the orchestrator holds
   `part5/` merges in that window, as in ADR-0017.

## Dissent (MANDATORY)
Reviewed by: the research lane (author); the independent review is a later step.
Concerns:
- The offsets may not matter to the guard at all (the aligner removes them): accepted, S1 records it.
- Two populations and three candidates are several chances to pass: accepted and stated; the targets and the margin do not change between
  them, and a pass is a result for the review, not for a freeze.
- The fit's tie-breaks are choices: accepted; they are written here, before any number.
- Why not scope by declared pair kind (Option C): different family; it needs a caller's declaration and a ruling.

## Code Backlinks (updated as code is written)
- `scripts/guard_cross_person_cause.py`, `docs/research/guard-cross-person.md`: step 1, the current guard only.
- `scripts/make_dummy_followers.py` (`CROSS_BODY_*`, `cross_body_plan`, `apply_cross_body_shape`, `lag_limbs`) and `tests/test_cross_body.py`:
  the constructed population, step 3.
- `scripts/guard_candidates.py`, `scripts/eval_guard_candidates.py`: the signals and the fit, step 4 and 5 (written after the reproduction
  result).
<!-- In code: # ADR-0025: reason -->
