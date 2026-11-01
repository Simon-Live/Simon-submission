# Score v3 (`simon.score.v3`, ADR-0019, TICKET-060): the seed 5 record, the real takes and the proofs

Split out of `docs/thresholds.md`, whose "Score v3" section holds the params, their hash and the floor table. Everything
here is measured on seed 5 or on throwaway copies of the tree (never committed) and the three real takes, read once, read-only.

Seed 5, score per slice (reported, as measured; no claim is made on seed 5):

| slice | v1 | v2 | v3 |
| --- | --- | --- | --- |
| good/0 (12 takes) | min 100: A 12 | min 100: A 12 | min 100: A 12 |
| good/1 (60) | min 73, median 83: A 6, B 46, C 8 | min 75, median 87.5: A 1, B 54, C 5 | min 75, median 87.5: A 1, B 53, C 6 |
| good/2 (6) | min 57, median 62.5: D 5, F 1 | min 64, median 71: C 4, D 2 | min 64, median 71: C 4, D 2 |
| low/0 (12) | min 55, median 92.5: A 6, B 2, C 2, D 1, F 1 | min 65, median 93: A 6, B 2, C 3, D 1 | min 65, median 92.5: A 6, B 1, C 4, D 1 |
| low/1 (60) | min 30, median 77.5: A 13, B 13, C 14, D 8, F 12 | min 45, median 82.5: A 9, B 24, C 15, D 9, F 3 | min 45, median 80.5: A 9, B 21, C 18, D 9, F 3 |
| low/2 (6) | min 38, median 54.5: D 2, F 4 | min 52, median 64: C 2, D 2, F 2 | min 52, median 64: C 2, D 2, F 2 |

The one good/1 take graded A under v2 and v3 reports no fault (`exercise_front_good_12_ankle_rolled_out-both`, a missed foot fault).
v3 differs from v2 on seed 5 by the 79 ceiling alone, and on good-light takes it lowers one: `dance_side_good_09_foot_turned_out-both`
reports two faults and goes from 83 B to 79 C (it is not judged by targets 4 and 5, its reported faults differ from its label).
ADR-0018's five targets on seed 5 under v3: 1 pass (12 takes), 2 the sweep never rises (pass), 3 no take that reports a fault
grades A (pass, 65 takes), 4 single faults B or C (pass, 56 takes that report exactly their fault), 5 double faults C, D or F
(pass, 5 takes). Not judged by 4 and 5, listed with their grades: `dance_front_good_04_knees_shallow-both` 76 C (two reported, one
labelled), `exercise_front_good_12_ankle_rolled_out-both` 100 A (nothing reported), `dance_side_good_09_foot_turned_out-both` 79 C
(two reported, one labelled), `dance_side_good_11_ankle_rolled_in-right` 89 B (a different fault reported),
`dance_side_good_08_arms_wider-both+foot_out-left` 64 D (three reported, two labelled). Strict slice verdicts (every take of the
slice): good/0 pass, good/1 fail (the one A), good/2 pass. Targets 3 and 5 hold by construction (ADR-0019); what is published beside
them, as measured: of the 5 exactly reported doubles the 79 ceiling lowered 0 (values before and after it: 75, 72, 71, 71, 67; the
highest is `exercise_front_good_08_arms_wider-both+elbow_bent-right`, 75 before and after), and under ADR-0007's reading (D or F) 1 of
the 5 grades D or F and 4 grade C. Seed 5 therefore cannot show what the ceiling does; seed 61 can.

The sweep (`foot_out` right, `arms_wider` both, `trunk_lean` center; score by fault size in degrees), v1, v2, v3:

| fault | v1 | v2 | v3 |
| --- | --- | --- | --- |
| foot_out right (0 to 28, step 4) | 100 100 100 86 83 81 79 77 | 100 100 100 89 87 86 84 83 | 100 100 100 89 87 86 84 83 |
| arms_wider both (0 to 35, step 5) | 100 100 100 85 83 81 78 76 | 100 100 100 89 87 85 84 82 | 100 100 100 89 87 85 84 82 |
| trunk_lean center (0 to 30, step 5) | 100 100 87 84 81 78 76 | 100 100 89 88 86 84 82 | 100 100 89 88 86 84 82 |

Worst good-light take that reports exactly its one labelled fault: 73 under v1, 75 under v2 and v3 (ADR-0007's rule of 70 or
above holds). Highest exactly reported good-light double: 67 under v1, 75 under v2, and 75 under v3 both before and after the 79
ceiling. Cost: every `score` block changes (version, `params_sha256`, the ceiling), so all 156 hashes of
`fixtures/profiles-fitness-baseline.json` were taken again and the goldens were regenerated; schema 1.11.0.

Real takes, read read-only and never tuned on (reported, not used to choose anything; the knee raises are Part 7's two stock-clip
jobs and the third is the moalborati/simon#59 Romanian deadlift at `8d820a8`, all scored by reference).

Disclosure (pre-freeze review R8, ADR-0019 "Calibration"): the ruling (Q3) has these takes read once after the freeze. This first
reading was made at `70d1a40`, at the end of the lane and before any freeze was recorded. No parameter could have moved on it:
`range_floor` is the output of ADR-0018's rule on seed 5 (it reads nothing else), the ceilings 89 and 79 are ruled, and all three
values below equal v2's. The reading after the freeze is a repeat and is published as one, not as a first look.

| take | faults | v1 | v2 | v3 |
| --- | --- | --- | --- | --- |
| knee raise, job 64225b97a879 | 2 (`upper_arm_forward` less, `knee_flexion` more) | 45 F | 53 F | 53 F (`fault_cap` 79, not lowered) |
| knee raise, job 1028ae59e0e2 | 5 (`elbow_flexion`, `upper_arm_out`, `knee_flexion`, `trunk_lean_side`, `shoulder_tilt`) | 25 F | 40 F | 40 F (`fault_cap` 79, not lowered) |
| deadlift, moalborati/simon#59 | 1 (`trunk_lean_forward` less) | 93 A | 89 B (`fault_cap` 89, `uncapped` 93 A) | 89 B (`fault_cap` 89, `uncapped` 93 A) |

v3 changes none of the three against v2: the deadlift reports one fault, so its ceiling is v2's 89, and the two knee raises report
two and five faults, so their ceiling is 79, but they sit at 53 and 40 under it. The two knee raises stay F, for the reason v2's
section gives (most of their misses are on measures the trainer moves a lot, and each rep window carries two to five misses); a
window cost ceiling or a gentler `base` is not in v3 (ruling Q3) and stays with TICKET-053. A reading that tempted a change
is reported here and not made: none did.

Going back to v1 from a v3 tree is the same command as from a v2 tree (`make score-fallback`; `scripts/make_score_fallback.py`
accepts a tree that ships v2 or v3 and removes both samples). Proof after the pre-freeze review batch, on throwaway copies of the
lane head (`git archive`, never committed; the code is that of `45fb6d4`, the later commits being records):
- Copy I, whose `fixtures/score-heldout.json` held the simulated v3 freeze and a simulated seed 61 attempt with `holds` false:
  `make score-fallback` exit 0 printed that `part5/rules.json` ships `simon.score.v1` (the `v1` block, `e818635b...`), removed the
  two v3 samples and wrote the goldens and the fitness baseline again; the rules file is byte-identical to main's, the goldens equal
  main's v1 goldens but for `schema_version`; `make test` exit 0 (5428 passed, 38 skipped: the v2 and v3-only tests);
  `make check-5-contract` exit 0; `make check-5` exit 0 on seed 73 with its document byte-identical to main's own run, the score
  lookup finding `e818635b...` for the v1 block while the v2 and v3 freezes and the failed seed 61 attempt were in the record. (The
  first run of this proof, at `9d9ecc0`, failed one test: the check-5-level scenario of review R1 built a v3 attempt on a v1 tree. It
  was marked `capped_only` in `45fb6d4` and the proof was run again from scratch; the line above is the second run.)
- Copy H (at `9d9ecc0`), which ships v3 with the simulated v3 freeze and a simulated seed 61 attempt with `holds` true and the
  shipped hash (v3 stays): `make test` exit 0 (5469 passed, 17 skipped); `make check-5` exit 0 on seed 73. The commits after it
  change only a decorator on a test that skips under v1.
So the version-aware tests survive a recorded seed 61 attempt either way. On the lane tree itself `make test` exit 0 (5482 passed,
4 skipped, at `45fb6d4`) and `make check-5-contract` exit 0.

`make check-5` on a throwaway copy of the lane head at `9d9ecc0` with the simulated v3 freeze and no attempt (its `part5`,
`scripts`, `contracts` and `fixtures` are those of `45fb6d4`; never committed) exited 0 on seed 73,
against main's own run of the same set (an archive of main, exit 0): the three detection lines of the summary, `gate` (metrics,
slices, failures, thresholds, passed), `attempts`, `tuning`, `report.low_light`, `report.dropout`, `report.refusals`, the faults of
every kit and stock take, `detection_sha256` and `profiles_sha256` are byte-identical; what differs is the score and what carries it
(`gate.sweep`, `report.score`, the `score` of each kit and stock take, and `rules_sha256`, the hash of the whole file). Without a v3
freeze record `make check-5` exits 2 ("no frozen score params ... for simon.score.v3"), as `make score-heldout SEED=61` does.

The v3 freeze (`freezes` in `fixtures/score-heldout.json`: `{version: simon.score.v3, freeze_commit, params_sha256, seed: 61}`) and
the result of seed 61 are recorded here by the orchestrator, as v2's were, under "v3 freeze record" and "v3 held-out result: seed 61".
Seed 59 is retired (recorded, v2 failed it). `make score-heldout SEED=61` refuses until one v3 freeze exists whose hash is the shipped
block's, the whole tree is clean (no uncommitted change, no untracked file anywhere) and the code is the freeze commit's (`part5`,
`scripts`, `contracts`, `fixtures/input/expected`, `fixtures/input/expected-feet`, `pyproject.toml`, `uv.lock`, `Makefile`), refuses a
second freeze, an existing `out/score-heldout/seed-61/` and any other unrecorded seed while v3 ships, and prints `scored_at`, `holds`
and the exact line to append to `attempts`, with `version` `simon.score.v3` and the measures published beside the targets. `make
check-5` refuses a record with two v3 freezes and a block whose hash differs from the recorded attempt's `params_sha256`. Seed 61 is
scored from one named checkout and its attempt line is committed at once (the directory check is per checkout).

## v3 freeze record
Freeze commit: `59918a1574c7b22e8a2abfdbe69c97c7497fb286`
params_sha256: `4261f8d7630d2787425a55959ca49eda7a2ddc47ff6e3d5a61e63084ac285f07`
Date: 2026-11-01
Approach family: simon.score.v3 (ADR-0019): v2's range weight (`range_floor` 0.75 from ADR-0018's unchanged rule re-run on seed 5,
`range_full` 3) and its 89 ceiling for a take that reports one fault, and a ceiling of 79 for a take whose `faults` list holds two
or more entries, applied once to the mean of the windows and written in `score.fault_cap`.

Rationale. The operator ruling on moalborati/simon#61 (2026-11-01T13:20Z) and the stakeholder-proxy rulings of 13:35Z and 15:50Z
(STATUS.md Decisions). Reviewed before the freeze: `progress/review-20261101-prefreeze-score-v3.md` (NEEDS_WORK on B1, R1 to R13
fixed; recheck APPROVED). `part5/rules.json` is unchanged since 70d1a40, the commit at which the three real takes were first read
(blob `b13c6bea40e149f25f06ceeaa2ee717a77806f0d`, params sha `4261f8d7`): no parameter could move on that read, and the read after
the freeze is a repeat of it. The freeze commit is lane/score-v3 merged into main; seed 61 is generated and scored once after this
record by `make score-heldout SEED=61` from the main checkout, and its attempt line is committed at once. v3 ships only if all five
targets hold (`holds` true); otherwise `make score-fallback` puts `score.v1` back and the result is published.

## v3 held-out result: seed 61
Held-out result as measured (`make score-heldout SEED=61` at `7d92b59644c3ffb163f11fff949c0d4edce48a80`, 2026-11-01T16:01Z, exit 0;
labels.json sha256 `bc59d2084708d32517707507657ba0348156a6adae0055e8d7e65d0424ae8b4c`): **passed**, all five targets hold
(`holds` true). `make check-5` at the freeze record `7d92b59` exited 0 on seed 73 with every detection field equal to the last run
(gate metrics, slices, failures, thresholds, tuning, low light, dropout, refusals, the kit and stock faults, `detection_sha256`,
`profiles_sha256`); only `attempts` differs, by the recorded fields TICKET-058 added. v3 ships; seed 61, the last reserved score
seed, is retired.

| slice | n | min | median | max | grades |
| --- | ---: | ---: | ---: | ---: | --- |
| good/0 | 20 | 100 | 100.0 | 100 | A 20 |
| good/1 | 60 | 73 | 86.0 | 89 | B 52, C 8 |
| good/2 | 10 | 63 | 69.5 | 77 | C 5, D 5 |
| low/0 | 20 | 72 | 85.5 | 100 | A 8, B 4, C 8 |
| low/1 | 60 | 23 | 79.0 | 100 | A 1, B 26, C 19, D 8, F 6 |
| low/2 | 10 | 21 | 66.0 | 70 | C 2, D 4, F 4 |

ADR-0018 targets on the good-light takes: 1 correct takes all A, pass (n 20); 2 the sweep never rises, pass; 3 no take that
reports a fault grades A, pass (n 70); 4 single faults B or C (reported exactly), pass (n 57); 5 double faults C, D or F
(reported exactly), pass (n 10). Not judged by 4 and 5 (reported faults differ from the labels), 3: the knees_shallow takes
`dance_front_good_04` (79 C), `dance_45_good_04` (74 C) and its dropout copy (79 C). Published beside the targets: the 79 ceiling
lowered 0 of the 10 exactly reported doubles (values before it 63 to 77, the same after it); ADR-0007's reading of the doubles (D
or F) holds for 5 of 10, 5 grade C; the strict slice verdicts pass for good/0, good/1 and good/2. What the seed shows: targets 2,
3 and 5 were settled before it (ADR-0019, pre-freeze review corrections); targets 1 and 4 held on it; the doubles stayed at C or
lower through the range weight, not the ceiling, which did no work on this seed.

## Real takes, read after the freeze (repeat of 70d1a40)
The reading the stakeholder-proxy ruling (15:50Z) asked for after the freeze, made once per take on 2026-11-01 with the shipped
`simon.score.v3` (`part5/rules.json` blob `b13c6bea`, `params_sha256` `4261f8d7`, byte-identical to the file at 70d1a40 and at the
freeze `59918a1`; tree `lane/v3-after` on `236826b`). Read-only: `python -m part5 analyse` with the expected clip and the follower
skeleton by reference, no feet files, the default fitness profile and template phrasing, written to a scratch directory and never
beside the inputs. The knee raises are Part 7's two stock-clip jobs of check run `20261031T214443Z` (`app/jobs/<id>/work/expected.json`
and `follower/follower.json`); the deadlift is moalborati/simon#59's `docs/evidence/2026-10-31-follow-scored-100/expected.json` and
`follower.json` at `8d820a8`, fetched into a new empty directory. This is a repeat of the reading in the table above, published as
one; nothing was chosen or tuned on it.

| take | faults | value | grade | `fault_cap` | `uncapped` | the 70d1a40 v3 column |
| --- | --- | ---: | --- | ---: | --- | --- |
| knee raise, job 64225b97a879 | 2 (`upper_arm_forward`, `knee_flexion`) | 53 | F | 79 | absent (the ceiling did not lower it) | 53 F, `fault_cap` 79, not lowered |
| knee raise, job 1028ae59e0e2 | 5 (`elbow_flexion`, `upper_arm_out`, `knee_flexion`, `trunk_lean_side`, `shoulder_tilt`) | 40 | F | 79 | absent (the ceiling did not lower it) | 40 F, `fault_cap` 79, not lowered |
| deadlift, moalborati/simon#59 | 1 (`trunk_lean_forward`) | 89 | B | 89 | 93 A | 89 B, `fault_cap` 89, `uncapped` 93 A |

Every value, grade, `fault_cap` and `uncapped` equals the 70d1a40 reading, the faults named are the same, and none of the three
documents carries a warning or `capped_by`. Nothing differs, so nothing else changes: the reading is a record and moved no number,
rule or parameter.
