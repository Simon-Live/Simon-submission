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
- `coordinate_frame` may be left out: the frame is then assumed, and checked through the hip-midpoint
  rule. If it is present, every field it gives must match the values above.
- `t` must strictly increase. If `t` is missing, it is taken as `index / fps`.

### Expected skeleton alternative: `skeleton.json` (`simon.skeleton.v1`)

Same top level and frame shape, but with `keyframes[]` (`{index, t, name, joints}`) in place of `frames[]`.
Extra fields, such as Part 4's `local_rotations` and `rest_offsets_m`, are ignored.

### Follower clip: `skeleton.json`

**Decided (the team, 2026-10-28, #18):** the follower file has the same `simon.animation.v1` shape as Part 4's output, with
every frame `interpolated: false`. Two optional extensions are accepted:
- a joint may be left out or set to `null` in a frame when the estimator lost it;
- a frame may carry `"conf": {"<joint>": 0..1}`. Joints below 0.3 are masked.

Validation: `part5.io.load_clip(path)` raises `InputError` with the file and field that broke the contract.

## Labels for evaluation: `fixtures/input/followers/labels.json`

See `fixtures/input/followers/README.md`.

## Output: `analysis.json` (`simon.analysis.v1`)

Written by `part5 analyse` (#10) and shown to the follower by Part 7. Build and validate it
through `part5.output` (`build_analysis`, `write_analysis`, `load_analysis`); validation raises
`OutputError` with the file and field that broke the contract. Unknown extra fields are allowed,
so the format can grow without breaking older readers. Live examples, generated from dummy
takes by `make output-examples`: `fixtures/output/analysis.example.json` (two faults) and
`fixtures/output/analysis.no-faults.example.json` (a correct take).

```json
{
  "format": "simon.analysis.v1",
  "expected": {"path": "fixtures/input/expected/exercise/animation.json", "set": "exercise", "movement": "squat"},
  "follower": {"path": "fixtures/input/followers/exercise/<take_id>/skeleton.json", "take_id": "<take_id>"},
  "faults": [
    {"measure": "foot_out", "measure_kind": "direction", "joint": "left_ankle", "body_part": "legs",
     "side": "left", "direction": "more", "magnitude_deg": 8.0, "peak_deg": 8.3, "threshold_deg": 6.0,
     "unit": "degrees", "expected_frames": [19, 43], "follower_frames": [29, 48],
     "phase": [0.211, 0.478], "coverage": 1.0, "confidence": 0.832,
     "text": "left foot slightly too far out"}
  ],
  "diagnostics": {"alignment_residual": 0.3558, "alignment_measures": ["left_knee_flexion", "..."]}
}
```

Top level:
- `format`: exactly `simon.analysis.v1`.
- `expected` / `follower`: objects identifying the input clips. `path` (non-empty string) is
  required; other ids (`set`, `movement`, `take_id`, …) pass through untouched.
- `faults`: sorted by \(|magnitude|\) descending. An empty list means no faults were found —
  a correct take still gets a file.
- `diagnostics` (optional): pipeline internals (alignment residual and the measures timing was
  taken from). Part 7 may ignore it; it is not part of the follower-facing contract.

Per fault:
- `measure`: what differed, in the side-less vocabulary shared with `labels.json` and
  `part5.rules.json` (e.g. `upper_arm_out`, `knee_flexion`, `trunk_lean_forward`).
  `measure_kind` is `angle` (a joint angle) or `direction` (a segment direction).
- `joint` / `body_part` / `side`: where it differed. Sides are the subject's own
  (`left`/`right`/`both`/`center`). For `both`, `joint` is side-stripped (`shoulder`, not
  `left_shoulder`); centre measures use the virtual joints `spine`, `shoulders`, `neck`.
  `part5.output` checks `joint` and `body_part` against the #6 measure specs.
- `direction`: `more` or `less` than the example. Together with `measure` and `side` this is
  the identity #13 matches labels on.
- `magnitude_deg`: signed size of the difference (follower − expected), the median over the
  fault run of the smoothed per-frame diffs; `peak_deg` is the largest smoothed diff in the
  run (same sign); `threshold_deg` is the rule threshold it crossed. `unit` is `degrees`.
- `expected_frames` / `follower_frames`: inclusive `[start, end]` frame range of the run in
  each clip. `phase` is the same range as a 0..1 fraction of the expected movement.
- `coverage`: fraction of the run where both measures were available (not masked).
- `confidence`: 0..1 margin-over-threshold heuristic times coverage. It is not a probability.
- `text`: the plain-words line from #9, e.g. "left foot too far out". Lowercase fragment;
  capitalise at display time if wanted.
