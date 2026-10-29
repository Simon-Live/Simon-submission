# Part 2 downstream contract

What Part 2 writes and what each file promises to the parts that read it. Part 3 reads `pose3d.json`
unchanged. Every file Part 2 writes has a JSON Schema in `contracts/`, and two commands check a file
for you.

## Check a file

```
python -m part2 doctor out/clip/pose3d.json                 # kind, version, and a verdict for Part 3, Part 5 and Part 6
python -m part2 doctor out/clip/pose3d.json --for part3     # one consumer; Part 3 is the default for the exit code
python -m part2 contract                                    # the schemas and the compatibility table
python -m part2 contract --json                             # the same, for a program
python -m part2 contract --schema pose3d                    # one schema file, verbatim
make check-2-contract                                       # every committed output against every schema and consumer rule
```

`doctor` prints one line per consumer. This is the committed class fixture:

```
fixtures/output/class/pose3d.json: kind pose3d, version part2.pose3d/2026-10-28 (by shape), 7 people, 89 frames
Part 3: accepts with option: several people; fix: python3 -m part3 run ... --person <id> or --all-people
Part 5: would reject: Part 5 reads skeleton.json; fix: run Part 3 first (--view part5)
Part 6: accepts (generic reader: 17 joints, finite numbers, person id 0 played)
```

Exit code: 0 when the named consumer (Part 3 without `--for`) accepts, with or without an option; 1 when
it would reject; 2 when the file is not JSON or is not a Part 2 file. `--json` prints the same
findings as JSON. The Part 6 line applies Part 6's generic reader rules only: Part 6 has no Part 2 kind.

Maintaining the Part 3 copy:

```
make contract-check     # compare the copy with Part 3's main (needs a gh login with access to Part 3)
make contract-sync      # refresh the copy; exit 1 if it changed
make test               # includes tests/test_contract.py, tests/test_doctor.py and tests/test_provenance.py
```

## Files and versions

| File | Kind | Version | Schema |
|---|---|---|---|
| `pose3d.json`, `pose3d_person_<id>.json` | `pose3d` | `part2.pose3d/2026-10-28` | `contracts/pose3d.schema.json` |
| `tracks.json` | `tracks` | `part2.tracks/2026-10-28` | `contracts/tracks.schema.json` |
| `camera.json` | `camera` | `part2.camera/2026-10-28` | `contracts/camera.schema.json` |
| `frames/frames.json` | `frames` | `part2.frames/2026-10-28` | `contracts/frames.schema.json` |

The schemas are draft 2020-12. The version is the `x-simon-version` key of each schema.
`contracts/compatibility.json` holds the table below. `contracts/consumers/part3-pose3d.schema.json` is
Part 3's own consumer schema, copied byte for byte, with `part3-pose3d.schema.source.json` next to it
naming the repo, path, commit and sha256 it came from. It used to be `contracts/pose3d.schema.json`;
that path now holds Part 2's own schema.

Version policy: a new optional field keeps the version. A removed or renamed field bumps the date.
No file carries a required version field, because Part 3 reads the files unchanged. The optional
`provenance.contract_version` writes the version into the file. Extra keys are allowed in every file and
readers ignore them.

## Rules that hold for every file

### Time: `t_ms` and `t0_pts_ms`

- `t_ms` is milliseconds from the first decoded frame of the input: `t_ms = (pts[k] - pts[0]) * 1000`.
  For a file whose first presentation time is 0 this is also milliseconds from the start of the file.
  With `--fps`, each kept frame is the source frame nearest its step and keeps its own time.
- `t0_pts_ms` is an optional top-level number: the first decoded frame's presentation time in
  milliseconds. `part2 frames` writes it into `frames.json` for a video, and `part2 run` copies it into
  `pose3d.json` and `tracks.json`. An image directory has none unless its own `frames.json` carries one.
  File time is `t_ms + t0_pts_ms`.
- To join with Part 1, join on `t_ms`, never on frame numbers. When both sides count from the first
  decoded frame, the times already agree. When `t0_pts_ms` is present and not 0, add it to `t_ms` to get
  the time on the file clock. `doctor` prints a warning in that case and its exit code does not change.

### `mirrored`

`part2 run --mirrored` writes top-level `"mirrored": true`. Use it when the saved video is a mirror image
of the scene: a front camera or selfie mode that saves the preview as shown, or a clip flipped in
editing. Without the option the key is absent, and absent means not mirrored. Part 2 never writes
`false`. Part 3 with `--flip auto` (its default) mirrors left and right only when it reads `true`. No pose
reveals a mirrored video, so the flag must come from whoever knows how the clip was recorded. A
non-boolean value is rejected by Part 3 and by `contract.validate`.

### NaN and infinity

No file holds NaN, infinity or a number too large for a double. `schema.validate_pose3d`,
`schema.validate_tracks`, `contract.validate` and the Part 3 check all reject them and name the path.
Writers refuse before the file is touched and write with `allow_nan=False`. Part 6 reads JSON strictly,
so it refuses NaN, Infinity and numbers such as `1e400` even in a field it ignores.

### `provenance`

An optional object in `pose3d.json` and `tracks.json` that says what produced the file. Readers ignore it,
and a file without it is valid.

| Key | Meaning |
|---|---|
| `contract_version` | The `x-simon-version` of this file's schema. |
| `backend` | The 3D backend that ran, for example `gpu`. |
| `tracker` | The tracker that ran, for example `api-sam31`; `null` in one-person mode, where none runs. |
| `lifter` | The 2D to 3D lifter of the cpu backend; `null` otherwise. |
| `refine` | The refinement rungs applied, in order. |
| `models` | `[{name, source, weights_sha256}]`. `weights_sha256` is `null` for a hosted model or a file that was not hashed. |
| `part2_commit` | The git commit of Part 2 that wrote the file, with `+dirty` when tracked files differed; `unknown` without git. |
| `created_utc` | `YYYY-MM-DDTHH:MM:SSZ`. |
| `licence_notes` | A list of notes that apply to the models used. |

`part2 run` writes the backend `gpu` (SAM 3D Body through `part2/body3d.py`) and, in multi mode, the
tracker `api-sam31` (SAM 3.1 through the Meta Model API and `part2/track.py`). Other keys may appear and
are ignored.

## `pose3d.json`

```json
{"frames": [{"frame": 0, "t_ms": 0.0, "people": [
  {"id": 0, "joints": {"nose": {"x": -0.0367, "y": 0.6067, "z": 0.3695, "conf": 1.0}, "...": "the other 16"}}]}],
 "mirrored": true, "t0_pts_ms": 0.0, "provenance": {"backend": "gpu", "...": "see above"}}
```

| Field | Promise |
|---|---|
| `frames` | Required list. `frame` strictly increases. A frame where nobody was found has `people: []`. |
| `frames[].frame` | Required whole number: the index from `frames.json` written by `part2 frames`. |
| `frames[].t_ms` | Required finite number, milliseconds from the first decoded frame (see Time). Part 2 always writes it, so Part 3 never needs `--input-fps`. |
| `frames[].people[].id` | Required integer or string, unique within a frame. In multi-person mode it is the `tracks.json` track id. |
| `frames[].people[].joints` | Required object with exactly the 17 canonical joints, written in this order: `nose`, `left_eye`, `right_eye`, `left_ear`, `right_ear`, `left_shoulder`, `right_shoulder`, `left_elbow`, `right_elbow`, `left_wrist`, `right_wrist`, `left_hip`, `right_hip`, `left_knee`, `right_knee`, `left_ankle`, `right_ankle`. Left and right are the subject's. |
| `joints.<name>.x, y, z` | Required finite numbers in metres, rounded to 0.1 mm. |
| `joints.<name>.conf` | Required number in [0, 1]. Not calibrated: 1.0 when the joint lies inside the image, 0.3 when the model placed it outside the frame. |
| `mirrored` | Optional boolean at the top level (see `mirrored`). |
| `t0_pts_ms` | Optional number at the top level (see Time). |
| `provenance` | Optional object at the top level (see `provenance`). |
| `fps` | Not written. Part 3 reads it only when `t_ms` is missing, and Part 2 always writes `t_ms`. |

Coordinate frame, per frame and person: origin at the hip midpoint; `x` is the subject's left
(left hip minus right hip, made horizontal); `y` is up; `z` is `x` cross `y` and points to the
front of the body. Up is the camera's up, so a level camera is assumed and a tilted camera tilts
every pose. Part 3 takes up from the body instead, so a tilt does not reach its output.

Part 3 names this shape `part2.pose3d/2026-10-28` in `x-simon-version`.

### Several people

Single mode writes one person, id 0. Multi-person mode writes `pose3d.json` with every tracked
person in each frame, and `pose3d_person_<id>.json` with one person each (same shape, same top-level
keys). Part 3 keeps the id seen in most frames unless it is given `--person <id>` or `--all-people`,
so pass it the per-person file or one of those options.

## `tracks.json`

```
{"frames": [{"frame": 0, "people": [
  {"id": 0, "bbox": [x, y, w, h], "mask_rle": {"size": [h, w], "counts": "<COCO RLE>"}, "confidence": c}]}],
 "t0_pts_ms": 0.0, "provenance": {"tracker": "api-sam31", "...": "see above"}}
```

`frame` strictly increases and matches `pose3d.json`. `bbox` is `[x, y, w, h]` in pixels with
`w, h >= 0`. `mask_rle` is COCO RLE (`size` is `[h, w]`). `confidence` is in [0, 1]. Ids are unique
within a frame. `t0_pts_ms` and `provenance` are optional. Part 3 does not read `tracks.json`, so no
consumer schema is copied for it; the promise is `contracts/tracks.schema.json` and `validate_tracks`
in `part2/schema.py`.

## `camera.json`

```
{"camera_frame": "opencv", "world_up": "...", "K": [[...], [...], [...]], "image_size": [w, h],
 "frames": [{"frame": 0, "people": [{"id": 0, "R": [[...], [...], [...]], "t": [x, y, z]}]}]}
```

The sidecar that projects joints back onto the frames: `p_cam = R @ p_canonical + t`, then project with `K`.
The camera frame is OpenCV (x right, y down, z forward), in metres. Parts 3, 4 and 5 do not need it.

## `frames/frames.json`

```
{"source": "clip.mp4", "t0_pts_ms": 0.0, "frames": [{"frame": 0, "t_ms": 0.0, "file": "000000.jpg"}]}
```

Written by `part2 frames` next to the images. `frame` and `t_ms` are the values written into
`pose3d.json` and `tracks.json`. `frame` strictly increases but is not always contiguous: an image
directory's own numbering is kept. `source` and `t0_pts_ms` are optional.

## Compatibility table

The same rows are in `contracts/compatibility.json` and are printed by `python -m part2 contract`.

| Producer file | Version | Consumer | Result | Option | Evidence |
|---|---|---|---|---|---|
| pose3d.json, one person | part2.pose3d/2026-10-28 | Part 3 | works |  | Part 3 CONTRACT row for Part 2 7e11a7f; neighbour check |
| pose3d.json, several people | part2.pose3d/2026-10-28 | Part 3 | works with option | Part 3 `--person <id>` or `--all-people`, or the `pose3d_person_<id>.json` file | Part 3 CONTRACT row |
| pose3d.json with `mirrored` | part2.pose3d/2026-10-28 | Part 3 | works | Part 3 `--flip auto` reads it | Part 3 ADR-0005 |
| pose3d.json with `provenance`, `t0_pts_ms` | part2.pose3d/2026-10-28 | Part 3 | works |  | extra keys ignored (Part 3 CONTRACT) |
| pose3d.json | part2.pose3d/2026-10-28 | Part 4 | via Part 3 | Part 3 `--view part4` | Part 4 reads Part 3's skeleton |
| pose3d.json | part2.pose3d/2026-10-28 | Part 5 | via Part 3 | Part 3 `--view part5` | Part 5 `analyse` reads skeleton.json |
| pose3d.json | part2.pose3d/2026-10-28 | Part 6 | works with its generic reader only | none; Part 6 has no Part 2 kind | Part 6 CONTRACT "What every reader accepts" |
| pose3d.json, tracks.json | part2.pose3d/2026-10-28, part2.tracks/2026-10-28 | Part 7 | works |  | Part 7 stitches through the files named here |
| tracks.json | part2.tracks/2026-10-28 | none today | n/a |  | PR #47: Part 3 does not read it |
| pose3d.json, tracks.json (`t_ms`, `t0_pts_ms`) | part2.pose3d/2026-10-28, part2.tracks/2026-10-28 | Part 1 (time join) | works with option | join on `t_ms` when both sides count from the first decoded frame; when `t0_pts_ms` is present and not 0, file time = `t_ms` + `t0_pts_ms` | `frames.py` rule; `doctor` warns |

## Differences between Part 2's validators and Part 3's schema

Part 3's side was read at Part 3 `6d339d5` (the commit in `contracts/consumers/part3-pose3d.schema.source.json`),
Part 2's side in `part2/schema.py` and `part2/contract.py`.

| Field | Part 2 | Part 3 | Effect |
|---|---|---|---|
| `mirrored` | optional; true or false only | optional boolean; any other value rejected | Same. |
| `fps` | optional; a finite number above 0 | optional number above 0 | Same. Part 2 never writes it. |
| person `id` within a frame | `contract.validate` rejects a duplicate; `schema.validate_pose3d` does not | duplicate id rejected | A duplicate passes `schema.validate_pose3d` and fails `contract.validate` and Part 3. Writers run `contract.validate` before writing, so Part 2's files hold none. |
| joint names | exactly the 17 | the schema says exactly the 17; `doctor` drops extra names through an adapter | Same promise; Part 2 never writes extras. |
| `frame` | whole number, `3.0` rejected | the schema type `integer` admits `3.0`; `doctor` rejects it | Same in practice. |
| frame order | strictly increasing | strictly increasing (outside the schema) | Same. |
| `t_ms` | finite number | number in the schema, finite in `doctor`; `--fps` also needs increasing times | Part 2 writes increasing times from `frames.json`. |
| up axis | camera up | taken from the body | Not a format difference. |

Committed outputs: `fixtures/output/single/`, `class/` and `dance/`, each with `pose3d.json` and
`camera.json`, plus `tracks.json` for `class/` and `dance/`. `make check-2-contract` runs each through
its schema, the Part 3 copy and `doctor --for part3`, and none breaks the contract. The single
`pose3d.json` is byte-identical to Part 3's `fixtures/input/part2-single/pose3d.json`.

## Neighbours (status 2026-10-28)

Parts 1, 3, 4 and 6 are done. This part follows the contracts they already set. The contracts below are the ones this part touches.

| Part | Status | What Part 2 follows |
|---|---|---|
| 1 Key frames | done | Part 1 writes `frame` and `t_ms` on the original video clock (`fps` is the video's own rate, for example 60). Part 2's frame numbers come from `frames.json`, sampled with `--fps`. Join the two on `t_ms`, never on frame numbers. `t_ms` must be milliseconds from the start of the original video, so a key frame from Part 1 lands on the same moment in Part 2's `pose3d.json`: add `t0_pts_ms` when it is present and not 0. |
| 3 Skeleton consistency | done | `contracts/consumers/part3-pose3d.schema.json`. Part 3 checks a file with `python3 -m part3 doctor <pose3d.json> --for part3`. Pass `--mirrored` to `part2 run` for a front camera or a mirrored saved video. Part 3 picks one person unless run with `--all-people`, so stable ids across frames matter in class mode. |
| 4 Animate | done | Does not read Part 2 files. Part 4 gets Part 2's motion through Part 3. |
| 6 Catalog | done | Does not read Part 2 files. `doctor --for part6` applies its generic reader rules only. |

Part 5 reads `skeleton.json`, which Part 3 writes. Part 7 stitches through the files on this page.
`make contract-check` fails when Part 3's published schema changes. `make contract-sync` updates the copy.

## How to ask

Questions and change requests go on issue #18 (Team chat, Part 2) in `moalborati/simon-part-2-images-to-3d`.
Name the file, the field and the rule you need. Run `python -m part2 doctor <your file> --for <your part>`
first and paste its output.
