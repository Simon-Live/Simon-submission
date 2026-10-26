# Simon Part 3 — Align 3D model / skeleton consistency

This repo is **only** Simon Part 3. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way — that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #57. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 3).

## Input

`pose3d.json` (from Part 2, any camera angle). Fixtures in `fixtures/input/`.

## Output

`skeleton.json` — the same motion with one fixed set of bone lengths, rotated to a standard facing, scaled to standard limb lengths, no left/right label flips.

## Shared-file context (only what this part touches)

Canonical 17 joints (subject's left/right): nose, left_eye, right_eye, left_ear, right_ear, left_shoulder, right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee, right_knee, left_ankle, right_ankle. Coordinate frame: origin at the hip midpoint per frame; x = subject's left (horizontal), y = world up, z = anterior (x × y); metres and degrees. Input and output use the same joint names and frame; output adds one fixed `bone_lengths_m` set for the whole clip.

## Frontier model

none

## Definition of done

Bone-length variation <2% across a clip; zero left/right flips; the same movement filmed from 4 synced phones produces skeletons whose joint angles agree within 10°.

Done-check: `make check-3` — prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** The 4 phone views going in, the 4 aligned skeletons overlapping.
- **Integrated:** Part 4 and Part 5 only ever see `skeleton.json`; camera angle is already removed here (this is the 'any angle' claim).

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-3`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.
