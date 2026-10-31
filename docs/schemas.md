# Part 5 file contracts

This page is the field reference. The same contract is published as JSON Schemas in `contracts/`
(`analysis`, `input-animation`, `input-skeleton`, `labels`, `metrics`, `replay`, each with a `version`).
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

## Labels for evaluation: `fixtures/input/followers/labels.json`

See `fixtures/input/followers/README.md`.

## Output: `analysis.json` (`simon.analysis.v1`, schema 1.5.0)

Written by `part5 analyse` (#10) and shown to the follower by Part 7. Build and validate it
through `part5.output` (`build_analysis`, `write_analysis`, `load_analysis`); validation raises
`OutputError` with the file and field that broke the contract. Unknown extra fields are allowed,
so the format can grow without breaking older readers. Live examples, generated from dummy
takes by `make output-examples` through the same pipeline and score hook `part5 analyse` uses (with the
`template` phrasing, whatever the environment): `fixtures/output/analysis.example.json` (two faults),
`fixtures/output/analysis.no-faults.example.json` (a correct take) and `fixtures/output/replay.example.json`
(the replay of the first). The machine-readable form is `contracts/analysis.schema.json` (version 1.5.0):
it adds optional fields to this shape, so a 1.0 document validates against it, and `CONTRACT.md` names what
Part 7 must read first.

Every addition is optional and told apart by its fields; `schema_version` says which to expect:

| `schema_version` | Adds | Written when |
|---|---|---|
| none (1.0) | the fields in the example below that are not listed in a later row | a producer from before `1.1.0` |
| `1.1.0` | `schema_version`, `status`, `phrasing`, `faults[].joints`, `runs`, `coaching`, `diagnostics.guard` | |
| `1.2.0` | `faults[].follower_t_s`, `at_s`, `follower_runs`, `text_timed`, `lateral`, `lateral_m`; `score` (`simon.score.v1`) | a take with no later group |
| `1.3.0` | `faults[].reps`, `score.per_rep`, `diagnostics.guard.reps`, `diagnostics.expected_reference`, `diagnostics.visibility` | a take compared one repetition at a time (ADR-0010) |
| `1.4.0` | `warnings`, `match`, `score.capped_by`, a fault `confidence` of `"low"` (ADR-0012) | the take earned a warning |
| `1.5.0` | `faults[].cue`, `cue_kind`; `score.basis`, `timeline`, `tempo`; `insights` (ADR-0013, ADR-0014) | every new document |

```json
{
  "format": "simon.analysis.v1",
  "schema_version": "1.5.0",
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
                            "limits": {"max_residual": 0.5677, "min_timing_corr": 0.8336}}},
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
- `expected` / `follower`: objects identifying the input clips. `path` (non-empty string) is
  required; other ids (`set`, `movement`, `take_id`, …) pass through untouched.
- `status` (optional, 1.1.0): `{code, text}`. From `1.4.0` `code` is always `ok`: a take is always analysed
  (ADR-0012) and what used to be a refusal is a `warnings` entry. Only a document written before 1.4.0 can carry
  `different_movement`, `not_enough_visible` or `moving_part_out_of_frame` (then `faults: []` and `score: null`);
  read `status` before `faults`, and a file with no `status` is a 1.0 file: read it as `ok`.
- `faults`: sorted by \(|magnitude|\) descending. An empty list means no faults were found:
  a correct take still gets a file.
- `warnings` and `match` (1.4.0): present only when the take earned a warning, see "Always analysed" below.
- `score` (1.2.0, never null from 1.4.0): `simon.score.v1`, see "Score" below.
- `insights` (1.5.0): what to work on, see "Coaching cues and insights" below.
- `phrasing` (optional, 1.1.0): who phrased `faults[].coaching`: `requested` and `backend` (`template`,
  `local-llm` or `muse-spark`), `model`, `fallback_reason`, `selected_by` (`flag` for an explicit backend, `live`
  for the live default, `default` for the template) and, per fault, `faults[k] = {backend, model, fallback_reason}`
  (`model` is null for the template). Phrasing changes `coaching` only: never `text`, `cue`, a scored field or the score.
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
  `diagnostics.guard.reps` (1.3.0, only for a take compared one repetition at a time, ADR-0010) lists each follower
  repetition: `span_s` (start and end on the follower file's clock), `residual`, `timing_corr` (null when the rep could
  not be aligned) and `ok`; `residual` and `timing_corr` above are then medians over the reps.
  `diagnostics.expected_reference` (1.3.0) says which part of the expected clip the reps were compared with:
  `kind` `first_rep` or `whole`, its `frames` and `span_s`, `expected_reps`, `follower_reps` and the cut `measure`.
  A fault of such a take has `reps` (1.3.0): the 0-based follower repetitions it was found in, and its time fields are
  those of the first; `score.per_rep` lists each accepted repetition's `value` and `grade`.

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
  counted run in each clip. `phase` is the same range as a 0..1 fraction of the expected movement.
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

## Score (`simon.score.v1`, 1.2.0 to 1.5.0)

`score` is `{version, value, grade, components, params_sha256}` plus the groups below. It is never null from
`1.4.0` (a take nothing could be measured on scores 0, grade F); before that a refused take had `score: null`.
`value` is an integer 0 to 100 and `grade` is A (90 and above), B (80 to 89), C (70 to 79), D (60 to 69) or F;
`components.faults` and `components.similarity` are the points taken off for the faults and for the take's overall
difference from the example, `params_sha256` the hash of the `score` block of `part5/rules.json` (ADR-0007).
- `basis`, `timeline` (1.5.0, ADR-0013): the score is the mean of the compared windows. A take compared as a whole
  is cut into windows of about 5 s (`basis` `windows`); a take compared one repetition at a time has one window per
  rep (`basis` `reps`). Each `timeline[]` entry is `{t_s, compared, value, grade, components, misses, tempo}` (an
  uncompared rep is `{t_s, compared: false}`); `misses[]` holds `{text, measure, side, joint, t_s, at_s, points,
  cue, cue_kind, direction}`, every miss the window lost points to, so the number can be justified.
- `tempo` (1.5.0): `{ratio, cue}`, see "Coaching cues and insights" below. Tempo is not scored.
- `per_rep` (1.3.0): each accepted repetition's `value` and `grade`.
- `capped_by` (1.4.0): the warning codes that capped `value` at 59, present only with `warnings`.

## Replay: `replay.json` (`simon.replay.v1`, schema 1.0.0)

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
the frozen rules. It exits 0 only when `passed` is true; a take that can't be analysed, or a gated slice with no
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

`match` is `{quality: "ok"|"low", residual, timing_corr, limits}` (null numbers when unmeasured); `quality` is `low`
exactly when the guard would have refused. Both are written only with at least one warning, and then
`schema_version` is `1.4.0`; a document without warnings is byte-identical to what it was. Alignment and
detection use the usable measures (with fewer than 3, any visible one); on a low match every fault carries
`confidence: "low"`. `score` is never null; any warning caps `score.value` at 59 (grade F) and
`score.capped_by` lists the codes. `part5 analyse` exits 0 for every written analysis, 1 for an unreadable or
invalid input file, and no longer uses 3. A document written before 1.4.0 can still carry a refusal
(`status.code` other than `ok`, `faults: []`, `score: null`): show it as a refusal, never as "no faults".

## Coaching cues and insights (1.5.0, ADR-0014)

Every new document is `1.5.0`. Each fault carries `cue`, an imperative of at most 6 words from its `measure`,
`direction` and `side` ("Bend your knees more", "Raise your left arm higher"), and `cue_kind`: `range` when the
fix is how far a joint bends or a limb lifts, `position` when it is where a body part is placed. Each
`score.timeline[].misses[]` repeats its fault's `cue`, `cue_kind` and `direction`. Each compared window has
`tempo: {ratio, cue}`: follower seconds per example second over the window (a rep against the example rep);
below 0.85 the cue is "Slow down to match the trainer", above 1.15 "Speed up to match the trainer", else
null; `ratio` is null when the example side spans under 1 s. `score.tempo` is the same for the whole take (the
median of the reps). The top-level `insights` lists at most 5 `{cue, why, kind, at_s, window, points, measure,
side, joint}`: one per distinct cue among the misses, ranked by `points` (their summed points over the compared
windows divided by the number of those windows, so their share of the score), `at_s` and `window` at the first
miss; a tempo item (`points` null) is kept last when `score.tempo.cue` is set. Without a timeline, one item
per distinct fault cue in the order of `faults`, `points` null. Cues are template text; no phrasing backend
rewrites them. Foot rotation and ankle twist have no cue: the 17 joints end at the ankle.

An insight's `why` that points at a fault (a `faults[]` entry with the same `measure`, `side` and `direction`)
is that fault's `text_timed` in sentence case, time included: "Right foot too far right at 1.9 s", followed by
" (3 of 8 reps)" or " (2 times)" when the cue missed more than once. A miss no fault matches keeps the plain
words ("Left knee not bent enough (3 of 8 reps)"); a tempo item says "You took 80% of the trainer's time".

Timed words (`text_timed` without its time) differ from `text` for lateral measures ("too far right", not "too
far out") and for an arm held low (`upper_arm_forward`, `less`: "left arm too low"). A thigh that is not lifted
(`thigh_forward`, `less`) says "right thigh not raised enough" in both, never "too low", which reads as squatting
too deep; its sizes read "not quite" and "nowhere near".
