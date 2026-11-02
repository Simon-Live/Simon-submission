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
| `mesh3d.json` + `mesh3d.bin` (optional, `--mesh`) | `mesh3d` | `part2.mesh3d/2026-10-31` | `contracts/mesh3d.schema.json` (the header; the bin is checked by `part2 doctor`) |

There are five schemas: the first four are for files Part 2 writes without being asked, and `mesh3d` is the header of the
optional mesh pair. They are draft 2020-12. The version is the `x-simon-version` key of each schema.
`contracts/compatibility.json` holds the table below, with no row for `mesh3d.json`: no consumer has verified it yet (Part 7's mesh view, its TICKET-143, asked for it), and a row cites a consumer's evidence, so the row is added with that evidence. `contracts/consumers/part3-pose3d.schema.json` is
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

With `mirrored: true`, the optional `extra_joints` (see "Extra joints (optional)") carry the same labels as
`joints`. Part 3 mirrors `joints` and does not touch `extra_joints`, so a reader that mirrors the joints and also
uses the feet must mirror the feet the same way: swap the `left_` and `right_` names (`left_heel` becomes
`right_heel`, and so on) and negate x.

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
| `backend` | The 3D backend that ran, for example `gpu`. It may be `cpu-sam3db` (SAM 3D Body on the CPU device), which writes `extra_joints` and a `null` `lifter`. |
| `tracker` | The tracker that ran, for example `api-sam31`; `null` in one-person mode, where none runs. |
| `lifter` | The 2D to 3D lifter of the `cpu` backend (`bones-prior`, `fixed-bones` or `motionbert`); `null` otherwise, as for `gpu` and `cpu-sam3db`. |
| `refine` | The refinement rungs applied, in order. |
| `models` | `[{name, source, weights_sha256}]`. `weights_sha256` is `null` for a hosted model or a file that was not hashed. |
| `part2_commit` | The git commit of Part 2 that wrote the file, with `+dirty` when tracked files differed; `unknown` without git. |
| `created_utc` | `YYYY-MM-DDTHH:MM:SSZ`. |
| `licence_notes` | A list of notes that apply to the models used. |
| `extra_joints` | The names of the foot points the file holds (see "Extra joints (optional)"), in writing order. Absent when the file holds none, as in every `cpu` backend output; the `cpu-sam3db` backend writes the points. |

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
| `frames[].people[].extra_joints` | Optional object: the foot points (see "Extra joints (optional)"). |
| `mirrored` | Optional boolean at the top level (see `mirrored`). |
| `t0_pts_ms` | Optional number at the top level (see Time). |
| `provenance` | Optional object at the top level (see `provenance`). |
| `fps` | Not written. Part 3 reads it only when `t_ms` is missing, and Part 2 always writes `t_ms`. |

Coordinate frame, per frame and person: origin at the hip midpoint; `x` is the subject's left
(left hip minus right hip, made horizontal); `y` is up; `z` is `x` cross `y` and points to the
front of the body. Up is the camera's up, so a level camera is assumed and a tilted camera tilts
every pose. Part 3 takes up from the body instead, so a tilt does not reach its output.

Part 3 names this shape `part2.pose3d/2026-10-28` in `x-simon-version`.

### Extra joints (optional)

A person may carry `extra_joints` beside `joints`: the heel, big toe and small toe of each foot, asked for by Part 5.

```
{"id": 0, "joints": {...the 17...}, "extra_joints": {
  "left_big_toe": {"x": x, "y": y, "z": z, "conf": c}, ...left_small_toe, left_heel, right_big_toe, right_small_toe, right_heel}}
```

| Rule | Promise |
|---|---|
| Names | `left_big_toe`, `left_small_toe`, `left_heel`, `right_big_toe`, `right_small_toe`, `right_heel`, written in this order. Any may be left out; no other name is allowed. Left and right are the subject's. |
| Each point | The shape of a joint: `x, y, z` finite numbers in metres in the same canonical frame as `joints` (rounded to 0.1 mm), `conf` in [0, 1] by the same rule (1.0 inside the image, 0.3 placed outside it). Never null. |
| Who writes it | The gpu backend and the cpu-sam3db backend (SAM 3D Body gives these points), for every person they write. The `cpu` backend writes none: RTMPose-x gives 17 points. `provenance.extra_joints` names the points a file holds. |
| Mirrored file | With `"mirrored": true`, `extra_joints` carry the same labels as `joints`. Part 3 does not touch `extra_joints`, so a reader that mirrors the joints must also swap the `left_` and `right_` names of the feet and negate x. |
| Refinement | The refine rungs keep the points with the refined skeleton: when a rung moves the ankles, each foot point moves with its own ankle by the same displacement; the `focal` rung takes the points of the camera it chooses. |
| `joints` | Unchanged: exactly the 17, so a reader that knows only `joints` reads the same file as before. |
| Version | A new optional field, so `part2.pose3d/2026-10-28` stays (version policy above). |

`python -m part2 doctor` adds one line when the file has them:
`extra joints: <names> on <k> of <n> person-frames (optional extra_joints beside the 17 joints)`, where `<k>` counts
the person-frames that carry any of the points. No verdict changes. `make check-feet` measures them on
the scored outputs (coverage, segment-length consistency per person, distance to the ankle); it is reported and
never gated.

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

## `mesh3d.json` + `mesh3d.bin` (optional, `part2 run --mesh`)

The SAM 3D Body body mesh (MHR) of every person in every frame, decimated once per run to about `--mesh-vertices`
vertices (default 2500). Written only with `--mesh` on the `gpu` or `cpu-sam3db` backend, after `pose3d.json`, in
the same directory; a run without `--mesh` removes a pair left there by an earlier run. Schema of the header:
`contracts/mesh3d.schema.json`, version `part2.mesh3d/2026-10-31`. Spec: `docs/specs/mesh3d.md`. With `--mesh-stream` the run also writes `mesh3d.stream/` (head.bin, chunk-NNNN.bin, stream.json) while the model runs; the pair is unchanged (AC-M19 to AC-M23).

| Rule | Promise |
|---|---|
| Frame | Each person-frame is in the pose3d canonical frame of that person and frame (origin hip midpoint, x the subject's left, y up, z forward, metres), from the model's own 17 joints. `--refine` is refused with `--mesh`, because the focal rung re-runs the model without the mesh, so a mesh would come from a different run than `pose3d.json`. `--smooth` moves the pose3d joints over time and the mesh is not smoothed; that offset is not measured. Measured without either (TICKET-048, 15 frames of `fixtures/input/single`, unrefined): each of the 17 joints lay a mean 2.4 cm (median 2.0, largest 9.1) from its nearest mesh vertex. That shows the joints and the mesh share one frame; it is not an accuracy claim. |
| Mirrored | `--mirrored` flips nothing: it writes `"mirrored": true` in `pose3d.json` and the joints stay unmirrored, and the mesh stays in the same unmirrored frame (a run with and without `--mirrored` writes the same `mesh3d.json` and `mesh3d.bin`). A reader that mirrors the joints (Part 3 `--flip auto`) must mirror the mesh the same way: negate the x of every vertex, swap the `left_` and `right_` names in `vertex_joint.names`, and reverse the winding of each face (swap two of its indices) so back-face culling still works. |
| Header | `frames[]` lists every frame with the `frame` and `t_ms` of `pose3d.json`; each person has an `id` and an `offset` into the bin. `vertex_count`, `face_count`, `faces.dtype` (`uint16` or `uint32`), `vertices.unit_m` (0.0001), `bin_bytes`, `bin_sha256`, `licence`. |
| Bin | Faces (`face_count` x 3, little-endian) at offset 0; then `vertex_count` uint8 labels at `vertex_joint.offset`, each the index in `vertex_joint.names` (the 17 joints) of the vertex's nearest joint on the first person-frame, for tinting a limb; each part zero-padded to 4 bytes; then one `vertex_count` x 3 little-endian int16 block per person-frame. Metres = value x `unit_m`. |
| Size | 6 bytes per vertex per person-frame: 15 KB at 2500 vertices, 150 KB per second at 10 fps for one person, plus the faces once. |
| Licence | The pair derives from two licensed sources, and the header's `licence` field names both. SAM 3D Body and the MHR model file Part 2 loads (`assets/mhr_model.pt` from the SAM 3D Body mirror) come under the mirror's SAM License; MHR upstream (`facebookresearch/MHR`) is Apache-2.0 (ADR-0005). A copy of the SAM License goes with any redistribution. Apache-2.0 also requires its licence text and MHR's notice to go with any redistribution of the mesh faces, which derive from MHR. Part 2 commits and publishes no mesh output, asset or face list. |

Backends and exit codes. `--mesh` works on the `gpu` and `cpu-sam3db` backends and gives the same pair on both (the
vertices are part of the same SAM 3D Body output). With `--backend cpu` it exits 2 (`part2: --mesh needs SAM 3D Body
(--backend gpu or cpu-sam3db)`), as does `--mesh-vertices` below 100 (0 and negative numbers included) or given
without `--mesh`, and `--mesh` with any `--refine` other than `none` (`part2: --mesh cannot be combined with --refine
(the mesh comes from the unrefined run)`). A command refused before `--input` is opened removes nothing, so a pair
already in `--out` stays: every exit 2 from the options and the `--refine` and `--mesh` checks, and the exit 1 of a
`--tracks` file that cannot be read, is not a valid tracks file or lacks an `--ids` entry. The old pair is removed just
before the input is read, so a failure from that point on can follow the removal: exit 1 for an `--input` that cannot be
read, an `--fps` of 0 or less or a `--tracks` file made for other frames, exit 2 for an unknown `--tracker` in
`--mode multi`. The `pose3d.json` of the earlier run is then left without a mesh pair, never with a mismatched one. When no
person is found the run exits 4 as without `--mesh` and writes no `mesh3d.json` or `mesh3d.bin`. When people are found
but none gives a mesh (every person's hips give no canonical frame), `pose3d.json` is written, no pair is, and the run
exits 1 with `part2: --mesh found no mesh vertices; no mesh3d pair written`. Through the warm worker
(`run --worker`) `--mesh` is an argument of the served `run` like any other.

`python -m part2 doctor mesh3d.json` checks the header against its schema and the bin (size, sha256, offsets, face
indices): exit 0 when valid, 1 when not, with the same `schema: breaks ...` line and the same `--json` fields as for
`pose3d.json`, for any malformed header. Parts 3, 5 and 6 do not read it; `--for` any of them exits 1 and says so.

## `frames/frames.json`

```
{"source": "clip.mp4", "t0_pts_ms": 0.0, "frames": [{"frame": 0, "t_ms": 0.0, "file": "000000.jpg"}]}
```

Written by `part2 frames` next to the images. `frame` and `t_ms` are the values written into
`pose3d.json` and `tracks.json`. `frame` strictly increases but is not always contiguous: an image
directory's own numbering is kept. `source` and `t0_pts_ms` are optional.

### Sampled times without images: `part2 frame-times`

```
part2 frame-times --input <video> [--fps N] [--out frames.json]
```

| Argument | Meaning |
|---|---|
| `--input` | required; a video file (an image directory is refused: it keeps its own `frames.json`) |
| `--fps N` | the sample rate, more than 0; without it every decoded frame is listed |
| `--out` | write the document there (parent directories are created) and print `<n> frames -> <path>`; without it the document is printed |

Output: the `frames.json` document above (`source`, `t0_pts_ms`, `frames[]` with `frame`, `t_ms`, `file`), validated by
`contracts/frames.schema.json`. Guarantee: for the same video and `--fps` it is identical to the `frames.json` that
`part2 run` and `part2 track` write into `frames/`, byte for byte when written with `--out`: the same ffprobe
`best_effort_timestamp_time` timestamps (so variable frame rate works), the same nearest-per-step rule (the source frame
nearest `t0 + n / fps`, deduplicated), the same `t_ms` (milliseconds from the first decoded frame) and `t0_pts_ms`. No
image is written. `file` names the image `run` would write for that record. Exit 0 written or printed, 1 input error
(missing file, directory, not a video, `--fps` of 0 or less), 2 bad option. Python: `part2.frame_times.frame_times(path,
fps)` returns the document, `part2.frame_times.sample_times(pts, fps)` returns the kept indices into a timestamp list
in seconds. Part 7 resamples its 3 fps people step onto these times; do not copy the rule.

## Compatibility table

The same rows are in `contracts/compatibility.json` and are printed by `python -m part2 contract`.

| Producer file | Version | Consumer | Result | Option | Evidence |
|---|---|---|---|---|---|
| pose3d.json, one person | part2.pose3d/2026-10-28 | Part 3 | works |  | Part 3 CONTRACT row for Part 2 7e11a7f; neighbour check |
| pose3d.json, several people | part2.pose3d/2026-10-28 | Part 3 | works with option | Part 3 `--person <id>` or `--all-people`, or the `pose3d_person_<id>.json` file | Part 3 CONTRACT row |
| pose3d.json with `mirrored` | part2.pose3d/2026-10-28 | Part 3 | works | Part 3 `--flip auto` reads it | Part 3 ADR-0005 |
| pose3d.json with `provenance`, `t0_pts_ms` | part2.pose3d/2026-10-28 | Part 3 | works |  | extra keys ignored (Part 3 CONTRACT) |
| pose3d.json with `extra_joints` | part2.pose3d/2026-10-28 | Part 3 | works |  | Part 3's schema sets additionalProperties false on `joints` only; tests/test_extra_joints.py |
| pose3d.json with `extra_joints` | part2.pose3d/2026-10-28 | Part 5 (feet read directly) | works with option | read `extra_joints` in Part 2's canonical frame (x subject's left, y up, z anterior, metres); with `mirrored: true`, swap the `left_` and `right_` names and negate x, as for `joints`, because Part 3 does not touch `extra_joints` | tests/test_extra_joints.py; CONTRACT.md "Extra joints (optional)" |
| pose3d.json | part2.pose3d/2026-10-28 | Part 4 | via Part 3 | Part 3 `--view part4` | Part 4 reads Part 3's skeleton |
| pose3d.json | part2.pose3d/2026-10-28 | Part 5 | via Part 3 | Part 3 `--view part5` | Part 5 `analyse` reads skeleton.json |
| pose3d.json | part2.pose3d/2026-10-28 | Part 6 | works with its generic reader only | none; Part 6 has no Part 2 kind | Part 6 CONTRACT "What every reader accepts" |
| pose3d.json, tracks.json | part2.pose3d/2026-10-28, part2.tracks/2026-10-28 | Part 7 | works |  | Part 7 stitches through the files named here |
| tracks.json | part2.tracks/2026-10-28 | none today | n/a |  | PR #47: Part 3 does not read it |
| pose3d.json, tracks.json (`t_ms`, `t0_pts_ms`) | part2.pose3d/2026-10-28, part2.tracks/2026-10-28 | Part 1 (time join) | works with option | join on `t_ms` when both sides count from the first decoded frame; when `t0_pts_ms` is present and not 0, file time = `t_ms` + `t0_pts_ms` | `frames.py` rule; `doctor` warns |
| tracks.json from `part2 track`; pose3d.json from `part2 run --mode multi --tracks --ids` | part2.tracks/2026-10-28, part2.pose3d/2026-10-28 | Part 7 (people picker) | works |  | tests/test_cli_track.py; same files, no new field |

## How Part 7 runs a take

Part 7 turns a viewer's recorded or uploaded take into `pose3d.json` with one command:

```
part2 run --mode single --input <take.webm|take.mp4|take.mov> --out <dir> --fps 10 --backend gpu [--mirrored]
```

| Option | Why |
|---|---|
| `--mode single` | one person per take |
| `--input` | the file as recorded: WebM from a browser (VP8 or VP9), MP4 or MOV from a phone; a rotate tag is applied, so frames come out upright |
| `--out <dir>` | required; `frames/`, `pose3d.json` and `camera.json` are written there |
| `--fps 10` | the rate the web app also uses (60 s gives at most 601 frames) |
| `--backend gpu` | the GPU backend; `cpu` is the slower choice on a host without CUDA and its 3D is approximate (it misses the 3D bar). `cpu-sam3db` runs the same SAM 3D Body on the CPU and meets the 3D bar (mean joint distance 0.0363 m, bone CV 0.0408, against the refined gpu output while the CPU run is unrefined), at 31.74 s per frame on 8 threads plus 23.7 s model load (the 2026-10-31 run); 46.95 s per frame plus 23.4 s model load under host load (the committed set, regenerated 2026-11-01) |
| `--mirrored` | only for a front-camera recording saved as a mirror image; writes `mirrored: true`, which Part 3 `--flip auto` reads |

Then Part 7 runs Part 3 on `<dir>/pose3d.json` with `--view part5` for Part 5. The command line reads a WebM
that carries no duration (a MediaRecorder file). The run app's upload check does too
(`docs/specs/journey-followup.md`).

### Exit codes (`run` and `track`)

| Code | Meaning | stderr |
|---|---|---|
| 0 | written | |
| 1 | failed: an unreadable input, a backend or tracker that cannot run here (no CUDA, a missing or refused key), the GPU busy, out of memory, an output that breaks the contract, any other error, `--mesh` that found people but no mesh vertices (`pose3d.json` is kept) | `part2: <reason>` |
| 2 | usage error: an option argparse refuses, an unknown backend, lifter or tracker, or options the command does not take together (`--tracks` with `--mode single`, `--mesh` with `--backend cpu` or with `--refine`) | argparse's text, or `part2: <reason>` |
| 4 | no person found in any frame; no `pose3d.json` or `camera.json` is written (nor `mesh3d.json` with `--mesh`), and `track` writes no `tracks.json` | `part2: no person found in <n> frames` (the 3D backend, `run`), or `part2: no person found to track` (the tracker, `track` and `run --mode multi`) |

Code 4 means Part 2 ran and found nobody, which is a different case from a failure. The message text is the one
Part 2 has always printed, so a consumer may rely on the code, on the message, or on both; an earlier Part 2 exited 1
with the same message. A frame with nobody in it is not this case: the run goes on with `people: []` for that frame
and exits 0. Through the warm worker the client exits with the same code (see "Warm worker").

### Several people in one take (`track`, then `run --tracks --ids`)

Part 7 first asks who is in the clip, then computes 3D for the people the viewer chose:

```
part2 track --input <take> --out <dir> --fps 10 [--tracker <name>]
part2 run --mode multi --input <take> --out <dir2> --fps 10 --backend gpu --tracks <dir>/tracks.json --ids <id>,<id>
```

| Command | Result |
|---|---|
| `part2 track` | `frames/` and `tracks.json` only, no 3D. The tracker order is the one of `run --mode multi` (`--tracker`, `--tracker-order`). Exit 0 written, 1 input error, 2 bad option (unknown tracker), 4 no person found ("Exit codes", above). |
| `run --tracks <tracks.json>` | uses that file as it is: no tracker runs and the ids stay as they are. Pass the same `--input` and `--fps` that made it; a frame the file lacks is exit 1. `--tracker` or `--tracker-order` together with `--tracks` is exit 2: the file already fixed the tracker. |
| `run --ids <id,...>` | 3D runs for the listed people only. `pose3d.json` holds those people, plus `pose3d_person_<id>.json` each. An id that `tracks.json` lacks is exit 1 and the message names it. |

`--tracks` and `--ids` apply to `--mode multi` only (exit 2 with `--mode single`). `--ids` without `--tracks`
tracks first, then filters. The files keep their versions; nothing new is written into them.

With no tracker named, `part2 track` and `part2 run --mode multi` walk the `bulk` order, and when the Meta API refuses the credential (HTTP 401 or 403) they move on to the next tracker that can run (`local-open`) with one stderr line instead of exiting 1, writing the `provenance` keys a skipped step writes (`fallback_from: "api-sam31"`, `fallback_reason: "credential_refused"`); a named `--tracker api-sam31` and `--tracker-order scored` still exit 1 with `the credential was refused`.

### Warm worker (`serve-worker`, `run --worker`)

Loading the 3D model costs about 20 to 35 s per `part2 run`. A worker loads it once and keeps it for every `run`
it serves. It keeps only the 3D backend warm: `track` is served the same way (same arguments, same files, same
output stream) but saves no model load, because a tracker loads its own model on every request (the local SAM 3.1
tracker starts a child process each time).

```
part2 serve-worker --socket <path> [--backend gpu]          # long-lived; prints "listening on <path>" when ready
part2 run --worker <path> --mode single --input ... --out ...   # same arguments, same files as without --worker
part2 track --worker <path> --input ... --out ...           # same files; no model load saved (see above)
```

With no worker at `<path>` (missing socket, connection refused, permission denied, or a path too long for a Unix
socket) the command runs in its own process and says so on stderr, so Part 7 can pass `--worker` always. A worker
that dies mid-request gives exit 1 and the job is not re-run in-process. So do the two waits of the CLI client.
Before the worker's first line it waits for its turn behind other jobs for up to 3600 s
(`worker.CLIENT_QUEUE_WAIT_S`): `part2: waited 3600 s for a turn at the worker; connection dropped, not re-run
in-process`. From the first line on it waits 120 s (`worker.CLIENT_IDLE_TIMEOUT_S`) for the next line, counted from
the last one received, a keepalive included: `part2: the worker sent nothing for 120 s; connection dropped, not
re-run in-process`. A socket that another user owns gives exit 1 and nothing is sent: the client reads the owner with
`SO_PEERCRED` before it writes the request.

`serve-worker` exits 1 with a one-line reason, before it loads any model, when `<path>` exists and is not a socket,
when a worker already answers there, or when no socket can be made there (the path is over 107 bytes, or its directory
is missing, not a directory or not writable). A socket left by a worker that was killed is replaced. On exit the worker
removes the socket file only if it made that file.

Protocol, for a client that does not call the CLI: a Unix stream socket, one request per connection, newline-delimited JSON.

| Direction | Message |
|---|---|
| client to worker | `{"argv": ["run", "--mode", "single", ...], "cwd": "<absolute dir>", "env": {"PART2_PROGRESS": "1"}}`, argv without `--worker`; relative paths in argv resolve against `cwd`; only `PART2_*` env is applied, and for the job it replaces the worker's own `PART2_*` variables |
| worker to client | `{"stream": "stdout" or "stderr", "data": "<text>"}` as the job prints (the `progress <stage> <done> <total>` lines arrive here), zero or more; `data` is always a string |
| worker to client, first | `{"keepalive": true}` at once when the worker takes the request, before anything runs. Requests are served one at a time, so a request queued behind a job hears nothing until its turn; this first line says the turn has come. A client with its own timeout should wait for it as long as it is willing to queue (the CLI client: 3600 s), and use a short limit only after it |
| worker to client, while a job runs | `{"keepalive": true}` every 30 s (`worker.KEEPALIVE_S`), whatever the job prints; it carries nothing to print and a client ignores it, but it counts as a sign of life for the idle limit. A 3D stage prints nothing for minutes, so a client that has its own timeout should restart it on any line, this one included |
| worker to client, last | `{"exit": <n>}` with `<n>` an integer, the exit code `part2 <argv>` would give (0 written, 1 input or contract error, 2 bad option, 4 no person found); the CLI client treats any other value as exit 1 with one message line. The worker also answers exit 2, with one stderr line and without running anything, for a command other than `run` or `track`, an argv that still carries `--worker` (or an abbreviation of it), and a request that is not a JSON object with `argv` a list of strings, `cwd` an existing absolute directory and `env` a map of strings to strings |

Concurrency: one request at a time per worker. A second client connects and waits in the socket queue (8 deep)
until the first finishes. The worker accepts one connection at a time, so a queued client hears nothing until its
turn; the CLI client waits up to 3600 s for the first line, however long the jobs ahead run within that bound, and
only then applies its 120 s limit (above). A client that gives up in the queue leaves exit 1 behind; its request is
then not run when its turn comes (the worker sees the closed connection). The CLI client treats a reply
that is none of the three kinds above, or a stream message whose `data` is not a string, as a lost connection (exit 1,
no re-run in-process). Part 7 should queue its own jobs or run one worker per GPU slot (about 10 GiB each).
The host GPU lock still applies to every request. A request that raises does not stop the worker, and neither
does a client that disconnects or sends a malformed request; the worker logs the traceback on its own stderr and
serves the next one. Restart the worker after a `git pull` of Part 2 (code and models are loaded once).

Two limits to plan for. A warm worker keeps its models in GPU memory between requests (about 10 GiB) and outside
the host GPU lock, which `part2 run` holds only around each 3D estimate. The staging job worker's check of 12 GiB
free memory therefore sees that memory as used. Only what Python code writes to `sys.stdout` and `sys.stderr`
streams to the client; output that a C extension or subprocess writes straight to file descriptors 1 and 2 stays
on the worker's terminal. Spec: `docs/specs/warm-worker.md`.

### Warm track worker (`serve-worker --mode track`)

The 3D worker saves no load for `track`. A track worker does: it builds SAM 3.1 once and serves `part2 track
--tracker local-sam31`. It is a separate process from the 3D worker and loads no 3D model, because SAM 3.1 enters a
bf16 autocast that broke SAM 3D Body when both shared a process. Inside the worker the model is built on one thread
and every call runs on that thread.

```
part2 serve-worker --mode track --socket <path>                       # long-lived; "listening on <path>" when ready
part2 track --worker <path> --tracker local-sam31 --input <take> --out <dir> --fps 10   # same files as without --worker
```

Measured on the RTX 5090 with a 10 s clip at `--fps 10` (101 frames): cold `part2 track --tracker local-sam31` 38.7 s; the worker is ready 23.5 s after it starts; then each warm call takes 13.1 to 15.0 s (median 13.4 s over three calls), and every file it writes matches the cold run's (the 2026-11-01 run of `tests/test_warm_track_gpu.py`).

| | |
|---|---|
| Request shape | the 3D worker's (above): `{"argv": ["track", "--input", "<take>", "--out", "<dir>", "--fps", "10", "--tracker", "local-sam31"], "cwd": "<absolute dir>", "env": {"PART2_PROGRESS": "1"}}`. `local-sam31` is named by `--tracker`, or by `PART2_TRACKER` in `env` when `--tracker` is absent |
| Socket protocol | the 3D worker's, unchanged: Unix stream socket, one request per connection, newline-delimited JSON; replies are the first `{"keepalive": true}`, then `{"stream": ...}` lines and a keepalive every 30 s, then `{"exit": <n>}` |
| Served | `track` with `local-sam31` named. `run` is exit 2 (`part2: the worker serves track, not ['run']`); `track` with another tracker or none named is exit 2 (`part2: this worker serves \`track --tracker local-sam31\` only ...`); nothing is read or written for either |
| Files | those of the cold `part2 track --tracker local-sam31` for the same input, byte for byte except `provenance.created_utc`, the second the file was written |
| Exit codes | as "Exit codes" above: 0 written, 1 failed, 2 bad option or not served, 4 no person found |
| GPU lock | each call holds the host GPU lock while the model runs, as the cold tracker does |
| Start | `serve-worker --mode track` needs `HF_TOKEN` and the gpu-cu128 venv; it exits 1 with one line, before any model loads, without them, when the GPU lock stays busy for 600 s, or on the socket refusals of the 3D worker. `--backend` with `--mode track` is exit 2 |

Memory. A call peaked near 27 GB reserved on the 32 GB card (measured: 26.1 GiB, 28.0 GB); the worker releases its
cache after each call and about 5.5 GB (5.1 GiB) stays resident between calls, outside the host GPU lock and beside the 3D worker's about 10 GiB. The worker
logs `part2 track worker: peak reserved X GiB, reserved after Y GiB` on its own stderr after each call.

Failure. Every failure reaches the client as an exit code, so Part 7 runs the cold `part2 track` (without
`--worker`) whenever `--worker` gives exit 1:
- out of GPU memory in a call: exit 1 with `part2: CUDA out of memory...`; the worker keeps serving;
- any other failure of the model: exit 1 with one line, then the worker stops and removes its socket, so later
  `--worker` calls find no worker and run in their own process (the cold path) by themselves;
- a worker that crashes or is killed mid-call: the client exits 1 with `part2: the worker closed the connection before
  finishing; not re-run in-process`;
- no worker at the path: the client runs the job in its own process and says so on stderr, as with the 3D worker.

Exit 4 (no person found) and exit 2 are answers, not failures: running the cold CLI again gives the same code. Restart
the worker after a `git pull` of Part 2 or a new checkpoint. Spec: `docs/specs/warm-track.md`.

## Rigged models: `part2 avatar` and `part2 autorig`

Two commands make a rigged humanoid GLB for Simon's model picker. Both write the same two files and share one
MHR joint table (`part2/mhr_export.py`). Neither touches `run`, `track` or any file of the take contract above.

```
part2 avatar  --out DIR IMG [IMG...]                   # 1 to 4 photos (JPEG, PNG, WebP) of one person
part2 autorig --out DIR MESH [--height M] [--up y|z]   # one .obj, or one .glb without a skin
```

| Argument | Meaning |
|---|---|
| `--out DIR` | required; the directory for the two outputs, created if missing. An `--out` that is a file is exit 2 (`avatar`) |
| `IMG` (`avatar`) | 1 to 4 photos, each up to 25 MB, checked by magic bytes. Order does not change the result |
| `MESH` (`autorig`) | an OBJ or a GLB with no skin, 50 to 300000 triangles, up to 200 MB |
| `--height M` (`autorig`) | the person's height in metres, 0.3 to 3; default: guessed from the mesh's unit |
| `--up y\|z` (`autorig`) | the mesh's up axis; default: guessed |

Outputs, written whole on exit 0. A stale `model.glb` or `avatar.json` in `DIR` is removed before the run, so a failed
run leaves none that looks current.

| File | Content |
|---|---|
| `model.glb` | glTF 2.0 binary: one skinned mesh, 127 joints, at most four joints per vertex, metres, Y up, facing +Z, soles on y = 0. The 22 bones Simon drives carry canonical names (`hips`, `spine`, `chest`, `upperChest`, `neck`, `head`, `leftShoulder` to `leftHand`, `rightShoulder` to `rightHand`, `leftUpperLeg` to `leftToes`, `rightUpperLeg` to `rightToes`); the rest are `mhr_<index>`. Every joint has an identity rotation at bind |
| `avatar.json` | `{schema: "simon.avatar.v1", kind: "image" or "autorig", inputs, height_m, joints: 127, mapped: {<canonical>: <glTF node index>}, licence: "SAM License; MHR Apache-2.0 notice", part2_commit, skinning}`; `autorig` adds `fit_error_m`, `turned_to_face_forward`, `up_axis`, `unit_guess` |

Exit codes of both commands; the message is one line on stderr, `part2: <reason>`:

| Code | Meaning |
|---|---|
| 0 | `model.glb` and `avatar.json` written |
| 1 | failed: the backend cannot run here (no CUDA, no weights) or any other error |
| 2 | bad input: a missing, empty, oversized or unreadable file, the wrong count or type, a mesh that already has a skin or does not look like one standing person, a figure whose facing cannot be told |
| 3 | no person found in the photo (`avatar`) or in the picture drawn of the mesh (`autorig`) |
| 4 | the GPU is not available: the host GPU lock stays held past `PART2_AVATAR_GPU_WAIT_S` or `PART2_AUTORIG_GPU_WAIT_S` (default 30 s), free GPU memory is too low, or the model ran out of memory |

Code 4 here means a busy GPU, unlike code 4 of `run` and `track` ("no person found", above); code 3 is the no-person
case for these two commands. A caller waits and retries on 4. The photos and the picture drawn of a mesh are never
kept. Consent, the age gate and who may see the result belong to the caller (Part 7 keeps generated models private to
their owner). The model is made with SAM 3D Body and the MHR body model; `licence` and the GLB's `asset.copyright`
carry the notice any copy needs (ADR-0005). Specs: `docs/specs/avatar.md`, `docs/specs/autorig.md`.

## A textured, rigged model from one picture: `part2 image3d`

```
part2 image3d --out DIR IMG [--height M] [--backend auto|sam3do|trellis]   # one JPEG, PNG or WebP of a character
```

Writes `DIR/model.glb` and `DIR/avatar.json` like `avatar` and `autorig` (same 22 canonical bone names, 127 joints, metres,
Y up, facing +Z), with two differences: the surface keeps its look as a texture image with UVs (`TEXCOORD_0`, base colour
texture, no vertex colours), and `avatar.json` has `kind: "image3d"` plus `backend` (model, version, weights revision),
`timings_s`, `peak_vram_gib`, `texture` and `height_assumed`. `--height` defaults to 1.7 m. An image-to-3D model makes
the mesh (SAM 3D Objects first; TRELLIS only when SAM 3D Objects cannot run on the host or by `--backend trellis`), then
`autorig`'s rigger rigs it. Exit codes: 0 written, 1 failed, 2 bad input, 3 nothing humanoid could be rigged (the line
says so), 4 the GPU is not available (lock held past `PART2_IMAGE3D_GPU_WAIT_S`, free memory below the backend's need,
or out of memory). **Part 7 must release Part 2's warm workers before calling it**, and wait and retry on 4: the memory
each backend needs is in `docs/specs/image3d.md` ("Measured"). It runs minutes, not seconds, so call it detached.
The picture is never kept; its rights are the caller's. Licences: ADR-0005.

## Differences between Part 2's validators and Part 3's schema

Part 3's side was read at Part 3 `6d339d5` (the commit in `contracts/consumers/part3-pose3d.schema.source.json`),
Part 2's side in `part2/schema.py` and `part2/contract.py`.

| Field | Part 2 | Part 3 | Effect |
|---|---|---|---|
| `mirrored` | optional; true or false only | optional boolean; any other value rejected | Same. |
| `fps` | optional; a finite number above 0 | optional number above 0 | Same. Part 2 never writes it. |
| person `id` within a frame | `contract.validate` rejects a duplicate; `schema.validate_pose3d` does not | duplicate id rejected | A duplicate passes `schema.validate_pose3d` and fails `contract.validate` and Part 3. Writers run `contract.validate` before writing, so Part 2's files hold none. |
| joint names | exactly the 17 | the schema says exactly the 17; `doctor` drops extra names through an adapter | Same promise; Part 2 never writes extra names inside `joints`. |
| `extra_joints` | optional; the six foot point names only, each a joint | not in the schema; the person object allows extra keys | Part 3 accepts a file that has them. |
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
