# Simon Part 4 — Animate 3D models between key frames

This repo is **only** Simon Part 4. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way — that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #58. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 4).

## Input

`skeleton.json` (Part 3) sampled at the key frames in `keyframes.json` (Part 1). Fixtures in `fixtures/input/`.

## Output

`animation.json` — a smooth 30 fps 3D animation of the expected movement.

## Shared-file context (only what this part touches)

Canonical 17 joints (subject's left/right): nose, left_eye, right_eye, left_ear, right_ear, left_shoulder, right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee, right_knee, left_ankle, right_ankle. Coordinate frame: origin at the hip midpoint per frame; x = subject's left (horizontal), y = world up, z = anterior (x × y); metres and degrees. Output shape mirrors `pose3d.json` frames at 30 fps with `interpolated: true` on filled frames.

## Frontier model

none

## Definition of done

With some in-between frames hidden, the animation rebuilds them within 8° per joint; bone lengths stay fixed throughout.

Done-check: `make check-4` — prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** The expected movement playing as a 3D animation you can orbit.
- **Integrated:** This animation is the reference Part 5 compares followers against, and what Part 6 plays back.

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-4`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.
