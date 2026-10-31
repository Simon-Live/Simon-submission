# Thresholds and guard limits

Written by `python -m part5.calibrate --set fixtures/input/followers --write-thresholds` from the
seed 5 tuning set only. Held-out numbers were not used to tune any value here (ADR-0003).

Expected clips: Part 4 commit dc3d9f2e70a0d3e95efb60bea1e5ab7fc307d284 (`fixtures/input/expected/SOURCE.md`).

## Chosen values (seed 5)

| key | before | plateau | grid | chosen | the sweep row that chose it (good light, minimum recall) |
| --- | ---: | --- | --- | ---: | --- |
| elbow_flexion threshold_deg | 12 | 16 to 23 | 1 to 24 | 20 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 0.94/1.00/0 |
| knee_flexion threshold_deg | 10 | 6 to 11 | 4 to 16 | 9 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 0.94/1.00/0 |
| upper_arm_out threshold_deg | 9 | 7 to 12 | 3 to 15 | 10 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 0.89/1.00/0 |
| forearm_out threshold_deg | 12 | 9 to 24 | 1 to 24 | 17 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 0.94/1.00/0 (plateau still reaches the grid edge after one extension) |
| thigh_out threshold_deg | 8 | 6 to 20 | 1 to 20 | 13 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 0.94/1.00/0 (plateau still reaches the grid edge after one extension) |
| foot_out threshold_deg | 6 | 3 to 9 | 1 to 12 | 6 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 0.94/1.00/0 |
| knee_valgus threshold_deg | 8 | 5 to 12 | 2 to 14 | 9 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 1.00/1.00/0 |
| upper_arm_forward threshold_deg | 15 | 9 to 21 | 9 to 21 | 15 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 1.00/1.00/0 (flat on seed 5, current value kept) |
| thigh_forward threshold_deg | 15 | 9 to 21 | 9 to 21 | 15 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 1.00/1.00/0 (flat on seed 5, current value kept) |
| trunk_lean_forward threshold_deg | 9 | 3 to 14 | 1 to 21 | 9 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 1.00/1.00/0 |
| trunk_lean_side threshold_deg | 9 | 3 to 15 | 3 to 15 | 9 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 1.00/1.00/0 (flat on seed 5, current value kept) |
| shoulder_tilt threshold_deg | 9 | 3 to 15 | 3 to 15 | 9 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 1.00/1.00/0 (flat on seed 5, current value kept) |
| head_forward threshold_deg | 18 | 12 to 24 | 12 to 24 | 18 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 1.00/1.00/0 (flat on seed 5, current value kept) |
| min_fraction | 0.38 | 0.33 to 0.38 | 0.23 to 0.53 | 0.38 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 1.00/1.00/0 |
| min_run_frames | 4 | 1 to 7 | 1 to 7 | 4 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 1.00/1.00/0 (flat on seed 5, current value kept) |
| min_overlap | 0.3 | 0.1 to 0.6 | 0.1 to 0.6 | 0.3 | min recall 1.00; front 1.00/1.00/0  45 1.00/1.00/0  side 1.00/1.00/0 (flat on seed 5, current value kept) |

## Guard limits

| limit | value | matched | mismatch |
| --- | ---: | --- | --- |
| max_residual | 0.5677 | max 0.5231 | min 0.6122 |
| min_timing_corr | 0.8336 | min 0.9110 | max 0.7562 |

- Excluded from the mismatch population: part2-single (provisional barbell back squat, pose3d.json sha256 433ae2edfe61b7e5c027f06ccdea289df34741225829f45fb5a652bb5147d857): Part 2's committed single is the provisional squat, not the seated stretch its input names, so it is a matched squat pair; it counts as a mismatch once Part 2 publishes the stretch and this entry is changed to mismatch
- Overlap, takes named: none

## Seed 5 per-slice table at the chosen values

| slice | tp | fp | fn | precision | recall | faults on correct takes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| good/45 | 16 | 0 | 0 | 1.00 | 1.00 | 0 |
| good/front | 16 | 0 | 0 | 1.00 | 1.00 | 0 |
| good/side | 16 | 0 | 0 | 1.00 | 1.00 | 0 |
| low/45 | 15 | 6 | 1 | 0.71 | 0.94 | 1 |
| low/front | 16 | 1 | 0 | 0.94 | 1.00 | 0 |
| low/side | 12 | 27 | 4 | 0.31 | 0.75 | 7 |

Recall by fault type, set and lighting:

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
- knee_caving dance good: 3/3
- knee_caving dance low: 3/3
- knee_caving exercise good: 3/3
- knee_caving exercise low: 3/3
- knees_shallow dance good: 3/3
- knees_shallow dance low: 1/3
- knees_shallow exercise good: 3/3
- knees_shallow exercise low: 3/3
- trunk_lean dance good: 4/4
- trunk_lean dance low: 5/5
- trunk_lean exercise good: 4/4
- trunk_lean exercise low: 5/5

<!-- attempts:begin -->
## Held-out attempts

One section per attempt, in seed order (29, then 31, then 37). Nothing below this line is generated or
rewritten by `calibrate`, and a red attempt is never removed. Each section's heading names the seed and
carries these lines, which `make check-5` reads for the current attempt (`part5/check.py`). The template below is
a list, not a copy-and-paste block, so that no line of it starts with a line label and a search for a recorded hash
prints real values only. In a real section each label starts its own line and the value follows it in backticks (the
hashes and the commit) or as plain words:

- the heading, `### Attempt <n>: seed <seed>`
- the label `Freeze commit:`, then the sha of the commit that froze rules.json and the code
- the label `rules_sha256:`, then the sha256 of part5/rules.json at the freeze commit
- the label `Date:`, then the date the seed was generated
- the label `Approach family:`, then the family, different from every earlier attempt's

then a one-paragraph rationale, and after scoring the held-out table as measured, pass or fail.

### Attempt 1: seed 29
Freeze commit: `fbb0bea78decfc7cf0e0d48e756e3021ea5d8616`
rules_sha256: `60f2e60b4bd60cea890ddbbce63c9d03ff82ff18f49e6284cb3cd48ff9aa62a4`
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

Seed 31 is the current held-out set (`fixtures/input/heldout/`). Seed 37 is unused; no further
attempt is needed while the gate stays green.

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
below was computed the same way from the file frozen at `fbb0bea` (the whole-file hash `60f2e60b...` of the
attempts above still passes on its own):

```
git show fbb0bea:part5/rules.json | python3 -c 'import json,sys,hashlib; d={k:v for k,v in json.load(sys.stdin).items() if k!="score"}; print(hashlib.sha256(json.dumps(d,sort_keys=True,separators=(",",":")).encode()).hexdigest())'
```

detection_sha256: `b76e6ca378557910a75f5f2ecedbab80452d4b3c0d87cae328b9f5c79967da6a`

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
the arm measure), so a pair is compared rep by rep only after the whole-clip guard refuses it. Different movements
stay refused: the stock squat, Part 2's dance, class, single and stretch against the trainer, and the squat against
the dance, class and stretch.
