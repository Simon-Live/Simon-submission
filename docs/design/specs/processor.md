# Spec: the trainer job and the Part 6 import (`part7/jobs.py`, `part7/chain.py`, `part7/parts/p6_catalog.py`)

> Copy of `docs/specs/processor.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted (setup, 2026-10-28); rewritten 2026-10-30 by ADR-0006: the processor seam is not built
Date: 2026-10-30
Request Type: feature-change
Risk Level: high
ADR: ADR-0006 (amends ADR-0003). Master: `part7-stitching.md`. Journey: `journey.md` steps 2 and 3.
Tickets: TICKET-039 (trainer entry by import with the video), 034 (Part 3 densify), 035 (Part 4
errors), 018, 021. TICKET-017 (processor seam) abandoned as superseded by ADR-0006.

## Overview
Part 6's server passes `video_path=None` to its processor and its web page has no `<video>` element, so
an entry made through the processor seam carries no video for a second visitor (journey step 3). An
entry made by `python3 -m part6 import` carries the video (`video_uri`, served with HTTP 206) and is
exempt from Part 6's cap of 30 visitor recordings. Part 7's trainer job therefore runs Parts 1 to 4
itself and ends with Part 6's documented `import` CLI. `part7/processor.py` is not written.

## Why This Is Wrong (Dissent-First)
- Import is not Part 6's recording path. Answer: the entry is made by Part 6's own documented command,
  lives in Part 6's catalog, is played by Part 6's player and listed by Part 6's API (ADR-0006).
- A running Part 6 server may not see a CLI import until restart. Answer: ASM-014, tested first in
  TICKET-039; the fallback is Part 6's `POST api/import` (table below).

Follower and group takes are never failed for analysis reasons: `chain.follower` writes Part 7's own analysis (an F
with a warning) when Part 2, 3 or 5 cannot see the take (`app.md` "Always analysed"); the job ends `done`.

## Sequence (`part7/chain.py trainer`, work dir `D`)
1. Upload: `POST api/uploads`, then `POST api/trainer {upload_id, name, category}` 202 `{job}`.
2. Normalize: the upload becomes H.264 MP4 with faststart (`part7/media.py`), the `video.mp4` every
   later step and the import use.
3. Part 1 key frames (`parts-harness.md`).
4. Part 2 pose (`--backend gpu`, holding the GPU lock).
5. Part 3 `--view part4 --body simon-standard` with Part 1's keys densified `--keyframes-densify
   every:10`.
6. Part 4 animate.
7. Import: `python3 -m part6 import <I> --catalog <catalog> --name <name> --category <category> --part
   keyframes=1 --part skeleton=3 --part animation=4` (`keyframes=3` on the Part 1 fallback), where `<I>`
   holds `keyframes.json`, `skeleton.json`, `animation.json` and `video.mp4`.
8. Doctor: `python3 -m part6 doctor <catalog>/<id>`.
9. The job is `done` with `entry_id`.

Stages shown on `#/job/<id>`: `upload`, `keyframes`, `pose`, `skeleton`, `animation`, `catalog`. Exact
argv per part: `journey.md` "Commands".

## Fallbacks (options the parts already offer)
| Failure | Fallback | Recorded as |
|---|---|---|
| Part 1 exits non-zero, hits the run-wide $5 cap, or outputs `people: []` | Part 3 `--keyframes every:10`, import with `--part keyframes=3` | job `note`, provenance keyframes 3 |
| Part 3 refuses the `part4` view (joint over 180 degrees between keys) | retry once with `every:5` | job `note` |
| Part 3's follow-up not yet pinned | `--keyframes every:10` without densify | job `note`, step argv |
| Part 2 GPU setup fails for 2 hours | `--backend cpu` | job `note`, step argv |
| Part 4 exits 1 | job `failed:animation`; the traceback's last line in the job log only | job log |
| Part 6's server does not list a CLI import (ASM-014) | Part 6 `POST api/import` with the video re-encoded under 16 MiB | job `note` |

## Acceptance Criteria
- AC-R1 A recorded or uploaded trainer video becomes an entry with `files_source: import`, a
  `video_uri`, `provenance.<kind>.part` 1 (or 3), 3, 4, and Part 6 `doctor` exit 0.
- AC-R2 The job screen shows at least four trainer stages.
- AC-R3 A Part 1 failure (stubbed) yields keyframes provenance 3 and a job note.
- AC-R4 A failure reason contains no `/`, no host name and no key (test with stubbed failures).
- AC-R5 The densify argv is present after the Part 3 re-pin and absent before it (stub `--help`).
- AC-R6 The normalized `video.mp4` is H.264 and plays with a Range request answered 206 through the
  `catalog/**` proxy.
- AC-R7 Part 4 exit 1 maps to `failed:animation`.

## Error Cases
| Condition | Job status shown | AC |
|---|---|---|
| Part 2 timeout | `failed:pose: the 3D step took too long` | AC-R4 |
| GPU busy over 30 min | `failed:pose: the GPU is busy, try again later` | AC-R4 |
| Part 4 exit 1 | `failed:animation: the animation step failed` | AC-R7 |
| Doctor rejection | `failed:<stage>: <file> was rejected by <part>` | AC-R4 |
| Import or Part 6 doctor fails | `failed:catalog: the catalog did not accept the entry` | AC-R1 |

## Edge Cases
- Same name twice: Part 6 makes a free id (`squat-2`); the job records the id Part 6 chose.

## Dissent Review
Reviewed at the rescope, 2026-10-30.
- Concern: Part 6's processor seam and its `processing:<stage>` texts go unused. Resolution: ADR-0006;
  the seam cannot carry the video the journey needs, and Part 7's job screen shows the stages.

## Delivery Verification Plan
Unit tests with stub parts and a stub Part 6 CLI; staging verify Record and Upload on the journey drive
(`staging.md`, firm-only, not published).
