# ADR-0004: Body-based canonical frame and one standard reference body

> Copy of the maintainers' working ADR `docs/adr/ADR-0004-facing-and-standard-lengths.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Date: 2026-10-27. Status: accepted (operator answers 2026-10-27, items 3 and 4).

## Context
Part 2 canonicalises each frame on its own with the camera's up, so a tilted phone tilts every pose.
The operator ruled that the recording angle and the phone tilt must not be a factor at all, and that
every skeleton is normalised to one standard reference body, not to per-person proportions.

## Options Considered
### Option 1: keep Part 2's camera-up frame
Phone tilt stays in the data; rejected by the ruling.
### Option 2: per-frame body up (trunk axis each frame)
Removes tilt but also erases real trunk lean, which Part 5 needs.
### Option 3: one clip-level body up from feet to shoulders over standing frames
Removes camera pitch and roll, keeps trunk lean and trunk twist. Assumes one facing per clip.

For lengths:
### Option A: per-person proportions scaled to a standard stature
Rejected by the ruling.
### Option B: one standard body for every skeleton
Every recording is directly comparable; individual proportions are kept only as metadata.

## Decision
Option 3 with Option B. Up = clip mean of ankle midpoint to shoulder midpoint over standing frames
(knees above 160 degrees), fallback all frames. Standard body at stature 1.70 m, fixed and
source-checked on 2026-10-27 in `part3/standard_body.json` (table and citations in the spec, step 6):
Winter 2009 Fig. 4.1 (after Drillis and Contini 1966) for limbs and trunk; ANSUR II biacromial breadth
for the shoulders and Human3.6M hip joint centres for the pelvis, because COCO keypoints sit near the
joints, not at Winter's outer breadths (ASM-004); a neutral head model from Winter levels, ANSUR II
head data, the MediaPipe canonical face and the plumb-line posture for the head and face bones.

## Consequences
- A whole-body turn on the spot is not represented (Part 2 removes it per frame); stated in the
  output fixture README for Part 5.
- COCO hip and shoulder keypoints sit inside the anatomical widths the ratios describe; every skeleton
  carries the same offset, so comparisons stay fair (ASM-004).

## Assumptions
ASM-002, ASM-004, ASM-005, ASM-009.

## Reversal Cost
Low: the table and the up step are isolated modules.

## Pre-Mortem (MANDATORY)
A movement that never stands straight (floor work) gets an up from all frames that is off by tens of
degrees. It is reported in `up_source`; Simon's recorded movements start standing (ASM-002).

Amendment (stitching, 2026-10-28, ASM-019): with fewer than 5 standing frames the up is now the
input's +y (Part 2's world up for a level camera), recorded as `up_source: input_up`. The all-frames
mean stood a real cat-cow clip upright. `PART3_UP_FALLBACK=all_frames` restores the old fallback.

## Dissent (MANDATORY)
Forcing one body changes positions of the hands and feet relative to a tall or short person's real
reach; Part 5 compares angles and directions, which the retarget keeps.

## Code Backlinks (updated as code is written)
`part3/facing.py`, `part3/standard.py`, `part3/standard_body.json`, `part3/bones.py`,
`docs/research/standard_body_derivation.py`.
