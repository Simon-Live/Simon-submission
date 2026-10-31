# ADR-0017: A second held-out series, seeds 67, 71 and 73, after seed 37; attempt 4 is one approach family
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-31

## Context
moalborati/simon#59 reports a real RDL follow take (10 s, 300 frames; the reporter's evidence is in the private moalborati/simon
repository at `docs/evidence/2026-10-31-follow-scored-100`, commit `8d820a8`) that scores 100 (A) with 0 faults. Part 5
main reproduces it. Three causes sit in detection:
1. Persistence is judged over the whole clip. `default.min_fraction` 0.38 in `part5/rules.json` needs 114 of the 300
   frames, so a 69-frame `trunk_lean_forward` deviation of up to 26.8 degrees is dropped.
2. Repetition by repetition comparison (ADR-0010) runs only when the whole-clip guard does not accept the pair
   (`part5/pipeline.py`, the `rep_run` line), so a multi-rep example matched as a whole is judged as one long take.
3. `trunk_lean_side` is `_lateral` in `part5/measures.py`, the `atan2` of the spine's x and y in the frontal plane. It
   wraps once the spine hinges forward past about 90 degrees: the trainer reads 155 degrees.

Any fix is a detection change, and ADR-0003 lets a detection change ship only through a held-out attempt: tune on seed 5,
freeze, generate the next unused seed once, score it once. ADR-0003 fixed the held-out seeds "now, in order 29, 31, 37"
(Decision, line 33) and its dissent promised they are "fixed now, before any tuning, and never changed" (Dissent, line
80). All three are spent: 29 green, 31 its green confirmation, 37 red (attempt 3, TICKET-040, foot measures; the
`ankle_inversion` false fault on `dance_side_good_01_correct`, `docs/thresholds.md`). No attempt is possible, and
TICKET-040 has been blocked on an operator ruling since.

Mo's held-out decision on #18 (brief, `goals/complete-simon-part-5.md` lines 327 to 329) reads "`make check-5` gates on
held-out sets from new seeds (29 first); seed 5 stays the tuning set. Each held-out seed is scored once and retired; a
retry with a different approach is scored on the next new seed, and every result, pass or fail, is published." The cap
of three seeds came from ADR-0003, not from that decision; the brief's rule (line 96) repeats the order 29, 31, 37.
The score protocol owns other seeds (ADR-0007): 41 and 43 were seen by the prototype, 47 and 53 are scored, and 59 and
61 are reserved for score retries.

The ruling this ADR records, verbatim (stakeholder-proxy, 2026-10-31T22:25Z, confidence medium, STATUS.md Decisions):

> "moalborati/simon#59 accepted under option (b), amended. A second held-out series is fixed as seeds 67, 71, 73 (59 and 61
> stay reserved for score retries, ADR-0007) in a new ADR committed before any detection change. Item 3 (near-miss
> diagnostics, analysis 1.8.0) lands first and changes no detection (seed 37 check-5 stdout and detection hashes
> unchanged). Items 1, 2 and 4 form one approach family tuned on seed 5 only, frozen, then scored once on seed 67 with
> every result published and seed 37's red kept. Item 5 is an answer only. The RDL take is reported by reference, never
> tuned on. Part 7 is messaged before detection changes. TICKET-040 no longer waits on an operator ruling: a foot-measure
> fix is its own family on the next unused seed of this series. Ends green and confirmed or DEGRADED with the new numbers
> by end of 2026-11-02."

Item 3 is TICKET-043 (no detection change, no seed). Items 1, 2 and 4 are TICKET-044, attempt 4. Item 5 changes nothing
in Part 5.

## Why This Is Wrong (Dissent-First)
1. **Hardest integration point: "rep by rep whenever the expected clip has 2 or more reps".** It meets three settled
   contracts at once. ADR-0010 rejected always cutting into reps because the synthetic expected dance has two cycles of
   the arm measure, so every dance take on seed 5 and on seed 67 changes path, and the reference becomes the first
   cycle: if the two cycles are not the same movement, the follower's second cycle is judged against the expected
   first. ADR-0015 hides the foot measures in rep mode (`part5/pipeline.py`, `REP_MODE_REASON`), while the gated slices
   count foot labels (8 per angle on seed 37): dance foot labels could turn into misses, and seed 37's failing take
   (a dance take) would stop failing by a side effect rather than a fix. ADR-0013 scores a rep take on each rep's own
   misses, so correct dance takes can lose points and the score gate (every correct good-light held-out take an A) can
   fail.
2. **Most rework: the freeze.** The family moves dance goldens, the score timeline of many takes, `detection_sha256`
   when `rules.json` changes, the attempt record and what Part 7 reads. A defect found after the freeze cannot be fixed
   on the same seed: it needs a new family and the next seed. The cheap place to find it is seed 5 and the pre-freeze
   review.
3. **Most likely regret: spending seed 67 on a family that does not touch the known red cause.** Seed 37 failed on a
   far-foot `ankle_inversion` false fault; the series is generated with planted feet like seed 37, and attempt 4 leaves
   the foot measures as they are. Attempt 4 can be red on seed 67 for TICKET-040's reason. Bundling three changes into
   one family also means a red result cannot be attributed and no part of it can be retried alone.

Verdict: **PROCEED.** None of the three blocks this ADR. Points 1 and 3 are questions the TICKET-044 spec answers and seed
5 measures before the freeze (the Decision makes them acceptance items); point 2 is why the per-part seed 5 record and
the pre-freeze review are required. The ruling already settles the scope and the order.

## Options Considered
### Where attempt 4 is scored
**Option 1: no new seed; ship the #59 fix without a held-out score, or not at all**
- Pros: ADR-0003's seed list stays as written.
- Cons: a detection change without a held-out score breaks ADR-0003 and AC-T02 outright; not shipping leaves a real take
  that is clearly off scoring 100 (A), which is the failure the product exists to avoid.
- Effort: Low.

**Option 2: rescore a spent seed (37, or 29 and 31) under the new rules**
- Pros: no new numbers to choose.
- Cons: a scored seed is retired (ADR-0003, AC-T03); rescoring is exactly what the protocol forbids, and seed 37's red
  would be overwritten in effect. Rejected.
- Effort: Low.

**Option 3: the reserved score seeds 59 and 61**
- Pros: already named in a record.
- Cons: they belong to ADR-0007's score retries; spending them on detection removes the score protocol's only retries.
  Rejected by the ruling.
- Effort: Low.

**Option 4: an open rule, "the next fresh seed", with no list**
- Pros: no cap, never runs out.
- Cons: a seed chosen after a result invites seed shopping; ADR-0003's defence against a quiet retune is a list fixed
  before tuning, so a missing or reused seed shows. Rejected.
- Effort: Low.

**Option 5: a second fixed series, 67, 71, 73, after 29, 31, 37, under the same protocol (chosen, the ruling)**
- Pros: fixed before any detection change and before any tuning; fresh seeds no tool has generated (none appears in
  `fixtures/`, `out/`, the tests or the records as of 2026-10-31); room for one attempt, its confirmation and one more
  family; every earlier result stands beside it.
- Cons: it amends a promise ADR-0003 made in writing; a reader can see moving goalposts unless seed 37's red stays in
  plain view.
- Effort: Low (a seed list in code, a Makefile case, tests).

### How the #59 items are grouped
**Option A: one family per item, each on its own seed**
- Pros: each result is attributable.
- Cons: three seeds for three items leaves no confirmation and no seed for TICKET-040; item 1 without item 2 is a
  half-fix on multi-rep takes.
- Effort: High (three freezes, three scores).

**Option B: items 1, 2 and 4 as one family on one seed (chosen, the ruling)**
- Pros: one freeze, one score, a seed left to confirm and one for the foot family.
- Cons: a red result does not say which part failed (mitigated by the per-part seed 5 record below).
- Effort: Medium.

## Decision
### The series
- The held-out order is **29, 31, 37, then 67, 71, 73**, fixed now, before any detection change, in that order. The next
  unused seed is the first of the six not in `attempts[]`; none is skipped, across both series.
- Each seed of the second series is generated once by `make heldout-data SEED=<n>` in its own commit, after its
  attempt's freeze commit, with the generator and options seed 37 used (`scripts/make_dummy_followers.py --seed <n>
  --out fixtures/input/heldout --dropout-variant --feet`; the `Makefile` gives `--feet` to every seed after 31). It is
  scored once by `make check-5`, then retired: never regenerated, rescored or used for tuning.
- No seed of either series is run through any tool before its attempt's freeze commit: not `make score-heldout`, not
  `make report-profiles`, not `calibrate`, not a debug run.
- A change to the generator's fault or noise model is no part of any attempt in this series; it needs its own ruling,
  because it changes what the series measures (ASM-002).
- 59 and 61 stay reserved for ADR-0007's score retries; 41, 43, 47 and 53 stay spent. No score seed is a detection
  held-out seed and no seed of this series is a score seed.
- More seeds after 73 need another ruling.

### What does not change
- The gate: held-out `good/front`, `good/45`, `good/side`, each precision >= 0.85, recall >= 0.75, 0 faults on correct
  takes, no gated slice empty; plus ADR-0007's score gate (every correct good-light held-out take an A, the monotonic
  sweep). Nothing reported becomes gated and nothing gated becomes reported.
- Every other rule of ADR-0003: freeze `rules.json` and the code in one commit, record the hash and a rationale first,
  publish every result, a retry only for a distinct approach family, a red confirmation counts as red.
- Seed 37's red attempt stays in `attempts[]`, `fixtures/heldout-attempts.json` and `docs/thresholds.md` exactly as
  recorded; the rules are not reverted.
- The score params (`params_sha256`) are not touched by any attempt in this series.

### Attempt 4 (TICKET-044)
- One approach family with three parts: persistence measured per expected rep; rep by rep comparison whenever the
  expected clip has 2 or more reps; a side-lean measure that does not wrap. Its name in the record: "persistence per
  expected rep, rep by rep whenever the expected clip has 2 or more reps, and a side lean that does not wrap
  (moalborati/simon#59 items 1, 2 and 4; TICKET-044, ADR-0017)".
- Tuned on seed 5 only (`calibrate` refuses any other seed, AC-T01). Seed 5 has no forward hinge past 90 degrees, so the
  no-wrap property is proven by geometry tests on constructed poses, not by data.
- The spec states, before tuning, what the foot measures do in rep mode and what the reference is for an example whose
  cycles differ. That is part of attempt 4 because it follows from part 2. Changing the definitions, visibility rule
  or thresholds of `foot_rotation` or `ankle_inversion` is not; that is TICKET-040's family.
- Before the freeze, each part's effect on seed 5 alone is recorded (good light per angle, faults on correct takes, foot
  labels found), so a red held-out result points at a part.
- A later attempt that is a subset of this family, or this family with other values, is not a new family.
- The freeze commit carries the seed list change in the code (it is `part5/` code, and AC-T02 allows no `part5/` change
  between a freeze and its generation). The attempt 4 section in `docs/thresholds.md` (freeze commit, `rules_sha256`,
  date, approach family, rationale) and the re-recorded `detection_sha256` are committed before `make heldout-data
  SEED=67`.
- Part 7 is messaged on the bus before the detection change merges.

### After seed 67
- One seed is scored at a time. No `part5/` or `rules.json` change lands between a freeze commit and its seed's
  generation commit, and for a confirmation, between the scored attempt's freeze and the confirmation's generation.

| seed 67 (attempt 4) | seed 71 | seed 73 |
| --- | --- | --- |
| green | confirmation of attempt 4, same freeze, both reported | TICKET-040's foot family if ready; green is reported "no seed left to confirm" |
| green | the confirmation is red (counts as a red attempt) | TICKET-040's foot family if ready |
| red | TICKET-040's foot family if ready, else DEGRADED | its confirmation when 71 is green |

- TICKET-040's foot-measure fix is its own family, tuned on seed 5 with ADR-0015's go/no-go, frozen, and scored on the
  next unused seed after attempt 4 and, when attempt 4 is green, after its confirmation. It is never bundled into
  attempt 4.
- The run ends green and confirmed, or DEGRADED with every attempt's numbers, by the end of 2026-11-02 (UTC). Still red
  after 73, or out of time, is DEGRADED.

### The RDL take
- Reported by reference: moalborati/simon `8d820a8`, `docs/evidence/2026-10-31-follow-scored-100`. It is analysed only after
  the attempt 4 freeze commit, as a real take: the command, the commit it ran at and the numbers are recorded in the
  attempt 4 section of `docs/thresholds.md` and posted on moalborati/simon#59.
- Never tuned on, never gated, never copied into the Part 5 tree (no file of it under `fixtures/`). TICKET-043's field
  may be shown on it as a real-take example; no attempt 4 value is chosen from it.

## Consequences
- **Positive**: #59 can be fixed and measured on unseen takes; TICKET-040 is unblocked by rule rather than by a waiting
  question; the record keeps every earlier result, seed 37's red included, beside the new ones.
- **Negative**: ADR-0003's written promise is amended; attempt 4 can be red for a cause it does not touch (the foot
  measures); a green confirmed attempt 4 followed by a red foot family on 73 ends the run with `make check-5` red; part 2
  changes the path of every multi-rep example, so dance goldens and scores move.
- **Neutral**: the seed list grows in `part5/check.py`, the `Makefile` and the tests; ASM-002 now covers six seeds;
  `make score-heldout` gains a refusal for the threshold series.

## Assumptions
- ASM-002 (same generator, same fault model, a fair proxy for unseen synthetic takes) holds for 67, 71 and 73 as it did
  for 29, 31 and 37. Its yaml names the first series only; extending it is listed for the orchestrator.
- None of 67, 71 or 73 has been generated or scored in this workspace (checked 2026-10-31: no `labels.json`, `out/`
  directory, test or record names them).
- The RDL evidence stays readable at moalborati/simon `8d820a8` for the post-freeze report.

## Reversal Cost
Low until seed 67 is generated: the series is a tuple in `part5/check.py`, a case in the `Makefile` and test lists.
High after: a scored seed cannot be unscored, its result is published in three places and upstream, and the
protocol forbids rescoring or dropping it.

## Pre-Mortem (MANDATORY)
It's 6 months from now and this decision was a disaster. Why?
1. Attempt 4 was red on seed 67 because of a far-foot `ankle_inversion` false fault, the failure TICKET-040 owns, and
   the body fixes were never credited. Likelihood: M, Impact: H, Mitigation: the per-part seed 5 record, the record of
   which criterion failed on which take, seed 71 left for the foot family, and an honest DEGRADED if time runs out.
2. Someone looked at seed 67 before the freeze (`make score-heldout SEED=67`, which today refuses only seeds recorded in
   `fixtures/score-heldout.json`). Likelihood: L, Impact: H, Mitigation: `make score-heldout` refuses every seed of
   both series before attempt 4's freeze; AC-T02 and AC-T03 history tests; the seed folder exists only from its
   generation commit.
3. Rep by rep on every multi-rep example broke correct dance takes (the second cycle judged against the first) or hid
   the dance foot labels, and seed 67 was red on correct takes or recall. Likelihood: M, Impact: H, Mitigation: the
   spec answers both before tuning; seed 5's correct dance takes and foot labels are in the per-part record and the
   pre-freeze review.
4. The side-lean fix passed every synthetic check and the RDL take still read wrong, because no synthetic take hinges
   past 90 degrees. Likelihood: M, Impact: M, Mitigation: geometry tests over 0 to 180 degrees of hinge; the RDL report
   after the freeze, published either way.
5. The second series read as moving the goalposts. Likelihood: M, Impact: M, Mitigation: fixed before any detection
   change, seed 37's red kept in every record and every STATUS, the gate thresholds unchanged, Mo's #18 decision allows
   a retry on the next new seed.
6. A non-detection lane landed a `part5/` change between seed 67's score and seed 71's generation, and the confirmation
   failed AC-T02. Likelihood: M, Impact: M, Mitigation: the orchestrator holds every `part5/` merge in that window; the
   history test names the commit.

## Dissent (MANDATORY)
Reviewed by: architect lane for moalborati/simon#59 (author); the independent review is TICKET-044's pre-freeze review.
Concerns:
- ADR-0003 said the seeds were fixed and never changed: this appends, it does not change. No scored seed changes status,
  the first series' results stand, and the new seeds are fixed before the change they will measure, which is the property
  the promise protected.
- Why not relax the gate for real-take realism: the README's done criterion is the gate; relaxing it to rescue an attempt
  is the retune the protocol exists to prevent.
- One family for three items loses attribution: accepted under the ruling; the per-part seed 5 record restores most of
  it, and a subset is not counted as a new family, so attribution cannot be bought with a seed.
- Running attempt 4 before the foot fix risks a red that attempt 4 did not cause: accepted under the ruling; the order
  puts the change that answers a real user report first, and the table above keeps a seed for the foot family either
  way.
- A synthetic series cannot show the #59 failure (no hinge past 90 degrees, no real persistence pattern): accepted; the
  series bounds regressions and false faults, and the RDL report by reference is the evidence for the fix itself.

## Code Backlinks (updated as code is written)
To change, by the implementing lane, in or before attempt 4's freeze commit:
- `part5/check.py:40` `HELDOUT_SEEDS = (29, 31, 37)`, read by `next_unused_seed` (`:158`), `attempts_list` (`:202`)
  and `check_seed` (`:205`); the docstring at `:9` and the hint at `:345`
- `Makefile:64` comment and `:71` the `heldout-data` case and messages (`29|31|37`); `:68` `HELDOUT_FEET` already gives
  `--feet` to seeds after 31
- `scripts/make_score_heldout.py:54` `check_seed`: refuse every seed of both series
- `tests/test_heldout_protocol.py:22`, `tests/test_check.py:413` and `:645`, `tests/test_generator.py:585`, `:593` and
  `:602`
- Records: `docs/thresholds.md:80` and `:189`, `fixtures/heldout-attempts.json:3` (`about`)
<!-- In code: # ADR-0017: reason -->
