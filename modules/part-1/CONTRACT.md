# keyframes.json contract

`make keyframes` writes `out/<name>/keyframes.json`. `make label` writes `fixtures/labels/<name>.json` in the same format. The schema is [`contracts/keyframes.schema.json`](contracts/keyframes.schema.json) (JSON Schema draft 2020-12). A full example is [`contracts/keyframes.example.json`](contracts/keyframes.example.json).

```json
{
  "format": "simon.keyframes/part1",
  "video": "inbox/example.mp4",
  "fps": 60.0,
  "analysis_fps": 8.0,
  "spark_names": "spark",
  "quality": {"verdict": "fine", "analysis_width": 640, "filters": []},
  "people": [
    {"id": 0, "repetitions": [
      {"rep": 1, "movement": "squat", "keyframes": [
        {"name": "start", "frame": 120, "t_ms": 2000},
        {"name": "bottom", "frame": 150, "t_ms": 2500},
        {"name": "top", "frame": 180, "t_ms": 3000}
      ]}
    ]}
  ]
}
```

Check a file from Python:

```python
from keyframe_finder.schema import validate
errors = validate(document)  # [] when it meets the contract
```

## The clock

There is one clock: the original video in `inbox/`.

- `t_ms` is milliseconds from the start of the original video. **Consumers join on `t_ms`.**
- `frame` is the same moment as a frame index of the original video: `frame = round(t_ms / 1000 * fps)`.
- `analysis_fps` is the rate of the copy the models watched (15 for a clip of 20 s or less, else 8). Every `t_ms` lands on a step of that clock, so its resolution is 1000 / `analysis_fps` ms (67 ms or 125 ms).

Join on `t_ms`, not on `frame`. Another part that samples the same video at a different rate numbers its frames differently, and `t_ms` is the same in both.

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `format` | string | yes | Always `simon.keyframes/part1`. A change that breaks a reader gets a new id. |
| `video` | string | yes | The original video, relative to this repo, `inbox/<name>.mp4`. |
| `fps` | number > 0 | yes | Frame rate of the original video. `frame` counts at this rate. |
| `analysis_fps` | number > 0 | `make keyframes` | Rate of the analysis copy. Sets the resolution of `t_ms`. |
| `spark_names` | `spark` or `fallback` | `make keyframes` | `fallback` means the poses are named `start`, `bottom`, `top`. |
| `quality` | object | `make keyframes` | The local quality report. `verdict` is `fine` or `enhanced`; a refused video writes no file. |
| `people[]` | array | yes | Each person kept. Empty when nobody moved enough to count. |
| `people[].id` | integer ≥ 0 | yes | The SAM object id from this part's own tracking run. |
| `people[].repetitions[]` | array | yes | That person's repetitions. |
| `repetitions[].rep` | integer ≥ 1 | yes | Numbered from 1 for each person. |
| `repetitions[].movement` | string | yes | Section name in snake_case from Spark, or `movement`. |
| `repetitions[].keyframes[]` | array | yes | The poses of this repetition, in time order. |
| `keyframes[].name` | string | yes | Pose name in snake_case. |
| `keyframes[].frame` | integer ≥ 0 | yes | Frame of the original video. |
| `keyframes[].t_ms` | integer ≥ 0 | yes | Milliseconds from the start of the original video. |
| `keyframes[].reviewed` | boolean | no | Hand labels only: a person moved or added this pose. |

Readers ignore keys they do not know. Hand labels omit `spark_names` and `quality`.

## People and repetitions

- Repetitions are found on the whole clip for each person, then named after the Spark section they fall in. People in the same frame can be on different poses, so two people's repetitions do not line up.
- A person's `id` belongs to Part 1's own SAM run. It is not Part 2's person id. A consumer that needs one person names it (Part 3 `--keyframes-person <id>`); nothing matches ids across parts.

## Who reads it

| Part | Reads | How |
|---|---|---|
| Part 3 | `people[].repetitions[].keyframes[]` `name`, `t_ms` | `python3 -m part3 run ... --view part4 --keyframes keyframes.json [--keyframes-person <id>]` maps one person's keys onto its 30 fps index by time. `--keyframes-out` writes the `simon.keyframes.v1` file Part 4 reads. |
| Part 4 | nothing from Part 1 directly | Reads the `simon.keyframes.v1` file Part 3 writes beside `skeleton.json`; its key indices must match the skeleton's. |
| Part 6 | `format`, `fps`, one person's `name`, `t_ms` | Scrub marks at `t_ms / 1000` s (or `frame / fps` when `t_ms` is missing), for the person with id 0, else the first. |
| Part 2, Part 5 | nothing from Part 1 | Part 2's `pose3d.json` frames carry `t_ms` on the same video clock; a join with Part 1 uses `t_ms`. |

Checked on 2026-10-28 against Part 3 6d339d5 (`run` gives the same `--keyframes-out` file with or without `format`) and Part 6 d1816ed (reads the file by its version id).

Part 3 6d339d5 `doctor` does not know the id yet and reports a versioned file as an unknown kind (exit 2). Its `run` is unaffected. The fix belongs in Part 3: map `simon.keyframes/part1` to its `keyframes-part1` kind.

## Assumptions

| ID | Assumption | Switch |
|---|---|---|
| A-P1-01 | The version field is `format: "simon.keyframes/part1"`, the id Part 6 already reads for Part 1 files. | A breaking change takes a new id, and readers add it. |
| A-P1-02 | Part 1 does not write Part 4's `simon.keyframes.v1`. Part 4 needs key indices identical to the ones in `skeleton.json`, and only Part 3 knows that clip, so `--keyframes-out` stays the one writer. | If a consumer needs Part 4's file without Part 3, add `--export-part4 <person>` here. |
| A-P1-03 | Person ids are not matched across parts; the consumer names the person. | If Part 2's `tracks.json` becomes an input, map ids by box overlap at the same `t_ms`. |
| A-P1-04 | Hand labels use the same format and are checked against the schema when saved. | None needed. |

## Older files

A `keyframes.json` written before the `format` field has the same fields without it. `make keyframes` rebuilds it from the saved SAM and Spark results in `out/<name>/`, calls no API, and adds the field.
