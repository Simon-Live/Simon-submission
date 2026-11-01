# Thresholds and guard limits

Written by `python -m part5.calibrate --set fixtures/input/followers --write-thresholds` from the
seed 5 tuning set only. Held-out numbers were not used to tune any value here (ADR-0003).

Since attempt 4 (ADR-0017) every take of the set goes through the pipeline at each candidate value, foot side
files included, so an example of two or more reps is compared rep by rep and persistence is judged in each
rep, as in `make check-5`; the slices below hold every take of the set, the foot-fault takes too. A key whose
current value ties at the best objective and lies strictly inside the longest run of its plateau (not at either
end) keeps it, and any other key goes to the middle of its plateau (a re-sweep changes only what the new rules
made wrong); a key that is flat keeps its current value first of all. A plateau that reaches the grid edge extends
the grid once before any of this is decided. The `plain rule` column is what the first calibration's rule alone
would choose for every key on the same rows: the flat rule, else the middle of the longest plateau run.

A persistence floor is a duration, written as frames at 30 fps: the time a deviation must hold in a rep
whatever the rep's length, turned into frames at the example's own rate and never more than three quarters
of the rep (`part5/persistence.py`). It splits by measure class: `min_frames_floor_body` for the body measures, `min_frames_floor` for the foot measures. It is 8 for the body measures here, 0.27 s. The foot measures keep `min_frames_floor` 32 (1.07 s).
The table below is the whole sweep run from the rules in force, so its `before` column is the value each key
started from.

Expected clips: Part 4 commit dc3d9f2e70a0d3e95efb60bea1e5ab7fc307d284 (`fixtures/input/expected/SOURCE.md`).

## Chosen values (seed 5)

| key | before | plateau | grid | plain rule | chosen | the sweep row that chose it (good light, minimum recall) |
| --- | ---: | --- | --- | ---: | ---: | --- |
| elbow_flexion threshold_deg | 20 | 16 to 25 | 14 to 26 | 21 | 20 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (current value ties at the best objective inside its plateau, kept) |
| knee_flexion threshold_deg | 10 | 8 to 11 | 4 to 16 | 10 | 10 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (current value ties at the best objective inside its plateau, kept) |
| upper_arm_out threshold_deg | 11 | 10 to 11 | 5 to 11 | 11 | 11 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 |
| forearm_out threshold_deg | 17 | 12 to 29 | 5 to 29 | 21 | 17 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (plateau still reaches the grid edge after one extension; current value ties at the best objective inside its plateau, kept) |
| thigh_out threshold_deg | 13 | 9 to 25 | 1 to 25 | 17 | 13 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (plateau still reaches the grid edge after one extension; current value ties at the best objective inside its plateau, kept) |
| foot_out threshold_deg | 6 | 5 to 9 | 1 to 12 | 7 | 6 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (current value ties at the best objective inside its plateau, kept) |
| knee_valgus threshold_deg | 9 | 7 to 14 | 3 to 15 | 11 | 9 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (current value ties at the best objective inside its plateau, kept) |
| upper_arm_forward threshold_deg | 15 | 9 to 21 | 9 to 21 | 15 | 15 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (flat on seed 5, current value kept) |
| thigh_forward threshold_deg | 15 | 9 to 21 | 9 to 21 | 15 | 15 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (flat on seed 5, current value kept) |
| trunk_lean_forward threshold_deg | 9 | 4 to 15 | 1 to 21 | 10 | 9 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (grid extended once; current value ties at the best objective inside its plateau, kept) |
| trunk_lean_side threshold_deg | 9 | 4 to 21 | 1 to 21 | 13 | 9 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (plateau still reaches the grid edge after one extension; current value ties at the best objective inside its plateau, kept) |
| shoulder_tilt threshold_deg | 9 | 4 to 21 | 1 to 21 | 13 | 9 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (plateau still reaches the grid edge after one extension; current value ties at the best objective inside its plateau, kept) |
| head_forward threshold_deg | 18 | 12 to 24 | 12 to 24 | 18 | 18 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (flat on seed 5, current value kept) |
| min_frames_floor_body | 8 | 4 to 20 | 4 to 20 | 8 | 8 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (flat on seed 5, current value kept) |
| min_fraction | 0.38 | 0.38 to 0.38 | 0.23 to 0.38 | 0.38 | 0.38 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 |
| min_run_frames | 4 | 1 to 7 | 1 to 7 | 4 | 4 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (flat on seed 5, current value kept) |
| min_overlap | 0.3 | 0.1 to 0.6 | 0.1 to 0.6 | 0.3 | 0.3 | min recall 0.96; front 0.96/0.96/0  45 1.00/1.00/0  side 0.88/0.96/0 (flat on seed 5, current value kept) |

Held, not swept here (`--feet` owns the thresholds, TICKET-040; attempt 4 keeps them, ADR-0017; the N2 ruling holds the foot floor): foot_rotation threshold_deg 14, ankle_inversion threshold_deg 14, foot floor min_frames_floor 32.

## Guard limits

| limit | value | matched | mismatch |
| --- | ---: | --- | --- |
| max_residual | 0.5677 | max 0.5231 | min 0.6122 |
| min_timing_corr | 0.8336 | min 0.9110 | max 0.7562 |

- Excluded from the mismatch population: part2-single (provisional barbell back squat, pose3d.json sha256 433ae2edfe61b7e5c027f06ccdea289df34741225829f45fb5a652bb5147d857): Part 2's fixtures/output/single stays the team's provisional barbell squat (Part 2 does not overwrite it), so it is a matched squat pair; the seated stretch its input names is published separately as scored/single and is the part2-stretch fixture
- Overlap, takes named: none

## Seed 5 per-slice table at the chosen values

| slice | tp | fp | fn | precision | recall | faults on correct takes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| good/45 | 24 | 0 | 0 | 1.00 | 1.00 | 0 |
| good/front | 23 | 1 | 1 | 0.96 | 0.96 | 0 |
| good/side | 23 | 3 | 1 | 0.88 | 0.96 | 0 |
| low/45 | 22 | 30 | 2 | 0.42 | 0.92 | 3 |
| low/front | 23 | 12 | 1 | 0.66 | 0.96 | 1 |
| low/side | 16 | 71 | 8 | 0.18 | 0.67 | 14 |

Recall by fault type, set and lighting:

- ankle_rolled_in dance good: 2/3
- ankle_rolled_in dance low: 1/3
- ankle_rolled_in exercise good: 3/3
- ankle_rolled_in exercise low: 2/3
- ankle_rolled_out dance good: 3/3
- ankle_rolled_out dance low: 1/3
- ankle_rolled_out exercise good: 2/3
- ankle_rolled_out exercise low: 2/3
- arms_wider dance good: 5/5
- arms_wider dance low: 4/4
- arms_wider exercise good: 5/5
- arms_wider exercise low: 4/5
- elbow_bent dance good: 4/4
- elbow_bent dance low: 4/4
- elbow_bent exercise good: 5/5
- elbow_bent exercise low: 3/4
- foot_out dance good: 5/5
- foot_out dance low: 4/5
- foot_out exercise good: 4/4
- foot_out exercise low: 4/4
- foot_turned_in dance good: 3/3
- foot_turned_in dance low: 3/3
- foot_turned_in exercise good: 3/3
- foot_turned_in exercise low: 2/3
- foot_turned_out dance good: 3/3
- foot_turned_out dance low: 3/3
- foot_turned_out exercise good: 3/3
- foot_turned_out exercise low: 2/3
- knee_caving dance good: 3/3
- knee_caving dance low: 3/3
- knee_caving exercise good: 3/3
- knee_caving exercise low: 3/3
- knees_shallow dance good: 3/3
- knees_shallow dance low: 3/3
- knees_shallow exercise good: 3/3
- knees_shallow exercise low: 3/3
- trunk_lean dance good: 4/4
- trunk_lean dance low: 5/5
- trunk_lean exercise good: 4/4
- trunk_lean exercise low: 5/5

<!-- attempts:begin -->
## Held-out attempts

One section per attempt, in seed order (29, 31, 37, then the second series 67, 71, 73; ADR-0017). Nothing below this line is generated or
rewritten by `calibrate`, and a red attempt is never removed. Each section's heading names the seed and
carries these lines, which `make check-5` reads for the current attempt (`part5/check.py`). The template below is
a list, not a copy-and-paste block, so that no line of it starts with a line label and a search for a recorded hash
prints real values only. In a real section each label starts its own line and the value follows it in backticks (the
hashes and the commit) or as plain words:

- the heading, `### Attempt <n>: seed <seed>`
- the label `Freeze commit:`, then the sha of the commit that froze rules.json and the code
- the label `rules_sha256:`, then the sha256 of part5/rules.json at the freeze commit
- the label `detection_sha256:`, then the sha256 of its detection rules (rules.json without `score`, computed as under
  "Freeze check for the detection rules" below), so that a scored seed is checked against its own freeze and never
  against a later one (pre-freeze review B3)
- the label `Date:`, then the date the seed was generated
- the label `Approach family:`, then the family, different from every earlier attempt's

then a one-paragraph rationale, and after scoring the held-out table as measured, pass or fail.

### Attempt 1: seed 29
Freeze commit: `fbb0bea78decfc7cf0e0d48e756e3021ea5d8616`
rules_sha256: `60f2e60b4bd60cea890ddbbce63c9d03ff82ff18f49e6284cb3cd48ff9aa62a4`
detection_sha256: `b76e6ca378557910a75f5f2ecedbab80452d4b3c0d87cae328b9f5c79967da6a`
Date: 2026-10-29
Approach family: baseline rule detection (per-measure thresholds, two-pass DTW alignment, persistence over runs, knee_valgus, movement guard on residual and timing correlation) with plateau-centre threshold selection on seed 5

Rationale. This is the first held-out attempt and the baseline approach family: every fault is a
per-measure difference against the expected clip at the DTW-matched phase, counted when its runs of at
least 4 frames add up to 38% of the clip (#30), with `knee_valgus` added for knee caving and the
movement guard refusing a take whose alignment residual is above 0.5677 or whose timing correlation is
below 0.8336. Every value was chosen on seed 5 only (108 takes, 96 labelled faults) by
`python -m part5.calibrate --set fixtures/input/followers --guard --write-thresholds`: precision first
with no fault on a correct take, then the best minimum recall, and the middle of the tied plateau so
the frozen value keeps margin from both the noise on correct takes and the smallest faults. On seed 5,
good light reads P 1.00, R 1.00 and 0 faults on correct takes at front, 45 and side, and the guard
separates every matched take from every mismatch pair. No held-out number existed when these values
were frozen.

Held-out result as measured (`make check-5` exit 0 at `d592148`, 2026-10-29): **passed**.

| slice | gated | tp | fp | fn | takes | correct takes | faults on correct takes | precision | recall | refused |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dropout/45 | no | 31 | 6 | 1 | 36 | 8 | 1 | 0.84 | 0.97 | 0 |
| dropout/side | no | 30 | 17 | 2 | 36 | 8 | 5 | 0.64 | 0.94 | 0 |
| good/45 | yes | 16 | 0 | 0 | 18 | 4 | 0 | 1.00 | 1.00 | 0 |
| good/front | yes | 16 | 0 | 0 | 18 | 4 | 0 | 1.00 | 1.00 | 0 |
| good/side | yes | 16 | 0 | 0 | 18 | 4 | 0 | 1.00 | 1.00 | 0 |
| low/45 | no | 15 | 5 | 1 | 18 | 4 | 0 | 0.75 | 0.94 | 0 |
| low/front | no | 16 | 1 | 0 | 18 | 4 | 0 | 0.94 | 1.00 | 0 |
| low/side | no | 14 | 17 | 2 | 18 | 4 | 5 | 0.45 | 0.88 | 0 |

Seed 29 is retired: it is never regenerated, rescored or used for tuning. Next: the confirmation on
seed 31 with the same freeze (calibration.md: after a green attempt, confirm on the next unused seed).
### Attempt 2: seed 31
Freeze commit: `fbb0bea78decfc7cf0e0d48e756e3021ea5d8616`
rules_sha256: `60f2e60b4bd60cea890ddbbce63c9d03ff82ff18f49e6284cb3cd48ff9aa62a4`
detection_sha256: `b76e6ca378557910a75f5f2ecedbab80452d4b3c0d87cae328b9f5c79967da6a`
Date: 2026-10-29
Approach family: confirmation of attempt 1 (the same baseline rule detection and the same freeze, unchanged)

Rationale. Attempt 1 passed on seed 29, so `calibration.md` asks for a confirmation on the next unused
seed with nothing changed: the same freeze commit, the same `rules.json` and code. This is not a retry
and names no new approach family. A red confirmation counts as a red attempt and is published as
measured.

Held-out result as measured (`make check-5` exit 0 at `3be3b40`, 2026-10-29): **passed**, confirming attempt 1.

| slice | gated | tp | fp | fn | takes | correct takes | faults on correct takes | precision | recall | refused |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dropout/45 | no | 31 | 5 | 1 | 36 | 8 | 1 | 0.86 | 0.97 | 0 |
| dropout/side | no | 29 | 15 | 3 | 36 | 8 | 3 | 0.66 | 0.91 | 0 |
| good/45 | yes | 16 | 0 | 0 | 18 | 4 | 0 | 1.00 | 1.00 | 0 |
| good/front | yes | 16 | 0 | 0 | 18 | 4 | 0 | 1.00 | 1.00 | 0 |
| good/side | yes | 16 | 2 | 0 | 18 | 4 | 0 | 0.89 | 1.00 | 0 |
| low/45 | no | 15 | 5 | 1 | 18 | 4 | 1 | 0.75 | 0.94 | 0 |
| low/front | no | 15 | 0 | 1 | 18 | 4 | 0 | 1.00 | 0.94 | 0 |
| low/side | no | 15 | 18 | 1 | 18 | 4 | 4 | 0.45 | 0.94 | 0 |

Seed 31 was the held-out set until attempt 3 below.

### Attempt 3: seed 37
Freeze commit: `fb1d6e816c99ab8a0c276c0d8c46d603b872c392`
rules_sha256: `37f163c9f3de634c7f467a706c8bc6fb915bef3ee6c8c8d1ffb19ae032e5f68c`
detection_sha256: `e340940f4fdc97a2761b7795b8d2c3a7177b75154acd449148b6e905431291ae`
Date: 2026-10-31
Approach family: a new measure, foot keypoints (`foot_rotation` and `ankle_inversion` from Part 2's `extra_joints`; TICKET-040, ADR-0015)

Rationale. Part 2 published foot points (`extra_joints`, moalborati/simon-part-2-images-to-3d e8ac336) and the operator
asked for foot cues (TICKET-040, ADR-0014's "What is not measured"). The detection rules gain two thresholds,
`foot_rotation` 14 and `ankle_inversion` 14 degrees, chosen on seed 5 only by `python -m part5.calibrate --feet`
(`progress/calibrate-feet-seed5-attempt-b.log`, rechecked unchanged in `attempt-c.log` after the pre-freeze review): both
GO at good light at every angle (0 faults on correct takes, precision 1.00, recall 0.75 or more, both directions found).
Every earlier key and value is unchanged, so the body measures behave as in attempts 1 and 2: seed 31's slices are
identical with the foot code in place (scored without the freeze check before the freeze). This is a new measure, so it
needs its own held-out score: seed 37, the last held-out seed, generated once with feet (`make heldout-data SEED=37`,
13 takes per cell, 260 with the dropout copies), scored once. Its gated good-light slices count the foot labels (8 per
angle) beside the body labels (16 per angle). A red result is published here and ends the run DEGRADED; green leaves no
seed to confirm it on. Not tuned on seed 37 before or after.

Held-out result as measured (`make check-5` at `45f8752`, 2026-10-31T15:20Z: the check exited 1, which make reports as
2): **failed**, 3 criteria. good/side has 1 fault on a correct take: `dance_side_good_01_correct`, `ankle_inversion`
right `more` 21.5 degrees at 2.5 s ("right ankle rolling out"), the far foot in side view; the same take and its
dropout copy score 87 (B) where a correct good-light take must be an A. Precision and recall pass at every gated angle
(front 1.00 and 0.92, 45 0.96 and 0.96, side 0.88 and 0.96).

| slice | gated | tp | fp | fn | takes | correct takes | faults on correct takes | precision | recall | refused |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dropout/45 | no | 41 | 20 | 7 | 52 | 8 | 3 | 0.67 | 0.85 | 0 |
| dropout/side | no | 41 | 41 | 7 | 52 | 8 | 6 | 0.50 | 0.85 | 0 |
| good/45 | yes | 23 | 1 | 1 | 26 | 4 | 0 | 0.96 | 0.96 | 0 |
| good/front | yes | 22 | 0 | 2 | 26 | 4 | 0 | 1.00 | 0.92 | 0 |
| good/side | yes | 23 | 3 | 1 | 26 | 4 | 1 | 0.88 | 0.96 | 0 |
| low/45 | no | 20 | 18 | 4 | 26 | 4 | 4 | 0.53 | 0.83 | 0 |
| low/front | no | 19 | 8 | 5 | 26 | 4 | 1 | 0.70 | 0.79 | 0 |
| low/side | no | 19 | 42 | 5 | 26 | 4 | 5 | 0.31 | 0.79 | 0 |

Seed 37 is retired: it is the last held-out seed (29, 31, 37), it is never rescored, regenerated or used to tune, and
the rules are not reverted (scoring it again under the old rules would be a rescore). `make check-5` now exits 1 on it.
The held-out protocol is used up; any further attempt needs an operator ruling on ADR-0003.

### Attempt 4: seed 67
Freeze commit: `fb06c27dd90aec99f78312078d639347297c62dc`
rules_sha256: `077affcf0a3104356558cedf79a57eaf499fd2cb36637a92078adf23ddbd3534`
detection_sha256: `0a559e183adad714e4ce0a6f2f03a5aba9a51bc1ed26daae4cf25e6cdd15d345`
Date: 2026-11-01
Approach family: a different persistence and alignment rule (ADR-0017, TICKET-044, moalborati/simon#59 items 1, 2 and 4): persistence measured per expected rep, with a floor taken as a duration and capped at 0.75 of the rep, split by measure class (body measures 8 frames at 30 fps, foot measures 32); rep by rep whenever the expected clip has 2 or more reps (follower rep k against expected rep k, foot measures compared, a two-sided fault counted per side); and `trunk_lean_side` measured so it does not wrap through a deep hinge

Rationale. The seeds 29, 31 and 37 were used up (attempt 3 red); the stakeholder-proxy ruling of 2026-10-31T22:25Z
(ADR-0017) fixed a second series, 67, 71, 73, after a real follow take (moalborati/simon#59, an RDL, evidence in moalborati/simon
at 8d820a8, reported by reference and never tuned on) scored 100 / A with 0 faults: persistence was a share of the whole
300-frame clip, rep by rep ran only when the whole-clip guard refused, and the side lean wrapped past about 90 degrees
of hinge. This family changes all three together, tuned on seed 5 only (`docs/specs/rep-persistence.md`).

What changed in `part5/rules.json` against attempt 3: the body floor `min_frames_floor_body` 8 and the foot floor
`min_frames_floor` 32 (a duration at the example's rate, `reference_fps` 30, capped at `floor_share` 0.75 of a rep;
rulings of 01:40Z and 03:45Z), `knee_flexion` 9 to 10 and `upper_arm_out` 10 to 11. Selection: a current value is kept
only when it ties at the best seed 5 objective strictly inside the longest plateau run (ruling of 00:05Z), and no
swept key may take a value that loses a fault on the 27 retimed seed 5 takes (00 to 08 at 15, 10 and 5 fps, a 2 s
squat at 30 fps, and a 1.5 s squat at 30 and 15 fps): the retimed 24-of-24 bar (`sweep.RETIMED_TOPS`,
`tests/test_retimed.py`, ruling of 03:45Z). Without that bar the sweep would choose `upper_arm_out` 13 and
`min_fraction` 0.43, which lose a retimed fault at 5 fps. The bar is why the body floor is not 32: with 32 for every
measure the retimed rows found 24, 24, 24, 23, 9 and 11 of 24 (12 of 21 faulty 1.5 s squats scored A, the #59
symptom); with the split every row finds 24.

Seed 5 at good light (precision, recall, faults on correct takes): front 0.96, 0.96, 0; 45 1.00, 1.00, 0; side 0.88,
0.96, 0; every correct good-light take scores an A (12 of 12). Reported costs, measured before this freeze and never used
to choose: seed 5 good/side precision 0.88 (0.96 with a floor of 32 for every measure), so seed 67's good/side
precision is the likeliest red against the 0.85 bar; low light worse (low/front P 0.66, low/45 0.42 with 3 faults on
correct takes, low/side 0.18 with 14), from noise in the dance's short first rep under the lower body floor; stock real
takes P 0.125 (fp 7, was 5). The foot measures are attempt 3's (`foot_rotation` 14, `ankle_inversion` 14), so seed
37's far-foot `ankle_inversion` failure may recur; that belongs to TICKET-040's family.

Reviews before this freeze: `progress/review-20261101-prefreeze-attempt4.md` (B1 to B4), its recheck (N1, N2) and the
delta recheck (`progress/review-20261101-prefreeze-attempt4-delta.md`, APPROVED). Known limit (ruling of 01:40Z,
residual 4): a scored seed of this series is checked against its own detection line before analysis and must
reproduce its recorded numbers after; a deliberate revert of rules.json to a retired attempt's bytes under later code
is not caught by the line alone. Seed 67 is generated once with feet (`make heldout-data SEED=67`) after this record
and scored once (`make check-5`). Green: confirm on seed 71. Red: published here, and the run ends DEGRADED with these
numbers.

Held-out result as measured (`make check-5` at `21b1d29`, 2026-11-01T02:55Z: the check exited 1, which make reports as
2): **failed**, 3 criteria. good/side has 1 fault on a correct take: `exercise_side_good_00_correct`, `ankle_inversion`
right `more` 22.4 degrees, the far foot in a side view (the failure mode of seed 37, which this family left to TICKET-040);
the same take and its dropout copy score 84 (B) where a correct good-light take must be an A. Precision and recall pass at
every gated angle (front 1.00 and 1.00, 45 0.91 and 0.88, side 0.96 and 0.96). Score report (reported, not gated): good/0
A 18, B 2 (target missed); good/1 A 14, B 70, C 16 (target missed); good/2 D 10 (target met).

| slice | gated | tp | fp | fn | takes | correct takes | faults on correct takes | precision | recall | refused |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dropout/45 | no | 42 | 22 | 6 | 52 | 8 | 3 | 0.66 | 0.88 | 0 |
| dropout/side | no | 43 | 74 | 5 | 52 | 8 | 15 | 0.37 | 0.90 | 0 |
| good/45 | yes | 21 | 2 | 3 | 26 | 4 | 0 | 0.91 | 0.88 | 0 |
| good/front | yes | 24 | 0 | 0 | 26 | 4 | 0 | 1.00 | 1.00 | 0 |
| good/side | yes | 23 | 1 | 1 | 26 | 4 | 1 | 0.96 | 0.96 | 0 |
| low/45 | no | 21 | 24 | 3 | 26 | 4 | 5 | 0.47 | 0.88 | 0 |
| low/front | no | 24 | 12 | 0 | 26 | 4 | 1 | 0.67 | 1.00 | 0 |
| low/side | no | 20 | 79 | 4 | 26 | 4 | 14 | 0.20 | 0.83 | 0 |

Seed 67 is retired: never rescored, regenerated or used to tune, and the rules are not reverted. Not tuned on seed 67
before or after. The next unused seed of the second series is 71 (ADR-0017).

## Score

`simon.score.v1` (ADR-0007, `docs/specs/journey-followup.md` J-4). Params live under `score` in `part5/rules.json`,
calibrated on seed 5 only by `python -m part5.calibrate --set fixtures/input/followers --score`; `part5/score.py`
computes the score and `part5/score_report.py` reports and sweeps it.

| param | value | rule |
| --- | ---: | --- |
| z0 | 0.289 | 95th percentile of the correct good-light takes' mean z |
| z1 | 0.732 | the worst seed 5 take's mean z |
| s_max | 4.0 | similarity costs at most 4 points |
| base | 16 | the smallest counted fault (r = 1, shortest run, full coverage) costs more than 10 points |
| slope | 5.9 | the worst single good-light fault still lands at 70 or above with the full similarity cost |
| cap | 31.1 | `base + slope * (r - 1)` at that worst fault's r |

AC-S01: the calibration reproduces the research prototype exactly (`z0 0.289`, `z1 0.732`, `s_max 4.0`,
`base 16`, `slope 5.9`, `cap 31.1`); there is no difference to explain. Seed 5 and the current held-out set
(seed 31) reproduce the prototype's per-slice grade tables.

### Freeze check for the detection rules
`make check-5` compares the detection rules, not the whole file: `part5/rules.json` without its `score` key,
serialised with `json.dumps(rules, sort_keys=True, separators=(",", ":"))`, hashed with sha256. The value
below was computed the same way from the file of attempt 4 after the recheck of its pre-freeze review (TICKET-044,
ADR-0017: the floor split by measure class, `default.min_frames_floor_body` 8, and the persistence constants
`default.reference_fps` and `default.floor_share` now keys of the rules, with `knee_flexion` 10 and `upper_arm_out` 11
from the re-sweep below); the file of the pre-freeze review fixes (`default.min_frames_floor` 32, it was 8) hashed to
`c53a751e...`, the file frozen at `fb1d6e8` for attempt 3 (the foot thresholds added) to `e340940f...`, and the one frozen
at `fbb0bea` for attempts 1 and 2 to `b76e6ca3...`:

```
python3 -c 'import json,hashlib; d={k:v for k,v in json.load(open("part5/rules.json")).items() if k!="score"}; print(hashlib.sha256(json.dumps(d,sort_keys=True,separators=(",",":")).encode()).hexdigest())'
```

detection_sha256: `0a559e183adad714e4ce0a6f2f03a5aba9a51bc1ed26daae4cf25e6cdd15d345`

Re-recorded for attempt 4: the score params are unchanged (`params_sha256` as recorded in `fixtures/score-heldout.json`;
ADR-0017 leaves them alone). Re-frozen at attempt 3 (2026-10-31): the held-out score report on seeds 47 and 53 below was
measured under the earlier detection rules (`b76e6ca3...`), and the cost of a foot fault in the score was never measured
on a held-out score seed; attempt 4 moves the dance takes' scores too (a rep-by-rep take is scored window by window), which
no held-out score seed has seen.

The recheck of the pre-freeze review changed `part5/rules.json` (three new keys in `default`, two thresholds), so
`rules_sha256` is now `077affcf0a3104356558cedf79a57eaf499fd2cb36637a92078adf23ddbd3534` (it was `7df9a020...` after
the pre-freeze fixes) and the detection hash above moved with it. This hash is the current freeze only. Each attempt
section above carries the `detection_sha256` of its own freeze, and `make check-5` judges a seed that is already scored by
its own line alone (pre-freeze review B3), so a retired seed is never analysed again under later rules; for a scored
seed of the second series (67, 71, 73) that line is required (recheck residual 4). Known limit (stakeholder-proxy ruling):
the line hashes the detection rules, not the code, so a deliberate revert of rules.json to a retired attempt's bytes
under later code is not caught by it; the guard is the check after analysis that the recorded numbers are reproduced
(`require_unchanged_scores`), and there is no code-diff requirement on `part5/`.

Changing any detection key changes this hash and `make check-5` exits 2.

### Gate and report
`make check-5` gates, in addition to the precision and recall gate: every correct (no labelled fault) good-light
take of the held-out set scores A, and the score never rises as `foot_out` right (0 to 28 degrees, steps of 4),
`arms_wider` both (0 to 35, steps of 5) and `trunk_lean` centre (0 to 30, steps of 5) grow, built on the
exercise clip with `random.Random(1234)`. Everything else is reported under `report.score` (held-out, seed 5,
kit, stock): low light is never graded against a target.

### Held-out score report
Seeds 47 and 53, each generated once after the score freeze commit `0aab25b` and scored once, params unchanged
(`params_sha256` `e818635bb46b7062f57e335f2940edd35d01835edaaaffed9339fdbfb79eaa62`). Generator:
`python3 scripts/make_dummy_followers.py --seed <n> --out <temp dir>/seed-<n> --dropout-variant`, scorer
`python -m part5.score_report --set <temp dir>/seed-<n>`. `labels.json` sha256: seed 47
`083adc3f44466e666a039116747c3213b50457096c941373c64d1dfa1e8b3ddd`, seed 53
`8edc5c111daef68230d81bcc37e683126bcac9c18c0892327450d12e6b8f164a`. Machine record: `fixtures/score-heldout.json`.

| slice (light/labelled faults) | seed 47 | seed 53 |
| --- | --- | --- |
| good/0 | A 20 | A 20 |
| good/1 | A 1, B 36, C 23 | A 2, B 40, C 18 |
| good/2 | D 6, F 4 | D 8, F 2 |
| low/0 | A 11, B 3, C 4, D 2 | A 10, B 3, C 2, D 4, F 1 |
| low/1 | A 3, B 23, C 12, D 10, F 12 | A 6, B 21, C 8, D 17, F 8 |
| low/2 | D 1, F 9 | D 4, F 6 |

Targets, as measured: correct good-light takes all A: pass on both. Double faults D or F: pass on both. Single
faults B or C: fail on both. The A takes among good-light single faults are faults the detector did not find (seed
47: `dance_side_good_07_knee_caving-right_dropout`; seed 53: `dance_45_good_04_knees_shallow-both` and its
dropout copy), so the cause is detection recall, which the score does not hide. Low light is reported, not graded.
The monotonic sweep passes in `make check-5`. No param changed after the freeze.

## The floor split and the retimed takes (recheck N2, attempt 4)

Stakeholder-proxy ruling (confidence medium): "the floor splits by measure class before the freeze; foot measures keep 32
frames at 30 fps (a duration, at most 0.75 of a rep); body measures get their own floor of the same form, re-swept on seed
5 within the values that keep the 27 retimed seed 5 takes at attempt 3's 24 of 24 in every row (the 00:05Z selection rule
inside that range, 8 if nothing higher qualifies), pinned by a test, one delta recheck; if seed 5's gate-shaped criteria
fail in that range or the delta is not merged and approved by 2026-11-01T20:00Z, freeze as it stands under (a) with the
fast-rep limit recorded and pinned by a test."

The retimed takes are derived from seed 5 by `tests/retimed.py` (a generator, nothing committed as data): the 27 good-light
exercise takes 00 to 08, 24 planted faults per row. Labelled faults found per row (`scripts/retimed_floor.py`, 24 is
all), the number of example frames in brackets:

| rows | 15 fps (46) | 10 fps (31) | 5 fps (16) | 2 s squat, 30 fps (61) | 1.5 s squat, 30 fps (46) | 1.5 s squat, 15 fps (23) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pre-freeze review fixes (floor 32 for every measure) | 24 | 24 | 24 | 23 | 9 | 11 |
| **the split, body floor 8** (every value 4 to 20 gives the same) | 24 | 24 | 24 | 24 | 24 | 24 |
| body floor 24 | 24 | 24 | 24 | 24 | 23 | 24 |
| body floor 28 | 24 | 24 | 24 | 24 | 20 | 19 |

**The qualifying range of the body floor** (every row at 24 of 24, the other keys at their shipped values) is 4 to 20 on the
step-4 grid (4, 8, 12, 16, 20); 24 and above lose a fault in the 1.5 s squat at 30 fps. Inside it the sweep is **flat** on
seed 5: good light reads the same at every value (front 0.96/0.96/0, 45 1.00/1.00/0, side 0.88/0.96/0), so the flat rule
keeps the starting value, **8** (attempt 3's floor; the ruling's "8 if nothing higher qualifies" and the plateau rule give the
same answer, 8 is strictly inside the plateau 4 to 20 too). The floor binds below the share only in a rep under 21 frames at
30 fps, which seed 5 has none of, and the dance's 43 frame rep needs `min_fraction` of itself (16 frames) at any floor up
to 16: that is why seed 5 cannot tell 4 from 16 apart. The foot floor stays 32 (held, not swept). The seed 5 gate-shaped
criteria hold at good light: precision 0.85 or more and 0 faults on correct takes at every angle, recall 0.75 or more, and
all 12 correct takes an A (below).

**The re-sweep under the split moved two thresholds and tried to move a third key.** The sweep is sequential from the rules
in force (`docs/specs/calibration.md`), and with the body floor at 8 instead of 32 the plateaus of the earlier keys moved.
First pass from the split rules (log `progress/calibrate-seed5-attempt4-split-pass1.log`; only the floor was capped, no
threshold yet): `knee_flexion` 9 to 10
(plateau 9 to 11, 9 was at its end), `upper_arm_out` 10 to 13 (plateau 10 to 15, 10 was at its end). `upper_arm_out` 13 loses
one arms_wider fault of the 10 fps and the 5 fps rows (23 of 24), and 12 loses one of the 5 fps row, which the ruling's bar
(24 of 24 in every row) does not allow; so the bar applies to the keys the sweep moves as it does to the floor, and
`sweep.RETIMED_TOPS` caps `upper_arm_out` at 11 and `min_fraction` at 0.38 (second pass,
`progress/calibrate-seed5-attempt4-split-pass2.log`: `upper_arm_out` 11, the middle of its capped plateau 10 to 11, and
`min_fraction` wanted 0.43, which loses one fault of the 5 fps row). Third pass (this table, from `knee_flexion` 10 and
`upper_arm_out` 11): every key keeps its value, a fixed point. `min_fraction` 0.38 is the top of its qualifying range
(0.18 to 0.38) and a one-value plateau there. This is a consequence of the amended selection rule on new rules, never a
threshold nudge to a held-out seed (it is a change of calibration on seed 5 before any attempt 4 seed, calibration.md).

Seed 5, before (the pre-freeze review fixes, `c1dcda1`, floor 32) and after (every slice, P / R / faults on correct takes):

| slice | before | after |
| --- | --- | --- |
| good/front | 1.00 / 0.96 / 0 | 0.96 / 0.96 / 0 |
| good/45 | 1.00 / 1.00 / 0 | 1.00 / 1.00 / 0 |
| good/side | 0.96 / 0.96 / 0 | 0.88 / 0.96 / 0 |
| low/front (reported) | 0.79 / 0.96 / 1 | 0.66 / 0.96 / 1 |
| low/45 (reported) | 0.54 / 0.88 / 1 | 0.42 / 0.92 / 3 |
| low/side (reported) | 0.30 / 0.71 / 6 | 0.18 / 0.67 / 14 |

Correct good-light takes: A 12 of 12 before and after. Score targets (reported): correct takes all A pass, single faults
B or C fail (A 6, B 46, C 8; before A 6, B 45, C 9), double faults D or F pass (D 5, F 1; before D 6). The cost of the lower
body floor is false positives in the dance's short first rep, mostly in low light (reported, never gated). The fault list
of a good-light take moves in three takes only: `dance_front_good_04_knees_shallow-both` reports its knees as `left` and
`right` rather than `right` alone (one more false positive, good/front 1.00 to 0.96), and `upper_arm_out` right appears in
the first rep of `dance_side_good_09_foot_turned_out-both` and `dance_side_good_11_ankle_rolled_in-right` (two more, good/side
0.96 to 0.88; the third, `forearm_out` right in `dance_side_good_08`, was there before). The margin at good/side is 0.88
against the 0.85 bar, thinner than before (0.96); with the thresholds as they were before the re-sweep (9 and 10) it was
0.85, to the digit.

`fixtures/profiles-fitness-baseline.json` is taken again: 119 of the 156 hashes move (27 good-light and 39 low-light dance
takes, 15 and 38 exercise takes). What moves is mostly the near-miss `needed_frames` of every take that reads the body
floor (the analysis is hashed whole), the two re-swept thresholds, and the window rule of
N1 (a rep's two-sided fault stays in its window when the take reports either side of it), which moves the score of
`dance_front_low_04_knees_shallow-both` (90 to 73) and `dance_side_good_08_arms_wider-both+foot_out-left` (63 to 57)
together with the floor.

## Repetitions

Constants of `part5/reps.py` and `part5/repwise.py` (ADR-0010), fixed from seed 5 and the documented real takes
(`fixtures/input/real/lateral-raise/`, the stock squat), never from the held-out seeds. The guard limits and the
detection rules above are not changed.

| constant | value | why |
| --- | ---: | --- |
| `MIN_PROMINENCE` | 0.35 of the range | a turn must stand out; the real lateral raises cut at 3, 8 and 2 reps |
| `MIN_REP_S` | 0.6 s | the fastest real rep is 1.2 s |
| `SMOOTH_S` | 0.25 s | removes pose jitter before the turning points |
| `MIN_RANGE_DEG` | 15 | a measure that moves less has no repetitions |
| `PREFER_SHARE` | 0.5 | the follower cuts on the expected clip's measure when it moves it half as much as its best |
| `MIN_REP_SPAN_SHARE` | 0.6 | a rep passes only when the matched span covers most of it |
| `MIN_FAULT_SHARE` | 0.5 | a fault counts when found in half of the accepted reps |

Real lateral raise against the trainer (3 reps), whole clip then rep by rep, frozen guard limits:

| follower | whole clip `timing_corr` | reps passed | rep residual | rep `timing_corr` |
| --- | ---: | ---: | --- | --- |
| 40297504 (8 reps, 1.3 s) | 0.53 | 8 of 8 | 0.35 to 0.45 | 0.94 to 0.98 |
| 8836968 (2 reps, 7.7 s) | 0.50 | 2 of 2 | 0.35 to 0.43 | 0.96 to 0.97 |

The synthetic dance clips are periodic (54 of the 108 seed 5 followers, and the expected dance, have two cycles of
the arm measure). Until attempt 4 a pair was compared rep by rep only after the whole-clip guard refused it; since
attempt 4 (ADR-0017, `docs/specs/rep-persistence.md`) an example of two or more reps is always compared rep by rep, so
every dance take is, each follower rep against the example rep that matches it (the dance example's reps are 43 and 61
frames). Different movements stay refused: the stock squat, Part 2's dance, class, single and stretch against the
trainer, and the squat against the dance, class and stretch.

## Profiles

`part5/profiles.json` (docs/specs/profiles.md, ADR-0016) holds the `dance`, `rehab` and `fitness` profiles. **Every
value in it is set by hand.** Nothing was tuned on any seed; the numbers are round multipliers a person chose
(position thresholds 1.5 times for rehab, 1.25 times with a 15% longer and 2 frames longer persistence for dance, range
thresholds unchanged, dance tempo 40 points per 1.0 of ratio outside 0.85 to 1.15, at most 20 per window). `fitness`
is the identity, is what `make check-5` runs, and changes nothing: `rules.json`, `rules_sha256` and `detection_sha256`
are as they were, and `fixtures/profiles-fitness-baseline.json` holds the hash of the fitness analysis of every one of
the 156 seed 5 takes from before the wiring (`tests/test_profiles.py::test_fitness_matches_the_prefeature_baseline`).
Changing a value after reading the numbers below needs an ADR-0016 amendment: this report is not a tuning loop.

The numbers below are the per-profile precision and recall on seed 5 (`make report-profiles`, 156 takes, written
to `out/report-profiles/report.json`), recorded once as measured. They have no target and no gate, and no held-out seed
was run under a profile. Good light, the clean takes, labelled faults found over labelled:

| fault type (kind) | fitness | dance | rehab |
| --- | ---: | ---: | ---: |
| `arms_wider`, `elbow_bent`, `knees_shallow` (range) | 25 of 25 | 25 of 25 | 25 of 25 |
| `foot_out`, `trunk_lean` (position) | 17 of 17 | 17 of 17 | 17 of 17 |
| `knee_caving` (position) | 6 of 6 | 5 of 6 | 5 of 6 |
| `foot_turned_out`, `foot_turned_in` (position, foot points) | 11 of 12 | 1 of 12 | 1 of 12 |
| `ankle_rolled_in`, `ankle_rolled_out` (position, foot points) | 10 of 12 | 3 of 12 | 3 of 12 |

Per slice, precision then recall (good light is the gated light for `fitness`; low light is reported):

| slice | fitness | dance | rehab |
| --- | --- | --- | --- |
| good/front | 1.00, 0.96 | 1.00, 0.67 | 1.00, 0.67 |
| good/45 | 1.00, 1.00 | 1.00, 0.71 | 1.00, 0.71 |
| good/side | 1.00, 0.92 | 1.00, 0.75 | 1.00, 0.75 |
| low/front | 0.83, 1.00 | 0.96, 0.92 | 0.96, 0.92 |
| low/45 | 0.54, 0.92 | 0.67, 0.67 | 0.67, 0.67 |
| low/side | 0.23, 0.58 | 0.34, 0.54 | 0.29, 0.46 |

Faults reported over the 156 takes: 201 for `fitness`, 136 for `dance` and 136 for `rehab`; none of them is a fault
`fitness` did not report (`uncovered` is 0, which `tests/test_profiles.py` also proves on these takes and on Part 3's
kit). Faults on correct takes over all slices: 10, 5 and 5; none in good light. Grades on good-light takes by labelled
faults (A/B/C/D): 0 faults, all A in every profile; 1 fault, `fitness` 3/49/8/0, `dance` 21/31/8/0, `rehab` 21/34/5/0; 2
faults, `fitness` and `dance` D 6, `rehab` C 1 and D 5. A profile's thresholds move the score (`r` and the similarity
term) and dance charges tempo, so **a score is read within its profile**. One analysis takes 0.035 s on average
(0.06 s at most) under every profile. The expectation written in the spec before the run was that the position
types `foot_out`, `knee_caving` and `trunk_lean` would lose recall; as measured, every planted `foot_out` and
`trunk_lean` is still past even 1.5 times its threshold and is kept, `knee_caving` loses one take, and the loss is in
the four foot-point types, whose 14 degree thresholds become 17.5 degrees for dance and 21 for rehab against planted
faults of 15 to 25 degrees.

Re-run at attempt 4 (TICKET-044, ADR-0017), `make report-profiles` exit 0, no profile value touched: every dance take is
now compared rep by rep and `min_frames_floor` is 32, so the numbers moved (the baseline file was taken again, once; the
numbers above stay as the first recording). Good light, precision then recall: front `fitness` 1.00, 0.96, `dance` 1.00,
0.75, `rehab` 1.00, 0.67; 45 0.96, 1.00 and 1.00, 0.71 for both; side 0.92, 0.96, `dance` 1.00, 0.79, `rehab` 1.00, 0.71.
Low light: front 0.77, 0.96 / 0.96, 0.92 / 0.95, 0.88; 45 0.54, 0.88 / 0.68, 0.71 / 0.67, 0.67; side 0.30, 0.71 / 0.37, 0.58 /
0.34, 0.54. Faults reported over the 156 takes: 199, 140 and 134; faults a profile reports that `fitness` does not: 0 for
both. Faults on correct takes in good light: 0 in all three profiles.

Re-run at the pre-freeze review of attempt 4 (`make report-profiles` exit 0, no profile value touched; a fault on both sides is
now reported once in rep mode, B2, so the baseline file was taken again for 4 dance takes): good light, precision then recall,
changed from the paragraph above: `fitness` 45 1.00, 1.00 and side 0.96, 0.96 (the other good-light cells are as above). Low
light changed: `fitness` front 0.79, 0.96; `dance` side 0.38, 0.58; `rehab` side 0.35, 0.54. Faults reported over the 156 takes:
195, 139 and 133; faults a profile reports that `fitness` does not: 0 for both. Faults on correct takes in good light: 0 in all
three profiles.

Re-run at the recheck (`make report-profiles` exit 0, no profile value touched; the floor is split by measure class, `knee_flexion`
and `upper_arm_out` were re-swept to 10 and 11, a rep's two-sided fault stays in its window; the baseline file was taken
again, 119 of 156 hashes), good light, precision then recall: front `fitness` 0.96, 0.96, `dance` 0.95, 0.75, `rehab` 0.94,
0.71; 45 1.00, 1.00 / 1.00, 0.71 / 1.00, 0.71; side 0.88, 0.96 / 0.90, 0.79 / 0.90, 0.75. Low light: front 0.66, 0.96 /
0.76, 0.92 / 0.76, 0.92; 45 0.42, 0.92 / 0.55, 0.75 / 0.53, 0.71; side 0.18, 0.67 / 0.25, 0.54 / 0.25, 0.54. Faults reported
over the 156 takes: 248, 172 and 168; faults a profile reports that `fitness` does not: 0 for both. Faults on correct takes in
good light: 0 in all three profiles. Grades on good-light takes by labelled faults: 0 faults, all A in every profile; 1 fault
(A/B/C/D), `fitness` 6/46/8/0, `dance` 21/29/10/0, `rehab` 24/31/5/0; 2 faults, `fitness` D 5 and F 1, `dance` D 6, `rehab` C 1
and D 5.
