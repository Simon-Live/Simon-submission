# ADR-0018: Score v2 (simon.score.v2): misses weighted by the trainer's range, and a ceiling for a take that reports a fault
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted, then not shipped: scored once on score seed 59 (2026-11-01, `make score-heldout SEED=59` at 0aba974,
exit 0), target 5 failed (3 of 10 exactly reported doubles scored B), so `holds` is false and `make score-fallback` put
`score.v1` back as the shipped score; the v2 code stays in the tree, version-aware; seed 61 stays reserved for a new
approach family (TICKET-053). Numbers: `docs/thresholds.md`, "v2 held-out result: seed 59".
Date: 2026-10-31
Amends: ADR-0007 (the score curve). ADR-0013 (the score is the mean of its windows) is kept as it is.

## Context
`simon.score.v1` (ADR-0007) charges every miss by its size alone: `min(cap, base + slope * (r - 1))`, weighted by its
duration and coverage, with `base` 16 so that no counted fault is cheap. Two kinds of real take, both reported by
reference and never copied into the tree or tuned on (TICKET-047), pull in opposite directions:

- Part 7 reports two real people doing a knee raise correctly (TICKET-161): 44 F with 2 faults and 30 F with 4 faults,
  each miss costing 12 to 22 points. These are Part 7's figures at their own time, before attempts 4 and 5 changed which
  faults real takes get (TICKET-047 waits for that); this checkout, with attempt 5's detection, reads the same two takes as
  45 F with 2 faults and 25 F with 5 faults. The open question in the ticket is whether those faults are ones a viewer
  would call faults.
- moalborati/simon#59, a real Romanian deadlift, reports its hinge fault in one rep of two and scores 93 (A). The reporter
  calls the difference clearly visible. The mean of the windows (ADR-0013) lets one faulted window under a clean one
  stay an A.

ADR-0007's targets (single faults B or C, double faults D or F) were calibrated on synthetic takes. On its own held-out
score seeds 47 and 53 the double-fault target held and the single-fault target was missed (one and two of the 60
good-light single-fault takes graded A, `fixtures/score-heldout.json`). Seeds 41 and 43 were seen by the prototype; 47 and
53 are scored and retired; 59 and 61 are reserved for score retries (ADR-0007, ADR-0017).

Ruling (stakeholder-proxy, 2026-11-01T05:00Z, confidence medium), verbatim:

> "TICKET-047 under (d): a new score family simon.score.v2 (each miss weighted by how much the trainer moves that
> measure in its window, with a floor; a take that reports a fault scores at most 89; the take stays the mean of its
> windows per ADR-0013, no worst windows) in a new ADR amending ADR-0007 with targets fixed before seed 59; tuned on seed
> 5 only, frozen by 2026-11-02T06:00Z, scored once on score seed 59 and published pass or fail; it ships only if correct
> good-light takes stay A, the sweep stays monotonic and every target holds, otherwise v1 stays and 61 stays reserved; no
> freeze by the cutoff means (a); detection, thresholds and detection seeds untouched; check-5 on seed 73 must exit 0
> with detection metrics and detection_sha256 byte-identical."

Part 7, the consumer, answered on 2026-10-31: `capped_by` keeps its meaning exactly (the low-match warning cap only);
`score.uncapped` means the value before every cap; a sample document under v2 is wanted.

Ruling of 2026-11-01T05:45Z (stakeholder-proxy, confidence medium, STATUS.md Decisions), after the pre-freeze review:
Q1 targets 4 and 5 stand as committed in 7a1c344 (judged on takes that report exactly their labelled faults; mismatched
takes counted and listed with their grades; the strict reading published beside as measured, not a target), plus one
fail-closed clause added before the freeze (below); Q2 `range_floor` is the rule's output with no hand nudge; Q3 v2 ships
on seed 59's verdict alone; Q4 the foot measures take the range weight before the freeze.

## Options Considered
### Option 1: (a) v1 stays
- Pros: nothing to freeze; the record of 47 and 53 stands.
- Cons: the two real-take complaints stay open. This is also the outcome if v2 misses its cutoff or its targets.
- Effort: none.
### Option 2: (d) v2, as the ruling words it
- Pros: it is aimed at the two complaints with two small, readable rules (the weight at faults on measures the exercise
  does not move, the ceiling at a faulted take that reads A); a miss still costs points on every measure (the floor);
  detection is not touched. How far it reaches on the real takes is measured after tuning (Consequences).
- Cons: a take that reports any fault is at most a B, however small the fault.
- Effort: Medium.
### Option 3: retune v1's `base`, `slope` and `cap`
- Pros: no new field.
- Cons: a single curve cannot be gentler on the knee raise and harsher on the deadlift; ruled out by the proxy.
- Effort: Low.

## Decision
Option 2. `score.version` becomes `simon.score.v2`; the formula is v1's with two changes and one new field. Everything
not named here is v1 as ADR-0007 and ADR-0013 state it: the penalty curve (`base`, `slope`, `cap`), the similarity term
(`z0`, `z1`, `s_max`), the bands (A 90 and above, B 80 to 89, C 70 to 79, D 60 to 69, F below 60), the windows, the
tempo charge of the dance profile, and the warning cap of 59 (ADR-0012).

1. **Weight by the trainer's range.** A miss costs `penalty(r) * (0.5 + 0.5 * dur) * coverage * w`, with
   `w = min(1, max(range_floor, u / range_full))` and `u` the trainer's range of the missed measure in the window, in
   thresholds: (max - min over the finite values of the trainer's series of that measure on the window's expected
   frames) divided by that measure's detection threshold. `range_full` is 3: a measure the trainer moves by three of its
   own thresholds is one the exercise is about and costs in full. The measure is the fault's own series: `{side}_{measure}`
   for `left` or `right`, the larger of the two sides' ranges for `both`, the bare name for `center`. A window is what
   ADR-0013 says (a rep, or a slice of about 5 s), so a rep take uses the reference rep's range. The foot measures
   (`foot_rotation`, `ankle_inversion`) take the same weight (ruling of 05:45Z, Q4): the trainer's foot series, the compared
   foot measures on the expected clip's own frames (`pipeline._foot_series`; for a rep take, the reference rep's slice of
   them), are part of the score's input beside the body measures, and the similarity term still reads the body measures
   only. `w` is 1 only where no trainer series exists (no feet file, a foot measure that was not compared) or the series
   has no finite value in the window: the miss then costs what v1 charged. `w` is at most 1, so no miss costs more than in
   v1 and ADR-0007's rule that the worst single good-light fault still lands at 70 or above holds with v1's `base`,
   `slope` and `cap` (it is measured on seed 5 and reported). Detection reads none of this and is byte-identical
   (`fixtures/seed5-detection-baseline.json`).
2. **A ceiling for a take that reports a fault.** When `analysis.faults` is not empty the value is at most `fault_cap`,
   89 (the top of B). It is applied to the mean of the windows (ADR-0013), once; there is no worst-window rule. A take
   with faults on which nothing could be measured (value 0) still carries `fault_cap`.
3. **A new field, `score.fault_cap`.** An integer, present only when the take reports at least one fault, in v2: the
   highest value such a take can score, in force whether or not it lowered this value. `capped_by` is not touched: it
   lists the warning codes of the low-match cap and nothing else (Part 7 reads it as a low-match warning).
4. **`score.uncapped` means the value before every cap.** `{value, grade}` of the mean of the windows before the fault
   cap and before the warning cap (ADR-0012), written when either cap lowered the value. With both, it is the value
   before the first. A faulted take with no warning that the fault cap lowered has `uncapped` and no `capped_by`.
5. **Schema 1.10.0** (additive, next minor after 1.9.0): `score.fault_cap`, `score.version` accepts `simon.score.v2`,
   the meaning of `score.uncapped`; a 1.9.0 document and every earlier one still validates. `docs/schemas.md`,
   `CONTRACT.md`, `part5 contract`, `part5 doctor` (which notes the score version and that `score.value` compares only
   within one `score.version`), the goldens and a sample analysis under v2 (a faulted take that hits the cap,
   `fixtures/output/analysis.fault-capped.example.json`) carry it.
6. **v1 stays reproducible, and going back to it is a command.** `part5/rules.json` keeps its `score` section the only place
   the params live (the detection hash leaves that key out, so `detection_sha256` does not move). The v2 block repeats v1's
   numbers at its top level (a test pins that they are equal) and carries the frozen v1 block verbatim as `score.v1`,
   whose `params_sha256` is the one `fixtures/score-heldout.json` recorded for seeds 47 and 53. Scoring with
   `{**rules, "score": rules["score"]["v1"]}` gives `simon.score.v1` exactly as before. Making v1 the shipped score again is
   more than that substitution (the goldens, the baseline and the tests that pin a v2 value follow the score in the rules),
   so it is prepared and tested before the freeze: `make score-fallback` (`scripts/make_score_fallback.py`) puts the `v1`
   block back as the `score` section, removes the v2 sample and writes the goldens and the fitness baseline again; the
   tests that depend on the shipped version read it (`tests/shipped_score.py`); `part5.check.recorded_score_hash` finds the
   frozen hash by the version the rules ship, so a v1 `make check-5` finds `e818635b` however many v2 entries and attempts
   the record holds. It was run on a throwaway copy with the v2 freeze and a simulated seed 59 attempt in the record:
   the score is v1, `make test` exits 0 and the check's score lookup passes (`docs/thresholds.md`, "Score v2").

### Calibration, on seed 5 only
Two numbers are new. `range_full` 3 and `fault_cap` 89 are design constants (the second is the ruling's), not fitted.
`range_floor` is fitted by a rule fixed here, before any tuning: the lowest value on a 0.05 grid from 0.50 to 1.00 for
which, on seed 5 under the shipped detection, (i) every correct good-light take is an A, (ii) every good-light take that
reports exactly its one labelled fault scores 70 or above (ADR-0007's worst-single rule), (iii) every good-light take
that reports exactly its two labelled faults scores 75 or below, five points under 80 (the lowest B) so that milder doubles
on another seed still land at C or lower, and (iv) the sweep never rises. If no value meets all four the floor is 1.00 (v2
is then v1 plus the ceiling). The rule is a function in `part5/score.py` that `python -m part5.score_report
--calibrate-v2` runs (on seed 5 only: it refuses any other set), and a test reproduces the shipped value from it. Seed 5 is
the only data the rule reads. The two knee-raise takes and the deadlift take are read once at the end, read-only, to report
their v2 scores; if that tempts a change it is reported and not made. When the foot weight landed (Q4) the rule was run
again on seed 5, unchanged, and its output kept (Q2): the same floor and the same table.

Disclosure of a wording change made after the first tuning commit. Commit 7a1c344 (before any tuning) explained condition
(iii)'s 75 as "five points under the top of C", which reads as 74. The commit that set `range_floor` (3fe95f3) changed the
explanation to "five points under 80 (the lowest B)". The number 75 and the constant `DOUBLE_MAX` 75 did not change in any
commit, and no target's meaning changed, but the measured highest double at floor 0.75 is exactly 75, so on a reading of
74 the rule would have chosen 0.80. The rule's output is the one the code gives; the publication of seed 59 repeats this
paragraph.

### Targets, fixed before seed 59
Scored once on score seed 59, by `make score-heldout SEED=59`, after the freeze (below). A target is judged on the
good-light takes of the seed, with the generator's labels:
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

**Fail closed (ruling of 2026-11-01T05:45Z, Q1; ADR-0003 #36).** A target with no judged take does not hold. If the seed
has no correct good-light take (1), no take that reports a fault (3), no take that reports exactly its one labelled fault
(4) or exactly its two (5), or the sweep was not run (2), that target does not hold and v2 does not ship on it. The report
says `all five hold: no` and its JSON carries `holds: false`; an empty target is never read as one that was not failed.

The result is published whatever it is. v2 ships only if 1 to 5 all hold on seed 59; if any does not, v1 stays, `make
score-fallback` puts the `score.v1` block back as the `score` section, and seed 61 stays reserved for a retry with a new
approach family. The freeze is due by 2026-11-02T06:00Z; no freeze by then means v1 stays.

**What a pass shows (the publication carries this sentence beside the strict good/1 verdict).** By the recorded v1 numbers
(`fixtures/score-heldout.json`, seeds 47 and 53, measured under earlier detection rules) v1 itself would have met targets 1,
3, 4 and 5: every good/1 A there was a fault that was not detected, every good/1 minimum was 72 or more, every good/2
grade was D or F. A pass on seed 59 therefore shows that v2 does not break those targets; it does not show that v2 fixes
v1's recorded misses. `python -m part5.score_report` prints the same sentence under its targets.

### The freeze record
Follows ADR-0007: the score params are frozen before seed 59 is generated, and `make check-5` refuses a `score` block
that differs from what is recorded. The orchestrator records the freeze in `fixtures/score-heldout.json` under a new
top-level `freezes` list, `{version, freeze_commit, params_sha256, seed: 59}`, with `params_sha256` the hash
`python -m part5.score_report --params-sha256` prints. `make score-heldout SEED=59` refuses (exit 2) until a v2 freeze
exists whose hash is the shipped block's, and accepts 59 once it does; seed 61 is refused as reserved. The result is
appended to `attempts` as 47 and 53 were, with `version: simon.score.v2`; once it is there seed 59 is retired, and no test
of the committed record depends on it being absent. `check-5` takes the recorded hash for the version the shipped block
names: a v2 block needs its freeze, a v1 block the newest v1 attempt (an attempt without a `version` is v1).

The score code is frozen with the params, not the params alone (recheck N3): `make score-heldout SEED=59` also refuses unless
the freeze entry names its `freeze_commit`, the working tree is clean (no uncommitted change, no untracked file under the
paths below) and `git diff <freeze_commit> HEAD -- <paths>` is empty, the paths being the code (`part5`, `scripts`,
`contracts`), the trainer's clips and feet the score is measured against (`fixtures/input/expected`,
`fixtures/input/expected-feet`) and the dependencies (`pyproject.toml`, `uv.lock`). The commit that records the freeze touches
`fixtures/score-heldout.json` and `docs/thresholds.md` only, so it passes. One freeze, one generation: seed 59 is also refused
when the record holds more than one v2 freeze entry (a re-freeze and rescore after seeing the seed) and when
`out/score-heldout/seed-59/` already exists. After scoring the script prints `scored_at` (`git rev-parse HEAD`), `holds` (the
JSON report's `targets_v2.holds`) and the exact JSON line to append to `attempts`, with `version` `simon.score.v2`,
`freeze_commit`, `params_sha256`, `scored_at`, `holds`, the commands, the labels hash, the slices and the targets.
`make check-5` refuses a v2 block (exit 2, pointing to `make score-fallback`) whose recorded v2 attempt has `holds` false, or
does not record `holds` (fail closed); without this a reverted fallback would hash to the freeze again and be accepted. An
attempt is v2's when it says so, is for seed 59, or carries the v2 freeze's hash, so a failed attempt recorded without its
`version` is caught all the same. A v1 block is never judged by a v2 attempt: v1 shipped with its misses on record (ADR-0007).

## Amendments
- 2026-11-01, ADR-0019: seed 59 missed target 5 and v2 did not ship; `simon.score.v3` keeps this ADR's range weight and its
  ceiling of 89 for a take that reports one fault, adds a ceiling of 79 for two or more, and reuses this ADR's five targets
  and its fail-closed clause on seed 61. The v2 block stays in `part5/rules.json` as `score.v2`, byte for byte
  (`params_sha256` `60116de4...`), the v2 code stays version-aware, and `make score-fallback` accepts a v3 tree. Seed 61 is
  no longer reserved for a new approach family; it is v3's seed.

## Consequences
- **Positive**: a take that reports a fault is never an A, so the grade agrees with the fault list the viewer reads; a
  fault on a measure the exercise does not move costs less than a fault on one it does, and still costs, for the foot
  measures as for the body's.
- **Negative**: any fault, however small, caps the take at B; A now means "no fault reported", so it depends on
  detection recall. A v1 value and a v2 value are not on one scale.
- **Neutral**: detection, its thresholds, `detection_sha256` and every detection seed are untouched; faults, near misses,
  warnings and status are byte-identical before and after on all 156 seed 5 takes
  (`fixtures/seed5-detection-baseline.json`). Part 7 reads `capped_by` as before, and compares `score.value` only within
  one `score.version` (CONTRACT.md duty 10, as it does within one `profile`).
- **Measured after tuning** (seed 5 only tuned; the real takes read once afterwards, read-only, never tuned on): the
  deadlift goes from 93 A to 89 B (`fault_cap` 89, `uncapped` 93 A), as the reporter asked; the two knee raises stay F
  (45 F to 53 F, and 25 F to 40 F), because most of their misses are on measures the trainer moves a lot and each rep
  window carries two to five misses. v2 therefore does not answer the knee-raise complaint; that is a measured limit,
  reported to Part 7, and a new family (TICKET-053, seed 61) holds it.

## Assumptions
- Seed 5's two-fault takes are a fair proxy for how much relief posture faults can take before a double reads as B.
  Evidence is only the generator's fault model (ADR-0007 Assumptions); real takes are read after tuning and reported.
- The synthetic feet are a proxy for Part 2's estimated feet (ASM-013): the foot weight is judged on them.

## Reversal Cost
Medium, and prepared: `make score-fallback` is the command, `tests/test_score_fallback.py` tests it, and a copy of the tree
with the v2 freeze and a simulated seed 59 attempt in the record was rolled back with it and passed `make test`
(`docs/thresholds.md`). What it cannot do is publish seed 59's result, which is written by hand. Without the script and the
version-aware tests it would be a one-line substitution followed by about twenty red tests (goldens, the sample, the
shipped-block tests), the pre-freeze review's measure; that is why it was built before the freeze.

## Pre-Mortem (MANDATORY)
1. Seed 59 misses target 5 because the floor was fitted to seed 5's doubles. Likelihood: M, Impact: M, Mitigation: the
   five-point margin in the rule; a miss is published and v1 stays by `make score-fallback`.
2. The ceiling is read by a viewer as "your best is a B". Likelihood: M, Impact: M, Mitigation: `fault_cap` and
   `uncapped` say why; Part 7 owns the wording.
3. Someone retunes `range_floor`, or edits the score code, after seeing seed 59. Likelihood: L, Impact: H, Mitigation: the
   freeze record and `params_sha256` in every output; `make check-5` exits 2 on a changed block; seed 59 is refused unless
   the code under `part5`, `scripts` and `contracts` is the freeze commit's; seed 61 needs a new family.
4. The synthetic feet misjudge the foot weight: a real trainer's foot series is noisy, so its range reads large and the
   weight sits at 1, or the synthetic one is flat and the weight sits at the floor for every foot fault. Likelihood: M,
   Impact: L, Mitigation: the steadiness gate (`max_jitter_deg`) already drops a jittery foot measure from the comparison
   and so from the series; the foot slices of seed 5 are reported; ASM-013.
5. Seed 59 fails and the fallback is done by hand as a one-line substitution, leaving the goldens and about twenty tests
   red under the deadline. Likelihood: M, Impact: H, Mitigation: `make score-fallback`, tested, with version-aware tests;
   proven on a throwaway copy before the freeze.
6. Part 7 draws v1 and v2 values on one axis. Likelihood: M, Impact: M, Mitigation: `score.version` is in every score,
   `part5 doctor` notes it and that `score.value` compares only within one `score.version`, CONTRACT.md duty 10 says so.
7. A strict reading of seed 59 is mistaken for the target, or the comparability sentence is left out of the publication.
   Likelihood: M, Impact: M, Mitigation: the report prints both and the sentence; this ADR fixes the wording.
8. Seed 59 fails, the fallback is reverted by hand, and `make check-5` accepts v2 again because the block hashes to the
   freeze. Likelihood: L, Impact: H, Mitigation: the attempt records `holds`; `make check-5` refuses a v2 block whose attempt
   has it false or lacks it.

## Dissent (MANDATORY)
Reviewed by: score v2 lane (the author; the independent review is the consolidated review)
Concerns:
- A trainer who holds a measure still is exactly when a deviation is a posture fault, so weighting by movement can be
  read the wrong way round: kept as the ruling words it, with a floor so a posture fault still costs, and the floor
  fitted so doubles stay at C or lower.
- Targets 4 and 5 exclude takes whose faults differ from their labels, which makes them easier to meet: stated above, the
  strict numbers are published beside them, the exclusion is the detection gate's business, and the ruling of 05:45Z
  ratified it with the fail-closed clause.
- A ceiling of 89 turns a graded curve into "B or lower" for every faulted take: ruled; the points below 89 still rank
  takes by how much they missed.

## Code Backlinks (updated as code is written)
- `part5/score.py` (weights, ceiling, `uncapped`), `part5/score_report.py` (targets, fail-closed, trainer feet),
  `part5/pipeline.py` (`foot_expected`), `part5/check.py` (freeze lookup by version, `require_v2_held`),
  `scripts/make_score_heldout.py` (seeds 59 and 61, the frozen code, `scored_at` and `holds`), `scripts/make_score_fallback.py` (going back to v1), `part5/rules.json` (`score`)
