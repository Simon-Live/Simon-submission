# Spec: Part 3 run app (pick or upload a pose3d.json, run the real pipeline, see it in 3D)

> Copy of the maintainers' working spec `docs/specs/run-app.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Requirements source: `goals/staging-simon-part-3.md` "What end to end means" (operator
directive 2026-10-28). Parent spec: `docs/design/specs/part3-skeleton.md`. Sibling: the staging spec (maintainers' workspace, not copied).
Request Type: new-feature
Risk Level: medium (a public, login-gated page that accepts uploaded files)
Tickets: TICKET-013 (server and API), TICKET-014 (run page).

Covers these files:
- `part3/runapi.py`: the pure request logic (sample table, upload parsing, pipeline run, metrics, error mapping).
- `part3/metrics.py` (`input_bone_variation` gains `person_id=None`; `None` keeps today's behaviour) and
  `part3/demo_data.py` (`frames_to_points` gains a strict-id mode; the bone pairs helper becomes public).
- `part3/server.py`: the stdlib HTTP server (`python3 -m part3.server`), routes, limits, headers.
- `web/app.html`, `web/app.js`, `web/app.css`: the run page.
- `web/scene.js`: the 3D pieces shared by the run page and the agreement view (moved out of `web/viewer.js`).
- `web/controls.js`: only `framingScale`, the output camera framing, is specified here; the rest of the module is
  specified in `docs/design/specs/compare-mode.md`.
- `web/viewer.js` and `web/index.html` (the four-take agreement view; imports from `scene.js`, gains a link back).
- `demo/capture.mjs` (its URL moves to `agreement`), `Makefile` (`make demo` serves the app; `make test` also runs `tests/staging` when present).
- Tests: `tests/part3/test_runapi.py`, `tests/part3/test_runapi_options.py`, `tests/part3/test_fps_refusal.py`,
  `tests/part3/test_frame_cap.py`, `tests/part3/test_typed_refusals.py`, `tests/part3/test_server.py`,
  `tests/part3/test_web_static.py`; their shared helpers are in `tests/part3/runapikit.py`.
- Docs: `README.md` (section "Web app") and `demo/README.md` ("How this was built"); `demo/staging-walkthrough.mp4`
  is published upstream through the `.simon-publish` `demo/**` entry.

## Overview
Today a visitor can only watch a prebuilt viewer. The run app lets a visitor run the real Part 3 pipeline in
a browser: pick one of the bundled `pose3d.json` inputs or upload their own, choose the mirror setting
(`auto | on | off`, the CLI's `--flip`), press Run. The server calls `part3.cli.process` on the bytes (no
precomputed result) and returns the exact `skeleton.json` text the CLI would write, plus metrics. The page
draws the input and the output skeletons side by side in 3D (orbit, zoom, Front, Side, Top, Reset, play,
pause, scrub) and offers a Download skeleton.json button. The existing four-take agreement view stays
reachable at `agreement` from the same app. Python standard library HTTP server only, no new framework;
every URL is relative so the app runs under any base path (the gateway's `/simon-part-3/` prefix route).

## Why This Is Wrong (Dissent-First)
- An upload endpoint on a shared host is an attack surface (large bodies, deep JSON, slow requests, path
  tricks). Mitigated by a 16 MiB body cap (raised from 2 MiB by `compare-mode.md` AC-M03), a required digits-only `Content-Length`, a fixed route table (no
  request path ever reaches the filesystem), a 15 s socket timeout, at most 16 open connections, at most 2 runs
  at once (the slot is taken before the body is read) and a 20 s run timeout.
- "In-process with a timeout" cannot stop a Python thread. A run past the timeout answers 503 and its
  worker thread finishes in the background; the body cap bounds that work (the 150 KB fixtures run in about
  0.1 s), and the run slots stay taken until the thread ends, so a flood gets `busy`, not more threads.
- Showing the input "as delivered" next to a cleaned output invites a reader to think the output is the
  same person's real limb lengths. The output panel is titled "Output skeleton.json, one fixed body", and the
  footnote under the two panels says the output is rebuilt on the Body the visitor chose, with the same limb
  lengths in every frame and the feet on the grid, that Measured from the clip uses this clip's own median
  lengths, left and right averaged, and that a Height scales whichever Body was chosen. The Body height card note
  reads "this run's body: <profile>", so it makes no claim across runs.
- The 3D view is WebGL; a browser without it shows nothing. The page then shows a plain message and the
  metrics and download still work.

## User Story
As a visitor holding the staging link and login, I want to run Part 3 on a real or my own `pose3d.json`
and see what it changes, so that I can judge the skeleton cleanup without a code checkout.

### Jobs-to-be-Done
- Functional job: turn a `pose3d.json` into a `skeleton.json` and inspect both in 3D.
- Emotional job: trust that the result comes from the real pipeline, not a canned demo.
- Social job: show a teammate (Part 4 and Part 5 owners) the exact file they will receive.
Registry use cases: `uc-clean-real-clip`, `uc-four-take-agreement`, `uc-demo-viewer`.

## Acceptance Criteria

### AC-R01: samples listed
Given the server is running
When the page loads
Then it lists the 7 bundled inputs in this order: the Part 2 squat (real clip), synthetic takes 1 to 4,
take 1 mirrored, and the arm-raise negative control, each with its frame count; the Part 2 squat is selected.

### AC-R02: run a sample with each mirror setting
Given a sample is selected and a mirror setting `auto`, `on` or `off` is chosen
When the visitor presses Run
Then the server runs `part3.cli.process` on that sample's file bytes with that setting, and the page shows
the metrics (bone-length variation of the output and of the input, flips repaired, mirror decision with its
reason, body height of the standard body, frames kept) and both skeletons in 3D.

### AC-R03: the download is the CLI's output
Given a finished run
When the visitor presses Download skeleton.json
Then the browser saves a file named `skeleton.json` whose bytes equal what
`python3 -m part3 run --in <same input> --out <file> --flip <same setting>` writes, and
`python3 -m part3.schema` accepts it.

### AC-R04: upload a good file
Given the visitor chooses a local `pose3d.json` that meets the input contract (at most 16 MiB)
When they press Run
Then it runs like a sample (AC-R02), the source is named "your file" with its file name, and the file is not
stored anywhere on the server.

### AC-R05: upload a bad file
Given the visitor chooses a file that is not JSON, or JSON that breaks the `pose3d.json` contract, or a file
over 16 MiB
When they press Run
Then the page shows a plain-language error in an alert region: for a contract break it names the failing
field (the validator's path, for example `pose3d.frames[0].people[0].joints.nose.conf`); never a stack trace,
an exception name or a server path; the previous result is hidden.

### AC-R06: 3D controls
Given a finished run
Then both panels can be orbited (drag) and zoomed (wheel or pinch); Front, Side, Top and Reset move both
cameras; Play and Pause start and stop the motion; the scrub slider and the arrow keys set the frame; Space
toggles play when focus is not on a button or slider.

And the output camera is framed for the body's height: `framingScale(stature_m)` in `web/controls.js` is 1 at
1.70 m or below, so that view is as before, and `stature_m / 1.70` above it. `web/app.js` moves the output camera
and its target out from the grid origin by that factor (on the first view, on every view button and on a run at
another height, which keeps the visitor's angle), so the head stays clear of the panel caption at every Height up
to 2.5 m. The input camera, `web/scene.js`, `web/viewer.js` and the agreement view are not touched by it.

### AC-R07: agreement view reachable
Given the run page
When the visitor follows the link "Four-take agreement"
Then the existing agreement view (`web/index.html`) loads at `agreement` under the same base path with its
agreement figure equal to `web/data/demo.json`, and it links back to the run page.

### AC-R08: base path
Given the server started with `--base /simon-part-3/`
Then every page, asset and API answers under `/simon-part-3/`, `/simon-part-3` redirects to
`/simon-part-3/`, and anything outside the base is 404. With the default `--base /` the same app answers at `/`.

### AC-R09: phone width
At 390 px wide nothing scrolls horizontally, the panels stack, and Run, the mirror setting, the upload and
Download stay reachable.

### Rule-Based ACs
- AC-NFR-01: no request path reaches the filesystem; static files come from a table built at start-up from
  `web/` (allowed extensions only). Verification: test (traversal attempts 404).
- AC-NFR-02: request body cap 16 MiB (2 MiB until Phase 2, `compare-mode.md` AC-M03); POST needs a digits-only `Content-Length` (missing 411, malformed 400);
  an oversize body is read and discarded up to 32 MiB (`DRAIN_MAX`), then 413 with `Connection: close` (beyond
  32 MiB the connection is closed); 15 s socket timeout per read and 60 s in total for the body (`BODY_TIMEOUT_S`,
  16 MiB over a slow link); the request line and
  headers complete within 20 s of the connection opening (`HEADER_DEADLINE_S`); at most 16 open connections
  (`MAX_CONNECTIONS`) plus 1 reserved connection (`RESERVED_CONNECTIONS`) that answers only `GET api/health`
  (anything else there gets 503 `busy`, and its head must arrive within `RESERVE_HEAD_S` = 2 s); at most 2 runs
  at once, the run slot taken before the body is read; 20 s run timeout. A client that trickles its head is
  dropped at the deadline, and with 16 stalled visitors `api/health` still answers 200. Verification: test.
- AC-NFR-07: a POST with `Sec-Fetch-Site: cross-site` is refused with 403 `cross_site`; error messages are cut
  to 300 characters; the page renders server text with `textContent` only (no `innerHTML` in `web/app.js`);
  the log line has the route without its query string. Verification: test.
- AC-NFR-03: every response carries `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`;
  HTML carries `Content-Security-Policy: default-src 'self'; script-src 'self' 'sha256-<each inline script,
  computed at start-up per HTML file>'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:;
  connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`;
  API responses carry `Cache-Control: no-store`. Verification: test.
- AC-NFR-04: no absolute URL (`/...` or a scheme) in `web/app.html`, `web/app.js`, `web/index.html`,
  `web/viewer.js`, `web/scene.js`, except the import map's relative entries. Verification: test.
- AC-NFR-05: a run of any bundled sample answers in under 2 s on this host. Verification: test (timed).
- AC-NFR-06: `make check-3` and `make test` stay green. Verification: the commands.

## API / Interface Contract
Base `B` is `--base`, normalised to start and end with `/` (default `/`).

Command: `python3 -m part3.server [--host 127.0.0.1] [--port 8733] [--base /]`. Logs one line per request to
stderr (method, path, status, ms, client: `X-Forwarded-For` only when the TCP peer is loopback).

| Method and path | Answer |
|---|---|
| `GET B` | `web/app.html` |
| `GET B` without the trailing slash (B is not `/`) | 308 to `B` |
| `GET Bagreement` | `web/index.html` (relative URLs resolve under `B`) |
| `GET B<file>` | a file of `web/` from the start-up table: extensions `.html .js .css .json .png .svg` |
| `GET Bapi/health` | 200 `{"ok": true, "samples": 7}` |
| `GET Bapi/samples` | 200 `{"samples": [{"id", "label", "detail", "frames", "mirrored_hint"}]}` |
| `POST Bapi/run?sample=<id>&flip=<f>` | empty body; runs the sample file |
| `POST Bapi/run?flip=<f>&name=<file name>` | body = the uploaded file's bytes |
| anything else under `B` | 404 JSON (`not_found`); a known path with the wrong method 405 (`method`) |

Samples (id, file under `fixtures/input/`, label):
`part2-squat` `part2-single/pose3d.json` "Part 2 squat (real clip)";
`take-1` .. `take-4` `synthetic-4take/take-<k>/pose3d.json` "Synthetic squat, take k";
`take-1-mirrored` `synthetic-4take/take-1-mirrored/pose3d.json` "Synthetic squat, take 1, saved mirrored";
`armraise-control` `synthetic-4take/negative-armraise/pose3d.json` "Arm raise (negative control)".
`detail` is one sentence (camera angle from the take's `truth.json` where present); `mirrored_hint` is the
file's top-level `mirrored` value is `true`.

Run success, 200:
```json
{"ok": true,
 "source": {"kind": "sample|upload", "id": "part2-squat|null", "name": "label or file name", "bytes": 130933, "sha256": "hex"},
 "flip": "auto",
 "metrics": {"frames": 0, "frames_present": 0, "frames_dropped": 0, "person_id": "...", "people_in_input": 1,
             "bone_length_variation_output": 0.0, "bone_length_variation_input": 0.0, "variation_limit": 0.02,
             "flips_repaired_frames": 0, "flips_repaired_total": {"<group>": 0},
             "mirror": {"setting": "auto", "applied": false, "reason": "..."},
             "stature_m": 1.7, "up_source": "standing_frames"},
 "input_frames": [[[0.0, 0.0, 0.0]], null],
 "bones": [[0, 1]],
 "skeleton_text": "<exactly part3.io.dumps(skeleton)>",
 "run_ms": 0.0}
```
- `input_frames`: per input frame, the kept person's 17 `[x, y, z]` in canonical order (4 decimals) as Part 2
  delivered them (before mirror and label repair), or `null` when that person is absent.
- `bones`: the 18 bones as joint-index pairs, `-1` hip midpoint and `-2` shoulder midpoint (the demo-data
  convention `part3.joints.bone_index`, through the public helper in `part3/demo_data.py`).
- `input_frames` uses `demo_data.frames_to_points` in strict-id mode: a frame without the kept id is `null`,
  never another person.
- `bone_length_variation_output` is `part3.metrics.bone_variation(skeleton, bones.lengths_array(skeleton["bone_lengths_m"]))`;
  `bone_length_variation_input` is `part3.metrics.input_bone_variation(doc, person_id=<kept id>)` (the input's
  own per-bone medians for the kept person); both rounded to 4 decimals. A value that is not finite is `null`;
  the response is serialised with `allow_nan=False`.
- `input_height_estimate_m`: the standard stature scaled by the ratio of the kept person's measured leg and
  trunk chain (`person.measured_bone_lengths_m`) to the same chain of the standard body; `null` when not finite.
  Shown next to `stature_m` so "body height" says something about the input.
  `flips_repaired_frames` counts output frames whose `flips_repaired`
  is non-empty. `stature_m` is `skeleton.standard.stature_m`.
- `source.sha256` equals the skeleton's `input.sha256` (the hash of the bytes run).

Error, any 4xx or 5xx: `{"ok": false, "error": {"code": "...", "field": "path or null", "message": "plain text"}}`

| code | status | When | message (plain language) |
|---|---|---|---|
| `not_json` | 400 | body is not UTF-8 JSON, or nests too deep | "This file is not JSON. Choose a pose3d.json file." |
| `contract` | 422 | a `ContractError` from the validator, the adapters or the pipeline that is none of the three typed refusals below (so never a `FrameCapError`, a `FrameRateError` or a `ViewError`), or an id that cannot be written as UTF-8 (field `pose3d.frames`) | "This file is not a valid pose3d.json: <field>: <reason>." with `field` set |
| `view_refused` | 422 | a `ViewError`: the chosen View cannot write the clip (`docs/design/specs/compare-mode.md` AC-M14); field `view` | the error's `page_text`, for example "This clip cannot be written as Part 4 keys: left_shoulder turns 341.3 degrees between keys 110 and 120 (Part 4 allows 180). Choose another View." |
| `fps_refused` | 422 | a `FrameRateError`: the clip cannot be resampled at the chosen Frame rate and it is not the cap; field `fps` | at 30 "No frame at 30 per second holds the person. Choose 60 per second or Source."; at 60 "No frame at 60 per second holds the person. Choose Source."; for times that do not increase "<path>: the times must increase to change the frame rate. Choose Source, or fix the times." |
| `too_long` | 400 | a `FrameCapError`, or the span pre-check: the frames the run would write are over the cap (20,000 on the server) | "This clip is too long for that frame rate here. Choose a lower frame rate or a shorter clip."; for the Part 4 key timeline (View Part 4, Frame rate Source) "This clip is too long for Part 4 keys here. Choose another View or a shorter clip." |
| `too_large` | 413 | `Content-Length` over 16 MiB | "This file is over 16 MB. Choose a smaller pose3d.json file." |
| `length_required` | 411 | POST without `Content-Length` | "The upload had no length. Try again." |
| `bad_flip` | 400 | `flip` not auto, on or off | "Mirror must be auto, on or off." |
| `unknown_sample` | 404 | no such sample id | "There is no sample with that name." |
| `no_input` | 400 | no sample and an empty body | "Choose a sample or a file first." |
| `both_inputs` | 400 | a sample and a body | "Choose a sample or a file, not both." |
| `busy` | 503 | 2 runs already in progress | "The server is busy. Try again in a moment." |
| `timeout` | 503 | the run took over 20 s | "The run took too long and was stopped." |
| `cross_site` | 403 | POST with `Sec-Fetch-Site: cross-site` | "This request came from another site and was refused." |
| `bad_request` | 400 | `Content-Length` not digits only | "The upload was malformed. Try again." |
| `internal` | 500 | any other exception (logged with its traceback to stderr only) | "Something went wrong on the server. Try again." |

### Page contract shared with the verify suite (the maintainers' staging spec uses it)
Landmarks (role and accessible name): radio group "Input" with one radio per sample label and "Your own file";
file input labelled "pose3d.json file"; radio group "Mirror" with "Auto", "On", "Off"; button "Run"; a status
region; an alert region; buttons "Front", "Side", "Top", "Reset", "Play" (reads "Pause" while playing); slider
"Frame"; button "Download skeleton.json"; link "Four-take agreement"; on the agreement view the link "Run the
pipeline".
Read-only hooks on `window.app` (getters; none changes state): `ready` (true after the samples load), `runs`
(finished runs, errors included), `lastRun` (`{ok, source, flip, metrics, error}`), `frame`, `frameCount`,
`playing`, `camera(panel)` and `target(panel)` returning `[x, y, z]` for panel `"input"` or `"output"`.
`tests/part3/test_web_static.py` asserts every landmark and hook name is present.

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| Non-JSON upload | 400 `not_json`, nothing run | table above | AC-R05 |
| Contract break | 422 `contract`, field = validator path | table above | AC-R05 |
| Over 16 MiB | 413 before the body is read | table above | AC-R05, AC-NFR-02 |
| Unknown flip or sample | 400 / 404 | table above | AC-R02 |
| Traversal (`../`, `%2e%2e`, absolute paths) | 404 `not_found` | JSON | AC-NFR-01 |
| Pipeline exception | 500 `internal`, traceback only in the log | table above | AC-R05 |
| Third concurrent run | 503 `busy` | table above | AC-NFR-02 |

## Edge Cases
- Upload with several people: the pipeline's one-person rule picks the id; `input_frames` shows that id;
  `people_in_input` reports how many ids the file had (AC-R04).
- A file whose kept person is missing in some frames: `input_frames` has `null` there; the output frame has
  no person; the page shows "no person in this frame" for that frame (AC-R06).
- `mirrored: true` in the file with `auto`: mirror applied, reason shown (AC-R02).
- Uploading the same file twice gives the same `skeleton_text` (AC-R03).
- File name with odd characters: it is shown as text only, truncated to 80 characters, never used as a path (AC-R04).
- WebGL unavailable: the panels show "3D needs WebGL"; metrics and Download still work (AC-R06).

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|---|---|---|---|
| Performance | sample run | under 2 s | AC-NFR-05 |
| Security | input limits, no path from the request | tests | AC-NFR-01, AC-NFR-02 |
| Security | headers | tests | AC-NFR-03 |
| Security | authentication | the gateway's basic auth; the app has no accounts | n/a |
| Privacy | uploads | kept in memory for one request, never written or logged (only size and hash are logged) | AC-R04 |
| Accessibility | labels, focus rings, `role=status` and `role=alert`, keyboard play and step | inspection, verify suite | AC-R06 |
| Compatibility | Chromium on desktop and phone widths | verify suite | AC-R09 |
| Reliability | restarts | stateless; nothing to persist | n/a |

## Negative Requirements
- The server never writes an upload to disk and never builds a filesystem path from a request.
- The page never shows a traceback, an exception class name or a server path.
- No precomputed run result is served; every Run calls the pipeline.
- No new Python or JavaScript dependency; three.js stays the vendored r170.

## Compromises
- Runs in a worker thread with a timeout instead of a subprocess: the brief asks for in-process; the body cap
  bounds the work a timed-out thread can still do.
- Side by side, not overlaid: the input is in camera coordinates and the output in the body frame; overlaying
  them would mislead.

## Non-Requirements
- No accounts, no stored history, no sharing links.
- No video upload; Part 3 only reads `pose3d.json`.

## Assumptions
- ASM: the gateway's basic auth is the only access control needed (staging contract).
- ASM: 16 MiB is ample: the bundled clips are 129 KB to 148 KB (105 to 121 frames); Phase 2 raised the cap from 2 MiB for longer real clips.

## Implied Requirements
- `make demo` now runs `python3 -m part3.server --port 8733 --base /`, so the local demo is the same app;
  `make demo-stop` stops it. `demo/capture.mjs` opens `http://127.0.0.1:8733/agreement`.
- The agreement view keeps its behaviour exactly: `web/viewer.js` imports the moved code from `web/scene.js`.

## Delivery Verification Plan
- Unit and HTTP tests: `tests/part3/test_runapi.py` (pure logic, every error code, metrics, the download equal
  to the CLI output), `tests/part3/test_runapi_options.py` (the run options and the View refusals),
  `tests/part3/test_fps_refusal.py` and `tests/part3/test_frame_cap.py` (the Frame rate and cap refusals, by type),
  `tests/part3/test_typed_refusals.py` (every option refusal the run app can reach is typed),
  `tests/part3/test_server.py` (a real server on an ephemeral port: routes, base path,
  limits, headers, traversal, concurrency and timeout), `tests/part3/test_web_static.py` (no absolute URLs,
  every element id that `app.js` looks up exists in `app.html`). The helpers these share are in
  `tests/part3/runapikit.py`; no test module imports another.
- Browser: `staging/verify.sh` drives the page through the gateway as a visitor on desktop and phone widths
  (the maintainers' staging spec): every sample, every mirror setting, a good and a bad upload, the 3D controls,
  the download compared byte for byte with the CLI, the agreement view. Data is created through the UI only.
- `node demo/capture.mjs` against `make demo` still passes for the agreement view.

## Dissent Review
Pre-mortem (it failed; why?):
1. The page worked at `/` but broke under `/simon-part-3/` because one fetch used `/api/run`. AC-NFR-04 test.
2. A visitor uploaded a 40 MB file and the server held the memory. The cap is checked on `Content-Length`
   before reading.
3. Moving code out of `viewer.js` broke the agreement view silently. `demo/capture.mjs` and the verify suite
   both open it.

## Requirements Traceability
| AC | Test | Code |
|---|---|---|
| AC-R01 | test_runapi `test_samples_*`, verify `samples` | `part3/runapi.py`, `web/app.js` |
| AC-R02 | test_runapi `test_run_sample_*`, verify `runs` | `part3/runapi.py`, `web/app.js` |
| AC-R03 | test_runapi `test_skeleton_text_equals_cli`, verify `download` | `part3/runapi.py`, `web/app.js` |
| AC-R04 | test_runapi `test_upload_*`, verify `upload-good` | `part3/runapi.py`, `web/app.js` |
| AC-R05 | test_runapi `test_error_*`, test_server limits, verify `upload-bad` | `part3/runapi.py`, `part3/server.py`, `web/app.js` |
| AC-R06 | verify `controls` | `web/app.js`, `web/scene.js` |
| AC-R07 | test_server `test_agreement_route`, verify `agreement` | `part3/server.py`, `web/index.html` |
| AC-R08 | test_server `test_base_path_*` | `part3/server.py` |
| AC-R09 | verify `phone` | `web/app.css` |
| AC-NFR-01..03 | test_server | `part3/server.py` |
| AC-NFR-04 | test_web_static | `web/*` |
| AC-NFR-05 | test_runapi `test_run_time` | `part3/runapi.py` |

## Test Scenarios
One per AC, named in the traceability table; the verify suite checks are listed in the staging spec (maintainers' workspace, not copied).

## Deviations from PRD
None (no PRD; the brief's "end to end" list is met item by item).
