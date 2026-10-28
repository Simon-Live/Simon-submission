# Part 5 file contracts

## Inputs

### Expected clip: `animation.json` (`simon.animation.v1`, from Part 4)

```json
{
  "format": "simon.animation.v1", "fps": 30, "duration_s": 3.0, "frame_count": 91,
  "movement": "squat", "set": "exercise",
  "coordinate_frame": {"origin": "hip_midpoint", "x": "subject_left", "y": "world_up", "z": "anterior",
                       "position_unit": "metres", "angle_unit": "degrees"},
  "joints": ["nose", "left_eye", "...", "right_ankle"],
  "bones": [{"name": "left_thigh", "parent": "left_hip", "child": "left_knee", "length_m": 0.42}],
  "frames": [{"index": 0, "t": 0.0, "interpolated": false,
              "joints": {"nose": [0.0, 0.77, 0.04], "...": [0, 0, 0]}}]
}
```

- `joints`: the canonical 17, in this order, named for the subject's own left and right:
  nose, left_eye, right_eye, left_ear, right_ear, left_shoulder, right_shoulder, left_elbow,
  right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee, right_knee, left_ankle,
  right_ankle.
- Positions are metres `[x, y, z]`. The hip midpoint is subtracted per frame (it must be within
  1 cm of the origin). x = subject's left, y = up, z = anterior (x × y).
- `interpolated: true` marks frames Part 4 filled between keyframes. Part 5 treats them like any other frame.
- `t` must strictly increase. If `t` is missing, it is taken as `index / fps`.

### Expected skeleton alternative: `skeleton.json` (`simon.skeleton.v1`)

Same top level and frame shape, but with `keyframes[]` (`{index, t, name, joints}`) in place of `frames[]`.
Extra fields, such as Part 4's `local_rotations` and `rest_offsets_m`, are ignored.

### Follower clip: `skeleton.json`

**Assumption (open decision 1 in #18):** the follower file has the same `simon.animation.v1` shape, with
every frame `interpolated: false`. Two optional extensions are accepted:
- a joint may be left out or set to `null` in a frame when the estimator lost it;
- a frame may carry `"conf": {"<joint>": 0..1}`. Joints below 0.3 are masked.

Validation: `part5.io.load_clip(path)` raises `InputError` with the file and field that broke the contract.

## Labels for evaluation: `fixtures/input/followers/labels.json`

See `fixtures/input/followers/README.md`.

## Output: `analysis.json`

Owned by #4 (Muse), and will be documented here.
