# Developing Simon Part 7

How to build, run and debug the stitched Simon app on a new host from a fresh clone of
`moalborati/simon-part-7-stitching-app`. The code is the authority; file and function names below are
where to look. Design background: [../design/README.md](../design/README.md).

## What the app is

A phone web app that stitches Parts 1 to 6 into one journey. Part 7 never imports another part's
code: it runs each part's published CLI from its folder under `modules/` and passes files between them.

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
| CLI | `part7/cli.py` | `python -m part7 setup-parts, parts-status, doctor-parts, videos, chain, serve, check` |
| HTTP server | `part7/server.py` | stdlib `ThreadingHTTPServer` on 127.0.0.1 only; serves `web/`, the `api/` routes and the Part 6 proxy |
| Job queue | `part7/jobs.py` | `SIMON7_GPU_WORKERS` threads (default 2), at most 8 jobs queued or running, one record per job on disk |
| Jobs | `part7/processor.py`, `part7/chain.py` | trainer and follow jobs: normalize the upload with ffmpeg, then run the part chain with a doctor check on every hand-off |
| Part adapters | `part7/parts/p1_keyframes.py` to `p6_catalog.py` | the exact argv for each part, run through `part7/runner.py` (own process group, timeout, key redaction in logs) |
| GPU admission | `part7/gpu_lock.py` | Part 2's file lock plus a wait for 12288 MiB free (`nvidia-smi`); gives up after 30 min |
| Part modules | `modules/part-1` to `modules/part-6`, `modules/PINS.json` | folders of this repo, merged with their history (ADR-0008); PINS.json names each part repo and commit they came from |
| Part 6 child | `part7/parts/p6_catalog.py` | `python3 -m part6 serve` on a free local port; Part 7 proxies `catalog/` to it |
| People and groups | `part7/people.py`, `people_routes.py`, `group.py` | choose one person in a clip of several, or analyse a group |
| Web app | `web/` | plain ES modules, no build step; `web/vendor/` holds the third-party files |

### The parts harness

- Parts 1 to 6 are folders of this repo (ADR-0008): a plain `git clone` has them all. `modules/PINS.json` names the
  part repo and commit each was merged from. `make parts` runs `setup-parts`. A staging build can still serve from a
  module tree whose parts are checkouts of their own (`SIMON7_MODULES_DIR`); `parts-status` reads those with git.
- `python -m part7 parts-status [--check-remote]` prints each part's `path`, `sha`, `short`, `url`,
  `branch` and `remote_sha` as JSON. With `--check-remote` it exits 3 when any part's remote `main`
  differs from the checked-out sha and 0 when all are current (staging's `stale.sh` uses it).
- `python -m part7 setup-parts` (run by `make parts`) runs each part's own setup in its module:
  Part 1 `make .venv/.installed`, Part 2 `uv sync`, Part 3 a `.venv` plus `pip install -r
  requirements.txt`, Part 5 `uv sync`; Parts 4 and 6 need none and get a contract check instead. It
  also probes Part 2's GPU venv (below) for CUDA and notes when the venv is missing.
- `python -m part7 doctor-parts` runs each part's contract or help command at its checked-out commit.

## Prerequisites

- Linux with `git`, `make` and Python 3.12 or newer (`pyproject.toml`).
- [uv](https://docs.astral.sh/uv/) on `PATH` (the Makefile and the runner add `~/.local/bin`).
- `ffmpeg` and `ffprobe` 5.1 or newer (every upload is normalized to H.264 MP4 and may be trimmed; a clip
  with a missing or unbelievable frame rate is re-timed with `-fps_mode cfr`, which first shipped in 5.1).
  `ffmpeg -version` prints the version.
- Node 22 or newer, only for the browser and unit tests.
- An NVIDIA GPU with CUDA and `nvidia-smi`. Each Part 2 call waits for 12288 MiB of free GPU memory;
  two jobs run at once only when free memory covers both. The timings below were measured on an
  RTX 5090 (32 GiB).
- Part 2's GPU environment. The server always asks Part 2 for `--backend gpu` and runs it with
  `~/.local/state/simon-part-2/venvs/gpu-cu128/bin/python` when that exists
  (`SIMON7_PART2_GPU_VENV` overrides the path); without it, Part 2 runs through its own `uv`
  environment. Build it once from `modules/part-2`:

  ```bash
  cd modules/part-2   # after `make parts`
  make setup-gpu    # bash envs/gpu-cu128/setup.sh
  make smoke-gpu    # one fixture frame on the GPU
  ```

  The script installs torch with CUDA 12.8 wheels into a uv-managed CPython 3.12 venv, clones SAM 3D
  Body at the commit Part 2 names, downloads the weights (SAM 3D Body, MoGe-2, ViTDet) and checks
  their SHA-256. It tries to build detectron2 for 45 minutes at most and falls back to the rtmlib
  person detector when the build fails. It writes nothing inside the repo. Part 2's `README.md` and
  `CONTRACT.md` in `modules/part-2` are the reference.

## Keys

Part 7 reads keys from files, one file per key, named after the key, in
`~/.config/simon/keys/` (override with `SIMON7_KEYS_DIR`). Give the directory mode 700
and each file mode 600. Values never appear in a log: `part7/runner.py` replaces them with
`<redacted>`.

| Key | Used for | Who reads it, and how |
|---|---|---|
| `MODEL_API_KEY` | Meta Model API: Part 1 keyframes and Part 2's `api-sam31` tracker | Part 7 checks the file before calling Part 1 or asking for `api-sam31`, then writes it to `<modules/part-1>/.env` (mode 600) for the length of the Part 1 call only. Part 2 reads its own key file (`PART2_KEY_DIR`, same default directory), the environment variable second. |
| `HF_TOKEN` | the gated `facebook/sam3.1` weights for Part 2's `local-sam31` tracker | Part 2 only, from `PART2_KEY_DIR` or the environment variable |
| `BASETEN_API_KEY` | Muse Spark phrasing of fault text in Part 5 | Part 5 only, from `~/.config/simon/keys/BASETEN_API_KEY` or the file named by `PART5_BASETEN_KEY_FILE`; it logs usage in `~/.simon/baseten_usage.jsonl` |

Environment variables alone are not enough: Part 7 and Part 5 only look at files. Every key is
optional. Without `MODEL_API_KEY` the trainer job skips Part 1 (Part 3 then picks keyframes every 10
frames) and tracking uses Part 2's other trackers. Part 2's default tracker order is `local-sam31`,
`api-sam31`, then `local-open`, which needs no key. Without `BASETEN_API_KEY` there is no live
phrasing; set `SIMON7_PHRASING=template` to ask for template text from the start.

## From a fresh clone to the running app

1. Clone and install Part 7's own environment (it has no runtime dependencies; pytest for dev):
   ```bash
   git clone https://github.com/Simon-Live/Simon-submission.git
   cd Simon-submission
   make setup                 # uv sync
   ```
2. Bring Parts 1 to 6 to the latest `main` and set each one up: `make parts`. It exits non-zero and
   names the part when one fails. (A clone made without `--recursive` needs this step to fill `modules/`.)
3. Check what is checked out: `uv run python -m part7 parts-status`.
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
| `SIMON7_P2_WARM_WORKERS` | unset: 1 on staging, 0 elsewhere | Unset, only the staging server (`SIMON7_STAGING=1` or the staging state folder, both set by `staging/env.sh`) starts the worker; lane and dev servers start none. `1` keeps ONE Part 2 `serve-worker` loaded for `part2 run` (the 3D step) only; `track` stays in-process. A `run` that cannot lease the worker within 5 s (`SIMON7_P2_LEASE_WAIT_S`) runs in-process. `0` turns it off. Measurements and the history of the 2026-10-30 stall: "Warm Part 2 worker" below. |
| `SIMON7_P2_FPS` | 10 | the rate Part 2 samples a take at, for the people step and the 3D step alike (moalborati/simon#62) |
| `SIMON7_P2_TRACK_FPS` | `SIMON7_P2_FPS` | the people step's tracking rate; when it differs from `SIMON7_P2_FPS`, Part 7 resamples the tracks to the 3D rate (`part7/track_resample.py`) |
| `SIMON7_P2_TRACKER` | unset | a Part 2 tracker name (`local-sam31`, `local-open`, `bytetrack`, `api-sam31`) used in place of "auto" for `part2 track` |
| `SIMON7_P2_TRACK_WORKER` | unset (off) | `1` keeps SAM 3.1 (`local-sam31`) loaded in its own process for the people step: "Warm SAM 3.1 tracker" below (TICKET-117) |
| `SIMON7_P2_TRACK_WORKER_IDLE_S` | 0 | seconds without a tracking call before the tracker worker frees its GPU memory; `0` loads it at boot and never frees it |
| `SIMON7_PART1_TIMEOUT_S` | 150 | seconds the trainer job waits for Part 1; past it, the job falls back to keyframes every 10 frames instead of failing |
| `SIMON7_LIMITS` | off | `on` enforces the daily caps (`SIMON7_DAILY_GPU` default 40 jobs, `SIMON7_DAILY_TRAINER` default 10) and the per-visitor caps (10 GPU and 3 trainer jobs a day). Jobs are counted either way under `<state>/quota/`. |
| `SIMON7_STATE_DIR` | `~/.local/state/simon-part-7` | root for `videos/`, `dev/`, `check/` |
| `SIMON7_KEYS_DIR` | `~/.config/simon/keys` | where Part 7 looks for key files |
| `SIMON7_PART2_GPU_VENV` | `~/.local/state/simon-part-2/venvs/gpu-cu128` | Part 2's GPU venv |
| `SIMON7_GPU_LOCK_PATH` | `~/.local/state/simon-part-2/gpu.lock` | the GPU lock shared with Part 2 |
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

Step logs are named after the call: `part1.log`, `part2.log`, `part2_track.api.log` (the api-sam31
tracker), `part2_track.log` (Part 2's default tracker order),
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
- `the server restarted`: the server stopped while the job was running (or queued and not resumable); on
  start such a job is marked failed. A queued trainer or follow job stays queued and runs after the restart.
- `the app restarted before this take finished; record it again`: the stop waited `SIMON7_DRAIN_MAX_S` (600 s) and
  the job was still running (`ANOMALY drain_cut_off`).
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
| `no_person` | Part 7 | Part 2 found no person | `part2.log`, `part2_track.api.log` and `part2_track.log` |

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
node tests/part7/pending.browser.mjs   # offline takes: needs python3 and ffmpeg (it starts tests/part7/fake_api.py)
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

## Warm Part 2 worker (TICKET-099)

On the staging server (unset `SIMON7_P2_WARM_WORKERS`; other servers start none and log `p2 warm workers: 0 (dev default off)`) or with `SIMON7_P2_WARM_WORKERS=1`, Part 7 starts ONE `part2 serve-worker` under `<state>/p2-workers`. Only `part2 run`
uses it. `track` stays in-process because it loads its own tracker and needs GPU admission. A `run` waits at most 5 s
for the busy worker, then runs in-process as before; it never queues behind it. A worker that fails its health
check logs `ANOMALY p2_worker_unhealthy`, the call runs in-process, and the worker is restarted once in the
background (a failed restart is retried after 5 min). A run the worker drops mid-request repeats in-process. The
heartbeat line ends with `p2_worker=off|starting|idle|busy|down`.

Why the 2026-10-30 warm workers stalled (5eccc60): from the code, not GPU memory alone and not the worker serving one
request at a time. The old pool had one worker per job slot (two), each leased to one job, so two `run` calls never
queued on one worker. Tracking was never sent to a worker (`_execute` leases only for `run`). Tracking stalled in
Part 7's own GPU admission (`gpu_lock.acquire`, `min_free_mib=12288`, polled every 15 s): two resident workers took
about 20 GB, leaving less than 12 GiB free on a 32 GB card that other processes also use, so every in-process
`track` that loads a local model waited, up to the 30 min limit, until a worker went away. Workers' own jobs were
exempt (`min_free_mib=0`), which kept them running and the waiting tracker starved. That fits the reported 6 to 12
minutes. With one worker (about 8 GB) free memory stays above the 12 GiB bar. The old logs of that run are gone, so this
is a reading of code and the 5eccc60 commit message, not a replay.

Measured 2026-10-31 on the RTX 5090 (32 607 MiB; 4 035 MiB already used by other processes before each run), staging
idle (`staging_live.live_jobs() == 0` before every run), Part 2 `f1d0dc7` GPU venv, a 4 s 640x360 clip, `part2 run
--mode single` through `p2_pose.run` with a local state folder:

| Run | Wall time | GPU used at peak |
|---|---|---|
| cold (in-process) 1 | 104.6 s | 17 359 MiB |
| cold 2 | 92.1 s | 16 107 MiB |
| cold 3 | 94.6 s | 16 071 MiB |
| warm (worker) 1 | 56.1 s | 16 065 MiB |
| warm 2 | 52.0 s | 16 071 MiB |
| warm 3 | 46.9 s | 16 071 MiB |

Cold mean 97.1 s, warm mean 51.7 s: the worker saves about 45 s per run. The worker takes 36 to 42 s to start and
holds 8 078 to 8 406 MiB while idle (12 113 to 12 441 MiB used against 4 035 MiB before). Worst case, with the worker
busy and a second `run` falling back to in-process after the 5 s wait, GPU use peaked at 24 480 MiB of 32 607 MiB
(8.1 GB spare); the in-process run took 139 s while the warm one took 49 s. A concurrent in-process `track` needs 12 GiB
free for admission and finds about 20 GB with the worker resident. Default: on.

## Warm SAM 3.1 tracker (TICKET-117, TICKET-128)

`SIMON7_P2_TRACK_WORKER=1` (staging/env.sh sets it; unset means off) starts Part 2's own warm track worker, `part2
serve-worker --mode track --socket <path>`, beside the 3D worker, under `<state>/p2-tracker`, with the same launcher,
log, pidfile, reaping, drain and load-scaled start deadline. It runs in Part 2's GPU venv, builds SAM 3.1 once and
serves `part2 track --worker <path> --tracker local-sam31`; the files equal the cold run's apart from
`provenance.created_utc` (Part 2 CONTRACT.md "Warm track worker", pin a8f91ac). TICKET-117's own bridge
(`part7/trackwarm/track_worker.py`, a patch of `part2.trackers.local_sam31`) was deleted in TICKET-128 once Part 2
shipped this entry.

- GPU lock: Part 2's worker takes the host GPU lock for each call. Part 7's admission releases it before the call body
  (`concurrent` admission, the way the 3D `--worker` path works), so the two never wait for each other; Part 7 still
  decides admission on 12288 MiB free (`TRACK_MIN_FREE_MIB`).
- Part 2's failure contract: exit 1 from `track --worker` means run the cold `part2 track` (fresh out folder,
  `ANOMALY p2_tracker_unhealthy`); exit 4 and 2 are answers. A worker that stopped and removed its socket is restarted
  at the next lease (retried after 5 min when the restart fails). Part 7 records the pin sha the worker started with
  and restarts it at the next lease when the Part 2 checkout moved (`p2_tracker_restart` log line); that call runs
  per-call.
- Opt-in. With the worker running, the people step's "auto" tracker is `local-sam31` (the paid API is skipped);
  `SIMON7_P2_TRACKER` still wins. A failed `local-sam31` then retries `local-open` by name.
- A call is admitted first and leases the worker after (as the 3D worker does). A busy tracker worker
  is waited for up to the call timeout (a cold local-sam31 run beside the loaded worker could run out of GPU memory);
  the 3D worker is still waited for 5 s (`SIMON7_P2_LEASE_WAIT_S`), then that call runs in-process. A worker that is down, did not
  start or drops a request (`ANOMALY p2_tracker_unhealthy`) sends the call to the per-call tracker; one background
  restart follows, retried after 5 min.
- Memory: about 5.1 GiB stays resident after a call; a call reserves about 26 GiB at its peak (TICKET-128, TICKET-125),
  exactly as a per-call run does. The cold repeat of a failed or timed-out warm call stops the tracker worker first and
  needs 26624 MiB free; a timed-out call also stops the worker (it keeps running the call and holds Part 2's GPU lock).
  Both start the worker again at the next people step. The pool needs `part2 serve-worker --mode` in the pin. The log line `p2_tracker resident:`
  gives the card's use after the load. `SIMON7_P2_TRACK_WORKER_IDLE_S=N` frees the model after N idle seconds and
  loads it again on the next call (`p2_tracker_released` log line); the default 0 keeps it loaded.
- The heartbeat line gains `p2_tracker=released|starting|idle|busy|down` while the pool runs. `part7 serve` stops it
  on exit, after the running takes drain.
- Starting either warm worker is patient on a busy host: the 180 s deadline is multiplied by load1 per CPU (1 to 4),
  and an abandoned start logs the elapsed time, load1, the exit code or signal and the last lines of the worker log.

## If the app looks wrong

1. Look at the top of the page. A yellow banner "Test server: nothing you record here is saved." means the browser is
   talking to the test stand-in (`tests/part7/fake_api.py`), not the real app. Stop that process
   and open the real address.
2. Open the page with `?debug=1`: the header shows the build line (commit and start time). A real server shows a real
   commit; the stand-in shows `fake (test server)`.
3. Read `api/health` (staging: `staging/health.sh` prints its URL): `fake` must be `false`, `build.sha` a commit, and
   `selfheal.summary` `ok`.
4. `uv run python -m part7 selfheal-status --staging` lists every self-heal check with its last run and last finding.
5. A movement that says "This movement's video may not match what was recorded" was flagged by the saved-entry check;
   the log has `ANOMALY entry_video_mismatch`. Record it again. Details: `docs/specs/self-healing.md`.

## Known issues and limits

- The warm Part 2 worker holds about 8 GB of GPU memory while resident and serves one request at a time
  (see "Warm Part 2 worker"). A SIGKILL of the server leaves it running; the next start stops it by its pid file.
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

## Updating the parts

Parts always follow the latest `main` of their repos, so updating is one command:

```bash
make parts       # setup-parts for the parts under modules/
make chain       # optional: run the whole chain on the new parts
```

`make parts` is idempotent per commit. To see whether a part has moved without changing anything, run
`uv run python -m part7 parts-status --check-remote` (exit 3 means a remote `main` is ahead). Staging
does this on a timer and redeploys itself within about 10 minutes of a part push.

When a part push breaks Part 7:

1. `make parts`, then `make test` and `make check-7` to reproduce.
2. Read the failing part's own log in the job record, and `uv run python -m part7 doctor-parts` for
   its contract check.
3. Fix it where it belongs: in the part repo (tell its owner), or in Part 7's adapter under
   `part7/parts/` when the part changed its contract on purpose.
4. To investigate against the last good commit, check it out inside the module
   (`git -C modules/part-N checkout <sha>`). The next `make parts` moves it back to `main`.
