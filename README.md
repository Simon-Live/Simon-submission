# Simon Part 3 — Align 3D model / skeleton consistency


Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
This repo is **only** Simon Part 3. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way — that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #57. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 3).

## Input

`pose3d.json` (from Part 2, any camera angle). Fixtures in `fixtures/input/`.

## Output

`skeleton.json` — the same motion with one fixed set of bone lengths, rotated to a standard facing, scaled to standard limb lengths, no left/right label flips.

## Shared-file context (only what this part touches)

Canonical 17 joints (subject's left/right): nose, left_eye, right_eye, left_ear, right_ear, left_shoulder, right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee, right_knee, left_ankle, right_ankle. Coordinate frame: origin at the hip midpoint per frame; x = subject's left (horizontal), y = world up, z = anterior (x × y); metres and degrees. Input and output use the same joint names and frame; output adds one fixed `bone_lengths_m` set for the whole clip.

## Frontier model

none

## Definition of done

Bone-length variation <2% across a clip; zero left/right flips; the same movement filmed from 4 synced phones produces skeletons whose joint angles agree within 10°.

Done-check: `make check-3` — prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** The 4 phone views going in, the 4 aligned skeletons overlapping.
- **Integrated:** Part 4 and Part 5 only ever see `skeleton.json`; camera angle is already removed here (this is the 'any angle' claim).

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-3`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.

## Development

```
make run IN=fixtures/input/part2-single/pose3d.json OUT=out/skeleton.json   # FLIP=auto|on|off
make check-3    # done-check: prints the metrics JSON, exit 0 only when every threshold passes
make test       # unit and acceptance tests (pytest, tests/part3/)
make demo       # web app on http://127.0.0.1:8733/ (runs in the background); make demo-stop ends it
```

Needs Python 3.11 or later with numpy and pytest. `make setup` installs the pins in `requirements.txt` with pip; on a system Python that refuses pip installs (PEP 668), run it inside a virtualenv (`python3 -m venv .venv && . .venv/bin/activate && make setup`). No network, no model, no GPU.

`python3 -m part3 run --in <pose3d.json> --out <skeleton.json> [--flip auto|on|off]` exits 0 on success, 2 when the input breaks the `pose3d.json` contract (the failing path is printed, nothing is written) and 1 when the output cannot be written. `python3 -m part3.schema <skeleton.json>` validates an output file.

What the run does, in order: validate the input, keep one person, apply the mirror option, repair left/right label swaps, take "up" from the body (feet to shoulders while standing straight) instead of the camera, express every frame in that body frame, apply one fixed 5-frame mean to remove per-frame jitter, and rebuild every frame on one body profile (default `simon-standard`: `part3/standard_body.json`, stature 1.70 m; `part4-rig` for `--view part4`). Timing is unchanged: every input frame and `t_ms` is kept unless `--fps` asks for a new grid.

- **One person.** When the input holds several ids, the id present in the most frames is kept; ties go to the larger person in the image, then to the first id. `skeleton.json` records the choice under `person`.
- **`--flip`.** A selfie-mode video can be saved mirrored, which swaps left and right in a way no pose can reveal. `auto` (default) mirrors only when the input has the top-level key `"mirrored": true`; `on` always mirrors; `off` never does. The output records the setting, whether it was applied and why under `mirror`.
- **The 4-angle agreement is synthetic.** A movement is recorded as one take from one phone at any angle, so no multi-angle recording exists. `make check-3` therefore measures the "4 phones agree within 10 degrees" criterion on four synthetic takes of the real Part 2 squat, rendered from four camera angles with Part 2-like errors (`fixtures/input/synthetic-4take/`, regenerated with `python3 -m part3.synth --out fixtures/input/synthetic-4take`). The metrics JSON says `"data_source": "synthetic"`.
- **Output for Parts 4 and 5.** `fixtures/output/` holds `skeleton.json` files with a README on the format, its invariants and its limits. Part 4 and Part 5 read other shapes than the native file; `--view part4` and `--view part5` write them (see Integration).

### Integration

The contract is `CONTRACT.md`: one JSON Schema per file Part 3 reads or writes (`contracts/`), the compatibility table and the version policy. `python3 -m part3 contract` prints the schemas and the table.

How another part plugs in:

1. Find your row in the compatibility table (`python3 -m part3 contract`).
2. Check your file: `python3 -m part3 doctor <file> --for part3|part4|part5`. It names the file's kind and version, validates it, and when a consumer would reject the file it gives the reason and the option that fixes it. Exit 0 valid, 1 valid but rejected by the `--for` consumer, 2 invalid or unknown.
3. Pick the output shape for your reader:
   ```
   # Part 4: simon.skeleton.v1 plus the keyframes file Part 4 reads beside it
   python3 -m part3 run --in pose3d.json --out part4/skeleton.json \
       --view part4 --keyframes part1/keyframes.json --keyframes-out part4/keyframes.json
   # Part 5 follower: simon.animation.v1
   python3 -m part3 run --in pose3d.json --out follower/skeleton.json --view part5 --fps 30
   # (--fps 30 puts the follower on a uniform 30 fps clock)
   # Everyone else: the native simon.skeleton/1 (default)
   python3 -m part3 run --in pose3d.json --out skeleton.json
   ```
4. Pick the body with `--body`, `PART3_BODY` or `part3.toml` (below). The default stays `simon-standard`, except that `--view part4` uses `part4-rig` because Part 4's animator rejects bone lengths more than 1 mm off its rig.
5. Test your reader on the conformance kit in `fixtures/conformance/`: golden input and output pairs for every profile and view, and Part 5 follower takes with labelled faults (`followers/labels.json`). `make check-3-contract` rebuilds every file byte for byte and checks each fault is still visible after normalization.

The `part4` view keeps the native frames and adds Part 4's keyframe block: Part 1's video-clock keys mapped onto a 30 fps index, local rotations on Part 4's rig (root `pelvis`, virtual joint `neck`) and `rest_offsets_m` from the chosen body. Part 4's rig moves the children of the pelvis, neck and nose together, while Part 3 keeps every bone's own direction, so each key pose is the forward kinematics of the fitted rotations and `rig.fit` reports how far it sits from the native frame (on the Part 2 squat, under 5 mm). Part 4 reproduces each key within its 1 mm rule by construction.

### Options

`python3 -m part3 run` takes these options besides `--in`, `--out` and `--flip`:

| Option | Values | What it does |
|---|---|---|
| `--body` | `simon-standard` (default), `part4-rig` (default for `--view part4`), `measured`, `file:<path>` | The body every frame is rebuilt on. `part4-rig` holds the lengths from Part 4's README (today equal to `simon-standard`). `measured` is the subject's own median lengths, left and right averaged, fixed for the clip. `file:` reads a `simon.body_profile/1` JSON. |
| `--stature` | 0.5 to 2.5 m | Scales the chosen body to this stature. |
| `--config` | path | A `part3.toml` (see `part3.toml.example`). |
| `--view` | `native` (default), `part4`, `part5` | The output shape. |
| `--keyframes` | a Part 1 or Part 4 `keyframes.json`, or `every:<n>` | The keys of the `part4` view. |
| `--keyframes-person` | id | The person of a Part 1 keyframes file (default the first). |
| `--keyframes-out` | path | Also writes the `simon.keyframes.v1` file of the `part4` view. |
| `--fps` | 1 to 240 | Resamples onto a uniform grid; each frame keeps the source clock and names the two input frames it came from. |
| `--input-fps` | number | The frame rate of an input without `t_ms`. |
| `--person` | id | Keeps this person instead of the one in the most frames. |
| `--all-people` | | Writes `person-<id>/skeleton.json` for every person into the `--out` folder, plus `people.json`. |

The body is chosen by the first of: `--body`, `PART3_BODY`, the config file (`--config`, else `PART3_CONFIG`, else `./part3.toml`), the `body=` argument of `part3.cli.process`, then the view's default (`part4-rig` for `--view part4`, `simon-standard` otherwise). Stature follows the same order with `--stature`, `PART3_STATURE`, `stature` in the config file and `stature=`. The output records the profile, its numbers, its source and the channel that chose it under `body`. When the view chose the profile, `body.reason` says why.

The input may also hold joints as `[x, y, z]` or `[x, y, z, conf]` arrays (or a list of 17 in canonical order), frames with `joints` and no `people`, joint names beyond the 17, frames without `frame`, or frames without `t_ms` (with `--input-fps` or a top-level `fps`). The output names each adapter that fired under `input.adapters`.

### Web app

`make demo` starts `python3 -m part3.server` (Python standard library only) on http://127.0.0.1:8733/. The page at `/` lets you run the real pipeline from the browser:

1. Pick an input: the Part 2 squat (a real clip), one of the synthetic takes, or your own `pose3d.json` (up to 16 MB, read in memory and never stored).
2. Pick the mirror setting `auto`, `on` or `off` (the same as `--flip`). Optionally pick a Body (Default for the View, `simon-standard`, `part4-rig`, `measured`), a Height, a View (`native`, `part4` with a key every 10 frames at 30 fps, `part5`) and a Frame rate (source, 30 or 60). Press Run.
3. The server calls the same `process` the command line uses and returns `skeleton.json` with its metrics: bone-length variation of the output and of the input, flips repaired, the mirror decision and the standard body height.
4. Input and output are drawn side by side in 3D. Drag to orbit, use the wheel to zoom, and use Front, Side, Top, Play and the frame slider. The Download button saves the exact bytes `python3 -m part3 run` writes for the same input and options.

A file that breaks the input contract gets an error naming the failing field, for example `pose3d.frames[0].people[0].joints.nose.conf`. The four-take agreement view is at `/agreement`.

The Compare page at `/compare` takes 2 to 6 inputs, each a sample or your own file with its own mirror setting. It runs them one at a time, aligns them by movement phase with the alignment `make check-3` uses, draws every skeleton in one 3D view (show or hide each, play them in phase) and shows a table: each input, then the joint-angle agreement p95 overall and per pair. The four synthetic takes give 7.420 degrees, the `make check-3` figure. Each input's file can be downloaded.

To serve the app under a path prefix, pass `--base`: `python3 -m part3.server --port 7120 --base /simon-part-3/`. Every URL in the page is relative, so it works under any prefix.

Limits: at most 2 runs at once, a 20 s run limit, a 16 MB upload limit and 3000 frames per Compare input. A request never selects a `file:` profile, and the server reads neither `PART3_BODY` nor `part3.toml`. The app has no accounts; put it behind your own access control if you expose it.
