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
| `GET api/samples` | | `{expected: [{id, set, movement, label}], followers: [{id, set, angle, light, label, faults}], phrasing: [<offered backends>], phrasing_default: <one of them>}` from committed fixtures |
| `POST api/analyse` | `{expected: {sample: id} \| {upload: <json>}, follower: {sample: id} \| {upload: <json>}, phrasing: "template" \| "local-llm" \| "muse-spark"}` | `{analysis: <simon.analysis.v1>, replay: {fps, expected: [[[x,y,z] x17] per frame], follower: [...], exp_to_fol: [follower frame per expected frame], joints, bones}}` |
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
  `verify.mjs`, `walkthrough.mjs`, `DEMO.md` (visitor sections only under "For visitors").
- No secret is committed or copied into the staging tree; the only key the server may read is the
  operator key file above, from its firm location.
- `staging.sh up simon-part-5` then `staging.sh verify simon-part-5` exit 0. The registry
  staging environment `status: available` lands through the run's own hub PR that edits only
  `engagements/simon-part-5.yaml` (brief, section 0).
- Local dev: `scripts/dev.sh` (firm only) starts the server on `127.0.0.1:8725` detached; `scripts/dev.sh
  stop` stops it; health `curl -fsS http://127.0.0.1:8725/api/health`. `make demo` (published) serves in
  the foreground on its own port, 8735, so the two never clash.

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
(AC-V20: a changed take, example, upload or wording; the saved file is the last pair's). The exit code is the verdict.

## QA recipes and video
- Recipes with the `qa-recipe` skill (ADR-0020), one per use case driven on staging: each edge driven by
  hand through the real UI, two independent witnesses, a negative assertion (for example a warned take is
  never called a correct take; a correct take shows no fault rows).
- `demo/staging-walkthrough.mp4` recorded through the staging gateway address, under 90 s and
  under 15 MB, H.264: pick, Analyse (score, timed lines), replay, tap a fault, upload, a different movement
  warned and graded F, preview at phone width. The recording chooses Template before each Analyse (AC-V19),
  so it makes no live call.

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

## Deviations from PRD
None.
