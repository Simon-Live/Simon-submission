# Part 5 file contracts

This page is the field reference. The same contract is published as JSON Schemas in `contracts/`
(`analysis`, `input-animation`, `input-skeleton`, `labels`, `metrics`, each with a `version`).
`python -m part5 contract` prints them with the compatibility table, `python -m part5 doctor <file>`
checks one file and `make check-5-contract` proves the schemas, the fixtures and the golden outputs
agree. `CONTRACT.md` says who sends what and what Part 7 must do with `analysis.json`.

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
`fixtures/output/analysis.no-faults.example.json` (a correct take). The machine-readable form is
`contracts/analysis.schema.json` (version 1.1.0): it adds optional fields to this shape, so a 1.0
document validates against it, and `CONTRACT.md` names what Part 7 must read first.

```json
{
  "format": "simon.analysis.v1",
  "schema_version": "1.1.0",
  "expected": {"path": "fixtures/input/expected/exercise/animation.json", "set": "exercise", "movement": "squat"},
  "follower": {"path": "fixtures/input/followers/exercise/<take_id>/skeleton.json", "take_id": "<take_id>"},
  "status": {"code": "ok", "text": "Compared with the expected movement."},
  "faults": [
    {"measure": "foot_out", "measure_kind": "direction", "joint": "left_ankle", "body_part": "legs",
     "side": "left", "direction": "more", "magnitude_deg": 8.0, "peak_deg": 8.3, "threshold_deg": 6.0,
     "unit": "degrees", "expected_frames": [19, 43], "follower_frames": [29, 48],
     "runs": [[19, 43]], "phase": [0.211, 0.478], "coverage": 1.0, "confidence": 0.832,
     "text": "left foot slightly too far out"}
  ],
  "diagnostics": {"alignment_residual": 0.3558, "alignment_measures": ["left_knee_flexion", "..."],
                  "guard": {"residual": 0.3558, "timing_corr": 0.97, "span_share": 0.92,
                            "limits": {"max_residual": 0.631, "min_timing_corr": 0.784}}}
}
```

Top level:
- `format`: exactly `simon.analysis.v1`.
- `schema_version` (optional, 1.1.0): `"1.1.0"`; a string `1.x.y`. A 1.0 document has none.
- `expected` / `follower`: objects identifying the input clips. `path` (non-empty string) is
  required; other ids (`set`, `movement`, `take_id`, …) pass through untouched.
- `status` (optional, 1.1.0): `{code, text}`. `code` is `ok` or `different_movement`. A take the
  movement guard refused (it does not look like the expected movement at all) has code
  `different_movement`, a plain-words `text` to show the follower, and `faults: []`; read
  `status` before `faults`. An accepted take has `ok` and a short sentence.
- `faults`: sorted by \(|magnitude|\) descending. An empty list means no faults were found —
  a correct take still gets a file. Always empty when `status.code` is `different_movement`.
- `diagnostics` (optional): pipeline internals (alignment residual and the measures timing was
  taken from). Part 7 may ignore it; it is not part of the follower-facing contract.
  `part5 analyse` (#10) also writes `follower_span` (first and last matched follower frame) and
  `warnings`, a list of plain sentences worth checking before trusting the result, e.g. when
  less than 60% of the follower clip matched the movement. That is harmless if the rest is
  idle lead-in or tail, but it is also what a follower much slower than the example, or one
  doing several repetitions, looks like.
  `diagnostics.guard` (1.1.0) holds the movement guard's numbers: `residual` (mean capped z cost
  per path cell of the alignment), `timing_corr` (median Pearson correlation of the expected and
  matched follower series over the measures that carry timing; left out when no measure has one),
  `span_share` (matched share of the follower frames), and `limits` (`max_residual`,
  `min_timing_corr`, from `part5/rules.json`). A take is refused when `residual` is above its
  limit or `timing_corr` below its limit; `span_share` only ever warns.

Follower and expected clips may have different frame rates: the follower is resampled onto
the expected clip's clock (its `fps`, or the median step of `t`) before alignment, and every
follower frame number in the output (`follower_frames`, `diagnostics.follower_span`) indexes
the follower file as written.

`part5 analyse` exits 0 when it wrote an `ok` analysis, and 1 with a message naming the file when
an input is malformed, less than half the body can be measured, or the takes can't be aligned
(a follower more than 2x faster than the example). It exits 3 when it wrote a refused analysis
(`status.code` `different_movement`, `faults: []`) and prints the status text: exit 3 means a
valid `analysis.json` was written, so a caller treats 0 and 3 as "written, read `status`".

Per fault:
- `measure`: what differed, in the side-less vocabulary shared with `labels.json` and
  `part5.rules.json` (e.g. `upper_arm_out`, `knee_flexion`, `trunk_lean_forward`, `knee_valgus`).
  `measure_kind` is `angle` (a joint angle) or `direction` (a segment direction).
  `knee_valgus` is a direction: the angle of the knee's offset inside the hip to ankle line over
  the thigh length, so `more` reads "knee caving in" and `less` "knee pushed out".
- `joint` / `body_part` / `side`: where it differed. Sides are the subject's own
  (`left`/`right`/`both`/`center`). For `both`, `joint` is side-stripped (`shoulder`, not
  `left_shoulder`); centre measures use the virtual joints `spine`, `shoulders`, `neck`.
  `part5.output` checks `joint` and `body_part` against the #6 measure specs.
- `direction`: `more` or `less` than the example. Together with `measure` and `side` this is
  the identity #13 matches labels on.
- `magnitude_deg`: signed size of the difference (follower − expected), the median over every
  counted run of the smoothed per-frame diffs; `peak_deg` is the largest smoothed diff in the
  counted runs (same sign); `threshold_deg` is the rule threshold it crossed. `unit` is `degrees`.
- `expected_frames` / `follower_frames`: inclusive `[start, end]` frame range of the longest
  counted run in each clip. `phase` is the same range as a 0..1 fraction of the expected movement.
- `runs` (optional, 1.1.0): every counted run as `[[start, end], ...]` in expected frames, in
  order. A fault counts when its runs of at least `min_run_frames` frames sum to `min_fraction`
  of the clip, so a fault held in several stretches is one fault with several runs; for a single
  run it is `[expected_frames]`.
- `coverage`: fraction of the counted frames where both measures were available (not masked).
- `confidence`: 0..1 margin-over-threshold heuristic times coverage. It is not a probability.
- `text`: the plain-words line from #9, e.g. "left foot too far out". Lowercase fragment;
  capitalise at display time if wanted.

## Evaluation metrics (`simon.part5.metrics.v1`)

Produced by `part5.evaluate.score` / `evaluate_corpus` (#13) and printed by `make check-5`
(#14). It scores `analysis.json` faults against `labels.json`:

- **Match rule (decided 2026-10-28):** a prediction matches a label on measure + side +
  direction; a label with `side: "both"` accepts a prediction on either side (a `"both"`
  prediction does *not* satisfy a one-sided label); trunk faults match at body-part level.
  Matching is one-to-one and maximal. Label fault `type`s map to prediction measures via
  `LABEL_TYPE_TO_MEASURE` in `part5/evaluate.py` (e.g. the generator's `foot_out`, whose label
  says `thigh_direction`, is scored as the `foot_out` measure).
- **Shape:** `{"format", "slices", "by_lighting", "good_light", "overall"}`. `slices` is keyed
  `"<lighting>/<angle>"` (e.g. `"good/side"`), or `"dropout/<angle>"` for takes labelled
  `variant: "dropout"`; every other angle is reported separately, per the README. Each entry
  has `tp`, `fp`, `fn`, `takes`, `correct_takes`, `faults_on_correct_takes`, `precision`,
  `recall` and `refused` (takes the movement guard refused; a refused take has no
  predictions, so its labels count as misses). An empty denominator scores 1.0: nothing
  predicted (or labelled) in that slice is not itself a failure — misses appear in the other
  ratio. #14 gates on **every good-light angle slice separately** (`good/front`, `good/45`,
  `good/side` must each reach precision ≥ 0.85 and recall ≥ 0.75 with 0 faults on correct
  takes), so one weak angle cannot hide inside an aggregate; `good_light` is a summary only.
  Low-light slices are reported, not gated. A labelled take with no analysis is an error
  (the missing `take_id`s are listed), never scored as "no predictions".

`make check-5` (#14, `part5/check.py`) prints this document with a `gate` block added:
`thresholds`, `gated_slices` (`good/front`, `good/45`, `good/side` → true/false), `failures`
(one plain line per failed criterion) and `passed`. It exits 0 only when `passed` is true; a
take that can't be analysed, or a gated slice with no takes, no labelled faults or no correct
takes (nothing to measure a criterion on), also fails the check.
