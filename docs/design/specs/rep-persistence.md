# Spec: attempt 4, persistence judged in each rep of the example, rep by rep for a multi-rep example, and a side lean that does not wrap
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-31
Linked PRD: none (moalborati/simon#59, items 1, 2 and 4)
Linked CRD: none
Request Type: feature-mod
Risk Level: high
Master spec: `part5-fault-analysis.md` ("Repetitions", "Detection changes (#30)"). ADRs: ADR-0017 (the second held-out
series and attempt 4), ADR-0003 (the protocol), ADR-0010 (rep by rep), ADR-0013 (score windows), ADR-0015 (foot measures),
ADR-0016 (profiles). Companion specs: `calibration.md`, `foot-keypoints.md`, `near-misses.md`. Ticket: TICKET-044.

## Overview
A real Romanian deadlift follow take scored 100 (A) with no fault (moalborati/simon#59). Three causes sit in detection, and
attempt 4 fixes them as one approach family, tuned on seed 5 only and scored once on seed 67 (ADR-0017):
1. **Persistence is judged in each rep of the example.** A fault needs `min_fraction` of the expected rep its frames fall
   in (floored by a duration, below: `min_frames_floor` for the foot measures, `min_frames_floor_body` for the others),
   not of the whole clip. An example of one rep is one rep, the whole clip, as before.
2. **An example of two or more reps is compared rep by rep**, whether or not the whole-clip guard accepts the pair
   (ADR-0010 ran rep by rep only when it refused). Each follower rep is compared with the example rep that matches it,
   and the foot measures are compared rep by rep too (they were hidden in rep mode).
3. **`trunk_lean_side` is the angle of the spine out of the sagittal plane**, `atan2(x, hypot(y, z))`, which stays in
   -90 to 90 degrees through any forward hinge, where the angle of the frontal projection wrapped to about 155 degrees.

Everything else is as it was: the thresholds (but for `knee_flexion` 9 to 10 and `upper_arm_out` 10 to 11, which the re-sweep
under the split floor moved, "The floor splits by measure class" and `docs/thresholds.md`), the guard limits, the score parameters, the foot measures' definitions,
visibility rule and thresholds (TICKET-040's family), the fault list's majority rule over reps (ADR-0010), the score
windows (ADR-0013) and the `analysis.json` contract (no field is added, so the schema stays 1.8.0). The floor of a rep is
new: `default.min_frames_floor` went from 8 to 32, because a rep is shorter than a clip (below), and since the recheck of the
pre-freeze review (N2, "The floor splits by measure class" below) it is the **foot measures'** floor only; every other
measure reads `default.min_frames_floor_body` (8). Both are durations: frames **at 30 fps** (32 is 1.07 s), turned into
frames at the example's own rate and capped at three quarters of the rep (pre-freeze review B1, Part 1). The 30 fps and the
three quarters are `default.reference_fps` and `default.floor_share` since the recheck (residual 5), not constants of the
module, so they are inside `detection_sha256` with the floors. `min_frames_floor` keeps its name because every reader of it
(the sweep, the profiles that copy it, `without_floor`) already treats it as the floor of a rep and only the unit under it
changed; the value is the same.

## Why This Is Wrong (Dissent-First)
1. **The expected dance has two cycles, so every dance take changes path.** Answer: that is the rule's point, and the
   seed 5 record below shows what it costs. Without a fix it is a regression: with the old floor of 8 frames and the
   first rep as the only reference, good light reads precision 0.62 to 0.80 at 45 and side with 2 faults on correct
   takes. The fixes that are in this family and not a narrowing: a floor that is frames of a rep (below), each follower
   rep against the example rep it repeats, and the foot measures kept in rep mode.
2. **Per-rep persistence also lets noise through.** A deviation that fills 38% of a 43 frame rep is 16 frames, half a
   second, which a far foot in a side view produces on a correct take (seed 37's red cause was a far-foot
   `ankle_inversion`). Answer: `min_frames_floor` is a duration, so a short rep needs at least that long whatever
   share it is; 32 frames at 30 fps (1.07 s) is the middle of the plateau seed 5 leaves (28 to 36). It is a time and not a
   count of the example's own frames, so a 15 or 5 fps example asks the same 1.07 s, and it never asks more than three
   quarters of the rep, so a rep or a clip under 1.07 s can still hold a fault (pre-freeze review B1: counted in frames at
   the example's rate, the floor of 32 made a 46 frame squat at 15 fps drop 6 of its 8 planted faults). This is not a
   second fix for seed 37: the foot measures' thresholds are not touched, and a red result for the foot's own noise is
   TICKET-040's.
3. **The floor makes a short first rep blind.** The dance example starts mid-cycle: its first rep is 43 frames, and a
   fault planted from 5 to 20% of the clip is present for only 20 to 37 of them, under a floor of 32. Scored on its own
   misses (ADR-0013), that rep's window would be clean and single-fault dance takes would score about 8 points higher (A
   20 of 60 in good light, was 3; the double-fault takes at C, was D). Answer: once the take reports a fault, a rep that
   shows it for `min_fraction` of itself counts it in its window (`continue_reported`: a higher bar to start a fault, a
   lower one to continue it). That restores the targets (below). What stays: a foot fault found in one rep of two (the
   foot measures are noisy near their threshold) leaves the other rep clean, so four dance takes score A (92 or 93)
   with their fault reported.
4. **A subset or other values are not a new family.** A red seed 67 cannot be retried with only the floor changed
   (ADR-0017).

## Vocabulary
- **Rep of the example**: a span of `reps.segment` on the expected clip. `Segmentation.partition(n)` tiles the clip into
  disjoint spans, one per rep; the lead-in before the first cut and the tail after the last belong to the nearest rep.
- **Matched rep**: the example rep a follower rep is compared with (`repwise.matched_rep`).
- **Reference**: the expected frames of the matched rep (`RepResult.expected`), starting at the expected file's frame
  `RepResult.ref_start`.

## Part 1: persistence in each rep (`part5/persistence.py`, called by `part5/detect.py`)
`detect_full(..., rep_spans=None, fps=None)`. `rep_spans` is the example's reps as disjoint inclusive spans tiling the clip,
or None; `fps` is the expected clip's frame rate (None reads the floor as frames, the reference rate of 30). For one
measure, side and direction (`persistence.judge`):
- Runs of frames past the threshold are found on the whole clip. A run counts from `min_run_frames` (its own length: a run
  is never cut at a rep boundary) and **belongs to the rep that holds most of its frames** (the earlier on a tie).
- Rep `j` of length `L` **persists** when the counted frames that belong to it are at least
  `needed(L) = min_frames` (explicit count of frames) or `max(floor_frames(L), round(min_fraction * L))`, and at least 1.
- **The floor is a duration** (`floor_frames`): the floor key is written as frames at 30 fps (`default.reference_fps`), so
  it names `floor / 30` seconds, `round(floor * fps / 30)` frames at the example's rate, and **never
  more than `round(0.75 * L)`** of a rep (`default.floor_share`). A foot measure (`measures.FOOT_MEASURES`) reads
  `min_frames_floor` (32), every other measure `min_frames_floor_body` (8; recheck N2). Chosen on seed 5: the dance example's first rep is 43 frames and
  `round(0.75 * 43)` is 32, so every seed 5 take reads exactly as it did (a share of 1.0 or none gives the same 156
  analyses byte for byte, a share of 0.7 or less moves 68 or more takes), and 0.75 is the smallest simple share that
  leaves seed 5 alone. The explicit `min_frames` stays a count of frames.
- The fault is made of the counted runs of the reps that persist (`Persistence.kept`); its `runs`, magnitude, peak,
  coverage and confidence are over those runs. A rep that does not persist contributes nothing: a short run in another
  rep neither helps nor harms. No frames are summed across reps.
- With no spans, or one, `L` is the clip: the rule is the one the whole clip always had, byte for byte (for a clip of 43
  frames or more at 30 fps, and in proportion at another rate).
- A near miss (TICKET-043) keeps its item shape. `counted_frames` and `needed_frames` are those of the rep that came
  closest to persisting (the highest counted over needed; the rep with the longest run when none counted anything), so
  `shortfall_frames` says how far that rep fell short, and its `expected_frames` is **the longest run in that same rep**
  (by its frames inside the rep; `Persistence.span`, `Persistence.longest`; pre-freeze review B4: it was the longest run
  anywhere, which could lie in another rep than the one the numbers describe). A candidate that persists is sized over the
  runs that persist, and its `expected_frames` is the longest of them, which is the fault's.
- Profiles (ADR-0016): the profile's looser config is judged in the same reps (`_fault` takes the spans); the floor is
  copied unchanged, so a profile needs at least what fitness needs and still reports nothing fitness does not.
- **Why per-rep and not "the frames where the trainer moves"** (the alternative named in moalborati/simon#59): on both
  synthetic examples the trainer's fastest timing measure moves in 87 to 100% of the frames at any speed limit from 0.1 to
  1 degree per frame (exercise 1.00 to 0.87, dance 1.00), so seed 5 cannot choose that denominator or show an effect,
  and the kit squat reads 0.59 to 0.75 depending on a speed limit seed 5 cannot set. A new constant that the tuning set
  cannot inform is not added (ADR-0003); the reps already exist (`reps.segment`).

## Part 2: rep by rep whenever the example has two or more reps (`part5/pipeline.py`, `part5/repwise.py`)
- **When.** `pipeline.run` segments the expected clip (`reps.segment`). With two or more reps, `repwise.compare` runs even
  when the whole-clip guard accepts the pair. With one rep it runs only when the whole-clip guard refuses, as before.
- **Verdict and fallback.** The rep verdict is ADR-0010's (a strict majority of follower reps pass the guard and cover 60%
  of themselves). When it does not accept the take, the whole-clip comparison stands with its own guard verdict: a take
  the whole-clip guard accepts is analysed as a whole with no warning, persistence judged in the example's reps (Part 1);
  one it refuses is a low match (ADR-0012). A take that cannot be aligned at all is unaligned, as before.
- **Which rep is the reference** (`matched_rep(k, expected_reps, follower_reps)`). A follower with no more reps than the
  example plays the example's sequence: follower rep `k` is compared with the example's rep `k`. A follower with more reps
  than the example repeats it, and which rep repeats which is unknown, so every rep is compared with the example's first,
  as ADR-0010 chose. A lone follower segment is compared whole with the first rep. For an example whose cycles differ,
  this is what keeps like with like: the dance example starts mid-cycle, its first rep (frames 0 to 42, 43 frames) is
  shorter than its second (42 to 102, 61 frames), and the follower's first rep starts mid-cycle too.
- **Each follower rep is resampled to its reference's frame count**, aligned, guarded and detected with the frozen limits,
  as ADR-0010 says. The bound is the sum of the squares of the reference lengths (a lone segment: its frames times the
  reference's); over `MAX_CELLS` the rep-by-rep comparison is dropped and the whole-clip comparison stands (AC-RP-16) when the whole pair fits
  (`test_r4_reps_over_the_limit_keep_the_whole_clip_comparison_when_it_fits`); when it does not, the analysis stops before any
  alignment with the same plain error as before, naming
  `ceil(pairs / widest reference)` follower frames against the widest reference.
- **Foot measures.** `pipeline._foot_series` is computed before the comparison. `compare` gets the expected series and the
  follower's series on the expected clock, cuts the expected one with the reference and resamples the follower's with each
  rep exactly as the joints (`_foot_rep`, a missing neighbour stays missing). `diagnostics.feet` lists the foot measures
  as compared in rep mode as in a whole comparison, and `REP_MODE_REASON` is gone. A foot measure is detected with its own
  threshold (TICKET-040's, not touched) and the persistence rule of Part 1.
- **Faults.** Aggregation over reps is ADR-0010's (found in at least half of the accepted reps), with one clarification
  for a fault on both sides (pre-freeze review B2, `repwise.aggregate_faults`), made exact by the recheck (N1): when some
  rep found a measure and direction on `both` sides, the take reports it once, and **the half rule is applied to each
  side on its own, over the reps that found that side, alone or as part of `both`**. It is reported on `both` when both
  sides reach half of the accepted reps (the reps that found either side, each counted once by its `both` fault or its
  one-sided fault of the largest magnitude, give its place and size, the first occurrence's side rewritten by
  `detect.as_both`), on the one side that does when only one does (sized from that side's own occurrences, with
  `faults[].reps` also holding the reps that found it as part of `both`: the size of a `both` fault is the two sides'
  mean, not that side's), and not at all when neither does. So a side found in under half the reps never rides in on
  the other's `both` (the real lateral raise pexels-40297504 against 5319084, 8 reps: the right elbow and hand in reps
  4 to 7, the left only in rep 7 as part of `both`, is now "right elbow bent slightly more than the example" and "right
  hand too close in", score 77 with `upper_arm_out` at 10 and 80 (B) at the shipped 11, which clears rep 3's left upper arm; it was reported as both elbows and both hands). Without a `both` occurrence each exact
  key is judged on its own, as before. A fault is placed on the
  expected file's own frames from its first occurrence, shifted by the start of the reference of the rep that found it
  (`RepResult.ref_start`), `phase` the fraction of the whole expected file. `diagnostics.expected_reference` still describes
  the first follower rep's reference (the example's first rep); a fault first found in a later rep can lie in another
  example rep. Near misses are shifted the same way.
- **Score.** ADR-0013: one window per follower rep, each scored on its own misses against its own reference, and (new) on
  the faults the take reports that the rep shows at `min_fraction` of itself without the floor
  (`repwise.continue_reported`, `RepResult.continued`). A fault starts to count where it persists in a rep with the
  floor, which keeps noise out of the list; once reported it is counted in every rep that shows it, so the short rep the
  floor blinds is not scored clean for a fault the follower made in it too. A rep is charged for a fault once: a fault whose
  measure and direction the rep already holds on an overlapping side (the same side, or `both` against either) is not
  continued, and a rep's fault is in its window as found when the take reports it on an overlapping side: a one-sided
  fault when the take reports `both` (pre-freeze review B2), and a `both` fault when the take reports either of its sides
  (recheck N1; `continue_reported` continues a floor-free `both` the same way). The take's fault list, `faults[].reps` (the
  reps that found it with the floor), the near misses (whose `found_in_reps` counts the reps that found a side, alone or as
  part of `both`) and the half rule are the strict ones, unchanged.
- **Replay.** `replay.reps[i].expected_frames` are frames of the tiled expected list, which now holds each rep's own
  reference one after the other (the lengths can differ); `expected_t` starts at the first reference's own time and strictly
  increases. With equal references it is the list it was.
- **Nothing is added to `analysis.json`**: `faults[].reps`, `score.basis` `reps` and `diagnostics.guard.reps` were 1.3.0's.
  What moves for a reader is that a multi-rep example now produces them (and `score.per_rep`) for a pair the whole-clip
  guard accepts, and that a dance take is compared in two reps of different length.

## Part 3: the side lean (`part5/measures.py`)
`trunk_lean_side = degrees(atan2(spine.x, hypot(spine.y, spine.z)))`, the asin of the spine's sideways component over its
length, positive toward the subject's left. It is continuous and in -90 to 90 degrees, reads 0 for a trunk hinged 0 to 180
degrees forward with no side lean, and reads a real side lean of `s` degrees as `s` at any hinge. `_lateral` (the frontal
projection) stays for `neck_lean_side`, a head-and-shoulder view measure that cannot hinge. On both expected clips and every
seed 5 take the new and old values differ by less than a degree where the trunk is upright, and no seed 5 take hinges past
90 degrees, so the proof is geometry on constructed poses (`tests/test_measures.py`).

## Calibration (seed 5 only, `docs/design/specs/calibration.md`)
- `part5.calibrate` runs every take of the set through `pipeline.run` at each candidate value (`PipelineRuns`, in parallel),
  foot side files included, so the sweep sees rep mode and the foot labels as the gate does. It still refuses any set
  whose seed is not 5 (exit 2, AC-T01). The default sweep leaves the two foot thresholds alone (`--feet` owns them).
- The floor joins the persistence keys (step 4 frames, six steps each side, extended once): `min_frames_floor_body` is
  swept since the N2 split (inside the retimed qualifying range, `sweep.RETIMED_TOPS`), `min_frames_floor` is the foot
  floor and held at 32. On a re-sweep a
  current value is kept (`choose`) only when it ties at the best objective and lies strictly inside the longest contiguous
  run of its plateau, not at either end of it; any other key goes to the middle of its plateau (stakeholder-proxy,
  2026-11-01; the first form of the rule, "a current value that still has the best objective is kept", was not ruled on
  and is replaced by it). A flat key keeps its value first of all (the 2026-10-29 rule), a grid bound included, and a
  plateau that reaches the grid edge extends the grid once before any key is kept or moved (residuals 2 and 3,
  calibration.md "How the rules combine"). A re-sweep thus changes only what the new rules made wrong, and a value at the
  edge of its plateau is not left there. This is a change of selection rule alone, never a retry (calibration.md). Every
  sweep prints and records beside the chosen value what the plain rule would choose (`plain rule`: the flat rule, else the
  plateau middle, on the same rows; residual 1: the first record of this column was wrong for `min_fraction`, where the
  tied plateau runs to the grid edge, and for the flat `min_overlap`).
- Procedure, at the pre-freeze review fixes: the floor alone first (`--only min_frames_floor`: best plateau 28 to 36, middle
  32); then the whole sweep from there. At the recheck: the floor is split, the body floor starts at 8, the retimed
  qualifying range is found (`scripts/retimed_floor.py`), then the whole sweep is run to a fixed point (three passes, the
  logs are `progress/calibrate-seed5-attempt4-split-pass1.log` to `-pass3.log`). `docs/thresholds.md` carries the table, with
  the plain rule's choice of every key, and the retimed rows.

## Seed 5 record per part (before the freeze)
Good light, every angle (P, R, faults on correct takes), labels found in good light (body 48, foot 24), correct takes'
grades (12 takes) and the score grades of the 60 single-fault takes (the reported target is B or C) and the 6
double-fault takes (D or F). Each row changes one part of the family from "before"; the harness is
`scripts/attempt4_ablation.py` (monkeypatches only; `--floor 8` for the rows at 8).

| variant | floor | front | 45 | side | body, foot found | correct takes | single-fault grades | double-fault grades |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- |
| before attempt 4 | 8 | 1.00, 0.96, 0 | 1.00, 1.00, 0 | 1.00, 0.92, 0 | 48, 21 | A 12 | A 3, B 49, C 8 | D 6 |
| part 3 alone (side lean) | 8 | 1.00, 0.96, 0 | 1.00, 1.00, 0 | 1.00, 0.92, 0 | 48, 21 | A 12 | A 3, B 49, C 8 | D 6 |
| part 1 alone (persistence per rep) | 8 | 0.96, 0.96, 0 | 0.92, 1.00, 0 | 0.74, 0.96, 1 | 48, 22 | A 11, B 1 | A 1, B 44, C 14, D 1 | D 5, F 1 |
| part 1 alone | 32 | 1.00, 0.96, 0 | 1.00, 1.00, 0 | 0.96, 0.92, 0 | 48, 21 | A 12 | A 3, B 49, C 8 | D 5, F 1 |
| part 2 alone (rep by rep, matched reps, feet) | 8 | 1.00, 0.96, 0 | 0.89, 1.00, 0 | 0.64, 0.96, 2 | 48, 22 | A 12 | A 4, B 43, C 12, D 1 | D 5, F 1 |
| part 2 with the foot measures hidden in rep mode | 8 | 1.00, 0.79, 0 | 1.00, 0.83, 0 | 0.80, 0.83, 0 | 48, 11 | A 12 | A 13, B 38, C 9 | D 5, F 1 |
| part 2 with the first rep as every reference | 8 | 1.00, 0.96, 0 | 0.80, 1.00, 1 | 0.62, 0.96, 2 | 48, 22 | A 12 | A 3, B 41, C 16 | D 6 |
| part 2 with the first rep as every reference | 32 | 1.00, 0.79, 0 | 0.95, 0.83, 0 | 0.95, 0.88, 0 | 46, 14 | A 12 | A 14, B 36, C 10 | C 1, D 5 |
| parts 1, 2 and 3 with the old floor | 8 | 0.96, 0.96, 0 | 0.89, 1.00, 0 | 0.64, 0.96, 2 | 48, 22 | A 12 | A 4, B 42, C 13, D 1 | D 5, F 1 |
| parts 1, 2 and 3, floor 32 (the family as merged, before the pre-freeze review) | 32 | 1.00, 0.96, 0 | 0.96, 1.00, 0 | 0.92, 0.96, 0 | 48, 22 | A 12 | A 6, B 44, C 10 | D 6 |
| the family after the pre-freeze review (B1 to B4), floor 32 as a duration | 32 | 1.00, 0.96, 0 | 1.00, 1.00, 0 | 0.96, 0.96, 0 | 48, 22 | A 12 | A 6, B 45, C 9 | D 6 |
| **the family after the recheck: N1, the floor split (body 8, foot 32), `knee_flexion` 10, `upper_arm_out` 11** | 8 body, 32 foot | 0.96, 0.96, 0 | 1.00, 1.00, 0 | 0.88, 0.96, 0 | 48, 22 | A 12 | A 6, B 46, C 8 | D 5, F 1 |

Reading it: part 3 changes nothing on seed 5 (there is no hinge past 90 degrees). Part 1 alone lets noise through at the
old floor and is the old behaviour at 32. Part 2 is what moves the dance, and without the foot measures it loses half the
foot labels, without matched references it loses recall at the floor that stops the noise. The floor is what makes them
work together, and continuing a reported fault in the rep the floor blinds (dissent 3) is what keeps the score targets
where they were: the correct takes stay A, the single-fault takes B or C but for the faults the detector misses or finds
in one rep only (A 6, was 3), the double-fault takes D.

The last row is the family as it goes to the freeze, measured after the pre-freeze review's fixes (B1 to B4), re-run with
the same harness. Only B2 moves seed 5: the floor as a duration and its cap leave all 156 takes byte for byte as they were
(a cap of 0.75 or more, the capped and the uncapped floor, give the same analyses), and a fault on both sides that was
reported twice in rep mode (`dance_45_good_12_ankle_rolled_out-both`, `dance_side_good_12_ankle_rolled_out-both`, and two
low-light takes) is now reported once. That removes two of the three good-light false positives (good/45
0.96 to 1.00, good/side 0.92 to 0.96), the single-fault grades move by one take (B 44 to 45, C 10 to 9), and
`fixtures/profiles-fitness-baseline.json` moves for those 4 takes. `rules.json` was unchanged and the re-sweep with the
amended selection rule kept every value; **what the plain rule would have chosen instead was recorded wrongly here and in
`docs/thresholds.md` (recheck residual 1) and is corrected**: the sweep of that state, re-run with the grid extended once
before any value is kept (residual 2, `progress/calibrate-seed5-attempt4-recheck-prefix-state.log`), keeps every value
again (seed 5 does not move) and its plain-rule column, for the keys where it differs, is `knee_flexion` 8 (kept 9, plateau
5 to 11), `upper_arm_out` 12 (kept 10, plateau 9 to 15), the floor 20 (kept 32; the extended plateau runs 4 to 36),
`min_fraction` 0.28 (kept 0.38; the tied plateau runs to the grid edge, 0.08 to 0.43 once the grid is extended, so its
middle is 0.28 and not the 0.33 of the unextended grid). `min_overlap` is flat, the plain rule keeps a flat key, so its
plain value is 0.3 and not the 0.4 recorded. The 13 other keys have the same value either way.

The last row is the family after the recheck of the pre-freeze review (N1, N2, residuals 1 to 6). Faults of every
good-light take are as they were except three (`docs/thresholds.md`, "The floor split and the retimed takes"): the body
floor of 8 lets noise in the dance's first rep (good/side 0.96 to 0.88, good/front 1.00 to 0.96), the correct takes stay A
12 of 12, the single-fault grades move by one take (B 45 to 46, C 9 to 8) and the double-fault takes by one (D 6 to D 5, F 1).
All the retimed rows find 24 of 24 (the pre-freeze rows found 9 of 24 and 11 of 24 in the 1.5 s squats).

Real takes (`make report-real`, reported and never gated), merged code `a716ce1` then this lane. Part 3's kit (15 takes at
15 fps against the 30 fps `part3-squat`, two squats, so rep by rep): tp 10, fp 5, fn 2 (P 0.6667, R 0.8333; before attempt 4
tp 9, P 0.6429, R 0.75) then tp 10, fp 4, fn 2 (P 0.7143, R 0.8333): B2 reports one fault where two were. The two stock
takes (Pexels 5034577 and 8837221, followers at 9.99 and 8.333 fps against a 9.99 fps side example of 154 frames): tp 0,
fp 0, fn 1 then tp 1, fp 5, fn 0 (P 0.1667, R 1.0). That is B1 alone (with the old floor patched back in, the stock
numbers and grades are the old ones): 32 frames at 10 fps is 3.2 s, longer than a rep of that example, so these takes could not report any
fault and scored A (98 and 96); the floor is 1.07 s at any rate now. 8837221 (labelled `elbow_bent`, both) now reports
`elbow_flexion` both, found, and four more (`upper_arm_forward`, `forearm_out`, `foot_rotation`, `foot_out`; F, 1);
5034577 (labelled correct) reports `foot_out` both (C, 77). The labels name the views: the example is a side camera, the
followers a front and a three-quarter one, so the extra faults are as much the view as the follower; nothing here was tuned.

After the recheck (`make report-real` exit 0, this branch): the kit is unchanged at tp 10, fp 4, fn 2 (P 0.7143, R 0.8333;
the totals do not move with the floor split and the re-swept thresholds). The two stock takes read tp 1, fp 7, fn 0
(P 0.125, R 1.0; it was tp 1, fp 5): the body floor of 8 lets two more faults through on followers that see the example
from another side, reported as measured and not tuned on. The Part 2 different-movement clips are still a low match graded F
(3 of 3), and the multi-rep lateral raises still match the example, 2 of 2 clips and 10 of 10 reps: pexels-40297504 is "right
elbow bent slightly more than the example" and "right hand too close in", score 80 (B) (it read as both elbows and both hands
before N1); pexels-8836968 has no fault, score 100.

## The recheck of the pre-freeze review (N1, N2 and the residuals; branch `lane/attempt-4-prefreeze-2`)
`progress/review-20261101-prefreeze-attempt4.md` found four blockers, fixed (B1 to B4); the recheck found one more and two
rulings followed. Nothing here reads a held-out seed or the moalborati/simon#59 take.
- **N1 (blocking): a side found in under half the reps was reported inside a two-sided fault.** `_toward_both` added every
  rep that found only `left` or only `right` to the `both` count, so right in reps 4 to 6 and `both` in rep 7 of 8 reported
  "elbows" on both sides; it also broke the premise of `evaluate.py` that detection emits `both` only when both sides fired.
  Fixed in Part 2 "Faults": each side is counted over the reps that found it, alone or as part of `both`; `both` only
  when both sides pass; else the side that does; without a `both` occurrence the exact-key rule. `compare` and
  `continue_reported` keep a rep's `both` fault in its window when the take reports either side. Seed 5 faults do not
  move (with two reps the half rule needs one); the window rule moves the scores of two takes (`docs/thresholds.md`).
- **N2: the floor splits by measure class (stakeholder-proxy ruling, confidence medium), verbatim:** "the floor splits by
  measure class before the freeze; foot measures keep 32 frames at 30 fps (a duration, at most 0.75 of a rep); body measures
  get their own floor of the same form, re-swept on seed 5 within the values that keep the 27 retimed seed 5 takes at attempt
  3's 24 of 24 in every row (the 00:05Z selection rule inside that range, 8 if nothing higher qualifies), pinned by a test,
  one delta recheck; if seed 5's gate-shaped criteria fail in that range or the delta is not merged and approved by
  2026-11-01T20:00Z, freeze as it stands under (a) with the fast-rep limit recorded and pinned by a test." Done:
  `default.min_frames_floor_body` 8 for every body measure, `default.min_frames_floor` 32 for the foot measures
  (`measures.FOOT_MEASURES`), both of the same form (Part 1). The qualifying range of the body floor is 4 to 20, flat on
  seed 5, so the flat rule keeps 8; the re-sweep under the split moved `knee_flexion` to 10 and `upper_arm_out` to 11 (the
  bar of 24 of 24 also caps `upper_arm_out` at 11 and `min_fraction` at 0.38). Every number is in `docs/thresholds.md`
  ("The floor split and the retimed takes"); the generator is a test helper (`tests/retimed.py`), the rows are pinned in
  `tests/test_retimed.py`. The fast-rep limit that remains is the foot measures' (Edge Cases).
- **Residual 4: the per-attempt detection line** (stakeholder-proxy ruling), see AC-SEED-03 and `calibration.md`: only
  the per-seed `detection_sha256` line is implemented, with the known limit recorded and pinned: "a deliberate revert of
  rules.json to a retired attempt's bytes under later code is not caught by the per-attempt detection line; check-5's
  reproduce-the-recorded-numbers check after analysis is the guard; no part5 code-diff requirement (stakeholder-proxy ruling)".
- **Residual 5**: `reference_fps` and `floor_share` are keys of `default` in `rules.json` (AC-RP-23), inside
  `detection_sha256`. **Residuals 1 to 3**: the sweep's plain-rule column, the extension before the choice, and the flat rule
  against a grid bound (`calibration.md`, "How the rules combine"). **Residual 6**: the R8 subprocess test runs the script
  with the repo off the path and fails without the insert. **Residual 9**: `tests/test_check.py` split, no test id lost.

## Acceptance Criteria
- AC-RP-01: a 69 frame deviation in one rep of a 300 frame example of four reps is a fault (92% of its rep, over the 38%
  it needs); the same series judged over the whole clip is a near miss with `counted_frames` 69 and `needed_frames` 114.
- AC-RP-02: an example of one rep, or `rep_spans` None or one span, gives the faults and candidates the whole clip always
  gave.
- AC-RP-03: each rep needs `min_fraction` of itself and its own runs alone: 30% of each of two reps is no fault; 45
  frames in one rep and 10 in the other is a fault of the first rep's run only.
- AC-RP-04: a run belongs to the rep that holds most of it, a tie to the earlier, and is counted whole.
- AC-RP-05: the floor and an explicit `min_frames` are counts of frames of a rep, not shares of it (the floor at the
  example's rate and capped, AC-RP-20).
- AC-RP-06: a candidate that fails reports the rep that came closest and the longest run in it, with `shortfall_frames`: with
  runs (0, 29), (100, 119) and (130, 145) over two reps of 100 frames it reads (100, 119), counted 36, needed 38, not the
  run (0, 29) of the other rep (B4).
- AC-RP-07: a reported fault and its candidate agree on size and frames.
- AC-RP-08: a profile's looser config is judged in the reps too.
- AC-RP-09: `Segmentation.partition` tiles the clip with no gap and no shared frame.
- AC-RP-10: `matched_rep` pairs rep `k` with rep `k` when the follower has no more reps than the example, else the first.
- AC-RP-11: the frame pairs of references of different lengths are the sum of their squares; the bound runs at exactly the
  limit and names numbers that multiply to at least the pairs.
- AC-RP-12: an example of two reps is compared rep by rep though the whole-clip guard accepts the take; an example of one
  rep is compared as a whole with no rep field.
- AC-RP-13: each follower rep is compared with its matched rep; a fault sits in the reference of the rep that found it, on
  the expected file's frames.
- AC-RP-14: the foot measures are compared rep by rep and a planted foot fault is found; a correct dance take with feet
  reports none.
- AC-RP-15: the foot series are cut and resampled like the joints.
- AC-RP-16: a rep verdict that refuses the take leaves the whole-clip comparison, persistence judged in the example's reps.
- AC-RP-17: the replay plays each rep against its own reference and validates against `replay.schema.json`.
- AC-RP-18: `rules.json` holds the persistence keys the sweep moves (`min_frames_floor`, `min_frames_floor_body`,
  `min_fraction`, `min_run_frames`, `min_overlap`) and the two constants of the floor, `reference_fps` and `floor_share`
  (residual 5: they were module constants outside `detection_sha256`).
- AC-RP-19: a fault the take reports is counted in every rep that shows it for `min_fraction` of itself without the floor
  (`continue_reported`), a refused rep and a key the take does not report get nothing, a correct take has nothing
  continued, and the short first rep of the dance is scored for the fault the take reports; a rep that holds the fault
  on an overlapping side (the same, or `both` against either) is not charged for it a second time (B2).
- AC-RP-20 (B1, `tests/test_rep_persistence.py`): the floor is a duration. `floor_frames` is the measure's floor in frames
  at 30 fps (`reference_fps`) turned into the example's rate and at most `round(floor_share * L)` (0.75) of the rep; the same seed 5 exercise take with its
  example and follower thinned to 15 and to 5 fps reports what it reports at 30 fps, the dance takes with an arms,
  elbow, trunk or foot fault do at 15 and 5 fps, a dance at twice the speed (reps of 22 and 31 frames, under the floor)
  keeps its arms_wider and trunk_lean faults, and a two-rep example with reps of 30 frames reports a fault held through
  25 frames of each and none held through 12.
- AC-RP-21 (B2, made exact by N1; `tests/test_reps.py`, `tests/test_rep_persistence.py`): a fault that some rep found on
  both sides is reported once, the half rule applied to each side over the reps that found it, alone or as part of `both`.
  `both` when both sides reach half of the accepted reps, the one side that does otherwise (right in reps 0 to 2 and `both`
  in rep 3 of 4 is `right`, reps [0, 1, 2, 3]; `left` in 1 of 3 and `both` in another is `left`), nothing when neither
  does; one-sided faults alone are judged per exact key as they were; a `both` fault covers only its own measure and
  direction; a rep's `both` fault is in its window, and continued, when the take reports either of its sides. Seed 5
  `dance_45_good_12_ankle_rolled_out-both` reports one `ankle_inversion` fault, side `both`, reps [0, 1]; the real lateral
  raise pexels-40297504 reports "right elbow bent slightly more than the example" and "right hand too close in", score 77 (80 at the shipped `upper_arm_out` 11).
- AC-RP-22 (N2, `tests/test_rep_persistence.py`, `tests/test_retimed.py`): the floor splits by measure class. A foot
  measure reads `min_frames_floor` (32) and every other measure `min_frames_floor_body` (8), both in the form of AC-RP-20;
  `without_floor` takes both out; the 27 retimed seed 5 takes keep 24 of 24 labelled faults found in each of six rows at the
  shipped rules, and the value above the top of each swept key's qualifying range loses a fault.
- AC-RP-23 (residual 5): `reference_fps` and `floor_share` are keys of `default` in `rules.json`, read from the config
  everywhere (the module has no constant of either name), so they are inside `detection_sha256`.
- AC-SL-01 to AC-SL-05 (`tests/test_measures.py`): the side lean reads 0 for a hinge of 0 to 180 degrees with no side lean,
  keeps its size and sign for a real side lean at any hinge, is bounded and continuous through 0 to 120 degrees, and the
  neck's frontal projection still wraps.
- AC-SEED-01 (`tests/test_check.py`, `tests/test_heldout_protocol.py`, `tests/test_generator.py`,
  `tests/test_score_heldout.py`): the held-out order is 29, 31, 37, 67, 71, 73 with none skipped; `make heldout-data`
  accepts the six and refuses the rest; `make score-heldout` refuses every one of the six, generated or not, also when
  the script is run directly (R8).
- AC-SEED-02 (`tests/test_check.py`, `tests/test_heldout_protocol.py`; pre-freeze review B3 and R7): a seed is checked
  against its own freeze. Each attempt section of `docs/thresholds.md` carries a `detection_sha256` line, the detection
  hash of its freeze commit (checked against `git show <freeze>:part5/rules.json`); a seed that already has an attempt is
  judged by its own record alone, so the retired seed 37 is refused by `require_frozen` before any take is analysed
  (a spy on `analyse_set` is never called) and the `detection_sha256` under "Score" (the current freeze) stands only for
  a seed not scored yet. `check_seed` refuses a seed that skips the next unused one (71 while 67 is unscored).
- AC-SEED-03 (`tests/test_check_freeze.py`; recheck residual 4): a scored seed of the second series (67, 71, 73) must have
  its own `detection_sha256` line in its attempt record, whether or not the rules hash matches; without it the check
  refuses (exit 2) before any take is analysed. A seed with no attempt yet, and 29, 31 and 37, are as they were. Known
  limit, as ruled (stakeholder-proxy): the line hashes the detection rules, not the code, so a deliberate revert of
  `rules.json` to a retired attempt's bytes under later code is not caught by it; `require_unchanged_scores`, which refuses
  a scored seed whose numbers differ from its recorded attempt after the analysis, is the guard; there is no `git diff` of
  `part5/` requirement. The test pins both what is covered and what is not.
- AC-CAL-01 (`tests/test_calibrate.py`): the sweep runs the pipeline, refuses a set that is not seed 5, leaves the foot
  thresholds and the foot floor alone, sweeps the body floor, extends the grid once before it chooses, keeps a flat key's
  value (a grid bound included, and before any other rule), and, on a re-sweep, keeps a current value only when it ties at
  the best objective strictly inside the longest run of its plateau (a value at either end, or on a shorter tied run, goes
  to the middle), and reports the plain rule's choice of every key (residuals 1 to 3).
- Seed 5 gate-shaped criteria, reported before the freeze (`docs/thresholds.md`): good light P at least 0.85 and 0 faults
  on correct takes at every angle, the highest minimum recall, every correct good-light take an A.

## Error Cases
| Condition | Behavior | AC |
| --- | --- | --- |
| reps together over the frame-pair limit | exit 1, the plain error, nothing written | AC-RP-11 |
| every rep refused for alignment | the whole-clip comparison stands | AC-RP-16 |
| a feet file for one clip only, or unusable | the foot measures are hidden with the reason, as in a whole comparison | AC-RP-14 |
| `calibrate` on a set that is not seed 5 | exit 2 | AC-CAL-01 |
| `make score-heldout SEED=<held-out seed>` | exit 2, nothing generated | AC-SEED-01 |

## Edge Cases
- A fault that straddles two reps is one run, owned by the rep that holds most of it (AC-RP-04).
- The lead-in and tail of the example belong to its first and last rep (AC-RP-09).
- A follower with one segment against two example reps is compared whole with the first (AC-RP-10).
- A profile never reports a fault fitness does not: the floor is copied unchanged, so it is the same duration (AC-RP-08).
- A short or slow example: a rep or a clip under 1.07 s (32 frames at 30 fps) still persists a fault held through three
  quarters of it (AC-RP-20). **The fast-rep limit, recorded and pinned (recheck N2): this limit used to bind every measure
  and is now the foot measures' alone.** With a floor of 32 a squat of 1.5 s at 30 fps (46 frames) needed 32 frames, 70% of the
  rep, and the planted squat faults of seed 5 retimed to it (the retimed row "1.5 s squat, 30 fps") fell to 9 of 24 found;
  the body floor of 8 gives 24 of 24 there. A foot measure still needs 32 of those 46 frames
  (`tests/test_rep_persistence.py::test_n2_the_floor_splits_by_measure_class_...` pins `needed` 32 for a foot measure and 17
  for a body measure in a 46 frame rep at 30 fps), so a foot fault in a rep that fast is reported only when it fills most of
  the rep. The foot floor is held by the ruling and seed 5 holds foot faults at 22 of 24 labels found at good light with it.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
| --- | --- | --- | --- |
| Performance | One dance analysis stays under 2 s | two reps of 43 and 61 frames | AC-RP-11 |
| Reliability | Determinism | byte-identical reruns, the sweep table included | AC-CAL-01 |
| Compatibility | `analysis.json` | no field added, schema 1.8.0 | AC-RP-12 |
| Compatibility | `load_rules`, `run(..., rules=)` | signatures unchanged | AC-RP-12 |

## Negative Requirements
- MUST NOT read, generate, score or print any number of a held-out seed before attempt 4's freeze commit. Why: ADR-0017.
- MUST NOT select a threshold, rule or design choice from the moalborati/simon#59 take. Why: ADR-0017.
- MUST NOT change a foot measure's definition, visibility rule or threshold. Why: TICKET-040's family.
- MUST NOT change the score parameters. Why: ADR-0017 ("What does not change").
- MUST NOT add a field to `analysis.json` without bumping its version. Why: the contract is additive.

## Non-Requirements
- Per-rep references in `analysis.json`: the replay and `faults[].expected_frames` carry them; a field would bump the schema.
- A change of the score's parameters or formula for a fault the take reports but a rep missed: `continue_reported` only
  puts the fault in that rep's window (dissent 3), the points a miss costs are ADR-0007's and ADR-0013's, unchanged.

## Assumptions
ASM-002 (the generator is a fair proxy, now six seeds), ASM-013 (synthetic feet).

## Delivery Verification Plan
- `make test` 0; `make check-5-contract` 0; `make report-real` 0; `make report-profiles` 0 (0 faults not reported by fitness).
- `python -m part5.calibrate --set fixtures/input/followers --guard --write-thresholds` exit 0, the table in
  `docs/thresholds.md`.
- `python3 scripts/make_design_copies.py --check` 0.
- After the freeze commit and not before: `make heldout-data SEED=67`, then `make check-5` once (ADR-0017). Neither is part of
  this lane.

### Device/Platform Strategy
Not applicable: no UI change. The staging page shows the same fields.

### Data
Seed 5 only (`fixtures/input/followers`), the committed real takes and the committed expected clips. No held-out seed.

### Ratchet Initialization Plan
Not applicable: no new milestone.

## Dissent Review
### Concern 1: the floor is a tuned constant that the dance example shapes
Kept: it is a duration, 32 frames at 30 fps, chosen on seed 5 by the established sweep (plateau 28 to 36), the reported cost
is stated, and the single-rep examples of 43 frames or more at 30 fps are exactly as they were; a shorter or slower example
persists a fault held through three quarters of it (AC-RP-20), where the frame count alone made it blind.
### Concern 2: matching reps by index is a guess when the follower's count differs
Kept: it applies only when the follower has no more reps than the example; otherwise ADR-0010's first rep stands.

## Files (every new or changed source file; the write gate reads this table)
| File | Part | Published |
| --- | --- | --- |
| `part5/measures.py` (`_sideways`, `trunk_lean_side`) | 3 | yes |
| `part5/detect.py` (`rep_spans`, `fps`, `overlaps_side`, `as_both`; the candidate points at `Persistence.longest`) | 1, 2 | yes |
| `part5/reps.py` (`Segmentation.partition`) | 1, 2 | yes |
| `part5/repwise.py` (`matched_rep`, `_pairs`, `_foot_rep`, `compare`, `RepResult.ref_start`, `without_floor`, `continue_reported`, `aggregate_faults` for a fault on both sides) | 2 | yes |
| `part5/score_report.py` (`_rep_timeline` counts the continued faults, `take_row` and `rep_mean_z` for a rep-by-rep take) | 2 | yes |
| `part5/feet.py` (a docstring; `resampled_series`, the stack-resample-unstack the pipeline and `repwise` share, R10) | 2 | yes |
| `part5/profiles_report.py` (the comment of the baseline it writes), `fixtures/profiles-fitness-baseline.json` (taken again at attempt 4: 94 of the 156 hashes move, 73 dance takes and 21 exercise takes whose similarity term reads the new side lean; and once more at the pre-freeze review: 4 dance takes whose two-sided fault was reported twice; and once more at the recheck: 119 of the 156, the floor split, two thresholds and the window rule) | 2, 3 | yes |
| `part5/pipeline.py` (rep mode for two or more reps, the foot series, the spans, `fps`, `REP_MODE_REASON` removed) | 1, 2 | yes |
| `part5/profiles.py` (imports `DEFAULT_MIN_RUN_FRAMES` from `persistence`) | 1 | yes |
| `part5/replay.py` (a reference per rep) | 2 | yes |
| `part5/calibrate.py` (the pipeline runs, the guard, `docs/thresholds.md`, the held foot thresholds) | calibration | yes |
| `part5/sweep.py` (new, pre-freeze review R1: the sweep, the body floor and `choose` with its flat and re-sweep rules, the extension before the choice, the plain rule, `RETIMED_TOPS`; moved out of `calibrate.py` to keep it under 800 lines) | calibration | yes |
| `part5/persistence.py` (new, pre-freeze review R1: `judge`, `Persistence`, the floor as a duration, split by measure class, its constants read from the rules; moved out of `detect.py` to keep it under 500 lines) | 1 | yes |
| `part5/check.py` (`HELDOUT_SEEDS`, `SECOND_SERIES`; `require_frozen` per attempt and `check_seed` in order, B3, R7 and residual 4) | seeds | yes |
| `part5/rules.json` (`default.min_frames_floor`, `min_frames_floor_body`, `reference_fps`, `floor_share`; `knee_flexion` and `upper_arm_out` thresholds) | calibration | yes |
| `scripts/make_score_heldout.py` (the path insert, R8), `Makefile` (`heldout-data`), `docs/thresholds.md` (a `detection_sha256` line per attempt) | seeds | no (firm) |
| `scripts/attempt4_ablation.py` (the per-part record on seed 5), `scripts/retimed_floor.py` (the retimed qualifying range of a key), `tests/retimed.py` (the retimed takes' generator, a test helper), `tests/test_retimed.py`, `tests/test_check_freeze.py` (split from `tests/test_check.py`) | record | no (firm) |
| `tests/test_rep_persistence.py`, `tests/test_measures.py`, `tests/test_check.py`, `tests/test_heldout_protocol.py`, `tests/test_generator.py`, `tests/test_score_heldout.py`, `tests/test_calibrate.py`, `tests/test_feet.py`, `tests/test_reps.py`, `tests/test_near_misses.py`, `tests/test_near_misses_reps.py`, `tests/test_profiles.py`, `tests/test_review_fixes.py`, `tests/test_real.py` | all | yes |

## Deviations from PRD
None.
