# ADR-0006: The eight-step journey: trainer entries by Part 6 import with the video, Part 5's score and timed AI feedback, a 3D compare

> Copy of `docs/adr/ADR-0006-journey-rescope.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted
Date: 2026-10-30
Amends: ADR-0003 (the trainer entry path, the result screen), ADR-0005 (the entry gate, two new gates).
Source: operator directive of 2026-10-30 (quoted in [`journey.md`](../specs/journey.md)) and research
of the same day.

## Context
The operator defined the finished app as one journey of eight steps: open the app; a trainer records a
movement; it is in the cloud for others to view; a user selects it and records or uploads their own
take; the pipeline analyses the take against the trainer's; the two 3D simulations come back to view,
rotate and compare; the faults read as timed sentences ("Foot is too far right at 2s"), written by AI
in words a person understands; and a score out of 100 with a grade A to F.

Research on 2026-10-30 against the pinned parts found these gaps:
- Part 6's server passes `video_path=None` to its processor and its web page has no `<video>` element,
  so an entry made through the processor seam carries no video for a second visitor (step 3). An entry
  made by `python3 -m part6 import` carries the video (`video_uri`, served with HTTP 206) and is exempt
  from Part 6's cap of 30 visitor recordings.
- Part 5's faults carry `follower_frames` but no seconds, there is no score, the replay payload
  (`exp_to_fol`, per-frame positions) is internal, and its Muse Spark phrasing backend is off unless
  `META_LIVE=1` and forbids numbers in its text (steps 6, 7, 8).
- Part 1 gives 3 to 5 keys per repetition; Part 4's animation then strays from the pose by a median
  0.26 m, against 0.024 m with a key every 10 ticks. Part 3 has no option to keep Part 1's keys and add
  dense ones.
- Part 2 rejects browser MediaRecorder WebM that has no duration field (its staging probe).
- Part 4 errors are uncaught tracebacks with exit 1.
- The staging tunnel is a Cloudflare quick tunnel (the URL changes on restart) and Cloudflare Free caps
  a request body at 100 MB, below Part 7's 200 MB upload limit.

Parts 2, 3, 5 and 6 were developed in separate workspaces; their follow-ups are filed in their own repos on 2026-10-30 as
the cross-part contract in [`journey.md`](../specs/journey.md). Parts 1 and 4 belong to the the team team.

## Options Considered
### Option 1: keep the processor seam; Part 7 serves the trainer video from its own store
- Pros: no change to ADR-0003. Cons: the video lives outside the catalog, so another Part 6 client
  never sees it; the entry counts against Part 6's cap of 30 and is trimmed; the claim protocol stays.
  Effort: Medium.
### Option 2: the trainer job runs Parts 1 to 4 itself, then imports the files and the video through Part 6's documented `import` CLI
- Pros: the entry carries the video and per-file provenance as Part 6 publishes them; no side channel;
  cap-exempt; one code path for the app and check-7. Cons: Part 6's processor seam goes unused, and its
  `processing:<stage>` texts are replaced by Part 7's own job screen. Effort: Low.
### Option 3: Part 7 keeps its own catalog
- Pros: full control. Cons: drops Part 6. Effort: High.

## Decision
Option 2, plus the cross-part follow-ups.
- **Trainer entry.** `POST api/trainer` queues a trainer job: Part 1, Part 2, Part 3 (`--view part4`,
  `--body simon-standard`, Part 1's keys densified `every:10`), Part 4, then `python3 -m part6 import
  <dir> --catalog <catalog> --name <name> --category <category> --part keyframes=1 --part skeleton=3
  --part animation=4` with the normalized trainer `video.mp4` in `<dir>`. The entry has
  `files_source: import`, a `video_uri`, and provenance 1, 3, 4 (3, 3, 4 when Part 1 failed). The
  processor seam (TICKET-017) is abandoned as superseded; `part7/processor.py` is not written.
- **Reading of the DoD.** "Record it via Part 6": the camera capture is Part 7's; the entry is created
  by Part 6's own documented command and lives in Part 6's catalog, played by Part 6's player and
  listed by Part 6's API. ADR-0003's dissent answer ("the processor seam is how Part 6 says recording
  becomes real") is withdrawn: the seam cannot carry the video the journey needs.
- **Follower path.** Part 2, Part 3 (`--view part5 --fps 30 --body simon-standard`), Part 5 `analyse
  --replay <job>/replay.json --phrasing muse-spark --live` on staging and dev, `--phrasing template` in
  tests and check-7. Same pins and the same body profile on both sides.
- **Result.** Part 5's `score`, the faults' `at_s` and `text_timed`, and Part 5's replay file drive the
  result screen: score and grade, the 3D compare ([`compare-view.md`](../specs/compare-view.md)), the timed fault list.
  `part7/replay.py` validates and serves Part 5's replay file; it never recomputes alignment.
- **check-7.** The entry gate expects `files_source: import` with a `video_uri` and provenance 1|3, 3,
  4. Two gates are added: `score_equal` (`score.value` identical in both paths) and `at_s_equal` (equal
  `at_s` for every matched fault), and the app result must carry `score` and every fault's `text_timed`.
- **Cloud.** Quick tunnel by default; a named tunnel on the operator's domain when
  `~/.cloudflared/cert.pem` exists (`staging.md`, firm-only, not published). Uploads capped at 95,000,000 bytes, the
  browser records at a capped bitrate, a per-visitor GPU job quota keyed on `Cf-Connecting-Ip`.

## Consequences
- **Positive**: the journey's eight steps each map to a screen, an API and a published part option;
  a second visitor sees and plays the trainer's video from the catalog.
- **Negative**: Part 6's processor seam and its stage texts are unused; the job screen shows Part 7's
  stages instead. The result depends on Part 5 schema 1.2.0; until the Part 5 re-pin lands the app is
  built against a fixture shaped as that schema.
- **Neutral**: `part7/processor.py` leaves the master Files table.

## Assumptions
- ASM-014: Part 6's running server lists an entry that its `import` CLI wrote into the same catalog
  directory, without a restart.
- ASM-015: Cloudflare Free rejects a request body over 100 MB; 95,000,000 bytes stays under it.

## Reversal Cost
Low: Option 1 is specified in `processor.md` history (git) and can be restored as a second path.

## Pre-Mortem (MANDATORY)
1. Part 6's server does not see a CLI import until restart. Likelihood: L, Impact: H. Mitigation: the
   first check of TICKET-039 tests it; if it fails, Part 7 uses Part 6's `POST api/import` (video up to
   16 MiB, so the trainer video is re-encoded under it) and records the choice.
2. The cross-part follow-ups are not published by the re-pin cut-off. Likelihood: M, Impact: H.
   Mitigation: Part 5 and Part 3 go first; Part 7 builds against fixtures shaped as the contract; the
   run ends DEGRADED naming the missing field rather than computing a score itself.
3. Live AI phrasing fails or is slow on staging. Likelihood: M, Impact: M. Mitigation: Part 5 falls
   back to its template text and records `phrasing.fallback_reason`; the result shows the text either
   way and the run reports the fallback count.

## Dissent (MANDATORY)
Reviewed at the rescope (architect review), 2026-10-30.
- The README DoD says "record it via Part 6", and import is not recording. Resolution: accepted risk;
  the entry is made and held by Part 6's published command, and the delivery notes state the path plainly.
- A score computed by Part 7 would avoid waiting on Part 5. Resolution: rejected; the score belongs
  with the analysis, and two scoring rules would disagree.

## Code Backlinks (updated as code is written)
- `part7/jobs.py`, `part7/chain.py`, `part7/parts/p3_skeleton.py`, `part7/parts/p5_analyse.py`,
  `part7/parts/p6_catalog.py`, `part7/replay.py`, `part7/check7.py`, `part7/compare.py`, `web/**`.
