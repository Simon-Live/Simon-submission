# 2026-10-31 offline takes lane: a take survives a failed upload, a reload or a closed tab

Spec: `docs/design/specs/recorder.md` (capture and error cases) and `app.md` ("Idempotency-Key", "Offline takes").
No shared file and no other part is affected: the change is in Part 7's browser code and Part 7's server only.

## Why
The take lived only in page memory. If the upload or the people job failed (server down, network blocked), the only
button was "Record again", which threw the take away; a reload or a closed tab lost it too.

## What was added
A camera take is saved on the device (IndexedDB `simon-local`, store `pending-takes`) as soon as it is trimmed. If the
server cannot be reached, the screen says the take is safe and the person can leave. When the server is back the app
sends the take by itself and continues the analysis. The saved copy is deleted once the server has accepted the job
(202 from `api/follow`, `api/trainer` or `api/group`), never on the upload's 201 alone. The same path runs online:
always save, always delete on 202. A picked file is not saved (the original is still on the device) but gets an
in-tab Try again. The server accepts an optional `Idempotency-Key` so a retry after a lost response never makes a
second upload or job, or uses a second daily analysis.

- Files (web): `web/pending.js` (pure core: failure sorting, backoff, caps, resume stage, sender, lock),
  `web/pending-app.js` (IndexedDB, locks, api, log wiring), `web/pending-ui.js` (banner, `#/pending`, `#/pending/<id>`),
  `web/pending.css`, `web/take-request.js` (the request builder, moved out of the take flow), `web/take-flow.js`,
  `web/api.js` (key header, `ApiError.detail`, `submitJob`), `web/labels.js` (`set`), `web/app.js`, `web/index.html`.
- Files (server): `part7/idempotency.py`, `part7/server.py`.
- Routes: `#/pending`, `#/pending/<id>`. No new API route; `Idempotency-Key` on `api/uploads`, `api/follow`,
  `api/trainer`, `api/group`.
- Test ids: `pending-banner`, `pending-count`, `pending-progress`, `pending-link`, `pending-sent`, `pending-sent-link`,
  `pending-list`, `pending-<id>`, `pending-send-<id>`, `pending-finish-<id>`, `pending-delete-<id>`,
  `saved-panel`, `saved-title`, `saved-message`, `saved-auto`, `pending-send`, `pending-delete`, `pending-finish`,
  `pending-open-job`, `pending-notice`, `try-again`, `people-error`, `record-again`.
- Tests: `tests/part7/pending.unit.test.mjs` (failure sorting, backoff, resume stage, delete only on 202, re-upload on
  "upload not found", expiry, caps, same key on every retry), `tests/part7/pending.browser.mjs` (a to f, below),
  `tests/part7/test_idempotency.py`, `tests/part7/fake_api.py` (honors the key).
- Browser checks: (a) uploads blocked, saved panel, reload, banner, unblock, one upload, one job, IndexedDB empty;
  (b) 413 shows the message and deletes the copy; (c) a response lost after the job was accepted gives exactly one
  job; (d) a two-person clip is uploaded in the background and Finish reopens the picker; (e) no IndexedDB: the
  sentence and the in-memory Try again; (f) Delete take.
- Try it: open Follow on a movement, block the network in the browser tools, record and trim. The panel says
  "Saved on this device". Reload to see the banner, go back online and watch it send.

## Rules in short
- Retry automatically: status 0, XHR error/abort/timeout, 500, 502, 504, busy 503 (10 s, 30 s, 1 min, 2 min, then every
  5 min). Retry later: 429 and a "today's limit" 503, at just after the next UTC midnight. Do not retry: 400 not a
  video, 413, 404, 409 (message, then the copy is deleted). 400 "The upload was not found" on a job call: upload again
  from the saved Blob without asking.
- Caps: 3 takes, 300 MB. When full, or when there is no IndexedDB, no room or a save error, the flow carries on as before
  and says "This take is only kept while this page is open."
- One sender across tabs (`navigator.locks`, BroadcastChannel lease as fallback), oldest first, large files only after
  `api/health` answers 200.
- Privacy: the video stays only in this browser. "Saved on this device" is shown wherever it appears and Delete is one
  tap away. Only sizes, counts and statuses are logged (`take_saved_local`, `take_save_skipped`, `pending_retry`,
  `pending_sent`, `pending_resumed`, `pending_deleted`).

## Known limits
- The app has to be open to send. There is no service worker or Background Sync (Safari and Firefox lack Background
  Sync and the app has none today). If the app is closed, sending resumes the next time it opens.
- Safari may evict stored data after a period of not using the site. `navigator.storage.persist()` is asked once, but a
  browser may refuse it.
- A saved take expires after 7 days, the server's retention for uploads.
- The whole file is resent after a failure (no resumable or chunked upload).
- A failed analysis job is not retried (out of scope); neither is offline catalog browsing.
- `api/people` carries no key (it is not one of the four routes), so a lost people-job response can start a second
  people job; it costs one extra person check and no analysis.
- A take sent in the background does not update a practice-ladder step's pending mark.

## Requires the team's attention
- **`make check-7` has not run for this change.** It needs an NVIDIA GPU; on the dev Mac it stops with
  `check-7: nvidia-smi found no GPU`. The change does not touch Parts 1 to 6 or their shared files, but the check should
  be run once on the GPU host before release.
- **`Idempotency-Key` is new server behaviour.** Deploy the server with this change before the web app is relied on to
  retry; an older server ignores the header and a retry after a lost response could then make a second job.
- Known issues from the video-quality lane still apply (`tests/test_parts.py::test_p4_and_p5_adapters`, the
  `modules/part-5` pin, `feature_checks.unit.test.mjs`).
