# Contract: `pose3d.json` (input, written by Part 2)

> Copy of the maintainers' working spec `docs/specs/contract-pose3d-input.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Shared file read by Part 3. Source of truth: Part 2's README "Shared-file context" and the fixture
`fixtures/input/part2-single/pose3d.json` (see its `SOURCE.md`). Part 3 re-implements this validator
from the contract text; it never imports or copies Part 2 code.

## Shape
```json
{"frames": [{"frame": 0, "t_ms": 0.0,
             "people": [{"id": 0,
                         "joints": {"nose": {"x": -0.0367, "y": 0.6067, "z": 0.3695, "conf": 1.0}}}]}]}
```

| Field | Rule | Error path example |
|---|---|---|
| `frames` | list | `pose3d.frames: expected a list` |
| `frames[].frame` | integer, strictly increasing | `pose3d.frames[].frame: frame indices must be strictly increasing` |
| `frames[].t_ms` | finite number (ms) | `pose3d.frames[4].t_ms: expected a finite number` |
| `frames[].people` | list (may be empty) | |
| `people[].id` | int or string, not bool; unique within a frame | `pose3d.frames[2].people[1].id` |
| `people[].joints` | object with exactly the 17 canonical joints | `...joints: expected the 17 canonical joints` |
| joint `x, y, z` | finite numbers, metres | `...joints.left_knee.y: expected a finite number` |
| joint `conf` | number in [0, 1] | `...joints.nose.conf: 1.2 not in [0, 1]` |
| `mirrored` (optional, top level) | `true` or `false` | `pose3d.mirrored: expected true or false` |

Canonical joints, in order: nose, left_eye, right_eye, left_ear, right_ear, left_shoulder,
right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee,
right_knee, left_ankle, right_ankle (subject's left and right).

## Frame (per frame and per person)
Origin at the hip midpoint; x = subject's left (left hip minus right hip, made horizontal); y = up;
z = x cross y (anterior). Metres.

## Known properties Part 3 relies on (ASM-001 to ASM-003)
- `conf` is not calibrated: 1.0 when the joint was inside the image, 0.3 when extrapolated outside it.
  An occluded joint inside the image is 1.0. Part 3 treats `conf < 1` as "less trusted", never as a
  probability.
- "Up" is the camera's up. A tilted phone tilts every pose; Part 3 removes it (spec step 5).
- Every frame is canonicalised on its own, so there is no rotation between frames and a left/right
  hip-label swap shows as a frame rotated 180 degrees about y.
- "Up" in the input is never trusted: Part 3 takes up from the body (spec step 5).
- Unknown extra keys are ignored (not an error), so a `skeleton.json` is also a valid input.

## What Part 3 asks of producers (optional, never waited on)
- Top-level `"mirrored": true` when the saved video is mirrored (left and right reversed against
  reality), `false` when known not to be. A non-boolean `mirrored` fails validation at path
  `pose3d.mirrored: expected true or false`. Without the key, `--flip auto` treats the file as not
  mirrored. Part 3 works without it; integration adds it later.
- The hint must describe the saved file, not the camera. A front camera alone does not mean a
  mirrored file: iOS saves front-camera captures unmirrored unless the user turns on "Mirror Front
  Camera", and browser recording APIs record the unmirrored stream even when the preview is mirrored
  (ADR-0005). Any camera-facing field is ignored.
- Several people are allowed; Part 3 keeps one (spec step 2).

## Change control
A change on Part 2's side reaches Part 3 only as a new fixture copy; refresh `fixtures/input/part2-single/`
and its `SOURCE.md` hash, then rerun `make check-3`.
