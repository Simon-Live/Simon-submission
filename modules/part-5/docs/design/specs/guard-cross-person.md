# Spec: the movement guard on cross-person takes, the cause measurement and a constructed cross-body population (research lane, draft)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.

Status on main (2026-11-02 wrap-up): this spec, ADR-0025 and docs/research/guard-cross-person.md are kept on main as the record of a stopped family; the `--cross-body` generator flag, the scripts and their tests stay on `lane/guard-family`, not merged.
Status: Stopped at step 4 by ADR-0025's clause S1 (the construction did not reproduce the real pattern; see `docs/research/guard-cross-person.md`,
"Step 4"); a research lane on `lane/guard-family`, nothing here is frozen, wired into `part5/` or merged
Date: 2026-11-02
Request Type: new-feature (research tooling, opt-in generator flag)
Risk Level: medium (no `part5/` file changes; the guard itself is untouched)
Tickets: TICKET-101 (the finding), TICKET-093 (the cross-person diagnosis). ADR: ADR-0025 (draft). Protocol: ADR-0003, ADR-0017.
Master spec: `part5-fault-analysis.md`. Assumptions: ASM-002.

## Overview
`part5/guard.py` caps a take as `low_match` when `residual` is above 0.5677 or `timing_corr` is below 0.8336. Both limits are the
midpoints of the gap between seed 5's matched pairs (one synthetic body, the expected clip performed by a rescaled copy of itself)
and its mismatch pairs (another movement). Real correct takes by another person are capped (TICKET-101: the hub's group dance clip 3,
residual 0.556 to 0.586 and `timing_corr` 0.62 to 0.76). This lane measures the cause, writes the family's targets down before any
constructed number exists (ADR-0025), builds the one population seed 5 lacks (a correct take by a different body, behind an opt-in
generator flag) and tests whether any candidate guard signal separates the seed-5 mismatches from it. It changes no file under
`part5/`, so `part5/guard.py` and `part5/rules.json` stay what they are.

## Why This Is Wrong (Dissent-First)
1. **A constructed population proves only what it is built from.** If the construction is tuned until the current guard caps it, a
   candidate that uncaps it has learned the construction. Answer: ADR-0025 fixes every range from the hub's reports before any
   constructed number exists, and a construction that does not reproduce the real pattern stops the family instead of being adjusted.
2. **The guard's aligner already removes a constant offset.** `part5.align.align` takes the median follower minus expected offset along
   a first path and aligns again on the offset-free features, so a constant per-take angle offset may barely move the residual.
   Answer: that is a result to report; if the constructed offsets do not reproduce the cap, the stop clause says so.
3. **One real clip is thin evidence.** Clip 3 of the hub's group dance run has four followers; REHAB24-6 has 22 correct cross-person
   reps on pipeline skeletons. Answer: both are reported with their n and never tuned on; the family can only conclude "reproduced" or
   "not reproduced", not "fixed".
4. **A guard that lets cross-person takes through also lets weaker mismatches through.** Answer: the targets keep every seed-5
   mismatch capped and require margin, and a null stays a cap.

## Acceptance Criteria
### AC-GC-01: the cause measurement
Given the hub's REHAB24-6 analyses and seed 5
When `scripts/guard_cross_person_cause.py` runs
Then it prints `residual`, `timing_corr` and `span_share` (min, median, max, and the share capped by each limit) for correct reps against
another person and against the same person, paired by clip, and for seed 5's matched and mismatch populations, writes the same to
`out/guard-cross-person/cause.json`, and recomputes every REHAB pair with the guard code of this tree to show the stored numbers agree.

### AC-GC-02: the generator flag is opt-in and leaves the committed sets alone
Given `scripts/make_dummy_followers.py` with and without `--cross-body`
When seed 5 and seed 73 are generated without the flag
Then every written byte equals what the generator wrote before the flag existed; with the flag every take gains a `cross_body` label
block (bone scales, the per-measure offsets, the per-limb lags, the kinds applied), the draws come from streams keyed by the take id so
no other draw moves, the same flags give the same bytes twice, and `--cross-body-parts` applies a subset (an ablation) while the
remaining draws stay the full population's.

### AC-GC-03: the construction follows the pre-registered ranges
Given the constants of ADR-0025 (a)
When a constructed take is measured with `part5.measures.compute`
Then each applied offset moves its measure by the drawn amount (within 0.5 degree of the noise-free case) and the bone scales leave
every angle measure unchanged.

### AC-GC-04: the candidate signals (not built)
Given a pair aligned by `part5.align.align`
When `scripts/guard_candidates.py` computes `residual_c` and `timing_corr_lag` (ADR-0025 (b))
Then both are NaN where the pair has no alignment or no measurable correlation, and a NaN signal is a cap in the candidate rule.
Not built: ADR-0025's stop clause S1 fired at step 4, and step 5 runs only if step 4 reproduces the real pattern. The signals stay defined
in the ADR; no module for them is in the tree.

### AC-GC-05: the evaluation of the construction
Given the constructed seed 5 populations
When `scripts/eval_guard_candidates.py reproduce` runs
Then it measures the current guard on each population's correct takes, prints the reproduction test R1 and R2 of ADR-0025 (a) with the
baseline of the unconstructed seed 5 correct takes beside it, says whether S1 fires, and writes `reproduce.json`; it refuses a labels
file whose seed is not 5 and names seeds 79, 83 and 89 in the refusal.

## Error Cases
| Condition | Behavior | AC Reference |
|-----------|----------|-------------|
| REHAB state directory missing | exit 2 with the path named; no partial output | AC-GC-01 |
| labels.json seed is not 5 | exit 2, refusal names 79, 83 and 89 | AC-GC-05 |
| a pair has a NaN statistic | the pair counts as capped (a null stays a cap) | AC-GC-05 |

## Negative Requirements (What This Lane Must NOT Do)
- MUST NOT change `part5/guard.py`, `part5/rules.json` or any `part5/` file. Why: new `part5/` modules need their spec on main first, and
  the guard is frozen under ADR-0017.
- MUST NOT generate, read or score seed 79, 83 or 89, or any seed other than 5. Why: they are unspent and the protocol needs them clean.
- MUST NOT copy REHAB24-6 data (CC BY-NC 4.0) or any frame into a repository. Why: the licence; numbers only, the path and sha256 cited.
- MUST NOT tune the constructed population on a guard outcome. Why: the targets are the pre-registration.

## Delivery Verification Plan
- `uv run pytest tests/test_guard_cause.py tests/test_cross_body.py tests/test_guard_reproduce.py` exit 0.
- `uv run python scripts/guard_cross_person_cause.py` exit 0 (step 1, through `bash /tmp/simon5-heavy.sh`).
- `uv run python scripts/make_dummy_followers.py --seed 5 --cross-body --out out/guard-cross-person/c1` exit 0, and the five other
  populations of ADR-0025 (a) (step 3).
- `uv run python scripts/eval_guard_candidates.py reproduce` exit 0 (step 4). The candidate fit (step 5) is not run: S1 fired.
- `python3 scripts/make_design_copies.py --check` exit 0.
- Not run in this lane: `make test`, `make check-5` (nothing in `part5/` changed), any held-out seed.

### Device/Platform Strategy
Not applicable: scripts and documents.

### Data
Seed 5 only (`fixtures/input/followers`, and the constructed set under `out/guard-cross-person/`, which the gitignore keeps out of the
tree). REHAB24-6 (CC BY-NC 4.0) is read from outside the repository and cited by path and sha256 in `docs/research/guard-cross-person.md`.

### Ratchet Initialization Plan
Not applicable.

## Dissent Review
### Concern 1: the constructed population is one reading of the hub's report
Kept and stated: ADR-0025 names two pre-declared readings of the offset SD (per take, and per pair) and the stop clause covers both.
### Concern 2: scripts are not published
Kept: the lane is research; a candidate that survives needs its own spec for a `part5/` module before any freeze.

## Files (every new or changed source file; the write gate reads this table)
| File | Part | Published |
| --- | --- | --- |
| `scripts/guard_cross_person_cause.py` (new) | step 1, the cause measurement | no (firm) |
| `scripts/make_dummy_followers.py` (the `--cross-body` flag) | step 3, the constructed population | yes |
| `scripts/guard_candidates.py` (not written) | step 5, candidate signals; S1 fired at step 4 | no (firm) |
| `scripts/eval_guard_candidates.py` (new) | step 4, the reproduction test | no (firm) |
| `tests/test_guard_cause.py` (new) | tests of the cause script's pure functions | no (firm) |
| `tests/test_cross_body.py` (new) | tests of the flag (byte identity, determinism, ranges) | no (firm) |
| `tests/test_guard_reproduce.py` (new) | tests of the reproduction test and the evaluation's refusals | no (firm) |
