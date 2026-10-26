# Simon Part 2 — Images to 3D models

This repo is **only** Simon Part 2. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way — that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #56. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 2).

## Input

Video frames. Two modes: a one-person recording (trainer or single follower) and a multi-person class recording.

## Output

`pose3d.json` per tracked person; multi-person mode also writes `tracks.json` (stable ID, box, mask, confidence per person per frame).

## Shared-file context (only what this part touches)

Canonical 17 joints (subject's left/right): nose, left_eye, right_eye, left_ear, right_ear, left_shoulder, right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee, right_knee, left_ankle, right_ankle. Coordinate frame: origin at the hip midpoint per frame; x = subject's left (horizontal), y = world up, z = anterior (x × y); metres and degrees. `tracks.json` shape: `{frames: [{frame, people: [{id, bbox, mask_rle, confidence}]}]}`. `pose3d.json` shape: `{frames: [{frame, t_ms, people: [{id, joints: {<joint>: {x, y, z, conf}}}]}]}`.

## Frontier model

SAM 3D Body (3D); SAM 3.1 (multi-person tracking)

## Definition of done

One-person: on 20 hand-clicked frames including side views, 3D joints reproject within 5% of body height. Multi-person: class clip with ≥5 people, each tracked on ≥95% of frames with ≤1 ID swap per minute, each with a pose3d stream.

Done-check: `make check-2` — prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** A photo beside its rotatable 3D skeleton; a class clip with coloured, stable per-person skeletons.
- **Integrated:** Parts 3–5 consume this repo's `pose3d.json` unchanged.

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-2`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.
