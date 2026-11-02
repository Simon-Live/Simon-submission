# Part 5 file contracts

This page is the field reference. The same contract is published as JSON Schemas in `contracts/`
(`analysis`, `input-animation`, `input-skeleton`, `labels`, `metrics`, `replay`, `input-feet`, each with a `version`).
`python -m part5 contract` prints them with the compatibility table, `python -m part5 doctor <file>`
checks one file and `make check-5-contract` proves the schemas, the fixtures and the golden outputs
agree. `CONTRACT.md` says who sends what and what Part 7 must do with `analysis.json` and `replay.json`.

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

### Feet side file (optional): a Part 2 `pose3d.json` with `extra_joints` (ADR-0015)

Published as `contracts/input-feet.schema.json` (1.0.0); `make check-5-contract` validates every committed `feet.json`
(`fixtures/input/followers`, `fixtures/input/expected-feet`, `fixtures/input/eval/real`) against it and loads it through
`part5.feet`. A file has no `format` key; `provenance` says where it came from (synthetic: `source`, `generator`, `seed`,
which is null for a derived example file; Part 2's: `contract_version`, `backend`, `extra_joints`).

The 17 joints end at the ankle. Part 2 publishes the heel, big toe and small toe of each foot as `extra_joints`, and its
contract says Part 3 does not carry them, so Part 5 reads them from Part 2's own file, one per clip, beside the clip:
`part5 analyse ... [--expected-feet PATH] [--follower-feet PATH] [--expected-feet-person N] [--follower-feet-person N]`
(`part5.pipeline.run` and `analyse` take `expected_feet`, `follower_feet`, `expected_feet_person`, `follower_feet_person`).

```json
{"frames": [{"frame": 0, "t_ms": 0.0, "people": [{"id": 0,
    "joints": {"left_hip": {"x": 0.1, "y": 0.0, "z": 0.0, "conf": 1.0}, "...": {}},
    "extra_joints": {"left_big_toe": {"x": 0.1, "y": -0.9, "z": 0.1, "conf": 0.9}, "left_small_toe": {}, "left_heel": {},
                     "right_big_toe": {}, "right_small_toe": {}, "right_heel": {}}}]}],
 "t0_pts_ms": 0.0, "mirrored": false, "provenance": {"source": "synthetic"}}
```

- Only the two hips and the six foot points are read; the knees and ankles are ignored. A synthetic file uses the same shape.
- `foot_rotation` and `ankle_inversion`, left and right, are computed per frame of the side file, inside the side file's own
  frame, from its own joints and foot points. A point is seen when it is present, finite and `conf` is at least 0.5; a
  measure is NaN in a frame where a point it reads is not seen. A top-level `mirrored: true` swaps the left and right series.
- A clip frame at time `t` (the clip's own `t`, seconds) takes the side frame whose `(t_ms - t0_pts_ms) / 1000` is nearest,
  within half the file's median frame step over all its frames (at least 0.008 s); otherwise the frame's foot values are NaN. `t0_pts_ms` defaults
  to 0. `*-feet-person` is matched to `people[].id` (default 0).
- A foot measure is usable in a clip when it is a number in at least 80% of its frames and steady (attempt 5, ADR-0015
  Amendment 4: its frame-to-frame jitter, the median change between consecutive frames of the file, is at most the
  `max_jitter_deg` of its entry in `rules.json`, 4 degrees a frame), and is compared only when usable on
  both sides. A file with no `extra_joints`, or a pair where only one clip has feet, is not an error: the foot measures are
  hidden for the pair and `diagnostics.feet.hidden_reason` says why. A take compared repetition by repetition compares them rep by rep (ADR-0017; before attempt 4 they were hidden there).
- `InputError` (exit 1, `part5 analyse: <file>: ...`): the file is unreadable or not this shape, the person id is in no frame,
  or no clip frame matches a frame of the file in time.
- `labels.json` takes may carry `expected_feet` and `follower_feet` (paths from the repository root, like `expected` and
  `follower`); the label types `foot_turned_out`, `foot_turned_in`, `ankle_rolled_in` and `ankle_rolled_out` map to
  `foot_rotation more`, `foot_rotation less`, `ankle_inversion more` and `ankle_inversion less`.

## Labels for evaluation: `fixtures/input/followers/labels.json`

See `fixtures/input/followers/README.md`.

## Output: `analysis.json` (`simon.analysis.v1`, schema 1.14.0)

Written by `part5 analyse` (#10) and shown to the follower by Part 7. Build and validate it
through `part5.output` (`build_analysis`, `write_analysis`, `load_analysis`); validation raises
`OutputError` with the file and field that broke the contract. Unknown extra fields are allowed,
so the format can grow without breaking older readers. Live examples, generated from dummy
takes by `make output-examples` through the same pipeline and score hook `part5 analyse` uses (with the
`template` phrasing, whatever the environment): `fixtures/output/analysis.example.json` (two faults),
`fixtures/output/analysis.no-faults.example.json` (a correct take), `fixtures/output/analysis.fault-capped.example.json`
(present while the rules ship v2 or v3: a take that reports one fault and hits the ceiling of 89, value 89 B, `fault_cap` 89, `uncapped` 94 A, no
`capped_by`; a dance take analysed without its foot files, so the arm fault it reports is not the foot fault its name
mentions), `fixtures/output/analysis.double-capped.example.json` (present while the rules ship v3: a real
take that reports two faults and hits the ceiling of 79, value 79 C, `fault_cap` 79, `uncapped` 82 B, no `capped_by`) and
`fixtures/output/replay.example.json` (the replay of the first). The machine-readable form is `contracts/analysis.schema.json` (version 1.14.0):
it adds optional fields to this shape, so a 1.0 document validates against it, and `CONTRACT.md` names what
Part 7 must read first. `simon.score.v2` failed held-out score seed 59 (docs/thresholds.md) and ADR-0018's fallback shipped
`simon.score.v1`; `simon.score.v3` then held all five targets on score seed 61 (docs/thresholds-score-v3.md) and ships, so the
rules in this tree carry it and both samples above are written. `make score-fallback` remains the reversal recipe: it puts v1
back and removes both.

Every addition is optional and told apart by its fields; `schema_version` says which to expect:

| `schema_version` | Adds | Written when |
|---|---|---|
| none (1.0) | the fields in the example below that are not listed in a later row | a producer from before `1.1.0` |
| `1.1.0` | `schema_version`, `status`, `phrasing`, `faults[].joints`, `runs`, `coaching`, `diagnostics.guard` | |
| `1.2.0` | `faults[].follower_t_s`, `at_s`, `follower_runs`, `text_timed`, `lateral`, `lateral_m`; `score` (`simon.score.v1`) | a take with no later group |
| `1.3.0` | `faults[].reps`, `score.per_rep`, `diagnostics.guard.reps`, `diagnostics.expected_reference`, `diagnostics.visibility` | a take compared one repetition at a time (ADR-0010) |
| `1.4.0` | `warnings`, `match`, `score.capped_by`, a fault `confidence` of `"low"` (ADR-0012) | the take earned a warning |
| `1.5.0` | `faults[].cue`, `cue_kind`; `score.basis`, `timeline`, `tempo`; `insights` (ADR-0013, ADR-0014) | every new document |
| `1.6.0` | faults with `measure` `foot_rotation` or `ankle_inversion` (`body_part` `feet`); `diagnostics.feet` (ADR-0015) | every new document is `1.6.0`; the foot fields appear only when a feet file was given for either clip |
| `1.7.0` | `profile`; `score.components.tempo` and the same on each window, dance only (ADR-0016) | every new document is `1.7.0`, and `profile` is always present; the tempo points appear only under the dance profile |
| `1.8.0` | `diagnostics.near_misses` (TICKET-043, `docs/specs/near-misses.md`) | every new document is `1.8.0`; the field is present whenever the take was compared, also when it lists nothing, and absent on a take that could not be aligned |
| `1.9.0` | `phrasing.lang`, `phrasing.lang_requested`, `phrasing.faults[].text` and `.lang`; top-level `second_opinion` (TICKET-045, TICKET-046, `docs/specs/second-opinion.md`); `score.uncapped` (Part 7 TICKET-155); the top-level `source` and the `no_person` warning code (TICKET-048) | every new document is `1.9.0` and carries the language fields; `second_opinion` is written only when both clips were given as videos (`--expected-video`, `--follower-video`), with `status` `ok`, `fallback` or `skipped`, and is never read by the score; `score.uncapped` only when a warning's cap lowered the value; `source` and `no_person` only in Part 7's own analysis of a take with no person (below), never by Part 5 |
| `1.10.0` | `score.fault_cap`; `score.version` `simon.score.v2`; the wider meaning of `score.uncapped` (TICKET-047, ADR-0018, `docs/specs/score-v2.md`) | every new document is `1.10.0`; its score is `simon.score.v1` (`simon.score.v2` failed held-out score seed 59 and ADR-0018's fallback shipped v1; read `score.version`); under v2 `fault_cap` (89) is written when the take reports a fault, and `uncapped` when the fault cap or the warning cap lowered the value; `capped_by` is unchanged |
| `1.11.0` | `score.version` `simon.score.v3`; `score.fault_cap` is the ceiling in force, 89 or 79 (TICKET-060, ADR-0019, `docs/specs/score-v3.md`) | every new document is `1.11.0`; read `score.version` (the rules in this tree ship `simon.score.v3`: it held all five targets on score seed 61, docs/thresholds-score-v3.md; `make score-fallback` remains the reversal recipe and puts `simon.score.v1` back); under v3 `fault_cap` is 89 for a take that reports one fault and 79 for a take whose `faults` list holds two or more entries, written whether or not it lowered the value; `uncapped` and `capped_by` mean what they meant in `1.10.0` |
| `1.12.0` | `faults[].rep_sizes`; `score.per_rep[].rep` and `.tempo_ratio`; `diagnostics.near_misses.items[].margin_deg` (TICKET-071, `docs/specs/history-per-rep.md`) | every new document is `1.12.0`; `rep_sizes`, `rep` and `tempo_ratio` only on a take compared one repetition at a time, `margin_deg` on every near miss; they exist for comparing takes with each other, and no fault, score or insight reads them |
| `1.13.0` | `score.credit` (`simon.credit.v1`, the DDR-style credit display, ADR-0020) | every new document is `1.13.0`; `score.credit` is always written, null when nothing was compared |
| `1.14.0` | `body_mask`, the limb chains the follower declared not scored (TICKET-084, ADR-0023, `docs/specs/body-mask.md`); `phrasing.cues[]` and `phrasing.native_review` (TICKET-080, `docs/specs/language-cues.md`) | every new document is `1.14.0`; `body_mask` only when a mask was declared (`--mask`, API field `mask`), below; `phrasing.cues[]` and `phrasing.native_review` only for a request in a listed language other than English, see "Cues in the follower's language" below; `quality.signals.heading_offset_deg` and the reason `heading_offset` in every quality block (TICKET-086, below); a document with neither a mask nor another language differs from `1.13.0` in `schema_version` and the heading signal of `quality` (with its reason past 5 degrees) only |

```json
{
  "format": "simon.analysis.v1",
  "schema_version": "1.14.0",
  "profile": "fitness",
  "expected": {"path": "fixtures/input/expected/exercise/animation.json", "set": "exercise", "movement": "squat"},
  "follower": {"path": "fixtures/input/followers/exercise/<take_id>/skeleton.json", "take_id": "<take_id>"},
  "status": {"code": "ok", "text": "Compared with the expected movement."},
  "faults": [
    {"measure": "elbow_flexion", "measure_kind": "angle", "joint": "right_elbow", "body_part": "arms",
     "side": "right", "direction": "more", "magnitude_deg": 36.1, "peak_deg": 43.0, "threshold_deg": 20.0,
     "unit": "degrees", "expected_frames": [18, 77], "follower_frames": [20, 65],
     "runs": [[18, 77]], "phase": [0.2, 0.856], "coverage": 1.0, "confidence": 1.0,
     "text": "right elbow bent more than the example",
     "cue": "Straighten your right arm more", "cue_kind": "range",
     "follower_t_s": [0.667, 2.167], "at_s": 0.7, "follower_runs": [[20, 65]], "lateral": null,
     "text_timed": "right elbow bent more than the example at 0.7 s",
     "joints": ["right_elbow"], "coaching": "right elbow bent more than the example at 0.7 s"}
  ],
  "diagnostics": {"alignment_residual": 0.3925, "alignment_measures": ["left_elbow_flexion", "..."],
                  "follower_span": [3, 75], "warnings": [],
                  "guard": {"residual": 0.3925, "timing_corr": 0.9892, "span_share": 0.9605,
                            "limits": {"max_residual": 0.5677, "min_timing_corr": 0.8336}},
                  "near_misses": {"total": 1, "omitted": 0, "items": [
                    {"measure": "knee_flexion", "side": "left", "joint": "left_knee", "body_part": "legs",
                     "direction": "more", "magnitude_deg": 10.8, "peak_deg": 15.2, "threshold_deg": 9.0,
                     "margin_deg": 1.8, "expected_frames": [18, 31], "follower_frames": [20, 29], "frames_over": 14,
                     "counted_frames": 14, "needed_frames": 35, "min_run_frames": 4,
                     "reason": "persistence", "shortfall_frames": 21}]}},
  "insights": [{"cue": "Straighten your right arm more", "why": "Right elbow bent more than the example at 0.7 s",
                "kind": "range", "at_s": 0.7, "window": 0, "points": 17.2, "measure": "elbow_flexion",
                "side": "right", "joint": "right_elbow"}],
  "phrasing": {"requested": "template", "backend": "template", "model": null, "fallback_reason": null,
               "selected_by": "default", "faults": [{"backend": "template", "model": null, "fallback_reason": null}]},
  "score": {"version": "simon.score.v1", "value": 66, "grade": "D", "components": {"faults": 33.86, "similarity": 0.58},
            "params_sha256": "<64 hex>", "basis": "windows",
            "timeline": [{"t_s": [0.1, 2.5], "value": 66, "grade": "D", "components": {"faults": 33.86, "similarity": 0.58},
                          "misses": [{"text": "right elbow bent more than the example at 0.7 s", "measure": "elbow_flexion",
                                      "side": "right", "joint": "right_elbow", "t_s": [0.667, 2.167], "at_s": 0.7,
                                      "points": 17.2, "cue": "Straighten your right arm more", "cue_kind": "range",
                                      "direction": "more"}],
                          "tempo": {"ratio": 0.8, "cue": "Slow down to match the trainer"}}],
            "tempo": {"ratio": 0.8, "cue": "Slow down to match the trainer"}}
}
```

Top level:
- `format`: exactly `simon.analysis.v1`.
- `schema_version` (optional, 1.1.0): a string `1.x.y`, see the table. A 1.0 document has none.
- `profile` (1.7.0, ADR-0016): the analysis profile that produced the document, a non-empty string, today `dance`,
  `rehab` or `fitness` (the names are data in `part5/profiles.json`, so the schema has no enum). Always present in a
  new document and required by `validate_analysis` from `1.7.0`; a document without it is read as `fitness`. `fitness`
  is the default and is the analysis as it was before profiles. `dance` and `rehab` loosen the position tolerances of
  detection (never the range ones) and, for the same take, never report a fault `fitness` does not (one `fitness`
  reports on both sides may be kept on one side; also for a take compared repetition by repetition). **A score is read within its profile**:
  a dance 84 and a fitness 84 mean different things, because the thresholds the score is measured against move with
  the profile and dance charges tempo. The tolerances are set by hand and not calibrated on any labelled dancer or
  patient (`docs/specs/profiles.md`).
- `expected` / `follower`: objects identifying the input clips. `path` (non-empty string) is
  required; other ids (`set`, `movement`, `take_id`, …) pass through untouched.
- `status` (optional, 1.1.0): `{code, text}`. From `1.4.0` `code` is always `ok`: a take is always analysed
  (ADR-0012) and what used to be a refusal is a `warnings` entry. Only a document written before 1.4.0 can carry
  `different_movement`, `not_enough_visible` or `moving_part_out_of_frame` (then `faults: []` and `score: null`);
  read `status` before `faults`, and a file with no `status` is a 1.0 file: read it as `ok`. No schema change: the
  `text` of a take with no warning is "Compared with the expected movement."; of a take with one warning it is
  "Compared with the expected movement, with a warning that caps the grade at F."; of a take with more than one it is
  "Compared with the expected movement, with 2 warnings that cap the grade at F." (the number of warnings in place of
  2). The code stays `ok`; `warnings[].text` still says what each warning is.
- `faults`: sorted by \(|magnitude|\) descending. An empty list means no faults were found:
  a correct take still gets a file.
- `warnings` and `match` (1.4.0): present only when the take earned a warning, see "Always analysed" below.
- `score` (1.2.0, never null from 1.4.0): `simon.score.v1`, `simon.score.v2` from 1.10.0 or `simon.score.v3` from 1.11.0, see "Score" below.
- `insights` (1.5.0): what to work on, see "Coaching cues and insights" below.
- `phrasing` (optional, 1.1.0): who phrased `faults[].coaching`: `requested` and `backend` (`template`,
  `local-llm` or `muse-spark`), `model`, `fallback_reason`, `selected_by` (`flag` for an explicit backend, `live`
  for the live default, `default` for the template) and, per fault, `faults[k] = {backend, model, fallback_reason}`
  (`model` is null for the template). Phrasing changes `coaching` only, and through it the `why` of an insight that
  repeats a live English line (below): never `text`, `cue`, a scored field or the score. From 1.9.0 `lang` (and
  `lang_requested`), and per fault `text` and `lang`. From 1.14.0, for a listed language other than English,
  `cues[]` and `native_review` (below).
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
  `min_timing_corr`, from `part5/rules.json`). A take earns a `low_match` warning when `residual` is above its
  limit or `timing_corr` below its limit; `span_share` only ever adds a line to `diagnostics.warnings`.
  `diagnostics.visibility` (1.3.0, ADR-0011) is present only when the take was compared on the measures the camera
  sees, not the full body: `usable_measures` (count), `excluded` (the measures left out) and `rule`. Part 2 marks a
  joint outside the image with conf 0.3. Fewer than 3 usable measures earns a `not_enough_visible` warning (ask for
  more of the body in frame); when none of the measures that move in the expected clip is usable in the take it
  earns `moving_part_out_of_frame`, whose text names the body part, and `diagnostics.visibility.moving_measures` and
  `moving_usable` list the measures.
  A take is compared one repetition at a time when the whole-clip guard refuses it and either clip holds several reps
  (ADR-0010) and, since attempt 4 (ADR-0017), whenever the expected clip holds two or more, so every take of a multi-rep
  example carries these fields; the dance example holds two.
  `diagnostics.guard.reps` (1.3.0, only for a take compared one repetition at a time, ADR-0010) lists each follower
  repetition: `span_s` (start and end on the follower file's clock), `residual`, `timing_corr` (null when the rep could
  not be aligned) and `ok`; `residual` and `timing_corr` above are then medians over the reps.
  `diagnostics.expected_reference` (1.3.0) says which part of the expected clip the reps were compared with:
  `kind` `first_rep` or `whole`, its `frames` and `span_s`, `expected_reps`, `follower_reps` and the cut `measure`.
  Since attempt 4 `frames` and `span_s` are the reference of the first follower rep (the example's first rep): rep `k`
  is compared with the example's rep `k` when the follower has no more reps than the example, so a fault first found in a
  later rep lies in that example rep, and `faults[].expected_frames` are always frames of the expected file.
  A fault of such a take has `reps` (1.3.0): the 0-based follower repetitions it was found in, and its time fields are
  those of the first; `score.per_rep` lists each accepted repetition's `value` and `grade`. From 1.12.0 such a fault also
  has `rep_sizes` (below) and each `per_rep` entry its `rep` and `tempo_ratio` (see "Score").
  `diagnostics.feet` (1.6.0, ADR-0015) is present only when a feet file was given for either clip:
  `{expected, follower, compared, hidden_reason}`. `expected` and `follower` are `{source, person, frames_matched, usable}`
  (`source` null when no file was given for that clip, `frames_matched` how many of the clip's frames took a frame of the file
  in time, `usable` the foot measures seen in at least 80% of them and steady, named `left_foot_rotation` and so on: a
  foot that jitters, the far foot of a side view, is left out); `compared` is
  what the pair was compared on; `hidden_reason` is null when anything was compared and otherwise plain words (no file,
  a file with no foot points, too few frames seen, nothing steady enough to read, a take that could not be aligned).
  `diagnostics.near_misses` (1.8.0, TICKET-043, `docs/specs/near-misses.md`) answers "why no fault?": the candidate
  faults detection considered and dropped, `{total, omitted, items}`. A candidate is a measure on one side in one
  direction with at least one frame past its threshold; it is a near miss when it is not a reported fault. `items`
  holds the `total` largest by `abs(magnitude_deg)` up to 10 (then measure, side, direction), `omitted` the rest. It
  is present whenever the take was compared, with `total` 0 and `items` `[]` when nothing came past a threshold, and
  absent only on a take that could not be aligned (no detection ran). Each item has `measure`, `side` (`left`,
  `right` or `center`, never `both`: sides are merged for faults only), `joint`, `body_part`, `direction`;
  `magnitude_deg` and `peak_deg`, sized like a fault (the signed median and the largest value over the runs that
  count, or over every frame past the threshold when no run is long enough), `threshold_deg`; `margin_deg` (1.12.0,
  TICKET-071): `abs(magnitude_deg)` minus `threshold_deg`, to 0.1 degree, positive when the candidate went past the
  threshold by that many degrees before persistence (or the rep count) dropped it, 0 when it sat on it and negative
  when it stayed short of it; detection lists a candidate only when a frame is past its threshold, so the value written
  today is 0 or more, and the negative sign is defined so a reader never has to guess it; `expected_frames` and
  `follower_frames`, the longest run past the threshold (the follower file's own frames, like a fault's);
  `frames_over` (frames past the threshold), `counted_frames` (those in runs of at least `min_run_frames`),
  `needed_frames` (`max(min_frames_floor, round(min_fraction x clip frames))`, or `min_frames`) and `min_run_frames`;
  and `reason`: `persistence` (counted fewer than needed; `shortfall_frames` is the difference) or `explained_by`
  (it persists but a kept fault explains it; `explained_by` is `{measure, side, direction}` of that fault as it is
  reported, `both` when the sides were merged). Under a profile the numbers are the profile's own config (its
  threshold and persistence), and an explanation is judged at the `fitness` baseline. A take compared one repetition at
  a time lists them at the take level like its faults: one item per measure, side and direction the take does not
  report, with `reps` (the reps it crossed the threshold in) and the numbers of the rep that came closest, its
  `expected_frames` on the expected file; its reason is also `reps` (reported in `found_in_reps` reps, fewer than the
  `needed_reps`, half the accepted reps rounded up) or `fitness` (half the reps reported it and a profile's take-level
  check dropped it). The field changes no fault, score or insight, is for people debugging a take and is not shown to
  the follower.

Follower and expected clips may have different frame rates: the follower is resampled onto
the expected clip's clock (its `fps`, or the median step of `t`) before alignment, and every
follower frame number in the output (`follower_frames`, `follower_runs`, `diagnostics.follower_span`) indexes
the follower file as written.

`part5 analyse` exits 0 when it wrote the analysis (with or without `warnings`: read `warnings`, the grade is
capped at F when there are any), 1 with a message naming the file when an input is malformed or unreadable, a clip
is over the size bounds or an output cannot be written (nothing is written), and 2 for a usage error. Exit 3
(a refused analysis) is no longer produced (ADR-0012). `--replay <path>` also writes the replay file, below;
an unwritable replay path exits 1 and the analysis that was written stays.

Per fault:
- `measure`: what differed, in the side-less vocabulary shared with `labels.json` and
  `part5.rules.json` (e.g. `upper_arm_out`, `knee_flexion`, `trunk_lean_forward`, `knee_valgus`).
  `measure_kind` is `angle` (a joint angle) or `direction` (a segment direction).
  `knee_valgus` is a direction: the angle of the knee's offset inside the hip to ankle line over
  the thigh length, so `more` reads "knee caving in" and `less` "knee pushed out".
  `foot_rotation` and `ankle_inversion` (1.6.0, only with a feet file) are directions with `body_part` `feet` and `joint` an
  ankle: `foot_rotation` is how far the toes point away from the midline against the pelvis's forward (`more` reads "foot
  turned out", cue "Turn your left foot in"; `less` reads "foot not turned out enough", cue "Turn your left foot out");
  `ankle_inversion` is how far the foot is rolled onto an edge, about its long axis, against the vertical (`more` is
  the outer edge down, the sole turning toward the midline: it reads "ankle rolling out", cue "Keep your left ankle
  straight"; `less` is the inner edge down: it reads "ankle rolling in", cue "Stop your left ankle rolling in").
  A document with a foot fault needs a reader built on the 1.6.0 schema (the `measure` and `body_part` enums).
- `joint` / `body_part` / `side`: where it differed. Sides are the subject's own
  (`left`/`right`/`both`/`center`). For `both`, `joint` is side-stripped (`shoulder`, not
  `left_shoulder`); centre measures use the virtual joints `spine`, `shoulders`, `neck`.
  `part5.output` checks `joint` and `body_part` against the #6 measure specs.
- `joints` (optional, 1.1.0): the canonical joint names to highlight; for `both` the left and right joint.
- `direction`: `more` or `less` than the example. Together with `measure` and `side` this is
  the identity #13 matches labels on.
- `magnitude_deg`: signed size of the difference (follower − expected), the median over every
  counted run of the smoothed per-frame diffs; `peak_deg` is the largest smoothed diff in the
  counted runs (same sign); `threshold_deg` is the rule threshold it crossed. `unit` is `degrees`.
- `expected_frames` / `follower_frames`: inclusive `[start, end]` frame range of the longest
  counted run in each clip (under a `profile` other than `fitness`, the counted run that overlaps the fitness
  fault's run most; `docs/specs/profiles.md`). `phase` is the same range as a 0..1 fraction of the expected movement.
- `runs` (optional, 1.1.0): every counted run as `[[start, end], ...]` in expected frames, in
  order. A fault counts when its runs of at least `min_run_frames` frames sum to `min_fraction`
  of the clip, so a fault held in several stretches is one fault with several runs; for a single
  run it is `[expected_frames]`.
- `coverage`: fraction of the counted frames where both measures were available (not masked).
- `confidence`: 0..1 margin-over-threshold heuristic times coverage. It is not a probability. On a low match
  (1.4.0) it is the string `"low"` instead; read a fault whose `confidence` is `"low"` as less certain.
- `text`: the plain-words line from #9, e.g. "left foot too far out". Lowercase fragment;
  capitalise at display time if wanted. It never changes.
- `follower_t_s`, `at_s`, `follower_runs`, `text_timed` (optional, 1.2.0): when it happened. `follower_t_s` is
  `[start_s, end_s]` on the follower file's own `t` at `follower_frames`; `at_s` is `follower_t_s[0]` rounded half up
  to 0.1 s (the moment to seek to); `follower_runs` maps every entry of `runs` to follower frames, same order;
  `text_timed` is the timed words plus ` at {at_s} s` ("right foot too far right at 1.9 s"). For a take compared
  one repetition at a time these are the first repetition's.
- `lateral` and `lateral_m` (optional, 1.2.0): `lateral` is `left`, `right` or `null` for the way a part is off,
  in the subject's own frame like `side` (mirror it only when you draw a mirrored view); `lateral_m` is, on a
  `foot_out` fault with side `left` or `right`, the median metres the ankle is further out than the example's.
- `coaching` (optional, 1.1.0): the phrasing backend's line; for the template it equals `text_timed` from 1.2.0.
- `cue` and `cue_kind` (1.5.0): what to do ("Bend your knees more"), at most 6 words; `range` or `position`.
- `reps` (1.3.0): see `diagnostics.guard.reps` above.
- `rep_sizes` (optional, 1.12.0, TICKET-071): on a fault of a take compared one repetition at a time, how big the fault
  was in each rep that found it: one `{rep, magnitude_deg, side, body_part}` for each entry of `reps`, in the same order.
  `rep` is the follower repetition (0-based, the index `reps` and `score.per_rep[].rep` use), `magnitude_deg` that rep's own
  size, signed like the fault's (`more` positive, `less` negative), `side` the side that rep found it on and `body_part`
  the fault's. The side can differ from the fault's own: a fault reported on `left` also counts a rep that found both
  sides (that entry has side `both` and the two sides' mean), and a fault reported on `both` counts a rep that found
  one side (a rep whose two sides did not merge gives its larger side). The fault's own `magnitude_deg` is the median of
  the entries on its side (every entry for a fault on `both`). Absent on a take compared as a whole. For comparing takes with
  each other; no fault, score or insight reads it.

## Score (`simon.score.v1`, `simon.score.v2` from 1.10.0 or `simon.score.v3` from 1.11.0: read `score.version`)

`score` is `{version, value, grade, components, params_sha256}` plus the groups below. It is never null from
`1.4.0` (a take nothing could be measured on scores 0, grade F); before that a refused take had `score: null`.
`value` is an integer 0 to 100 and `grade` is A (90 and above), B (80 to 89), C (70 to 79), D (60 to 69) or F;
`components.faults` and `components.similarity` are the points taken off for the faults and for the take's overall
difference from the example (under the dance profile also `components.tempo`, the points the pace cost, on the take and
on each window; the three add up to `100 - value` within rounding), `params_sha256` the hash of the `score` block of `part5/rules.json` (ADR-0007).
- `basis`, `timeline` (1.5.0, ADR-0013): the score is the mean of the compared windows. A take compared as a whole
  is cut into windows of about 5 s (`basis` `windows`); a take compared one repetition at a time has one window per
  rep (`basis` `reps`). Each `timeline[]` entry is `{t_s, compared, value, grade, components, misses, tempo}` (an
  uncompared rep is `{t_s, compared: false}`); `misses[]` holds `{text, measure, side, joint, t_s, at_s, points,
  cue, cue_kind, direction}`, every miss the window lost points to, so the number can be justified.
- `tempo` (1.5.0): `{ratio, cue}`, see "Coaching cues and insights" below. Tempo is not scored, except under the dance
  profile (ADR-0016): each compared window is charged `min(cap, weight * max(0, 0.85 - ratio, ratio - 1.15))` points
  (weight 40, cap 20), a run-time term outside the frozen `score` params, so `params_sha256` is the same in every profile.
  Under `rehab` the cue for a ratio above 1.15 reads "Slower is fine" instead of "Speed up to match the trainer".
- `per_rep` (1.3.0): each accepted repetition's `value` and `grade`. From 1.12.0 (TICKET-071) each entry also has `rep`,
  the follower repetition it is for (0-based; `timeline[rep]` is its window, and a rep that did not match is left out of
  `per_rep` while the others keep their own index), and `tempo_ratio`, that window's `tempo.ratio` (follower seconds per
  example second): a number, or null where the rep could not be timed and for every rep of a take whose `match.quality`
  is `low` (the timing was not measured, never on time; TICKET-063). The ratio is made in one place, `score.tempo_ratio`,
  so it cannot differ from the window's.
- `capped_by` (1.4.0): the warning codes that capped `value` at 59, present only with `warnings`.
- `uncapped` (1.9.0, Part 7 TICKET-155): `{value, grade}` before the cap, written only when the cap lowered `value`
  (a one-fault take that scored 73 C and shows 59 F because of `low_match` keeps `uncapped: {value: 73, grade: "C"}`), so a
  reader can say what the warning cost. Nothing reads it back: the score is the capped `value`. From 1.10.0 it is the
  value and grade **before every cap**, the fault cap (`fault_cap`) and the warning cap (`capped_by`): written when
  either lowered `value`, and when both did, the value before the first. A faulted take with no warning whose mean of
  windows was 94 A and was lowered to 89 B has `uncapped: {value: 94, grade: "A"}`, `fault_cap: 89` and no `capped_by`.
- `fault_cap` (1.10.0, ADR-0018, `simon.score.v2` and from 1.11.0 `simon.score.v3`): an integer, the highest `value` a take
  that reports a fault can score, the ceiling in force. Under v2 it is 89 (the top of B) for any reported fault; under v3
  (ADR-0019) it is 89 for a take that reports one fault and 79 (the top of C) for a take whose `faults` list holds two or
  more entries (read it; never assume 89). Present when the take's `faults` list is not empty, whether or not the cap lowered
  `value`; absent for a take with no faults and under `simon.score.v1`. It is not a warning: `capped_by` never names it and
  keeps its meaning exactly (the warning codes of the low-match cap at 59 F). The cap is applied once, to the mean of the
  windows (ADR-0013); `timeline[]` windows and `per_rep` keep their own values.

## Score v2 (`simon.score.v2`, from 1.10.0)

The formula is v1's (ADR-0007) with a weight on each miss and a ceiling (ADR-0018). A miss costs
`penalty(r) * (0.5 + 0.5 * dur) * coverage * w`, where `w = min(1, max(range_floor, u / range_full))` and `u` is how far
the trainer (the expected clip) moves the missed measure in that window, in that measure's detection thresholds
(`range_full` 3, `range_floor` 0.75). The foot measures take the same weight from the trainer's foot series; `w` is 1 only
where no trainer series exists (no feet file, a foot measure that was not compared). `score.value` compares only within
one `score.version`: a v2 value is not on the v1 scale. The
take's `value` is the mean of its windows and then at most `fault_cap` when it reports a fault. The penalty curve, the
similarity term, the bands and the warning cap are v1's, and the v1 block is kept in `part5/rules.json` as `score.v1` so
a v1 score can be reproduced. `params_sha256` is the hash of the whole `score` block, v1 block included.

## Score v3 (`simon.score.v3`, from 1.11.0)

v2's weight and ceiling with a second ceiling (ADR-0019). A miss costs what it costs under v2 (`range_floor` 0.75,
`range_full` 3). A take that reports one fault scores at most 89 (`fault_cap` 89); a take whose `faults` list holds two or
more entries scores at most 79 (`fault_cap` 79, the top of C). The ceiling is applied once, to the mean of the windows, and
`fault_cap` says which one was in force; `uncapped` is the value before every cap, and `capped_by` is still the warning
codes only. A take that reports two or more faults is therefore a C at best, one that reports a fault a B at best, and A
means no fault was reported. `score.value` compares only within one `score.version`. The `score` block of `part5/rules.json`
keeps the frozen v1 and v2 blocks as `score.v1` and `score.v2`, and `params_sha256` is the hash of the whole block.
`fixtures/output/analysis.double-capped.example.json` is a sample of a take that reports two faults and hits the 79 ceiling.

## Cues in the follower's language (`phrasing.cues`, `phrasing.native_review`, from 1.14.0)

Spec: `docs/specs/language-cues.md`. For a request in a listed language other than English (`--lang es`, `ar`, `hi` and the
rest of `part5/phrasing/lang.py`), Muse Spark already writes each fault line in it (`faults[].coaching`,
`phrasing.faults[].text`). The cues and reasons around those lines are English templates: `faults[].cue`, each
`score.timeline[].misses[].cue`, `score.timeline[].tempo.cue`, `score.tempo.cue`, `insights[].cue` and `insights[].why`.
They stay exactly as they are, so no reader breaks. In one more batched model call, after the insights are final, the
same backend writes them again in the language, and the result is the additive record:

- `phrasing.cues[]`: one entry per cue or reason of the document, in document order. `path` names the field
  (`faults[0].cue`, `score.timeline[2].misses[0].cue`, `score.timeline[2].tempo.cue`, `score.tempo.cue`, `insights[1].cue`,
  `insights[1].why`), `text` is what to show there, `lang` its language, `backend` and `model` who wrote it, and
  `fallback_reason` is null or why the English text is shown. An entry the model wrote has the requested `lang`, the backend
  `muse-spark` (or `local-llm`) and its model. An entry whose text failed its word test (a digit in a cue; a reason whose
  numbers differ from the English; a second or English time phrase; praise; over the length; more than a line; not in the
  language's script, or a copy of the English; missing from the answer), or whose backend could not run (the template, no
  key, live calls off), or whose call failed, keeps the field's English text with `lang` `en`, `backend` `template`,
  `model` null and the reason. The same English text on several paths is asked once and written to each. `[]` when the
  document has no cue or reason.
- `phrasing.native_review`: `false` for every listed language but English today. It says no native reader has checked
  the language, so a viewer shows "not reviewed by a native reader". It is `true` only for a language in
  `lang.NATIVE_REVIEWED` (empty).

An English request (no `lang`, `en`, or a tag Part 5 does not list) has neither key. Neither the score, the faults, the
insights nor any scored field reads them. Show `cues[].text` at its `path`, and the English field when there is no entry.

## Score credit (`score.credit`, `simon.credit.v1`, from 1.13.0)

A DDR-style display beside the score (ADR-0020), additive: `value`, `grade`, `components`, the ceilings and `capped_by` are
unchanged and never read it, and the 59 warning cap does not apply to it. In every compared window of `score.timeline`, each
measure finite in at least half of the window's frames is judged on every frame it is finite: with `z = |follower -
expected| / threshold_deg` of that measure (the profile's thresholds), `z / tolerance` at most 0.5 earns 1.0, at most 1
earns 0.6, at most 2 earns 0.2, beyond that 0 (`bands`). A frame lasts what it does on the example's own clock (the example's first to last time
over its frames less one, for a rep the rep's reference clip), so `points = credit * frame_s * 100 * multiplier` (100
points per measure per second, `points_per_measure_second`) and `max_points` the same with every credit 1. The same
routine has the same `max_points` however fast or slowly it was followed, within one comparison basis (the whole take, or rep by rep) and with the same measures seen. `percent` is `100 * points / max_points`, to 0.1, and `grade` is the percent's own letter on the
credit's own scale, `grades` (`[percent at least, letter]`, highest first): S 95, A 85, B 75, C 65, D 55, E 45, F 30;
under 30 is still F (the team's game scale, ADR-0020; the score's bands are not used here). It is informational: it is not `score.grade`, it sets no cap and no gate,
and it ignores warnings and caps, so a take capped to F can show a credit grade of B. Only the 22 body measures of `part5.measures.MEASURES` earn credit; the foot measures (`foot_rotation`, `ankle_inversion`, from the optional foot files) are compared and can be reported as faults, but earn none.

```json
"credit": {"version": "simon.credit.v1", "percent": 87.5, "grade": "A", "points": 5841, "max_points": 6673,
           "tolerance": "normal",
           "levels": {"easy": {"percent": 92.2, "points": 4615, "max_points": 5005},
                      "normal": {"percent": 87.5, "points": 5841, "max_points": 6673},
                      "hard": {"percent": 81.2, "points": 8131, "max_points": 10010}},
           "bands": [[0.5, 1.0], [1.0, 0.6], [2.0, 0.2]],
           "grades": [[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [45, "E"], [30, "F"]],
           "points_per_measure_second": 100,
           "per_window": [{"t_s": [0.1, 2.5], "percent": 87.5, "points": 5841, "max_points": 6673}]}
```

- `levels`: `easy` (tolerance 1.5, points x0.75), `normal` (1.0, x1.0), `hard` (0.7, x1.5); the top-level `percent`,
  `points` and `max_points` are those of the level `tolerance` names (`normal`).
- `grades`: the credit's letters, `[percent at least, letter]` from S down to F; `grade` is the first one `percent`
  reaches, and a percent under the last (30) is still F.
- `per_window`: one entry per compared window of `score.timeline`, the same `t_s`, in the same order, at that level. A
  window with no measure seen in half its frames has `percent` null and 0 points.
- `null`: nothing was compared (the take could not be aligned, or no window was compared), or no measure could be counted.
- Points grow with the take's length and the measures seen; compare `percent` across takes, within one profile.

## Body mask (`body_mask`, from 1.14.0)

Written only when the follower declared limb chains that are not scored (ADR-0023, `docs/specs/body-mask.md`):
`part5 analyse --mask seated` or `--mask left_arm,right_leg`, or the `mask` field of `POST api/analyse`. The chains are
`left_arm` and `right_arm` (from the shoulder: elbow and wrist masked), `left_forearm` and `right_forearm` (from the elbow:
the wrist) and `left_leg` and `right_leg` (from the hip: knee, ankle and a feet file's heel and toes); `seated` is both legs
and `full_body` masks nothing. Every measure that reads a masked joint is NaN on every frame of both clips for detection
and the score, after alignment, so no fault, miss, insight or near miss names it, and the score is taken on the remaining
measures: the faults term sums the remaining faults, the similarity term's `mean_z` is the mean over the remaining
measures' frames, and the credit counts only them. The four centre measures are never masked. Compare a masked score only
with takes under the same mask. A `both` fault whose one side is masked is reported on the other side, sized on it alone.
Designed for and tested on seated and masked takes from the fixtures, not with wheelchair users or amputees.

```json
"body_mask": {"declared": ["seated"], "source": "cli",
              "scored_chains": ["left_arm", "right_arm", "left_forearm", "right_forearm"],
              "not_scored_chains": ["left_leg", "right_leg"],
              "masked_joints": ["left_knee", "right_knee", "left_ankle", "right_ankle"],
              "not_scored_measures": ["left_knee_flexion", "left_thigh_out", "left_thigh_forward", "left_foot_out",
                                      "right_knee_flexion", "right_thigh_out", "right_thigh_forward", "right_foot_out",
                                      "left_knee_valgus", "right_knee_valgus", "left_foot_rotation",
                                      "right_foot_rotation", "left_ankle_inversion", "right_ankle_inversion"],
              "text": "Legs not scored, by your setting."}
```

## Replay: `replay.json` (`simon.replay.v1`, schema 1.1.0)

`part5 analyse ... --replay <replay.json>` also writes both normalised skeletons, matched frame for frame, for a 3D
replay (`contracts/replay.schema.json`; `python -m part5 doctor replay.json` checks it). Keys: `format`
(`simon.replay.v1`), `schema_version`, `fps` (the expected clip's), `joints` (the 17 names), `bones` (joint index
pairs to draw), `expected` and `follower` (per frame, 17 entries of `[x, y, z]` in metres to 4 decimals, or `null`
where a joint is missing; hip midpoint at the origin), `expected_t` and `follower_t` (seconds as written in each
input file, strictly increasing), `exp_to_fol` (the follower file's frame shown at each expected frame) and
`coordinate_frame` (`origin` `hip_midpoint`, `x` `subject_left`, `y` `world_up`, `z` `anterior`, `unit` `metres`).
`expected`, `expected_t` and `exp_to_fol` have one entry per expected frame; `follower` and `follower_t` one per
follower frame. A take compared one repetition at a time repeats the expected reference once per follower rep and
adds `reps: [{expected_frames, follower_frames, ok}]`. A take that could not be aligned plays on a straight-line
stand-in alignment.

From 1.1.0 (TICKET-085) every replay says where the alignment path ends. The alignment is open-ended
(`part5/align.py`): a follower who idles before the routine or goes on after it has those frames skipped, not
forced onto the first or last expected pose. `aligned_until_s` is `follower_t[max(exp_to_fol)]`, the follower time
where the path ends, and `aligned_until_expected_frame` is the last expected frame shown with that follower frame
(an index into `expected` and `expected_t`). The follower frames after `aligned_until_s` are the tail: never compared
and never scored. A reader that maps follower frames back to expected ones would pair every tail frame with
`aligned_until_expected_frame` and so repeat that frame's error; leave out the follower frames whose `follower_t` is
after `aligned_until_s` instead. Without a tail `aligned_until_s` equals `follower_t[-1]`. The fields are reported
only: the alignment, detection and the score are unchanged. A 1.0.0 replay has neither and still validates. The golden
`fixtures/output/replay.example.json` has no tail (its 76 follower frames end at 2.5 s):

```json
"aligned_until_s": 2.5, "aligned_until_expected_frame": 90
```

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
  `recall` and `refused` (takes analysed with a warning, which the metrics treat as the movement guard's old
  refusals: since ADR-0012 the take is analysed and graded F, but check-5 still scores it as having no
  predictions, so its labels count as misses). Such a take with no labelled faults is a
  wrong verdict on a correct take: it counts once in `faults_on_correct_takes`, so flagging
  correct takes can never satisfy the "0 faults on correct takes" rule. An empty denominator scores 1.0: nothing
  predicted (or labelled) in that slice is not itself a failure; misses appear in the other
  ratio. #14 gates on **every good-light angle slice separately** (`good/front`, `good/45`,
  `good/side` must each reach precision ≥ 0.85 and recall ≥ 0.75 with 0 faults on correct
  takes), so one weak angle cannot hide inside an aggregate; `good_light` is a summary only.
  Low-light slices are reported, not gated. A labelled take with no analysis is an error
  (the missing `take_id`s are listed), never scored as "no predictions".

`make check-5` (#14, `part5/check.py`) prints `simon.part5.check.v1` (`contracts/metrics.schema.json`, `1.2.0`): a
`gate` block (`set`, `seed`, `slices` (the gated slice names `good/front`, `good/45`, `good/side`), `thresholds`,
`failures` (one plain line per failed criterion), `passed`, `sweep` and the metrics above under `metrics`), the same
metrics for seed 5 under `tuning`, the recorded `attempts`, a `report` of what is reported and never gated (low
light, dropout, the real kit and stock takes, `refusals`, `score`; every block carries `gated: false`, and `refusals` is the map of slice to count with that one extra key) and the `rules_sha256` and `detection_sha256` of
the frozen rules, plus `profiles_sha256` (1.3.0, ADR-0016), the hash of `part5/profiles.json`, printed for information only
(the gate runs the `fitness` profile, which is the rules unchanged). It exits 0 only when `passed` is true; a take that can't be analysed, or a gated slice with no
takes, no labelled faults or no correct takes (nothing to measure a criterion on), also fails the check. Since
ADR-0007 the gate also needs every correct good-light take to score A and the monotonicity `sweep` never to rise;
`report.score` is the score distribution per slice of every set (`n`, `min`, `median`, `max`, `grades`) and the
verdict of each good-light target, as measured.

## Always analysed: `warnings`, `match`, `score.capped_by` (1.4.0, ADR-0012)

A take is always analysed. `status.code` is `ok` for every analysis; the former refusals are entries in the
top-level `warnings: [{code, text}]`:

| code | when |
|---|---|
| `low_match` | the movement guard would have refused: `residual` above `guard.max_residual` or `timing_corr` below `guard.min_timing_corr` (or the take could not be aligned at all) |
| `moving_part_out_of_frame` | the part the example moves is not in frame in the take |
| `not_enough_visible` | fewer than 3 measures are usable in both clips |
| `no_usable_measures` | no measure can carry timing, or most of the body could not be measured: no faults, score 0 |
| `no_person` | 1.9.0: Part 2 found no person in the take; written only by Part 7's own analysis (`source` `part7`), never by Part 5 |

`match` is `{quality: "ok"|"low", residual, timing_corr, limits}` (null numbers when unmeasured); `quality` is `low`
exactly when the guard would have refused. Both are written only with at least one warning, and then
`schema_version` is `1.4.0`; a document without warnings is byte-identical to what it was. Alignment and
detection use the usable measures (with fewer than 3, any visible one); on a low match every fault carries
`confidence: "low"`. `score` is never null; any warning caps `score.value` at 59 (grade F) and
`score.capped_by` lists the codes. `part5 analyse` exits 0 for every written analysis, 1 for an unreadable or
invalid input file, and no longer uses 3. A document written before 1.4.0 can still carry a refusal
(`status.code` other than `ok`, `faults: []`, `score: null`): show it as a refusal, never as "no faults".

## Quality: `quality` (`simon.quality.v1`, from 1.13.0, TICKET-079)

Every new document carries `quality`, one object that says how well the camera saw the follower's take. It is optional in
the schema: detect it by presence, and read a document without it as **not assessed** (every document before `1.13.0`). It ships
in `1.13.0` together with `score.credit`, so no schema version is added for it. It is **reported only**: `score.value`,
`score.grade`, `score.fault_cap`, `score.uncapped`, `score.capped_by` and `warnings` are what they are without it, byte for
byte, and it never adds a `warnings` entry. The cap it names is Part 7's to apply. `docs/specs/quality.md` and ADR-0021 give the
reasoning; the thresholds are in `part5/quality.json`, not in `part5/rules.json`.

| Key | Meaning |
|---|---|
| `version` | `simon.quality.v1` |
| `level` | `ok`, `degraded` or `major`: the worst reason, `ok` when there is none |
| `reasons` | `[{code, words, value, threshold}]`, empty for `ok`; a reason about one joint adds `joint` (a canonical joint name) |
| `signals` | the raw readings below; `null` for a reading that cannot be made, never 0 in its place (0.0 is a measured zero) |
| `score_cap` | 59 when `level` is `major` (the cap a warning puts on `score.value`, `part5.score.WARNING_CAP`), otherwise `null` |

`reasons[].code` is one of a closed list. The first three repeat a warning the take already carries, are always `major`, and have
`value` and `threshold` `null`; the others read a signal and carry its reading as `value` and the limit it reached as `threshold`
(the higher limit when both were reached):

| `code` | When | Signal | Unit |
|---|---|---|---|
| `not_enough_visible` | the take carries that warning | none | |
| `moving_part_out_of_frame` | the take carries that warning | none | |
| `no_usable_measures` | the take carries that warning | none | |
| `joints_unseen` | joint readings at Part 2's 0.3 unseen mark | `unseen_joint_share` | share, 0 to 1 |
| `joints_missing` | joint readings null or with `conf` under 0.3 | `missing_joint_share` | share, 0 to 1 |
| `frames_missing` | frames flagged `interpolated` or with at most half the joints usable | `missing_frame_share` | share, 0 to 1 |
| `measures_hidden` | full-body measures the follower's own `conf` hides under ADR-0011 | `hidden_measure_share` | share of the 22, 0 to 1 |
| `position_jitter` | frame-to-frame jitter of the joint positions | `position_jitter_mm` | millimetres per frame |
| `heading_offset` | from `1.14.0` (TICKET-086): the follower faced another way than the example, past 5 degrees; `degraded` only, never `major` (TICKET-086) | `heading_offset_deg` | degrees, 0 to 180 |

`low_match` is never a reason: a take of another movement is not a take the camera saw badly. `words` is one plain sentence made
from the measured numbers; it names no cause (light, a hand over the lens), because no part gives Part 5 a light reading.
`unseen_joint_share` and `hidden_measure_share` are `null` for a follower file that carries no `conf`. `unseen_joint_share` counts
only the joints the example itself sees in at least half of its frames (its own `conf` or `--expected-visibility`, read as ADR-0011
reads them), over the readings of those joints, and is `null` when the example sees none; an example with no `conf` anywhere (Part 4's
animations today) has unknown visibility and counts every joint, so a follower filmed from the waist up against such a trainer still
reads its legs as unseen. `position_jitter_mm` is
`feet.jitter` (the median absolute change between consecutive frames) of the step series of each joint and axis, the three axes
joined as a norm and the median taken over the joints, so it depends on the file's frame rate. `heading_offset_deg`
(from `1.14.0`, TICKET-086) is the one signal read after alignment, from both clips: in each aligned frame pair (example
frame `i` and follower frame `exp_to_fol[i]`, every aligned rep of a take compared rep by rep) the body's heading is the
direction of its hip and shoulder lines in the horizontal plane, and the signal is the median over the pairs of the angle
between the two headings. It is `null` when the take could not be aligned or no pair has a line to read, and a `1.13.0`
block has no such key. Part 3 turns each clip to face forward; this is what it leaves, which TICKET-082 found moves the
score (`docs/evaluation.md`).

```json
"quality": {"version": "simon.quality.v1", "level": "major",
            "reasons": [{"code": "joints_unseen", "words": "41 percent of the joint readings were outside the picture, most often the nose.", "value": 0.4118, "threshold": 0.2, "joint": "nose"},
                        {"code": "position_jitter", "words": "Joint positions shook by about 27 mm from one frame to the next, most at the left knee.", "value": 26.7, "threshold": 21.0, "joint": "left_knee"},
                        {"code": "heading_offset", "words": "The body was turned about 6 degrees from the way the example faces.", "value": 5.8, "threshold": 5.0}],
            "signals": {"unseen_joint_share": 0.4118, "missing_joint_share": 0.0, "missing_frame_share": 0.0,
                        "hidden_measure_share": 0.2273, "position_jitter_mm": 26.7, "heading_offset_deg": 5.8},
            "score_cap": 59}
```

This is `fixtures/output/analysis.quality-major.example.json`, made by the real pipeline from `fixtures/input/quality/exercise_front_dark_00`:
the low-light correct squat of seed 5 with the face and both wrists at Part 2's unseen mark (`scripts/make_quality_sample.py`). Its
`score.value` is 100 (A): the cap is reported and not applied, the take carries no warning, and the score is the one it had without
the block. The block is written after `match` (and after `warnings` when there are some) and before `diagnostics`.

## Part 7's own analysis: `source` and `no_person` (1.9.0, TICKET-048)

`source` is an optional top-level string: the part that produced the document (`part5` or `part7` today). Absent
means `part5`, and Part 5 never writes it, so every document `part5 analyse` writes is exactly what it was.

When Part 2 finds nobody in a take, Part 7 has nothing to compare and writes its own `analysis.json`: `status` `ok`,
`source` `part7`, a `warnings` entry with the code `no_person` ("Part 2 found no person in the take"; Part 5 never
writes it), `faults: []`, `expected` and `follower` with their real `path`, a `score` of 0 (grade F) and no `match`,
because nothing was compared. Its `schema_version` stays what Part 7 writes (`1.4.0` today). The schema validates it,
`part5.output.validate_analysis` accepts it (a `match` is required for Part 5's own warning codes and is not for
`no_person` alone) and `part5 doctor <file> --for part7` exits 0 with the warning and two notes: who wrote it, and
that `faults: []` means nothing was looked at. A committed example is
`fixtures/input/contract/part7/analysis.no-person.json`; `tests/test_part7_no_person.py` checks it.

## Coaching cues and insights (1.5.0, ADR-0014)

Every new document is `1.5.0`. Each fault carries `cue`, an imperative of at most 6 words from its `measure`,
`direction` and `side` ("Bend your knees more", "Raise your left arm higher"), and `cue_kind`: `range` when the
fix is how far a joint bends or a limb lifts, `position` when it is where a body part is placed. Each
`score.timeline[].misses[]` repeats its fault's `cue`, `cue_kind` and `direction`. Each compared window has
`tempo: {ratio, cue}`: follower seconds per example second over the window (a rep against the example rep);
below 0.85 the cue is "Slow down to match the trainer", above 1.15 "Speed up to match the trainer" (under the rehab
profile "Slower is fine", ADR-0016), else null; `ratio` is null when the example side spans under 1 s, and for every tempo of a document whose
`match.quality` is low (ADR-0014, Amendment 4). `score.tempo` is the same for the whole take (the
median of the reps). The top-level `insights` lists at most 5 `{cue, why, kind, at_s, window, points, measure,
side, joint}`: one per distinct cue among the misses, ranked by `points` (their summed points over the compared
windows divided by the number of those windows, so their share of the score), `at_s` and `window` at the first
miss; a tempo item (`points` null) is kept last when `score.tempo.cue` is set (not for a slow take under the rehab
profile, whose "Slower is fine" stays in `tempo.cue` and `score.tempo.cue` but is no item, ADR-0016 Amendment 2). Without a timeline, one item
per distinct fault cue in the order of `faults`, `points` null. Cues are template text; no phrasing backend
rewrites them. Foot rotation and ankle twist have no cue: the 17 joints end at the ankle.

An insight's `why` that points at a fault (a `faults[]` entry with the same `measure`, `side` and `direction`)
is that fault's `text_timed` in sentence case, time included: "Right foot too far right at 1.9 s", followed by
" (3 of 8 reps)" or " (2 times)" when the cue missed more than once. When that fault's `phrasing.faults[i]` has a
backend other than `template`, no `fallback_reason` and `lang` `en` (or none), the `why` repeats the line shown
instead: the fault's `coaching` before its first ";", any closing run of "." "!" and "?" dropped, which must pass the timed word
test again (otherwise the `text_timed` form stays), with the time number replaced by the insight's own `at_s` and
the first letter capitalised: "Your right foot drifts too far to the right at 1.7 s (3 of 8 reps)". A miss no fault
matches keeps the plain words ("Left knee not bent enough (3 of 8 reps)"); a tempo item says "You took 80% of the
trainer's time". The same document always gives the same insights.

Timed words (`text_timed` without its time) differ from `text` for lateral measures ("too far right", not "too
far out") and for an arm held low (`upper_arm_forward`, `less`: "left arm too low"). A thigh that is not lifted
(`thigh_forward`, `less`) says "right thigh not raised enough" in both, never "too low", which reads as squatting
too deep; its sizes read "not quite" and "nowhere near".
