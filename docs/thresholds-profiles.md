# Thresholds: the profiles record

Moved out of `docs/thresholds.md` unchanged, because that file went past the 800 line limit (TICKET-054 R11). The
section below is the former "Profiles" section of `docs/thresholds.md`, word for word. No held-out seed was run under a
profile, so no held-out record is here and none was touched.

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
