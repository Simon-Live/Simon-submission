# Developing Simon Part 7

How to build, run and debug the stitched Simon app on a new host from a fresh clone of
`moalborati/simon-part-7-stitching-app`. The code is the authority; file and function names below are
where to look. Design background: [../design/README.md](../design/README.md).

## What the app is

A phone web app that stitches Parts 1 to 6 into one journey. Part 7 never imports another part's
code: it runs each part's published CLI from a pinned clone and passes files between them.

The journey has eight steps (`docs/design/specs/journey.md`):

| Step | Screen | What runs |
|---|---|---|
| 1 Open | `#/` catalog home | Part 6 `api/entries`, proxied under `catalog/` |
| 2 Record | `#/record`, then `#/job/<id>` | trainer job: Part 1 keyframes, Part 2 pose, Part 3 `--view part4`, Part 4 animate, Part 6 `import` |
| 3 Cloud | `#/watch/<id>` | the Part 6 entry and its video |
| 4 Follow | `#/follow/<id>` | Part 6 follow hand-off, capture and upload |
| 5 Pipeline | `#/job/<id>` | follow job: Part 2, Part 3 `--view part5 --fps 30`, Part 5 `analyse --replay` |
| 6 Compare | `#/result/<job>` | Part 5 `replay.json` in the 3D compare view |
| 7 Feedback | `#/result/<job>` | Part 5 timed faults, phrased live by Muse Spark or by template |
| 8 Score | `#/result/<job>` | Part 5 `score` (0 to 100, grade A to F) |

`#/result/fixture` shows the result screen on a committed Part 5 example and needs no GPU.

## Architecture

| Piece | Code | What it does |
|---|---|---|
| CLI | `part7/cli.py` | `python -m part7 pin, setup-parts, doctor-parts, videos, chain, serve, check` |
| HTTP server | `part7/server.py` | stdlib `ThreadingHTTPServer` on 127.0.0.1 only; serves `web/`, the `api/` routes and the Part 6 proxy |
| Job queue | `part7/jobs.py` | `SIMON7_GPU_WORKERS` threads (default 2), at most 8 jobs queued or running, one record per job on disk |
| Jobs | `part7/processor.py`, `part7/chain.py` | trainer and follow jobs: normalize the upload with ffmpeg, then run the part chain with a doctor check on every hand-off |
| Part adapters | `part7/parts/p1_keyframes.py` to `p6_catalog.py` | the exact argv for each part, run through `part7/runner.py` (own process group, timeout, key redaction in logs) |
| GPU admission | `part7/gpu_lock.py` | Part 2's file lock plus a wait for 12288 MiB free (`nvidia-smi`); gives up after 30 min |
| Pins | `part7/pins.py`, `parts.lock.json` | one commit per part; clones under `<state>/parts/<n>@<sha12>` |
| Part 6 child | `part7/parts/p6_catalog.py` | `python3 -m part6 serve` on a free local port; Part 7 proxies `catalog/` to it |
| People and groups | `part7/people.py`, `people_routes.py`, `group.py` | choose one person in a clip of several, or analyse a group |
| Web app | `web/` | plain ES modules, no build step; `web/vendor/` holds the third-party files |

### The parts harness

- `parts.lock.json` names each part's repo and 40-character commit (`sha`). Part 2 also records
  `entry_point` (`backend` when its `run --help` offers `--backend`).
- `python -m part7 pin --materialize` (`make pin`) clones each pinned commit, detached, to
  `~/.local/state/simon-part-7/parts/<n>@<sha12>`. A clone already there must be at that commit or
  the command stops. Git LFS files are not fetched (`GIT_LFS_SKIP_SMUDGE=1`).
- `python -m part7 setup-parts` (`make setup-parts`) runs each part's own setup in its clone:
  Part 1 `make .venv/.installed`, Part 2 `uv sync`, Part 3 a `.venv` plus `pip install -r
  requirements.txt`, Part 5 `uv sync`; Parts 4 and 6 need none and get a contract check instead. It
  also probes Part 2's GPU venv (below) for CUDA and notes when the venv is missing.
- `python -m part7 doctor-parts` runs each part's contract or help command at its pin.

## Prerequisites

- Linux with `git`, `make` and Python 3.12 or newer (`pyproject.toml`).
- [uv](https://docs.astral.sh/uv/) on `PATH` (the Makefile and the runner add `~/.local/bin`).
- `ffmpeg` and `ffprobe` (every upload is normalized to H.264 MP4 and may be trimmed).
- Node 22 or newer, only for the browser and unit tests.
- An NVIDIA GPU with CUDA and `nvidia-smi`. Each Part 2 call waits for 12288 MiB of free GPU memory;
  two jobs run at once only when free memory covers both. The timings below were measured on an
  RTX 5090 (32 GiB).
- Part 2's GPU environment. The server always asks Part 2 for `--backend gpu` and runs it with
  `~/.local/state/simon-part-2/venvs/gpu-cu128/bin/python` when that exists
  (`SIMON7_PART2_GPU_VENV` overrides the path); without it, Part 2 runs through its own `uv`
  environment. Build it once from the Part 2 clone:

  ```bash
  cd ~/.local/state/simon-part-7/parts/2@<sha12>   # after `make pin`
  make setup-gpu    # bash envs/gpu-cu128/setup.sh
  make smoke-gpu    # one fixture frame on the GPU
  ```

  The script installs torch with CUDA 12.8 wheels into a uv-managed CPython 3.12 venv, clones SAM 3D
  Body at the commit Part 2 pins, downloads the weights (SAM 3D Body, MoGe-2, ViTDet) and checks
  their SHA-256. It tries to build detectron2 for 45 minutes at most and falls back to the rtmlib
  person detector when the build fails. It writes nothing inside the repo. Part 2's `README.md` and
  `CONTRACT.md` at the pin are the reference.

## Keys

Part 7 reads keys from files, one file per key, named after the key, in
`~/.config/firm/operator-keys/` (override with `SIMON7_KEYS_DIR`). Give the directory mode 700
and each file mode 600. Values never appear in a log: `part7/runner.py` replaces them with
`<redacted>`.

| Key | Used for | Who reads it, and how |
|---|---|---|
| `MODEL_API_KEY` | Meta Model API: Part 1 keyframes and Part 2's `api-sam31` tracker | Part 7 checks the file before calling Part 1 or asking for `api-sam31`, then writes it to `<part 1 clone>/.env` (mode 600) for the length of the Part 1 call only. Part 2 reads its own key file (`PART2_KEY_DIR`, same default directory), the environment variable second. |
| `HF_TOKEN` | the gated `facebook/sam3.1` weights for Part 2's `local-sam31` tracker | Part 2 only, from `PART2_KEY_DIR` or the environment variable |
| `BASETEN_API_KEY` | Muse Spark phrasing of fault text in Part 5 | Part 5 only, from `~/.config/firm/operator-keys/BASETEN_API_KEY` or the file named by `PART5_BASETEN_KEY_FILE`; it logs usage in `~/.simon/baseten_usage.jsonl` |

Environment variables alone are not enough: Part 7 and Part 5 only look at files. Every key is
optional. Without `MODEL_API_KEY` the trainer job skips Part 1 (Part 3 then picks keyframes every 10
frames) and tracking uses Part 2's other trackers. Part 2's default tracker order is `local-sam31`,
`api-sam31`, then `local-open`, which needs no key. Without `BASETEN_API_KEY` there is no live
phrasing; set `SIMON7_PHRASING=template` to ask for template text from the start.

## From a fresh clone to the running app

1. Clone and install Part 7's own environment (it has no runtime dependencies; pytest for dev):
   ```bash
   git clone https://github.com/moalborati/simon-part-7-stitching-app.git
   cd simon-part-7-stitching-app
   make setup                 # uv sync
   ```
2. Clone Parts 1 to 6 at the pinned commits: `make pin` (`uv run python -m part7 pin --materialize`).
3. Set up each part: `make setup-parts`. It exits 1 and prints the failing part when a setup fails.
4. Build Part 2's GPU venv (Prerequisites above) and put the key files in place (Keys above).
5. Start the server:
   ```bash
   make dev                   # bin/dev.sh: 127.0.0.1, port SIMON7_PORT or 8727, base path /
   ```
   or directly:
   ```bash
   uv run python -m part7 serve --host 127.0.0.1 --port 8727 --base-path / [--state <dir>] [--follow-url <template>]
   ```
   `bin/dev.sh` passes extra arguments on to `serve`. Flags:
   - `--host` must be `127.0.0.1`, `localhost` or `::1`; anything else exits 2.
   - `--port` default 8727.
   - `--base-path` default `/` (or `STAGING_BASE_PATH` when set). Behind a reverse proxy on a path,
     use that path, for example `/simon-part-7/`.
   - `--state` default `~/.local/state/simon-part-7/dev`.
   - `--follow-url` the link Part 6 gives for "follow this entry", with `{id}`; on a local run it
     defaults to `http://<host>:<port><base>#/follow/{id}`.
6. Open `http://127.0.0.1:8727/`. The server prints `serving http://...` once Part 6 answers. If
   Part 6 does not start, it exits 1; read `<state>/part6.log`.

To reach it from a phone, put an HTTPS tunnel or reverse proxy in front of port 8727: the camera
needs a secure origin.

Optional, for the end-to-end chain and the done check:

```bash
make videos     # download the openly licensed test clips listed in videos/manifest.json
make chain      # run the trainer and follower clips through the parts, outside the server
make check-7    # the done check: one metrics JSON, exit 0 when every gate passes
```

## Switches

All read from the environment (`part7/config.py`, `part7/quota.py`, `part7/server.py`,
`part7/parts/p2_pose.py`).

| Variable | Default | Effect |
|---|---|---|
| `SIMON7_PORT` | 8727 | port used by `bin/dev.sh` |
| `SIMON7_PHRASING` | `live` | `live` asks Part 5 for `--phrasing muse-spark --live`; `template` for template text. Tests and `make check-7` use `template`. |
| `SIMON7_GPU_WORKERS` | 2 | job threads; Part 2 calls still wait for free GPU memory |
| `SIMON7_P2_WARM_WORKERS` | off | `1` starts one Part 2 `serve-worker` per job thread, keeping the 3D model loaded. Off because on the staging host the two warm workers held about 20 GB and follow-side tracking stalled behind them for 6 to 12 minutes. |
| `SIMON7_PART1_TIMEOUT_S` | 90 | seconds the trainer job waits for Part 1; past it, the job falls back to keyframes every 10 frames instead of failing |
| `SIMON7_LIMITS` | off | `on` enforces the daily caps (`SIMON7_DAILY_GPU` default 40 jobs, `SIMON7_DAILY_TRAINER` default 10) and the per-visitor caps (10 GPU and 3 trainer jobs a day). Jobs are counted either way under `<state>/quota/`. |
| `SIMON7_STATE_DIR` | `~/.local/state/simon-part-7` | root for `parts/`, `videos/`, `dev/`, `check/` |
| `SIMON7_KEYS_DIR` | `~/.config/firm/operator-keys` | where Part 7 looks for key files |
| `SIMON7_PART2_GPU_VENV` | `~/.local/state/simon-part-2/venvs/gpu-cu128` | Part 2's GPU venv |
| `SIMON7_GPU_LOCK_PATH` | `~/.local/state/simon-part-2/gpu.lock` | the GPU lock shared with Part 2 |
| `SIMON7_LOCK_PATH` | `parts.lock.json` in the repo | another lock file (tests) |
| `SIMON7_VIDEOS_MANIFEST` | `videos/manifest.json` | another test-video manifest |
| `STAGING_BASE_PATH` | unset | default `--base-path`; when set, no default `--follow-url` is passed to Part 6 |

Part 6 runs with every `SIMON7_*` variable removed from its environment.

## Where job state lives

Under the server state directory (`~/.local/state/simon-part-7/dev` for `make dev`):

```
<state>/
  catalog/                 Part 6's catalog (entries, videos)
  part6.log                Part 6 child output
  part7.log                Part 7's own decisions and failures for every job (also on stderr)
  uploads/<upload id>/     raw uploads, removed after 7 days
  quota/<YYYY-MM-DD>.json  job counters
  jobs/<job id>/
    job.json               the job record (below)
    steps/error.log        traceback of an unexpected error, redacted
    steps/part7.log        this job's lines of part7.log: clip in/out (size, fps, length, trim), why it failed
    work/                  video.mp4 (normalized), trimmed.mp4, expected.json
      trainer/ or follower/
        steps/*.log        one log per part call, written while it runs; part7.log there says whether Part 1
                           got a cropped copy (and the sizes) and why its key frames fell back to Part 3
        part2/, part2_track/, skeleton or follower JSON, analysis.json, replay.json
```

Job folders are removed 7 days after their last change. `job.json` holds `id`, `kind` (`trainer`,
`follow`, `people`, `group`), `status`, `stage`, `stages` (every stage reached), `note`, `reason`,
`error`, `result` (paths under `api/results/<id>/`) and the `created_at`, `started_at`,
`finished_at` times. `GET api/jobs/<id>` returns the same record plus `queue_position`.

Step logs are named after the call: `part1.log`, `part2.log`, `part2_track.log`,
`part3_part4.log`, `part3_part5.log`, `part4_animate.log`, `part5_analyse.log`, `part6_import.log`,
and a `*_doctor_*` or `*_validate_*` log for each hand-off check. Each log holds the part's own output, redacted.

Start with `steps/part7.log`: it holds what Part 7 itself decided between the parts (the trim it applied,
the crop given to Part 1, every fallback) and the cause of a failure, which the visitor's reason leaves out.
A trim the server rejected (HTTP 400) has no job; it is logged in `<state>/part7.log` with the numbers.

### Debugging a job

| `status` | Meaning | Look at |
|---|---|---|
| `queued` | waiting for a job thread | `queue_position`; at 8 queued or running, new jobs get HTTP 503 "The app is busy" |
| `running` | `stage` is the current step (`upload`, `keyframes`, `pose`, `skeleton`, `animation`, `catalog`, `analyse`) | the newest log in `work/*/steps/` |
| `done` | finished; a follow job always ends with an analysis | `work/follower/analysis.json` and its `warnings` |
| `failed` | `error` is `failed:<stage>: <reason>`; the reason shown to the visitor has paths, hosts and tokens stripped | the stage's log in `work/*/steps/`, then `steps/error.log` |

Common failure reasons:

- `the GPU is busy, try again later`: Part 2 waited 30 min for the lock and 12288 MiB of free
  memory. Check `nvidia-smi` and the lock holder.
- `the server restarted`: the server stopped while the job was queued or running; on start every
  such job is marked failed.
- `... was rejected by part <n>`: a doctor check refused a hand-off file; the matching
  `*_doctor_*.log` says why.
- `the step failed unexpectedly`: an exception in Part 7; the traceback is in `steps/error.log`.
- A part that times out (Part 2 20 min, Parts 3 to 5 3 min, doctors 1 min; Part 1 in a trainer job
  `SIMON7_PART1_TIMEOUT_S`, and its timeout is a fallback, not a failure) gets SIGTERM, then SIGKILL
  10 s later; its log ends with `part <n> timed out after ...`.

### Warnings in a finished analysis

From Part 5 schema 1.4.0 a take is never refused. A problem with the take becomes a warning in
`analysis.json` (`warnings: [{code, text}]`), the score is capped at 59 (grade F) and
`score.capped_by` names the codes. The result screen shows each warning's text beside the F.

| Code | Written by | Meaning | What to check |
|---|---|---|---|
| `low_match` | Part 5 | the take does not match the expected movement well (`match.quality` is `low`); faults carry `confidence: "low"` | the follower did a different movement or a different part of it; compare `match` in `analysis.json` |
| `moving_part_out_of_frame` | Part 5 | the body part the trainer's example moves is out of frame | the framing; Part 5 gets the trainer's `skeleton.json` as `--expected-visibility` |
| `not_enough_visible` | Part 5 | too little of the body is in frame to score | the framing; `part3_part5.log` and the follower skeleton |
| `no_usable_measures` | Part 5, or Part 7 when Part 3 or Part 5 could not run on the take | nothing could be measured against the trainer | `part3_part5.log` and `part5_analyse.log`; a Part 7 analysis has `"source": "part7"` and the reason in `warnings[0].reason` |
| `no_person` | Part 7 | Part 2 found no person | `part2.log` and `part2_track.log` |

Part 7 writes its own analysis (status `ok`, score 0, grade F) only when the failure is about the
take. A busy GPU, a missing tool or a timeout stays a failed job (`part7/chain.py`,
`_is_analysis_case`).

## Running the tests

```bash
make test                                    # uv run pytest -q, everything under tests/
node --test tests/part7/*.unit.test.mjs      # pure functions of the web app
```

The browser checks under `tests/part7/*.browser.mjs` and the drives `tests/part7/drive_*.mjs` use
Playwright 1.61.1 against local harness pages or `tests/part7/fake_api.py`; they need no GPU.
Install Playwright once in the repo root, then run any of them with Node:

```bash
npm install --no-save playwright@1.61.1 && npx playwright install chromium
node tests/part7/result.browser.mjs
node tests/part7/drive_web.mjs /tmp/simon-shots/web    # screenshots go to the folder given
```

When Playwright lives elsewhere, set `PLAYWRIGHT_DIR`. The scripts disagree on what it names: the
header comment of each script says whether it is a `node_modules` folder or the
`node_modules/playwright` folder. `trim.browser.mjs` also needs ffmpeg.

## Driving the whole journey by hand

The development workspace drives all eight steps with a Playwright script that is not published. The
same journey by hand against a local server:

1. `make dev`, then open `http://127.0.0.1:8727/` in Chromium at a phone size (412x915 is what the
   tests use).
2. Record (or upload) a trainer take of 1 to 60 s, name it and save; follow `#/job/<id>` to `done`.
3. Open the new entry (`#/watch/<id>`), then Follow it and record or upload a follower take.
4. On `#/result/<job>`: rotate the 3D compare, tap a fault, read the score.

For a camera without a person in front of it, make a y4m from a clip and give it to Chromium as
the fake camera:

```bash
ffmpeg -y -i clip.mp4 -t 12 -vf "scale=640:-2,fps=30" -pix_fmt yuv420p take.y4m
chromium --use-fake-ui-for-media-stream --use-fake-device-for-media-stream \
  --use-file-for-fake-video-capture=take.y4m http://127.0.0.1:8727/
```

The API underneath, for scripting: `POST api/uploads` (raw body, at most 95,000,000 bytes), then
`POST api/trainer` or `POST api/follow` with the upload id, then poll `GET api/jobs/<id>` and read
`GET api/results/<id>/analysis.json`. The request fields are in
`docs/design/specs/app.md` and `part7/server.py`.

## Known issues and limits

- Warm Part 2 workers are off (`SIMON7_P2_WARM_WORKERS`, above). Each follow job loads the 3D model
  again, about 20 to 35 s per Part 2 run according to Part 2's contract.
- Orphaned processes: Part 7 starts every part, the Part 6 child and any warm worker in its own
  process group. A clean stop (Ctrl-C or SIGTERM) stops Part 6 and the workers. A SIGKILL or crash
  leaves them running, including a Part 2 run that still holds GPU memory. Before restarting, look
  with `pgrep -af 'part6 serve|part2'`.
- The staging deployment used a Cloudflare quick tunnel. Its URL changes on every restart, so this
  repo keeps no link to it; use your own tunnel or a named one.
- Partial-body framing: when the body part the trainer moves, or too much of the body, is out of the
  frame, the take is still analysed but gets a warning and an F. The recorder's hint says: "Step back
  until your whole body fits, or at least everything that moves."
- Timings per job, measured on the staging host (RTX 5090) on 2026-10-30, `started_at` to
  `finished_at` of finished jobs:

  | Kind | Jobs | Median | Fastest | Slowest |
  |---|---|---|---|---|
  | trainer | 9 | 83 s | 73 s | 899 s |
  | follow | 16 | 94 s | 72 s | 603 s |
  | people | 15 | 29 s | 15 s | 149 s |

  Queue wait is not included.
- Uploads: at most 95,000,000 bytes and 90 s raw; the clip sent to the parts is 1 to 60 s after
  trimming.

## Re-pinning to newer parts

```bash
make repin       # pin --update --materialize, setup-parts, then make chain
```

Or one part at a time:

```bash
uv run python -m part7 pin --update 5 --materialize   # re-read Part 5's upstream main
uv run python -m part7 setup-parts
uv run python -m part7 doctor-parts
```

`pin --update` with no part names updates all six. It reads `refs/heads/main` of each repo with
`git ls-remote`, writes the new commit to `parts.lock.json` and clones it next to the old clone
(old clones stay under `<state>/parts/` until removed). When a local checkout of a part exists at
`~/simon-part-<n>`, its last `STATUS:` line is copied into the lock's `status` field. Restart the
server afterwards: it reads the lock at start. Then run `make test`, `make chain` and `make check-7`,
and commit `parts.lock.json`.
