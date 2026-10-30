# Spec: recorder, trim editor and labels (TICKET-052 to TICKET-056)

> Copy of `docs/specs/recorder.md` from the development workspace, edited for publication; the code is the authority where they differ.


Operator 2026-10-30: "Scope in enhanced recording/editing/countdown to the recorder, so people can specify
clips, labels, etc. This removes a bug where moving to/from the camera to play/pause recording breaks the
movement."

## Problem
A person who records themselves presses Record, walks into position, performs, walks back and presses Stop.
The walks are in the clip. Part 2 tracks them, Part 5 compares them with the movement, and a correct take
is refused or gets false faults. Close-up framing makes it worse (invented legs; see ADR-0011 in Part 5).

## One take flow (operator 2026-10-30)
Operator: "analyze/follow should use the same video recording as the initial record (code reuse) so it comes
with the labeling, countdown, etc." Trainer and follower capture is one module, `web/take-flow.js`; `record.js`
and `follow.js` only load their data and mount it. The flow is capture (countdown, duration, framing hint),
trim editor, upload, `POST api/people` with the trim, the person picker (`people.md`; skipped for a one-person
clip), details, then `api/trainer`, `api/group` or `api/follow`. Details differ by role: the trainer has the
required name and category plus tags and notes; the follower has optional tags and notes for their take.

## Overview
Both capture screens (trainer `#/record`, follower `#/follow/<id>`) gain:
1. A countdown before recording starts and an optional fixed duration that stops recording by itself, so
   nobody touches the phone during the movement.
2. A trim editor after recording or upload: the person marks where the movement starts and ends; only that
   range is processed.
3. Labels (tags and notes): the trainer's go beside name and category and are kept with the entry and
   searchable; the follower's are optional and belong to their take (see "Follower take labels").

## Capture (web/capture.js, web/countdown.js)
- Countdown selector: Off, 3 s, 5 s, 10 s (default 5 s). The countdown shows large digits over the preview,
  a short beep per second through WebAudio (muted when the device is silent is acceptable), and a Cancel
  button. Recording starts when it reaches zero.
- Duration selector: Manual, 5 s, 10 s, 15 s, 20 s, 30 s, 45 s, 60 s (default 15 s). With a duration, recording stops by
  itself at that time; Stop still works. Manual records until Stop or 90 s.
- Framing hint on the preview: "Step back until your whole body fits, or at least everything that moves."
- The selected countdown and duration are remembered per device (localStorage, wrapped in try/catch).
- Raw capture limit: 90 s. MediaRecorder settings are unchanged (2.5 Mbit/s, first supported of webm vp9,
  webm, mp4).

## Trim editor (web/trim.js)
Shown after a recording stops or a file is picked; nothing is uploaded before the person confirms.
- The video plays from a local object URL (no upload needed to preview).
- A range control with two handles (start, end) over a strip of thumbnails taken from the video (8 to 12
  frames drawn to canvas), plus the current time and the selected length ("2.1 s to 9.4 s, 7.3 s").
- Play selection plays from start to end and loops; Set start and Set end take the current playhead.
- Defaults: the whole clip, except that a recording with a countdown starts at 0.0 s (the countdown is not
  recorded) and a Manual recording trims the last 1.0 s (the walk to Stop).
- Rules shown before Continue: the selection must be 1 s to 60 s; the raw file must be at most 95,000,000
  bytes. Errors use plain words.
- Keyboard: arrow keys move the focused handle by 0.1 s; both handles are buttons with aria labels.
- Continue uploads the raw file with `POST api/uploads` and then starts the job with the trim.

## Labels (web/labels.js)
Name (required, 1 to 60 characters), category (existing list), tags (0 to 8 chips, each 1 to 24
characters, lower case, letters, digits and hyphen), notes (0 to 280 characters). Shown on the trainer's save
screen and on the Watch screen; catalog search matches name, category and tags.

## Server
| Change | Contract |
|---|---|
| `POST api/uploads` | Raw limit becomes 90 s (was 60 s); 95,000,000 bytes unchanged. Response unchanged. |
| `POST api/trainer` | Body `{upload_id, name, category, trim?: {start_ms, end_ms}, labels?: {tags: [...], notes}}`. |
| `POST api/follow` | Body `{upload_id, entry_id, trim?: {start_ms, end_ms}, labels?: {tags: [...], notes}}`. |
| Trim rules | 0 <= start_ms < end_ms <= duration_ms; 1,000 <= end_ms - start_ms <= 60,000; else 400 with a plain message. No trim means the whole upload, which must then be at most 60 s (413 as today). |
| Trimming | `part7/media.py` cuts the normalized H.264 MP4 to the range with a frame-accurate re-encode before Part 1 or Part 2 sees it; the job records `trim` and the trimmed duration. |
| Labels | Stored by Part 7 in `<state>/labels/<entry_id>.json` `{tags, notes, updated_at}` (Part 6 has no tags field; Part 6 is unchanged). |
| `GET api/labels` | `{<entry_id>: {tags, notes}}` for every labelled entry; the catalog screen merges it for display and search. |
| `GET api/labels/<entry_id>` | One entry's labels; 404 when none. The web never calls it: Watch reads the `api/labels` map, so an unlabelled entry logs no console 404 (verify bug B). |
| Follower take labels | Validated like trainer labels (`labels.validate`) and stored in the follow job record as `labels: {tags, notes}` (decision: the job record, not `<state>/labels/`, which is keyed by catalog entry). `GET api/jobs/<id>` returns them and the result screen shows them (`take-labels`, `take-tags`, `take-notes`). They live as long as the job (7 days). |
| Trim with a person | With `people_job` the people job already cut the clip, so the job's `trim` and `duration_ms` are the people job's and the request's `trim` is not applied twice. Trim parsing is one function (`server._clip`); `people_routes` calls it. `media.trim(src, dst, start_ms, end_ms)` is the one cutting function. |

## data-testid
`countdown-select`, `duration-select`, `countdown` (the overlay digits), `countdown-cancel`, `rec-timer`,
`framing-hint`, `trim`, `trim-start`, `trim-end`, `trim-play`, `trim-set-start`, `trim-set-end`,
`trim-length`, `trim-error`, `trim-continue`, `tags`, `tag-input`, `notes`, `entry-tags` (Watch),
`entry-notes` (Watch), `take-labels`, `take-tags`, `take-notes` (result), `record-again`, `people-checking`, and from `people.md` the picker ids `people`, `people-continue`, `person-<id>`,
`person-trainer-<id>`, `person-label-<id>`.
Existing ids stay (`cam-start`, `cam-stop`, `upload`, `name`, `category`, `save`,
`analyse`): `save` and `analyse` now live on the screen after the trim editor.

## Acceptance Criteria
- AC-R1 With countdown 5 s and duration 10 s, pressing Record starts recording 5 s later (the countdown
  digits show 5 to 1) and stops by itself at 10 s; no touch is needed in between. Cancel during the countdown
  returns to the preview with nothing recorded.
- AC-R2 The trim editor opens after Stop and after a file is picked; Play selection loops inside the range;
  the length label equals end minus start to 0.1 s.
- AC-R3 A trimmed trainer job's normalized video lasts end minus start within one frame, and Part 1 and
  Part 2 receive only that range (job record `trim`).
- AC-R4 A follower job honours its trim the same way; the analysis times (`at_s`) are on the trimmed clip's
  clock, and the result screen says so.
- AC-R5 Selections under 1 s or over 60 s, or past the clip end, are refused in the browser and by the
  server (400) with plain words.
- AC-R6 Tags and notes saved with a trainer entry show on Watch for a second visitor and are matched by
  catalog search.
- AC-R7 The framing hint is visible on both capture screens.
- AC-R8 Keyboard-only trimming works (arrow keys move the focused handle by 0.1 s).

## Reference (web/reference.js, web/reference.css; follower only; operator 2026-10-30)
The follower sees the trainer while recording and editing. Source: the entry's `video_uri` via
`catalog/api/entries/<id>/<video_uri>`, else its 3D animation in `mountViewer`; neither means no panel.
- Capture: picture-in-picture over the preview on a phone, beside it from 720 px. Tap the picture or `reference-swap`
  to swap the two views. It plays muted and looping from the end of the countdown with the recording clock; the
  countdown overlay shows its first frame (`reference-first`). `reference-mirror` toggles the mirror, default on.
- Trim editor: the panel sits beside the take; its time is the trim playhead plus `reference-offset` ("Line up the
  start", -3 s to +3 s), looped inside the reference length; it plays along with Play selection.
- Test ids: `reference`, `reference-video`, `reference-mirror`, `reference-swap`, `reference-offset`.
- AC-R9 The panel shows on `#/follow/<id>`, never on `#/record`. AC-R10 It starts at countdown end, muted, looping.
  AC-R11 In trim its playhead follows the take's. AC-R12 Mirror and swap work.
  Test: `tests/part7/drive_reference.mjs`, `tests/part7/test_reference_static.py`.

## Error Cases
- The camera is refused: the Upload path is offered (unchanged).
- WebAudio is blocked: the countdown runs silently.
- Thumbnails fail to draw (codec): the range control still works without the strip.

## Edge Cases
- A MediaRecorder webm has no duration in its header (the video reports Infinity). The recorder clock's length in
  ms goes to the editor as `durationHint`; the editor waits for a finite duration after the 1e101 seek
  (durationchange, timeupdate, seeked) and falls back to the hint, so `trim-length` is never empty.
- A clip under 1 s cannot be trimmed: the editor says it is too short and offers Record again.
- iOS Safari records mp4; the editor and trim work the same.

## Files
| File | Work stream |
|---|---|
| `web/capture.js`, `web/countdown.js` (new), `web/take-flow.js` (shared by `web/record.js` and `web/follow.js`) | REC, TAKE-FLOW |
| `web/reference.js`, `web/reference.css` (new), hooks in `web/capture.js`, `web/trim.js`, `web/take-flow.js`, `web/follow.js` | FOLLOW-REF |
| `web/trim.js` (new), `web/labels.js` (new), `web/catalog.js` (tags in search), `web/watch.js` (labels), `web/styles.css` | EDIT |
| `part7/server.py`, `part7/media.py`, `part7/jobs.py`, `part7/processor.py`, `part7/labels.py` (new), `part7/config.py` | SERVER |
| `staging/drive.mjs`, `staging/verify.mjs`, QA recipes, `tests/staging/*` (all firm-only) | QA |

## Delivery Verification Plan
Unit tests per work stream; the staging journey verify drives countdown plus duration plus trim on trainer Record
and follower Record (fake camera), labels on the trainer and a second visitor seeing them; the staging journey verify (firm-only) exit 0.
