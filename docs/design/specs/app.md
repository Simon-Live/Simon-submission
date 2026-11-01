# Spec: the Simon app (`part7 serve`, `web/`)

> Copy of `docs/specs/app.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted (setup, 2026-10-28); amended 2026-10-30 by ADR-0006
Date: 2026-10-28
Request Type: new-feature
Risk Level: high
ADR: ADR-0003, ADR-0006. Master: `part7-stitching.md`. Companions: `journey.md`, `compare-view.md`,
`processor.md`, `staging.md` (firm-only, not published).
Tickets: TICKET-005, 006, 016, 018, 019, 020, 039 to 047.

## Overview
A phone web app on one port, laid out for 412x915; desktop width also works. The screens follow the
journey in `journey.md`. Home lists the catalog from Part 6's API, with a video badge. Record (trainer)
and Follow (follower) capture with the camera or take a file. A job screen shows the stages. Watch plays
the trainer's video, shows its figure in a rotatable 3D viewer and frames Part 6's entry page. The result
screen shows Part 5's score and grade, the 3D compare of both figures, the timed fault list (a tap seeks
and highlights the joints), a warning banner when the take has warnings, and the downloads. A take is never
refused ("Always analysed").

## Why This Is Wrong (Dissent-First)
- A GPU job takes minutes; a phone visitor may leave. Answer: the job id is in the URL (`#/job/<id>`)
  and survives a reload; results are kept 7 days.
- Camera access fails on some phones. Answer: Upload is always offered beside Record.

## Server (`part7/server.py`, `part7/proxy.py`, `part7/jobs.py`, `part7/replay.py`)
stdlib `ThreadingHTTPServer`, 127.0.0.1 only. Paths are relative to the base path (`--base-path`, from
`STAGING_BASE_PATH` on staging). A request outside the base path gets 404.
| Method and path | Result |
|---|---|
| `GET api/health` | 200 `{ok, part6: {ok, entries}, pins: {<n>: <sha12>}, queue: {running, waiting}, gpu_jobs_today}`; 503 when Part 6 does not answer |
| `GET api/config` | 200 `{base, limits: {max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000}, phrasing: "live"\|"template", movement, fixture_result: true}` |
| `POST api/uploads` | raw body, `Content-Type: video/mp4` or `video/webm` (also `video/quicktime`); 201 `{upload_id, duration_ms, width, height}`; 400 not a video; 413 over 95,000,000 bytes or 60 s. Takes an optional `Idempotency-Key` (below) |
| `POST api/trainer` | `{upload_id, name, category}`; 202 `{job}` (`processor.md`); 429 over the visitor quota; 503 queue full |
| `POST api/follow` | `{upload_id, entry_id}`; 202 `{job}`; 404 unknown entry; 409 entry has no animation or skeleton; 429 over the visitor quota |
| `GET api/jobs/<id>` | 200 `{id, kind, status: queued|running|done|failed, stage, note, entry_id, result, queue_position}`; stages per `journey.md` (trainer: `upload`, `keyframes`, `pose`, `skeleton`, `animation`, `catalog`; follow: `upload`, `pose`, `skeleton`, `analyse`); 404 |
| `GET api/results/<job>/analysis.json` | Part 5's file as written |
| `GET api/results/<job>/replay.json` | Part 5's replay file, validated against its `contracts/replay.schema.json` at the pin; 422 when it fails; never computed by Part 7 |
| `GET api/fixture-result` | `{analysis, replay}` from `fixtures/input/analysis-1.2.0.json` and `fixtures/input/replay.json`, shaped as Part 5 schema 1.2.0 |
| `ANY catalog/**` | reverse proxy to the Part 6 child (`proxy.py`): method, headers except hop-by-hop, body, status, `Range` and 206 passed through; the trainer video comes from the entry's `video_uri` this way |
| `GET /`, static | `web/` files; `index.html` for the base path |

Jobs (`part7/jobs.py`): one worker thread; queue limit 8 (503 beyond); a job record and logs under
`<state>/jobs/<id>/` (`job.json`, `steps/*.log`, outputs); results kept 7 days, then removed by the
worker at start. Kinds: `trainer` (the chain in `journey.md` ending with Part 6 `import`,
`processor.md`) and `follow` (Parts 2, 3, 5). Every upload is normalized to H.264 MP4 (`media.py`)
before Part 2 sees it.
Follow job: the entry's `animation.json` (else its `skeleton.json`) is read from Part 6's API, then
Part 2, Part 3 `--view part5 --fps 30 --body simon-standard`, Part 5 `analyse --replay <job>/replay.json
--phrasing <p>` (`muse-spark --live` when `SIMON7_PHRASING=live`, `template` when `template`), each with
its doctor (`parts-harness.md`).
Daily caps on staging: 40 GPU jobs and 10 trainer jobs per UTC day (`api/health` shows the count); over
either, 503 "The app has reached today's limit. Try again tomorrow."

### Idempotency-Key (`part7/idempotency.py`, offline takes)
`POST api/uploads`, `api/follow`, `api/trainer` and `api/group` take an optional `Idempotency-Key: <UUID>` header; the
browser sends the saved take's id on all four. The first accepted answer (201 or 202) is stored under
`<state>/idempotency/<route>-<key>.json` for 7 days (pruned at start like uploads). A repeat of the same key on the
same route answers the stored body with `Idempotent-Replayed: true`: no new upload, no new job, no quota charge. This
makes a retry safe when the response was lost after the server accepted the request. Rules: only 201 and 202 are
stored (a refusal is retried for real); the key is scoped to its route (the take id is the key on the upload and on
the job); a stored upload whose file is gone is uploaded again under the same key; a second request with a key that
is still running answers 503 "The app is busy" (the browser retries); a missing or invalid key (not a UUID), or a key
on any other route, behaves exactly as before.

### Quotas and spend (`part7/quota.py`)
- Per visitor, keyed on `Cf-Connecting-Ip` (the gateway forwards it; local requests have none and skip
  the visitor quota): 3 trainer jobs and 10 GPU jobs per UTC day; over it, 429 "You have used today's
  analyses. Try again tomorrow."
- Part 1: the run-wide $5 cap (`parts-harness.md`).
- Live phrasing runs once per follow job, so the daily cap of 40 GPU jobs bounds it.
- Counters on disk under `<state>/quota/`.

## Score
Part 7 shows Part 5's `score` (`simon.score.v1`): `value` 0 to 100, `grade` A to F (A 90 and above, B 80
to 89, C 70 to 79, D 60 to 69, F below 60), `components` (`faults`, `similarity`), `params_sha256`. Part 7
never computes or adjusts it. A score is always shown: a missing score (the pinned Part 5's refusal) reads as 0,
grade F. A tap on the grade shows the band rule.

## Always analysed
A take is never refused: the operator's rule is that the app NEVER fails to analyse. Part 5 (schema 1.4.0,
additive) always writes a full analysis and exits 0 for a readable input: `status.code` is `ok`, the former
refusals are top-level `warnings: [{code, text}]` (`low_match`, `moving_part_out_of_frame`,
`not_enough_visible`, `no_usable_measures`), `match: {quality: "ok"|"low", residual, timing_corr, limits}`
says how well the take matches, faults are always listed with `confidence: "low"` when the match is low,
and `score` is never null: any warning caps it at 59 (grade F) with `score.capped_by: [codes]`.
- The result screen shows the full result (3D compare, faults, score and grade) under a warning banner
  (`warning`, one `warning-<code>` line per warning with its text) and a Record again button; a fault with
  `confidence: "low"` carries a "Low confidence" chip (`fault-<i>-low`, `data-confidence="low"`).
- Until the re-pin, the pinned Part 5 still refuses (old status such as `different_movement`, exit 3, `score:
  null`, no faults). Part 7 reads that as a warning with the status code and text, shows score 0 and grade F, the
  compare view when a replay exists, and Record again. The job summary (`score`, `grade`) reads a missing score
  as 0 and F.
- Part 7 writes the analysis itself when its own chain cannot see the take (`chain.follower`): Part 2 found no
  person or its doctor rejected the file (warning `no_person`), or Part 3 or Part 5 could not run or produced
  nothing (warning `no_usable_measures`). The file has `status ok`, one warning with a `reason`, `faults: []`,
  `score` 0, grade F, `source: "part7"`; it carries no replay. The job record is `done`, never `failed`, and the
  job note says the take was analysed by Part 7 alone. Infrastructure errors stay `failed`: the GPU is busy, a
  step is not available, a step timed out (the server restarting, disk full). A group job's shared Part 2 run
  failing still fails that job, because there is no trainer animation without it.
- The group board reads a row with no score the same way (0, F, its warning line `group-warning-<id>`); only a
  row whose chain failed on infrastructure (`status_code` `error`) shows "No score" with its reason.

## Video quality on the result (simon.quality.v1; `web/quality-result.js`, `part7/quality.py`)
Part 5 writes an additive top-level `quality` in `analysis.json` (`issues[]` with `impact` major/minor, `rule`
M1 to M4 or null, `text`, `tip`, `at_s`, `spans_s`, `affects`; `expected_issues` is information about the
trainer's video and never affects the follower). Part 7 only displays it and never decides impact or cap.
- Major: the cap already arrives as `quality_<code>` warnings and `score.capped_by`. The warning banner shows each
  warning's `tip` under its line (`warning-tip-<code>`); a warning that carries `cause` (for example
  `moving_part_out_of_frame` with `body_cut_off`) shows its tip and sets `data-cause`. A major issue with no
  matching warning still appears in the banner. Record again stays.
- Minor: a "Tips for your next take" section (`quality-tips`, one `quality-tip-<code>` each). A tip with `at_s`
  has a time chip "At 1.2 s" (`quality-time-<code>`) that dispatches `simon:seek {at_s}` like the coaching
  moments. No score change is mentioned.
- Score panel: when `capped_by` has a `quality_*` code it says "Capped at 59 because of the video quality."
  (`quality-cap`).
- Group: the same per person on `#/result/<job>/<pid>`, plus a "Video quality" chip (`group-quality-<id>`) on a
  board row whose person has a major issue. Person picker: `people_quality` in `tracks.json` shows "small in
  frame" or "partly out of frame" (`person-quality-<id>`) under that person's crop; it never blocks selection.
- Own analysis: `chain.write_own_analysis` (no_person / no_usable_measures) copies `quality.issues` from Part 2's
  `pose3d.json` or `tracks.json` (the selected person only) as `impact: "minor"`, `rule: null`, with the shared tip
  as text and tip, so a take with no person found in a dark room still says "The room was dark...". The score
  stays 0, grade F, and its schema_version is `1.5.0` (`part7/quality_constants.py`). No quality in the input means
  no `quality` key. The reader ignores the schema version and unknown fields.
- With no quality anywhere every screen looks as before.

## Offline takes (`web/pending.js`, `web/pending-app.js`, `web/pending-ui.js`, `web/take-request.js`)
A camera take is saved in IndexedDB (`simon-local`, `pending-takes`) when it is trimmed, and deleted only when the
server answers 202 to the job call (`api/follow`, `api/trainer`, `api/group`), when the person taps Delete, after a
non-retryable error, or after 7 days. At most 3 takes and 300 MB; `navigator.storage.persist()` is asked once and
`estimate()` checked before saving. Picked files are not saved. A record holds `id, created_at, expires_at, role
(trainer|follow|group), entry_id, entry_name, mode, section, trim, labels, name, category, mime, size, blob, stage
(saved|uploaded|people_ready|ready_to_submit|submitting), upload_id, people_job, choice, auto_submit, attempts,
next_try_at, last_error {status, message, kind}` (plus `challenge_id`), updated as each step completes.
- Failures: retry automatically (status 0, XHR error/abort/timeout, 500, 502, 504, busy 503) on 10 s, 30 s, 1 min,
  2 min, then every 5 min; retry later (429, 503 "today's limit") at just after the next UTC midnight; do not retry
  (400 not a video, 413, 404, 409): show the message and delete the copy; 400 "The upload was not found" on a job call:
  clear `upload_id`, back to `saved`, upload again from the saved Blob. A 400 on the job call that is not that (a bad
  name) keeps the take and returns it to the details.
- Triggers: app start, `online`, `visibilitychange` to visible, the backoff timer, and Send now. Before re-sending a
  file over 5 MB it pings `GET api/health` and only uploads on 200. One sender at a time across tabs
  (`navigator.locks.request("simon-pending-sender", {ifAvailable: true})`, a BroadcastChannel lease as fallback),
  oldest take first. There is no service worker or Background Sync: the app has to be open to send.
- Resume: upload, `POST api/people`, poll the people job. One person (`auto_id`), details complete (a trainer needs a
  name) and `auto_submit` on: the job is submitted by itself. Otherwise the stage is `people_ready` and the banner and
  panel say "Your take is uploaded. Choose who is in it to finish." with Finish to `#/pending/<id>`, which reopens the
  take flow at the picker and details from the record (no camera, trim or upload). Mode, section and group mode are
  in the record.
- Screens: `#/pending` (`pending-list`, `pending-<id>`, `pending-status-<id>`, `pending-send-<id>`,
  `pending-finish-<id>`, `pending-delete-<id>`, `pending-empty`); `#/pending/<id>` (`pending-resume`, `pending-gone`,
  `pending-busy`); the header banner on every screen (`pending-banner`, `pending-count` "1 take waiting to send",
  `pending-progress` "Sending, 42%", `pending-link`, `pending-sent` "Your take was sent. The analysis has started."
  with `pending-sent-link` to `#/job/<id>` and `pending-dismiss`), `aria-live="polite"`.
- Client log (numbers and statuses only): `take_saved_local`, `take_save_skipped {reason}`, `pending_retry {attempt,
  status}`, `pending_sent`, `pending_resumed {stage}`, `pending_deleted {reason}`.
- Nothing else changes: no shared file, no other part and no existing field is touched. Known limits: the app has to
  be open to send; Safari may evict stored data after a period of not using the site; a saved take expires after 7
  days; the whole file is resent (no resumable upload); a take sent in the background does not update a practice
  ladder step's pending mark.

## Web (`web/`)
Hash routes, relative URLs only, no build step, three@0.170.0 vendored (sha256 in
`web/vendor/README.md`, fetched from the npm registry tarball, never from another part's repo).
| Route | Screen | Key controls (`data-testid`) |
|---|---|---|
| `#/` | Catalog: search, entries (name, category, source badge, video badge), Record button | `entry-<id>`, `record`, `search` |
| `#/watch/<id>` | The trainer video from the entry's `video_uri`; a single-figure 3D viewer with orbit (`compare-view.md` single mode); Part 6's entry page in a frame (`catalog/#/entry/<id>`); Follow | `trainer-video`, `viewer`, `watch-frame`, `follow` |
| `#/record` | Trainer: camera preview, Record/Stop (max 60 s, timer, bitrate cap), or Upload; name, category; Save | `cam-start`, `cam-stop`, `upload`, `name`, `category`, `save` |
| `#/follow/<id>` | Follower: the same capture controls; Analyse | `cam-start`, `cam-stop`, `upload`, `analyse` |
| `#/job/<id>` | Stage list with the current stage, elapsed time, queue position while waiting, Try again on failure | `stage`, `retry` |
| `#/result/<job>`, `#/result/<job>/<pid>` (one person of a group job) | Score panel; compare view (`compare-view.md`); fault list: `fault-<i>` rows show `text_timed` in Part 5's order, a tap seeks to `at_s`, highlights exactly the fault's `joints` and sets `aria-pressed`; a warning banner (`warning`, `warning-<code>`) and a Record again button (`record-again`) when the take has warnings or the pinned Part 5 refused it; low-confidence faults marked (`fault-<i>-low`); the follower's take labels (`take-labels`); downloads | `score`, `grade`, `compare`, `mode-toggle`, `play`, `scrub`, `clock`, `view-front`, `view-side`, `view-top`, `fault-<i>`, `fault-<i>-low`, `warning`, `warning-<code>`, `record-again`, `download-analysis`, `download-replay` |
| `#/result/fixture` | the same screen on Part 5's example (S0) | as above |
| `#/pending`, `#/pending/<id>` | Saved takes (offline takes, above); Finish reopens a saved take at the picker and details | `pending-list`, `pending-<id>`, `pending-send-<id>`, `pending-finish-<id>`, `pending-delete-<id>` |

Follow hand-off: Watch listens for `message` events with `data.type === "simon:follow"` and
`event.origin === location.origin`, then opens `#/follow/<data.id>`. The follow URL given to Part 6
(`<base>#/follow/{id}`) covers the unframed case.

Capture (`web/capture.js`): `getUserMedia({video: {facingMode: "user"}, audio: false})`, preview
mirrored with CSS only, `MediaRecorder` with the first supported of `video/webm;codecs=vp9`,
`video/webm`, `video/mp4`, with `videoBitsPerSecond: 2500000`; chunks every 1 s; stops at 60 s. File input `accept="video/*"`.

Words on screen are written with the writer skill (FORMS: button, empty state, error message). Required
strings: the warning and error texts come from Part 5 (or from `chain.py` for Part 7's own analysis) and from the table in `part7-stitching.md`.

## Acceptance Criteria
- AC-A1 Home lists Part 6's entries through the proxy, with search.
- AC-A2 Watch plays the animation in Part 6's player; Follow in the frame opens Part 7's Follow screen
  (message hand-off, origin checked: a message from another origin is ignored).
- AC-A3 Record with the camera (fake camera in verify) and Upload both create a trainer job that ends
  with an import entry carrying the video (`processor.md` AC-R1, `journey.md` AC-J2).
- AC-A4 A follower take uploaded or recorded produces a result with the score and faults with
  `text_timed`, or an F with a warning, never a refusal or a failure for an analysis case; a Part 5 analysis passes
  `doctor --for part7` (Part 7's own analysis is exempt).
- AC-A5 Tapping a fault seeks the clock to its `at_s` and highlights exactly its `joints`.
- AC-A6 The S0 fixture result renders without a GPU.
- AC-A7 Upload limits: 61 s or 96,000,000 bytes is refused with the message and nothing is queued.
- AC-A8 Only one GPU job runs at a time (two follow jobs submitted together run one after the other).
- AC-A9 No console errors during the verify drive.
- AC-A10 A second visitor plays the trainer video (`journey.md` AC-J4).
- AC-A11 A visitor over the quota gets 429 with the message and nothing is queued.
- AC-A12 The score panel shows `score.value` and `score.grade` equal to `analysis.json`.

## Error Cases
| Condition | HTTP | Message on screen |
|---|---|---|
| Not a video | 400 | `This file is not a video. Pick an MP4 or WebM file.` |
| Too long or too large | 413 | `The video is too long (60 s at most).` / `The file is too large (95 MB at most).` |
| Visitor quota reached | 429 | `You have used today's analyses. Try again tomorrow.` |
| Queue full | 503 | `The app is busy. Try again in a few minutes.` |
| Camera refused | none | `Camera access is off. Allow it in the browser, or upload a video.` |
| Job failed | none | the job's plain reason plus Try again |
| Server unreachable (0, 500, 502, 504, busy 503) on upload, people job or job call | any | `Couldn't reach the app. Your take is saved on this device and will be sent when the app is back.` (camera take); `Try again` (file or not saved) |
| Daily limit (429, 503 "today's limit") on a saved take | 429, 503 | `The app has reached its limit for today. Your take is saved on this device and will be sent tomorrow.` |
| Upload not found on a job call | 400 | none: the saved take is uploaded again, without asking |

## Edge Cases
- Entry with only a skeleton (Part 6 fixture): Follow uses `skeleton.json` as the expected clip only when
  Part 5 accepts it (`simon.skeleton.v1`); otherwise 409 with `This movement has no animation to follow.`
- Reload during a job: the job screen resumes from `api/jobs/<id>`.

## Dissent Review
Reviewed at setup, 2026-10-28.
- Concern: building Part 7's own replay when Part 5 has a viewer duplicates work. Resolution: Part 5's
  viewer is published as part of its demo page, not as a documented reusable module. Since ADR-0006
  Part 7 draws from Part 5's published replay file and computes no alignment itself.

## Delivery Verification Plan
Unit tests for the server, queue, quota, proxy and replay validation; staging verify drives every route (`staging.md`, firm-only, not published).
