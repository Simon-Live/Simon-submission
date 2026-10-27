# Simon Part 3 — Align 3D model / skeleton consistency


Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
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

## Development

```
make run IN=fixtures/input/part2-single/pose3d.json OUT=out/skeleton.json   # FLIP=auto|on|off
make check-3    # done-check: prints the metrics JSON, exit 0 only when every threshold passes
make test       # unit and acceptance tests (pytest, tests/part3/)
make demo       # 3D viewer on http://127.0.0.1:8733/ (runs in the background); make demo-stop ends it
```

Needs Python 3.11 or later with numpy and pytest. `make setup` installs the pins in `requirements.txt` with pip; on a system Python that refuses pip installs (PEP 668), run it inside a virtualenv (`python3 -m venv .venv && . .venv/bin/activate && make setup`). No network, no model, no GPU.

`python3 -m part3 run --in <pose3d.json> --out <skeleton.json> [--flip auto|on|off]` exits 0 on success, 2 when the input breaks the `pose3d.json` contract (the failing path is printed, nothing is written) and 1 when the output cannot be written. `python3 -m part3.schema <skeleton.json>` validates an output file.

What the run does, in order: validate the input, keep one person, apply the mirror option, repair left/right label swaps, take "up" from the body (feet to shoulders while standing straight) instead of the camera, express every frame in that body frame, apply one fixed 5-frame mean to remove per-frame jitter, and rebuild every frame on one standard reference body (`part3/standard_body.json`, stature 1.70 m). Timing is unchanged: every input frame and `t_ms` is kept.

- **One person.** When the input holds several ids, the id present in the most frames is kept; ties go to the larger person in the image, then to the first id. `skeleton.json` records the choice under `person`.
- **`--flip`.** A selfie-mode video can be saved mirrored, which swaps left and right in a way no pose can reveal. `auto` (default) mirrors only when the input has the top-level key `"mirrored": true`; `on` always mirrors; `off` never does. The output records the setting, whether it was applied and why under `mirror`.
- **The 4-angle agreement is synthetic.** A movement is recorded as one take from one phone at any angle, so no multi-angle recording exists. `make check-3` therefore measures the "4 phones agree within 10 degrees" criterion on four synthetic takes of the real Part 2 squat, rendered from four camera angles with Part 2-like errors (`fixtures/input/synthetic-4take/`, regenerated with `python3 -m part3.synth --out fixtures/input/synthetic-4take`). The metrics JSON says `"data_source": "synthetic"`.
- **Output for Parts 4 and 5.** `fixtures/output/` holds `skeleton.json` files with a README on the format, its invariants and its limits.
