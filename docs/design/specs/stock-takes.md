# Spec: stock follower takes for Part 5 (`make stock-outputs`)

> Copy of `docs/specs/stock-takes.md` from the maintainers' working repo at `1bfac92`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-28 (the cut `pexels-5034562-0to7s` added 2026-10-29)
Linked PRD: none. Requirements source: registry use case uc-stock-takes-for-part5; team decision D2 on
the team Part 5 issue #18 (Pexels licence accepted, visual labels accepted); stakeholder-proxy decision 9; Part 5's
request of 2026-10-29 for a 0 to 7 s cut of 5034562 (its scoring is frozen, so the fix is in the data).
Request Type: new-feature
Risk Level: routine
Tickets: TICKET-028 (milestone M2: runs right after the M2 close-out; the registry change from M5 is in
the hub PR, TICKET-035).
ADRs: ADR-0005 (licences), ADR-0006 (outputs and stamps).

## Overview
Part 5 needs real follower takes. Three Pexels clips are named: 5034562 (side, Part 5's expected take),
5034577 (front) and 8837221 (three-quarter). `make stock-outputs` (`part2 stock`) downloads each into
`~/.cache/simon-part-2/stock/` (never committed), extracts frames at 10 fps, runs `part2 run --mode single`
with the default backend and tracker, validates the result, and commits
`fixtures/output/stock/pexels-<id>/{pose3d.json, camera.json, SOURCE.md}`.

A fourth take, `pexels-5034562-0to7s`, is the 0 to 7 s cut of the side clip, made for Part 5. The whole clip
holds the squats, then a bottle reach and about 6 s of standing that Part 5's alignment cannot skip. The three
whole-clip takes stay as they are. The run publishes them right
after the commit (`scripts/simon-publish.sh --pull`, `--dry-run`, real run; the check command is whatever
ADR-0006 sets at that time, `make -s test` before TICKET-022) and then sends one IECB message to
`simon-part-5` naming the upstream commit the publish printed.

## Why This Is Wrong (Dissent-First)
- Pexels may refuse scripted downloads (ASM-007). Then the ticket is blocked with the HTTP status, and
  the operator is asked through the maintainers' operator channel (default: skip the clip, record why).
- Single mode keeps one person; a stock clip with a second person in frame would pick the wrong one.
  The tracker's largest track over the clip is used and `doctor` reports the person count.
- Labels for these takes are visual (D2); Part 2 adds none.

## Interface
```
part2 stock [--clip pexels-5034562|pexels-5034577|pexels-8837221|pexels-5034562-0to7s] [--backend gpu|cpu]
make stock-outputs [CLIP=<take>]   # every take without CLIP
```
Takes (`part2/stock.py` `TAKES`, run in this order):

| Take | Clip | Time range | Angle |
|---|---|---|---|
| `pexels-5034562` | 5034562 | whole clip | side (Part 5's expected take) |
| `pexels-5034577` | 5034577 | whole clip | front |
| `pexels-8837221` | 8837221 | whole clip | three-quarter |
| `pexels-5034562-0to7s` | 5034562 | 0 to 7 s | side (a cut of Part 5's expected take) |

A cut is a `Take(clip, start, end, why)` in `CUTS`; its name, `<clip>-<start>to<end>s`, comes from the range.
A cut reuses its clip's download and samples the clip at 10 fps like a whole take, then keeps the frames timed
`start` to `end` s, both ends included. The kept frames are renumbered from 0, `t_ms` counts from the first of
them and `t0_pts_ms` moves to that frame's PTS, so `t0_pts_ms + t_ms` is still the file clock. Its provenance
adds `source_range_s: [start, end]`.

Download URL: `https://www.pexels.com/download/video/<id>/`. Title for SOURCE.md is read from the page
`https://www.pexels.com/video/<id>/` at run time (the `<title>` or `og:title`), never typed by hand.

SOURCE.md content (same style as `fixtures/input/*/SOURCE.md`):
- Clip: title as fetched, Pexels video `<id>`, page URL.
- Author: the creator name as shown on the Pexels page, fetched at run time; when the page does not show
  one, the line reads "not stated on the page". Never typed by hand.
- Licence: Pexels free licence, https://www.pexels.com/license/.
- Original file: name, size in bytes, resolution, frame rate and duration as read by ffprobe; download
  date (UTC); sha256 of the downloaded video file. The video is not in the repo.
- Time range used: start and end in seconds (`0 to <duration>` when the whole clip is used). For a cut, the
  line also gives the clip's duration and reads "This take is a cut of pexels-<id> made for Part 5: <why>."
- Frames: sampled at 10 fps with `part2 frames`; count.
- Produced by: `part2 stock`, `part2_commit` `<sha>` (local commit the outputs were made from; measured once before
  the run writes its first take, so the same value in every take of a run and never `+dirty` because of the run's own
  files, `docs/design/specs/check-2.md` AC-K16), backend,
  tracker, lifter (from `provenance`).
- Use: follower take for Part 5 (angle: side, front or three-quarter), decision D2 on Part 5 #18.

IECB message (TICKET-028), sent with `scripts/comms.sh send` to `simon-part-5` after the publish: subject
"Part 2 stock takes published", body naming the upstream commit on the team main, the three paths, the angle
of each and that `5034562` is the expected take.

## Files
| File | Role |
|---|---|
| `part2/stock.py` | takes and cuts, download, ffprobe facts, frames, the cut's frame range, run, validate, SOURCE.md |
| `part2/cli.py` | `stock` subcommand |
| `Makefile` | `stock-outputs` |
| `fixtures/output/stock/<take>/` | committed outputs, one folder per take |
| `tests/test_stock.py` | tests with a local HTTP server serving a tiny generated clip and page; no network |

## Acceptance Criteria
### AC-T01: One output dir per take
After `make stock-outputs`, each take's dir holds `pose3d.json`, `camera.json` and `SOURCE.md`;
each `pose3d.json` passes `python -m part2 doctor --for part3` with exit 0.
### AC-T02: SOURCE.md facts are fetched
Title, author, size, sha256, resolution, frame rate and duration in SOURCE.md come from the page, the
file and ffprobe (test: the local fake page and clip produce exactly their values; a fake page with no
author gives "not stated on the page").
### AC-T03: Nothing heavy committed
No video or frame image under `fixtures/output/stock/`; the download cache is under `~/.cache`.
### AC-T04: Provenance
Each `pose3d.json` has `provenance` naming backend, tracker and the source clip id.
### AC-T05: Download failure is explicit
An HTTP error exits 1 with `stock: download of pexels-<id> failed: HTTP <code>` and writes nothing.
### AC-T06: Published, then Part 5 told
The stock outputs are on the team main before the message; the IECB message id and the upstream commit it
names are recorded in STATUS.md.
### AC-T07: A cut is a take of its own
`part2 stock --clip pexels-5034562-0to7s` writes `fixtures/output/stock/pexels-5034562-0to7s/` with the three
files. Its `pose3d.json` holds only the frames timed 0 to 7 s, numbered from 0, and passes `doctor --for part3`.
Its provenance has `source_clip` `pexels-5034562` and `source_range_s` `[0, 7]`. Its SOURCE.md states the range,
the clip's duration and that the take is a cut of pexels-5034562 made for Part 5, with every other field of a
whole take (licence, download URL, sha256, `part2_commit`, backend, one-person mode, 10 fps). The cut reuses the
clip's cached download (test: a fake 2 s clip cut 0.5 to 1.5 s gives 11 frames, `t_ms` 0 to 1000, one download).

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| HTTP error or HTML instead of video | exit 1, nothing written | `stock: download of pexels-<id> failed: HTTP <code>` / `not a video` | AC-T05 |
| No person found | exit 1 | `stock: no person in pexels-<id>` | AC-T01 |
| Output breaks the contract | exit 1 | `stock: pexels-<id> breaks the contract at <path>` | AC-T01 |
| Cut ends at or before its start | exit 1, nothing written | `stock: <take>: end <e> s is not after start <s> s` | AC-T07 |
| Cut ends past the clip | exit 1, nothing written | `stock: <take>: end <e> s is past the clip (<duration> s)` | AC-T07 |
| Cut starts before 0 s | exit 1, nothing written | `stock: <take>: start <s> s is before the clip` | AC-T07 |
| No sampled frame in the cut | exit 1, nothing written | `stock: <take>: no frame between <s> and <e> s` | AC-T07 |

## Edge Cases
- A clip longer than 60 s: kept whole (CLI has no staging cap); frame count recorded.
- A cached download present: reused after its size and sha256 match the recorded values. A cut and its whole
  clip share the download; each take has its own scratch run in the cache.
- A cut that ends exactly where the clip ends is accepted.

## Locked defaults (final)
| Item | Decision |
|---|---|
| Clips | 5034562 side (expected), 5034577 front, 8837221 three-quarter |
| Cuts | `pexels-5034562-0to7s`: 0 to 7 s of 5034562, for Part 5 |
| Frame rate | 10 fps |
| Mode | single |
| Output dir | `fixtures/output/stock/<take>/` (`pexels-<id>` or `pexels-<id>-<start>to<end>s`) |
| Cache | `~/.cache/simon-part-2/stock/` |

## Negative Requirements
- MUST NOT commit the videos. Why: size; the Pexels page is the source.
- MUST NOT invent a title, author or credit. Why: facts only; fetched at run time.

## Assumptions
ASM-007 (Pexels downloads work without a login).

## Dissent Review
Reviewed by: setup lane (architect, opus), 2026-10-28.
### Concern 1: front and three-quarter views stress the one-person backend
Impact: worse 3D. Mitigation: these are Part 5 inputs, not DoD evidence; numbers are not claimed.
Resolution: ACCEPTED_RISK.
### Concern 2: Pexels page markup changes
Mitigation: fall back to `og:title`; if neither exists, SOURCE.md says the title was not available.
Resolution: ADDRESSED_IN_SPEC.
### Concern 3: Part 5 wants skeleton.json, not pose3d.json
Mitigation: Part 5 runs Part 3 first; the neighbour check proves that path. Resolution: ACCEPTED_RISK.
### Concern 4: the content of the cut is Part 5's reading of the clip
Impact: if the squats ran past 7 s, the cut would clip one. Mitigation: the full take's hip height shows three
squat cycles ending before 7 s and a different movement after; Part 2 still adds no action labels (D2).
Resolution: ACCEPTED_RISK.
### Pre-Mortem
1. Download blocked by bot protection. M M, Mitigation: AC-T05, ask with default skip.
2. Wrong person chosen. L M, Mitigation: largest track, doctor person count.
3. Licence questioned. L L, Mitigation: D2 on Part 5 #18 recorded in SOURCE.md.

## Requirements Traceability
| Requirement | AC | Ticket |
|---|---|---|
| uc-stock-takes-for-part5 | AC-T01 to T06 | TICKET-028 |
| Part 5's request for a 0 to 7 s cut (2026-10-29) | AC-T07 | none (lane STOCK2) |

## Delivery Verification Plan
`make stock-outputs` exit 0, `doctor` exit 0 on each file, neighbour check includes the three takes, IECB
message id in STATUS.md.
