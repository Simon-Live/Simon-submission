# Simon Part 5 — Compare 3D animations and analyse faults


Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
This repo is **only** Simon Part 5. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way — that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #59. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 5).

## Input

The expected `animation.json` (or `skeleton.json`) plus a follower's `skeleton.json`. Fixtures in `fixtures/input/`.

## Output

`analysis.json` — per fault: what differed, which joint/body part, the size of the difference, and a plain-words line (e.g. "left foot too far out", "elbows wider than the example").

## Shared-file context (only what this part touches)

Canonical 17 joints (subject's left/right): nose, left_eye, right_eye, left_ear, right_ear, left_shoulder, right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee, right_knee, left_ankle, right_ankle. Coordinate frame: origin at the hip midpoint per frame; x = subject's left (horizontal), y = world up, z = anterior (x × y); metres and degrees. Measurements are joint angles and segment directions between corresponding joints in the two skeletons, compared at the same phase of the movement.

## Frontier model

none (rule maths is the measurement; plain-words analysis from the measurements)

## Definition of done

On labelled follower clips (correct and deliberate-fault takes, several angles): fault precision ≥0.85 and recall ≥0.75 in good light, every other angle reported separately; on correct takes it reports no faults.

Done-check: `make check-5` — prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** A follower clip replayed with each fault listed and the joint highlighted.
- **Integrated:** In Part 7, this analysis is what the follower is shown after a take.

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-5`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.

## Dev setup

```bash
uv sync                # Python ≥3.10 + numpy, pytest
make test              # unit tests
make dummy-data        # regenerate fixtures/input/followers/ (synthetic labelled takes)
uv run part5 analyse --expected fixtures/input/expected/exercise/animation.json \
  --follower fixtures/input/followers/exercise/<take_id>/skeleton.json --out out/analysis.json
make check-5           # done-check
```

Work is coordinated in GitHub issues: checklist #17, team chat #18.
