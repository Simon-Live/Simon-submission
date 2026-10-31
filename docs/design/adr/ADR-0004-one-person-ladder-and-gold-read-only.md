# ADR-0004: One-person check made green only by model-side improvement; gold data read-only

> Copy of `docs/adr/ADR-0004-one-person-ladder-and-gold-read-only.md` from the maintainers' working repo at `1bfac92`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted (stakeholder-proxy, 2026-10-28)
Date: 2026-10-28

## Context
The one-person DoD is: on 20 hand-clicked frames including side views, 3D joints reproject within 5% of
body height. `check-2` applies it to every frame (decision 2 on #18), with body height = the clip maximum
of the clicked nose to ankle-midpoint distance. The operator ruled on #337 (2026-10-28) that camera angle
must not matter, because Part 2 normalises from all angles and distances: no specially filmed side-view clip is
needed and "including side views" is not a requirement we chase. The recorded HPC result on the seated side-view clip is
3 of 20 frames over 5% (mean 3.78, p95 5.26, max 5.29). Those outputs are not committed. The CPU probe on
#46 showed RTMPose-x 2D at 1 of 20 frames over (worst 6.32%).

## Options Considered
### Option 1: relax the rule (mean instead of every frame) or re-click labels
- Pros: green quickly. Cons: changes the DoD the team set; not ours to change. Effort: Low.
### Option 2: model-side ladder on committed reproducible outputs
- Pros: an honest green or an honest red. Cons: may not reach green. Effort: High.

## Decision
Option 2. Threshold, labels (`fixtures/input/single/labels_2d.json`), the body-height rule and the
every-frame rule are read-only; agents never re-click labels. First reproduce the 5.29% on this host
(TICKET-019), then climb a ladder of distinct families, stopping at the first green rung: (1) 2D-keypoint
guided refinement of SAM 3D Body (fit to RTMPose 2D, keeping SAM's bone lengths and depth prior),
(2) temporal smoothing, (3) focal and field-of-view fit, (4) ensemble. Each rung is measured on committed
outputs. Still red after the ladder: publish an honest DEGRADED result with the numbers.

Second scored one-person set (operator ruling on #337, 2026-10-28; TICKET-037). Ground truth stays
human-clicked; agents never make labels. The set comes from openly licensed, human-annotated 2D keypoints at any
angle: COCO val2017 person keypoints (annotations CC BY 4.0), keeping only images whose licence field allows
commercial use. At least 20 single-person images with every keypoint labelled, nose and both ankles visible and a body height of at least 150 px (occluded joints null and unscored, as in the seated set; stakeholder-proxy ruling 2026-10-29, because val2017 with commercial licences holds only 17 images with all 17 keypoints visible),
chosen by a rule committed before any scoring, never by score. COCO's 17 keypoints map onto Part 2's canonical
17 by name; body height uses the check-2 rule (nose to ankle midpoint, each image its own clip). It is a second
one-person block in check-2 under the unchanged 5% every-frame rule. The one-person gate passes only when every
scored one-person set passes; the 20 seated frames stay scored and gated, unchanged. "Green rung" below means
green on every scored one-person set.

The gold set is the test set (setup review B2). The 20 labelled frames (`labels_2d.json`), the COCO set
(`fixtures/input/coco/labels_2d.json`) and `gt_tracks.json` are used only to score, never to choose:
- No rung, rung parameter or tracker parameter is chosen by its score on the gold set. Parameters are
  fixed before scoring from label-free objectives only: agreement with RTMPose 2D on the single clip's
  unlabelled frames and on the dance clip, temporal smoothness, bone-length stability.
- `part2/refine/**` and `part2/trackers/**` never import `part2.eval_reproj` or `part2.eval_tracks` and
  never read a label file; `tests/test_gold_isolation.py` asserts it.
- Each configuration is committed, then scored once. Every gold scoring, pass or fail, gets a row in
  `progress/ladder.md`; the count appears in STATUS.md and in the DONE? (or STATUS) comment.
- At most one revision per rung, justified by a label-free diagnostic written to `progress/ladder.md`
  before the rescore.
- `ensemble` combines per frame by a label-free rule (per-joint median across members, or the member that
  agrees best with RTMPose 2D on that frame).
- Tracker tuning uses the dance clip or a label-free id-consistency measure, never `gt_tracks.json`.

The reference reproduction (step 0) runs on the local RTX 5090 cu128 backend. If the cu128 port fails
inside its timebox, the record says the HPC reference could not be reproduced on this host, and the
ladder starts from the unrefined score of the backend that works (CPU).

## Consequences
- **Positive**: any green is reproducible by `make outputs` and checkable without a GPU.
- **Negative**: rung 1 uses a 2D detector whose errors partly agree with the labels' convention
  (Muse's left_hip note on #18); the refined 3D must still pass the 3D bar to show depth was not broken.
- **Neutral**: every rung is recorded in `provenance.refine` and the stamp.

## Assumptions
- ASM-011 (the seated clip is representative enough for the one-person DoD); the COCO set (TICKET-037) adds
  other people, angles and distances.

## Reversal Cost
Low: each rung is a flag.

## Pre-Mortem (MANDATORY)
1. Rung 1 overfits the 2D and distorts depth. Likelihood: M, Impact: M. Mitigation: bone lengths fixed to
   SAM's; report the 3D distance to the unrefined output beside the score.
2. The baseline does not reproduce on the 5090 (different torch, detector fallback). Likelihood: M,
   Impact: M. Mitigation: record the difference; the ladder starts from the host's own baseline.
3. Time runs out mid-ladder. Likelihood: M, Impact: M. Mitigation: timebox per rung (goal brief); DEGRADED.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect role)
- "Fitting to 2D is gaming the 2D metric": the bar is a reprojection bar; the refinement keeps the 3D
  model's lengths and depth and the 3D bar reports drift.
- "Re-clicking would be fairer": refused; labels are team ground truth.
- "A specially filmed clip would be fairer": the operator ruled on #337 that angle must not matter; the second
  set is open human-annotated data at any angle.
- "One rescore per rung still leaks": accepted as a bounded leak; the revision needs a label-free reason
  written first, and every scoring is counted in public.

## Code Backlinks (updated as code is written)
- `part2/refine/`, `part2/check.py`, `tests/test_gold_isolation.py`.
