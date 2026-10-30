# ADR-0005: check-7 compares the app path with a direct run, under a tolerance fixed before measuring

> Copy of `docs/adr/ADR-0005-check-7-definition-and-tolerance.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted; amended by ADR-0006 (2026-10-30)
Date: 2026-10-28 (amended the same day by the review fix batch, before any measurement: the
`faults_compared` gate, the mismatch rule, the frozen follower set)

## Context
DoD: "end to end on a movement the app has never been hand-configured for: record it in Part 6, follow
it, and the faults reported match running Parts 2 to 5 on the same recorded follower clip directly.
make check-7." Part 2 runs a neural network on the GPU, so two runs on the same clip may differ in the
last digits. Part 5 reports each fault as `measure`, `side`, `direction` and `magnitude_deg` (or
`magnitude_m`), and exits 3 for a written `different_movement` refusal. check-7 judges stitching, not
fault accuracy, which is Part 5's own check.

## Options Considered
### Option 1: byte-identical `analysis.json` in both paths
- Pros: strict. Cons: fails on GPU noise that has nothing to do with stitching. Effort: Low.
### Option 2: same fault identities, magnitudes within a stated tolerance, refusals in both paths
- Pros: tests the stitching; tolerates float noise; the tolerance is set before any measurement.
  Cons: a fault right at Part 5's threshold can appear on one side only. Effort: Medium.
### Option 3: compare only fault counts
- Pros: robust. Cons: too weak; a side swap or a sign flip would pass. Effort: Low.

## Decision
Option 2, with the evidence of Option 1 reported.
- **Paths.** App path: the trainer clip is uploaded to Part 7's HTTP API and goes into a temporary
  Part 6 catalog through `POST catalog/api/entries` and the processor (Parts 1 to 4); each follower clip
  is uploaded to `api/follow` and analysed (Parts 2, 3, 5) as a visitor's would be. Direct path: the same
  follower clip file through Part 2, Part 3 (`--view part5 --fps 30`) and Part 5 `analyse`, at the same
  pins, by their CLIs, against an expected `animation.json` that the direct path builds from the same
  trainer clip with Part 2, Part 3 (`--view part4`, the app path's Part 1 `keyframes.json`) and Part 4.
- **Fault identity.** For each follower, the set of `(measure, side, direction)` in the app's
  `analysis.json` equals the direct set.
- **Magnitude.** For each matched fault, `|a - d| <= max(2.0, 0.10 * max(|a|, |d|))` degrees for
  `magnitude_deg`, and `<= max(0.01, 0.10 * max(|a|, |d|))` metres for `magnitude_m`.
- **Status.** `status.code` equal in both paths for every take. A file with no `status` block is Part 5
  analysis schema 1.0 and reads as `ok` (Part 5 CONTRACT, rule 1).
- **Mismatch take** (amended 2026-10-30, operator directive "NEVER fail to analyze"). Gated on: analysed in both
  paths, equal warnings (`warnings[].code`; an old-pin refusal status such as `different_movement` reads as a
  warning), a grade of F in both paths (a missing score on an old-pin refusal reads as F), and equal fault sets.
  This replaces `refusal_both` and the `mismatch_rule` machinery (`equal_only | refusal_required`), which read the
  pinned Part 5 CONTRACT for the movement guard: Part 5 schema 1.4.0 never refuses, so a different movement is a
  low-match warning over a score capped at 59. `faults_compared >= 1` still holds on the same-movement takes.
- **Coverage.** At least 2 same-movement followers, at least one of them with `status.code: ok` in both
  paths, and `faults_compared >= 1`: at least one matched fault (the same `(measure, side, direction)`
  in both paths) in at least one same-movement take, its magnitudes compared. Equal empty fault sets
  never pass check-7 on their own.
- **Clip set.** The follower set is frozen at TICKET-013 (`test-videos.md`). No clip is swapped after
  any check-7 result; a swap needs a written reason that does not depend on a check-7 result, and it
  restarts all reporting.
- **Entry.** The trainer entry has `files_source: processor` (or `import` on the fallback path, which
  fails the gate and is reported), and `keyframes.json`, `skeleton.json`, `animation.json` each pass
  their doctor; Part 6 `doctor <entry>` exits 0.
- **Inputs.** The sha256 of the file given to Part 2 is the same in both paths for every clip.
- **Reported, never gated:** whether each `pose3d.json` pair is byte-identical; the largest joint
  difference between the two `pose3d.json` files and between the catalog's and the direct
  `animation.json`; per step the part, commit, command, exit code and duration.
- Exit 0 only when every gated metric passes. Never tune a part, a rule or the tolerance to pass; a
  failure is reported and the run ends DEGRADED with the numbers if it stays red.

## Consequences
- **Positive**: a pass means the app runs the parts as their owners do.
- **Negative**: a borderline fault can fail the gate on GPU noise; the reported pose3d difference
  shows whether that is the cause.
- **Neutral**: Part 1 runs once per trainer clip; the direct path reuses its `keyframes.json` because
  the DoD names Parts 2 to 5.

## Assumptions
- ASM-010: Part 2 on the same GPU and input gives the same or near-same output (measured and reported).
- ASM-011: Part 5's `analyse` is deterministic for identical inputs.

## Reversal Cost
Low: the tolerance is a constant in `part7/compare.py`, but changing it after a measurement is
forbidden; a change needs a new ADR written before the next measurement.

## Pre-Mortem (MANDATORY)
1. GPU noise flips a borderline fault. Likelihood: M, Impact: M. Mitigation: reported with the pose3d
   difference; the run may use only an option Part 2 documents for deterministic inference, never a
   Part 7 tolerance change.
2. Part 5's guard refuses every follower. Likelihood: M, Impact: H. Mitigation: coverage metric fails
   honestly; a report to Part 5 with the guard statistics.
3. The app silently uses another pin than the direct path. Likelihood: L, Impact: H. Mitigation: both
   paths read `parts.lock.json`; each step records its commit; check-7 fails on a mismatch.
4. A vacuous pass: both paths report no faults, so every comparison holds trivially. Likelihood: M,
   Impact: H. Mitigation: the `faults_compared >= 1` gate and the frozen follower set.
5. The mismatch take is not an F at the pin. Likelihood: M, Impact: M. Mitigation: `mismatch_equal` fails and names
   the grade and warnings of each path; the clip is replaced only by a new ADR amendment.

## Dissent (MANDATORY)
Reviewed at setup (architect review), 2026-10-28.
- 2 degrees may hide a small real stitching bug (for example a unit slip). Resolution: unit slips give
  differences far larger than 2 degrees; side and direction are matched exactly.
- Reusing Part 1's output in the direct path skips Part 1 there. Resolution: the DoD's direct run is
  Parts 2 to 5.

## Code Backlinks (updated as code is written)
- `part7/check7.py`, `part7/compare.py`, Makefile `check-7`.
