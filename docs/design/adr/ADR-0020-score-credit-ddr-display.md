# ADR-0020: Score credit (DDR) display: `score.credit`, additive beside the score
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted. The team chose DDR-style credit scoring, as the team reported on moalborati/simon#61
(issuecomment-6567178466); additive and reported only (stakeholder-proxy ruling of 2026-11-02T01:58Z, TICKET-078).
Spec: `docs/design/specs/score-credit.md`.
Date: 2026-11-01
Amends: nothing. ADR-0007, ADR-0013, ADR-0018 and ADR-0019 (the score, its windows and its ceilings) are kept as they are.

## Context
The shipped score (`simon.score.v3`, ADR-0019) is a penalty score: 100 minus what each reported fault and the similarity
term cost, capped at 89 for one fault, 79 for two or more and 59 for a warning. It answers "how bad were the mistakes",
and a take that reports nothing reads 100.

On moalborati/simon#61 (issuecomment-6567178466) the team reported that the team chose the scoring to ship: per-frame credit
on every compared measure ("DDR"), 1 point within half the tolerance, 0.6 within it, 0.2 within twice it and 0 beyond,
shown as a percentage or as points (100 per measure per second, so a longer routine has a higher maximum), the viewer
choosing which. the team tested it on 41 dance takes and reported a median of 53 percent where the current score's median is
10, with a rank correlation of 0.75 to the current score. Those figures are the team's, taken from that comment; Part 5 has
not reproduced them. The replay script the team's ADR describes (`replay.py`, which is not in this repository) captured every
scored window's per-frame, per-measure z through `score.timeline_window`.

## Decision
Every new analysis document (schema 1.13.0) carries `score.credit`, version `simon.credit.v1`, computed inside the scoring
path (`part5/score.py`: `window_score` keeps each window's credit sums, `timeline_block` writes the block), never by
patching the score.

Formula, per compared window of `score.timeline` (the same windows the score is the mean of, ADR-0013: about 5 s slices of a
take compared as a whole, or one window per accepted rep):

- `z = |follower - expected| / threshold_deg` per measure of `part5.measures.MEASURES` and expected frame of the window,
  the threshold being the profile's detection threshold of that measure (`score.threshold_of`).
- A measure counts in the window only when its z is finite in at least half of the window's frames (`CREDIT_MIN_SEEN`).
- Credit per measure and frame, by `z / tolerance`: at most 0.5 earns 1.0, at most 1.0 earns 0.6, at most 2.0 earns 0.2,
  beyond that 0 (`bands` `[[0.5, 1.0], [1.0, 0.6], [2.0, 0.2]]`). A frame where z is not finite is skipped (not counted).
- Points are counted on the example's clock (review B2 of TICKET-078). A frame lasts `frame_s` seconds, the example's first
  to last time over its frames less one (`score.example_frame_s`; rep by rep, the rep's reference clip). `points =
  sum(credit) * frame_s * 100 * multiplier` (100 points per measure per second), `max_points` the same with every counted
  credit 1. The same routine therefore has the same `max_points` however fast or slowly it was followed (within one
  comparison basis, the whole take or rep by rep, and with the same measures seen), its points do not scale with the
  follower's time (a retimed take is aligned again and differs by that, measured in the spec under "Retimed takes"), and a
  longer routine has a higher maximum. A take scored without the example's clock (`compute_timeline` without
  `expected_times`) has no credit.
- The take's points and max points are the sums over its compared windows; `percent = 100 * points / max_points`, to 0.1
  (so a window weighs by its example frames and its counted measures); `grade` is the percent's letter on the credit's own game
  scale, written with it as `grades` (team, 2026-11-02): S 95 and above, A 85, B 75, C 65, D 55, E 45, F 30, and
  under 30 still F. The score's bands (A to F) are unchanged for `score.value`.

Levels: `easy` (tolerance x1.5, points x0.75), `normal` (x1.0, x1.0), `hard` (x0.7, x1.5). All three are written under
`levels`; the top-level `percent`, `points` and `max_points` are the `normal` level's (`tolerance: "normal"`). `per_window`
has one entry per compared window of `score.timeline`, same `t_s`, same order, at the `normal` level.

`score.credit` is null when nothing was compared: the take could not be aligned, no window was compared, or no measure
could be counted in any window. It is additive: `score.value`, `grade`, `components`, `fault_cap`, `uncapped`, `capped_by`
and every other field are unchanged, and nothing in Part 5 reads it back (detection, the score, the insights and the
phrasing are byte-identical; the four goldens changed only by `schema_version` and the new block).

## Decision for the team: the warning cap
The 59 warning cap (ADR-0012) is not applied to credit. A take with `low_match` or `not_enough_visible` still shows the
credit of what was compared, which can be high (a different movement can follow the example closely on the few measures the
camera saw). Readers must read `warnings` before showing credit. Whether credit should also be capped, hidden or greyed on a
warned take is left to the team (Part 7 owns the display); this ADR does not decide it.

## Consequences
- analysis schema 1.13.0 (additive); `contracts/history-fields.json` 1.2.0 lists `score.credit`.
- Points depend on the example's length and on how many measures were seen, not on how long the follower took, so they
  compare only between takes of one example; compare `percent` across takes, within one profile and one credit version.
- Thresholds are the profile's, so a credit percent is read within its profile, like the score.
- Credit is not calibrated or gated: no held-out seed was scored, no target is set, and `make check-5` does not read it.

## Differences from the replay script
- Rounding: `percent` and points are rounded half up (`score.round_half_up`, as every number of the score), the script used
  Python's `round` (half to even). They differ only on an exact tie.
- A window where no measure is seen in half its frames has `percent` null in `per_window` (the script would count it as 0
  of 0), and a take where that holds for every window has `credit` null (the script printed 0).
- Clock: the script, and the first version of this block (7181813), counted a window's seconds on the follower's clock
  (`t_s[1] - t_s[0]`). The review of that version found the same follower take (`exercise_front_good_00_correct`) showing
  percent 97.8 at normal speed and 97.7 at half speed, but 5525 points of 5647 at normal speed against 9889 of 10120 at half
  speed, `max_points` moving with the first follower second the alignment landed on, and points rising as a fault grew.
  The 9889 of 10120 is that review's probe: the follower file's own frames with every timestamp doubled
  (`python3 scripts/make_score_credit_retime_noise.py --sets exercise --speeds 0.5 --mode stretch --list`, run on a 7181813
  tree with that script, then named `scripts/score_credit_retime_noise.py`, and `tests/retimed.py` copied in; the script is
  not in that commit). The spec's "Retimed takes" has the other half-speed figure for the same take on the same tree,
  9826 of 10047, from
  `retimed.retime(follower, out, 0.5, 30)`, which resamples the clip at 30 fps. Points now use the example's clock, so a
  routine has one maximum within one comparison basis. On the four goldens the percents moved by at most 0.4 (a window now
  weighs by its example frames, not its follower seconds); `analysis.example.json` went from 4622 of 5280 points to 5841 of
  6673, the length of its example.
- The script's "deduct" variant (a miss costing -0.5) is not shipped.

## Part 5 review (TICKET-078)
The review of this branch before it merged into Part 5 led to the changes below; each is its own Part 5 commit on top of
the team's, whose commit is kept as it is.

- The credit's grade stays and is informational. `score.credit.grade` is the credit percent's own letter on its own game
  scale (`grades`). It is never `score.grade`, it sets no cap and no gate, and it ignores warnings and caps, so a take
  capped to F can show a credit grade of B. A correct take slowed to a quarter of the speed gets `low_match`, a score of 59
  and a grade of F, and a credit of about 83 percent, grade B (`tests/test_score_credit_pins.py`). The score's value,
  grade, `fault_cap`, components and `capped_by` do not read the credit at all, which that test pins by replacing the
  credit block. A reader that shows both must say which letter is which.
- The credit's letters are the team's game scale, as the team reported the ruling on moalborati/simon#61
  (issuecomment-6569445776) and wrote it in 8f135ee, merged as it is: S 95, A 85, B 75, C 65, D 55, E 45, F 30, under 30
  still F, written as `grades`; the score's bands, `score.value` and the caps are unchanged.
- Points use the example's clock, not the follower's: see "Differences from the replay script". Within one comparison
  basis a routine has one maximum, and points do not scale with the follower's clock. A retimed take's points are still
  not the original's, and they move in both directions; the falls are not the clock's and were not traced further
  (`--mode stretch`, which keeps the file's own frames and scales their timestamps, falls too; the pipeline resamples
  every follower to the example's frame rate either way: the spec's "Retimed takes"). Over 54 takes at 0.75, 0.5 and 0.33
  times the speed (162 pairs), a slower take earned more in 46 pairs by at most 35 points (0.56 percent) and fewer in 110
  by up to 1387 (23.9 percent, at a third of the speed): `scripts/make_score_credit_retime_noise.py`, and the spec's "Retimed
  takes".
- The spec `docs/design/specs/score-credit.md` states the half-window rule (`CREDIT_MIN_SEEN`) as Part 5's reading, to confirm
  with the team: #61 does not say it. Foot measures earn no credit. The validator checks the shape of the block
  before it reads it, and the schema defines the level and window numbers once (`$defs.credit_entry`).
- The sweep (`tests/test_score_credit_sweep.py`). The acceptance asks that credit never rises as a fault grows. With the
  alignment held fixed it never does: `tests/test_score_credit_pins.py` sweeps each of the 22 measures alone, and all of them
  together, at the three levels and in every window. Through the whole pipeline, on the score's own sweep takes (foot out 0 to
  28 degrees, arms wider 0 to 35, trunk lean 0 to 30, on `random.Random(1234)`), the credit falls from the take with no fault
  to the largest fault at every level, and foot out and arms wider never raise it. The trunk lean sweep raises the percent at
  two steps: from 20 to 25 degrees at the hard level (92.7 to 92.8) and from 25 to 30 degrees at the normal level (95.2 to
  95.3) and the hard level (92.8 to 93.0). At each of those steps the take is aligned to the example again and a few frames
  land elsewhere (`alignment.exp_to_fol` differs from the step before). Strict monotonicity through the pipeline would need
  the alignment path to change, which is not part of this work, so the rises are recorded as measured and not tuned away.

## Amendment 1 (2026-11-03, TICKET-108): the take's last second
Decision: from 1.14.2, when over the example's last second (at most a third of the expected frames read) the follower holds
still (every measure read has a robust range of at most half its threshold), each measure in which the example moves away (its
range at least one threshold) earns full credit on every counted entry of that second; the measures the example holds are scored
as before. It is read once per take: on the take's expected frames when it is compared whole, on the last rep when it is compared
rep by rep. `max_points`, every other entry, the score, the faults and the near misses are unchanged. The rule and its tests are
in the spec, "The take's last second" and AC-CR-12. It makes AC-CR-08 false in that second (a follower who stops following the
last move earns more than one who follows it badly); the spec names the exception and pins it.

Why: staging take `b5acba462f16` (moalborati/simon-part-5-fault-analysis#38) read 82.9 (B) beside a score of 99 and no fault; 295
of its 600 lost points fell in the last second, where the trainer bent both elbows again and the follower held still. The repo
owner ruled the fix a bug fix to ship before the demo recording (moalborati/simon#61, 6595090557, 6595093083, 6595096742). With the
rule it reads 91.3 (A).

Options, all on the credit alone:
1. Leave the tail out of the count (earned and possible). Rejected: `max_points` would then depend on how the follower ended,
   where today it is the routine's own (the same routine has the same maximum); `b5acba462f16` would read 89.1.
2. Do not count differences at the clip's edges that never reach a fault's duration (#38's third suggestion). Rejected: the
   credit would read the faults (AC-CR-06 says it does not), and a held wrong pose in the last second, shorter than the 1.9 s a
   fault needs there, would never cost, against #38's "a real sustained miss in its last second still loses credit".
3. End the credit where the trainer's movement or last rep ends (#38's first two suggestions). Rejected: on `b5acba462f16` the
   trainer moves until its last frame, and a one-rep example has no rep boundary to end on.
4. The follower still and the example moving away, over the last second, with full credit for the measures the example moves
   (chosen). Its first form also forgave the other direction (the follower moving while the example holds) and every measure of
   the second; the review of 1.14.2 found that a nod then forgave an arm held wrong, so the forgiving is per measure and the
   follower must be still in all of them. The other direction was dropped: the alignment's open end already leaves the follower's
   frames after the routine uncompared (`aligned_until_s`).

Cost and case against: a follower who forgets the routine's real last move is forgiven for up to one second, in the measures
that move; the rule cannot tell that from stopping early, and it breaks AC-CR-08's "a bigger fault never earns more" there.
Accepted, on the owner's ruling: one second at most, and a miss that both sides hold, makes while moving together or makes while
moving anything at all, still costs.

## Reversal Cost
Low: remove the block from `timeline_block` and the schema property; no other field reads it.

## Code Backlinks
- `part5/score.py`: `credit_z`, `credit_of`, `credit_sums`, `credit_points`, `credit_grade` (`CREDIT_GRADES`),
  `credit_block`; `window_score` (`credit_raw`),
  `timeline_block` (`credit`).
- `part5/score_report.py`: `score_block` (null credit for a take that could not be aligned); `_rep_timeline` (the last rep's
  tail, Amendment 1).
- `part5/score.py`: `credit_tail`, `_tail_ranges`, `CREDIT_TAIL_S`, `CREDIT_TAIL_SHARE`, `CREDIT_HOLD`, `CREDIT_LEAVE`
  (Amendment 1, TICKET-108).
- `part5/output.py`: `_validate_credit`; `contracts/analysis.schema.json` `score.credit`.
- `tests/test_score_credit.py`.
