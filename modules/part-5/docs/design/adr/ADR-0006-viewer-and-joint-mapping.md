# ADR-0006: Staging viewer, per-fault joints and the result preview
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28

## Context
The README's isolated demo is "a follower clip replayed with each fault listed and the joint
highlighted" (#16). `analysis.json` names the fault's joint in three ways: a sided canonical joint
(`left_elbow`), a side-stripped one for `both` (`elbow`), or a virtual one for centre measures (`spine`,
`shoulders`, `neck`). A viewer cannot highlight `spine` without a mapping. No viewer exists; Part 7 is
an empty scaffold; Part 6 does not read `analysis.json`. Staging runs on port 7123 under
`/simon-part-5/` (registry).

## Options Considered
### Option 1: a mapping table in the viewer only
- Pros: no output change.
- Cons: Part 7 must copy the same table; two tables drift.
- Effort: Low
### Option 2: the producer adds `faults[].joints` with canonical joint names
- Pros: one source of truth; Part 7 highlights without knowing measure names.
- Cons: an additive output field.
- Effort: Low

## Decision
Option 2, with the viewer keeping a fallback table for v1.0 files that lack `joints`.
- `part5.joints_map.fault_joints(fault)` fills `joints` (never empty, every name one of the 17):
  side `both`: `left_X` and `right_X`; `spine`: both shoulders and both hips; `shoulders`: both
  shoulders; `neck`: nose and both shoulders; a sided joint: itself.
- Server: a stdlib HTTP server (`part5/server.py`, `part5/api.py`), no framework, as Parts 3 and 6.
- 3D: three.js r170 vendored in `web/vendor/three/` from the npm package `three@0.170.0`, hashes in
  `web/vendor/README.md`, never copied from another part's repo.
- Replay: the follower over a ghost of the expected clip, time-matched through the alignment
  (`exp_to_fol`); tapping a fault jumps to its frames and highlights its `joints`.
- Result preview: a phone-width screen labelled as Part 5's preview of its published result contract,
  not a Part 7 build.

## Consequences
- **Positive**: Part 7 and the viewer read one field; the mapping is tested once.
- **Negative**: schema version moves to 1.1.0.
- **Neutral**: the fallback table exists in two places (producer and viewer) and is tested against each
  other.

## Assumptions
- ASM-001: inputs stay `simon.animation.v1` with the 17 canonical joints.
- ASM-005: Part 7 reads `status` before `faults`.

## Reversal Cost
Low: `joints` is optional; the viewer fallback works without it.

## Pre-Mortem (MANDATORY)
1. The preview is mistaken for Part 7. Likelihood: M, Impact: L, Mitigation: the label on the screen and
   in `DEMO.md`.
2. The fallback table and the producer disagree. Likelihood: L, Impact: M, Mitigation: a test runs both
   over every measure and side.
3. The vendored library is edited. Likelihood: L, Impact: M, Mitigation: hashes in
   `web/vendor/README.md`, checked by a test.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect)
Concerns:
- Highlighting four joints for `spine` is coarse: it shows the trunk, which is what the fault names.
- A stdlib server is slow for many visitors: staging is a demo for a few people.
- A preview screen invites scope creep into Part 7: it shows the contract only and says so.

## Code Backlinks (updated as code is written)
- `part5/joints_map.py`, `part5/replay.py`, `part5/server.py`, `web/viewer.js`, `web/joints.js`,
  `web/preview.js`
