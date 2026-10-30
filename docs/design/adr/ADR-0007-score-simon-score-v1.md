# ADR-0007: Score out of 100 with a grade (simon.score.v1)
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-30

## Context
Operator directive of 2026-10-30: the journey ends with "a score out of 100 with a grade from A to F". Part 5 finds
faults with frozen detection rules (ADR-0003, freeze `fbb0bea`) and has no overall number. A research prototype of
2026-10-30 (session scratchpad `journey-b/score/`) calibrated a score on seed 5 and printed per-slice grades on seeds 5,
31, 41 and 43, and a sweep showed scores falling as one fault grows. Seeds 29, 31 and 37 belong to the threshold
protocol; 41 and 43 were seen by the prototype. `make check-5` refuses a `part5/rules.json` whose sha256 differs from
the freeze record, so adding a `score` block to that file would break the check unless the check changes.

## Options Considered
### Option 1: fault penalties plus a small similarity term (the prototype)
- Pros: explains itself (the faults cost the points), monotonic in fault size by construction, a correct take keeps
  100 unless it is broadly off; the prototype already ran.
- Cons: calibrated on synthetic takes; four params.
- Effort: Medium
### Option 2: similarity only (mean z over all measures mapped to 0 to 100)
- Pros: one param pair; no dependence on detection.
- Cons: a clear single fault and diffuse sloppiness read the same; grades do not line up with the faults the viewer
  reads.
- Effort: Low
### Option 3: a learned model on labelled takes
- Pros: could fit human judgement.
- Cons: no human-graded takes exist; README rule maths only.
- Effort: High

## Decision
Option 1, exactly as `docs/design/specs/journey-followup.md` J-4 states it: per-fault penalty
`min(cap, base + slope * (r - 1))` weighted by `0.5 + 0.5 * dur` and by coverage, a similarity term of at most
`s_max` points from every measure aligned through `exp_to_fol`, `value = clamp(round_half_up(100 - F - S), 0, 100)`,
bands A 90+, B 80 to 89, C 70 to 79, D 60 to 69, F below 60, `null` on a refused take.
- Calibration: seed 5 only, by the prototype's rules (`z0` the 95th percentile of correct good-light takes, `z1`
  the worst seed 5 take, `s_max` 4, `base` so the smallest counted fault costs more than 10 points, `slope` so the
  worst single good-light fault still lands at 70 or above). Params in `part5/rules.json` under `score`;
  `params_sha256` in every output.
- Held-out claim: seeds 47 and 53, fresh, generated only after the score freeze commit, scored once each, recorded
  as measured. Targets (reported, never tuned on): correct good-light takes all A; single faults B or C; double faults
  D or F; monotonic. A miss is published; a retry needs a new approach family and the next unused seed (59, then 61).
- Gate in `make check-5`: correct good-light held-out takes at A, and the monotonicity sweep. Everything else,
  low light included, is reported.
- Freeze check: `check-5` compares the detection rules, not the whole file. It hashes `part5/rules.json` without
  the `score` key as `json.dumps(rules, sort_keys=True, separators=(",", ":"))` and compares that with a
  `detection_sha256` recorded once in `docs/thresholds.md` "Score", computed the same way from
  `git show fbb0bea:part5/rules.json` (command and value recorded). The whole-file hash still passes on its own,
  so attempts recorded before this ADR verify unchanged. Changing any detection key still exits 2.

## Consequences
- **Positive**: Part 7 gets one explainable number; the faults and the score never disagree in direction.
- **Negative**: the number inherits the generator's fault model; low light is not graded.
- **Neutral**: a rules change now has two hashes to think about (detection and score); both are printed.

## Assumptions
- The prototype's `seed5.json` was collected from the committed seed 5 followers through this checkout's pipeline on
  2026-10-30; AC-S01 re-derives the params and explains any difference before the freeze.

## Reversal Cost
Low: `score` is one optional field and one module; dropping it leaves 1.2.0 readers working.

## Pre-Mortem (MANDATORY)
1. Held-out single faults score A because a fault went undetected. Likelihood: M (seen on seeds 31 and 43 in the
   prototype), Impact: M, Mitigation: reported per slice; the cause is detection recall, which the score must not hide.
2. Someone tunes `slope` after seeing seed 47. Likelihood: L, Impact: H, Mitigation: freeze commit and
   `params_sha256` recorded before generation; append-only `fixtures/score-heldout.json`.
3. The freeze-check change lets a detection edit through. Likelihood: L, Impact: H, Mitigation: a test edits one
   detection key and expects exit 2.

## Dissent (MANDATORY)
Reviewed by: journey follow-up lane (the author; the independent review is part of TICKET-038)
Concerns:
- Similarity from 22 measures double counts a fault already penalised: kept, because it is capped at 4 points and
  separates diffuse sloppiness from a clean take.
- A grade on synthetic data may mislead real users: the `check-5` output says `data_source: synthetic`, and real
  takes stay reported.
- Gating on the threshold protocol's held-out set: a regression gate only; the held-out claim is seeds 47 and 53.

## Code Backlinks (updated as code is written)
- `part5/score.py`, `part5/calibrate.py` (`--score`), `part5/check.py` (gate, freeze check), `part5/rules.json` (`score`)
