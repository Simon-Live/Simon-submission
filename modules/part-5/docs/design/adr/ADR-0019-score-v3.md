# ADR-0019: Score v3 (simon.score.v3): v2's range weight and 89 ceiling, and a ceiling of 79 for a take that reports two or more faults
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted and shipped: scored once on score seed 61 (2026-11-01, `make score-heldout SEED=61` at 7d92b59, exit 0), all
five targets hold (`holds` true), so `simon.score.v3` is the shipped score. Numbers: `docs/thresholds-score-v3.md`, "v3 held-out
result: seed 61".
Date: 2026-11-01
Amends: ADR-0007 (the score curve, and its retry rule) and ADR-0018 (score v2). ADR-0013 (the score is the mean of its
windows) is kept as it is.

## Context
`simon.score.v2` (ADR-0018) was scored once on score seed 59 (`make score-heldout SEED=59` at 0aba974, 2026-11-01, exit 0)
and missed target 5: 3 of the 10 double-fault takes that report exactly their two labelled faults graded B
(`dance_front_good_08_elbow_bent-right+arms_wider-right` 85, `dance_side_good_08_arms_wider-right+trunk_lean-center` 80 and
its dropout copy 80). Targets 1 to 4 held. `holds` was false, so v2 did not ship, `make score-fallback` put `score.v1`
back (bbfe036) and the v2 code stays in the tree, version-aware. Numbers: `docs/thresholds.md`, "v2 held-out result: seed
59".

Two things in the v1 and v2 record pull in different directions. v2 held what it set out to do: a miss on a measure the
trainer barely moves costs less than a miss on one the exercise is about; a take that reports a fault is never an A (the
real Romanian deadlift of moalborati/simon#59 goes from 93 A to 89 B); single faults grade B or C. v1 never let a double read
as a B on any seed it was scored on (47 and 53: every good/2 grade was D or F). v2's floor, fitted to seed 5's doubles,
put the highest exactly reported double on its own bound (75) and the milder doubles of seed 59 landed above it.

Operator ruling on moalborati/simon#61 (issuecomment-6558511039, 2026-11-01T13:20Z, STATUS.md Decisions), verbatim:

> "it seems like a lot was lost. Regarding score v1/v2, go with reconciliation and adjust to create a v3. Likewise I don't
> want anything "back" but I want to make sure any intent or improvements from what might have been lost is integrated."

The hub session (claude-template-7e) relayed it with its reading: simon.score.v3 keeps v2's improvements that held (each
miss weighted by how much the trainer moves the measure; a take that reports a fault capped at 89) and v1's behaviour
where v2 failed (3 of 10 doubles at B), adjusted so the double-fault target holds; run as the next score family under
ADR-0007 on the reserved score seed 61 (tune on seed 5, freeze, score once), now, not waiting on TICKET-053's recall
trigger; plan and ETA, then the result, on #59; Part 7 told the published sha (its TICKET-120 waits on the fault cap).

Ruling of the stakeholder-proxy, 2026-11-01T13:35Z, confidence medium (Q2 and Q6 high), STATUS.md Decisions, verbatim:

> "score v3 under the operator ruling of 2026-11-01T13:20Z on moalborati/simon#61. Q1 simon.score.v3 (ADR-0019, amending
> ADR-0007 and ADR-0018) keeps v2's range weight (range_full 3; range_floor from ADR-0018's unchanged rule re-run on seed 5
> under v3 code, output kept with no hand nudge) and the 89 cap for a take that reports one fault, and adds a ceiling of 79
> (top of C) for a take whose faults list holds two or more entries, applied once to the mean of the windows and written in
> score.fault_cap (the ceiling in force, 89 or 79); uncapped is the value before every cap, capped_by unchanged; the rules
> keep score.v1 (e818635b) and score.v2 (60116de4) verbatim and make score-fallback still restores v1; next additive schema
> minor with simon.score.v3, CONTRACT.md, doctor, goldens and a double-capped sample; the team lines byte-identical; detection
> byte-identical. Q2 seed 61 is judged on ADR-0018's five targets verbatim with the fail-closed clause and the 05:00Z ship
> conditions, committed before any tuning commit; the ADR states that targets 3 and 5 hold by construction for the takes
> they judge, and the report publishes beside them, as measured, each exact double's value before the 79 ceiling and how
> many it lowered, ADR-0007's doubles D or F reading, the strict slice verdicts and the comparability sentence. Q3 the knee
> raises and the #59 RDL are no target: read once after the freeze, read-only, reported with v1, v2 and v3 columns; no window
> cost ceiling enters v3; TICKET-053 stays open on its recall trigger, amended to a third score series since seed 61 is
> spent. Q4 if v3 fails: make score-fallback, v1 stays, the result is published, seed 61 retired, v3 code kept
> version-aware; no third score series is opened in this run; a new ticket holds the next family and a series fixed by a new
> ADR before any score change. Q5 v3 runs on lane/score-v3 in parallel with TICKET-058, merge only: ADR, seed 5 rule run,
> code and contract, one pre-freeze independent review and recheck, Part 7 told of fault_cap 79 before it lands, freeze by
> 2026-11-02T06:00Z, make score-heldout SEED=61 once; nothing under part5, scripts, contracts, fixtures/input/expected*,
> pyproject.toml or uv.lock lands on main between the v3 freeze and the scoring; then one combined integration, gates once,
> one delta review, staging, the affected QA drives once on the served final commit, delivery review re-run, registry,
> publish and fresh clone and DONE? per the 12:45Z ruling. Not frozen by 06:00Z: v1 stays, the lane branch is kept
> unmerged with a ticket and recall trigger, the plan and the miss are posted on #59, and the run ends on the TICKET-058
> state; TICKET-058's 12:00Z cutoff is unchanged. Q6 the hub posts the plan and ETA on #59 now (writer skill), then one
> result post naming the published sha; Part 7 is told the sha on the bus."

The ship conditions of the 05:00Z ruling (ADR-0018, stakeholder-proxy, 2026-11-01T05:00Z) carry over to v3, quoted from it:
"it ships only if correct good-light takes stay A, the sweep stays monotonic and every target holds, otherwise v1 stays and
61 stays reserved; no freeze by the cutoff means (a); detection, thresholds and detection seeds untouched; check-5 on seed
73 must exit 0 with detection metrics and detection_sha256 byte-identical." Read for v3: the seed is 61, and under Q4 a
miss retires 61 and opens no further score series in this run.

Disclosure of what v3 knows. v3 is designed after seed 59 was scored: the recorded miss (three doubles at B) is why a
second ceiling exists. Seed 59 informs the design and is not fitted to; no v3 number was chosen to make a seed 59 take
land anywhere (the ceiling 79 is the ruling's, the floor is a rule's output on seed 5). Seed 61 has never been generated.
It is the only data v3 has not seen.

## Options Considered
### Option 1: v1 stays
- Pros: nothing to freeze; v1's record (seeds 47 and 53) stands.
- Cons: the complaints behind v2 stay open (a deadlift fault in one rep of two reads A; a miss on a measure the exercise
  does not move costs the same as one it does). The operator asked for a reconciliation. This is also the outcome if v3
  misses its cutoff or its targets (Q4, Q5).
- Effort: none.
### Option 2: v3 as ruled (v2 plus a ceiling of 79 for two or more reported faults)
- Pros: keeps what held in v2 and what v1 did for doubles; two small, readable rules (weight by the trainer's range;
  a ceiling by the number of reported faults); `fault_cap` says which ceiling applied; detection is not touched.
- Cons: a take with two small faults is at most a C however small they are, as a take with one is at most a B. Targets 3
  and 5 hold by construction (below), so a pass on them shows less than the same pass on 1, 2 and 4.
- Effort: Medium (the v2 machinery exists; the new parts are the count, the second ceiling and the v3 freeze).
### Option 3: lower v2's `range_floor` until the doubles land at C
- Pros: no new field.
- Cons: ADR-0018's rule, run unchanged, picks the floor; lowering it by hand is the "hand nudge" Q1 rules out, and a floor
  low enough for seed 59's doubles would charge every single fault more, which the worst-single rule (70 or above) bounds.
- Effort: Low. Rejected by Q1.
### Option 4: a ceiling on a window's total cost, or a gentler `base`
- Pros: would lift the two real knee raises that still grade F under v2.
- Cons: a different approach family, aimed at a complaint nothing yet shows is a false fault (TICKET-053). Q3 keeps it out
  of v3.
- Effort: Medium. Not taken.

## Decision
Option 2. `score.version` becomes `simon.score.v3`. The formula is v2's (ADR-0018 items 1 to 4: the weight
`w = min(1, max(range_floor, u / range_full))` on every miss, the foot measures included, the mean of the windows, `uncapped`
as the value before every cap) with one change to item 2 and one change to item 3. Everything not named here is v1 as
ADR-0007 and ADR-0013 state it, and v2 as ADR-0018 states it: the penalty curve (`base`, `slope`, `cap`), the similarity
term (`z0`, `z1`, `s_max`), the bands (A 90 and above, B 80 to 89, C 70 to 79, D 60 to 69, F below 60), the windows, the
tempo charge of the dance profile and the warning cap of 59 (ADR-0012).

1. **Two ceilings, by the number of entries in `analysis.faults`.** With `n` the length of that list: `n` 0, no ceiling;
   `n` 1, at most `fault_cap` 89 (the top of B), as in v2; `n` 2 or more, at most `fault_cap_many` 79 (the top of C). The
   ceiling is applied once, to the mean of the windows (ADR-0013); no window is capped and there is no worst-window rule. A
   take with faults on which nothing could be measured (value 0) still carries the ceiling in force.
2. **`score.fault_cap` is the ceiling in force.** An integer, present only when the take reports at least one fault: 89
   when it reports one, 79 when it reports two or more, whether or not the ceiling lowered this value. (In v2 it was always
   89.) `capped_by` is not touched: it lists the warning codes of the low-match cap and nothing else, because Part 7 reads it
   as a low-match warning.
3. **`score.uncapped` is the value before every cap**, as in v2: `{value, grade}` of the mean of the windows before the
   fault ceiling and before the warning cap, written when either lowered the value; with both, the value before the first.
4. **The params.** The v3 block repeats v1's numbers at its top level (`z0`, `z1`, `s_max`, `base`, `slope`, `cap`,
   `bands`, equal to v1's, a test pins it) and adds `range_floor` (the rule's output below), `range_full` 3, `fault_cap` 89,
   `fault_cap_many` 79 and `many_faults` 2 (the count at which the second ceiling starts). `range_full`, `fault_cap`,
   `fault_cap_many` and `many_faults` are design constants (the first by ADR-0018, the others the ruling's), not fitted.
5. **v1 and v2 stay in the rules, verbatim.** The `score` section of `part5/rules.json` carries the shipped v3 block with
   the frozen v1 block as `score.v1` (`params_sha256` `e818635bb46b7062f57e335f2940edd35d01835edaaaffed9339fdbfb79eaa62`) and
   the v2 block as `score.v2`, byte for byte what was frozen for seed 59 (`params_sha256`
   `60116de4cede436c574b91b15a74a7f0c5561790ac6f61cf9181a8317575fe95`, its own nested `v1` included). Scoring with
   `{**rules, "score": rules["score"]["v1"]}` or `rules["score"]["v2"]` gives `simon.score.v1` or `simon.score.v2` exactly
   as before. The detection hash leaves the `score` key out, so `detection_sha256`
   (`c92ae9a8524c559741cdaebcd14bb5305e91479d19123e15c3a5e14efb1337fb`) does not move.
6. **Schema 1.11.0** (additive, next minor after 1.10.0): `score.version` accepts `simon.score.v3`, `score.fault_cap` is 89
   or 79 under v3 and 89 under v2, the meaning of `score.uncapped` and `capped_by` is as in 1.10.0; a 1.10.0 document and
   every earlier one still validates. `docs/schemas.md`, `CONTRACT.md`, `part5 contract`, `part5 doctor` (which notes the score
   version and the ceiling in force), the goldens, and a sample for Part 7 of a take that reports two faults and hits the 79
   ceiling (`fixtures/output/analysis.double-capped.example.json`) carry it. `contracts/metrics.schema.json` accepts
   `simon.score.v3` in `report.score.version`.
7. **Going back to v1 is a command, for a v2 tree or a v3 tree.** `make score-fallback` (`scripts/make_score_fallback.py`)
   puts the `v1` block back as the `score` section, removes the v2 and v3 samples and writes the goldens and the fitness
   baseline again, as ADR-0018 item 6 says; it now accepts a tree that ships v3. The tests that depend on the shipped
   version read `tests/shipped_score.py`, so `make test` is green on either result.

### Calibration, on seed 5 only
`range_floor` is the value of ADR-0018's rule, unchanged, run on seed 5 under the v3 code: the lowest value on a 0.05 grid
from 0.50 to 1.00 for which, on seed 5 under the shipped detection, (i) every correct good-light take is an A, (ii) every
good-light take that reports exactly its one labelled fault scores 70 or above, (iii) every good-light take that reports
exactly its two labelled faults scores 75 or below, and (iv) the sweep never rises; if no value meets all four the floor is
1.00. The doubles are measured as v3 scores them, after the 79 ceiling. `python -m part5.score_report --calibrate-v3` runs
the rule (seed 5 only: it refuses any other set) and a test reproduces the shipped value from it. Its output is kept with no
hand nudge (Q1), and its table is recorded in `docs/thresholds.md`, "Score v3". Seed 5 is the only data the rule reads. The
two real knee-raise takes and the deadlift take are read once, read-only, and reported with v1, v2 and v3 columns; if a
reading tempts a change it is reported and not made (Q3). Disclosure (pre-freeze review R8): Q3 says the reading is made
after the freeze, and the lane made it at its end, at 70d1a40, before any freeze was recorded
(`docs/thresholds-score-v3.md`). No parameter could have moved on it: the floor is the output of the rule on seed 5, the
ceilings are ruled, and all three values equal v2's. The reading after the freeze is a repeat and is published as one, not as
a first look.

### Targets, fixed before seed 61
ADR-0018's five targets, verbatim, scored once on score seed 61 by `make score-heldout SEED=61` after the freeze. A target is
judged on the good-light takes of the seed, with the generator's labels:
1. Every correct take (no labelled fault) is an A. Gated by `make check-5` on its detection seed.
2. The monotonicity sweep (`foot_out`, `arms_wider`, `trunk_lean`, growing) never rises. Gated by `make check-5`.
3. No take that reports a fault grades A.
4. Single faults B or C: every take with one labelled fault that the take reports exactly (its one labelled fault found,
   nothing else reported) grades B or C.
5. Double faults C, D or F: every take with two labelled faults that the take reports exactly grades C, D or F.

A take whose reported faults differ from its labels (a miss or an extra fault) is a detection result, which ADR-0003
and `make check-5` own. It is counted and listed with its grade, not judged by 4 and 5, because a fault that was not
detected cannot be charged by any score and would make 4 fail by detection recall alone (target 4 was missed on 47 and
53, each time by takes graded A). The strict reading, every take of the slice and nothing excluded, is published beside
it as measured and is not a target.

**Fail closed (ruling of 2026-11-01T05:45Z, Q1; ADR-0003 #36), as ADR-0018 states it.** A target with no judged take does
not hold. If the seed has no correct good-light take (1), no take that reports a fault (3), no take that reports exactly its
one labelled fault (4) or exactly its two (5), or the sweep was not run (2), that target does not hold and the score does not
ship on it. For v3 the report says `all five hold: no` and its JSON carries `holds: false`; an empty target is never read as
one that was not failed.

The result is published whatever it is. v3 ships only if 1 to 5 all hold on seed 61 (the 05:00Z conditions above: correct
good-light takes stay A, the sweep stays monotonic, every target holds); if any does not, v1 stays, `make score-fallback`
puts the `score.v1` block back, seed 61 is retired and no further score series is opened in this run (Q4). The freeze is due
by 2026-11-02T06:00Z; no freeze by then means v1 stays and this branch is kept unmerged.

**Targets 2, 3 and 5 are settled before seed 61 is generated; only 1 and 4 test anything on it.** Every take target 3 judges
reports at least one fault, so the ceiling of 89 puts it at B or lower; every take target 5 judges reports exactly two
faults, so the ceiling of 79 puts it at C or lower. A failure of 3 or 5 could only come from a ceiling that was not applied
(a code defect). Target 2, the sweep, is built by `run_sweep` on one fixed take with `random.Random(1234)` and never reads
the score seed, and it was measured as a pass on the frozen code (seed 5 table, `docs/thresholds-score-v3.md`; `make check-5`
runs the same sweep). A pass on 2, 3 and 5 therefore shows that the ceilings are applied and the sweep did not rise; it does
not show that the curve, the weight or detection are right. The targets that can be missed on seed 61 are 1 (a correct take
below A, the similarity term) and 4 (an exactly reported single fault below 70, or at A by another route). The report
prints this sentence in its comparability line (`COMPARABILITY_V3`).

**Published beside the targets, as measured and not as a target.** The report prints, and the publication of seed 61
carries:
- for each take that reports exactly its two labelled faults, its value before the 79 ceiling (`score.uncapped.value`, or
  the value itself when the ceiling did not lower it) and its value after, and how many of those takes the ceiling lowered;
- ADR-0007's reading of the double-fault slice, D or F, as a count: how many of those takes grade D or F, how many C (the
  grade ADR-0018 and this ADR allow), so a reader sees how far the ceiling, not the curve, put them where they are;
- the strict slice verdicts (good/0 A, good/1 B or C, good/2 C, D or F), every take of the slice and nothing excluded;
- the comparability sentence: by the recorded v1 numbers (`fixtures/score-heldout.json`, seeds 47 and 53, measured under
  earlier detection rules) v1 itself would have met targets 1, 3, 4 and 5 (every good/1 A there was a fault not detected,
  every good/1 minimum was 72 or more, every good/2 grade was D or F), so a pass on seed 61 shows that v3 does not break those
  targets, not that it fixes v1's recorded misses; with the statement above that targets 2, 3 and 5 are settled before the
  seed and only 1 and 4 test anything on it;
- what the ceiling counts: the entries of the take's `faults` list. Detection (`part5/detect.py`) merges the left and right of
  one measure into one `both` entry only for the same direction with overlapping frames; otherwise they are two entries, and
  two entries put the 79 ceiling on the take. The report prints this too.

### The freeze record for seed 61
Follows ADR-0007 and ADR-0018, with the seed and the version changed. The score params are frozen before seed 61 is
generated, and `make check-5` refuses a `score` block that differs from what is recorded. The orchestrator records the freeze
in `fixtures/score-heldout.json` under `freezes`, `{version: simon.score.v3, freeze_commit, params_sha256, seed: 61}`, with
`params_sha256` the hash `python -m part5.score_report --params-sha256` prints.
- `make score-heldout SEED=61` refuses (exit 2) until one v3 freeze entry exists whose hash is the shipped block's and the
  rules ship v3, and accepts 61 once it does. It also refuses unless the freeze entry names its `freeze_commit`, the working
  tree is clean (no uncommitted change and no untracked file anywhere: the scorer runs from the repository root, where an
  untracked `numpy.py` would shadow the real import; the gitignored `out/` and `.venv/` are not seen) and `git diff
  <freeze_commit> HEAD` is empty under `part5`, `scripts`, `contracts`, `fixtures/input/expected`,
  `fixtures/input/expected-feet`, `pyproject.toml`, `uv.lock` and `Makefile` (the score code, the trainer's clips, the
  dependencies and the Makefile that starts the run are frozen with the params, recheck N3 and R-b of ADR-0018, pre-freeze
  review R2 and R3 of ADR-0019). The commit that records the freeze touches `fixtures/score-heldout.json` and
  `docs/thresholds.md` only, so it passes. One freeze, one generation: seed 61 is refused when the record holds more than
  one v3 freeze entry and when `out/score-heldout/seed-61/` already exists. That directory check is per checkout, so seed 61
  is scored from one named checkout and its attempt line is committed at once.
- While a score with a ceiling (v2 or v3) ships, any other seed that is not recorded is refused too (pre-freeze review R4;
  Q4, no third series in this run): the script generated any unrecorded seed before, so a fresh held-out-equivalent set could
  be scored before the freeze.
- After scoring the script prints `scored_at` (`git rev-parse HEAD`), `holds` (the JSON report's `targets_v2.holds`; the key
  is named for the ADR that fixed the five targets, and v3 reuses it) and the exact JSON line to append to `attempts`, with
  `version` `simon.score.v3`, `freeze_commit`, `params_sha256`, `scored_at`, `holds`, the commands, the labels hash, the
  slices, the targets and the measures published beside them. Once it is there, seed 61 is retired.
- Seed 59 is retired: it is recorded (a v2 attempt, `holds` false) and the script refuses every recorded seed. A seed that
  is a detection held-out seed (29, 31, 37, 67, 71, 73) is refused as before.
- `make check-5` takes the recorded hash for the version the shipped block names: a v3 block needs its freeze, a v2 block its
  own, a v1 block the newest v1 attempt (an attempt without a `version` is v1, unless it is for seed 59 or 61 or carries a
  freeze's hash). It refuses a v3 block (exit 2, pointing to `make score-fallback`) whose recorded v3 attempt has `holds`
  false or does not record `holds`; an attempt is v3's when it says so, is for seed 61 or carries the v3 freeze's hash. A
  version is judged by its own attempt only: a v3 block is never judged by v2's failed attempt on 59 and the reverse. Two
  more refusals close a retune after the seed was scored (pre-freeze review R1): a record that holds more than one freeze of
  the version is refused (the newest would otherwise let a block that was never scored pass), and the shipped hash must equal
  the `params_sha256` of the version's recorded attempt.

## Consequences
- **Positive**: a take that reports two or more faults cannot read above C and one that reports a fault cannot read A, so
  the grade agrees with the fault list the viewer reads; the weight of ADR-0018 still makes a fault on a measure the
  exercise does not move cost less than one on a measure it does; v1 and v2 stay reproducible from the rules.
- **Negative**: any two faults, however small, cap the take at C and any one at B, so A means "no fault reported" and B or C
  say little about how much was missed; they depend on detection recall and on how detection splits one error into
  entries. A v1, v2 and v3 value are not on one scale.
- **Neutral**: detection, its thresholds, `detection_sha256` and every detection seed are untouched; faults, near misses,
  warnings and status of all 156 seed 5 takes are byte-identical to those of main before v3
  (`fixtures/seed5-detection-baseline.json`). Part 7 reads `capped_by` as before, and compares `score.value` only within one
  `score.version` (CONTRACT.md duty 10). `fault_cap` is 89 or 79 under v3: a reader that treats it as the constant 89 must
  read it as the ceiling in force (told to Part 7 before this lands; TICKET-120 waits on it).

## Assumptions
- Seed 5's two-fault takes are a fair proxy for the relief posture faults can take; under v3 the question for doubles is
  settled by the ceiling, and the floor only has to keep singles at 70 or above. Evidence is the generator's fault model
  (ADR-0007 Assumptions).
- The synthetic feet are a proxy for Part 2's estimated feet (ASM-013): the foot weight is judged on them.

## Reversal Cost
Medium, and prepared: `make score-fallback` is the command for a v3 tree as it was for a v2 tree,
`tests/test_score_fallback.py` tests it, and a throwaway copy of the tree with the v3 freeze and a simulated seed 61
attempt was rolled back with it and passed `make test` (`docs/thresholds.md`, "Score v3"). What it cannot do is publish
seed 61's result, which is written by hand.

## Pre-Mortem (MANDATORY)
1. The sweep (target 2) rises across the step from one to two reported faults (a larger fault is reported as two entries, a
   smaller one as one). Likelihood: L, Impact: M, Mitigation: the sweep reads no score seed (one fixed take, `Random(1234)`),
   so it is settled before seed 61: it was measured under the v3 code on seed 5 and by `make check-5`, and a change that made
   it rise would show there before the freeze.
2. Seed 61 misses target 4: an exactly reported single fault lands below 70. Likelihood: L, Impact: M, Mitigation: the floor
   rule's condition (ii) and ADR-0007's worst-single rule; v3's single-fault values equal v2's, which held on seed 59.
3. A pass on 3 and 5 is read as evidence about the curve. Likelihood: M, Impact: M, Mitigation: this ADR says they hold by
   construction; the report prints the pre-ceiling values, the count the ceiling lowered and ADR-0007's D or F reading beside
   them; the publication repeats it.
4. Someone retunes `range_floor`, or edits the score code, after seeing seed 61. Likelihood: L, Impact: H, Mitigation: the
   freeze record and `params_sha256` in every output; `make check-5` exits 2 on a changed block, on a second freeze of the
   version and on a block that differs from the one the recorded attempt was scored with; seed 61 is refused unless the tree is
   clean and the code under the frozen paths (`part5`, `scripts`, `contracts`, the trainer's clips, the dependencies and the
   Makefile) is the freeze commit's, and any other unrecorded seed is refused while v3 ships.
5. Seed 61 fails and the fallback is done by hand, leaving the goldens and many tests red under the deadline. Likelihood: M,
   Impact: H, Mitigation: `make score-fallback` handles a v3 tree, version-aware tests, proven on a throwaway copy before the
   freeze.
6. A failed v3 is accepted again after a hand revert because the block hashes to the freeze. Likelihood: L, Impact: H,
   Mitigation: the attempt records `holds`; `make check-5` refuses a v3 block whose attempt has it false or lacks it.
7. Part 7 draws a v1, v2 and v3 value on one axis, or reads `fault_cap` as the constant 89. Likelihood: M, Impact: M,
   Mitigation: `score.version` is in every score, `part5 doctor` names it and the ceiling in force, CONTRACT.md duty 10
   says so, and Part 7 is told of 79 before it lands.
8. A ceiling by count is decided by detection splitting one error into two entries, so the grade follows detection and not how
   much was missed. Likelihood: M, Impact: M, Mitigation: none in the score, as ruled. Detection merges the left and right of
   one measure into one `both` entry only for the same direction with overlapping frames (`part5/detect.py`); without them,
   or in two directions, there are two entries and the 79 ceiling applies. The count is of entries; the report says so, and
   lists the takes whose reported faults differ from their labels. A severity-aware cap is a new family (TICKET-053).

## Dissent (MANDATORY)
Reviewed by: score v3 lane (the author; the independent review is the pre-freeze review the ruling names)
Concerns:
- A ceiling of 79 for two faults of any size is as blunt as 89 for one: ruled (Q1); the points under the ceiling still rank
  takes by how much they missed, and the timeline still shows each miss.
- Targets 2, 3 and 5 cannot fail on seed 61, so "all five hold" is easier than it reads (only 1 and 4 test anything): stated
  above, with the measures that can show the ceiling doing the work published beside them, and the strict verdicts and the
  comparability sentence repeated.
- v3 is designed after seeing seed 59's miss: disclosed in Context; seed 59 is not fitted to and is retired, and only seed
  61 is unseen. A pass on 61 is one more held-out seed, not a proof for real takes (the real takes are no target; they were
  read before the freeze and are read again after it, see the disclosure under Calibration).
- The reconciliation leaves the two real knee raises at F, as v2 did: Q3 keeps a window cost ceiling out of v3 because
  nothing yet shows their faults are false; TICKET-053 holds it, amended to a third score series.

## Pre-freeze review corrections (2026-11-01)
The independent pre-freeze review (`progress/review-20261101-prefreeze-score-v3.md`, NEEDS_WORK at 70d1a40) found the statements
and mechanisms below wrong or open. None changes a target, a parameter or `params_sha256` (`4261f8d7...`); the corrections
were made before the freeze and are dated here because the ADR was committed before the code.
- R1: `make check-5` refuses a record with more than one freeze of the shipped version and a block whose hash differs from the
  recorded attempt's `params_sha256` (Decision, freeze record).
- R2, R3: the `Makefile` joins the frozen paths, and the clean-tree check covers the whole tree with untracked files.
- R4: unrecorded seeds other than 61 are refused while a score with a ceiling ships; the seed is scored from one named checkout.
- R6: target 2 is settled before seed 61, not testable on it (Decision, targets); R7: the entry count is stated exactly (Decision
  and pre-mortem 8); R8: the real takes were read before the freeze (Calibration).
- R13: `part5.output.validate_analysis` checks that `score.fault_cap` equals the ceiling in force for the faults the document
  reports.

## Code Backlinks (updated as code is written)
- `part5/score.py` (ceilings by count, `block_v3`, `rules_v2`, version helpers), `part5/score_report.py` (v3 targets, the
  measures beside them, `--calibrate-v3`), `part5/check.py` (freeze and `holds` by version), `scripts/make_score_heldout.py`
  (seed 61, the frozen code), `scripts/make_score_fallback.py` (a v3 tree), `part5/rules.json` (`score`)
