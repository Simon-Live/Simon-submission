# Simon Part 4 — Animate 3D models between key frames


Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
This repo is **only** Simon Part 4. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way — that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #58. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 4).

The behavior described below is what this working branch ships. It is not a claim that `main` already contains it; `main` updates when the Part 4 pull request merges.

## Input

`skeleton.json` (Part 3) sampled at the key frames in `keyframes.json` (Part 1). Fixtures in `fixtures/input/<set>/`.

Each set has:

- `keyframes.json` — 30 fps timeline and the key indices
- `skeleton.json` — rigid rig (rest offsets, bone lengths) plus `local_rotations` and joint positions at those keys
- `coaching_note.txt` — authored coaching text used by the offline voice hook

Rotations are quaternions `(x, y, z, w)`.

## Output

`animation.json` — a smooth 30 fps 3D animation of the expected movement, written to `fixtures/output/<set>/animation.json`.

`format` is `simon.animation.v1`. One frame per 30 fps tick. Each frame has `index`, `t`, `interpolated`, and `joints` named with the canonical 17. Positions are metres in the hip-centered frame. Keyframe samples have `interpolated: false`. Filled frames have `interpolated: true`.

Interpolation is cubic Hermite on rotation vectors, then forward kinematics, so segment lengths stay at the rest offsets. Blending positions would stretch the bones.

## Shared-file context (only what this part touches)

Canonical 17 joints (subject's left/right): nose, left_eye, right_eye, left_ear, right_ear, left_shoulder, right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee, right_knee, left_ankle, right_ankle. Coordinate frame: origin at the hip midpoint per frame; x = subject's left (horizontal), y = world up, z = anterior (x × y); metres and degrees. Output shape mirrors `pose3d.json` frames at 30 fps with `interpolated: true` on filled frames.

## Frontier model

Classical interpolation is the default and is the only path `make check-4` runs.

Sparse Meta Model API hooks sit beside that path. They do not edit `animation.json` unless you are looking at an optional poster file under `demo/posters/` (gitignored). Live HTTP calls run only when `META_LIVE=1`. Local open-weight calls run only when `META_LOCAL=1`. A key by itself does not enable either.

| Model | Role |
| --- | --- |
| `muse-spark-1.3` | Critique of keyframe spacing against the 8° budget |
| `muse-wonder-1.0` | Advisory phase plan from the keyframe names. Does not edit `animation.json` |
| `muse-image-1.0` | Optional demo poster |
| `muse-voice-transcribe-1.0` | Optional coaching-wav transcript. Offline, the authored note is returned and labeled offline |
| `sam-3.1` | Optional person segment for a demo overlay. No mask is invented offline |
| Muse Glimmer | Optional local caption (`META_LOCAL=1`, `GLIMMER_BASE_URL`). No weight download |
| Muse Spark Open | Optional local review of the interpolator (`META_LOCAL=1`, `SPARK_OPEN_BASE_URL`) |

Chat hooks use the developer role. The client floors `max_tokens` at 1024. Spark critique and Wonder plan request 2048 in practice: reasoning tokens consume the budget first, and a live smoke with 1024 returned `finish_reason=length` and empty content. A truncated reply is still logged, then re-raised.

Setup, commands, and prices: `docs/META_MODELS.md`. Spend ledger: `docs/meta-api-spend.md`. The ledger prints an alert when cumulative estimated spend crosses $5, $10, $15, and so on. A live smoke is optional. It is logged on the machine where you set `META_LIVE=1`; `make check-4` does not call Meta, and its metrics JSON must report `meta_live_calls` of 0.

## Definition of done

With some in-between frames hidden, the animation rebuilds them within 8° per joint; bone lengths stay fixed throughout.

Done-check: `make check-4`. It prints a metrics JSON and exits 0 only when every threshold passes for both fixture sets. The implemented thresholds are:

- max joint direction error ≤ 8° on every held-out frame
- bone length within 1 mm of the rest rig
- hip midpoint within 1 mm of the origin
- keyframe positions reproduced, `interpolated` flags correct, shipped `animation.json` matches a fresh rebuild
- `meta_live_calls` is 0

Held-out ground truth lives in `fixtures/expected/<set>/held_out.json`. The animator does not read that directory.

## Demos

- **Isolated:** The expected movement playing as a 3D animation you can orbit (`demo/index.html`).
- **Integrated:** This animation is the reference Part 5 compares followers against, and what Part 6 plays back.

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-4`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.

## Run

Python 3.10+ and the standard library. No packages to install. Run these from the repo root on this branch.

Two fixture sets:

| Set | Movement | Frames | Keys | Held out | Input | Shipped output |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `exercise` | squat, 3 s | 91 | 10 | 81 | `fixtures/input/exercise/` | `fixtures/output/exercise/animation.json` |
| `dance` | step-touch, 4 s | 121 | 13 | 108 | `fixtures/input/dance/` | `fixtures/output/dance/animation.json` |

```bash
make check-4          # both sets; metrics JSON on stdout; exit 0 only if every threshold passes
make animate          # rebuild both animation.json files from the keyframes
make fixtures         # regenerate inputs, held-out frames, and outputs from the analytic motions
```

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

`keyframes.json` lists the 30 fps timeline and the key indices. `skeleton.json` holds the rest rig and the key samples (`joints` plus `local_rotations`, including the virtual pelvis, chest, and neck used for forward kinematics). The 17 canonical joints are the ones written into `animation.json`.

`animation.json` positions are metres. x is the subject's left, y is world up, z is anterior (x × y). The origin of each frame is the hip midpoint.
