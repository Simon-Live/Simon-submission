# Spec: the Simon journey (eight steps, one app)

> Copy of `docs/specs/journey.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted (rescope, 2026-10-30)
Date: 2026-10-30
Request Type: feature-change
Risk Level: high (public submission 2026-11-04, cross-part follow-ups, live AI text)
ADR: ADR-0006 (amends ADR-0003 and ADR-0005). Master: `part7-stitching.md`. Companions: `app.md`,
`compare-view.md`, `processor.md` (the trainer job), `check-7.md`, `staging.md` (firm-only, not published), `demo.md`.
Tickets: TICKET-033 to TICKET-051, with TICKET-005, 006, 016, 018, 019, 020, 021, 022, 025, 028 edited.

## Overview
The operator's definition of the finished app, verbatim (2026-10-30):

> "be aggressive, fan out and complete thoroughly. The end goal is the full cohesive simon application
> stitching together all the parts: 1) Open the app. 2) Trainer can record a movement/exercise. 3) it is
> available in the cloud for others to view. 4) Users can select that upload and upload/record their
> own video of them doing the exercise/movement. 5) Goes through pipeline and we do fault analysis
> between the expected and provided (trainer's video vs viewer's) 6) Return the simulations for viewers
> to see and rotate and compare 7) Provide the fault analysis feedback such as "Foot is too far right at
> 2s" etc. 8) Provide a score out of 100 (A-F). [...] This is meant to setup for a single long running
> session to finalize the app so that user journey is completable."
>
> Follow-up: "fault text should be dynamic, using AI to generate a human understandable message".

Every step below has its screen, its API, its part commands, its acceptance criteria and one QA recipe
driven through the real UI on the staging gateway at 412x915 (desktop must also work). The journey is
done when all eight recipes are validated and the staging journey verify (`staging/verify.mjs`, firm-only) exits 0 on
the journey drive.

## Part map (who does what in the journey)
| Step | Part 7 | Parts used, by published command |
|---|---|---|
| 1 Open | shell, catalog home | Part 6 `api/entries` through the proxy |
| 2 Record | capture, upload, trainer job | Part 1 keys; Part 2 pose; Part 3 `--view part4`; Part 4 animate; Part 6 `import` |
| 3 Cloud | Watch screen, public route | Part 6 entry, `video_uri` (HTTP 206), player frame |
| 4 Follow | Follow screen, capture, upload | Part 6 follow hand-off (`simon:follow`) |
| 5 Pipeline | follower job, job screen | Part 2; Part 3 `--view part5 --fps 30`; Part 5 `analyse --replay` |
| 6 Compare | compare view | Part 5 replay file (`exp_to_fol`, per-frame joints) |
| 7 Feedback | fault list | Part 5 `text_timed`, `at_s`, live phrasing |
| 8 Score | score panel | Part 5 `score` |

## Commands (same pins and body profile on both sides)
Trainer job (`part7/chain.py trainer`, work dir `D`; `D` exists before Part 3 runs):
1. Part 1: `.venv/bin/python -m keyframe_finder.from_video inbox/p7-<sha12>.mp4` with `MODEL_API_KEY`
   from its own `.env` (written mode 600 for the call, removed after). Exits 2 (its $5 guard) and 3
   (refused), a missing key, the run-wide $5 cap, or `people: []` all take the fallback in step 3.
2. Part 2: `<gpu venv>/bin/part2 run --mode single --input <video> --out D/p2 --fps 10 --backend gpu`
   (exit 0 ok, 1 input or contract error, 2 bad option), holding the GPU lock.
3. Part 3: `python3 -m part3 run --in D/p2/pose3d.json --out D/skeleton.json --view part4 --keyframes
   <part1 keyframes.json> --keyframes-densify every:10 --keyframes-out D/keyframes.json --body
   simon-standard`. Before Part 3's follow-up is pinned, and on any Part 1 fallback: `--keyframes
   every:10` (no densify). Part 3's 180 degree refusal: retry once with `every:5`.
4. Part 4: `PYTHONPATH=src python3 -m simon_anim.animate --in D --out D/animation.json`. Part 4 errors
   are uncaught tracebacks with exit 1; Part 7 maps exit 1 to `failed:animation` and keeps the last
   traceback line in the job log only (QUESTION on the team Part 4 #1, TICKET-035).
5. Part 6: `python3 -m part6 import <I> --catalog <catalog> --name <name> --category <category> --part
   keyframes=1 --part skeleton=3 --part animation=4` (`keyframes=3` on the fallback), where `<I>` holds
   Part 1's `keyframes.json` (or Part 3's on the fallback), `skeleton.json`, `animation.json` and the
   normalized `video.mp4`; then `python3 -m part6 doctor <catalog>/<id>`.

Follower job (`part7/chain.py follower`, work dir `F`):
1. Part 2 as above on the follower take (`--out F/p2`).
2. Part 3: `python3 -m part3 run --in F/p2/pose3d.json --out F/skeleton.json --view part5 --fps 30
   --body simon-standard`.
3. Part 5: `part5 analyse --expected <entry animation.json> --follower F/skeleton.json --out
   F/analysis.json --replay F/replay.json --phrasing <p>`, where `<p>` is `muse-spark --live` on dev and
   staging (`SIMON7_PHRASING=live`) and `template` in tests and check-7 (`SIMON7_PHRASING=template`).
   Exit 0 written `ok` (with `warnings` at schema 1.4.0); 3 written with a refusal status (the pinned Part 5 before the re-pin, read as a warning); 1 error. When Part 2, 3 or 5 cannot see the take, Part 7 writes the analysis itself (an F with a warning, `app.md` "Always analysed").

## The steps
### Step 1: Open the app
- Screen: `#/` (`app.md`). API: `GET api/health`, `GET api/config`, `GET catalog/api/entries`.
- AC-J1 The home screen loads at 412x915, lists Part 6's entries (name,
  category, a video badge when the entry has `video_uri`), with search and a Record button; no console
  errors; desktop width also lays out without horizontal scroll.
- Recipe: QA recipe `browse-and-play` (firm-only) (witnesses: entry rows on screen and the
  `catalog/api/entries` response; negative: a search with no match shows the empty state, no rows).

### Step 2: A trainer records a movement
- Screen: `#/record`: camera preview, Record and Stop (60 s at most, timer), or Upload; name and
  category; Save. Then `#/job/<id>` with real stages: `upload`, `keyframes`, `pose`, `skeleton`,
  `animation`, `catalog`.
- API: `POST api/uploads` (raw body, at most 95,000,000 bytes and 60 s), `POST api/trainer {upload_id,
  name, category}` 202 `{job}`, `GET api/jobs/<id>`.
- Capture: `MediaRecorder` with `videoBitsPerSecond: 2500000` (60 s stays near 19 MB); WebM from
  Chromium, MP4 from Safari; Part 7 normalizes to H.264 MP4 before any part sees it.
- AC-J2 A fake-camera recording (Chromium, y4m of the trainer clip) and an upload each produce a job
  that shows at least four real stages and ends with a Part 6 entry: `files_source: import`, a
  `video_uri`, provenance 1 (or 3), 3, 4, and Part 6 `doctor` exit 0.
- AC-J3 A 96,000,000-byte upload or a 61 s video is refused with the `app.md` message; nothing queued.
- Recipe: QA recipe `record-expected` (firm-only) (witnesses: job screen stages and `api/jobs/<id>`; the
  entry in the catalog and its manifest; negative: Save with an empty name stays on the screen with
  the name error and no job).

### Step 3: Available in the cloud for others to view
- Screen: `#/watch/<id>`: the trainer video (the entry's `video_uri` through the proxy, `<video
  controls playsinline>`), Part 7's 3D viewer of the entry's `animation.json` with orbit (one figure,
  `compare-view.md` single mode), Part 6's entry page in a frame below, and Follow.
- Cloud: the staging gateway route `/simon-part-7/` (`staging.md`, firm-only, not published). No accounts: every visitor sees every entry (Part 6's model).
- AC-J4 A second browser context, with no state shared with the trainer's, finds the
  trainer's entry by name, plays its video (`currentTime` advances, the proxy answers 206 to a Range
  request) and rotates its 3D figure.
- Recipe: QA recipe `second-visitor` (firm-only) (witnesses: the video's `currentTime` and the 206 response;
  the entry id on screen and in `catalog/api/entries`; negative: an entry id that does not exist shows
  the not-found state and no player).

### Step 4: A user selects it and records or uploads a take
- Screen: `#/follow/<id>` from Watch's Follow button or Part 6's framed Follow (`simon:follow`, origin
  checked); the same capture controls as Record; Analyse.
- API: `POST api/uploads`, `POST api/follow {upload_id, entry_id}` 202 `{job}`; 404 unknown entry; 409
  no animation; 429 over the visitor quota.
- AC-J5 Follow by the fake camera (y4m of a follower clip) and Follow by upload each queue a follower
  job against the selected entry.
- Recipe: QA recipe `follower-record` (firm-only) (witnesses: the recording timer and the `api/uploads`
  response size; the job's `entry_id`; negative: a `simon:follow` message from another origin does not
  navigate).

### Step 5: The pipeline analyses the take against the trainer's
- Screen: `#/job/<id>` with stages `upload`, `pose`, `skeleton`, `analyse`, elapsed time, and position
  in the queue while waiting.
- AC-J6 The follower job runs Parts 2, 3, 5 with each doctor; `analysis.json` passes Part 5 `doctor
  --for part7`; `replay.json` validates against Part 5's `contracts/replay.schema.json`; a reload
  resumes the job screen.
- Recipe: QA recipe `follow-and-analyse` (firm-only) (witnesses: the stage list and `api/jobs/<id>`;
  negative: a second job from the same visitor beyond the quota gets the 429 text and is not queued).

### Step 6: The simulations come back to see, rotate and compare
- Screen: `#/result/<job>`, the compare view (`compare-view.md`): the trainer's animation and the
  follower's skeleton, side by side or overlaid, one clock, one orbit camera, scrub, play and pause,
  front, side and top views, aligned by `exp_to_fol`.
- AC-J7 A drag on the canvas rotates both figures (one camera: `data-camera-azimuth` changes and both
  figures' screen positions change); the overlay toggle switches `data-mode` between `side` and
  `overlay`; scrub moves both figures to the same aligned frame.
- Recipe: QA recipe `compare-3d` (firm-only) (witnesses: `data-camera-azimuth` and a screenshot diff;
  `data-mode` and the toggle's `aria-pressed`; negative: while paused the clock text does not change
  over 2 s).

### Step 7: Timed fault feedback in plain words, written by AI
- Screen: the fault list under the compare view: each row is Part 5's `text_timed` (for example "Your
  right foot drifts too far to the right at 1.9 s"), ordered as Part 5 orders them. Tap: the clock seeks
  to `at_s`, the fault's joints are highlighted on the follower figure, the row is `aria-pressed`.
- Text: Part 5's phrasing backend writes `text`, and Part 5 composes `text_timed` with `at_s`. Live AI
  (`muse-spark --live`) on dev and staging; Part 5's validator allows only the numbers it was given, so
  the seconds are exact. A row whose `phrasing.backend` is not the live one still shows its text; the
  run reports how many rows fell back and why (`phrasing.fallback_reason`).
- AC-J8 Every row shows "at X.X s" equal to that fault's `at_s` in `analysis.json`; a tap sets the
  clock to `at_s` (within one frame) and `data-highlighted-joints` to the fault's joints.
- Recipe: QA recipe `timed-feedback` (firm-only) (witnesses: the row text and `analysis.json`; the clock
  text and `data-highlighted-joints`; negative: a warned take shows the warning banner over its full result, never a refusal-only screen).

### Step 8: A score out of 100 with a grade
- Screen: the score panel at the top of the result: the value large, the grade beside it, the band
  rule one tap away. A warned take: the warning banner above the panel, grade F (a cap of 59).
- Source: Part 5's `score` (`app.md`, "Score"). Part 7 never computes a score.
- AC-J9 The panel shows `score.value` and `score.grade` exactly as in `analysis.json`; a take the pinned Part 5 refused
  (`score: null`) shows 0 and F with the warning.
- Recipe: QA recipe `score-grade` (firm-only) (witnesses: the panel text and `analysis.json`; the grade
  matches the band of the value; negative: the mismatch take shows no score).

## Cross-part contract (follow-ups filed 2026-10-30 in Parts 2, 3, 5; Part 6 unchanged)
Part 7 code never imports another part; it re-pins to the new upstream SHAs (TICKET-036, 037, 038).
Until a re-pin lands, Part 7 builds against fixtures shaped exactly as below.
- Part 2: browser WebM without a duration field is accepted by its staging probe and its CLI, with a
  test.
- Part 3: `run --keyframes-densify every:<n>` keeps Part 1's named keys and adds a key every `n` ticks;
  `run` creates its out directory.
- Part 5, `simon.analysis.v1` schema 1.2.0, additive and optional fields:
  - per fault: `follower_t_s: [start_s, end_s]`; `at_s` (the start, 0.1 s resolution);
    `follower_runs` mapped to the original follower frames; `lateral: "left"|"right"|null` (screen
    direction from side and out/in); `text` (the phrasing backend's output, AI when live);
    `text_timed`; `phrasing: {backend, model, fallback_reason}`;
  - top level: `score: {version: "simon.score.v1", value: 0-100, grade: "A"-"F", components: {faults,
    similarity}, params_sha256}`, never null from schema 1.4.0 (`null` on a refusal of the pinned Part 5, shown as 0 and F), with `capped_by` when a warning caps it. Bands: A 90 and above, B 80 to 89, C 70 to
    79, D 60 to 69, F below 60;
  - `part5 analyse --replay <replay.json>` writing `contracts/replay.schema.json` (fps, expected and
    follower per-frame `t` and joints, `exp_to_fol`, bones); `--phrasing muse-spark|template|local-llm`
    and `--live`; Muse Spark may receive `at_s` and must reproduce it exactly; the deterministic path is
    what tests and checks use.
- Part 6: no change. Part 7 imports with `--part keyframes=1 --part skeleton=3 --part animation=4` plus
  the trainer video, so entries are cap-exempt and carry a `video_uri`. Follow hand-off as published:
  `{v, id, name, category, link, manifest, files: {keyframes, skeleton, animation, video}}` by the
  `simon:follow` event, `postMessage` or `--follow-url`; its player draws one figure per instance.

## Error Cases
| Condition | HTTP | Message on screen | AC |
|---|---|---|---|
| Upload over 95,000,000 bytes | 413 | `The file is too large (95 MB at most).` | AC-J3 |
| Video over 60 s | 413 | `The video is too long (60 s at most).` | AC-J3 |
| Visitor quota reached | 429 | `You have used today's analyses. Try again tomorrow.` | AC-J6 |
| Daily GPU cap reached | 503 | `The app has reached today's limit. Try again tomorrow.` | AC-J6 |
| Entry not found | 404 | `This movement is not in the catalog.` | AC-J4 |
| Warned take | none | warning banner with each warning's text, full result, grade F | AC-J8, AC-J9 |
| Part 2, 3 or 5 cannot see the take | none | Part 7's own analysis: warning `no_person` or `no_usable_measures`, 0, F; job `done` | AC-J8, AC-J9 |
| Live phrasing unavailable | none | Part 5's template text (row still timed) | AC-J8 |

## Edge Cases
- A take with no faults: the list shows `No faults found in this take.` and the score panel still shows
  Part 5's score.
- Two faults at the same `at_s`: both rows seek to the same time; highlighting shows only the tapped
  row's joints.
- A visitor with no `Cf-Connecting-Ip` (local dev, check-7): the per-visitor quota does not apply; the
  daily caps do.

## Timeline (dates win over hour budgets)
Today 2026-10-30. Part 5 and Part 3 follow-ups published and re-pinned by 2026-11-01T18:00Z; Part 2 by
2026-11-02T12:00Z; re-pin cut-off 2026-11-02T18:00Z. Journey verify green by 2026-11-03T12:00Z, when
recording of the submission video starts from whatever works. The run ends 2026-11-04T00:00Z
(submission day 2026-11-04).

## Dissent Review (MANDATORY)
Reviewed at the rescope, 2026-10-30.
- Concern: live AI text makes the result differ between runs, so recipes cannot match fixed text.
  Resolution: recipes match the "at X.X s" figure and the row count to `analysis.json`, never the words.
- Concern: eight recipes plus the GPU jobs may not fit the verify budget. Resolution: the drive reuses
  one trainer entry and the follower jobs for steps 5 to 8; the budget rule in `staging.md` (firm-only, not published) applies.
- Concern: four cross-part follow-ups in four days. Resolution: Part 7 builds on fixtures of the
  contract in parallel; Part 5 and Part 3 first; a part missing the cut-off stays pinned and the run
  names the missing field in a DEGRADED end, never a Part 7 substitute.

## Delivery Verification Plan
Eight recipes validated by an independent reviewer; the staging journey verify (firm-only) 0 on the journey drive;
check-7 with the score and `at_s` gates; `demo/simon-end-to-end.mp4` showing all eight steps.

## Cross-part follow-up tickets (filed 2026-10-30)
The run works these in each part's own workspace, under that part's specs, tests and publish path, then re-pins.

| Part | Workspace | Tickets | Spec |
|---|---|---|---|
| 2 | the Part 2 repo | TICKET-039 (browser WebM without a duration; Part 7 call documented) | docs/specs/journey-followup.md |
| 3 | the Part 3 repo | TICKET-036 (`--keyframes-densify every:<n>|off`), TICKET-037 (`run --out` creates its folder; README follower example has `--fps 30`) | docs/specs/journey-followup.md |
| 5 | the Part 5 repo | TICKET-032 (time per fault), 033 (lateral and timed words), 034 (replay contract), 035 (`simon.score.v1`), 036 (AI phrasing as live default), 037 (review of 20 live lines), 038 (contract, doctor, goldens, publish); ADR-0007 to 0009 | docs/specs/journey-followup.md |

Differences from the interface above, as Part 5's spec settled them (Part 5's spec wins):
- `simon.replay.v1` carries per-frame times as two arrays, `expected_t` and `follower_t`, beside `expected`, `follower`, `exp_to_fol`, `fps`, `joints`, `bones` and `coordinate_frame`.
- Each fault may also carry `lateral_m` (on `foot_out` only). `text_timed` example: "right foot too far right at 1.9 s".
- The similarity term of the score uses all 22 measures in Part 5's `MEASURES`; the value is clamped to 0 to 100.
- Live phrasing is on with `--live`, `serve --live`, `SIMON5_LIVE=1` or `META_LIVE=1`; tests, check-5 and the goldens are forced to the template.
- Part 3's densify option also reads `PART3_KEYFRAMES_DENSIFY`, `[keyframes] densify` and the API's `keyframes_densify=`; its output records `timeline.densify`.
- Part 2's documented call includes `--out <dir>`: `part2 run --mode single --input <webm|mp4|mov> --out <dir> --fps 10 --backend gpu [--mirrored]`.
