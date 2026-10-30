# ADR-0003: Held-out calibration on a new seed, and the check-5 gate
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28

## Context
The rule thresholds in `part5/rules.json` were tuned on the 96 seed 5 takes that also gate
`make check-5` (#36). In-sample, good light reads P = R = 1.00 at every angle with 0 faults on correct
takes; low light reads P 0.76, 0.57, 0.30 (front, 45, side) and R 0.93. That proves fit, not skill.
#15 asks for a held-out split. Team decision D3 on #18: gate on good light at front, 45 and side
(P >= 0.85, R >= 0.75, 0 faults on correct takes); low light and real takes are reported, never gated.

## Options Considered
### Option 1: k-fold on seed 5
- Pros: no new data.
- Cons: with 4 takes per fault type per slice, folds are tiny; the gate number is an average of folds,
  hard to state plainly.
- Effort: Medium
### Option 2: train and test split of seed 5
- Pros: matches #15's wording.
- Cons: halves an already small set; the test half shares the tuning half's random draws per take
  layout.
- Effort: Low
### Option 3: a new seed from the same generator as the held-out set
- Pros: a full-size set never seen during tuning; simple to state; deterministic.
- Cons: shares the generator's fault model (ASM-002).
- Effort: Low

## Decision
Option 3 (operator decision 3, held-out protocol amended 2026-10-28 after review).
- Seed 5 stays the tuning set (`fixtures/input/followers/`), regenerated once from the refreshed
  expected clips.
- Thresholds, guard limits and method changes are tuned on seed 5 only.
- Held-out seeds are fixed now, in order 29, 31, 37.
- Each attempt freezes `rules.json` and the code in one commit, writes the hash and a one-paragraph
  rationale to `docs/thresholds.md`, then generates the next unused seed once and scores it once.
- Every attempt's result, pass or fail, is published in `docs/thresholds.md` and in the `make check-5`
  JSON under `attempts[]`.
- A seed once scored is retired: never regenerated, rescored or used for tuning.
- A retry is allowed only for a distinct approach family (a new measure, a different alignment or
  persistence rule), never a threshold nudge alone.
- Still red after the last seed: the run ends DEGRADED with every attempt's numbers.
- After a green attempt, confirm on the next unused seed and report both. A red confirmation counts as a
  red attempt. A green attempt on seed 37 is reported green with "no seed left to confirm".
- The held-out set lives in `fixtures/input/heldout/` (own `labels.json`, which names its `seed`);
  `make heldout-data SEED=<n>` generates it and `make check-5` reads `gate.seed` from that file. The
  next attempt replaces the folder; a retired set stays in git history at the commit its `attempts[]`
  entry names.
- Gate: held-out `good/front`, `good/45`, `good/side`, each P >= 0.85, R >= 0.75, 0 faults on correct
  takes, and no gated slice empty (no takes, no labelled faults or no correct takes fails, as #36).
- Reported, never gated: seed 5 slices, low light, the dropout variant (`dropout/<angle>`), Part 3's
  kit and the stock takes. Refusals by the movement guard are counted per slice.
- `make check-5` exits 0 only when the gate passes.

## Consequences
- **Positive**: the gate states skill on unseen takes; the in-sample number stays visible beside it.
- **Negative**: the held-out number may be lower than 1.00 and may be red.
- **Neutral**: final thresholds and reasons go in `docs/thresholds.md` (#15).

## Assumptions
- ASM-002: seeds 29, 31 and 37 from the same generator are a fair proxy for unseen synthetic takes.

## Reversal Cost
Low: the gate set is a path and a seed in `part5/check.py`.

## Pre-Mortem (MANDATORY)
1. Someone retunes after seeing held-out numbers. Likelihood: M, Impact: H, Mitigation: the rule is in
   the brief, the spec and this ADR; each attempt's freeze commit predates its seed's generation commit,
   a scored seed is retired, and every attempt is published, so a quiet retune shows as a missing or
   reused seed.
2. Held-out passes but real takes fail. Likelihood: H, Impact: M, Mitigation: real takes are reported
   on every run and shown on staging.
3. A gated slice is empty after a generator change. Likelihood: L, Impact: M, Mitigation: an empty slice
   fails the gate.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect)
Concerns:
- Same generator, same fault model: accepted and stated in the check output (`data_source`).
- #15 says train and test split: a new seed is a split by seed; the DECISION comment says so.
- Seeds 29, 31 and 37 are arbitrary numbers: they are fixed now, before any tuning, and never changed.
- Three attempts invite a search over held-out seeds. Kept: a retry needs a new approach family, each
  seed is scored once, and every result, red ones included, is published beside the final one.

## Code Backlinks (updated as code is written)
- `part5/check.py`, `make heldout-data SEED=<n>` (`scripts/make_dummy_followers.py --seed <n> --out
  fixtures/input/heldout --dropout-variant`),
  `docs/thresholds.md`
