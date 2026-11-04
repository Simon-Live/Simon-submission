# Spec: measures that do not jump a turn where their branch cut falls (TICKET-094)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Implemented
Date: 2026-11-02
Request Type: bug-fix (a measure, no output field)
Risk Level: medium
Ticket: TICKET-094. ADR: none (a measure that reads the same wherever it did not wrap; ADR-0017 set the precedent with `_sideways`).
Master spec: `part5-fault-analysis.md`. Used by: every caller of `measures.compute` (alignment, visibility, score, calibration,
the Ask tools); a range or span built on `upper_arm_forward` reads the unwrapped series.

## Overview
`upper_arm_forward` read -297.6 on a REHAB24 rep where an arm passed overhead (the hub's diagnosis, TICKET-094): the angle comes
from `arctan2`, whose branch cut lies at straight up, and the cut was added to the trunk lean after the fact. The same cut sits
under `thigh_forward` (a leg raised to vertical), `trunk_lean_forward` (a trunk folded flat) and `head_forward` (a head
hanging in that fold). `part5/measures.py` now passes those four through `_continuous`: a step of more than half a turn
between two frames is closed (the frames after it move a whole turn), and the whole clip is then put on the branch whose
window of 360 degrees holds its median. A clip with no such step and a median inside the window is returned bit for bit, so
every take the check reads is unchanged.

## Why This Is Wrong (Dissent-First)
1. **A fixed window per frame is the simplest cut, and a real clip crosses it.** The first version put every frame in a window
   with its edges in the middle of the angles a shoulder cannot hold (-128 to 232). It had no state and could not give a clip
   a turn of offset. Run over the 447 committed clips it changed three series, all in Part 2's `mismatch/part2-stretch`, and
   it made that clip's right arm worse: that arm lowers from overhead through the back, so its path runs from -181 to -38 and
   crosses -128, where the old cut at 180 never touched it (old: 0 steps over 300 degrees, window: 3). No place for a cut is
   safe from a path that goes the other way round. So the series is closed along time, which has no cut to cross.
2. **Closing along time alone leaves the branch to the first frame.** A follower and a reference that start on opposite sides
   of the cut would then differ by a whole turn for the whole clip, and every difference, range and span built on them would be
   wrong. The median of the clip decides the branch instead, by one rule for both clips, and it only fails when a clip's
   median sits at an angle a body cannot hold.
3. **Closing along time can drift.** A single-frame spike over half a turn closes and reopens (a step and its return are both
   corrected, so the clip comes back to its branch); a flip that does not return carries the rest of the clip a turn away.
   That needs a step of more than 180 degrees in one frame (6000 degrees a second at 30 fps) and was not found in any of the
   committed clips. It is listed under Limits; it is no worse than the cut it replaces, which makes that jump every time.

## Limits (stated, not fixed here)
- **The frontal plane is not a branch cut.** `upper_arm_forward` and `thigh_forward` read the segment's angle in the sagittal
  plane. A segment lying in the frontal plane (an arm out to the side, a lateral raise) has almost no length there, so its
  angle is set by noise and can take any value. This lane makes the series continuous; it does not make that reading mean
  anything. A range or span built on such a measure inherits the noise.
- **A real movement across a run of lost frames can read as a wrap (R5 of the 1.14.1 review).** The steps are judged between the
  frames that have a value, however many frames lie between them. An arm that really moved from -70 to 170 degrees (240
  degrees) over 20 lost frames is closed as a wrap and read as a move of 120 degrees the other way (`upper_arm_forward` 290
  then 170): a step over half a turn is taken for the cut whatever the time it took. The gate below changed no series of the
  447 committed clips but the two of `mismatch/part2-stretch`, so none of the rest shows it; `part5/measures.py` is not changed for it, and
  `test_limit_a_real_movement_over_half_a_turn_across_lost_frames_reads_as_a_wrap` pins today's reading so a change to it is
  decided, not made by accident.
- **A series a whole turn wide is read frame by frame (1.14.4).** No joint turns 360 degrees, so a series whose unwrapped span
  reaches a whole turn holds a tracking glitch that was closed as a wrap: a trainer's arm flung 170 degrees behind the trunk for
  three frames moved the 250 frames before it by a turn (`upper_arm_forward` up to 462 degrees), its reps were lost (13 became
  1), and 21 follower reps aligned against the whole 1,800-frame clip passed `MAX_CELLS`, so long dance follows were refused.
  Such a series now has each value brought into the window by whole turns on its own, so the glitch stays in its own frames.
  A series under a whole turn is unwrapped as before, bit for bit (the 447 committed clips included).
- **A false wrap under a whole turn is not caught.** The whole-turn gate sees only a span of 360 degrees or more; a false wrap whose
  unwrapped span stays under it (100 to 175, then -110 to -30, reads 100 to 330) is unwrapped as before.
- **Poses estimated impossibly.** A median inside the unreachable arc of a measure (an upper arm held 120 degrees behind the
  body, say) is put on the other branch. No committed clip does that.

## Audit: every `arctan2` in `part5/measures.py`
| Measure (function) | Where its cut falls | Reached by a body? | Decision |
| --- | --- | --- | --- |
| `trunk_lean_forward` (`_sagittal(spine)`) | spine straight down | yes: a standing forward fold, hinge 180 or more | `_continuous`, window [-125, 235) |
| `head_forward` (`_sagittal(head)` minus the trunk) | head straight down | yes: the head hanging in that fold | `_continuous`, window [-180, 180) |
| `{side}_upper_arm_forward` (`_forward_from_down` plus the trunk) | arm straight up | yes: overhead, the ticket | `_continuous`, window [-120, 240) |
| `{side}_thigh_forward` (`_forward_from_down`) | thigh straight up | yes: a kick, a straight leg raise, a standing split | `_continuous`, window [-125, 235) |
| `trunk_lean_side` (`_sideways`) | none: `arctan2(x, hypot(y, z))` | no | unchanged (ADR-0017) |
| `shoulder_tilt` | none: `arctan2(y, hypot(x, z))` | no | unchanged |
| `{side}_knee_valgus` (`_knee_valgus`) | none: the divisor is a length | no | unchanged |
| `{side}_foot_rotation` (`_foot_rotation`) | NaN unless the foot is within 90 degrees of the pelvis's forward | no | unchanged |
| `{side}_ankle_inversion` (`_ankle_inversion`) | NaN unless world up is on the sole's side | no | unchanged |
| `neck_lean_side` (`_lateral(neck)`, a view measure) | neck horizontal in the frontal plane | not by a seated take | unchanged, listed: timing and the guard only, never a reported fault (ADR-0011); `test_ac_sl_04` pins its wrap |
| `head_turn`, `shoulder_turn` (`_yaw`, view) | facing away | no | unchanged, listed |
| `head_pitch`, `neck_lean_forward` (view) | nose behind the ears, neck straight down | no | unchanged, listed |
| `{side}_wrist_height`, `{side}_wrist_out` (view) | none | no | unchanged |
| the elbow and knee flexions | `arccos`, 0 to 180 | no | unchanged |

The four windows sit in the middle of the angles each part cannot hold, so a median is never near an edge: the shoulder
reaches about -60 to 180 against the trunk and the window opens at -120 (60 degrees each side); the thigh and the trunk about
-90 to 200 and the window opens at -125 (35 each side); the head against the trunk about -90 to 90 and its window is the
signed difference, -180 to 180.

## Acceptance Criteria
### AC-BC-01: an arm raised from down through overhead and back reads its flexion without a jump
Given an upright, leaning (30) or level (90) trunk with one upper arm raised 0 to 210 degrees from the trunk's down direction in
one degree steps and back, on each side, When the measures are computed, Then `{side}_upper_arm_forward` equals the flexion at
every frame and no step is over one degree. The same raise read with the old formula jumps over 300 degrees (the control).
### AC-BC-02: an arm one degree either side of the old cut reads two degrees apart
Given the arm at 179 and at 181 degrees of flexion, at each of the three leans, Then the two readings differ by 2 degrees.
### AC-BC-03: a follower and a reference cannot differ by a whole turn
Given a reference that drifts across the old cut from below and a follower that drifts across it from above, Then each reads
its own flexion and they differ by at most the drift. A clip is moved by whole turns until its median is in the window of its
measure, the same clip a turn apart comes back identical, and a wrap inside a clip is closed whichever way the arm crosses it.
### AC-BC-04: a clip with no wrap is as it was, bit for bit
Given a series with no step over half a turn and a median in the window (NaN frames and a negative zero among them), Then it comes
back with the same bytes. Given seed 5's takes, the expected clips and the held-out takes the check reads, Then the four measures
equal the old formulas exactly (`array_equal`).
### AC-BC-05: the one real clip with an arm past vertical
Given `fixtures/input/mismatch/part2-stretch/skeleton.json`, Then none of the four measures has a step over 100 degrees, while the
old formulas had one over 300 in `left_upper_arm_forward` and `head_forward`.
### AC-BC-06: the other measures
Given a thigh raised from -80 to 200 degrees, a trunk hinged from -60 to 200, and a head swung 90 back to 120 forward of a trunk
folded 170, Then each reads its angle without a jump (the old formulas jump over 300). Given random bodies, Then shoulder_tilt,
trunk_lean_side, the four out angles and the knee valgus stay within 90 degrees and the flexions within 0 to 180.
### AC-BC-07: gaps and edges
Given an elbow lost for ten frames across the old cut, Then those frames are NaN and the others still read their flexion. An
all-NaN series, an empty one and a one-frame one come back as they are or on the branch of the window.

## Error Cases
None: `compute` raises nothing it did not, and a NaN stays NaN.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|----------|------------|--------|-------------|
| Compatibility | `make check-5` stdout and every detection hash unchanged | byte-identical, seed 5 and the held-out seed 73 | gate below |
| Compatibility | `analysis.json` and its schema | no field, no version change | none needed |
| Performance | One pass over a clip, no loop over frames | numpy only; AC-BC-01 reads 421 frames a case | AC-BC-01 |
| Reliability | Deterministic | no state, no random | AC-BC-04 |

## Negative Requirements
- MUST NOT change `part5/rules.json`. Why: every detection hash and the freeze records stay valid.
- MUST NOT read, generate or score any held-out seed. Why: ADR-0003, ADR-0017.
- MUST NOT touch the foot measures or the view measures. Why: their NaN guards already bound them, and TICKET-040 owns the feet.

## Non-Requirements
- A measure that means something for an arm in the frontal plane: a different definition, so a family of its own under the held-out protocol.

## Assumptions
ASM-002 is not touched (no seed is scored).

## The gate (recorded when the commit was made)
- Over the 447 committed clips under `fixtures/input` (9834 series, every body measure): 9832 are identical to the bit; two
  differ, both in `mismatch/part2-stretch` (`left_upper_arm_forward` 3 frames, `head_forward` 9 frames; its right arm,
  which the old cut never crossed, is unchanged).
- `make check-5` (`uv run python -m part5.check`), run once on a clean copy of the parent commit 72f53e2 and once on a clean copy
  of the implementing commit 251c4ed (neither run on the working tree, so a later edit could not touch it), each under
  `/tmp/simon5-heavy.sh`: both exit 0, both print 137011 bytes of stdout with the sha256
  `0e46f4f979e479b175fd97f47bfdc82f708ae69a164a79379a81c03aa33aef8e`, and `cmp` finds them identical. stderr is identical
  apart from the lines uv prints when it makes the copy's virtual environment. `out/check-5/takes.json` (416 takes: the 156 of
  seed 5 and the 260 of the held-out seed 73), `metrics.json` and `sweep/` are identical too. `rules.json` is untouched, so
  `rules_sha256` `23da0c7291eb4b4a27e4d8de6a3b44c2d18c7cd1de30270c52d9e6ade76b4a7b` and `detection_sha256`
  `c92ae9a8524c559741cdaebcd14bb5305e91479d19123e15c3a5e14efb1337fb` are the ones the freeze records name.
- Targeted tests on the same copy: 493 passed (this file, `test_measures`, `test_guard`, `test_real`, `test_calibrate`,
  `test_align`, `test_visibility`, `test_design_copies`) and 310 passed (`test_profiles`, `test_profiles_wiring`,
  `test_near_misses`, `test_score_v2`, which hold the seed 5 fitness baseline hashes).
- Why the take set cannot move: no committed take holds an arm past vertical, which is also why the gate cannot show the fix.
  The constructed raise (AC-BC-01) and the real stretch clip (AC-BC-05) show it; the bit-for-bit comparison above and AC-BC-04
  show nothing else changed.

## Delivery Verification Plan
- `uv run pytest tests/test_measure_branch_cuts.py tests/test_measures.py` exit 0 (230 tests).
- Targeted: `tests/test_guard.py tests/test_real.py tests/test_calibrate.py tests/test_align.py tests/test_visibility.py`.
- `make check-5`: stdout byte-identical to the parent commit's, exit 0; `rules_sha256` and `detection_sha256` the same.
- Not run in this lane: `make test`, the published-tree test (the host runs the 1.14.0 round).

### Device/Platform Strategy
Not applicable: no UI change.

### Data
The committed fixtures only. No held-out seed is generated or scored.

### Ratchet Initialization Plan
Not applicable.

## Dissent Review
### Concern 1: unwrapping a series makes a measure depend on the whole clip
Kept: `compute` already takes the whole clip and every caller passes one (alignment, visibility, score, calibration, the Ask
tools). A clip cut into pieces and computed piece by piece could land on another branch for a piece whose median differs; no
caller does that.
### Concern 2: the gate is the byte-identity of the take set, which holds no arm past vertical
Kept, and said so: seed 5 and the held-out takes hold no overhead arm (TICKET-094's own words). The constructed raise and the
real stretch clip are the evidence that the wrap is closed; the byte-identity is the evidence that nothing else moved.

## Files (every new or changed source file; the write gate reads this table)
| File | Part | Published |
| --- | --- | --- |
| `part5/measures.py` (`WINDOW_LOW`, `_continuous`; `trunk_lean_forward`, `head_forward`, `{side}_upper_arm_forward`, `{side}_thigh_forward`) | measures | yes |
| `tests/test_measure_branch_cuts.py` | tests | yes |

## Deviations from PRD
None.
