# Spec: Journey follow-up J1 (browser recordings without a duration; the call Part 7 makes)

> Copy of `docs/specs/journey-followup.md` from the maintainers' working repo at `f43deee`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-30
Linked PRD: none. Requirements source: operator directive of 2026-10-30 (the full Simon app journey: a trainer
records a movement, others view it in the cloud, a viewer records or uploads their own take, the pipeline analyses
faults, 3D replays to rotate and compare, timed feedback, a score out of 100 with a grade from A to F) and the
journey research of 2026-10-30. Parent spec: `docs/design/specs/run-app.md` (uploads and limits).
Request Type: bug-fix (J-1) and docs (the Part 7 call)
Risk Level: routine (one function on the upload path; limits unchanged)
Tickets: TICKET-039. Milestone: J1.

## Overview
A browser recording made with MediaRecorder is a WebM file that often carries no duration, neither on the
container nor on the video stream. The command line reads such a file (it decodes the frame timestamps), but the
run API refuses it: `part2/runapi.py` `probe_video` computes `duration` from ffprobe's `format.duration`, then the
largest stream `duration`, gets 0 from both and answers 422 `no_frames` (lines 287 to 291 at `c1070de`). The fix:
when both durations are missing, take the duration from the decoded frame timestamps that `ingest_frame_count`
already reads (`part2.frames._probe_timestamps`), and keep the 60 s and 200 MB limits exactly as they are. The
spec also records in `CONTRACT.md` the one command Part 7 runs for a viewer's take.

## Why This Is Wrong (Dissent-First)
1. Decoding every frame timestamp of a 200 MB upload before accepting it costs one more ffprobe pass. Answer: the
   pass already runs today (`ingest_frame_count`); the fix reads the timestamps once and uses them for both the
   duration and the frame count, so a file with a duration costs no more than before.
2. A file whose container lies about its duration (a stale header) still passes on the header. Answer: out of
   scope; the 601-frame cap counts the decoded timestamps, so a long file still meets `too_long` there.
3. Patching the API instead of remuxing the upload (`ffmpeg -c copy`) leaves other duration-less tools broken.
   Answer: nothing downstream reads the container duration; `part2 frames` works from timestamps already.

## User Story
As a viewer who records a take in the browser, I want the upload accepted like any other video, so that I get my
analysis instead of "no frames".

### Jobs-to-be-Done
- Functional: a MediaRecorder WebM (VP8 or VP9, with or without Opus audio) runs end to end.
- Emotional: the take just recorded is never refused for a reason the viewer cannot see.
- Social: Part 7 can rely on one documented command.

## API / Interface Contract
`probe_video(path, limits, timeout_s=60.0) -> str` keeps its signature and its answers:

| Step | Rule |
|---|---|
| 1 | ffprobe `-count_packets` as today; not mp4, mov or webm, or no video stream: 415 `unsupported` |
| 2 | no video packets: 422 `no_frames` |
| 3 | `duration` = `format.duration`, else the largest video stream `duration` (unchanged) |
| 4 (new) | when step 3 gives 0 or nothing, `duration` = `max(pts) - min(pts)` over `part2.frames._probe_timestamps(path)`; timestamps unreadable, or the read timed out: 415 `unsupported`; none: 422 `no_frames` |
| 5 | `duration > limits.video_s` (60 s): 422 `too_long` (unchanged message "Videos can be at most 60 seconds long.") |
| 6 | frames at `limits.fps` over the same timestamps `> limits.max_frames` (601): 422 `too_long` (unchanged) |

The timestamps are read at most once per call: steps 4 and 6 share one list (a private helper returns it;
`ingest_frame_count(path, fps)` keeps its public signature and behaviour). The 200 MB body cap is enforced before
`probe_video` (`body_cap`) and is not touched. The return value stays the extension (`.webm`, `.mp4`, `.mov`).

### The timestamp read cannot hang (review residual R17, 2026-10-31)
`part2.frames._probe_timestamps` decodes every frame to read its timestamp. It runs ffprobe through `frames._run`,
which now takes an optional `timeout` (seconds, default none, so the ffmpeg extraction is unchanged), and passes
`frames.PROBE_TIMEOUT_S`. When ffprobe has not answered by then, `subprocess` kills it and `_run` raises
`RuntimeError("ffprobe timed out after <N> s")`. That error is a `RuntimeError`, so:

- in `runapi.probe_video` the existing "timestamps unreadable" row applies: 415 `unsupported`, so an upload that
  hangs the probe is refused (fail closed) and the request thread is freed;
- in `part2 run`, `part2 track` and `part2 frames` the CLI prints `part2: ffprobe timed out after <N> s` and exits 1.

`PROBE_TIMEOUT_S = 120.0` is the one constant (tests patch it to a fraction of a second). Why 120 s: the timestamp
pass is a decode, not a header read, so it needs more than the 60 s that `probe_video` gives its packet count. Measured on
this host on 2026-10-31 (22 cores, ffprobe decodes on one thread): 60 s of 1080p at 30 fps (1800 frames, H.264)
took 2.3 s; 60 s of 4K at 60 fps (3600 frames, H.264, 464 MB, so already over the 200 MB upload cap) took 12.9 s. The
largest upload the app admits therefore clears the limit about 50 times over, and a slow or busy host still has
room, while a probe that is truly stuck is stopped after two minutes. The same limit applies to a local `part2 run`;
a local video that needs more than 120 s to decode its timestamps (very roughly 50 minutes of 1080p) is refused with
the timeout message and must be cut first.

### The call Part 7 makes (`CONTRACT.md`, section "How Part 7 runs a take")
```
part2 run --mode single --input <take.webm|take.mp4|take.mov> --out <dir> --fps 10 --backend gpu [--mirrored]
```
`--out` is required by the CLI and is part of the call. `--mirrored` is passed for a front-camera (selfie)
recording saved as a mirror image. Part 7 then runs Part 3 `--view part5` on `<dir>/pose3d.json`.

## Acceptance Criteria
### AC-J01: a WebM without any duration is accepted
Given a WebM with no `format.duration` and no stream `duration` (made as in "Test media" below) of 2 s at 30 fps,
when `probe_video` runs with the default limits, then it returns `.webm`, and ffprobe on the file shows
`format|duration=N/A` (the test asserts the precondition, so it never passes on a file that has a duration).
### AC-J02: VP8 and VP9 both work
Given the same recipe with `libvpx` (VP8) and with `libvpx-vp9` (VP9), each with an Opus audio track, when
`probe_video` runs, then both return `.webm`, and `ingest_frame_count(path, 10)` equals the frame count that
`part2 frames --fps 10` writes for that file.
### AC-J03: the 60 s limit still holds without a duration
Given a duration-less WebM of 61 s at 1 fps, when `probe_video` runs, then it is 422 with the message "Videos can
be at most 60 seconds long."; a duration-less WebM of 59 s at 1 fps is accepted.
### AC-J04: the frame cap still holds
Given a duration-less WebM whose span is under 60 s, with `Limits(max_frames=5)` and `fps` 10, when `probe_video`
runs, then it is 422 `too_long`.
### AC-J05: files with a duration are unchanged
Given the existing tests (`test_mp4_and_webm_videos_are_read`, `test_a_video_over_the_duration_limit_is_422`,
`test_an_mp4_without_a_video_stream_is_415`, `test_a_text_file_renamed_mp4_is_415`), when run, then they pass
unchanged, and for a file with `format.duration` the timestamp pass is never needed for step 3 (asserted with a
spy on the helper that counts calls: exactly one timestamp read per `probe_video` call).
### AC-J06: a rotate-tagged MP4 stays upright
Given a 320x240 MP4 tagged with a 90 degree display rotation, when `part2 frames` ingests it, then the first frame
is 240 wide and 320 high (ffmpeg applies the display matrix), and `probe_video` returns `.mp4`.
### AC-J07: the Part 7 call is documented
Given `CONTRACT.md`, then the section "How Part 7 runs a take" names the command above, `--mirrored` and the
follow-on Part 3 call; `tests/test_contract.py` keeps passing (the compatibility table is unchanged).
`test_j07_contract_md_names_the_part7_call` reads that section, asserts the command line, fills its placeholders and
parses it (with and without `[--mirrored]`) through `cli._build_parser()`, so a renamed option fails the test; it also
asserts that the options table lists exactly the command's options and that the Part 3 follow-on names
`<dir>/pose3d.json` and `--view part5`.

### AC-J08: the span is the largest timestamp minus the smallest
Given a duration-less video whose decoded timestamps are not in order (a fake list `[0.0, 90.0, 0.1]`), when
`probe_video` runs with the default limits, then it is 422 `too_long` (the old `pts[-1] - pts[0]` read 0.1 s and
accepted it). Given `[5.0, 3.0, 1.0]` and `Limits(video_s=3.5)`, then it is 422 `too_long` too (the old span was
negative). Given `[5.0, 3.0, 1.0]` and the default limits, then it is accepted.
### AC-J09: a hung timestamp read is refused
Given an ffprobe that never answers (the subprocess is replaced by one that sleeps, with `PROBE_TIMEOUT_S` set to a
fraction of a second), when `part2.frames._probe_timestamps` runs, then it raises `RuntimeError` whose message names
the timeout ("ffprobe timed out after ... s") within a second and the hung process is killed; `probe_video`
on a valid video, with and without a duration, is 415 `unsupported` ("This file is not a video or photo the app can
read."); `part2 frames` and `part2 run` exit 1 with `part2: ffprobe timed out after ... s` on stderr. `_run` without a
timeout and `_probe_timestamps` with a normal ffprobe are unchanged (the existing frame tests pass).

### Rule-Based ACs
- AC-NFR-J01: one ffprobe timestamp pass per `probe_video` call, never two. Verification: test (spy).
- AC-NFR-J02: no new dependency; ffprobe stays the only probe. Verification: inspection.

## Test media
Built in the test with ffmpeg 6.1 (`tests/test_runapi.py` helper `video_without_duration`), never committed:
```
ffmpeg -v error -f lavfi -i testsrc2=size=64x48:rate=<fps> -f lavfi -i sine=frequency=440 -t <s> \
  -c:v libvpx|libvpx-vp9 -c:a libopus -live 1 -f webm pipe:1 > take.webm
```
Writing to a pipe with `-live 1` leaves the container and stream durations empty, as a MediaRecorder file does.
Checked on 2026-10-30 on this host: `ffprobe -show_entries format=duration:stream=duration` printed `N/A` for
both, for VP8 and VP9 (video only). The rotation case: `ffmpeg -display_rotation 90 -i plain.mp4 -c copy rot.mp4`;
the first decoded frame came out 240x320. The research files in the session scratchpad (`journey-b/vids/`:
`mr_vp9_opus_vfr.webm`, `mr_vp9_vfr_real.webm` with no duration, `rot90.mp4`, `iphone_hevc_rot.mov`) are a manual
cross-check only; they are not in the repo and no test may need them.

## Error Cases
| Condition | Behavior | Message format | AC Reference |
|---|---|---|---|
| No duration and the timestamps cannot be read | 415 `unsupported` | "This file is not a video or photo the app can read." | AC-J01 |
| The timestamp read (any video, step 4 or 6) does not finish within `PROBE_TIMEOUT_S` | 415 `unsupported` (the same row); `part2 run`, `track` and `frames`: exit 1 | API: unchanged. CLI: `part2: ffprobe timed out after 120 s` | AC-J09 |
| No duration and no decoded frame | 422 `no_frames` | unchanged | AC-J01 |
| Span over 60 s | 422 `too_long` | "Videos can be at most 60 seconds long." | AC-J03 |
| More than 601 frames at 10 fps | 422 `too_long` | unchanged | AC-J04 |
| ffprobe missing | 503 `no_ffprobe` | unchanged | AC-J05 |

## Edge Cases
- One decoded frame and no duration: the span is 0, which is not over the limit, and the frame count is 1: the
  file is accepted like a one-frame video with a duration (AC-J01 helper with `-frames:v 1`).
- Variable frame rate (MediaRecorder): the span uses real timestamps, so a stretched or uneven clock still gives
  the true length (AC-J02).
- A WebM whose stream has a duration but whose container has none: step 3 already reads the stream (unchanged).
- First timestamp above 0: the span `max(pts) - min(pts)` measures the clip, not the clock offset; for ordered
  timestamps it equals the `t_ms` rule of `part2.frames` (time from the first decoded frame).
- Timestamps out of order (a damaged or spliced stream): `max(pts) - min(pts)` is never negative and a late
  timestamp cannot hide a long span behind a small last value, so a stream that spans more than 60 s is refused
  whatever order its frames report (AC-J08). `part2.frames` itself is unchanged by this.
- A file whose timestamp read exceeds `PROBE_TIMEOUT_S` (a corrupt stream that stalls ffprobe's decoder) is refused
  with the "timestamps unreadable" answer, not waited for (AC-J09). The first ffprobe pass of `probe_video` keeps its
  own 60 s `timeout_s`.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|---|---|---|---|
| Performance | Probe cost | one timestamp pass, as today | AC-NFR-J01 |
| Security | Upload limits | 200 MB body, 60 s, 601 frames, unchanged | AC-J03, AC-J04 |
| Reliability | Error handling | 415 or 422 with the existing plain messages | Error Cases |
| Maintainability | Tests | every AC named in a test | all |
| Compatibility | Browsers | MediaRecorder WebM from Chromium and Firefox (VP8, VP9) | AC-J02 |
| Accessibility | N/A | no UI text changes | |

## Negative Requirements
- MUST NOT raise or remove the 60 s, 200 MB or 601-frame limits. Why: staging safety (run-app.md AC-A07).
- MUST NOT remux or rewrite the upload. Why: the frames come from the file as recorded.
- MUST NOT change the output files or their versions. Why: no consumer change is needed.

## Compromises
None.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `part2/runapi.py` | `probe_video` duration fallback from frame timestamps; one shared timestamp read; span `max(pts) - min(pts)` (R17) | TICKET-039, R17 | yes |
| `part2/frames.py` | `PROBE_TIMEOUT_S`, an optional `timeout` on `_run`, the timeout on the ffprobe timestamp read (R17) | R17 | yes |
| `tests/test_runapi.py` | AC-J01 to AC-J05, helper `video_without_duration`; AC-J08, AC-J09 (probe side) | TICKET-039, R17 | yes |
| `tests/test_frames.py` | AC-J06 (rotate-tagged MP4 upright); AC-J09 (the hung read, CLI side) | TICKET-039, R17 | yes |
| `docs/design/specs/run-app.md` | "Uploads and limits": a video without a duration is measured by its frame timestamps | TICKET-039 | yes |
| `CONTRACT.md` | section "How Part 7 runs a take" (written with this spec) | TICKET-039 | yes |
| `tests/test_contract.py` | AC-J07 (`test_j07_contract_md_names_the_part7_call`) | TICKET-039 | yes |

## Delivery Verification Plan
- `uv run pytest -q tests/test_runapi.py tests/test_frames.py tests/test_contract.py` exit 0, then `make test` 0.
- `make check-2-contract` 0 and `make check-2` 0 (unchanged outputs).
- Staging: the maintainers' staging start and `verify simon-part-2` exit 0; one upload of a
  duration-less VP9 WebM through the run page reaches `done` (QA recipe edge, two witnesses: the job state in
  `api/jobs/<id>` and the rendered skeleton; negative: a 61 s duration-less file shows the 60 s message).
- Publish with `scripts/simon-publish.sh`, then `make test` in a fresh clone.

### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|---|---|---|---|
| Desktop Chromium | Playwright (`staging/verify.mjs`) | 1440 | TICKET-039 lane |

### Data
Media generated in the tests; no committed video.

## Dissent Review
### Concern: the span undercounts by one frame interval
`max(pts) - min(pts)` stops at the last frame's start, so a file with a duration header reads up to one frame longer
than the same file without one. Kept: at 30 fps that is 33 ms against a 60 s limit, and the frame cap, which both
paths share, is the binding limit for long clips.

## Deviations from PRD
The brief says "use the last ffprobe frame timestamp". This spec uses the largest timestamp measured from the
smallest (`max(pts) - min(pts)`; first written as `pts[-1] - pts[0]`, which R17 replaced so out-of-order timestamps
cannot shrink or negate the span). It equals the brief's value whenever the first frame is at 0 and the timestamps
are in order, as MediaRecorder files are, and matches the `t_ms` rule of `part2.frames` for files that start later.

## People follow-up (TICKET-040 and TICKET-041)
Requirements source: Part 7 `docs/design/specs/people.md`, "Part 2 follow-up". Part 7 shows a picker of the people in a
take, then needs 3D for the chosen ones only. Additive: no file gains a field and no version changes.
The criteria are AC-P01 to AC-P09. They were numbered AC-K01 to AC-K09 until 2026-10-31, which collided with the
AC-K ids of `docs/design/specs/check-2.md` (scored outputs and stamps); the two sets are unrelated.

### Interface
```
part2 track --input <video|dir> --out <dir> [--fps 10] [--tracker <name>] [--tracker-order scored|bulk]
part2 run --mode multi ... [--tracks <tracks.json>] [--ids <id,id,...>]
```

### Acceptance Criteria
- AC-P01 `track` writes `<dir>/frames/` and `<dir>/tracks.json` and no other file; `tracks.json` passes the tracks
  contract and its provenance names the tracker and no backend.
- AC-P02 `track` exits 0 when written, 1 for an unreadable input, 2 for a bad option (unknown tracker, bad
  `--tracker-order`).
- AC-P03 `track` runs no 3D estimate.
- AC-P04 `run --tracks` runs no tracker (no registry call, no model load); `<out>/tracks.json` equals the given
  file's frames, so ids are unchanged.
- AC-P05 With `--ids`, the 3D estimate gets the boxes of the listed ids only; `pose3d.json` holds those people and
  `pose3d_person_<id>.json` exists for each of them and for no one else.
- AC-P06 An id the tracks lack: exit 1, the message names it, no `pose3d.json` is written. With `--tracks` the ids
  are checked against the file before any frame is ingested, so nothing is written and nothing is decoded; without
  `--tracks` the ids can only be checked once the tracker has run.
- AC-P07 `--tracks` must cover exactly the frames of the input (the set of frame numbers in the file equals the set
  ingested at the given `--fps`). A frame of the input the file lacks, or a frame in the file the input lacks (a
  file made at a higher `--fps` or from a longer clip): exit 1, the message names the first such frame and both
  frame counts and asks "was it made with the same --input and --fps?". No `tracks.json` is written.
- AC-P08 `--tracks` or `--ids` with `--mode single`, or an empty id in `--ids`: exit 2. `--tracker` or
  `--tracker-order` together with `--tracks`: exit 2 (the tracks file already fixed the tracker; naming one is not
  silently ignored). `--ids` without `--tracks` tracks first, then filters.
- AC-P09 A `--tracks` file that cannot be read, is not JSON or fails the tracks contract is an input error: exit 1,
  the message names the file (and, for the contract, the failing path), it is never reported as an output that
  breaks the contract, and no frame is ingested.

### Error Cases
| Condition | Exit | Message |
|---|---|---|
| unknown id | 1 | `part2: unknown person id 99 in --ids; tracks.json has 0, 1` |
| tracks lack a frame of the input | 1 | `part2: --tracks <file> has no entry for frame N of this input (it covers A frames, this input has B; was it made with the same --input and --fps?)` |
| tracks have a frame the input lacks | 1 | `part2: --tracks <file> has an entry for frame N that this input lacks (it covers A frames, this input has B; was it made with the same --input and --fps?)` |
| tracks file unreadable, not JSON or breaks the tracks contract | 1 | `part2: --tracks <file> cannot be read (...)`, `... is not valid JSON (...)` or `... breaks the tracks contract at <path>: <rule>` |
| unknown tracker | 2 | the registry's message |
| `--tracker` and/or `--tracker-order` with `--tracks` | 2 | `part2: --tracker and --tracker-order cannot be combined with --tracks (the tracks file already fixed the tracker)` (names only the options given) |

### Files
| File | Change | Ticket | Published |
|---|---|---|---|
| `part2/cli.py` | `track` command, `--tracks`, `--ids`, shared `_track_stage`; `--input`, `--out`, `--fps` declared once for `frames`, `run` and `track`; the `--tracks` with `--tracker` refusal (AC-P08) | TICKET-040, TICKET-041 | yes |
| `tests/test_cli_track.py` | AC-P01 to AC-P09 with the fakes of `tests/test_cli.py` | TICKET-040, TICKET-041 | yes |
| `CONTRACT.md` | "Several people in one take" and one compatibility row | TICKET-040, TICKET-041 | yes |
| `contracts/compatibility.json` | the same row | TICKET-040, TICKET-041 | yes |
| `tasks/tickets/TICKET-040-*.md`, `TICKET-041-*.md` | tickets | TICKET-040, TICKET-041 | yes |

### Delivery Verification Plan
`uv run pytest -q tests/test_cli_track.py`, then `make test`, `make check-2-contract`, `make check-2` exit 0; one
GPU smoke on the class fixture frames made into a video (`track`, then `run --ids` with two ids).
