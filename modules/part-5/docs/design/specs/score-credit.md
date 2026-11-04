# Spec: score.credit, the DDR-style credit display (analysis 1.13.0)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-11-02
Linked PRD: none (moalborati/simon#61, issuecomment-6567178466 and, for the grade scale, issuecomment-6569445776;
stakeholder-proxy ruling of 2026-11-02T01:58Z)
Linked CRD: none
Request Type: new-feature
Risk Level: low
Master spec: `part5-fault-analysis.md` (the score). ADRs: Part 5's ADR-0020 (this change; not the firm's ADR-0020 on QA
recipes), ADR-0013 (the windows), ADR-0012 (the warning cap), ADR-0019 (the score). Tickets: TICKET-078; TICKET-108 (the take's last second, 1.14.2). Companion specs:
`score-v3.md`, `integration-contract.md`.

## Overview
Every analysis document from schema 1.13.0 carries `score.credit`: a percent and a points total earned, per measure and frame,
by how close the follower stayed to the example, at three levels, with one entry for each compared window of
`score.timeline`. It sits beside `score.value` and changes nothing about it. It is reported only: it sets no score grade, cap
or gate, nothing in Part 5 reads it, and detection, the score, the insights and the phrasing are byte-identical to the
commit before it.

The choice behind it, as the team reported it on #61: the team chose per-frame credit on every compared measure ("DDR"),
1 point within half the tolerance, 0.6 within it, 0.2 within twice it and 0 beyond, shown as a percentage or as points (100
per measure per second, so a longer routine has a higher maximum), the viewer choosing which. the team built the block on the
branch `score-credit` (commit 7181813); Part 5 merged it with that commit kept, reviewed it, and made the fixes listed under
"Review" as commits of its own. the team then put the credit's letters on their own scale (8f135ee, the team's ruling as
the team reported it on #61, issuecomment-6569445776), which Part 5 merged as it is. Part 7 owns the display.

## Why This Is Wrong (Dissent-First)
1. **A second letter can contradict the first.** A correct take slowed to a quarter of the speed gets `low_match`, a score of
   59 and grade F, and a credit of 82.7 percent, grade B on the credit's own scale. Answer: the stakeholder-proxy kept the credit grade. It is
   informational everywhere it is described, it ignores warnings and caps, and a reader that shows both must say which
   letter is which (AC-CR-06).
2. **It is not calibrated.** No held-out seed was scored, no target is set, and `make check-5` does not read it. the team's
   figures (41 dance takes: a median of 53 percent where the score's median is 10, a rank correlation of 0.75 to the score)
   are theirs, taken from #61; Part 5 has not reproduced them. Answer: ruled reported only, with no held-out seed.
3. **The half-window rule is Part 5's reading.** A measure counts in a window only when it is finite in at least half the
   window's frames (`CREDIT_MIN_SEEN`, 0.5). #61 does not say this. It decides which measures are counted in a window, so
   it moves `max_points`. Answer: kept as the team wrote it, stated here as Part 5's reading, to confirm with the team.
4. **Through the whole pipeline, credit can rise by tenths as a fault grows.** The take is aligned to the example again at
   each size and a few frames land elsewhere. Answer: with the alignment held fixed it never rises (outside the take's last
   second, item 6); the pipeline rises are measured and pinned (AC-CR-08), and the alignment path is not changed.
5. **Points compare only between takes of one example.** They grow with the example's length and the measures seen.
   Answer: `percent` is the number to compare across takes, within one profile and one credit version.
6. **The last second makes AC-CR-08 false there (1.14.2, TICKET-108).** With the alignment fixed, a follower who follows the
   example's last move less and less loses credit until they hold still, and then earns that second in full: a bigger fault,
   more credit. Any rule that forgives a follower for stopping does this (review B2 of 1.14.2). Answer: the exception is named
   in AC-CR-08 and pinned. It stays in the last second, in the measures the example moved, and never earns more than those
   entries' full credit; the team's ruling that the end of a take should not cost credit (#38, moalborati/simon#61) is the
   reason it is accepted.

## User Story
As Part 7, I want a percent and a points total for how closely a follower stayed with the example, frame by frame, so that
the result can show them beside the score and the viewer can choose which to see.

### Jobs-to-be-Done
- Functional job: say how closely the take followed the example, measure by measure and moment by moment.
- Emotional job: reward staying with the example, the way a dance game credits each step.
- Social job: none.

## The block
`score.credit` is `null` when nothing was compared, else:

| Key | Meaning |
|---|---|
| `version` | `simon.credit.v1` |
| `percent`, `points`, `max_points` | at the level named by `tolerance` (`normal`); `percent = 100 * points / max_points`, to 0.1 |
| `grade` | the letter for `percent` on the credit's own scale, `grades` (S 95 and above, A 85, B 75, C 65, D 55, E 40, and F under 40). Informational: not `score.grade`, no cap, no gate, and it ignores warnings and caps |
| `tolerance` | the level the top-level numbers are shown at |
| `levels` | `easy`, `normal`, `hard`, each `{percent, points, max_points}` |
| `bands` | `[[0.5, 1.0], [1.0, 0.6], [2.0, 0.2]]`, the rule that earned them |
| `points_per_measure_second` | 100 |
| `grades` | `[[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [40, "E"], [0, "F"]]`, `[percent at least, letter]` from the highest, the scale `grade` is read on |
| `per_window` | one `{t_s, percent, points, max_points}` for each compared window of `score.timeline`, same `t_s`, same order, at the `normal` level |

### How a number is made
- **Windows.** The compared windows of `score.timeline` (ADR-0013): about 5 s of the follower for a take compared as a whole,
  one for each accepted rep when compared rep by rep. A window nothing could be scored in has no entry.
- **Measures.** The 22 body measures of `part5.measures.MEASURES`. The foot measures (`foot_rotation`, `ankle_inversion`) are
  compared and can be reported as faults but earn no credit. A measure counts in a window only when its z is finite in at
  least half the window's frames (`CREDIT_MIN_SEEN`); a frame where z is not finite is skipped and not counted.
- **Credit per measure and frame.** `z = |follower - expected| / threshold_deg` of that measure under the take's profile
  (`score.threshold_of`). By `z / tolerance`: at most 0.5 earns 1.0, at most 1 earns 0.6, at most 2 earns 0.2, beyond that 0.
  An edge belongs to its own band.
- **Levels.** `easy`: tolerance x1.5, points x0.75. `normal`: x1.0, x1.0. `hard`: x0.7, x1.5.
- **Points.** A frame lasts what it does on the example's own clock (`score.example_frame_s`: the example's first to last time
  over its frames less one; rep by rep, the rep's reference clip). `points = credit * frame_s * 100 * multiplier`, and
  `max_points` is the same with every counted credit 1. The same routine has the same `max_points` however fast the follower
  was, within one comparison basis (the whole take, or rep by rep) and with the same measures seen: a speed that moves the
  take from one basis to the other changes it, and so can a measure that is partly visible, because the half-window rule is
  applied to each window of the follower's clock (see "Retimed takes"). Without the example's clock (`compute_timeline` without `expected_times`) there is no credit.
- **Percent.** The take's points over its max points, summed over its compared windows, so a window weighs by its example
  frames and the measures counted in it.
- **Grade.** The first letter of `grades` that `percent` reaches: S 95 and above, A 85, B 75, C 65, D 55, E 40, and F under
  40 (`score.credit_grade`, `CREDIT_GRADES`; team, 3 Nov, was E 45 and F 30). The scale is the team's game scale, as the team
  reported the ruling on moalborati/simon#61 (issuecomment-6569445776) and wrote it in 8f135ee. It is not the score's bands,
  which stay A to F for `score.value`, and it changes no other number of the block or of the score.
- **Constants.** `CREDIT_*` in `part5/score.py`. They are not in `part5/rules.json`, whose `score` section stays frozen.
- **The take's last second (1.14.2, TICKET-108, ADR-0020 Amendment 1).** See the next section.

### The take's last second (1.14.2)
At the end of a take one person often stops before the other. Until 1.14.1 the credit scored that second like any other.
Staging take `b5acba462f16` (moalborati/simon-part-5-fault-analysis#38) lost 295 of its 600 lost points there, with no fault and a
score of 99: the trainer bent both elbows again while the follower held still.

The rule (`score.credit_tail`), read once per take: compared as a whole, on the take's expected frames; rep by rep, on the last
rep, and only when that rep was compared (an earlier rep never takes its place):
- **The tail** is the last `CREDIT_TAIL_S` (1.0 s) of the example's clock, `round(CREDIT_TAIL_S / frame_s)` expected frames,
  and never more than a third of the expected frames read (`CREDIT_TAIL_SHARE`).
- **The measures read** are those of `MEASURES` whose z is finite in at least half the tail's frames (`CREDIT_MIN_SEEN`).
- **Movement** is, per measure, the robust range (`reps.robust_range`, p95 minus p5) over the tail in that measure's
  thresholds: the example over the tail's frames, the follower over the frames the alignment pairs with them (`exp_to_fol`).
- **The follower holds still** when every measure read has a range of at most `CREDIT_HOLD` (0.5, the edge of the full-credit
  band). If not, nothing is forgiven.
- **When it does**, each measure read whose example range is at least `CREDIT_LEAVE` (1.0, one threshold) earns full credit
  (1.0 at every level) on every counted entry of the tail. The measures the example holds are scored as before.
- Nothing else changes: the same entries are counted, so `max_points` stays the routine's own, and every other entry earns
  what it did.

So a pose both hold (the example holds it, so it is never forgiven), wrong form while both move (the follower is not still) and
a follower who moves anything at all in the last second (review B1 of 1.14.2: a nod does not forgive an arm held wrong) are
scored as before, and a follower who stops early loses credit for everything before the last second. The other direction, a
follower who moves on after the example has stopped, is not this rule's: the alignment is open-ended, so the follower's frames
after the routine are not compared at all (`aligned_until_s`, CONTRACT.md); a #38 suggestion to forgive it too was dropped to
keep the exception to AC-CR-08 small. The rule cannot tell a forgotten last move from stopping early; it forgives at most one
second of either, in the measures the example moved. It reads the two clips and the alignment only, never the reported faults
(AC-CR-06 holds), and it does not read the match: on a low match the alignment can pair the example's last second with a few
follower frames, so the follower holds by construction and that second is forgiven, as #38's first suggestion asked.

On `b5acba462f16` the trainer bends both elbows again in its last second (about 122 to 45 degrees, 3.6 thresholds) while the
follower holds (at most 0.16 of a threshold): the six elbow and arm measures it moves earn that second in full, `shoulder_tilt`
(0.30) does not, and the credit reads 91.3 (A) where 1.14.1 read 82.9 (B), `max_points` 3500 in both. The other 305 lost points
are the 0.6 band in the first bend and hold, where the follower's elbow and forearm angles sat between half a threshold and one
threshold from the trainer's; they are credit working as designed and stay.

### Example (`fixtures/output/analysis.example.json`)
`score.value` 75, grade C; `credit`: `version` `simon.credit.v1`, `percent` 87.5, `grade` A, `points` 5841, `max_points`
6673, `tolerance` `normal`; `levels.easy` 92.2 with 4615 of 5005, `levels.hard` 81.2 with 8131 of 10010; `grades` the scale
above; `per_window` one entry, `t_s` `[0.1, 2.5]`. The other goldens' credit grades: `no-faults` 97.8, S; `fault-capped` 93.6,
A; `double-capped` 66.1, C.

### Retimed takes (measured)
`python3 scripts/make_score_credit_retime_noise.py --sets exercise dance` plays the 54 good-light, clean seed 5 exercise and dance
takes numbered 00 to 08 at 0.75, 0.5, 0.33 and 1.5 times the speed (30 fps), runs each through the whole pipeline against its
own example, and sets its credit beside the same take at normal speed (216 pairs, deterministic):
- Where the comparison basis (the whole take, or rep by rep) did not change, `max_points` is equal: 211 of 211 pairs. In 5
  pairs the basis changed (one dance take at 0.5 and at 0.33 times the speed, whole take to rep by rep; three dance takes at
  1.5 times, rep by rep to whole take) and `max_points` went between 8873 and 7627.
- Points do not scale with the follower's time. A slower take (162 pairs, 160 on one basis) earned more points than the
  original in 46 pairs, by at most 35 points (0.56 percent of the points), and fewer in 110, by up to 736 points (12.7 percent)
  at half speed and 1387 (23.9 percent) at a third of the speed. A faster take (1.5) earned more in 39 pairs, by up to 81
  points (1.28 percent), and fewer in 11, by up to 27. The falls were not traced further.
- The falls are not the clock's. `--mode stretch` keeps the follower file's own frames and scales their timestamps, where
  `retime` writes new frames at 30 fps; the pipeline resamples every follower to the example's frame rate
  (`part5/pipeline.py`) with either. Over the 27 exercise takes at half speed (`--sets exercise --speeds 0.5 --mode
  stretch`) `max_points` is equal in 27 of 27, and points are up in 6 by at most 24 (0.39 percent of the points) and down
  in 21 by at most 724 (12.5 percent), against 4 up by at most 14 and 23 down by at most 736 with `retime`.
- On the follower's clock (7181813) the same correct take, `exercise_front_good_00_correct`, went from 5525 points of 5647
  to 9826 of 10047 at half speed. That figure is `retimed.retime(follower, out, 0.5, 30)`, which resamples the clip at 30
  fps; this script prints it with `--speeds 0.5 --list` on a 7181813 tree, with the script and `tests/retimed.py` copied in.
  The first review's probe keeps the follower file's own frames and doubles every timestamp (`--mode stretch`; the pipeline
  resamples it to the example's frame rate like any follower); on the same tree it gave 9889 of 10120, the half-speed
  figure ADR-0020 quotes. Both doublings are what the bounds in `tests/test_score_credit_pins.py` refuse: over the 27
  exercise takes at half speed (`--speeds 0.5`: `max_points` equal in 27 of 27, points up in 4 by at most 14, down in 23 by
  at most 736), points may rise by at most 2 percent and move by at most 20 percent either way.

## Acceptance Criteria
### AC-CR-01: the block, additive
Given any analysis from 1.13.0, when it is written, then `score.credit` is an object or null, validates against
`contracts/analysis.schema.json` (one `$defs.credit_entry` for the levels and the per-window entries), and an earlier
document without it still validates. Tests: `tests/test_score_credit.py`, `tests/test_score_credit_history.py`.

### AC-CR-02: the bands
Given z / tolerance of 0.5, 1 and 2, then the credit is 1.0, 0.6 and 0.2; a hair above each it is the next band's, then 0; at
each level, for one entry and for a whole block. Tests: `tests/test_score_credit.py`, `tests/test_score_credit_pins.py`.

### AC-CR-03: points on the example's clock
Given the same routine followed at half, normal and double speed with the same measures off by the same amount, then `points`
and `max_points` are equal: points do not scale with the follower's clock. Through the pipeline a retimed take's points are
not the original's and move in both directions, but not by the clock; the falls were not traced further (measured under
"Retimed takes"). Given 100 points per measure per second, then
a 10 s example of 22 measures has `max_points` 22000 at normal, x0.75 at easy and x1.5 at hard. Tests:
`tests/test_score_credit_pins.py` (synthetic, and the 27 good-light clean seed 5 exercise takes at half speed through the
pipeline, with bounds that refuse points nearly doubling); measurement: `scripts/make_score_credit_retime_noise.py`.

### AC-CR-04: percent
Given two windows of different length, then the take's percent is its points over its max points, not the mean of the
windows' percents; in every golden each shown percent reads as its shown points over max points. Tests:
`tests/test_score_credit_pins.py`.

### AC-CR-05: null
Given a take that could not be aligned, no compared window, no measure counted, or no example clock, then `score.credit` is
null. Tests: `tests/test_score_credit.py`, `tests/test_score_credit_pins.py`.

### AC-CR-06: reported only
Given any take, then `score.value`, `grade`, `fault_cap`, `components` and `capped_by` are what they are without the credit;
replacing the credit block moves none of them; the 59 warning cap does not apply to the credit; the credit does not read the
reported faults. A slowed correct take shows 59 F beside a credit grade of B (82.7 percent on the credit's own scale).
Tests: `tests/test_score_credit_pins.py`, `tests/test_score_credit.py`.

### AC-CR-07: nothing frozen moves
Given the commit before the merge, then `make check-5` prints the same stdout (`cmp` exit 0), `rules_sha256`,
`detection_sha256` and `score.params_sha256` are the same, and on the 156 seed 5 takes and the 23 real takes every document
is identical beyond `score.credit` and `schema_version` (`scripts/score_credit_before_after.py`). Test:
`tests/test_score_credit_pins.py` (the constants are outside `rules.json`).

### AC-CR-08: credit as a fault grows
Given the alignment held fixed, then no measure's growing fault raises the credit at any level, in any window, with one
exception (1.14.2, TICKET-108, "Why This Is Wrong" 6): in the take's last second, a follower who follows the example's move
less and less loses credit until they hold still, and from that step earns the entries of the measures the example moved in
full. The rise is in the last second only, never above those entries' full credit, and every other entry is unchanged
(`tests/test_score_credit_tail.py`). Given the
whole pipeline on the score's sweep takes (foot out, arms wider and trunk lean on `random.Random(1234)`), then the credit
falls from no fault to the largest fault at every level, foot out and arms wider never raise it, and trunk lean raises the
percent at two steps only: 20 to 25 degrees at hard (92.7 to 92.8) and 25 to 30 degrees at normal (95.2 to 95.3) and hard
(92.8 to 93.0), each time the alignment moved. Tests: `tests/test_score_credit_pins.py`, `tests/test_score_credit_sweep.py`.

### AC-CR-09: the contract
Given `contracts/history-fields.json` 1.2.0, then every key of `score.credit` is listed from 1.13.0, every path of a golden
under it is listed or inside a listed container that names it, `CONTRACT.md` says it is reported only, and
`part5 doctor --for part7` accepts a 1.13.0 document. Tests: `tests/test_score_credit_history.py`,
`tests/test_contract_part7_history.py`.

### AC-CR-10: the validator and the goldens
Given a credit that is a string, a `levels` that is not an object of objects, a `per_window` that is not a list of objects, a
`per_window` that does not follow the compared timeline, or points above max points, then the document is refused with an
`OutputError`. The four goldens carry the block and rebuild byte for byte (`make check-5-contract`). Tests:
`tests/test_score_credit.py`, `tests/test_score_credit_pins.py`.

### AC-CR-11: the grade scale
Given a credit percent, then `grade` is the first letter of `grades` it reaches: 95 and above S, 94.9 A, 85 A, 75 B, 65 C, 55
D, 54.9 E, 45 E, 40 E, 39.9 F, 30 F and 0 F; every golden carries `grades` as `[[95, "S"], [85, "A"], [75, "B"], [65, "C"],
[55, "D"], [40, "E"], [0, "F"]]` and its grade is its percent's letter on it; the schema accepts S to F in `grade` and in
each `grades` entry and refuses any other letter; the score's own bands stay A to F. A document written before 1.14.3
carries `[45, "E"], [30, "F"]` and is read on it, so a percent of 40 to 44.9 is an F there and an E on the new scale; the
validator holds each document to its own `grades`. Tests:
`tests/test_score_credit.py` (the team), `tests/test_score_credit_pins.py`, `tests/test_score_credit_history.py`.

### AC-CR-12: the take's last second (1.14.2, TICKET-108)
Given the last second of a take where the follower holds still and the example moves away, then each measure the example moves
earns full credit on every counted entry of that second at every level, the measures the example holds are scored as before,
`max_points` and every other entry are unchanged, and `score.value`, the faults and the near misses are what they were (the same
with the rule on and off): staging take `b5acba462f16` (`tests/fixtures/staging-b5acba462f16/`) reads 91.3 where 1.14.1 read
82.9. Given a held wrong pose in the last second (both still), wrong form while both move, a follower who moves anything in the
last second (a nod beside an arm held wrong), or a follower who moves on while the example holds, then that second costs credit
as before. Given a follower who stops more than a second before the end while the example moves on, then only the last second
is forgiven. Given a take compared rep by rep, then only the last rep reads the rule, and the committed lateral raise is
unchanged by it. Given a take of under 3 s, then the tail is a third of it. Given a measure unseen in most of the tail, it is
not read. Tests: `tests/test_score_credit_tail.py`.

Measured reach (`scripts/score_credit_before_after.py dump`, run on 1.14.1's tree and on this one, 2026-11-03): the 156 seed 5
takes and the 23 committed real takes give byte-identical documents once the trees' paths are set aside, so neither TICKET-107
nor TICKET-108 moves any of them; the goldens rebuild byte for byte (`make check-5-contract`). A perfect copy of the regression
trainer reads 100.0; the same copy with its left wrist moved 0.15 m over the last second reads 96.9, the same with and without the
rule. Seed 5, the real takes and the goldens were measured under the first form of the rule (either side still); the form shipped
forgives a subset of what that one did, so they stay unchanged under it (`make check-5-contract` rebuilds the goldens).

## Error Cases
| Condition | Behavior | AC |
|---|---|---|
| `score.credit` is not an object or null | `OutputError`: `score.credit must be an object or null` | AC-CR-10 |
| `levels` or `per_window` misshapen | `OutputError`, naming the key | AC-CR-10 |
| `per_window` does not follow the compared windows | `OutputError`: one entry per compared window, at its `t_s` | AC-CR-10 |
| `points` above `max_points` | `OutputError` | AC-CR-10 |

## Edge Cases
- A take with a warning (`low_match`, `not_enough_visible`): the credit of what was compared is shown, uncapped. It can be
  high. Readers read `warnings` first; whether to hide or grey it is the team's (ADR-0020), and Part 7 owns the display.
- A measure the camera did not see arrives as NaN and drops out of the window.
- A take compared rep by rep: one window per accepted rep, each counted on its reference clip's clock; a rep that did not
  match is not compared and has no entry.
- A profile with other thresholds (`dance`, `rehab`): z uses that profile's thresholds, so a percent is read within its
  profile.
- A window where no measure is seen in half its frames: its `percent` is null in `per_window`.
- The take's last second, the follower still and the example moving away: full credit there for the measures the example
  moves (AC-CR-12). The first second is not read this way: #38 asked about the end of a take only.
- A low match: the rule does not read the match, so a last second the alignment pairs with a few follower frames can be
  forgiven (the follower holds by construction).
- Nothing in a 1.14.2 document says the rule was applied: `schema_version`, `simon.credit.v1` and `params_sha256` are those of
  1.14.1 (review R2 of 1.14.2). Trigger to revisit: the next schema version, which can echo the constants as `bands` is echoed.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | one pass over the aligned frames per window | no new loop over the clip | AC-CR-07 |
| Reliability | deterministic, offline | the goldens rebuild byte for byte | AC-CR-10 |
| Compatibility | additive | a 1.12.0 document still validates | AC-CR-01 |
| Security, Accessibility, Scalability | not applicable: a number in a JSON file, no UI, no endpoint | | |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT change `score.value`, `grade`, `components`, `fault_cap`, `uncapped` or `capped_by`. Why: reported only (01:58Z).
- MUST NOT be read by detection, the score, the insights or the phrasing. Why: byte-identical (AC-CR-07).
- MUST NOT apply the 59 warning cap. Why: left to the team (ADR-0020); the grade and percent say what was compared.
- MUST NOT be tuned on seed 5 or any held-out seed. Why: no held-out seed was ruled; the read on the committed takes is
  reported as measured in `progress/score-credit-integration.md`.
- MUST NOT touch the alignment path. Why: the pipeline rises of AC-CR-08 are recorded, not tuned away.

## Compromises
### Percent can rise by tenths through the pipeline
Short-term: recorded and pinned (AC-CR-08). Long-term: a ruling on strict monotonicity through the pipeline, which would need
the alignment to change.

### The half-window rule
Short-term: the team's rule kept, stated as Part 5's reading. Long-term: confirm with the team whether a measure seen in
under half of a window should count for it.

## Non-Requirements (Explicitly NOT Building)
- A display, the "Show score as" switch, or a hide rule for warned takes: Part 7.
- A deduction for misses (the replay script the team's ADR describes had one; it is not shipped).
- A held-out seed, a target, or a gate on the credit.
- The same rule for the first second of a take (getting into the pose). Trigger to revisit: a take whose credit is lost in its
  first second with no fault.

## Review (TICKET-078)
The independent review of 7181813 asked for the changes below; each is a Part 5 commit on top of the team's, whose commit is
kept as it is. The stakeholder-proxy ruled them. They are also in ADR-0020, "Part 5 review".
- The credit grade stays and is informational (AC-CR-06).
- Points use the example's clock (AC-CR-03).
- The sweep is pinned, with its rises (AC-CR-08).
- This spec, with the owner's choice and the team's 41-take figures cited as the team's.
- One `$defs.credit_entry` in the schema; the credit tests use `shipped_score.aligned`.
- A shape check before the credit validator; foot measures stated as earning none; the half-window rule stated as Part 5's
  reading.
- the team's 8f135ee merged as it is (the team's grade scale, S 95 to F 30, written as `grades`; AC-CR-11; from 1.14.3 E 40
  and F under 40, the team's 93a95db): the schema's one `$defs.credit_entry` keeps S, E and `grades`, the grade stays
  informational, and the shape check accepts them.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `docs/design/specs/score-credit.md` | this spec | TICKET-078 | yes |
| `docs/design/specs/score-credit.md`, `docs/design/README.md` | neutralised copy written by `make design-copies`, and its line in the index | TICKET-078 | yes |
| `docs/design/adr/ADR-0020-score-credit-ddr-display.md`, `docs/design/adr/ADR-0020-score-credit-ddr-display.md` | the team's ADR (the copy is theirs; the source is generated from it), with the review changes | TICKET-078 | yes |
| `part5/score.py` | the credit (the team), `example_frame_s`, points on the example's clock, the grade scale `CREDIT_GRADES` and `credit_grade` (the team, 8f135ee) | TICKET-078 | yes |
| `part5/score_report.py` | a rep's window carries its reference clock | TICKET-078 | yes |
| `part5/output.py` | `SCHEMA_VERSION` 1.13.0, `_check_credit_shape`, `_validate_credit`; the letters without jsonschema (review R8 of 1.13.0): `grade` one of S to F and the letter `percent` reaches on `grades`, and `grades` [percent at least, letter] pairs with the percents falling and the letters in the scale's order (`tests/test_score_credit_pins.py`) | TICKET-078 | yes |
| `part5/profiles_report.py`, `part5/contract.py` | the baseline digest leaves `score.credit` out; the analysis row, with the credit's grade scale | TICKET-078 | yes |
| `contracts/analysis.schema.json`, `contracts/history-fields.json` | version 1.13.0, `$defs.credit_entry`, S and E and `grades` (8f135ee); history 1.2.0 with `score.credit.grades`, and an `order` on each letter field (`score.grade` A to F; `score.credit.grade` and `score.credit.grades` S to F; review R3 of 1.13.0) | TICKET-078 | yes |
| `fixtures/output/analysis*.example.json` | regenerated by `make output-examples` | TICKET-078 | yes |
| `CONTRACT.md`, `docs/schemas.md` | the credit, reported only, and its grade scale | TICKET-078 | yes |
| `tests/test_score_credit.py` (the team), `tests/test_score_credit_pins.py`, `tests/test_score_credit_sweep.py`, `tests/test_score_credit_history.py` | AC-CR-01 to AC-CR-10 | TICKET-078 | yes |
| `tests/shipped_score.py` | `aligned(offset=)`, `degrees_off` (one helper for the credit tests, review N6) | TICKET-078 | yes |
| `tests/retimed.py`, `tests/test_retimed.py` | `labelled_take`, `retimed_inputs` (one labels lookup plus retime for the credit tests, review N6), `picked_takes(labels, sets)` (the one pick of takes, also read by the retime noise script), and their test | TICKET-078 | yes |
| `scripts/score_credit_before_after.py` | the before and after run of AC-CR-07 | TICKET-078 | no (firm) |
| `part5/score.py` | the take's last second: `credit_tail` (one mark per measure and frame), `_tail_ranges`, `CREDIT_TAIL_S`, `CREDIT_TAIL_SHARE`, `CREDIT_HOLD`, `CREDIT_LEAVE`; `credit_z` and `window_score` take the marks; `compute_timeline` reads them on the take | TICKET-108 | yes |
| `part5/score_report.py` | `_rep_timeline` reads the tail on the last rep's window | TICKET-108 | yes |
| `docs/design/adr/ADR-0020-score-credit-ddr-display.md` and its design copy | Amendment 1 | TICKET-108 | yes |
| `tests/test_score_credit_tail.py`, `tests/fixtures/staging-b5acba462f16/` | AC-CR-12 | TICKET-108 | yes |
| `part5/score.py`, `part5/contract.py`, `contracts/analysis.schema.json`, `contracts/history-fields.json`, `CONTRACT.md`, `docs/schemas.md` | the grade scale E 40 and F under 40 (the team, 93a95db); the history notes and `docs/schemas.md` say what a document written before carries | TICKET-109 | yes |
| `docs/design/specs/integration-contract.md` and its design copy | the Part 5 row of the compatibility table, as `part5 contract` prints it | TICKET-109 | yes (the copy) |
| `docs/design/adr/ADR-0020-score-credit-ddr-display.md` and its design copy | Amendment 2 | TICKET-109 | yes |
| `fixtures/output/analysis*.example.json`, `tests/test_quality_pins.py`; `fixtures/output/lang/analysis.{ar,es,hi}.json`, `fixtures/output/lang/PROVENANCE.md` | regenerated, four quality pins repinned (the team, 93a95db); the recorded translations' `grades` by hand | TICKET-109 | yes |
| `tests/test_score_credit.py`, `tests/test_score_credit_pins.py`, `tests/test_score_credit_history.py` | AC-CR-11 at the new edges (the team, 93a95db); a document written before 1.14.3 keeps its own letter | TICKET-109 | yes |
| `part5/__init__.py`, `pyproject.toml`, `uv.lock`, `tests/test_version.py`, `CHANGELOG.md` | the release 1.14.3 in the three places that name it, held equal by the test; the changelog | TICKET-109 | yes |
| `scripts/make_score_credit_retime_noise.py` | the retimed takes measurement of AC-CR-03 (`--mode retime`, the default, or `stretch`); named `scripts/score_credit_retime_noise.py` until review B2 of 1.13.0, renamed `make_*` so the published `tests/test_retimed.py` can load it | TICKET-078 | yes (`scripts/make_*.py`) |

## Delivery Verification Plan
- `uv run pytest -q tests/test_score_credit.py tests/test_score_credit_pins.py tests/test_score_credit_sweep.py
  tests/test_score_credit_history.py tests/test_contract_history_fields.py tests/test_contract_part7_history.py
  tests/test_design_copies.py` while building; `make test` once at the end.
- `make check-5` on the merged tree, stdout compared with `cmp` against the commit before the merge.
- `make check-5-contract` 0; `make report-real` 0; `part5 doctor --for part7` on the four goldens 0.
- `python3 scripts/score_credit_before_after.py dump`, then `compare` and `goldens`.
- `python3 scripts/make_score_credit_retime_noise.py --sets exercise dance` (the numbers under "Retimed takes").
- `python3 scripts/make_design_copies.py --check` 0; the dash scan of the changed lines is empty.

### Device/Platform Strategy
Not applicable: no UI and no new endpoint. The staging page does not show the credit.

### Data (created through the product's own UI with synthetic accounts; never a DB or API seed)
- Synthetic accounts needed: none.
- Data each verification needs: the committed seed 5 fixtures, the real takes of `part5.real`, and the four goldens.

### Ratchet Initialization Plan
Not applicable: the floors in `progress/ratchets.json` must not drop.

## Dissent Review
Reviewed by: independent agents (opus, read-only) in four rounds: the review of the team's 7181813, NEEDS_WORK with B1 to B6
(`progress/review-20261102-score-credit.md`); the delta review of Part 5's fixes at 9306ccc, NEEDS_WORK with N1; its
recheck at fea1598, NEEDS_WORK with D1; and the second recheck at 16dbe16, APPROVED (all three in
`progress/review-20261102-score-credit-delta.md`). Rulings: the stakeholder-proxy, STATUS.md Decisions 2026-11-02T02:38Z,
and the team's grade scale as the team reported it, 05:02Z.
Date: 2026-11-02

### Concern 1: the credit carries a second letter
Challenge: the 01:58Z ruling says reported only, yet the block writes its own `grade`, and a take slowed four times gets
`low_match` and grade F beside a credit grade of B (first review B1; "Why This Is Wrong" 1).
Impact if right: a reader sees two letters that disagree and cannot tell which one counts.
Mitigation: ruling B1 (c) keeps the letter as the credit's own informational grade, which never sets `score.grade`; the
owner's scale (8f135ee, S to F) gives it a scale of its own; a reader that shows both says which letter is which. The delta
review found B1 fixed as ruled, with a test that replaces the credit block with None and with an all-F block and sees no
other score field move.
Resolution: ADDRESSED_IN_SPEC (AC-CR-06, AC-CR-11).

### Concern 2: points on the follower's clock
Challenge: as first written, points and `max_points` used the follower's time span, so the same routine got a different
maximum on every take and a slow take earned more: at half speed 5525 of 5647 points became 9889 of 10120 (first review B2).
Impact if right: the points view rewards a slow take.
Mitigation: ruling B2 (a) counts points on the example's clock. The delta review then refused the claim written for it,
that a slower follower never earns more points: through the pipeline a slower take earned more in 46 of 162 pairs, by at
most 35 points (N1). It also found that equal `max_points` holds only within one comparison basis and with the same
measures seen (N3). AC-CR-03 was reworded, the pipeline test covers the 27 exercise takes with bounds (a rise of at most
2 percent, a move of at most 20 percent either way), and "Retimed takes" names the method behind each half-speed figure
(R-b). The cause of the falls was reworded twice (R-a, R-a2): they are not the clock's, and they were not traced further.
Resolution: REQUIRES_CHANGE, made in Part 5's commits on top of the team's and rechecked at fea1598 and 16dbe16 (AC-CR-03).

### Concern 3: credit can rise as a fault grows
Challenge: no test swept the fault size, and through the whole pipeline percent rises by 0.1 (normal) and 0.2 (hard) at
trunk lean 25 to 30 degrees, because the take is aligned again at each size (first review B3; "Why This Is Wrong" 4).
Impact if right: a worse take earns a slightly higher credit.
Mitigation: ruling B3 (a). With the alignment held fixed the credit never rises, and fixed-alignment sweeps test that for
each measure at three levels. The pipeline rises, the three trunk lean steps of AC-CR-08, are pinned in
`tests/test_score_credit_sweep.py`, which checks points as well as percent since N8. The alignment path is not touched.
Resolution: ACCEPTED_RISK (AC-CR-08; Compromises, "Percent can rise by tenths through the pipeline").

### Concern 4: the half-window rule is Part 5's reading
Challenge: a measure counts in a window only when it is finite in at least half the window's frames (`CREDIT_MIN_SEEN`),
which #61 does not say, and the rule moves `max_points` (first review R6; "Why This Is Wrong" 3).
Impact if right: the measures counted in a window, and so `max_points`, differ from what the owner intended.
Mitigation: kept as the team wrote it and stated as Part 5's reading here and in the ADR. The delta review recorded R6 as fixed
as documentation, with the owner's confirmation still open.
Resolution: ACCEPTED_RISK (Compromises, "The half-window rule").

### Concern 5: the credit is not calibrated
Challenge: no held-out seed was scored, no target is set, `make check-5` does not read it, and the team's 41-take figures are
theirs, not reproduced by Part 5 ("Why This Is Wrong" 2; first review B4 asked that they be cited as the team's).
Impact if right: a reader takes the percent for a validated measure.
Mitigation: ruled reported only, with no held-out seed; the credit sets no score grade, cap or gate (Overview, AC-CR-06),
and the spec and ADR cite the 41-take figures as the team's (delta review B4).
Resolution: ACCEPTED_RISK (Non-Requirements).

### Concern 6: the last second breaks AC-CR-08 there (review B2 of 1.14.2)
Challenge: with the alignment fixed, a follower who stops following the example's last move earns more credit than one who
follows it badly ("Why This Is Wrong" 6).
Impact if right: a reader who trusts "a bigger fault never earns more" is wrong for one second of a take.
Mitigation: the exception is written into AC-CR-08 and pinned with a fixed-alignment sweep: the rise stays in the last second,
in the measures the example moved, and never exceeds those entries' full credit. The follower-moves branch was dropped so the
exception covers one direction only.
Resolution: ACCEPTED_RISK, on the team's ruling that getting out of the pose at the end of a take should not cost credit
(moalborati/simon-part-5-fault-analysis#38, moalborati/simon#61) and the dispatch's delegation of the method to Part 5.

### Pre-Mortem: It's 6 months from now and this feature was a disaster. Why?
The reviews wrote these three; they rate no likelihood or impact.
1. The points view rewarded slow dancing, and the credit grade said B on takes the score had capped at F (first review).
   Mitigation: points on the example's clock (AC-CR-03); the credit grade informational and on its own scale (AC-CR-06,
   AC-CR-11).
2. Part 7 told users that a slower retake can never raise their points, and a user's slower retake scored 35 points higher
   (delta review). Mitigation: AC-CR-03 now says a retimed take's points move in either direction, with the measured
   figures under "Retimed takes".
3. Someone narrowed `picked_takes` for the retimed floor, and the credit test's bounds no longer matched the measurement
   the spec cites for them (recheck at fea1598, D1). Mitigation: the measurement script calls `retimed.picked_takes(labels,
   sets)`, and `tests/test_retimed.py` pins that it has no copy of its own.
