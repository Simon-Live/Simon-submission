# Spec: Staging compare mode, 16 MiB uploads and the body, view and frame-rate switches

> Copy of the maintainers' working spec `docs/specs/compare-mode.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Requirements source: `goals/phase2-simon-part-3.md` section 5 (operator directive 2026-10-28).
Parent specs: `docs/design/specs/run-app.md` (every guard there is kept unless this spec changes it), the staging spec (maintainers' workspace, not copied),
`docs/design/specs/integration-contract.md` (profiles, views, `process`).
Request Type: feature-mod
Risk Level: medium (a public, login-gated page that accepts larger uploads)
Tickets: TICKET-028 (server, API, pages), TICKET-029 (verify, QA recipes, walkthrough).

Covers these files:
- `part3/runapi.py` (run options, angles, view text), `part3/compare.py` (new: pure compare logic),
  `part3/server.py` (limits, `api/compare`, the `compare` page route).
- `web/controls.js` (new: the request, option, player and view-button code shared by the Run and Compare pages).
- `web/icon.svg` (TICKET-021: the app icon of the Run, Compare and agreement pages), and the TICKET-021 polish in
  `web/app.css` (a pressed view button looks pressed), `web/controls.js` and `web/viewer.js` (Play keeps its label
  change and drops `aria-pressed`), `web/index.html`.
- `web/app.html`, `web/app.js`, `web/app.css` (Body, Height, View and Frame rate selectors on Run),
  `web/compare.html`, `web/compare.js`, `web/compare.css` (new page), `web/scene.js` (overlay of up to 6 skeletons).
- `staging/verify.mjs`, `staging/verify.sh`, `staging/recipes.mjs`, `staging/drive.mjs`, `staging/walkthrough.mjs`,
  `staging/record-walkthrough.sh`, `staging/DEMO.md`; `qa/recipes/*.md` (new recipes below).
- Tests: `tests/part3/test_runapi.py`, `tests/part3/test_compare.py`, `tests/part3/test_frame_cap.py` (review B1),
  `tests/part3/test_server.py`,
  `tests/part3/test_web_static.py`, `tests/staging/test_staging_scripts.py`.
- Media: `demo/staging-walkthrough.mp4`, `demos/screenshots/*`, `demos/screenshot-manifest.json`.

## Overview
The run page gains four switches: Body (blank = the View's default, `simon-standard`, `part4-rig`, `measured`), Height (blank = the profile's,
else 0.5 to 2.5 m), View (`native`, `part4` with a key every 10 ticks, `part5`) and Frame rate (source, 30, 60). A new
Compare page (`compare`) takes 2 to 6 inputs, each a sample or an upload with its own mirror setting, runs the real
pipeline on each one at a time, aligns them with the same phase alignment as `make check-3`, overlays every normalized
skeleton in one 3D view with per-input show or hide and phase-aligned playback, and shows a metrics table: per input,
and joint-angle agreement p95 overall and per pair, computed by the code `make check-3` uses. Each input's file can be
downloaded. Uploads may be up to 16 MiB each.

## Why This Is Wrong (Dissent-First)
- Six 16 MiB uploads in one request would hold about 100 MiB of JSON in memory at once. So the page sends one run per
  input (`api/run`, one at a time) and then one small `api/compare` request with the angle series only.
- `api/compare` trusts angle series sent by the browser. That is fine: they come from the visitor's own runs, the
  answer only goes back to them, and the series are bounded (size cap, finite numbers, 2 to 6 inputs, at most
  3,000 frames each).
- A 16 MiB body over a slow link breaks the 15 s body deadline. The body deadline becomes 60 s; the 16-connection cap
  and the run slots still bound what slow clients can hold.
- `file:` profiles and `part3.toml` would let a visitor name a server path. The server accepts only the three named
  profiles and never reads env or config for a request.

## User Story
As a stitching team member or a visitor
I want to run several takes side by side with one body and one output shape
So that I can see the four phones agree, and switch the body or the file shape without touching a command line.

## Acceptance Criteria
- AC-M01: `POST api/run` accepts `body` (`simon-standard` | `part4-rig` | `measured`; blank or absent takes the View's
  default, `part4-rig` for `part4` and `simon-standard` otherwise, assumption ASM-012, as `python3 -m part3 run` does),
  `stature` (blank or 0.5 to 2.5), `view` (`native` | `part4` | `part5`, default `native`) and `fps` (blank, `30` or
  `60`); the reply carries `skeleton_text` (native, for drawing and metrics, as today), `output_text` and
  `output_name` (the chosen view's exact bytes, what `python3 -m part3 run` writes with the same options; `part4` uses
  `--keyframes every:10`), `angles` (the joint-angle series `make check-3` uses) and `options` (what ran; `body` is the
  profile the run used, so a blank body echoes the View's default). Defaults give today's reply plus the new fields.
- AC-M02: Any other `body` (including `file:...`), `view`, `fps` or `stature` answers 400 with a plain error naming the
  field (`bad_body`, `bad_view`, `bad_fps`, `bad_stature`).
- AC-M03: An upload up to 16 MiB runs; over 16 MiB answers 413 `too_large` with "This file is over 16 MB. Choose a
  smaller pose3d.json file."; every other guard of `docs/design/specs/run-app.md` is kept (digits-only Content-Length, socket
  timeout, header deadline, connection cap and reserve, 2 runs at once, cross-site POST refused, CSP).
- AC-M04: `POST api/compare` with `{"inputs": [{"label", "angles"}, ...]}` (2 to 6, each angles a list of frames of
  the joint-angle vector, finite or null) answers `{"agreement": {"p95_deg", "pass": p95 <= 10, "per_pair":
  [{"a", "b", "p95_deg"}]}, "alignment": {"reference": 0, "maps": [[frame of input k for each reference frame]]}}`
  using `part3.metrics` DTW samples and spread statistics; fewer than 2, more than 6, a bad shape or over the size cap
  answers 400 naming the problem.
- AC-M05: The Compare page lists 2 input rows to start, Add input up to 6, Remove down to 2; each row has a sample
  picker or a file, and its own Mirror; one Body, Height, View and Frame rate for all; Compare runs the inputs one at a
  time with a progress line, then shows the overlay, the table and downloads.
- AC-M06: The overlay draws every normalized skeleton in its own colour with a legend; a checkbox per input shows or
  hides it; Play, pause and the slider move every input together on the reference timeline through the alignment maps.
- AC-M07: The metrics table shows per input: label, frames, bone variation of the output, flips repaired, mirror
  applied, body profile; then agreement p95 overall with PASS or FAIL at 10 degrees and one row per pair; the four
  synthetic takes with the defaults show the same overall p95 as `make check-3` (7.420).
- AC-M08: Each input has a Download button that saves its `output_text` under `output_name`.
- AC-M09: A failing input (bad file) stops the compare with a plain error naming that input and the field; the other
  rows keep their choices.
- AC-M15: The Compare result's source note names the Body, Height, View and Frame rate the server applied, read from the `options` the runs echoed (never from the page's field text): for example "Body: measured, height 1.85 m. View: native. Frame rate: 30 per second."; a blank Height reads "the body's own" and Frame rate Source reads "source". Test: `tests/part3/test_web_node.py`.
- AC-M16: The overlay camera is framed by the tallest input's stature (`framingScale` from `web/controls.js`), so every head stays clear of the caption; at 1.70 m the view is unchanged. Test: `tests/part3/test_web_node.py` runs
  `framingScale`, `framedView` and `reframePanel` of `web/controls.js` under node with the vendored `THREE.Vector3`.
- AC-M10: The run page shows the Body, Height, View and Frame rate selectors; switching Body changes the bone lengths
  shown and recorded in the download; View `part5` downloads a `simon.animation.v1` file; the metric cards name the
  profile.
- AC-M11: `staging/verify.sh` adds checks: compare page and API, the 16 MiB edge (16 MiB accepted, 16 MiB + 1 refused
  413), each selector value through `api/run`, bytes of a `part5` and a `part4` download equal the CLI's, agreement
  p95 of the four takes equals `make check-3`; it lists the new recipes and checks their landmarks.
- AC-M12: QA recipes, each driven by hand and validated by a different agent: `compare-four-takes` (the four takes,
  p95 7.420 PASS, hide one, play), `compare-mixed-inputs` (two samples and one upload with Mirror on, per-input
  table), `run-profile-switch` (Body part4-rig then measured, bone lengths change, download records the profile),
  `run-view-switch` (View part5 download format, View part4 keys); the six existing recipes still pass.
- AC-M13: `demo/staging-walkthrough.mp4` is one uninterrupted recording under 90 s and under 15 MB, through the
  gateway, showing a run with a profile switch and a compare of the four takes.
- AC-M14 (TICKET-032, review residuals 1, 3, 4; TICKET-033, residuals 1, 2, 6): `runapi` answers a pipeline refusal by
  the type of the error, never by its path or the wording of its message, and never by a test for `--` in either.
  `FrameCapError` (the output frame grid or the key timeline over the cap) is 400 `too_long`; the key timeline's
  error, marked by its `timeline` attribute, is worded for Part 4 keys ("This clip is too long for Part 4 keys here.
  Choose another View or a shorter clip.", also from the span pre-check for View Part 4 at Frame rate Source), and the
  grid is worded by the chosen rate and names only the lower Frame rate options at which the clip fits (TICKET-034
  residual 1): at 60 "This clip is too long for 60 per second here. Choose 30 per second, Source or a shorter clip.",
  at 30 "This clip is too long for 30 per second here. Choose Source or a shorter clip."; View Part 4 gets the Part 4
  keys text whenever its 30 per second timeline is over the cap (Source, 30, or the span at 30 over the cap at 60). A
  cap with no chosen rate keeps the table's text, "This clip is too long to run here. Choose a shorter clip." `FrameRateError` (the clip cannot be resampled at the chosen frame rate for another
  reason) is 422 `fps_refused`, field `fps`, in words with no `--` flag that name only choices the page has (its Frame
  rate options are Source, 30 per second and 60 per second): no output frame holds the person at 30 is "No frame at 30
  per second holds the person. Choose 60 per second or Source.", at 60 "No frame at 60 per second holds the person.
  Choose Source." (any other accepted rate names the next higher option, else Source alone); the input times do not
  increase is "<path>: the times must increase to change the frame rate. Choose Source, or fix the times." Every
  refusal a view module raises is a `ViewError` (`LongWayError` is one): 422 `view_refused`, field `view`, the text is the
  error's `page_text` (worded from the long-way attributes `joint`, `degrees`, `from_index`, `to_index`, `limit_deg`,
  with no regular expression over the message). Any other `ContractError` is `contract`. A test scans `part3/` with
  `ast` and fails on a `ContractError` or `OptionError` raised with a `--` path that is not a `ViewError`,
  `FrameCapError` or `FrameRateError` and is not listed there as command-line only. The scan counts each (file, path
  text) so a second refusal with listed text is not hidden, follows a path held in a variable or passed as `path=` or
  `option=`, and finds the untyped classes from the source, so a new `ContractError` subclass is scanned too (TICKET-034
  residual 5). The command line is unchanged:
  same exit codes and stderr text.

### Rule-Based ACs
- AC-NFR-M1: a 16 MiB upload runs within the run timeout on this host (measured and recorded); peak server memory for
  one such run is measured and recorded. Verification: test plus measurement in STATUS.
- AC-NFR-M2: keyboard: every control is reachable; the show or hide boxes are real checkboxes with labels; the table
  has headers. Verification: recipe and static test.

## API / Interface Contract
- `api/run` query: `sample`, `flip`, `name`, `body`, `stature`, `view`, `fps`; body: upload bytes or empty.
- `runapi.handle(sample_id, flip, name, body, options=None)`; `options = {"body", "stature", "view", "fps"}` validated
  by `runapi.parse_options(query) -> (options, error)`. The run calls `cli.process(doc, flip=..., sha256=...,
  body=profiles.resolve(flag=options["body"], stature_flag=options["stature"], env={}, config=False,
  view=options["view"]), fps=...)`
  (`config=False` means never read a file), then `views.render(native, view, keyframes="every:10")`.
- `compare.handle(body_bytes) -> (status, dict)`; caps: 16 MiB body, 2 to 6 inputs, 3,000 frames each (measured: the DTW matrix of 3,000 frames takes 0.68 s and
  223 MiB; 20,000 would need gigabytes), label 80 characters.
- Limits: `MAX_BODY = 16 MiB`, `DRAIN_MAX = 32 MiB`, `BODY_TIMEOUT_S = 60`, `RUN_TIMEOUT_S` raised only if the 16 MiB
  measurement needs it (record the number).

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| upload over 16 MiB | 413 `too_large` | "This file is over 16 MB. Choose a smaller pose3d.json file." | AC-M03 |
| bad body / view / fps / stature | 400 | "Body must be blank, simon-standard, part4-rig or measured." (and the like) | AC-M02 |
| the chosen View cannot write the clip (review R1; any `ViewError`, its `page_text`; a `LongWayError` builds it from its attributes) | 422 `view_refused`, field `view` | "This clip cannot be written as Part 4 keys: left_shoulder turns 341.3 degrees between keys 110 and 120 (Part 4 allows 180). Choose another View." or "This clip cannot be written as a Part 5 animation: frame 2: times must strictly increase (Part 5 rejects a clip whose times do not). Choose another View." | AC-M01, AC-M14 |
| the pipeline's own frame grid over the cap (a `FrameCapError` with `timeline` False, review R1) and the span pre-check of any other run | 400 `too_long` | by rate: "This clip is too long for 60 per second here. Choose 30 per second, Source or a shorter clip." (30 left out when the span is over the cap at 30 too); "This clip is too long for 30 per second here. Choose Source or a shorter clip." | AC-M01, AC-M14 |
| the Part 4 key timeline over the cap (a `FrameCapError` with `timeline` True, or a grid cap at 30 per second or less at View Part 4), or the span pre-check for View Part 4 whenever the span at 30 per second is over the cap | 400 `too_long` | "This clip is too long for Part 4 keys here. Choose another View or a shorter clip." | AC-M14 |
| the clip cannot be resampled at the chosen Frame rate and it is not the cap (a `FrameRateError`): no output frame holds the person | 422 `fps_refused`, field `fps` | at 30: "No frame at 30 per second holds the person. Choose 60 per second or Source."; at 60: "No frame at 60 per second holds the person. Choose Source." | AC-M14 |
| the same, the input times do not increase | 422 `fps_refused`, field `fps` | "pose3d.frames[2].t_ms: the times must increase to change the frame rate. Choose Source, or fix the times." | AC-M14 |
| any other `ContractError` (the validator, the adapters, a pipeline break) | 422 `contract`, field the failing path | "This file is not a valid pose3d.json: <field>: <reason>." | AC-M09 |
| compare with 1 or 7 inputs | 400 `compare_count` | "Compare needs 2 to 6 inputs." | AC-M04 |
| compare bad shape | 400 `compare_shape` | "Input <k>: angles must be a list of frames." | AC-M04 |
| one input fails in Compare | page stops, names the input | "Input 3 (my.json): pose3d.frames[0].t_ms: missing ..." | AC-M09 |

## Edge Cases
- The same sample twice: allowed; their pair p95 is 0 (AC-M07).
- An input with very few frames: compare still answers; the table shows its frame count (AC-M04).
- WebGL missing: metrics, table and downloads still work (as run-app).

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|---|---|---|---|
| Performance | 16 MiB run | within the run timeout, measured | AC-NFR-M1 |
| Security | uploads | 16 MiB cap, kept guards, no file paths from requests | AC-M02, AC-M03 |
| Accessibility | controls | labelled, keyboard reachable | AC-NFR-M2 |
| Compatibility | browsers | current Chromium, Firefox, WebKit | recipes |
| Reliability | one bad input | named, others kept | AC-M09 |

## Negative Requirements
- MUST NOT store an upload on disk. Why: run-app rule kept.
- MUST NOT accept `file:` profiles, config files or env selection from a request. Why: no server paths from visitors.
- MUST NOT post all inputs in one request. Why: memory.

## Traceability
| AC | Test or evidence |
|---|---|
| AC-M01, M02 | `tests/part3/test_runapi.py`, `tests/part3/test_runapi_options.py` |
| AC-M14 | `tests/part3/test_fps_refusal.py` (by rate), `tests/part3/test_runapi_options.py` (the View refusals), `tests/part3/test_frame_cap.py` (the grid and the timeline cap), `tests/part3/test_schema.py` (the four types), `tests/part3/test_typed_refusals.py` (the `ast` scan); the test helpers are in `tests/part3/runapikit.py` |
| AC-M03 | `tests/part3/test_server.py`, verify `limits` |
| AC-M04 | `tests/part3/test_compare.py` |
| AC-M05..M10 | recipes `compare-four-takes`, `compare-mixed-inputs`, `run-profile-switch`, `run-view-switch`; `tests/part3/test_web_static.py` |
| AC-M11 | `staging/verify.sh` run |
| AC-M12 | `qa/runs/recipe-*` validated bundles |
| AC-M13 | `demo/staging-walkthrough.mp4`, `demos/videos/orchestrator-review.md` |
| AC-M15, M16 | `tests/part3/test_web_node.py` (run under node), `tests/part3/test_web_static.py` (the wiring); the helpers are in `tests/part3/webkit.py` |

## Dissent Review
- "Client-sent angles could be faked": accepted risk, explained above; the server recomputes nothing it did not run,
  and the four-take figure is checked against `make check-3` by verify.
- "Raising the body deadline weakens slowloris protection": bounded by the connection cap and the reserve slot.

## Delivery Verification Plan
- `python3 -m pytest tests/part3 tests/staging -q`, including the server limit and compare tests.
- `firm/staging/staging.sh up simon-part-3`, then `staging/verify.sh http://127.0.0.1:7120/simon-part-3/` and
  `firm/staging/staging.sh verify simon-part-3`, both exit 0 on the integrated build.
- The recipes `compare-four-takes`, `compare-mixed-inputs`, `run-profile-switch`, `run-view-switch` and the six
  existing ones driven by hand through the gateway after the final implementer commit, each validated by a different
  agent (`verify-run-bundle.sh --require-validated` exit 0).
- `demo/staging-walkthrough.mp4` recorded once, uninterrupted, frames reviewed in `demos/videos/orchestrator-review.md`.
- Screenshots of Run (each switch) and Compare at desktop and phone width in `demos/screenshots/`, read one by one.

## Deviations (recorded at integration, 2026-10-28)
- Compare frame cap 3,000, not 20,000 (measured above).
- Per-pair p95 is read off the shared alignment of all inputs; a pair with input 0 equals `spread_stats(dtw_samples([a, b]))`.
- A blank Body (the page's "Default for the View") is resolved as no `--body` (`selected_by: default`), so its bytes
  equal a plain `python3 -m part3 run --view <view>`; a named Body is resolved as `--body <name>` (`selected_by: flag`),
  `simon-standard` included (2026-10-28, ASM-012: before, `simon-standard` from the page counted as the default).
- Measured 16 MiB (Lane E): native 4.1 s and 392 MiB peak RSS; `measured` + `part4` + 30 fps 15.3 s and 769 MiB;
  60 fps on a maximal file answers `timeout` at 20 s (the worker finishes on its own and holds its slot until then).
- `web/controls.js` holds what `web/app.js` and `web/compare.js` had twice: the DOM and number helpers, the one
  `api/run` request builder and answer check (`sendRun`, `call`, `runAnswer`), the option and file checks, the badge,
  the alert, the download, the "3D needs WebGL" note, `ensureStage`, `markView` and the frame player
  (`createPlayer`: play, pause, step, slider, keys, the animation loop). Each page keeps its own stage, `showView`,
  frame drawing, result filling and busy handling. Both pages now send the `api/run` query in the same order
  (`flip`, `body`, `stature`, `view`, `fps`; `name` first for an upload), which the server does not depend on.
  The Compare page's `state.overlay` is `state.stage`, as on the Run page. Pure refactor: no id, label or string changed.
- Review B1 (2026-10-28): the run's work grows with the clip's time span, not the upload size. The server refuses a
  request whose span times its frame rate (the chosen fps, 30 for the part4 view) is over 20,000 frames, with 400
  `too_long` "This clip is too long for that frame rate here. Choose a lower frame rate or a shorter clip.", before
  any run; the pipeline itself refuses over 100,000 (`resample.MAX_FRAMES`).
- Review residual 7: a 16 MiB upload with `measured`, `part4` and 60 fps took 22.5 s and 1.2 GiB peak and answered
  `timeout` (reviewer measurement); the 20,000-frame cap above now refuses it before it runs.
- Review residual 6 (run slot taken before the body is read, body deadline 60 s): kept as designed in run-app.md
  (a flood gets `busy`); two slow uploads can hold both slots for up to 60 s.
- Review residual 11: a staging upload without `t_ms` gets "pose3d.frames[0].t_ms: missing; add t_ms to every frame or
  a top-level fps." (the page has no `--input-fps`); `api/compare` over 16 MiB answers "This compare request is over
  16 MB."
- Review N1 (second batch): the footnotes under the panels no longer say the output limb lengths are "not the person's
  own", which is false for Body "Measured from the clip" (the clip's own median lengths). The Run page says the output
  is rebuilt on the Body you chose with the same limb lengths in every frame; Measured uses the clip's own median
  lengths, left and right averaged, and a Height scales whichever Body you chose. On the Compare page each input gets
  its own measured body, so the page claims no single body across inputs (the overlay caption is "Aligned outputs, all
  inputs overlaid").
- Review R1 (second batch): a refusal by the chosen View reached the page as 422 `contract` "This file is not a valid
  pose3d.json" with a command line flag in it. `runapi` now tells the pipeline's refusals apart by their type, never by
  their path or wording (TICKET-032 replaced the first version, which read the path prefix and a regular expression):
  a `LongWayError` and any other `--view ...` refusal is 422 `view_refused` (field `view`, flags dropped), a
  `FrameCapError` (the `--fps` grid or the `--keyframes` timeline over the cap) is 400 `too_long`, a `FrameRateError`
  is 422 `fps_refused` (field `fps`). Any other `ContractError` stays `contract`.
- Review residuals 1, 3, 4 and 9 (TICKET-032): the first version answered every `--fps` path `too_long`, so a sparse
  upload at Frame rate 30 (the person in 2 of 6 frames over 60 ms) was told "Choose a lower frame rate" when 60 runs.
  Now only the cap is `too_long`; "no output frame holds the person" and "times must increase for --fps" are
  `fps_refused` with page words (AC-M14). The long-way refusal carries joint, degrees, keys and limit as attributes, and
  the long-way next step ("add keys between them (a smaller every:<n>) or use another view") is one constant,
  `rig.LONG_WAY_FIX`, used by the part4 view and by `doctor` (so `doctor` no longer adds "or more keys in the keyframes
  file").
- Review R9 (second batch): the `.tables` box of the Compare page scrolls sideways on a phone, so it is a focusable
  region labelled "Result tables" (`tabindex="0" role="region"`) that the keyboard can scroll.
- Review residuals 1, 2, 4, 6 and 7 of the TICKET-032 batch (TICKET-033): the refusal copy named choices the page does
  not have ("leave Frame rate blank"; "Choose a higher frame rate" at 60, the highest). It now names the page's own
  options by rate (AC-M14). `runapi` no longer reads `--view` out of a path or `--` out of a message: every refusal a
  view raises is a `ViewError` with a `page_text`, and a test scans `part3/` so a new untyped option refusal cannot reach
  the page as "not a valid pose3d.json". The command-line-only refusals (`--person`, `--keyframes-out`, `--fps` value,
  `--keyframes` spec, `--keyframes-person`, `--input-fps`, and the view registry's own checks) stay `ContractError` and
  are listed in that test. View Part 4 at Frame rate Source over the cap no longer advises a lower frame rate (the
  timeline is fixed at 30 per second): `FrameCapError` carries a `timeline` attribute (replacing `colon`) and answers
  "Choose another View or a shorter clip." The cross-module test imports are gone (`runapikit.py`, `part5rules.py` and
  more helpers in `clipkit.py`).
