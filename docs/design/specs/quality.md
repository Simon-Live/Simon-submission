# Spec: quality, a reported reading of how well the camera saw the take (analysis 1.13.0)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-11-02
Linked PRD: none (Part 7's request on moalborati/simon#61, issuecomment-6568313194; stakeholder-proxy rulings Q1 to Q5 of 2026-11-02T03:39Z, recorded in STATUS.md)
Linked CRD: none
Request Type: new-feature
Risk Level: low
Master spec: `part5-fault-analysis.md`. ADRs: ADR-0021 (this change), ADR-0011 (compare only what the camera sees), ADR-0012
(the warning cap of 59), ADR-0015 (the jitter measure). Ticket: TICKET-079. Companion specs: `integration-contract.md`,
`viewer.md`, `score-credit.md` (ships in the same schema version, 1.13.0).

## Overview
Every analysis document from schema 1.13.0 may carry `quality`: one object that says whether the camera saw the follower well
enough for the result to be trusted, as a level (`ok`, `degraded` or `major`), the reasons for it, the raw readings behind it
and a score cap of 59 that is reported when the level is `major`. It is read from what Part 5 already reads in the follower's
file (the joint confidence and its 0.3 unseen mark, missing and filled frames, the measures ADR-0011 hides, and the
frame-to-frame jitter of the joint positions as `feet.jitter` measures it). It is reported only: it sets no cap, no grade and no
gate in Part 5, and nothing in detection, the score, the insights or the phrasing reads it.

Why it exists: Part 7's check has a degraded-quality gate. A deliberately degraded (dark) follower clip must come back flagged
with a major quality warning and capped at 59. No part writes quality data today, so Part 7 asked for it. Part 7 applies the
cap; Part 5 only reports what it is. The shape below was told to Part 7 before any code.

## Why This Is Wrong (Dissent-First)
1. **Part 2 writes no light reading, and its confidence is 1.0 or 0.3.** `conf` is 1.0 for a joint inside the image and
   exactly 0.3 for one outside it (Part 2 CONTRACT), so a dark clip can carry confidence 1.0 on every joint of every frame.
   Then the only signal Part 5 can read is how much the joints jump from one frame to the next, and a dark take that the
   estimator happens to hold steady reads `ok`. Answer: the block says what was measured and never claims a cause; Part 7's
   own dark take is read once and reported (the last slice of `make report-quality`), not tuned on, and the readings are
   given as they came.
2. **Seed 5 can calibrate one signal.** Its clean followers carry no `conf`, so the confidence signals read null on them, and
   the jitter is the only signal that separates good light from low light. The limits of the other signals are anchored (a limb
   lost is degraded, a fifth of the readings or of the frames lost is major) and shown by unit tests, not fitted. Answer: said
   here, and in the thresholds file, which signal was fitted and which was anchored. The joint shares' major limit is the seed 5
   value, 0.2. The lane had moved it to 0.3 after the committed real lateral raise (filmed from the waist up) read major with
   every arm measure in view; that move was against "tune only on seed 5" and is withdrawn (stakeholder-proxy, option (c)). The
   real lateral raise prompted a rule instead, which does not touch a limit: `unseen_joint_share` counts only the joints the
   example itself sees (see "The example's visibility" below).
3. **A synthetic gap says little about real footage.** The seed 5 followers are Part 4's clips with planted noise
   (`scripts/make_dummy_followers.py`), so the jitter limit separates two noise levels the generator chose. Answer: the limit
   is reported against seed 73 once and against Part 7's real takes as a separate slice, and a miss there is a finding, not
   a retune.
4. **A cap that is reported but not applied can be ignored.** `score.value` stays what it was; a viewer that shows only the
   score hides the problem. Answer: that is the ruling (Q2). Part 7 applies the cap, and the viewer here shows one line when
   the level is not `ok`.
5. **Jitter depends on frame rate and on how the person moves.** It is a median of second differences per frame, so a 15 fps
   file reads differently from a 30 fps one, and a very fast movement lifts it. Answer: stated under Signals; the limit is
   per frame at the follower's own rate, as `feet.jitter` is, and the median over joints keeps one wild joint from deciding.
6. **Part 3's real skeletons are smooth.** The committed real lateral raise reads 0.2 mm of jitter where planted low-light noise
   reads 25 to 40, so on a real file the jitter signal says little and a dark real clip may read `ok`. Answer: said in
   Pre-Mortem 1 and the thresholds file; Part 7's own dark take is the test of it, and a miss is reported, not retuned.

## User Story
As Part 7, I want a level, the reasons for it and a score cap in `analysis.json`, so that a take the camera saw badly is flagged
and capped by my own gate without my reading Part 5's internals.

### Jobs-to-be-Done
- Functional job: say whether the result can be trusted, and why not when it cannot.
- Emotional job: the follower is told once, plainly, that the take was hard to see, and not left to wonder why a good
  movement scored badly.
- Social job: none.

## The block
`quality` is optional at the top level. A document without it was not assessed (every document before 1.13.0). Every new
document carries it.

| Key | Meaning |
|---|---|
| `version` | `simon.quality.v1` |
| `level` | `ok`, `degraded` or `major` |
| `reasons` | a list, empty for `ok`; each `{code, words, value, threshold}` and, when one joint is the cause, `joint` |
| `signals` | the raw readings, below; `null` when a reading is not measurable, never 0 |
| `score_cap` | 59 (`score.WARNING_CAP`, CONTRACT.md) when `level` is `major`, otherwise `null` |

`reasons[].code` is one of a closed list in the schema: `not_enough_visible`, `moving_part_out_of_frame`,
`no_usable_measures`, `joints_unseen`, `joints_missing`, `frames_missing`, `measures_hidden`, `position_jitter`. `value` and
`threshold` are the reading and the limit it crossed, in the signal's unit (`null` when a reason is a warning and has no
number). `words` is one plain sentence in the reader's terms, made from the measured numbers and claiming no cause.
`low_match` is never a reason: a take of another movement is not a take the camera saw badly.

### Signals
All five are read from the follower's file as Part 5 loads it, before smoothing. A value of 0.0 is a measured zero; a reading
that cannot be made is `null`.

| Signal | Reading | Unit | `null` when |
|---|---|---|---|
| `unseen_joint_share` | share of the (frame, joint) readings of the joints the example sees (below) whose `conf` is the 0.3 unseen mark, counted as ADR-0011 counts it: a joint is unseen when its left/right counterpart is at 0.3 too (the nose when it is) | 0 to 1 | the file carries no `conf`, or the example sees no joint |
| `missing_joint_share` | share of the readings that are null or have `conf` below 0.3 | 0 to 1 | never |
| `missing_frame_share` | share of the frames flagged `interpolated`, or with at most half of the 17 joints usable | 0 to 1 | never |
| `hidden_measure_share` | share of the 22 full-body measures the follower's own `conf` makes unusable under ADR-0011 (a joint seen in under 80 percent of the frames) | 0 to 1 | the file carries no `conf` |
| `position_jitter_mm` | per joint and axis, `feet.jitter` of the step series (the median absolute change of the step between consecutive frames, so a steady movement is not jitter); the three axes joined as a norm; the median over the joints | millimetres per frame | no joint has `JITTER_MIN_PAIRS` pairs of numbers |

### The example's visibility (the rule the real lateral raise prompted)
A follower is not held to a body part the example itself does not show. The committed real lateral raise was filmed from the
waist up: its legs sit at Part 2's unseen mark in every frame, 4 of 17 joints, and with the first limits it read major although
every arm measure it compares was in view. The rule (stakeholder-proxy, option (c), written here before any re-read):

- `unseen_joint_share` counts only the joints the example sees in at least half of its frames. The example's visibility is read
  the way ADR-0011 reads it: from its own `conf` and from `--expected-visibility`, each strict (a joint at 0.3 is never seen),
  and a joint counts when every conf that is known shows it in at least half the frames.
- The denominator is the readings of those joints (frames times the joints counted), so a follower that loses 2 of the 10 joints a
  waist-up example shows reads 0.2. The worst joint named in the reason is one of them. If the example sees no joint, the
  signal is `null`.
- An example whose visibility is unknown, with no `conf` anywhere (Part 4's animations, and seed 5's examples), counts every
  joint. This fails closed: a take is not excused for a body part because the example says nothing. The follower's own set is never
  borrowed for it.
- No limit moves for this. `missing_joint_share`, `missing_frame_share`, `hidden_measure_share` and the jitter do not read the
  example.

The limitation, said plainly: a waist-up trainer with no `conf` (the committed lateral raise trainer is one) does not excuse a
waist-up follower, so such a take can still read major on `unseen_joint_share`. That is reported, not tuned away.

### Level
Each signal has two limits in `part5/quality.json`: `degraded` and `major`. A signal at or above a limit adds a reason (the
higher limit it reached) with its reading as `value` and the limit as `threshold`; the reasons of `position_jitter`,
`joints_unseen` and `joints_missing` name the worst joint. A take that carries the warning `not_enough_visible`, `moving_part_out_of_frame` or
`no_usable_measures` adds that reason at `major`, whatever the signals say. The level is the worst reason; `score_cap` is 59
when it is `major`. The thresholds are in their own file, never in `part5/rules.json`, so `rules_sha256`, the detection hash
and the score `params_sha256` do not change.

### The limits (`part5/quality.json`, version 1.0.0, set after the targets below)
| Signal | `degraded` | `major` | Basis |
|---|---|---|---|
| `unseen_joint_share` | 0.10 | 0.20 | anchored, not fitted (seed 5's clean followers carry no `conf`): a limb is 2 of 17 joints (0.12), a fifth of the readings is the point where ADR-0011 stops using a joint |
| `missing_joint_share` | 0.10 | 0.20 | anchored: the same limb and fifth; the dropout copies of seed 5 lose at most 2 percent |
| `missing_frame_share` | 0.10 | 0.20 | anchored on ADR-0011's rule that a joint seen in under 80 percent of the frames is not used |
| `hidden_measure_share` | 0.25 | 0.50 | anchored: a quarter and a half of the 22 full-body measures; seed 5 hides none |
| `position_jitter_mm` | 21.0 | 42.0 | fitted on seed 5: good light reads 10.4 to 17.4 and low light 25.1 to 40.2 in the 156 clean takes, 21.0 sits in the gap (3.6 above the one, 4.1 below the other); `major` is twice that and no seed 5 take reaches it |

A reading is compared with a limit as the document shows it (rounded), and at or above a limit reaches it.

## Targets (written before any threshold was set)
These are the targets, in the commit before the one that adds `part5/quality.json`. Thresholds are tuned on seed 5
(`fixtures/input/followers`) only.

| # | Target | Kind |
|---|---|---|
| T1 | every clean good-light take of seed 5 (the 78 takes with lighting `good`, all three angles, both sets, correct and faulted) is level `ok` | pinned |
| T2 | the low-light takes of seed 5 (78) are `degraded` or `major`, as the jitter justifies; none is `ok` | reported, pinned if it holds |
| T3 | the dropout copies of seed 5 (regenerated into a temporary directory with `--dropout-variant`, never committed) take their light's level: a good-light copy is `ok` (a burst of 3 to 8 frames on one joint is under 2 percent of the readings and is not a degradation by itself), a low-light copy is `degraded` or `major` | reported |
| T4 | the shipped degraded sample is `major` with `score_cap` 59 | pinned |
| T5 | seed 73 (the held-out set on disk) is read once: its clean good-light takes should be `ok`. If one is not, stop and report it with its numbers; no retune | reported |
| T6 | Part 7's dark take and its clean twin (`fixtures/input/real/part7-check-20261102T021153Z`) are read once, after the thresholds are frozen, as their own slice; the dark take should be `major`. If it is not, report the readings; no retune | reported |

The retired held-out seeds (29, 31, 37, 67, 71) are neither regenerated nor read (seed 73 is the live gate seed, read under
T5), and `fixtures/heldout-attempts.json` is not written.

## Results (measured under the rule above and the limits as shipped; `make report-quality`, one run)
The first reading, made under a joint-share major limit of 0.3 that was then withdrawn, gave the same counts for seed 5 and seed 73
(none of their takes has a `conf`). It is replaced by this one, made after the rule was written.

| Target | Result |
|---|---|
| T1 | met: 78 of 78 clean good-light takes of seed 5 are `ok`; their jitter reads 10.4 to 17.4 mm |
| T2 | met: 78 of 78 low-light takes are `degraded` (jitter 25.1 to 40.2), none `ok`, none `major` |
| T3 | met: the 52 good-light dropout copies are `ok`, the 52 low-light copies `degraded`; the bursts add no reason of their own |
| T4 | met: the shipped sample is `major` (joints_unseen 0.4118 against 0.20, and position_jitter 26.7 against 21.0), `score_cap` 59, `score.value` 100 (A) untouched |
| T5 | met, read twice, the first time under the withdrawn 0.3 limit (above), with no tuning after either read: seed 73 has 78 of 78 clean good-light takes `ok` (jitter 10.9 to 16.7), 78 of 78 low-light `degraded` (25.1 to 40.2), and its dropout copies follow their light, 52 of 52 each |
| T6 | not met: Part 7's dark take reads `ok`, with `unseen_joint_share` 0, `missing_joint_share` 0, `missing_frame_share` 0, `hidden_measure_share` 0 and `position_jitter_mm` 0.4; its clean twin reads `ok` with 0.5; neither carries a warning against the example Part 7 compared them with. Reported, not retuned |

Counts per light and condition (ok / degraded / major), the same on both seeds:

| Light and condition | Seed 5 | Seed 73 |
|---|---|---|
| good, clean (78) | 78 / 0 / 0 | 78 / 0 / 0 |
| good, dropout (52) | 52 / 0 / 0 | 52 / 0 / 0 |
| low, clean (78) | 0 / 78 / 0 | 0 / 78 / 0 |
| low, dropout (52) | 0 / 52 / 0 | 0 / 52 / 0 |

The committed real lateral raise, reported as it comes out: its trainer (`pexels-5319084`) is a Part 4 animation with no `conf`, so its
visibility is unknown and every joint counts (the rule fails closed). Both followers were filmed from the waist up and read `major`
on `unseen_joint_share`, with no warning and the score left alone:

| Follower | `unseen_joint_share` | `hidden_measure_share` | `position_jitter_mm` | Level |
|---|---|---|---|---|
| `pexels-40297504` (8 fast reps) | 0.2353 (4 of 17 joints) | 0.4545 | 0.2 | `major`, cap 59 reported, `score.value` 79 |
| `pexels-8836968` (2 slow reps) | 0.3012 | 0.8636 | 0.2 | `major`, cap 59 reported |

This is the reported limitation of "The example's visibility", not something to tune. A trainer that carries its own `conf` (or
`--expected-visibility`) excuses unseen joints only: it lowers `unseen_joint_share`, which `tests/test_quality_pins.py` shows
with a waist-up example. `hidden_measure_share` does not read the example, so with the trainer's visibility (its legs at the
unseen mark) `pexels-8836968` stays `major` on `measures_hidden` (0.8636, at or above 0.5) and `pexels-40297504` is `degraded`
on it (0.4545, at or above 0.25), neither `ok` (review R2 of 1.13.0, measured with the pipeline).

Why T6 is not met, from the files: every joint of both takes has `conf` 1.0 in Part 3's skeleton and in Part 2's `pose3d.json`
(joints and foot points), Part 3's positions are smooth (0.4 and 0.5 mm of jitter against 25 to 40 for planted low-light noise),
and the two skeletons are the same pose estimate to within 12.9 mm per joint (median over joints, 29.3 at the left elbow). Nothing
Part 5 reads tells the dark take from its twin. A gate on that clip needs a reading Part 2 does not publish (a light level, or a
confidence that drops), or a reading of the video itself, which is not Part 5's input; Part 7 measures the brightness itself.

## Acceptance Criteria
### AC-Q01: the block, additive
Given any analysis from 1.13.0, when it is written, then it carries `quality`, which validates against
`contracts/analysis.schema.json` (`$defs.quality`); a document without it still validates; the schema does not require it.
Tests: `tests/test_quality.py`, `tests/test_contract_part7_history.py`.

### AC-Q02: each signal
Given a follower clip that is steady, one with joints at 0.3, one with null joints, one with filled frames, one with legs
unseen and one with noise added, then each signal reads as defined above, is `null` when it cannot be measured (no `conf`, too
few frames) and is never 0 as a stand-in. Test: `tests/test_quality.py`.

### AC-Q03: each reason
Given a reading at or above a limit, then the reason has the code, the reading as `value`, the limit as `threshold`, its words
and, for jitter and unseen joints, the worst `joint`; the higher limit reached is the one reported. Test: `tests/test_quality.py`.

### AC-Q04: level and cap
Given no reason, the level is `ok` and `score_cap` is `null`; a reason at the degraded limit only is `degraded` with `score_cap`
`null`; a reason at the major limit is `major` with 59. Test: `tests/test_quality.py`.

### AC-Q05: the warnings
Given a take with the warning `not_enough_visible`, `moving_part_out_of_frame` or `no_usable_measures`, then the level is
`major` with that reason; given a take with `low_match` alone, then `low_match` is not a reason and the level follows the
signals. Test: `tests/test_quality.py`.

### AC-Q06: reported only
Given any take, then `score.value`, `grade`, `fault_cap`, `uncapped`, `capped_by` and `warnings` are what they are without the
block, byte for byte (the same analysis with the block left out equals the analysis before this change), and the block never
adds a `warnings` entry. Test: `tests/test_quality_pins.py`.

### AC-Q07: nothing frozen moves
Given the commit before this one, then `make check-5` prints the same stdout (`cmp` exit 0), and `rules_sha256`,
`detection_sha256` and the score `params_sha256` are the same. Test: `tests/test_quality.py` (the thresholds are their own file
and `rules.json` holds none of them); the check is in the
integration note.

### AC-Q08: seed 5 in good light is ok
Given every clean good-light take of seed 5, then its level is `ok` (T1). Test: `tests/test_quality_pins.py`.

### AC-Q09: the shipped sample
Given `fixtures/output/analysis.quality-major.example.json`, made by the real pipeline from the degraded seed 5 input in
`fixtures/input/quality`, then its level is `major`, its `score_cap` is 59, `score.value` is not capped by it and the file
rebuilds byte for byte (`make check-5-contract`). Test: `tests/test_quality_pins.py`.

### AC-Q10: the contract
Given `contracts/history-fields.json` 1.2.0, then every `quality` path is listed from 1.13.0; `CONTRACT.md` and
`docs/schemas.md` say it is detected by presence, that absent means not assessed and that the cap is reported only;
`part5 contract` lists the row; `part5 doctor --for part7` notes the level, the reasons and the cap. Tests:
`tests/test_quality_history.py`, `tests/test_quality_doctor.py`, `tests/test_contract_cli.py`.

### AC-Q11: a bad block is refused
Given a `quality` with an unknown level or code, a cap that does not match the level, a level that does not agree with its
reasons, a reason without words, a joint that is not canonical, or a signal out of range or of the wrong type, then
`validate_analysis` raises `OutputError` and the schema refuses it. Tests: `tests/test_quality_validate.py`,
`tests/test_quality_history.py`.

### AC-Q12: the report
Given `make report-quality`, then it prints seed 5 and seed 73 per slice (light, condition, angle), the counts of `ok`,
`degraded` and `major`, and Part 7's two takes as their own slice, writes `out/report-quality/report.json` and exits 0; it
refuses a held-out seed it has used. Test: `tests/test_quality_report.py`.

### AC-Q13: the viewer line
Given a result whose level is not `ok`, then the Compare page shows one line under the score, in plain words; given `ok` or no
block, the line is not shown, and the words name no cause. Test: `tests/test_quality_web.py` (Node, on `web/joints.js`); QA
recipe `qa/recipes/compare/quality-line-on-degraded-take.md`.

### AC-Q14: the goldens
Given the four goldens that existed before, then each differs only by the added `quality` block. Test:
`tests/test_quality_pins.py`; `make check-5-contract`.

### AC-Q15: the example's visibility
Given a follower with its legs at the unseen mark, then `unseen_joint_share` counts them against an example that sees its legs
(or whose visibility is unknown, with no `conf`), and counts nothing for them against an example that does not see them (its own
`conf`, or `--expected-visibility`); given two known confs, a joint must be shown by both; given an example that sees no joint,
the signal is `null`; and the follower's own visibility is never borrowed for an unknown example. The pipeline reads the example's
`conf` and `--expected-visibility` before the block is made. Tests: `tests/test_quality.py`, `tests/test_quality_pins.py`.

## Error Cases
| Condition | Behavior | AC |
|---|---|---|
| `quality` is not an object | `OutputError`: `quality must be an object` | AC-Q11 |
| unknown `level`, `code` or `version` | `OutputError` naming the key | AC-Q11 |
| `score_cap` is not 59 for `major` and `null` otherwise | `OutputError` | AC-Q11 |
| a reason with no words, or a `value` that is not a number or null | `OutputError` | AC-Q11 |
| `level` `ok` with reasons, or `degraded` or `major` without | `OutputError` | AC-Q11 |

## Edge Cases
- A follower file with no `conf` anywhere: `unseen_joint_share` and `hidden_measure_share` are `null`; the other three are read.
- A clip too short for `JITTER_MIN_PAIRS` pairs: `position_jitter_mm` is `null`.
- A take that could not be aligned (`low_match`, `no_usable_measures`): the block is still written, from the follower's file.
- A take compared rep by rep: the signals are read on the whole file, once.
- A take with `low_match` and nothing else: the level follows the signals, not the warning.
- Two reasons: both are listed, in the fixed order of the code list; the level is the worst.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | one pass over the follower's frames | no new loop over frame pairs | AC-Q07 |
| Reliability | deterministic, offline | the goldens rebuild byte for byte | AC-Q14 |
| Compatibility | additive | a 1.12.0 document still validates | AC-Q01 |
| Security, Scalability | not applicable: a block in a JSON file and one line on a page, no endpoint | | |
| Accessibility | the line is text in the document order under the score, not colour alone | `data-testid` quality-note, a paragraph | AC-Q13 |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT change `score.value`, `grade`, `fault_cap`, `uncapped`, `capped_by` or `warnings`, or add a `warnings` entry. Why:
  reported only (ruling Q2).
- MUST NOT be read by detection, the score, the insights or the phrasing. Why: byte-identical (AC-Q06, AC-Q07).
- MUST NOT put a threshold in `part5/rules.json`. Why: `rules_sha256` and the score `params_sha256` must not move.
- MUST NOT make `low_match` a reason. Why: a take of another movement is not a badly seen take.
- MUST NOT name a cause (low light, occlusion) in `words`. Why: no part gives Part 5 a light reading; it reports what it measured.
- MUST NOT be tuned on seed 73, Part 7's takes or any used held-out seed. Why: they are read to report, not to fit.
- MUST NOT read Part 7's code or repository. Why: the 59 is Part 5's own `WARNING_CAP`.

## Compromises
### The limits other than jitter are anchored, not fitted
Short-term: seed 5 carries no `conf` on its clean followers, so the limits of the confidence signals are ADR-0011's 80 percent
rule halved and doubled, and unit tests show each reason fires. Long-term: a real set of dark and occluded takes with labels.
Migration path: change `part5/quality.json` and report the change in an ADR amendment. Trigger to revisit: Part 7's first real
dark take that reads `ok`.

### An example of unknown visibility counts every joint
Short-term: a trainer file with no `conf` (Part 4's animations today) excuses nothing, so a waist-up follower against a waist-up
trainer without `conf` still reads `unseen_joint_share` 0.24 and major. Long-term: the trainer's `unseen_joints` or `conf`, which
Part 4's schema already allows, once Part 4 writes it. Migration path: none needed, the rule reads whatever the clip carries.
Trigger to revisit: Part 4 writing visibility for its animations.

### Jitter is a proxy for a hard-to-see take
Short-term: the median second difference of the joint positions. Long-term: a light reading from Part 2, if one is published
under `contracts/`. Trigger to revisit: Part 2 publishing it.

## Non-Requirements (Explicitly NOT Building)
- A light signal: none is published under `contracts/`.
- A cap applied by Part 5, or a new warning: ruled out (Q2).
- A held-out seed, a gate or a target in `make check-5` for quality: it is reported by `make report-quality`.
- Quality in the phone preview or in the replay file.

## Assumptions
- None added. The 0.3 unseen mark is Part 2's contract, which ADR-0011 already relies on.

## Implied Requirements Discovered
- The fitness baseline digest (`profiles_report.analysis_digest`) hashes the whole document, so it leaves `quality` out like the
  other additions, or `fixtures/profiles-fitness-baseline.json` would stop matching (found by reading the digest).
- `tests/test_contract_part7_history.as_version` strips what a later version added, so it strips `quality` below 1.13.0.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `docs/design/specs/quality.md` | this spec | TICKET-079 | yes |
| `docs/design/adr/ADR-0021-quality-block.md`, `docs/design/specs/quality.md`, `docs/design/adr/ADR-0021-quality-block.md`, `docs/design/README.md` | the ADR and the neutralised copies written by `make design-copies` | TICKET-079 | yes |
| `part5/quality.py` | the signals, the reasons, the level and the block (the vocabulary and the validator are in `part5/output.py`, like every other block) | TICKET-079 | yes |
| `part5/quality.json` | the thresholds, in their own file | TICKET-079 | yes |
| `part5/quality_report.py` | `make report-quality` | TICKET-079 | yes |
| `part5/pipeline.py` | reads the raw follower once, passes the block to `build_analysis` | TICKET-079 | yes |
| `part5/output.py` | the quality vocabulary, `build_analysis(quality=)`, `_validate_quality` | TICKET-079 | yes |
| `part5/profiles_report.py` | the baseline digest leaves `quality` out | TICKET-079 | yes |
| `part5/contract.py` | the compatibility row for `quality` | TICKET-079 | yes |
| `part5/doctor.py` | `--for part7` notes | TICKET-079 | yes |
| `contracts/analysis.schema.json`, `contracts/history-fields.json` | `quality` and `$defs.quality`; every quality path, version 1.2.0 kept; a reason's `words` refuses a whitespace-only line in the schema as the validator does (`pattern` `\S`, review R9 of 1.13.0, `tests/test_quality_validate.py`) | TICKET-079 | yes |
| `CONTRACT.md`, `docs/schemas.md`, `README.md` | the block, the row, `make report-quality` | TICKET-079 | yes |
| `Makefile` | `report-quality` | TICKET-079 | yes |
| `scripts/make_quality_sample.py`, `fixtures/input/quality/` | the degraded seed 5 input and the script that derives it | TICKET-079 | yes |
| `scripts/make_output_examples.py`, `fixtures/output/analysis*.example.json` | the shipped major example and the regenerated goldens | TICKET-079 | yes |
| `fixtures/input/real/part7-check-20261102T021153Z/` | Part 7's dark take and its clean twin, with PROVENANCE.md (no host path: the source is named as Part 7's check directory, run 20261102T021153Z) | TICKET-079 | yes (`fixtures/**` is published, and `tests/test_quality_report.py` reads the folder) |
| `web/index.html`, `web/joints.js`, `web/app.js`, `web/style.css` | the quality line under the score | TICKET-079 | yes |
| `qa/recipes/compare/quality-line-on-degraded-take.md` | the QA recipe for the line | TICKET-079 | yes |
| `tests/test_quality.py`, `tests/test_quality_validate.py`, `tests/test_quality_pins.py`, `tests/test_quality_history.py`, `tests/test_quality_doctor.py`, `tests/test_quality_web.py`, `tests/test_quality_report.py` | AC-Q01 to AC-Q14 | TICKET-079 | yes |
| `tests/test_contract_history_fields.py`, `tests/test_contract_part7_history.py`, `tests/test_contract_cli.py`, `tests/test_output_examples.py` | `millimetres` among the units; `as_version` strips `quality` below 1.13.0; the golden tests expect the quality sample | TICKET-079 | yes |
| `tests/test_score_credit_history.py` | one assertion: the quality paths may be dated 1.13.0 beside the credit ones (the set of that assertion only) | TICKET-079 | yes |

## Delivery Verification Plan
- `uv run pytest -q tests/test_quality.py tests/test_quality_validate.py tests/test_quality_pins.py tests/test_quality_history.py
  tests/test_quality_doctor.py tests/test_quality_web.py tests/test_quality_report.py tests/test_contract_history_fields.py
  tests/test_contract_part7_history.py tests/test_design_copies.py`
  while building; `uv run make test` once at the end.
- `make check-5` on the final tree, stdout compared with `cmp` against a run at c8673d1 in a `git archive` export.
- `make check-5-contract` 0; `make report-real` 0; `make report-quality` 0; `make contracts-check` 0;
  `scripts/qa-recipe-lint.sh` 0; `python3 scripts/make_design_copies.py --check` 0; the dash scan of the changed lines is empty.

### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|----------|------|----------|-------------|
| Chromium on the staging page | the QA recipe `quality-line-on-degraded-take` | 1440px | demo-gate agent, at the milestone |

### Data (created through the product's own UI with synthetic accounts; never a DB or API seed)
- Synthetic accounts needed: none.
- Data each verification needs: the shipped degraded skeleton in `fixtures/input/quality`, uploaded through the page's own file
  input; the committed seed 5 fixtures for the other cases.
- Empty states acceptable for: a result with no `quality` (an older document) shows no line.
- Populated states required for: the Compare result of the degraded upload.

### Ratchet Initialization Plan
Not applicable: the floors in `progress/ratchets.json` must not drop.

## Dissent Review (MANDATORY, hooks block implementation without this)
Reviewed by: stakeholder-proxy (rulings Q1 to Q5) and the TICKET-079 delta review at the end of the lane
Date: 2026-11-02

### Concern 1: a flagged-major take scores above 59 in Part 5's own document
Challenge: a reader sees `score.value` 82 and `quality.level` `major` side by side.
Impact if right: confusion about which wins.
Mitigation: `score_cap` is 59 in the block and CONTRACT.md says the cap is reported only and Part 7 applies it.
Resolution: ADDRESSED_IN_SPEC (ruling Q2).

### Concern 2: the thresholds will not hold on real footage
Challenge: a limit fitted on planted noise says nothing about a real dark clip.
Impact if right: real dark takes read `ok`, real clean takes read `degraded`.
Mitigation: Part 7's takes are a reported slice, seed 73 is read once, and a miss is reported without a retune.
Resolution: ACCEPTED_RISK.

### Concern 3: the block makes a new gate that cannot be removed
Challenge: Part 7 builds on the shape.
Impact if right: a later change to a level breaks Part 7's gate.
Mitigation: `version` is `simon.quality.v1`; a change of meaning is a new version; limits live in one file.
Resolution: ADDRESSED_IN_SPEC.

### Pre-Mortem: It's 6 months from now and this feature was a disaster. Why?
1. Real dark takes read `ok` because Part 2 holds the confidence at 1.0 and the estimator is steady. Likelihood: M, Impact: H,
   Mitigation: ask Part 2 for a light reading; the Compromise names the trigger.
2. A fast dance lifts the jitter and a good take reads `degraded`. Likelihood: M, Impact: M, Mitigation: the median over joints
   and over frames; the real takes slice shows it; the limit is one number in one file.
3. Someone puts the cap into the score "to match". Likelihood: L, Impact: H, Mitigation: AC-Q06 pins the score fields byte for
   byte with and without the block.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|---|---|---|---|
| ticket: the block, additive | AC-Q01, AC-Q11 | `tests/test_quality_validate.py`, `tests/test_quality_history.py` | passing |
| ticket: signals only from what Part 5 reads | AC-Q02, AC-Q03 | `tests/test_quality.py` | passing |
| ticket: reported only | AC-Q04, AC-Q05, AC-Q06, AC-Q07 | `tests/test_quality.py`, `tests/test_quality_pins.py` | passing |
| ticket: pinned tests | AC-Q08, AC-Q09, AC-Q14 | `tests/test_quality_pins.py` | passing |
| ticket: contract, history, doctor | AC-Q10 | `tests/test_quality_history.py`, `tests/test_quality_doctor.py` | passing |
| ticket: make report-quality | AC-Q12 | `tests/test_quality_report.py` | passing |
| ticket: viewer line and recipe | AC-Q13 | `tests/test_quality_web.py`, the recipe | passing; the recipe is for the demo gate |

## Test Scenarios (maps 1:1 to acceptance criteria)
- AC-Q01 → `tests/test_quality_validate.py`, `tests/test_quality_history.py`
- AC-Q02 to AC-Q05 → `tests/test_quality.py`
- AC-Q06 to AC-Q09, AC-Q14 → `tests/test_quality_pins.py`
- AC-Q10 → `tests/test_quality_history.py`, `tests/test_quality_doctor.py`
- AC-Q11 → `tests/test_quality_validate.py`
- AC-Q12 → `tests/test_quality_report.py`
- AC-Q13 → `tests/test_quality_web.py`

## Deviations from PRD
| PRD item | Deviation | Reason |
|----------|-----------|--------|
| the viewer example "Low light: this take's joints were hard to see..." | the line does not say "Low light" | no part gives Part 5 a light reading, so naming the cause would be a guess; the line says the joints were hard to see |
| the ticket names two warnings as reasons at `major` | `no_usable_measures` is a reason at `major` as well | it is the warning for a take mostly missing its joints, which is the case the gate is for |
| the block and its validator in `part5/quality.py` | the vocabulary and the validator are in `part5/output.py` | every other block of the document is validated there, and it keeps `output.py` free of an import of the signals code |
| thresholds tuned on seed 5 only | none: the move of the joint shares' major limit from 0.2 to 0.3 is withdrawn (stakeholder-proxy, option (c)); both limits are 0.2, the seed 5 value | the move had been prompted by the committed real lateral raise (legs out of frame, arms in view) reading major, a real take outside the tuning set; what that take showed is handled by a rule that moves no limit, "The example's visibility" |
