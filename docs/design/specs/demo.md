# Spec: demos (`demo/simon-end-to-end.mp4`, `demo/walkthrough.mp4`)

> Copy of `docs/specs/demo.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted (setup, 2026-10-28; amended by the review fix batch the same day; amended 2026-10-30
by ADR-0006)
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium (public hackathon submission, 2026-11-04)
Master: `part7-stitching.md`. Tickets: TICKET-023, 028 (the journey content comes from ADR-0006 and
`journey.md`; no new demo ticket).

## Overview
Two videos, both recorded through the staging gateway route by Playwright 1.61.1 at phone width:
- `demo/simon-end-to-end.mp4`, the submission video: all eight journey steps in order (AC-D2). Captions on screen and in `demo/captions.srt`. Under 3 minutes, H.264, yuv420p,
  phone-width sections (the 412 px app viewport, letterboxed into 1080x1920 or shown at native size).
- `demo/walkthrough.mp4`, the verify evidence: one uninterrupted drive of the journey checks, under 90 s
  (GPU waits cut and marked with a caption that names the cut length), under 20 MB.

## Production
- `staging/submission.mjs` and `staging/walkthrough.mjs` record `recordVideo` WebM at the viewport size,
  against the staging route. Long GPU waits are
  cut with ffmpeg at points logged by the script (`cuts.json`), and each cut gets an on-screen caption
  "Processing on the GPU: <n> s skipped" with the measured seconds.
- Assembly with ffmpeg: concat, burn the captions (`subtitles=` filter from `captions.srt`), encode
  `-c:v libx264 -pix_fmt yuv420p -movflags +faststart`, target under 50 MB.
- The public URL never appears on screen (the drive hides the address bar; captions never
  name a URL).
- Captions are written with the writer skill, FORMS "Caption / subtitle": readable at speed, split on
  sense, no em dash, facts only. Every number shown (fault size, timing, part commits) comes from the run
  being recorded; `demo/README.md` cites each: run id, job ids, `analysis.json` path, check-7 metrics file.
- Credits at the end: each clip's author (or "not stated on the page") and licence from SOURCE.md.
- `.gitignore` ignores `*.mp4`; the run adds `!demo/*.mp4` in the same commit as the videos.

## Timing and cuts
- Recording of the submission video starts at 2026-11-03T12:00Z from whatever works then (the run
  plan); a step that does not work yet is left out and the caption and README say so. The
  submission video is never cut.
- `demo/walkthrough.mp4` is the first item on the brief's cut list: when cut, the staging verify log
  stands in for it and `demo/README.md` says so.

## `demo/README.md`
Form: README opening plus a reference table. What the video shows in two lines; chapter timestamps;
the numbers table (value, where it came from); the clips and licences; how to reproduce
(`make videos`, `make check-7`, the staging route). Written with the writer skill.

## Acceptance Criteria
- AC-D1 `ffprobe` reports H.264, duration under 180 s (submission) and under 90 s (walkthrough).
- AC-D2 The submission shows all eight journey steps, in order: open the app; trainer Record (fake
  camera fed from the trainer clip) and the job stages; a second visitor plays the trainer's video and
  rotates its figure; Follow by Record; the pipeline stages; the compare view rotated and toggled; the
  timed AI fault text and a tap that seeks; the score and grade.
- AC-D3 Every number on screen is in the `demo/README.md` table with its source.
- AC-D4 No URL, secret or key on any frame (frames sampled every 2 s and checked by eye; the check is
  recorded in TICKET-028).
- AC-D5 Captions pass an em dash check.

## Dissent Review
Reviewed at setup, 2026-10-28.
- Concern: a fake-camera recording is not a person in front of a phone. Resolution: the camera feed is a
  real person's licensed video; the caption says the camera is fed from a stock clip.

## Delivery Verification Plan
ffprobe output and the frame check in the run notes; the files committed and published (`.simon-publish`
`demo/**`).
