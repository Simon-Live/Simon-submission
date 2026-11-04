# ADR-0003: One phone at a time; the 4-view criterion means 4 separate takes aligned by phase

> Copy of the maintainers' working ADR `docs/adr/ADR-0003-one-phone-four-separate-takes.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Date: 2026-10-27. Status: accepted (operator ruling, Mo, scope owner).

## Context
The upstream README and MINI-APPS.md say "the same movement filmed from 4 synced phones produces
skeletons whose joint angles agree within 10 degrees". The operator ruled on 2026-10-27 that movement
is only ever recorded from one phone at a time; there are no synced multi-phone captures, ever.

## Options Considered
### Option 1: keep the synced reading
Needs hardware and a capture the project will never have.
### Option 2: 4 separate single-phone takes, aligned by Part 1 key frames
Reads `keyframes.json`, which is not in Part 3's shared-file list: scope widening.
### Option 3: 4 separate single-phone takes, aligned by DTW on a joint-angle phase signal
Self-contained; works on any take; needs a negative control so alignment cannot hide disagreement.

## Decision
Option 3. Takes share no clock, calibration or simultaneous view. The check aligns each take to take
1 by DTW on the mean of the 8 interior joint angles in degrees (spec "Phase alignment"; the audit of
2026-10-27 dropped per-take z-scoring, which cancels in a squat) and measures the spread of 9 angles. The synthetic set gives each take its own start offset, tempo and small
performance differences. No sync-offset fields, no triangulation, no multi-view fusion.

## Consequences
- The execution session posts a DECISION comment on the team issue #1 quoting this ruling (from Mo, the
  scope owner) before relying on it, because upstream text still says "synced". The same comment
  states the agreement metric as a decision (spec "Phase alignment"); nothing is asked. Upstream text
  is not edited by this workspace.
- Real input is one take from one phone at any angle (operator, 2026-10-27). Nobody films a movement
  from several angles, so the 4-angle agreement is permanently a synthetic angle-invariance test;
  there is no capture item.

## Assumptions
ASM-007 (the locked metric for "agree within 10 degrees": p95 of the per-frame spread of 9 angles,
posted as a DECISION on issue #1).

## Reversal Cost
Low: the alignment is one module; the metric definition stays.

## Pre-Mortem (MANDATORY)
DTW makes unlike motions look alike and the check passes on bad output. Guard: the negative control
must stay above 10 degrees, and the linear-time figure is printed beside the DTW one.

## Dissent (MANDATORY)
A teammate may read "synced" literally and expect a multi-camera rig. The DECISION comment and the
DONE? text state the ruling and its source.

## Code Backlinks (updated as code is written)
`part3/align.py`, `part3/synth.py`, `part3/metrics.py`.
