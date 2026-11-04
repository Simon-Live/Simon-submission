# Developing Part 3

How to build, run, test and debug Part 3 from a fresh clone. `README.md` describes what the part does and every option; `CONTRACT.md` is the integration contract. This page covers the work around them.

## Setup

Prerequisites: Python 3.11 or later (the config reader uses `tomllib`) and git. Node is optional: `tests/part3/test_web_node.py` runs page code under node and skips those checks without it. No network, model, GPU or key is needed at any point.

```
git clone https://github.com/Simon-Live/Simon-submission.git
cd Simon-submission/modules/part-3
python3 -m venv .venv && . .venv/bin/activate
make setup          # pip install -r requirements.txt (numpy 2.4.6, pytest 9.1.0)
make check-3        # prints the metrics JSON; exit 0 means the clone works
```

On a system Python that refuses pip installs (PEP 668), the virtualenv above is required. Every command below assumes it is active, or use `PYTHON=.venv/bin/python make ...`.

## Keys and configuration

Part 3 reads no key: no `MODEL_API_KEY`, `HF_TOKEN` or `BASETEN_API_KEY`, and no `.env` file. It reads these environment variables, all optional:

| Variable | Effect |
|---|---|
| `PART3_BODY` | Body profile when `--body` is not given (`simon-standard`, `part4-rig`, `measured`, `file:<path>`). |
| `PART3_STATURE` | Stature in metres when `--stature` is not given. |
| `PART3_CONFIG` | Path of a `part3.toml` when `--config` is not given; otherwise `./part3.toml` is read when it exists. |
| `PART3_KEYFRAMES_DENSIFY` | `every:<n>` or `off` when `--keyframes-densify` is not given (`--view part4` with a keyframes file only). |
| `PART3_UP_FALLBACK` | `all_frames` makes a clip with fewer than 5 standing frames take "up" from the mean feet-to-shoulders line over every frame instead of the input's own `y`. |

`part3.toml.example` documents the config file. The first channel set wins: flag, environment, config file, the Python API argument, the default. The output records which channel won under `body.selected_by` and `timeline.densify.selected_by`.

A stray `PART3_*` variable or a `part3.toml` in the working directory changes results silently in your shell; the conformance kit clears both for its own runs, so `make check-3-contract` is unaffected.

## Commands

```
# Native skeleton
python3 -m part3 run --in fixtures/input/part2-single/pose3d.json --out out/skeleton.json

# What Part 7 runs for a trainer (Part 4 shape, Part 1 keys, densified)
python3 -m part3 run --in pose3d.json --out work/skeleton.json --view part4 \
    --keyframes keyframes.json --keyframes-densify every:10 --keyframes-out work/keyframes.json

# What Part 7 runs for a follower (Part 5 shape on a 30 fps clock)
python3 -m part3 run --in pose3d.json --out work/follower.json --view part5 --fps 30

# Every person in the clip
python3 -m part3 run --in pose3d.json --out work/people --all-people

# Contract and file checks
python3 -m part3 contract [--json] [--schema skeleton]
python3 -m part3 doctor work/skeleton.json --for part4      # 0 accepted, 1 consumer would reject, 2 invalid
python3 -m part3.schema out/skeleton.json                   # validates a native skeleton

# Web app on http://127.0.0.1:8733/ (background); make demo-stop ends it
make demo
python3 -m part3.server --port 7120 --base /simon-part-3/   # foreground, under a path prefix

# Regenerate the synthetic takes and the demo data
python3 -m part3.synth --out fixtures/input/synthetic-4take
make demo-data
```

`run` creates the folder of `--out` (and of `--keyframes-out`) when it does not exist. Exit codes of `run`: 0 written, 2 the input or an option breaks the contract (the message names the field or option; nothing is written), 1 the output is not writable. Files are written to a temporary name beside the target and renamed only when every file of the run is complete, so a failed run leaves none of its files behind.

## Done-checks

| Command | What it measures | Gates |
|---|---|---|
| `make check-3` | `python3 -m part3.metrics`: bone-length variation of the outputs, left/right flips, joint-angle agreement p95 across the four synthetic takes, and a negative control (an arm raise must disagree). | Exit 0 only when all four pass: variation under 0.02, 0 flips, agreement p95 at most 10 degrees, control p95 above 10 degrees. `"data_source": "synthetic"` (see Limits). |
| `make check-3-contract` | `python3 -m part3.conformance check`: validates every file in `fixtures/conformance/` against `contracts/`, rebuilds every golden file byte for byte from its recorded command, checks every labelled follower fault is still visible after normalization and every correct take stays clean. | Exit 0 only when `failures` is 0. A change that alters any output byte fails here first. |
| `make test` | pytest over `tests/part3` (plus `tests/staging` and `tests/neighbour` when present; they are not in this repository). | All tests pass. |

Both checks print one JSON document on stdout. `make check-3` runs in under a second and `make check-3-contract` in a few seconds; `make test` takes about a minute.

When a change is meant to alter output, rebuild the kit with `python3 -m part3.conformance build`, review the diff under `fixtures/conformance/`, then rerun `make check-3-contract`.

## Tests

`tests/part3/` holds the unit and acceptance tests, one file per module or feature (`test_cli.py`, `test_view_part4.py`, `test_keyframes_densify.py`, `test_cli_out_dir.py` and so on), with shared helpers in the `*kit.py` and `*rules.py` files and inputs in `tests/part3/data/`. Run one file or one test:

```
python3 -m pytest tests/part3/test_keyframes_densify.py -q
python3 -m pytest "tests/part3/test_server.py::test_health_answers_and_everything_else_is_busy_while_sixteen_clients_stall" -q
```

`part4rules.py` and `part5rules.py` restate the neighbours' acceptance rules so the tests catch a file Part 4 or Part 5 would refuse.

## Debugging

- **Exit 2 on `run`.** The message is one line naming the field path (for example `pose3d.frames[0].people[0].joints.nose.conf`) or the option. Run `python3 -m part3 doctor <input> --for part3` for the file's kind and the first failure. Inputs with joints as arrays, without `people`, without `frame` or without `t_ms` are adapted; the output lists the adapters that fired under `input.adapters`. A file without `t_ms` and without a top-level `fps` needs `--input-fps`.
- **`--person` exits 2.** The id is absent; the message lists the ids present.
- **The `part4` view refuses a clip** with a message such as `left_shoulder turns 329.6 degrees between keys 30 and 40`. Part 4 rejects a joint that turns over 180 degrees between neighbouring keys, so Part 3 refuses to write it. Add keys between the two named ones: a smaller `every:<n>`, or `--keyframes-densify every:<n>` with a Part 1 file. Part 7 retries once with `every:5`.
- **Keys missing from a `part4` file.** A key that lands where the person is absent is dropped and listed in `timeline.dropped`. Densified fillers are named `key_<index>`; `timeline.densify` records `every`, `selected_by` and `added`.
- **`rig.fit` in a `part4` file** is how far the snapped key pose sits from the native frame (on the Part 2 squat, under 5 mm). It is a report, not an error.
- **Odd facing on floor work.** A clip with fewer than 5 standing frames takes "up" from the input and records `frame.up_source: input_up`. Try `PART3_UP_FALLBACK=all_frames` to compare.
- **Up on a one-legged exercise.** When a straight leg is raised (leg abduction), up comes from the frames with both feet down and `frame.up_source` says `two_footed_frames` (TICKET-038).
- **Up on a plank or push-up.** Straight knees pass the standing test while the body lies or leans. Run with `--floor-work` for floor exercises: a standing-frame up more than 30 degrees from the input's up then uses the input's up and records `frame.up_source: input_up_floor_work` (TICKET-040).
- **Left and right swapped for the whole clip.** The recording is mirrored (selfie mode). Use `--flip on`, or set `"mirrored": true` in the input; the output explains the decision under `mirror`.
- **Unexpected bone lengths.** Read `body.profile`, `body.selected_by` and `body.reason`: a `PART3_BODY`, `PART3_STATURE` or `./part3.toml` you forgot may have chosen them. `--view part4` defaults to `part4-rig`.
- **`make demo` says the port is busy.** Something holds 8733; `make demo-stop` stops a demo this checkout started (pid in `.demo.pid`, log in `out/demo.log`).
- **Web app errors.** The server answers with a plain message and a code; the limits are 2 runs at once, 20 s per run, 16 MB per upload and 3000 frames per Compare input. The server ignores `PART3_BODY` and `part3.toml` and never accepts a `file:` profile.

## How Part 7 calls Part 3

Part 7 runs Part 3 from its own clone, as a separate process, through files and the command line only:

1. Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, then `python3 -m part3 contract --json` as a smoke check.
2. Trainer: `run --view part4 --keyframes <Part 1 keyframes.json> --keyframes-densify every:10 --keyframes-out <dir>/keyframes.json --body simon-standard`. On a Part 1 fallback it passes `--keyframes every:10` without densify; on the 180 degree refusal it retries once with `every:5`.
3. Follower: `run --view part5 --fps 30 --body simon-standard`, so both sides use one body.
4. Check: `doctor <skeleton.json> --for part4` and `doctor <follower.json> --for part5`.

Part 7 relies on the exit codes of `run` (0, 1, 2) and of `doctor` (0, 1, 2). Changing either, a schema in `contracts/`, or a row of `contracts/compatibility.json` changes the contract: follow the version policy in `CONTRACT.md` and update the compatibility table (`python3 -m part3 contract` prints it).

## Design records

`docs/design/README.md` indexes copies of the specs and decision records behind this code.

## Known issues and limits

- The 4-angle agreement is measured on synthetic takes (the real Part 2 squat rendered from four angles with Part 2-like errors); no multi-phone recording exists.
- With the default body the bone lengths are the standard body's, not the performer's (`person.measured_bone_lengths_m` holds those; `--body measured` uses them).
- Joints that Part 2 extrapolated outside the image carry `conf` 0.3 and follow the input direction.
- A whole-body turn on the spot is not represented: Part 2 removes rotation per frame.
- Mirroring is corrected only with `--flip on` or `"mirrored": true` in the input.
- One person per output unless `--all-people`; the choice is the id seen in most frames.
- The `part4` view snaps key poses to Part 4's rig, which moves pelvis, neck and nose children rigidly; `rig.fit` reports the residual.
- `test_server.py::test_health_answers_and_everything_else_is_busy_while_sixteen_clients_stall` is timing-sensitive: it failed once in a full run on a heavily loaded host and passed when rerun alone.
