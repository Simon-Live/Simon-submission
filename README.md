# Simon Part 4 — Animate 3D models between key frames


Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
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

## Run

Python 3.10+ and the standard library. No packages to install.

Two fixture sets:

| Set | Movement | Input | Shipped output |
| --- | --- | --- | --- |
| `exercise` | squat, 3 s | `fixtures/input/exercise/` | `fixtures/output/exercise/animation.json` |
| `dance` | step-touch, 4 s | `fixtures/input/dance/` | `fixtures/output/dance/animation.json` |

Hidden in-betweens used by the done-check live in `fixtures/expected/<set>/held_out.json`. The animator does not read that directory.

```bash
make check-4          # both sets; metrics JSON on stdout; exit 0 only if every threshold passes
make animate          # rebuild both animation.json files from the keyframes
make fixtures         # regenerate inputs, held-out frames, and outputs from the analytic motions
```

`make check-4` scores every non-keyframe against the held-out pose. A joint passes when its bone direction is within 8°. Bone lengths must stay within 1 mm of the rest rig, and the hip midpoint must stay at the origin. The check also requires `interpolated: true` on filled frames and `false` on keyframes. It makes no Meta API calls.

Rebuild one clip:

```bash
PYTHONPATH=src python3 -m simon_anim.animate --set exercise
```

Orbit either clip in a browser. From the repo root:

```bash
python3 -m http.server 8765
# open http://127.0.0.1:8765/demo/
```

Drag to orbit, scroll to zoom, space to play. The page loads `fixtures/output/<set>/animation.json`.

## File shapes

`keyframes.json` lists the 30 fps timeline and the key indices. `skeleton.json` is the rigid rig (rest offsets, bone lengths) plus `local_rotations` and joint positions at those keys. Rotations are quaternions `(x, y, z, w)`.

`animation.json` (`format: simon.animation.v1`) is one frame per 30 fps tick. Each frame has `index`, `t`, `interpolated`, and `joints` named with the canonical 17. Positions are metres in the hip-centered frame (x subject left, y up, z anterior).

Interpolation is cubic Hermite on rotation vectors, then forward kinematics, so segment lengths stay at the rest offsets. Blending positions would stretch the bones.

## Meta models

Optional. Off unless `META_LIVE=1`. Setup, the role of each model, and the spend ledger are in `docs/META_MODELS.md`. Cumulative spend starts at $0. `make check-4` does not call the API.
