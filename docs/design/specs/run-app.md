# Spec: Part 2 web app (browse committed outputs, then upload a video, class clip or photo and run the real pipeline)

> Copy of `docs/specs/run-app.md` from the maintainers' working repo at `68ecdcc`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Requirements source: locked decision 8 (stakeholder-proxy 2026-10-28), hub registry milestones S0
and M4 and use cases `uc-one-person-video`, `uc-class-video`, `uc-photo-to-3d`; README "Demos" (a photo beside
its rotatable 3D skeleton; a class clip with coloured, stable per-person skeletons). Parent spec:
`docs/design/specs/part2-images-to-3d.md`. Sibling: `staging.md (maintainers' tooling spec, not published)`.
Request Type: new-feature
Risk Level: medium (a login-gated public page that accepts uploaded media and starts GPU work)
Tickets: TICKET-003 (browse app, S0), TICKET-023 (job queue), TICKET-024 (run API), TICKET-025 (run page).
ADRs: ADR-0002 (backends), ADR-0003 (trackers), ADR-0006 (reproducible outputs), ADR-0007 (takeover etiquette).

## Overview
One Python standard library HTTP server (`python -m part2.server`) serves three pages under a base path:
`index.html` (S0: the committed outputs `single`, `class`, `dance` and the scored outputs, each frame beside a
rotatable 3D skeleton, the class and dance clips with every person in a stable colour), `contract.html` (S0: the
contract page rendered from `CONTRACT.md` data and `contracts/*.schema.json`), and `run.html` (M4: upload a
video, a class clip or a photo, or pick a sample; a job queue with one GPU worker runs the real `part2 run`; the
page shows progress, then the frames beside the 3D skeleton, the class overlay with per-person colours and one
person at a time in 3D, and downloads of `pose3d.json` and `tracks.json`, naming the backend and tracker that
ran). The 3D renderer is the canvas renderer of the existing `part2/demo.py` viewer, extracted into
`web/viewer.js`; no 3D library is added. Every URL is relative, so the app runs under the gateway prefix
`/simon-part-2/` and at the root for `scripts/dev.sh`.

## Why This Is Wrong (Dissent-First)
- Upload plus GPU inference is an abuse target (huge files, long videos, decoder exploits, queue flooding). The
  server caps bodies before reading, sniffs content with `ffprobe` and Pillow (never trusts names or types),
  limits duration and frame count, keeps one worker and a queue of 5, and times jobs out at 20 minutes.
- GPU memory is shared with other host work. The worker checks free memory before each job and waits rather than
  crashing someone else's process (two jobs on one card took the team's GPU down on 2026-10-27, thread #18).
- A canvas renderer is less capable than three.js. It already orbits, zooms and scrubs in the shipped demos; the
  added views (Front, Side, Top, Reset) are camera presets, so a library would add weight without a feature.
- Jobs leave visitor media on disk. Job directories live under `~/.local/state/simon-part-2/jobs/`, never in the
  tree, and are deleted after 24 hours; DEMO.md says uploads are not kept.

## User Story
As a trainer or visitor, I want to upload a phone clip, a class clip or a photo and see it in 3D beside the
original, so that I can judge Part 2's output and download the files Parts 3 to 5 read.

### Jobs-to-be-Done
- Functional: a `pose3d.json` (and `tracks.json` for a class) from my own media, without a GPU of my own.
- Emotional: the page says what is happening while the GPU works.
- Social: a link the team can show at the hackathon.

## Interface

### Server
`python -m part2.server --host 127.0.0.1 --port <n> --base <prefix>` (`ThreadingHTTPServer`, stdlib only).
`scripts/dev.sh [start|stop]` runs it on `127.0.0.1:8722` with base `/` (pid in
`~/.local/state/simon-part-2/dev.pid`, log beside it; `stop` kills only a pid whose command line holds
`-m part2.server`). Staging runs it on 7122 with base `/simon-part-2/` (`staging.md (maintainers' tooling spec, not published)`).

| Method and path (relative to base) | Answer |
|---|---|
| `GET ` (base), `index.html`, `contract.html`, `run.html`, `*.js`, `style.css`, `icon.svg` | 200 static file from `web/`; fixed table, no path from the request reaches the filesystem |
| `GET api/health` | 200 `{"ok": true, "version": <part2 commit>, "gpu": {"free_gib", "total_gib"} or null, "worker": "idle"|"busy"}` |
| `GET api/outputs` | 200 list of browsable outputs `[{id, title, mode, people, frames, backend, tracker, source}]` from `fixtures/output/{single,class,dance}/` and `fixtures/output/scored/*/` |
| `GET api/outputs/<id>` | 200 `{pose3d, camera, tracks or null, frames: [{frame, t_ms, url}]}`; 404 unknown id |
| `GET api/outputs/<id>/frames/<n>.jpg` | 200 JPEG from the fixture frames dir; 404 otherwise |
| `GET api/contract` | 200 `{schemas: [...], compatibility: [...]}` (same data as `python -m part2 contract --json`) |
| `GET api/capabilities` | 200 `{backends: [{name, available, reason}], trackers: [{name, available, reason}], limits}` (presence checks only, never a key). Backend order: local `gpu`, then `cpu`. Tracker "Automatic" (the bulk order: `local-sam31` once parity passes, else `api-sam31` within the staging cap, else `local-open`) is the default; `local-open` and `bytetrack` can be chosen by name. Naming `api-sam31` or `local-sam31` in `POST api/jobs` is 400: a visitor never names a paid or key-gated tracker, the order decides (operator ruling 2026-10-28) |
| `POST api/jobs` | multipart: `file`, `mode` (`single`|`class`), optional `backend`, `tracker`, `sample` (a sample id instead of a file). 202 `{id, state}`; 400 plain error; 413 too large; 415 not a video or image; 422 too long or no frames; 429 queue full; 503 no backend available |
| `GET api/jobs` | 200 the visitor-visible queue `[{id, state, position, mode, created}]` |
| `GET api/jobs/<id>` | 200 `{id, state, mode, backend, tracker, fallback: {from, reason} or null, notice, progress: {stage, done, total}, position, error, files: [...]}`; `notice` is the plain line shown when a cap or a missing key moved the job to a later tracker; 404 unknown |
| `POST api/jobs/<id>/cancel` | 200 `{state: "cancelled"}`; 409 already finished; 404 unknown |
| `GET api/jobs/<id>/files/<name>` | `pose3d.json`, `tracks.json`, `camera.json` as `application/json` with `Content-Disposition: attachment`; `frames/<n>.jpg`; 404 otherwise |
| anything else | 404 JSON `{"error": "not found", "code": "not_found"}`; wrong method 405 |

Headers on every response: `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` on `api/`,
`Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:`. Errors are JSON `{error, code}` with a
plain sentence; never a traceback, class name or server path.

### Uploads and limits (`part2/runapi.py`)
| Kind | Accepted | Limit | After intake |
|---|---|---|---|
| video (single or class) | container sniffed by `ffprobe` as mp4, mov or webm with a video stream | 200 MB body, 60 s duration | `part2 frames` at 10 fps, at most 601 frames (60 s with both ends) |
| photo | Pillow opens it as JPEG or PNG | 20 MB body, 8000 px longest side | one frame, `t_ms` 0 |
| sample | ids from `api/outputs` with input frames (`single`, `class`) | none | copies nothing; frames read in place |
A video whose container and stream carry no duration (a browser MediaRecorder WebM) is measured by its decoded frame
timestamps, `last - first`, read once and shared with the frame count; the limits above are unchanged
(`docs/design/specs/journey-followup.md`, TICKET-039).
`Content-Length` is required and must be digits; bodies over the cap get 413 before reading. The upload is written
to the job dir as `input.<ext>` with a server-chosen name.

### Jobs (`part2/jobs.py`, `part2/gpu_guard.py`)
States: `queued` -> `waiting-gpu` -> `running` -> `done` | `failed` | `cancelled`. One worker thread; the job runs
`part2 run` as a subprocess in its own process group (in the GPU venv for `gpu`). The GPU lock
`~/.local/state/simon-part-2/gpu.lock` is shared with `make outputs`: the worker waits until it is free, then lets
go before the run starts, and the run takes it around each GPU stage itself (a SAM tracker while it tracks, the gpu
backend around each 3D estimate), so it never waits on its own parent. Before `running`, `gpu_guard.free_gib()`
(parses `nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits`) must report at least 12 GiB, else the
job sits in `waiting-gpu`, re-checked every 15 s, failed after 10 minutes with "The GPU is busy with other work;
try again later." A CPU job skips the memory check. Timeout 20 minutes, then the process group is killed and the
job fails with "The job took longer than 20 minutes and was stopped." Cancel kills the process group. A class or
video job with no tracker named runs with `PART2_TRACKER` unset and the staging spend settings in its environment
(`META_SPEND_LEDGER=~/.simon/meta_spend_staging.jsonl`, `META_BUDGET_USD=10`, a per-job cap of $0.50 over a ledger
in the job directory); the subprocess reads any key file itself, and the server never holds a key. Queue holds at
most 5 jobs not yet finished; the sixth POST gets 429. Progress: the subprocess prints `progress <stage> <done>
<total>` lines (stages `frames`, `track`, `pose`, `write`), which the worker parses into `progress`. Job dirs
under `~/.local/state/simon-part-2/jobs/<id>/` (id: 12 random hex characters) are removed 24 h after the job ends
and at server start for anything older.

### Pages (`web/`)
- `viewer.js`: canvas 3D skeleton (canonical frame: x left, y up, z anterior) extracted from the inline script in
  `part2/demo.py`; drag to orbit, wheel or pinch to zoom, buttons Front (camera on +z), Side (+x), Top (+y), Reset,
  Play/Pause, slider "Frame", arrow keys step a frame. Colours from the same palette and rule as
  `part2.demo.color_for` (ids stable across runs); the right side drawn in a darker tone as in the demo.
- `overlay.js`: draws each person's projected joints and bones over the frame image (projection with
  `camera.json` as `part2.canonical.project_pose3d` does), one colour per id, a legend listing ids with colours,
  and a person picker that sends one id to the 3D panel.
- `index.html` + `browse.js`: an output picker, the frame panel and the 3D panel side by side (stacked under 700 px
  width), the overlay for multi-person outputs, a line naming backend, tracker and source clip with licence.
- `contract.html`: schema list (name, version, file) and the compatibility table from `api/contract`, the coordinate
  frame and joints, and links to download each schema.
- `run.html` + `run.js`: radio group "Input" (samples and "Your own file"), file input labelled "Video or photo",
  radio group "Mode" ("One person", "Class"), selects "Backend" and "Tracker" (options from `api/capabilities`,
  unavailable ones disabled with the reason), button "Run", status region (queue position, stage, done of total),
  button "Cancel", alert region, then the frame panel, the 3D panel and controls, overlay and person picker for a
  class, buttons "Download pose3d.json" and "Download tracks.json" (class only), and a line naming the backend,
  tracker and lifter that ran, with "3D approximate" when the CPU backend's 3D bar failed (`docs/design/specs/backends-gpu-cpu.md` AC-B10).
- `style.css`, `icon.svg` (the page icon on every page).

### Page contract shared with the verify suite
Read-only hooks on `window.app`: `ready` (true after the first data load), `output` (id shown on the browse page),
`job` (`{id, state, progress, backend, tracker}` or null), `runs` (count of finished jobs, errors included),
`frame`, `frameCount`, `playing`, `people` (ids drawn), `colors` (`{id: hex}`), `camera()` -> `[x, y, z]`,
`target()` -> `[x, y, z]`. Every action in tests goes through the real controls; the hooks are only read.

Added with M4 (TICKET-025 and the S0 QA follow-up):
- `people`: the ids drawn in the current frame. For a multi-person output (browse) and for every run result it is
  the overlay's ids, so the class output shows all 7; for a one-person browse output, the 3D panel's.
  `colors` is `{id: hex}` of the same drawing (`part2.demo.color_for`).
- `person`: the id shown in the 3D panel (one person at a time, canonical frame, Front on +z), or null.
- Run page only: `viewerPeople` (ids drawn in the 3D panel in the current frame); `job` also carries `lifter`,
  `notice`, `fallback` (`{from, reason}` or null), `error` and `position`; `runs` also counts a POST the server
  refused (an upload error) and a file the page refused before sending it (too large, none chosen).
- The browse page opens on the first output with stored pictures (`has_pictures`), unless the URL hash names one.

Run page landmarks (role and accessible name; ids in brackets): group "Input" (fieldset) with radios named by the
sample titles from `api/capabilities` ("Stretch sample" `#input-sample-single`, one person; "Yoga sample"
`#input-sample-class`, a class; picking one also picks its mode) and "Your own file" (`#input-file`); file input "Video or photo" (`#file-input`); group "Mode"
with radios "One person" (`#mode-single`) and "Class" (`#mode-class`); comboboxes "Backend" (`#backend-select`) and
"Tracker" (`#tracker-select`, enabled in Class mode; option values `automatic`, `local-open`, `bytetrack`;
unavailable options disabled with the reason in their text); buttons "Run" (`#run-button`) and "Cancel"
(`#cancel-button`); status (`#status`: "Queued. Jobs ahead of yours: N.", "Waiting for the GPU to have enough free
memory.", "Running: <stage>, <done> of <total>.", "Done in N s.", "Cancelled.", "The job failed."); alert
(`#alert`, the plain error); the fallback notice (`#notice`); region "Result" (`#result`) with the result line
(`#result-line`: "Backend: <name>. Tracker: <name>. Lifter: <name>. <n> frames." plus "3D approximate" for the CPU
backend), img "Picture for frame N" (`#frame-img`) under the overlay canvas (`#overlay`), list "People"
(`#legend`), combobox "Person" (`#person-select`, options "id N"), img "3D skeleton view" (`#viewer`), group
"Camera" with buttons "Front", "Side", "Top", "Reset", button "Play" ("Pause" while playing), slider "Frame", and
group "Downloads" with buttons "Download pose3d.json" and "Download tracks.json" (class results only). The browse
page adds the overlay canvas (`#overlay`), list "People" (`#legend`) and combobox "Person" (`#person-select`) under
its picture for multi-person outputs. Navigation "Pages" links Browse, Contract and Run on every page.

Test hook header: `X-Part2-Test-Max-Body: <bytes>` lowers the body cap of one `POST api/jobs` (never raises it), for
the `errors` check on the app port.

## Files
| File | Role |
|---|---|
| `part2/server.py` | HTTP server, route table, limits, headers; `python -m part2.server` |
| `part2/runapi.py` | pure request logic: outputs index, sample table, multipart parsing, sniffing, limits, job creation, error mapping |
| `part2/jobs.py` | queue, worker, states, progress parsing, timeout, cancel, cleanup |
| `part2/gpu_guard.py` | free-memory query and the GPU lock helper |
| `part2/cli.py` (modified) | `progress` lines on stdout when `PART2_PROGRESS=1` |
| `web/index.html`, `web/browse.js` | browse page |
| `web/contract.html` | contract page |
| `web/run.html`, `web/run.js` | run page |
| `web/viewer.js` | canvas 3D renderer and controls |
| `web/overlay.js` | 2D overlay and person picker |
| `web/style.css`, `web/icon.svg` | style and icon |
| `scripts/dev.sh` | local dev server on 8722 (firm-only, never published) |
| `tests/test_server.py`, `tests/test_runapi.py`, `tests/test_jobs.py`, `tests/test_gpu_guard.py`, `tests/test_viewer_js.py` | tests |

## Acceptance Criteria
### AC-A01: browse committed outputs (S0)
`GET api/outputs` lists `single`, `class`, `dance` and every `fixtures/output/scored/*` present; the browse page
shows each with frame and 3D panels, the class and dance outputs with one colour per id that matches
`part2.demo.color_for` for that id. Test plus staging verify.
### AC-A02: contract page (S0)
`contract.html` lists every schema in `contracts/` with its version and the compatibility table rows; numbers equal
`python -m part2 contract --json`. Test.
### AC-A03: 3D controls
Drag changes `camera()`, wheel changes its distance, Front, Side, Top put the camera on +z, +x, +y of `target()`,
Reset returns it home, Play advances `frame`, Pause holds it, the slider and arrow keys set it.
### AC-A04: upload a one-person video (M4)
A 5 s mp4 posted with `mode=single` runs to `done`; the page shows its frames beside the skeleton; Download saves a
`pose3d.json` that validates against `contracts/pose3d.schema.json` and carries `provenance.backend` and
`provenance.tracker`; the page names both.
### AC-A05: class clip (M4)
The class sample (or an uploaded class clip) run with `mode=class` shows the overlay with a stable colour per id
across frames, the person picker switches the 3D panel, and Download saves `tracks.json` and `pose3d.json` that
validate.
### AC-A06: photo (M4)
A JPEG posted with `mode=single` gives a one-frame `pose3d.json` and the photo beside the skeleton in Front, Side
and Top.
### AC-A07: limits and sniffing
A 201 MB body is 413 without being read; a text file renamed `.mp4` is 415; a 61 s video is 422 "Videos can be
at most 60 seconds long."; a sixth queued job is 429; a missing or non-digit `Content-Length` is 411 or 400. Tests
with small fakes (the cap is a parameter in tests).
### AC-A08: one worker, memory check, timeout, cancel
With a fake `free_gib` of 4, a job stays `waiting-gpu` and fails after the wait limit (shortened in tests); two
jobs never run at once; a job past the timeout is killed and `failed`; cancel during `running` kills the process
group and leaves `cancelled`. Tests with a fake subprocess.
### AC-A09: progress
`GET api/jobs/<id>` reports `stage`, `done`, `total` from the subprocess lines; the page's status region shows them.
### AC-A10: plain errors
No response body or page text contains "Traceback", a Python exception class name or a filesystem path. Test over
every error path and staging verify.
### AC-A11: paths and methods
Encoded traversal (`..%2f`, `%2e%2e/`) and unknown files are 404 and never return file content; wrong methods 405;
`nosniff` on every response. Test.
### AC-A12: cleanup
A job dir older than 24 h is removed at start and by the sweeper; nothing is written in the repo tree by the server.

### Rule-Based ACs
- AC-A-NFR-01: stdlib only on the server side (plus the part2 package). Verification: inspection.
- AC-A-NFR-02: page usable at 390 px width with no horizontal scroll. Verification: staging verify `phone`.
- AC-A-NFR-03: every interactive control has an accessible name listed above. Verification: staging verify.

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| body over cap | 413 | "The file is too large. Videos can be up to 200 MB and photos up to 20 MB." | AC-A07 |
| not a video or image | 415 | "This file is not a video or photo the app can read." | AC-A07 |
| video too long | 422 | "Videos can be at most 60 seconds long." | AC-A07 |
| no person found | job `failed` | "No person was found in this file." | AC-A04 |
| queue full | 429 | "The queue is full. Try again in a few minutes." | AC-A07 |
| GPU busy past the wait | job `failed` | "The GPU is busy with other work; try again later." | AC-A08 |
| timeout | job `failed` | "The job took longer than 20 minutes and was stopped." | AC-A08 |
| backend or tracker unavailable | 503 or 400 | "The <name> backend is not available here." | AC-A04 |
| unknown job or file | 404 | "Not found." | AC-A11 |

## Edge Cases
- A video with a rotation tag: frames are written upright (ffmpeg autorotate), the overlay matches.
- A class clip with one person: allowed; the overlay shows one colour.
- A photo with several people in single mode: the largest person is kept (`body3d.choose_subject` rule).
- Server restart with jobs running: unfinished jobs are marked `failed` with "The server restarted." at start.

## Locked defaults (2026-10-28)
| Item | Decision | Why |
|---|---|---|
| Ports | dev 8722, staging 7122 | hub registry |
| Video cap | 200 MB, 60 s, 10 fps, 601 frames (both ends of 60 s; corrected 2026-10-29) | decision 8 ("e.g. 60 s / 200 MB"), decided here |
| Photo cap | 20 MB, 8000 px | phone photos fit |
| Queue | 1 worker, 5 waiting | one GPU |
| Free memory before a GPU job | 12 GiB; wait 10 min; re-check 15 s | ASM-009 |
| Job timeout | 20 min | a 600-frame class clip at measured speed fits (measured at TICKET-023) |
| Retention | 24 h | uploads are not kept |
| Staging Meta spend | $10 total (`~/.simon/meta_spend_staging.jsonl`), $0.50 per job; past a cap the job runs the next tracker and its result says "SAM 3.1 spend cap reached; tracked with local-open" | operator ruling 2026-10-28 |
| 3D renderer | canvas, from `part2/demo.py` | reuse the viewer (decision 8) |

## Negative Requirements
- MUST NOT serve any path the request names from disk. Why: traversal.
- MUST NOT show or log a key, the staging login or a server path.
- MUST NOT run two GPU jobs at once.
- MUST NOT spend past the staging caps or let a visitor name a paid or key-gated tracker. Why: operator caps of
  2026-10-28.
- MUST NOT keep uploads beyond 24 h or in the repo tree.

## Compromises
### One worker
Short-term: one job at a time. Long-term: batch small jobs. Trigger: queue waits over 10 minutes in use.

## Non-Requirements
- No accounts, no persistence of results beyond 24 h, no editing of outputs.

## Assumptions
- ASM-001: uv is on PATH through `~/.local/bin`.
- ASM-009: GPU memory free is at least 12 GiB most of the time.

## Implied Requirements Discovered
- A capabilities endpoint (the page must not offer a tracker that would fail closed).
- Server-restart handling of running jobs.

## Dissent Review
Reviewed by: setup lane (architect archetype, model: opus). Date: 2026-10-28
### Concern 1: decoders on hostile media
Challenge: ffmpeg parses untrusted files. Impact: crash or worse. Mitigation: ffprobe and ffmpeg run as subprocesses
with a timeout and no shell; only the job dir is writable for them. Resolution: ACCEPTED_RISK.
### Concern 2: a long queue makes the demo look broken
Challenge: one worker. Impact: visitors wait. Mitigation: queue position and stage shown; samples run from cached
frames. Resolution: ADDRESSED_IN_SPEC.
### Concern 3: CPU fallback hides a missing GPU
Challenge: the page silently runs on CPU. Impact: wrong expectations. Mitigation: the backend is named on every
result and selectable. Resolution: ADDRESSED_IN_SPEC.
### Pre-Mortem
1. The GPU venv is missing in the staging checkout. Likelihood: M, Impact: H, Mitigation: venv lives outside the
   tree; `up.sh` checks it and `api/capabilities` reports it.
2. A slow upload holds a thread. Likelihood: M, Impact: L, Mitigation: socket timeout 30 s per read.
3. Overlay colours differ from the shipped mp4 demos. Likelihood: L, Impact: L, Mitigation: same palette rule, test.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|---|---|---|---|
| S0 browse and contract page | AC-A01, AC-A02, AC-A03 | `tests/test_server.py`, `tests/test_viewer_js.py`, staging verify | pending |
| M4 upload video, class, photo | AC-A04, AC-A05, AC-A06 | staging verify, QA recipes | pending |
| M4 queue, memory, timeout, cancel | AC-A07, AC-A08, AC-A09 | `tests/test_jobs.py`, `tests/test_runapi.py`, `tests/test_gpu_guard.py` | pending |
| Security | AC-A10, AC-A11, AC-A12 | `tests/test_server.py` | pending |

## Delivery Verification Plan
`make test` exit 0; `scripts/dev.sh start` then a manual drive; staging `up` and `verify` exit 0
(`staging.md (maintainers' tooling spec, not published)`); QA recipes driven and validated by two agents; walkthrough video.
