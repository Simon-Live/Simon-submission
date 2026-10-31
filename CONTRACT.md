# Part 5 contract

What Part 5 reads and writes, which part sends what, and how to check a file before you stitch. Field rules are in `docs/schemas.md`; this page says who sends what and what each side must do.

## Check a file now

```bash
python -m part5 doctor skeleton.json                  # a clip Part 5 would read (expected or follower)
python -m part5 doctor analysis.json --for part7      # an analysis a viewer would read
python -m part5 doctor replay.json                    # the replay file (simon.replay.v1) a viewer would draw
python -m part5 contract                              # the schemas and the compatibility table below
python -m part5 contract --schema analysis            # one schema, exactly as stored
make check-5-contract                                 # schemas, fixtures and golden outputs agree
make test-contract                                    # every file below through part5.io.load_clip, and against its schema
make contracts-check                                  # exit 1 when a copy differs from Part 3 or Part 4 main
make contracts-sync                                   # refresh the copies and contracts/sources.lock.json
```

`doctor` names the file's kind and version, validates it and, when the consumer would reject it, says which field is wrong and which option fixes it:

```
$ python -m part5 doctor skeleton.native.json
skeleton.native.json: simon.skeleton/1 (Part 3 native); rejected for part5
  no "format" field: this is Part 3's native skeleton.json (simon.skeleton/1); fix: rerun Part 3 with --view part5
```

Exit codes of `doctor`: 0 accepted, 1 rejected, 2 unreadable (missing, not a file, not JSON). `--json` prints one object. `--for part7` checks an `analysis.json` (or a `replay.json`, which either option accepts) instead of a clip. `contract` and `doctor` run offline, and Part 5 never fetches a URL, a hand-off's included.

## Schemas

Each schema is JSON Schema draft 2020-12 with an `$id` and a top-level `version`. Any validator reads them; Python is not needed.

| Name | Version | File | Describes |
|---|---|---|---|
| `analysis` | `1.5.0` | `contracts/analysis.schema.json` | Part 5 analysis.json (simon.analysis.v1) |
| `input-animation` | `1.0.0` | `contracts/input-animation.schema.json` | Part 5 input clip (simon.animation.v1) |
| `input-skeleton` | `1.0.0` | `contracts/input-skeleton.schema.json` | Part 5 expected skeleton (simon.skeleton.v1) |
| `labels` | `1.0.0` | `contracts/labels.schema.json` | Part 5 labels.json (evaluation labels) |
| `metrics` | `1.1.0` | `contracts/metrics.schema.json` | Part 5 make check-5 document (simon.part5.check.v1) |
| `replay` | `1.0.0` | `contracts/replay.schema.json` | Part 5 replay.json (simon.replay.v1) |

The copies of Part 3's and Part 4's schemas stay under `contracts/part3/` and `contracts/part4/`, exactly as they were published. The analysis schema is `1.5.0`: it adds optional fields to `simon.analysis.v1`, so a `1.0` document still validates and `format` does not change. `1.3.0` adds `faults[].reps`, `diagnostics.guard.reps`, `diagnostics.expected_reference` and `score.per_rep`, written only for a take compared one repetition at a time (ADR-0010); `1.4.0` (ADR-0012) adds the top-level `warnings` and `match`, `score.capped_by` and a fault `confidence` of `"low"`, written only for a take that earned a warning; a document without warnings keeps its earlier `schema_version` (`1.2.0`, or `1.3.0` for a take compared by repetition). The replay (`simon.replay.v1`) of such a take adds an optional `reps` list. `1.5.0` (ADR-0014) adds coaching cues to every new document, which is therefore always `1.5.0`: `faults[].cue` and `cue_kind`, the same with `direction` on each `score.timeline[].misses[]`, `score.timeline[].tempo` and `score.tempo`, and the top-level `insights`. The earlier groups stay optional and are told apart by their fields. The `metrics` schema is `1.1.0`: it adds the score report that `make check-5` writes (`gate.sweep`, `report.score`, `detection_sha256`), and a `1.0.0` check document still validates. The `replay` schema is `1.0.0` and describes the second file `part5 analyse --replay` writes (below).

## Compatibility

Which producer file works with Part 5, as checked against the producer commit in the last column. `works` needs no option. `works with an option` needs the fix shown. `rejected` names what makes the file acceptable. The Part 3 and Part 4 commits come from `contracts/sources.lock.json`; the Part 2 and Part 6 commits are their `main` heads on the day Part 5 last ran its own check against them.

<!-- part5-compatibility:begin -->
| Producer | File | format | Part 5 role | Verdict | Fix | Checked against |
|---|---|---|---|---|---|---|
| Part 2 | `pose3d.json` | `part2.pose3d/2026-10-28` (Part 3 CONTRACT.md) | none | rejected | run Part 3 `--view part5` on it; `doctor` exits 1 with "run Part 3 --view part5" | Part 2 2e06d58 |
| Part 3 `run --view part5` | `skeleton.json` | `simon.animation.v1` | follower or expected | works |  | Part 3 fd96379 |
| Part 3 `run --view part4` | `skeleton.json` | `simon.skeleton.v1` | expected | works |  | Part 3 fd96379 |
| Part 3 native | `skeleton.json` | `simon.skeleton/1` (no `format`) | none | rejected | rerun Part 3 with `--view part5` | Part 3 fd96379 |
| Part 4 | `animation.json` | `simon.animation.v1` | expected | works |  | Part 4 dc3d9f2 |
| Part 6 Follow hand-off (event detail) | `{v: 1, id, name, category, link, manifest, files: {keyframes, skeleton, animation, video}}` | none | none | works with an option | download `files.animation` and pass it as `--expected`; Part 5 never fetches URLs | Part 6 fc3249a |
| Part 6 Follow hand-off (framed message, Part 6 CONTRACT.md "The hand-off to Part 7") | `{v: 1, id, name, category, link, manifest, files: {keyframes, skeleton, animation, video}}` with `type: "simon:follow"` | none | none | works with an option | download `files.animation` and pass it as `--expected`; Part 5 never fetches URLs | Part 6 fc3249a |
| Part 5 | `analysis.json` | `simon.analysis.v1` | output for Part 7 | works | Part 7 reads `warnings` and `score` (ADR-0012); each fault's `confidence` is a number or the literal `"low"`; the 1.2.0 to 1.5.0 fields (`at_s`, `text_timed`, `lateral`, `score`, `cue`, `insights`) are all optional | Part 5 (this repo) |
| Part 5 `analyse --replay <replay.json>` | `replay.json` | `simon.replay.v1` | output for Part 7 | works | optional second file; `expected_t` and `follower_t` carry the times in seconds; check it with `part5 doctor <replay.json>` | Part 5 (this repo) |
| Part 5 `analyse --live` | live mode (`--live`, `serve --live`, `SIMON5_LIVE=1`, `META_LIVE=1`) | `simon.analysis.v1` with `phrasing.selected_by` `live` | option for Part 7 | works with an option | needs the Baseten key file on the host that runs Part 5; without it each fault keeps its timed template line (`fallback_reason: "no key"`); the template stays the default for tests and `make check-5` | Part 5 (this repo) |
| Part 5 | `part5 analyse` exit code | 0 analysis written (with or without warnings), 1 unreadable or invalid input file or write error, 2 usage; 3 is no longer used (ADR-0012) | for Part 7 | works with a mapping | Part 7 at 90aa473 expects the family codes 0 written, 1 not writable, 2 input or option breaks the contract (Part 3 CONTRACT.md, row for Part 7): 0 is "written" (read `warnings`), 1 and 2 are failures; 3 is no longer produced | Part 7 90aa473 (as Part 3 CONTRACT.md records it) |
| Part 5 | `labels.json` | none | evaluation | works |  | Part 5 (this repo) |
<!-- part5-compatibility:end -->

## What Part 5 writes

`part5 analyse --expected <file> --follower <file> --out <analysis.json> [--replay <replay.json>] [--live]` writes `analysis.json` (`simon.analysis.v1`, schema `1.5.0`; documents written before ADR-0014 are `1.2.0`, `1.3.0` for a take compared one repetition at a time, or `1.4.0` when the take has a warning). A take is always analysed (ADR-0012): the exit code says what happened to the file:

| Exit | Meaning | `analysis.json` written |
|---|---|---|
| 0 | the analysis is written; `status.code` is always `ok`, and `warnings` (when present) say why the grade is capped at F | yes |
| 1 | an input or the output breaks the contract: an unreadable or malformed clip, a clip over the size bounds, an output that cannot be written | no |
| 2 | usage: a missing or unknown option | no |
| 3 | not used since ADR-0012 (it was a refused analysis) | no |

`analyse` never refuses a take. What was a refusal is a warning: `warnings: [{code, text}]` with `low_match` (the guard would have refused: `match.quality` is `low`), `moving_part_out_of_frame`, `not_enough_visible` or `no_usable_measures`. The analysis runs best effort on the measures the camera sees (with none, no faults and a score of 0), `score` is never null, and any warning caps `score.value` at 59 (grade F) and names the codes in `score.capped_by`. On a low match each fault carries `confidence: "low"` (a number in 0..1 otherwise). A correct, matching take has none of these fields and is unchanged.

### The replay file

`--replay <replay.json>` also writes `replay.json` (`simon.replay.v1`, schema `1.0.0`, `contracts/replay.schema.json`) after `analysis.json`: both normalised skeletons, matched frame for frame, for a 3D replay. Keys: `format`, `schema_version`, `fps`, `joints` (the 17 names), `bones` (index pairs to draw), `expected` and `follower` (per frame, 17 entries of `[x, y, z]` in metres to 4 decimals or `null`; hip midpoint at the origin, x the subject's left, y up, z forward), `expected_t` and `follower_t` (seconds as written in each input file, strictly increasing), `exp_to_fol` (the follower file's frame shown at each expected frame) and `coordinate_frame`. A take compared one repetition at a time adds `reps`. The timeline runs on the expected clip's frames: at expected frame `i` show follower frame `exp_to_fol[i]`. An unwritable replay path ends with exit 1 and `part5 analyse: cannot write <path> (<reason>)`; the analysis that was written stays. `python -m part5 doctor replay.json` checks the schema, that `expected`, `expected_t` and `exp_to_fol` have one entry per expected frame and `follower` and `follower_t` one per follower frame, that every `exp_to_fol` and bone index is in range and that both time lists strictly increase.

### Live mode

Live mode is on with `part5 analyse --live`, `part5 serve --live`, `SIMON5_LIVE=1` or `META_LIVE=1`. Muse Spark then writes each fault's `coaching` line (including its time) unless `--phrasing` names a backend, and `phrasing.selected_by` is `live`. It needs the Baseten key file on the host that runs Part 5; without it each fault keeps its timed template line with `fallback_reason: "no key"`. The line never changes `text`, `cue` or the score. Without live mode the phrasing is `template` (`selected_by` `default`), which is what the tests, `make check-5`, `make check-5-contract` and `make output-examples` always use, whatever the environment.

## Part 7's duties

1. **Read `warnings` and `score`.** From `1.4.0` `status.code` is always `ok`; show each `warnings[].text` beside the grade F. Only a document written before ADR-0012 can still carry a refusal: it has `status.code: "different_movement"` (or `"not_enough_visible"` or `"moving_part_out_of_frame"`: too little of the body, or the part the example moves, is in frame; show `status.text`, which says what to change; ADR-0011), a `status.text` that says why in plain words and `faults: []`. Show it as a refusal, never as "no faults". A file with no `status` block is a schema `1.0` file: read it as `ok`.
2. **Treat exit 0 as "written".** Part 7 at 90aa473 expects the family codes 0 written, 1 not writable, 2 input or option breaks the contract (Part 3 `CONTRACT.md`, row for Part 7). Map 0 to "written" and 1 and 2 to failures.
3. **Highlight `faults[].joints`.** It lists canonical joint names. A `1.0` file has no `joints`; then map the fault's `joint`: a sided joint is itself; side `both` is `left_X` and `right_X`; `spine` is both shoulders and both hips; `shoulders` is both shoulders; `neck` is the nose and both shoulders.
4. **Ignore fields you do not know.** New fields are added without changing `format`; `schema_version` says which additions to expect. `diagnostics` is for people debugging a take and is not shown to the follower.
5. **Show `coaching` when it is there, `text` when it is not.** `text` is a lowercase fragment ("left foot too far out"); capitalise it for display. From `1.2.0` the template phrasing makes `coaching` equal `text_timed` (the same words with the direction said as a side and plus the time, "left foot too far left at 1.9 s"; a thigh not lifted reads "right thigh not raised enough", an arm held low "left arm too low"), and `text` stays as it was.

6. **Show `insights` as what to work on.** From `1.5.0` each item is `{cue, why, kind, at_s, window, points}`: `cue` is an imperative of at most 6 words ("Bend your knees more"), `why` what was seen and where (when it points at a fault, that fault's own `text_timed` words in sentence case, "Right foot too far right at 1.9 s", so the row and the insight match), `kind` `position`, `range` or `tempo`, `at_s` the follower time to seek to, `points` what it cost the score (null for tempo and for a take without a timeline). Show each fault's and each miss's `cue` beside its text, and a window's `tempo.cue` when it is not null. A document without `insights` was written before `1.5.0`: show it as before.

7. **Show the time, the direction, the score and the replay.** `at_s` (and `follower_t_s`) is the moment on the follower file's own clock to seek to; `follower_runs` maps every run to follower frames. `lateral` (`left`, `right` or `null`) is the subject's own left and right, like `side`: mirror it only when you draw a mirrored view. `lateral_m` (metres, `foot_out` on one side) is how much further out the ankle is than the example's. `score` is `{version, value, grade, components, params_sha256}` plus `basis`, `timeline`, `tempo` and `capped_by` when present: show `value` out of 100 with `grade` A to F, the faults first, and each `timeline` window with its `misses`. A fault whose `confidence` is the string `"low"` came from a low match: show it as less certain. The replay (`replay.json`) is optional; `exp_to_fol` says which follower frame goes with each expected frame.

`python -m part5 doctor analysis.json --for part7` checks all of this on a file, warns when `status.code` is not `ok` or the take has `warnings`, and notes the score (and what capped it), the timed faults and the faults at confidence `"low"`.

## What Part 5 accepts

| Role | File | `format` | Producer | Schema in this repo | Loader result |
|---|---|---|---|---|---|
| expected clip | `animation.json` | `simon.animation.v1` | Part 4 | `contracts/part4/animation.schema.json` and `contracts/part3/animation-part5.schema.json` | accepted |
| expected clip | `skeleton.json`, `--view part4` | `simon.skeleton.v1` | Part 3 | `contracts/part3/skeleton-part4.schema.json` | accepted; top-level `fps` is 30 and each key carries `t` |
| follower clip | `skeleton.json`, `--view part5` | `simon.animation.v1` | Part 3 | `contracts/part3/animation-part5.schema.json` | accepted |
| none | `skeleton.json`, native view | none (`schema: simon.skeleton/1`) | Part 3 | `contracts/part3/skeleton.schema.json` | rejected: `format must be one of ...`. Part 3's fix: `python3 -m part3 run ... --view part5` |
| evaluation labels | `labels.json` | `simon.part3.follower_labels/1` | Part 3 | `contracts/part3/follower-labels.schema.json` | not read by `part5.io`; used by tests |

Common to every accepted file: the 17 joints in canonical order, positions in metres as `[x, y, z]`, hip midpoint at the origin per frame, x the subject's left, y world up, z anterior, `t` in seconds and strictly increasing.

Part 5's own schemas for these inputs are `input-animation` and `input-skeleton`. They also allow a joint set to `null` and a per frame `conf`, which an estimator that lost a joint writes and the Part 3 and Part 4 schemas do not describe.

## Where the copies come from

`contracts/sources.json` lists every copy and `contracts/sources.lock.json` records the upstream commit and sha256 of each. At the time of writing:

| Copy | Source |
|---|---|
| `contracts/part3/*.schema.json` | `moalborati/simon-part-3-skeleton-consistency` `contracts/`, verbatim, commit `fd96379` (synced 2026-10-31; only `skeleton-part4.schema.json` changed since `65a5aad`: an optional `densify` block) |
| `fixtures/input/contract/part3/followers/` | Part 3 `fixtures/conformance/followers/<take>/skeleton.json` and `labels.json`, verbatim, `fd96379` |
| `fixtures/input/contract/part3/view-part4/skeleton.json` | Part 3 `fixtures/conformance/golden/view-part4-every-10/skeleton.json`, `fd96379` |
| `fixtures/input/contract/part3/native/skeleton.json` | Part 3 `fixtures/conformance/followers/squat_front_correct/skeleton.native.json`, `fd96379` |
| `fixtures/input/contract/part4/exercise/animation.json` | `moalborati/simon-part-4-animate-keyframes` `fixtures/output/exercise/animation.json`, verbatim, commit `dc3d9f2`. The clip now carries `"producer": "part4"` |
| `contracts/part4/animation.schema.json` | `moalborati/simon-part-4-animate-keyframes` `contracts/animation.schema.json` (`simon.animation.v1`), verbatim, commit `dc3d9f2`. Part 4 also publishes `keyframes.schema.json` and `skeleton.schema.json`; this part does not read them. |
| `fixtures/input/expected/<set>/animation.json` | Part 4 `fixtures/output/<set>/animation.json`, pinned at `dc3d9f2` (see `fixtures/input/expected/SOURCE.md`) |

Never edit a copy by hand. Change it upstream, then run `make contracts-sync`. `make contracts-check` reads local checkouts from `PART3_DIR` and `PART4_DIR` when set, otherwise it clones both repos from GitHub. It reads files only and imports no upstream code.


## Pinned copies

`fixtures/input/expected/` holds Part 4's output at `dc3d9f2` (Part 4 main when the copies were refreshed, together with the follower takes and their labels). `make dummy-data` builds every follower take from these clips, so they change only with the takes and the labels, never after a held-out seed is scored. They are the `pinned` entries of `contracts/sources.json`: `make contracts-check` reports a note, never a failure, if Part 4's files change after the pin.

## Fault labels

Part 3's kit names its faults differently from Part 5's labels. Mapping from Part 3's `CONTRACT.md` ("Conformance kit and Part 5 fault names"):

| Part 3 kit `type` | Closest Part 5 `type` | Part 3 measure | Part 5 measure |
|---|---|---|---|
| `feet_wide` | `foot_out` | `ankle_lateral_offset`, metres, one label for both feet | `thigh_direction`, degrees, one label per side |
| `elbows_out` | `arms_wider` | `upper_arm_abduction`, degrees, both shoulders | `upper_arm_direction`, degrees, per side or `both` |
| `shallow_squat` | `knees_shallow` | `knee_angle_at_bottom`, interior angle, grows as the knee straightens | `knee_flexion`, bend (180 minus interior), shrinks |
| `knee_caving` | `knee_caving` | `thigh_inward_turn_at_bottom`, degrees, one knee | `knee_valgus`, degrees, the knee's offset inside the hip to ankle line, one label per side |
| `correct` | a take with `correct: true` and no faults | none | none |

Only `elbows_out` and `arms_wider` measure the same thing. A size in metres for `feet_wide` is not a size for `foot_out`. Part 3's `knee_caving` maps to Part 5's `knee_valgus` measure (a knee caving in), but the two sizes are different angles: the kit's is a thigh turn at the bottom of the squat, Part 5's is the knee's offset from the hip to ankle line. Part 3's kit has no `elbow_bent` or `trunk_lean`.

## Neighbours (status 2026-10-28)

Parts 1, 3, 4 and 6 are done. This part follows the contracts they already set. The contracts below are the ones this part touches.

| Part | Status | What Part 5 follows |
|---|---|---|
| 3 Skeleton consistency | done | Follower clips come from `python3 -m part3 run ... --view part5`: `simon.animation.v1` with a required `fps`, the 17 joints in order, metres, the hip-centred frame. Part 3 writes the source clock (15 fps for its kit takes). Run it with `--fps 30` to put a follower on Part 4's 30 fps clock before aligning (issue #35). The fault-label mapping is in Part 3's `CONTRACT.md` and in this PR. |
| 4 Animate | done | The expected clip is Part 4's `animation.json` (`simon.animation.v1`, 30 fps, `interpolated` on filled frames, and a required `"producer": "part4"` constant) at main `dc3d9f2`, which publishes its own schemas under `contracts/`. The copies in `fixtures/input/expected/` are Part 4 `dc3d9f2` (see "Pinned copies"). |
| 1 Key frames | done | Key frames sit on the original video clock (`frame`, `t_ms`). Part 4 has already used them to build the expected clip. If Part 5 aligns by key frame, match on `t_ms`. |
| 6 Catalog | done | A catalog entry holds the expected movement's files (`manifest.json` v1, see Part 6's `CONTRACT.md`). Part 6 does not read `analysis.json`; Part 7 shows it. |

Part 5's output, `analysis.json` (`simon.analysis.v1`), goes to Part 7. What Part 7 must do with it is in "Part 7's duties" above.
