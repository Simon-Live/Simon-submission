# ADR-0003: App architecture: Part 7 server in front, Part 6 as the catalog and player behind it

> Copy of `docs/adr/ADR-0003-app-architecture.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted; amended by ADR-0006 (2026-10-30)
Date: 2026-10-28

## Context
Part 6's CONTRACT (read in the Part 6 workspace on 2026-10-28; upstream `main` was `fc3249a`) offers: a read API, `POST api/entries`
that runs a processor plug-in (`SIMON6_PROCESSOR` or `--processor`, called as
`process(recording, report)` with stages `processing:<stage>`), `POST api/import` (files plus an
optional video up to 16 MiB), `SIMON6_BASE_PATH`, `--follow-url`, and the Follow hand-off
`{v: 1, id, name, category, link, manifest, files: {keyframes, skeleton, animation, video}}` by event,
`postMessage` to a parent frame, or URL. Part 6's capture is mocked: its server always passes
`video_path: None` to the processor (`part6/server.py`, `recording = dict(fields, id=entry_id,
video_path=None)`), and a processor result can return only `keyframes`, `skeleton`, `animation` and
`parts`, not a video. Staging allows exactly one HTTP entry point (`127.0.0.1:7124`, prefix
`/simon-part-7/`). The local dev port is 8727.

## Options Considered
### Option 1: Part 7 does everything and only imports finished files into Part 6
- Pros: no correlation problem; the video goes into the entry through `api/import`.
  Cons: "record it in Part 6" becomes "import into Part 6"; Part 6's processor seam goes unused.
  Effort: Low.
### Option 2: Part 7 runs Part 6's server with Part 7's processor, and correlates the video itself
- Pros: Part 6's own Record seam produces the entry (`files_source: processor`, stages shown); Part 6's
  player and Follow hand-off are used as published. Cons: the processor gets no video, so Part 7 must
  hand it over by a key it controls. Effort: Medium.
### Option 3: Part 7 reimplements the catalog
- Pros: full control. Cons: duplicates Part 6; fails "record it in Part 6". Effort: High.

## Decision
Option 2, with Option 1 as the fallback.
- **One entry point.** `python -m part7 serve` (stdlib `http.server`, threading) listens on 127.0.0.1
  (dev 8727, staging 7124, base path `/simon-part-7/` on staging, `/` in dev). It starts Part 6 from its
  pinned clone as a child process on a free local port, with `SIMON6_BASE_PATH=<base>catalog`,
  `--catalog <state>/catalog`, `--max-recordings 30`, `--processor part7.processor:process`,
  `--follow-url <base>#/follow/{id}`, and `PYTHONPATH=<part7 checkout>`. Part 7 reverse-proxies
  `<base>catalog/**` to it (method, body, `Range` and status passed through), so Part 6 is same-origin
  and its pages can be framed.
- **Record and Upload (trainer).** The phone app records with `getUserMedia` plus `MediaRecorder`, or
  picks a file. It sends the bytes to `POST <base>api/uploads`, then `POST <base>api/trainer
  {upload_id, name, category}`. Part 7's server registers a pending recording under the key
  `(name, category, duration_ms)` it measured with ffprobe, then itself calls Part 6
  `POST catalog/api/entries {name, category, duration_ms}`. Part 6's worker calls
  `part7.processor.process(recording, report)`, which claims the pending recording from Part 7 over a
  local internal endpoint guarded by a per-boot token, waits for Part 7's job (Parts 1 to 4) while
  passing its stages to `report`, and returns `{keyframes, skeleton, animation, parts}`. Part 7 keeps the
  trainer video itself under the entry id, because the processor result cannot carry one.
- **One queue.** Part 7 owns the only job queue: one worker, one GPU job at a time, Part 2's
  `~/.local/state/simon-part-2/gpu.lock` held around every Part 2 call. Only one pending recording may
  exist at a time, so the key is unambiguous.
- **Watch and Follow.** The home screen lists entries from `catalog/api/entries`. Watch frames Part 6's
  entry page (`catalog/#/entry/<id>`), which plays the animation with Part 6's player. Part 6's Follow
  button posts `simon:follow` to the parent; Part 7 checks `event.origin` equals its own origin and opens
  its Follow screen. Opened unframed, Part 6 uses the follow URL.
- **Follow (follower).** Record or upload a take; `POST <base>api/follow {upload_id, entry_id}` queues
  Part 2, then Part 3 `--view part5 --fps 30`, then Part 5 `analyse` against the entry's
  `animation.json` read from Part 6's API.
- **Result.** Part 7's own result screen: the fault list in Part 5's words and a 3D replay (Part 7's own
  three.js viewer, three@0.170.0 vendored from npm) of the follower over the expected clip with the
  fault's `joints` highlighted. Part 5's viewer is reused only if Part 5 publishes it as a reusable file
  with a documented interface at the pin; the run checks and records which.
- **Fallback (Option 1).** Only when Part 6 reports the job failed for a reason in its own behaviour,
  or loses the job, the trainer job runs the chain itself and imports through Part 6's documented CLI,
  `python3 -m part6 import <dir> --catalog <catalog> --name <name> --category <category> --part
  keyframes=1 --part skeleton=3 --part animation=4`, so each file's provenance is kept
  (`processor.md`). The job result names the path taken.

## Consequences
- **Positive**: Part 6's seam, player and hand-off are used as published; one port; one queue.
- **Negative**: entries made through the processor have no `video_uri` in Part 6; Part 7 serves the
  trainer video from its own store. A Part 6 visitor who uses Part 6's own Record screen gets a failed
  job ("Record this movement in the Simon app"), because no video is pending.
- **Neutral**: Part 6's server is a child process; Part 7's health includes Part 6's `api/health`.

## Assumptions
- ASM-006: Part 6's worker calls the processor in its own process, so `PYTHONPATH` is enough to import
  `part7.processor`.
- ASM-007: the phone browser records with `MediaRecorder` over the HTTPS tunnel (WebM on Chromium,
  MP4 on Safari).

## Reversal Cost
Medium: Option 1 is already the fallback path; switching to it alone removes code.

## Pre-Mortem (MANDATORY)
1. The pending key collides when two trainers submit the same name. Likelihood: L, Impact: M.
   Mitigation: one pending recording at a time; a second gets 503 "busy, try again".
2. Part 6 blocks its worker while the processor waits on a long GPU job. Likelihood: H, Impact: L.
   Mitigation: Part 6's queue has one worker by design; Part 7's job carries its own timeout (20 min
   per Part 2 call) so the processor always returns.
3. The internal endpoint is reachable through the gateway. Likelihood: M, Impact: M. Mitigation: it
   requires the per-boot token, which only the child process receives in its environment.

## Dissent (MANDATORY)
Reviewed at setup (architect review), 2026-10-28.
- Option 1 is simpler and also puts the video into Part 6. Resolution: the DoD says "record it in
  Part 6"; the processor seam is how Part 6 says recording becomes real. Option 1 stays as the fallback.
- Framing Part 6 ties Part 7's watch screen to Part 6's layout. Resolution: accepted; Part 6 is the
  player of record and is phone-sized.

## Code Backlinks (updated as code is written)
- `part7/server.py`, `part7/proxy.py`, `part7/jobs.py`, `part7/processor.py`, `web/**`.
