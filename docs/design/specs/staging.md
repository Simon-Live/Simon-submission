# Spec: Part 5 staging stack, analysis API, verify suite, QA recipes and walkthrough video
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. Hub contract: the maintainers' staging contract (port 7123, prefix route).
Companion: `viewer.md`. Tickets: TICKET-006 (API, server, `scripts/dev.sh`), TICKET-007 (S0 page),
TICKET-008 (stack, S0 verify), TICKET-022, TICKET-024 (M3 verify, recipes, walkthrough).
Follow-up of 2026-10-31 (lane stage-j1): verify, recipes and walkthrough follow ADR-0012 (no refusals), J1
(timed line and score) and ADR-0014 (insights); see `viewer.md` AC-V06 and AC-V14 to AC-V18.
Staging QA fixes of 2026-10-31 (lane fix-ux): `viewer.md` AC-V19 (the hint follows the pick) and AC-V20 (a stale result
is marked and cannot be downloaded); the recipes name the files their drives save.
Mode select of 2026-10-31 (lane profiles-web, TICKET-042, ADR-0016): the API takes an optional `profile`, `api/samples`
lists the modes, and verify and a recipe drive the page's "Mode" select (`viewer.md` AC-V21, `profiles.md` AC-PROF-15).
Delivery fixes of 2026-10-31 (lane delivery-fixes): the API analyses a labelled sample with its foot files (AC-S10).
Walkthrough notes of 2026-11-01 (lane qa-notes-web, TICKET-057): the picker words every label in the analysis's timed words
(AC-S10, WR9), the walkthrough files and their review frames are named, with one key-moment frame per step (WR5, WR1, WR6).
Walkthrough residuals of 2026-11-01 (lane walkthrough-r, TICKET-062): the score frame is described by its form, the upload
keeps the fixture's file name, and two key moments are added, `low-confidence` on desktop and `score` on the phone.
Milestones: S0 (target 2026-10-29), M3 (target 2026-11-01). Use cases: uc-analyse-take, uc-correct-take,
uc-wrong-movement, uc-real-takes.

## Overview
A visitor opens `/simon-part-5/` on the firm gateway, picks (or uploads) an expected clip and a follower
take, presses Analyse, and the server runs the real `part5` pipeline (no precomputed result) and returns
`analysis.json` plus a replay payload. S0 ships pick, Analyse, the fault list and the download. M3 adds
the 3D replay, upload, the warning panel, the phrasing switch, the real-takes list and the result preview
(`viewer.md`). The server is Python stdlib (`python -m part5 serve`), one HTTP entry on
`127.0.0.1:7123`, serving under `STAGING_BASE_PATH`.

## Why This Is Wrong (Dissent-First)
1. Running analysis in the request thread can stall the server on a large upload. Answer: 16 MiB and
   6000 frames per clip, one analysis at a time, 60 s timeout.
2. A sample picker that lists 216 takes is unusable. Answer: grouped by set, angle and light, with the
   fault in the label.
3. Staging that only proves the happy path hides the warned take. Answer: verify drives a take of another
   movement (analysed with a warning and graded F, ADR-0012) and a bad upload.

## User Story
As a follower, I pick or upload the expected movement and my take and see each fault in plain words.

## API (all paths relative to the base path; JSON in and out)
| Method and path | Request | Response |
|---|---|---|
| `GET api/health` | | `{ok: true, version}` |
| `GET api/samples` | | `{expected: [{id, set, movement, label}], followers: [{id, set, angle, light, label, faults}], phrasing: [<offered backends>], phrasing_default: <one of them>, profiles: [<mode names>], profile_default: "fitness"}` from committed fixtures; `profiles` and `profile_default` are listed by a server that knows modes (`profiles.md`) and absent from an older one |
| `POST api/analyse` | `{expected: {sample: id} \| {upload: <json>}, follower: {sample: id} \| {upload: <json>}, phrasing: "template" \| "local-llm" \| "muse-spark", profile?: "dance" \| "rehab" \| "fitness"}` | `{analysis: <simon.analysis.v1>, replay: {fps, expected: [[[x,y,z] x17] per frame], follower: [...], exp_to_fol: [follower frame per expected frame], joints, bones}}` |
| `GET api/real-takes` | | the real-take report (`real-takes.md`) |
| `GET api/contract` | | `python -m part5 contract --json` output |

- Errors: HTTP 400 `{error: {field, message}}` in plain words naming the field (for example
  `follower.upload: frames[12].joints.left_knee: not a list of three numbers`); 413 over 16 MiB; 404 an
  unknown sample id; 500 never shows a stack trace.
- A take that does not match the example returns 200 with `analysis.status.code: "ok"`, `analysis.warnings`
  (for example `low_match`), `analysis.match`, faults that may carry `confidence: "low"`, and a `score` capped
  at 59 (grade F) with `score.capped_by` (ADR-0012). The API no longer answers `different_movement`.
- Each fault has `text_timed`, `at_s` and `lateral` and, in live mode, a `coaching` line; the analysis has
  `score` and, from schema 1.5.0, `cue`s and `insights` (J1, ADR-0014). The page reads them (`viewer.md`).
- Phrasing: `api/samples` (or `api/health`) lists the backends this server offers; `muse-spark` is offered
  only when the Baseten key file exists on the server and `META_LIVE=1` is set
  there (`staging/env.sh` sets it only when the key file exists). The key is read server side at the call
  and never reaches the browser or any response. `phrasing_default` is the backend a request that names none
  would get (`part5.phrasing.select_backend`, ADR-0008): `muse-spark` in live mode with the key file,
  `template` otherwise, and always one of the offered backends. The page's "Wording of the faults" select
  starts on it (`viewer.md` AC-V19), so a visitor to the staging page reads model wording unless they choose
  the template. Verify, the walkthrough and the recipes that do not test wording choose Template themselves. Requests asking for `muse-spark` are rate limited per
  client address (one at a time, at most 6 per minute); over the limit the server answers HTTP 429
  `{error: {field: "phrasing", message: "Too many Muse Spark requests. Wait a minute or pick template."}}`.
- Modes (TICKET-042, ADR-0016, `profiles.md`): `profile` is optional; omitted or `null` means `fitness`, a name that is
  not in `profiles` is HTTP 400 with field `profile`, and every `analysis` carries the `profile` that scored it. The page
  offers a "Mode" select only when `api/samples` lists `profiles`, starts it on `profile_default`, sends its value as
  `profile` and names a mode other than `fitness` in the result (`viewer.md` AC-V21). A server that lists no modes gets no
  select and no `profile`, so the page and the API can be merged in either order. Verify and the recipes keep the
  Template wording in every mode.
- Foot side files (ADR-0015, AC-S10): a sample whose label names `expected_feet` or `follower_feet` (all 156 seed 5 takes
  and their two trainer sets) carries that file in the table, read from the label like every sample file and checked to
  be under `fixtures/input`. A request whose two sides are both such samples is analysed with the files
  (`score_report.feet_kwargs` turns the names into `pipeline.run` options, AC-FOOT-18), so a take whose fault is in the
  feet shows it and `analysis.diagnostics.feet` is present, naming each file from the repository root and never this
  server's path. An upload on either side, the Part 3 kit and the real clips carry no foot file: a request with one of
  them is analysed exactly as before, with no `diagnostics.feet`.
- No value from a request becomes a filesystem path: sample ids resolve through an in-memory table built
  at start; uploads are parsed in memory and never written.
- Code: `part5/api.py` (pure functions), `part5/replay.py`, `part5/server.py`
  (`python -m part5 serve [--host 127.0.0.1] [--port 8725] [--base-path /]`).

## Staging stack (`staging/`, firm only, never published)
- `env.sh` (shared defaults: `STAGING_PORT` 7123, `STAGING_BASE_PATH` `/simon-part-5/`, state root in the maintainers' state directory), `up.sh` (idempotent; refuses outside the staging checkout;
  stamp over committed app files; pid and log under the state root; `setsid nohup python3 -m part5 serve`
  with the cleared environment; uses `uv run` only when `uv` is on the cleared PATH, otherwise
  `python3` with numpy importable, decided at TICKET-008 and recorded), `down.sh`, `health.sh` (only
  `STAGING_PORT`, default base path, exit 0 when `api/health` answers), `verify.sh [<base-url>]`,
  `verify.mjs` (with the modules it imports, each under 800 lines: `verify-kit.mjs` for the helpers every drive shares,
  `verify-modes.mjs` for the Mode select, `verify-wording.mjs` for the wording select and the picker's label words),
  `walkthrough.mjs`, `walkthrough-frames.sh` (the key-moment frames of the recording, "QA recipes and video"), `DEMO.md`
  (visitor sections only under "For visitors").
- No secret is committed or copied into the staging tree; the only key the server may read is the
  operator key file above, from its firm location.
- `staging.sh up simon-part-5` then `staging.sh verify simon-part-5` exit 0. The registry
  staging environment `status: available` lands through the run's own hub PR that edits only
  `engagements/simon-part-5.yaml` (brief, section 0).
- Local dev: `scripts/dev.sh` (firm only) starts the server on `127.0.0.1:8725` detached; `scripts/dev.sh
  stop` stops it; health `curl -fsS http://127.0.0.1:8725/api/health`. `make demo` (published) serves in
  the foreground on its own port, 8735, so the two never clash. The server stops on SIGINT or SIGTERM with exit code 0 and
  a clean log: its SIGTERM handler is one-shot (the first TERM sets SIG_IGN, then exits `serve_forever`), so a second TERM
  from `make` or `uv run` during interpreter shutdown is ignored (`tests/test_server.py`,
  `test_serve_stops_with_exit_0_and_a_clean_log_on_repeated_sigterm`).

## Verify suite
`staging/verify.sh` runs `staging/verify.mjs` with Playwright 1.61.1 (pinned in a local-only
`package.json`, never published) through `scripts/with-browser-slot.sh`, against the base URL argument
(default the staging gateway address), with HTTP basic auth from the gateway login (passed in the environment, never printed), never a blanket Authorization header. S0 drive: load, pick Squat and a labelled
feet-wide take, Analyse, read the faults, download `analysis.json` and validate it; a correct take shows
"no faults". M3 drive adds: replay plays, tapping a fault moves the frame and highlights the joint, an
upload of a good and a bad file, the warning (class yoga or dance against the squat: status ok, a `low_match`
warning in the warning panel, grade F, a score of 59 or less, no error), the phrasing switch (template; a fresh
page starts the select on the `phrasing_default` that `api/samples` names, which it offers, AC-V19; every analysis
verify presses chooses Template first, so verify makes no live call), the real-takes list, the result preview at
390 px. J1 and ADR-0014 add: a take with a fault shows its score and
grade, each fault row starts with a timed line matching `/ at \d+\.\d s/` (template wording, so no live
call), the insights list shows when the file has insights, and the preview shows the score. The staging QA fixes add:
the hint under the wording select follows a pick and returns when the default is picked again (AC-V19), and a result
made for another choice is marked with the stale line and loses its download link until Analyse is pressed again
(AC-V20: a changed take, example, upload, wording or mode; the saved file is the last pair's). The Mode follow-up adds
(AC-V21, AC-PROF-15): the select appears exactly when `api/samples` lists modes (checked on the server's own listing and
on stubbed listings that give none, an empty list, three modes, a default of rehab and a default that is not offered);
an untouched page sends and shows `fitness`; Analyse with Rehab on a feet-wide take sends `profile: "rehab"`, the result
names the mode and the saved file says `rehab`; the fitness analysis equals the one a request naming no mode gets, apart
from `profile`; a page for a server with no modes sends no `profile`. Where the server does not list modes yet, those
checks run on a stubbed listing and a stubbed answer that echoes the mode asked for, and say so in their names. The
delivery fixes add (AC-S10) a foot-fault take (Take 09, the right foot turned out) analysed with Template wording: the
page shows a foot rotation fault line and not "No faults found", and the answer carries `diagnostics.feet` with
repo-relative sources; Take 11 (the left ankle roll), whose picker label and shown ankle line name the same roll
direction; Take 03 (the right foot planted too far out), whose picker label says "too far right" like the row the page
then shows and never "too far out" (AC-S10 for every measure); and (AC-V10) at 390 px every visible tab, button, select,
file picker and the scrubber is at least 44 px tall, the visible "Choose File" button of each file picker included, and
the preview's field name "Why the grade is limited" is one line. The exit code is the verdict.

## QA recipes and video
- Recipes with the `qa-recipe` skill (ADR-0020), one per use case driven on staging: each edge driven by
  hand through the real UI, two independent witnesses, a negative assertion (for example a warned take is
  never called a correct take; a correct take shows no fault rows).
- The walkthrough is two videos in `demos/videos/`, `staging-walkthrough-desktop.mp4` (1100x800) and
  `staging-walkthrough-phone.mp4` (390x844), H.264, each converted from its own recording and never joined
  (`staging/walkthrough.mjs` records each browser page as its own video). Both are gitignored (`.gitignore`, `*.mp4`);
  what is committed is `demos/videos/frames-desktop/`, `demos/videos/frames-phone/` and `demos/videos/orchestrator-review.md`,
  the review the orchestrator writes before any reviewer runs (what was recorded, when, from which commit, and what each
  frame shows). They are recorded through the firm gateway at the staging gateway address, by
  `staging.sh exec simon-part-5 -- env P5_DRIVE=walkthrough bash staging/verify.sh` (the login reaches the
  browser as HTTP credentials and is never printed), so the page they show is the one the gateway serves. Limits, per
  file and together: each file under 90 s and under 15 MB, and the two together under 90 s and under 15 MB
  (`walkthrough.mjs` refuses a recording over 88 s, so a joined video would also stay under 90 s); no still stretch of
  5 s in either (`ffmpeg freezedetect n=-60dB:d=5` finds none, so a hold is never lengthened to give a frame more time).
  The steps, in order: pick, Analyse (score, timed lines), replay, tap a fault, upload (the committed Take 03 fixture,
  sent under the file name it has on disk, so the page shows "Using your file: skeleton.json"; every labelled take's
  follower file has that name, so the orchestrator's review names the fixture's repository path to say which take it is),
  a different movement warned and graded F and then its fault rows with their low confidence notes (AC-S06), the real
  takes, and on the phone Analyse with its own score, then the preview at phone width. The recording chooses Template
  before each Analyse (AC-V19), so it makes no live call.
- Review frames, read from the videos. The sampled frames (`frame-NNNN.png`, one every 4 s of the desktop video and one
  every 3 s of the phone video) stay as they were. After recording, one settled key-moment frame per step is added
  (TICKET-057, walkthrough review R1 and R6; TICKET-062, third review R1, R4 and R5): `key-NN-<step>.png` in the
  segment's frames folder, `NN` counting the steps of that video, `<step>` one of `pick`, `score` (the score line, in the
  form "Score: N out of 100, grade G", where N and G are the value and grade the served analysis of Take 03 gives; this
  spec fixes no number, so a change of score version does not make it wrong), `replay` (with the timed fault line),
  `tap-fault`, `upload`, `warned`, `low-confidence` (the same warned result scrolled to its fault rows, each showing its
  low confidence note) and `real-takes` on desktop, and `score` (the phone's own Analyse result, with the same score
  line) and `preview` on the phone, so the phone's frames are `key-01-score.png` and `key-02-preview.png`.
  `walkthrough.mjs` writes `walkthrough-key-moments.txt` next to the videos, one `<segment> <step> <end> <start>` line per
  step: the end and the start, in seconds on the drive's clock, of a hold the drive already makes, so a mark adds no
  pause. A mark must directly follow the pause it ends and refuses to run without one. `low-confidence` shares the
  hold `warned` had: that 2.5 s hold is split into two of 1.5 s, the first on the warning panel and the second on the
  fault rows, so the recording is 0.5 s longer and the phone's `score` mark adds nothing.
  `staging/walkthrough-frames.sh <key-moments.txt> <desktop video> <phone video> [<frames-root>]` then reads each frame
  at the middle of its hold, `(start + end) / 2` on the drive's clock (exit 0 every frame written, 1 a hold too short for
  the margin below, a key frame that changes in the video beside its reading, or a frame that could not be read, 2 a bad
  argument or line, a line without a hold start, or a frames folder that already holds a `key-*.png`; `<frames-root>`
  defaults to `demos/videos`). The video does not run on that
  clock. Measured on the 897ddad recording, a frame read at second T of the desktop video shows the page 0.22 to 0.36 s
  after T on the drive's clock, and on the phone 0.06 to 0.08 s after T; the video also ends 0.06 to 0.4 s before the
  drive's last mark. The script corrects for none of this. Half of a hold has to cover the largest lag measured, and the
  sign of the lag is not assumed, so the middle must be 0.4 s or more from each end of its hold. A shorter hold is
  refused with exit 1 before any frame is written, which makes 0.8 s the shortest hold accepted (0.79 s, which is 0.8 s
  within mark rounding: the marks are written to 0.01 s). The shortest hold the drive makes is `replay`, at 0.8 s: at the largest desktop lag it
  keeps 0.04 s before its end, as the old fixed offset did, and every other hold keeps more, because the margin grows
  with the hold. That margin is on the drive's clock, so the script also compares each key frame with the video's own
  frames 0.12 s before and after it, and removes the frame and exits 1 when either differs in more than 64 pixels (a
  pixel counts when a colour value moves by more than 32 of 255; 64 is twice the noise measured on the committed
  videos, set before the check ran on a key frame, and `SETTLE_REPORT=1` prints each count). A key frame whose middle
  falls past the end of its video is read from the last frame only when that
  frame comes after the hold's start and is within the loss measured at the end of a video, else the script exits 1
  (TICKET-065, TICKET-067). A moments file from before the start marks (`<segment> <step> <seconds>`) is refused with
  exit 2 and a request to re-record, because a guessed offset would bring the old margin back. The old frames
  are archived before a re-record: the script refuses ("archive the old frames first") before it writes anything, so a
  changed step list never leaves old frames beside the new ones. The orchestrator records and commits them; this step
  is the one command that turns a recording into the frames.

## Acceptance Criteria
### AC-S01: S0 live
Given `staging.sh up simon-part-5`, when verify runs the S0 drive, then exit 0 and the downloaded
`analysis.json` validates against `contracts/analysis.schema.json`.
### AC-S02: health without variables
Given no variables, `staging/health.sh` probes `127.0.0.1:7123/simon-part-5/api/health`.
### AC-S03: idempotent up
Given a running stack, a second `up.sh` exits 0 "already running"; a changed checkout restarts it.
### AC-S04: real pipeline
Given an Analyse request, the server calls `part5.pipeline.analyse`; no cached result exists in the tree.
### AC-S05: plain errors and cap
Given a 17 MiB upload, 413 with a plain message; given a bad joint, 400 naming the field; never a trace.
The 6000 frame cap counts the frames a clip has once the follower is put on the expected clip's clock
(`part5.pipeline.MAX_FRAMES`, checked before it is resampled), so a 3 frame follower whose `t` spans
1000 s is a 400 naming `follower.upload`; an expected clip faster than 240 fps (`MAX_FPS`) is a 400
naming `expected.upload`.
### AC-S06: a different movement is warned and graded F through the UI
Given class yoga against the squat, the page shows the analysis with a `low_match` warning in the warning
panel, grade F, a score of 59 or less, faults marked low confidence, and no error (`viewer.md` AC-V06, AC-V17).
### AC-S07: M3 verify
Given the M3 drive, every step in "Verify suite" passes and verify exits 0.
### AC-S08: recipes and video
Given the recipes, each validates with two witnesses; the walkthrough exists within its limits.
### AC-S09: no path from requests
Given a sample id `../../etc/passwd`, 404 and no file read outside the table.
### AC-S10: a labelled take is analysed with the foot files its label names
Given `POST api/analyse` with `{sample: exercise}` and `{sample: exercise_front_good_09_foot_turned_out-right}` (Take 09)
Then the answer has one fault, `foot_rotation` on the right side, a score below 100 and `analysis.diagnostics.feet` whose
two `source` values are the repository-relative paths of the label's `expected_feet` and `follower_feet`; the document
equals `pipeline.run` given `score_report.feet_kwargs` of that label. Given an upload on either side, or a Part 3 kit
take, the answer is the one the pipeline gives without foot files and has no `diagnostics.feet`. Before this
criterion the API ignored the label's foot files and showed "No faults found" and 100 A for Take 09 (delivery review
B1). Tests (`tests/test_api.py`): `test_a_sample_take_is_analysed_with_the_foot_files_its_label_names`,
`test_the_sample_answer_is_the_pipeline_run_with_the_labels_feet_files`,
`test_the_feet_sources_in_the_answer_are_repo_relative_never_this_servers_path`,
`test_every_generated_sample_carries_its_label_feet_and_every_other_sample_none`,
`test_a_take_with_no_foot_files_is_analysed_as_before`; `staging/verify.mjs` (`driveFootFault`).

The picker words a foot take as the analysis does (delivery review N1). Given `GET api/samples`, then for a take whose
label type maps to `foot_rotation` or `ankle_inversion` (`evaluate.LABEL_TYPE_TO_MEASURE`, the 48 foot takes) the
picker `label` and the listed `faults[].text` are `words.phrase(measure, direction, side)` for the label's own measure,
direction and side, without a quality word, and `faults[].type` and `side` are the label's own. Take 11 (the left ankle
roll) reads "Take 11: Left ankle rolling out" and its analysed fault line reads "left ankle rolling out slightly", so the
two point the same way; before this criterion the picker said "rolled in" over a result that said "rolling out", because
the label file keeps its old wording on purpose (`foot-keypoints.md`, "The ankle label ids read the old way round").
Every generated take's picker label starts "Take NN:" with the take's own number,
the digits after the light field of its id (`part5/api.py` `_take_number`); the 45 degree takes were all numbered "Take 45"
because the first digit group of their id is the angle, and front and side labels keep their numbers. Tests
(`tests/test_api.py`):
`test_every_generated_take_label_starts_with_the_takes_own_number_the_45_degree_ones_included`,
`test_front_and_side_labels_keep_the_number_they_had`,
`test_every_foot_take_is_worded_in_the_picker_and_the_listing_as_the_analysis_words_it`,
`test_the_ankle_label_ids_and_the_label_file_keep_their_old_words_and_only_the_page_changes`,
`test_take_11_picker_label_and_its_analysed_fault_line_point_the_same_way`; `staging/verify.mjs` (`driveFootLabel`, called
by `driveFootFault`) picks Take 11 and checks the option's roll word, the listed fault's and the ankle line the page then
shows.

The picker words every label, not only the foot ones (walkthrough review R9, TICKET-057). Given `GET api/samples`, the
picker `label` and the listed `faults[].text` of every generated take and every Part 3 kit take are the analysis's timed
words for the label's own measure, direction and side, without the time and without a quality word:
`words.phrase_timed(measure, direction, side)`,
the line `faults[].text_timed` carries before its " at N s", at the plain size because a label does not know the measured
size. `lateral` is derived from the label's side and direction as the analysis derives it (`lateral_for`, inside
`phrase_timed`), so Take 03 reads "Take 03: Right foot too far right", not "too far out", over a result that says "right
foot too far right at 1.9 s". `faults[].type` and `side` stay the label's own. The kit's labels name their measures in
Part 3's own vocabulary, which `evaluate.canonical_label` (the matching rule, unchanged) does not know, so a kit type is
worded through `real.KIT_TYPE_MAP`, the map the real-take report already matches the kit by, with the label's side:
`feet_wide` reads "Feet too far apart" (it was "Feet too wide"), `elbows_out` "Elbows wider than the example" (it was
"Elbows too far out"), `shallow_squat` "Knees not bent enough" (it was "Knees not bent enough at the bottom") and
`knee_caving` "Left knee caving in" (it was "Left knee caves in at the bottom"), for the front, 45 degree and side kit takes
alike; the kit's labels file keeps its own words. Only a label of a type neither map knows, or with no direction or a side
its measure does not take, keeps its own `text`. Label ids, the label files and every fixture byte are unchanged, and so is
every `analysis.json`. Property: for every seed 5 good light take and every kit take whose analysis reports its labelled
fault on the label's own side, the picker words equal that fault's `text_timed` with " at N s" removed and with the size
word removed (`slightly`, `much`, `not quite`, `nowhere near`; those are the measured size, which only the analysis knows),
in sentence case; on the other takes (a label that names both sides where the analysis reports one) the picker still says
the analysis's words for the label's own side. Checked on 2026-11-01 over all 156 generated takes and the 15 kit takes
against the analysis of each: 115 of the 126 labelled faults that the analysis reports read the same, the other 11 are
labels naming both sides over a result that names one (plural against singular, same direction), and 30 are not reported
at all, so there is nothing to compare. Tests
(`tests/test_api_picker_words.py`):
`test_every_generated_label_is_worded_as_the_analysis_words_it_timed_and_the_label_files_are_unchanged`,
`test_take_03_is_listed_as_too_far_right_and_never_as_too_far_out_while_its_result_says_too_far_right`,
`test_for_every_good_light_take_whose_analysis_reports_its_labelled_fault_the_picker_words_are_its_timed_words`,
`test_a_correct_take_keeps_its_words_and_a_label_the_analysis_has_no_words_for_keeps_its_own_text`,
`test_the_size_words_are_the_ones_the_analysis_uses`; in `tests/test_api.py`
`test_the_kit_takes_are_listed_with_the_kit_labels_and_no_invented_light`; and, in `tests/test_words.py`,
`test_phrase_timed_is_what_describe_timed_says_at_every_size` and
`test_phrase_timed_derives_the_lateral_from_the_side_and_direction_as_the_analysis_does`; `staging/verify.mjs`
(`driveLateralLabel` in `verify-wording.mjs`) picks Take 03 and checks that "too far out" is absent from its label while the
row the page then shows says "too far right at N.N s". Negative assertion: no picker label or listed fault of Take 03 reads
"too far out".

### AC-S11: a long terminal transcript is drawn in whole steps, never cut
`qa/tools/render_transcript.py <transcript.txt> <out.png> [--max-lines N] [--cols N]` draws the `.txt` of a terminal frame
(`qa/INTERFACE.md`, "Terminal frames") as PNG frames. It is firm QA tooling: `qa/` is on the publish denylist and not in
`.simon-publish`, so it is never published.
- Given a transcript that fits in `--max-lines` drawn lines (default 100; a line wider than `--cols`, default 150, wraps and
  counts as its rows), it writes `<out.png>` and nothing else, with no header.
- Given a longer one, it writes `<out>-p<k>of<N>.png` for k from 1 to N, and the first line of each frame names its part:
  "part 2 of 5: transcript lines 91 to 180 of 567". The parts are contiguous, overlap nowhere and together hold every line:
  no line is left out and no frame says that lines are left out. A part after the first repeats the command under its
  header, and every part but the last ends with "(continues in part k+1 of N)".
- A part ends only at a step boundary. It never ends inside a bracket group (`{...}` or `[...]` outside double quotes), a
  line with the lines indented under it, a paragraph between blank lines, the `--- stderr ---` section, the command lines
  with the first line of output, or just before the closing `$ echo $?` line, when that group is at most `--max-lines`
  drawn lines. A group longer than that cannot sit in one frame and is split at its own inner boundaries only, the
  outermost ones that fit. A part is therefore taller than `--max-lines` only when no step boundary lies within that height of its
  start: a group that has to stay whole, which in practice is a chain of overlapping groups, each at most `--max-lines`
  drawn lines, that together span it (a bracket group that spans a blank line between two paragraphs is one), or a single
  line that wraps into more rows than that. Nothing is lost in either case: the parts stay contiguous and together hold
  every line.
- Exit 0 every frame written; 1 the frames could not be drawn (Pillow or the DejaVu Sans Mono font missing; run it with
  the system `python3`, not the project venv); 2 a usage error or an unreadable transcript. Stdout has one tab separated
  line per frame: path, size, part, transcript lines, rows drawn.
Why: the first renderer kept the head (150 lines) and tail (70) of anything over 230 drawn lines. Frame 09 of
`qa/runs/20261101T113735Z-uc-integration-contract` (567 lines, 61 steps) drew step 55's lines under step 15's, and frame 03
of `qa/runs/20261101T113936Z-uc-done-check` (319 lines) left out the attempts of seeds 37 and 67 (delivery review
2026-11-01, R4b). Tests (`tests/staging/test_qa_render_transcript.py`): the two transcripts above rebuilt in their own
shape split with no step cut and no line lost, a short one is one frame with the old name, blank-line paragraphs, the
stderr section and the exit line stay whole, a group longer than the cap is split only between its children, the part
header and file names, the exit codes, and the tool stays off the publish list.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| Upload over cap | 413 | `<side>.upload: larger than 16 MiB` | AC-S05 |
| Bad JSON | 400 | `<side>.upload: not JSON` | AC-S05 |
| Contract violation | 400 | `<side>.upload: <field>: <what>` | AC-S05 |
| Too many frames once resampled, or a frame rate over 240 | 400 | `<side>.upload: <n> frames at the example's <fps> frames per second (<s> s), the limit is 6000` | AC-S05 |
| Unknown sample | 404 | `<side>.sample: no sample named <id>` | AC-S09 |
| Analysis timeout | 503 | `analysis took longer than 60 s` | AC-S04 |

## Edge Cases
- Port 7123 held by another process: `up.sh` exits 1 naming it.
- Gateway feedback widget injected into the page: the layout leaves room for it.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | Analyse round trip | under 5 s for a sample pair | AC-S04 |
| Security | Secrets | none needed; never read the staging login | all |
| Reliability | Restart | `up.sh` safe to rerun | AC-S03 |
| Accessibility | Keyboard | every control reachable | AC-S07 |

## Negative Requirements
- MUST NOT read or print the staging login or the gateway login file; never post the
  login or the gateway's public address.
- MUST NOT write uploads to disk. MUST NOT publish `staging/`, `package.json` or `qa/`.

## Non-Requirements
- Accounts, persistence of visitor uploads, a production deployment.

## Assumptions
ASM-011 (stdlib server load and the runtime in the cleared environment, `docs/assumptions/ASM-011.yaml`).

## Delivery Verification Plan
- `staging.sh up` 0, `staging.sh verify simon-part-5` 0 with sha at start and end, recipes validated,
  walkthrough recorded; S0 and M3 close-outs in STATUS.md with exit codes. The J1 plan
  (`journey-followup.md`) asks the staging page to show a timed line and the score: verify checks both on a
  faulty take, and the recipe `compare/live-timed-line-and-score` drives it by hand.

## Dissent Review
### Concern 1: stdlib server instead of a framework
Kept: Parts 3 and 6 run the same way on this gateway; no dependency to vendor.
### Concern 2: replay payload duplicates frames already in the clips
Kept: it lets the browser render without parsing uploads twice and keeps the alignment server side.

## Amendments
- 2026-10-31 (TICKET-042, `docs/design/specs/profiles.md`): `POST api/analyse` takes an optional `profile` (`dance`, `rehab` or
  `fitness`; omitted or `null` means `fitness`; any other value is a 400 with field `profile`, before any file is read),
  and `GET api/samples` gains `profiles` and `profile_default`. The `analysis` carries `profile`.

- 2026-10-31 (delivery review B1, lane delivery-fixes): `part5/api.py` passes a sample's foot side files to the pipeline
  (AC-S10, `docs/design/specs/foot-keypoints.md` AC-FOOT-18), and `staging/verify.mjs` drives Take 09. The page's controls are
  at least 44 px tall at phone width (R8, `viewer.md` AC-V10).

- 2026-10-31 (delivery review N1): `part5/api.py` words a foot take's picker label and its listed `faults[].text` in the
  analysis vocabulary (AC-S10), so Take 11 no longer says "rolled in" over a result that says "rolling out". The label
  file keeps its words; `api/samples` still lists the label's own `type` and `side`.

- 2026-11-01 (walkthrough review R9, lane qa-notes-web, TICKET-057): AC-S10 extends from the foot takes to every measure.
  `part5/api.py` words each picker label and each listed `faults[].text` in the analysis's timed words without the time
  (`words.phrase_timed`, the timed vocabulary `describe_timed` already used), so Take 03 reads "Right foot too far right"
  and no longer "too far out" over a result that says "too far right". Label ids, label files and fixture bytes are
  unchanged; so is every `analysis.json`. The log line of 2026-10-31 above stays true for the foot takes.

- 2026-11-01 (delivery review R4b, lane dr-qa, TICKET-058): AC-S11. The terminal-frame renderer is committed as
  `qa/tools/render_transcript.py` and splits a long transcript into numbered frames at step boundaries instead of
  drawing its head and tail. Drivers declare every frame it prints. `qa/INTERFACE.md` documents the call.

- 2026-11-01 (third walkthrough frame review R1, R2, R4, R5, lane walkthrough-r, TICKET-062): the score key frame is
  described by its form and no longer quotes a number the score version had changed; `staging/walkthrough.mjs` uploads the
  Take 03 fixture under its own file name instead of "my-take.json", scrolls the warned result to its fault rows for the
  `low-confidence` moment and marks the phone's own result as `score`. `staging/walkthrough-frames.sh` is unchanged: it
  numbers the steps of each video in the order the marks were made.
- 2026-11-01 (sixth walkthrough frame review R1, lane score-wrap, TICKET-065): `staging/walkthrough-frames.sh` reads each
  video's length and last frame time with ffprobe; the video ends 0.06 to 0.4 s before the drive's clock, so the last mark's
  seek time can fall past the end, and that frame is then read from the last frame, but only when it comes after the previous
  mark of the same video (else exit 1, as before). The 0.4 s offset is on the drive's clock, not the video's.
- 2026-11-01 (seventh walkthrough frame review R2, lane hold-midpoints, TICKET-068): `staging/walkthrough.mjs` writes the
  start of each hold beside its end (`<segment> <step> <end> <start>`), and `staging/walkthrough-frames.sh` reads each key
  frame at the middle of its hold instead of a fixed offset before the end. With the desktop lag measured at up to 0.36 s,
  the fixed offset left as little as 0.04 s before the end of a hold; the middle's margin grows with the hold. A hold
  shorter than twice the margin is refused, a moments file without start marks is refused, and the past-the-end read is
  checked against the hold's start instead of the previous mark.
- 2026-11-01 (eighth walkthrough frame review R1, lane closing-batch, TICKET-069): the offsets measured on the 897ddad
  recording (a frame read at second T showed the desktop page 0.22 to 0.36 s later on the drive's clock, the phone 0.06 to
  0.08 s later) did not hold for the next recording. On the d61b2f6 recording the desktop video starts a hold up to 0.34 s
  late and ends it 0.06 to 0.14 s early, the opposite sign at the start. A margin on the drive's clock cannot see that, so
  `staging/walkthrough-frames.sh` also checks the video itself: a key frame must match the frames either side of it. Its
  threshold was measured on those two videos and committed first; all ten key frames of that recording pass and are
  unchanged.

## Deviations from PRD
None.
