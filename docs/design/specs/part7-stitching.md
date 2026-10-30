# Spec: Simon Part 7, stitching Parts 1 to 6 into one app (master)

> Copy of `docs/specs/part7-stitching.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted (setup, 2026-10-28). Amended 2026-10-30 (rescope, ADR-0006)
Date: 2026-10-28
Linked PRD: none. Requirements source: this repo's `README.md` (Part 7 of moalborati/simon
`docs/MINI-APPS.md`), the project plan (use cases record expected, follow and analyse, done check, submission demo;
milestones S0, M1, M2, M3) and the operator
directive of 2026-10-28 ("put all the parts together and create a full simon integration demo end to
end, get your own test videos") and the operator directive of 2026-10-30 (the eight-step journey,
verbatim in `journey.md`).
Request Type: new-app
Risk Level: high (GPU inference, six upstream parts, unattended, public submission)
ADRs: ADR-0001 (workspace, publish), ADR-0002 (black box, pins), ADR-0003 (app architecture),
ADR-0004 (test videos), ADR-0005 (check-7), ADR-0006 (journey rescope). Companion specs: `journey.md`,
`compare-view.md`, `parts-harness.md`, `processor.md`,
`app.md`, `check-7.md`, `test-videos.md`, `staging.md` (firm-only, not published), `demo.md`, `simon-publish.md` (firm-only, not published),
`oneshot-watch.md` (firm-only, not published).

## Overview
Part 7 is the Simon app, built as the eight-step journey in `journey.md`: open the app; a trainer
records or uploads a movement; Parts 1 to 4 turn it into key frames, a skeleton and a 30 fps animation,
and Part 6's `import` puts it in the catalog with the video; a second visitor finds it, plays the video
and rotates its 3D figure; a follower records or uploads a take; Parts 2, 3 and 5 analyse it; the result
shows the two figures in a rotatable 3D compare, the faults as timed sentences written by AI ("at X.X
s", a tap seeks there), and Part 5's score out of 100 with a grade A to F. Part 7 runs every other part from a pinned clone
of its upstream through the commands it publishes, and exchanges only the shared files. `make check-7`
proves on real, openly licensed videos of a movement no part was configured for that the app reports the
same faults as a direct run of Parts 2 to 5.

## Why This Is Wrong (Dissent-First)
1. Six parts, two still being built, one still changing (Part 1): the chain may not run end to end by
   2026-11-03. Answer: pins plus `make chain` at M1 surface each break at one named step; the fallbacks
   in `processor.md` use only options the parts already offer; DEGRADED is an honest ending.
2. Part 6 never passes a video to its processor. Answer: ADR-0006; the trainer entry is made by Part 6
   `import` with the video.
3. Stock clips of other people may be refused by Part 5's guard. Answer: reported to Part 5; check-7's
   coverage metric fails honestly rather than being tuned.

## User Story
As a trainer I record a movement once and it appears in the catalog with its animation. As a follower I
pick it, watch it, perform it to camera and read what I did differently, with the joint shown.

### Jobs-to-be-Done
- Functional: record, catalog, watch, follow, get faults, on a phone.
- Social: the hackathon team shows one take recording an exercise and a follower analysed against it.
- Emotional: the follower trusts the result because it names the body part and shows it.

## Command line (`python -m part7`, also `uv run part7`)
```
part7 pin [--update [<part>...]] [--materialize]   # parts.lock.json; clones under the state dir
part7 setup-parts                                  # each part's documented setup at its pin
part7 doctor-parts                                 # each part's contract or doctor command answers
part7 videos fetch|verify|list                     # test videos from videos/manifest.json
part7 chain [--trainer <clip-id>] [--follower <clip-id>...]   # make chain: every hand-off with its doctor
part7 serve [--host 127.0.0.1] [--port 8727] [--base-path /] [--state <dir>]
part7 check                                        # make check-7
```
Make targets: `setup` (uv sync), `test` (pytest), `pin`, `repin` (`pin --update` then `chain`),
`setup-parts`, `videos`, `chain`, `serve` (dev, 8727), `check-7`.

## Locked defaults
| Item | Decision | Source |
|---|---|---|
| State root | `~/.local/state/simon-part-7/` (`parts/`, `videos/`, `dev/`, `staging/`, `check/`); never the tree | ADR-0002 |
| Clones | `parts/<n>@<sha12>/`, detached at the pinned commit | ADR-0002 |
| Pins | `parts.lock.json`, upstream `main` of each part at run start; `make repin` reruns `make chain` | ADR-0002 |
| Ports | dev 8727, staging 7124 under `/simon-part-7/`; Part 6 child on a free local port | ADR-0003 |
| Runtime | Python 3.12 stdlib only for `part7/`; pytest for tests; three@0.170.0 vendored in `web/vendor/` | ADR-0003 |
| Queue | one worker, one GPU job at a time; Part 2 calls hold `~/.local/state/simon-part-2/gpu.lock` and wait for 12 GiB free GPU memory | ADR-0003, Part 2 `run-app.md` |
| Timeouts | Part 1 15 min, Part 2 20 min, Parts 3, 4, 5 3 min each, doctors 1 min | `parts-harness.md` |
| Uploads | video up to 60 s and 95,000,000 bytes (Cloudflare Free caps request bodies at 100 MB); MP4 or WebM; Part 6's 1 to 120 s duration range; recorder `videoBitsPerSecond: 2500000` | `app.md`, ASM-015 |
| Movement | chosen by the ADR-0004 rule, first candidate: dumbbell lateral raise | ADR-0004 |
| Tolerance | identical `(measure, side, direction)` sets; magnitudes within `max(2.0, 10%)` degrees or `max(0.01, 10%)` metres | ADR-0005 |
| Part 5 exits | 0 and 3 both mean "written, read `status`"; 1 is an error | Part 5 spec, Part 3 CONTRACT Part 7 row |
| Keys | passed only through each part's documented channel at use, never printed or committed | `parts-harness.md` |
| Phrasing | Part 5 `muse-spark --live` on dev and staging; `template` in tests and check-7 | `journey.md` |
| Body profile | `simon-standard` on both sides (Part 3 `--body`) | `journey.md` |
| Key frames | Part 1 keys densified `every:10` (Part 3 `--keyframes-densify`); fallback `every:10` | `processor.md` |
| Score | Part 5 `score` (`simon.score.v1`); Part 7 never computes one | `app.md` |
| Trainer entry | Part 6 `import` with the video | ADR-0006 |
| Visitor quota | per `Cf-Connecting-Ip` | `app.md` |
| Tunnel | quick by default; named when `~/.cloudflared/cert.pem` exists | `staging.md` (firm-only, not published) |

## Files (every source file the run creates; the write gate reads this table)
| File | Role | Ticket | Spec |
|---|---|---|---|
| `pyproject.toml`, `uv.lock` | package, `part7` script, pytest | TICKET-004 | this |
| `Makefile` | targets above; `check-7` replaces the stub | TICKET-004, 025 | this, `check-7.md` |
| `parts.lock.json` | pins (data) | TICKET-003 | `parts-harness.md` |
| `part7/__init__.py`, `part7/__main__.py` | package, `python -m part7` | TICKET-004 | this |
| `part7/cli.py` | subcommands | TICKET-004 | this |
| `part7/config.py` | state root, ports, base path, environment names | TICKET-004 | this |
| `part7/pins.py` | lock file, clone, fetch, detached checkout | TICKET-003 | `parts-harness.md` |
| `part7/runner.py` | subprocess in its own group, timeout, log, step record | TICKET-009 | `parts-harness.md` |
| `part7/gpu_lock.py` | Part 2 GPU lock and free-memory wait | TICKET-009 | `parts-harness.md` |
| `part7/keys.py` | key file presence and the Part 1 dotenv write and removal | TICKET-009 | `parts-harness.md` |
| `part7/parts/__init__.py` | adapter registry | TICKET-010 | `parts-harness.md` |
| `part7/parts/p1_keyframes.py` | Part 1 key frames | TICKET-010 | `parts-harness.md` |
| `part7/parts/p2_pose.py` | Part 2 frames to `pose3d.json`, doctor | TICKET-010 | `parts-harness.md` |
| `part7/parts/p3_skeleton.py` | Part 3 `--view part4` and `--view part5`, doctor | TICKET-010, 034 | `parts-harness.md` |
| `part7/parts/p4_animate.py` | Part 4 animate, contract validate | TICKET-010 | `parts-harness.md` |
| `part7/parts/p5_analyse.py` | Part 5 analyse, doctor | TICKET-010, 044 | `parts-harness.md` |
| `part7/parts/p6_catalog.py` | Part 6 child server, API client, import, doctor | TICKET-005, 010, 039 | `parts-harness.md`, `processor.md` |
| `part7/setup_parts.py` | each part's documented setup at its pin | TICKET-011 | `parts-harness.md` |
| `part7/chain.py` | trainer chain (1, 2, 3, 4, Part 6 import) and follower chain (2, 3, 5) | TICKET-014, 034, 044 | `parts-harness.md`, `journey.md` |
| `part7/media.py` | ffprobe facts, WebM to MP4, trim, y4m for the fake camera | TICKET-009 | `app.md` |
| `part7/movement.py` | the ADR-0004 rule and the candidate record | TICKET-012 | `test-videos.md` |
| `part7/videos.py` | fetch, trim, sha256, SOURCE.md, manifest | TICKET-012, 013 | `test-videos.md` |
| `part7/jobs.py` | queue, one worker, job records on disk, stages | TICKET-016, 039, 042 | `app.md`, `processor.md` |
| `part7/quota.py` | per-visitor and daily job quotas, spend caps | TICKET-042 | `app.md` |
| `part7/server.py` | stdlib HTTP app, API, static files | TICKET-005, 016..020, 039, 041, 042, 044 | `app.md` |
| `part7/proxy.py` | reverse proxy of `catalog/**` to the Part 6 child | TICKET-005 | `app.md` |
| `part7/replay.py` | validates and serves Part 5's replay file; never recomputes alignment | TICKET-020, 044 | `app.md`, `compare-view.md` |
| `part7/check7.py` | `make check-7` driver | TICKET-025, 051 | `check-7.md` |
| `part7/compare.py` | fault set comparison and tolerance | TICKET-025, 051 | `check-7.md` |
| `web/index.html` | app shell | TICKET-005 | `app.md` |
| `web/app.js` | router (`#/`, `#/watch/<id>`, `#/record`, `#/follow/<id>`, `#/job/<id>`, `#/result/<job>`) | TICKET-005 | `app.md` |
| `web/api.js` | calls relative to the base path | TICKET-005 | `app.md` |
| `web/catalog.js` | home: entries from Part 6's API | TICKET-005 | `app.md` |
| `web/watch.js` | trainer video, single-figure 3D viewer, Part 6 entry page in a frame, Follow hand-off listener | TICKET-005, 040 | `app.md` |
| `web/capture.js` | camera preview, MediaRecorder with the bitrate cap, file picker, upload | TICKET-018, 041 | `app.md` |
| `web/record.js` | trainer Record or Upload screen | TICKET-018 | `app.md` |
| `web/follow.js` | follower Record or Upload screen | TICKET-019 | `app.md` |
| `web/job.js` | job progress screen | TICKET-016 | `app.md` |
| `web/result.js` | result screen: score, compare, fault list, refusal text, fixture result | TICKET-006, 020, 047 | `app.md` |
| `web/viewer.js`, `web/joints.js` | three.js figures, bones and joint highlight | TICKET-006, 045 | `app.md`, `compare-view.md` |
| `web/compare.js` | two-figure compare, clock, modes, camera | TICKET-045 | `compare-view.md` |
| `web/score.js` | score panel | TICKET-046 | `app.md` |
| `web/faults.js` | timed fault list, seek and highlight | TICKET-047 | `app.md` |
| `web/style.css`, `web/icon.svg` | look and icon | TICKET-005 | `app.md` |
| `web/vendor/three/**`, `web/vendor/README.md` | three@0.170.0 from npm, unchanged, sha256 listed; covers `web/vendor/three/examples/jsm/controls/OrbitControls.js` | TICKET-006 | `app.md` |
| `bin/dev.sh` | dev server start (published) | TICKET-007 | `staging.md` (firm-only, not published) |
| `staging/**` | up, down, health, env, verify, DEMO.md, Playwright drives (firm-only) | TICKET-007, 008, 022, 023, 028 | `staging.md` (firm-only, not published), `demo.md` |
| `staging/tunnel.sh` | named tunnel setup when `cert.pem` exists (firm-only) | TICKET-043 | `staging.md` (firm-only, not published) |
| `qa/recipes/**` | QA recipes (firm-only), including `second-visitor.yaml`, `follower-record.yaml`, `compare-3d.yaml`, `timed-feedback.yaml`, `score-grade.yaml` | TICKET-008, 022, 048, 049, 050 | `staging.md` (firm-only, not published), `journey.md` |
| `package.json`, `package-lock.json` | Playwright 1.61.1 pinned (firm-only) | TICKET-007 | `staging.md` (firm-only, not published) |
| `videos/manifest.json`, `videos/<clip-id>/SOURCE.md` | test video manifest (data) | TICKET-012, 013 | `test-videos.md` |
| `fixtures/input/analysis-1.2.0.json`, `fixtures/input/replay.json` | Part 5 schema 1.2.0 and replay fixtures shaped as the contract until the re-pin (data) | TICKET-044 | `journey.md` |
| `CONTRACT.md` | what Part 7 reads from each part, at which pin, and how to run it | TICKET-029 | this |
| `docs/app.md` | how to use the app (published) | TICKET-029 | `app.md` |
| `demo/simon-end-to-end.mp4`, `demo/walkthrough.mp4`, `demo/README.md`, `demo/captions.srt` | demos (data) | TICKET-023, 028 | `demo.md` |
| `tests/test_<module>.py` for each module, `tests/conftest.py` | part tests (published) | per ticket | per spec |
| `tests/staging/**` | verify helpers (firm-only) | TICKET-008 | `staging.md` (firm-only, not published) |

`part7/processor.py` is not written: TICKET-017 abandoned, ADR-0006.

## Acceptance Criteria
### AC-001: Pins
`part7 pin` writes `parts.lock.json` with one record per part 1 to 6 (repo, 40-character sha, pinned_at,
status) and materializes each clone at its sha; `pin --update 2` moves only Part 2. (`parts-harness.md`)
### AC-002: Chain with doctors
`make chain` runs the trainer clip through Parts 1, 2, 3 (`--view part4`), 4 and the follower clips
through Parts 2, 3 (`--view part5 --fps 30`), 5; every hand-off's doctor runs; it prints one JSON with a
step record each and exits 0 only when every step and doctor passed. (`parts-harness.md`)
### AC-003: Record into the catalog
Given the app, when a trainer video is recorded or uploaded with a name, then a Part 6 entry with
`files_source: import` and a `video_uri` appears with `keyframes.json`, `skeleton.json`,
`animation.json`, provenance 1 (or 3), 3, 4, Part 6 `doctor` exits 0 on it, and its video plays for a
second visitor. (`processor.md`, `app.md`, `journey.md` AC-J2, AC-J4)
### AC-004: Follow and analyse
Given an entry, when a follower take is recorded or uploaded through Follow, then the result screen
shows Part 5's score and grade, lists Part 5's faults as timed AI text with "at X.X s", a tap seeks to
that time and highlights the fault's joints, the 3D compare shows both figures, and a refused take
shows Part 5's status text with no score and no faults. (`app.md`, `compare-view.md`)
### AC-005: check-7
`make check-7` prints one metrics JSON and exits 0 only when every ADR-0005 gate passes, including the
`score_equal` and `at_s_equal` gates. (`check-7.md`)
### AC-006: Staging
the staging journey verify (`staging/verify.mjs`, firm-only) exits 0 for S0 and again for M2, including Record driven
through Chromium's fake camera fed from a test clip. (`staging.md`, firm-only, not published)
### AC-007: Black box
No file in `part7/` or `web/` imports, copies or vendors another part's code; a test greps for
`import part[1-6]`, `from part[1-6]`, `keyframe_finder`, `simon_anim` in `part7/` and fails on a hit.
### AC-008: Secrets
No key value appears in a log, job record, result, commit or comment; a test feeds a fake key through
the Part 1 adapter and asserts it is absent from every file the run writes under the job directory.
### AC-009: Demo
`demo/simon-end-to-end.mp4` exists, under 3 minutes, H.264, shows all eight journey steps, with every
number in it cited in `demo/README.md` to a run id. (`demo.md`)
### AC-010: Journey
The eight recipes in `journey.md` are validated and the staging journey verify (`staging/verify.mjs`, firm-only) exits
0 on the journey drive. (`journey.md`; `staging.md`, firm-only, not published)

## Error Cases
| Condition | Behavior | Message (plain, shown or logged) | AC |
|---|---|---|---|
| A part's command exits non-zero | the chain stops at that step; the job fails with the stage | `failed:<stage>: <part> exited <n>` (detail in the job log only) | AC-002 |
| A doctor rejects a hand-off | the chain stops; the doctor's first line is kept | `failed:<stage>: <file> rejected by <part> doctor` | AC-002 |
| Part 2 waits for the GPU lock over 30 min | job fails | `failed:pose: the GPU is busy, try again later` | AC-003 |
| Upload over 95,000,000 bytes or 60 s, or not MP4 or WebM | 413 or 400, nothing queued | `The file is too large (95 MB at most).` and siblings in `app.md` | AC-003 |
| Visitor quota reached | 429, nothing queued | `You have used today's analyses. Try again tomorrow.` | AC-010 |
| Part 5 exit 3 (pinned Part 5 before the re-pin) | result shows the warning, an F and the compare view | the warning text from `status.text` | AC-004 |
| Part 2, 3 or 5 cannot see the take | Part 7 writes the analysis (F, warning), job `done` | `app.md` "Always analysed" | AC-004 |
| Part 6 child exits | Part 7 restarts it once; health fails until it answers | `catalog unavailable` in `api/health` | AC-006 |
| Key file missing for Part 1 | Part 3 `every:10` keys, entry provenance says Part 3 | job note `key frames from Part 3, Part 1 unavailable` | AC-003 |

## Edge Cases
- A trainer video with two people: Part 2 single mode keeps its own choice; Part 1 keys use the first
  listed person (Part 3 `--keyframes-person` default). Reported in the job result.
- A mirrored selfie recording: MediaRecorder frames are not mirrored (the preview is mirrored by CSS
  only), so Part 7 never passes `--mirrored`.
- Part 6 seeds an empty catalog with its eight fixture entries; Follow works on them too (their
  animation is synthetic or Part 4's), and the result says which entry was used.
- A follower take slower or faster than 2x: Part 5 exits 1; the result shows its message.

## Non-Functional Requirements Checklist
- Performance: a 15 s follower take returns a result in under 10 min on this host (measured, reported).
- Accessibility: tap targets 44 px, contrast AA, captions in the demo.
- Security: 127.0.0.1 only; per-visitor quota; uploads stored under the state root with
  generated names; no path from a request reaches the filesystem.
- Observability: every step's log under the job directory; `api/health` names each part's pin.

## Negative Requirements (What This Feature Must NOT Do)
- Never import, copy or modify another part's code; never edit another part's repo or workspace.
- Never tune a part, rule, threshold or tolerance to make check-7 pass.
- Never print, log or commit a key or a private URL.
- Never commit video bytes except the demo videos.

## Compromises
### Part 6's processor seam is unused
The seam cannot carry the video (ADR-0006); the trainer entry is made by Part 6 `import`, and Part 7's
job screen shows the stages in place of Part 6's `processing:<stage>` texts.

## Non-Requirements (Explicitly NOT Building)
Accounts (every visitor sees every entry, Part 6's model), sharing, editing entries, multi-person
following, a native app.

## Assumptions
ASM-001 to ASM-015 (the assumption records are kept in the development workspace and not published; each ASM id is stated where it is used).

## Delivery Verification Plan (MANDATORY, from CRD)
- `make test` 0; `make chain` 0; `make check-7` 0 (or DEGRADED with numbers);
  the staging journey verify (`staging/verify.mjs`, firm-only) 0 at S0 and M2; QA recipes validated by an independent
  reviewer; `demo/simon-end-to-end.mp4`; one consolidated review and the delivery checks; fresh-clone check.
### Device/Platform Strategy
Chromium at Pixel 7 size through the gateway (Playwright 1.61.1), plus the fake camera for Record.
### Data
Visitor-made only: entries created through Record or Upload in the app; Part 6's own seeded samples.
### User Journey Definition
The eight steps in `journey.md`: open, trainer Record, a second visitor views it, Follow (record or
upload), the pipeline, the 3D compare, the timed fault feedback, the score and grade.

## Dissent Review (MANDATORY, hooks block implementation without this)
Reviewed at setup, 2026-10-28.
### Concern 1: the schedule
Two days for six parts. Resolution: ADDRESSED_IN_SPEC (work in parallel, fallbacks, DEGRADED).
### Concern 2: framing Part 6
A Part 6 layout change could break Watch. Resolution: ACCEPTED_RISK; pinned, and verify drives it.
### Concern 3: Part 1 spend
Each new trainer video costs Meta API calls. Resolution: Part 1's own guard; staging Record limited to
10 trainer jobs a day; `every:10` fallback.
### Pre-Mortem
It failed because Part 2 never published a runnable entry point: on 2026-10-28 neither upstream `b45a91d`
nor Part 2's committed workspace has `--backend`, and `body3d.py` at `b45a91d` needs pod paths.
Mitigation: the TICKET-002 probe; S0, the app and check-7 built against fixtures; an hourly re-check of
Part 2's upstream until 2026-11-03T06:00Z; then M1 BLOCKED with the evidence and a message to
the Part 2 maintainers. Once `--backend` is published, `--backend cpu` is the fallback for a failed GPU setup,
named in every result.

## Deviations from PRD
- Registry M2 demo says "Upload a trainer squat"; the DoD needs a never-configured movement, so the demo
  uses the ADR-0004 movement. The project plan was updated to match.
- The trainer entry is made by Part 6 `import`, not Part 6's processor seam (ADR-0006).
