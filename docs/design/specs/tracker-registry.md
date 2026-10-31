# Spec: Part 2 tracker registry (SAM 3.1 first, open local fallback, named trackers fail closed)

> Copy of `docs/specs/tracker-registry.md` from the maintainers' working repo at `1c8cb7e`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Requirements source: locked decision 1 (stakeholder-proxy 2026-10-28), hub registry milestone M2,
README "Frontier model" (SAM 3.1 for multi-person tracking). Parent spec: `docs/design/specs/part2-images-to-3d.md`.
Request Type: new-feature
Risk Level: medium (keys handled by code; the scored multi-person result depends on the tracker)
Tickets: TICKET-017 (registry, `api-sam31`, open trackers), TICKET-038 (`local-sam31` and the parity check).
ADRs: ADR-0003 (tracker registry), ADR-0005 (licences), ADR-0006 (reproducible outputs), ADR-0007 (takeover etiquette).

## Overview
`part2 run --mode multi` gains `--tracker api-sam31|local-sam31|local-open|bytetrack` (environment `PART2_TRACKER`;
the flag wins). With no tracker named, the registry walks a fixed order and records which tracker ran (operator
rulings of 2026-10-28, ADR-0003):
- scored outputs and the reference (`make outputs`, check-2): `api-sam31`, then `local-open`;
- staging and bulk runs: `local-sam31` once it has passed the parity check, else `api-sam31` within its cap, else
  `local-open`.

`api-sam31` wraps the existing `part2/track.py` path through the paid Meta API (`MODEL_API_KEY`, verified on
2026-10-28: a real call on the first 50 frames of the single fixture returned 50 frames, 50 detections and one id,
at $0.01 per call). `local-sam31` runs the gated `facebook/sam3.1` weights on the RTX 5090 (`HF_TOKEN`, verified on
2026-10-28: `whoami-v2` HTTP 200, and `config.json` resolves with HTTP 200 for `facebook/sam3.1` and
`facebook/sam3`). `local-open` is SAM 2.1 hiera-large (ungated, Apache-2.0) prompted with person boxes from the
rtmlib detector; ByteTrack is the second open option. A tracker named explicitly never falls back and fails closed
without its key, with a message that names the key file and the open alternative. Every tracker writes the same
`tracks.json` shape, plus an optional `provenance` block naming the tracker, its models and any fallback.

## Why This Is Wrong (Dissent-First)
- A paid tracker first in the scored order spends money on every scored run. The run's Meta budget is $25 and
  staging has its own ($10 in total, $0.50 per job); the local steps cost nothing per frame, and provenance says
  which tracker ran, so a scored result never hides its tracker.
- Parity with the API is not accuracy. Parity only decides where bulk and staging work runs; the scored class
  result stays on `api-sam31`.
- SAM 2.1 is a promptable segmenter, not a detector: people who enter after the first frame are missed unless the
  tracker re-prompts. The adapter re-prompts every 2 s with detector boxes that overlap no live track.
- Keys in code paths leak through logs and tracebacks. The key is read only inside the adapter function that
  makes the call, never stored on an object that is printed, and tests grep all captured output for the fake key.
- ByteTrack masks are boxes, not segmentations. `mask_rle` stays required by the shape, so ByteTrack writes the
  filled box as its mask and provenance says `mask_source: "box"`.

## User Story
As the team, I want multi-person tracking to use SAM 3.1, the frontier model the README names, within a spend
cap, and to keep running on an open tracker when a key or the budget is missing, so that every result is
frontier-grade when it can be and always names what produced it.

### Jobs-to-be-Done
- Functional: `make outputs` tracks the class fixture with `api-sam31`, and with `local-open` when no key is present.
- Emotional: no surprise bill, no leaked key.
- Social: the check output names the tracker, so the team reads the number correctly.

## Interface
```
part2 run --mode multi --input <video|dir> --out <dir> [--tracker api-sam31|local-sam31|local-open|bytetrack]
```
```python
from part2 import trackers
t = trackers.get("local-open")       # unknown name raises trackers.UnknownTracker(name, known)
ok, reason = t.available()           # checks imports and the key's presence, never its value
doc = t.track(frames_dir, out_path)  # writes and returns tracks.json
trackers.names()                     # ["api-sam31", "bytetrack", "local-open", "local-sam31"]
t, skipped = trackers.resolve("scored")  # or "bulk": walks the order; skipped = [(name, reason)]
```
`tracks.json` (unchanged): `{frames: [{frame, people: [{id, bbox: [x, y, w, h], mask_rle: {size, counts},
confidence}]}]}`, ids stable integers from 0 in order of first appearance, built by `track.build_tracks` and checked
by `schema.validate_tracks`. Optional top-level `provenance`: `{tracker, models: [{name, source, weights_sha256,
licence}], mask_source: "sam"|"box", detector, reprompt_every_s, part2_commit, created_utc, fallback_from?,
fallback_reason?: "no_key"|"budget"|"no_parity"|"no_env", spend_usd?}`. `part2_commit` is
`provenance.part2_commit()`, the one rule every writer uses: HEAD, plus `+dirty` when a tracked file differs,
`unknown` without git. Under `make outputs` the run's one measure replaces it (check-2.md AC-K16).

### Trackers
| Name | What runs | Key | Notes |
|---|---|---|---|
| `local-open` (fallback, last in every order) | rtmlib YOLOX person detector on frame 0, SAM 2.1 hiera-large video predictor propagates masks; every 2 s the detector runs again and a box with IoU under 0.3 to every live track starts a new track | none | weights `facebook/sam2.1-hiera-large` (ungated, Apache-2.0; HEAD 200 on 2026-10-28); runs in the gpu-cu128 venv; CPU allowed but slow |
| `bytetrack` | rtmlib YOLOX boxes on every frame, ByteTrack association (starting values: high 0.6, low 0.1, match 0.8, buffer 30 frames) | none | mask is the filled box; licence MIT (verified at TICKET-017 from its LICENSE file) |
| `api-sam31` | existing `part2.track.api_tracker` through `part2.meta_api` with its budget guard | `<key dir>/MODEL_API_KEY` (env `MODEL_API_KEY` second channel, below) | key verified 2026-10-28; paid ($0.01 per call of 50 frames on 2026-10-28; prices on thread #18); first in the scored order |
| `local-sam31` | `facebook/sam3.1` weights (SAM 3 code pinned per the team's note in `k8s/README.md`), text prompt "person", in the gpu-cu128 venv on the RTX 5090; weights cached under `~/.cache/huggingface` | `<key dir>/HF_TOKEN` (env `HF_TOKEN` second channel, below) | token verified 2026-10-28; gated weights reachable; no per-frame cost; first in the bulk order once parity passes; shares the cu128 port risk with SAM 3D Body |

### Order and fallback (no tracker named)
| Purpose | Order | Used by |
|---|---|---|
| `scored` | `api-sam31`, `local-open` | `make outputs`, check-2 scored outputs, the reference |
| `bulk` | `local-sam31` (parity passed), `api-sam31` (within its cap), `local-open` | staging jobs, `part2 run` with no tracker named, stock takes |

A step is skipped only for a missing key file (`no_key`), an exhausted budget (`budget`) or, for `local-sam31`, no
committed parity pass (`no_parity`), or packages a step needs that are not installed in the running environment
(`no_env`, added 2026-10-29 so a teammate without the GPU profile keeps the team default `api-sam31`; a tracker named
explicitly still fails closed). Any other failure of a step (API error, CUDA error) fails the run with its
error; it is never turned into a fallback. Provenance names the tracker that ran plus `fallback_from` and
`fallback_reason` of the first skipped step.

### Budget (`api-sam31`)
- Run: `META_BUDGET_USD=25` on the default ledger `~/.simon/meta_spend.jsonl` (whatever it already holds counts).
  STATUS.md records the ledger total at every milestone close-out.
- Staging: ledger `~/.simon/meta_spend_staging.jsonl`, $10 in total, plus $0.50 per job (a second `meta_api.Budget`
  over a ledger in the job directory). Both must accept a reservation. When either cap is hit, the job runs the
  next step of the `bulk` order and the job result says so ("SAM 3.1 spend cap reached; tracked with local-open").

### Parity check (`local-sam31`, TICKET-038)
On the class clip, `local-sam31` against `api-sam31`: the same id count, and per-id coverage (share of frames
where the id is present) within 1 percentage point after matching ids by mask IoU. Label-free: it compares two
tracker outputs and never reads `gt_tracks.json`. The result, both commits and the numbers go into
`progress/sam31-parity.md`; `part2.trackers.resolve("bulk")` reads the committed pass from
`fixtures/output/parity/sam31.json`.

### Keys (`part2/keys.py`)
- `present(name) -> bool` checks the key file exists and is non-empty, or the environment variable is set; it never
  reads the value. `read(name) -> str` is called only inside `api_sam31.track` and `local_sam31.track`, immediately
  before the call that needs it. `api_sam31` sets it as `MODEL_API_KEY` in its own process environment for
  `part2.meta_api` (operator ruling 2026-10-28); `local_sam31` hands it to the Hugging Face client as `HF_TOKEN`.
  The value is never logged, returned, stored on a module attribute or put in an exception message.
- Key directory: `PART2_KEY_DIR`, default `<key dir>/` (tests point it at a temp dir).
- File names follow one convention, the file named after its environment variable: `MODEL_API_KEY`,
  `HF_TOKEN` (only these two are read). The directory is mode 700 and each file 600; `present` reports a
  looser mode as missing with a plain reason (`<name> must be mode 600`). `BASETEN_API_KEY` also lives there;
  Part 2 never reads it.
- Second channel: the environment variable of the same name. It exists for tests and for the team's existing
  `part2/meta_api.py` use (which already reads `MODEL_API_KEY` from the environment); the run never exports a
  key to a shell and the staging server never sets one (a job's own `part2 run` process reads the key file).
  The file wins when both exist.
- The module is `part2/keys.py`, not a module named after secrets: `scripts/simon-publish.sh` refuses any path named
  secret-shaped names or `*token*` (TICKET-034).

## Files
| File | Role |
|---|---|
| `part2/trackers/__init__.py` | registry: `get`, `names`, `resolve`, `UnknownTracker`, flag and env resolution, the two orders |
| `part2/trackers/parity.py` | label-free comparison of two `tracks.json` files (id count, per-id coverage) |
| `fixtures/output/parity/sam31.json` | committed parity result read by `resolve("bulk")` |
| `part2/keys.py` | presence check and the single read path (shared; named so the publish denylist accepts it) |
| `part2/trackers/local_open.py` | SAM 2.1 plus detector, re-prompting |
| `part2/trackers/bytetrack.py` | ByteTrack association over detector boxes |
| `part2/trackers/api_sam31.py` | adapter over `part2/track.py` API path |
| `part2/trackers/local_sam31.py` | gated SAM 3.1 weights adapter; the predictor runs in a child process (`python -m part2.trackers.local_sam31`) because SAM 3.1 turns on bf16 autocast for its whole process, which broke SAM 3D Body in the same run (fixed 2026-10-29); the token is read in the parent and never reaches the child |
| `part2/track.py` (modified) | `track(frames_dir, out_path, tracker=None)` resolves through the registry; `build_tracks`, `mask_to_rle` unchanged |
| `part2/cli.py` (modified) | `--tracker` |
| `envs/gpu-cu128/requirements.txt` (modified at TICKET-017) | SAM 2.1 package pin |
| `tests/test_trackers.py`, `tests/test_keys.py`, `tests/test_tracker_parity.py` | tests; models faked |

## Acceptance Criteria
### AC-R01: registry and precedence
`--tracker bytetrack` with `PART2_TRACKER=local-open` runs ByteTrack; env wins over the order; with nothing set,
the order of AC-R08 applies. Unknown name exits 2 naming the four choices.
### AC-R02: fail closed without a key
With an empty key dir and neither `MODEL_API_KEY` nor `HF_TOKEN` set, `--tracker api-sam31` exits 1 with
`part2: tracker api-sam31 needs the key file MODEL_API_KEY (or the MODEL_API_KEY variable); use --tracker local-open`,
and `local-sam31` likewise with `HF_TOKEN`. No network call is made (test: the client factory is a
fake that fails the test if called).
### AC-R03: the key never appears
With a fake key `FAKE-KEY-DO-NOT-PRINT-123` (not key-shaped, so the publish content check accepts the test) in the temp key dir and a fake client that raises, the captured stdout,
stderr, log records, the written `tracks.json` and the exception text contain no part of the key. Test.
### AC-R04: same shape for every tracker
Each tracker's output on a fake model passes `schema.validate_tracks` and the `contracts/tracks.schema.json`
schema, ids from 0 in order of first appearance, frames matching `frames.json`.
### AC-R05: provenance
Every tracker writes `provenance.tracker` and `models`; ByteTrack writes `mask_source: "box"`. A file without
`provenance` still validates.
### AC-R06: the class bar on `api-sam31`; `local-open` reported beside it
`make outputs` on `fixtures/input/class/` with the `scored` order (`api-sam31`) gives `eval_tracks` coverage at
least 0.95 per ground truth person and at most 1 ID swap per minute, 7 people, each with a pose3d stream.
Verification: `make check-2` multi_person block (TICKET-018), naming `api-sam31`. `local-open` on the class clip is
written to `fixtures/output/scored/class-local-open/` and printed as block `multi_person_local_open`, never gated
(`bytetrack` likewise when run). A miss is reported as it is; the order changes only by a recorded decision in
STATUS.md.
### AC-R08: order and fallback
With no tracker named: an empty key dir gives `local-open` with `fallback_from: "api-sam31"`,
`fallback_reason: "no_key"`; an exhausted fake budget gives `fallback_reason: "budget"`; `bulk` without a committed
parity pass skips `local-sam31` with `no_parity`. An API error on a present key fails the run (no fallback). Test.
### AC-R09: spend caps
A fake staging ledger at $9.80 and a job estimate of $0.30 runs `local-open` and the job result names the cap; a
job whose reservations pass $0.50 stops calling the API. The run's ledger total appears in STATUS.md at each
close-out. Test plus inspection.
### AC-R10: parity check
`parity.compare(a, b)` on hand-made `tracks.json` pairs returns pass for equal id counts and coverage within 1
point, fail otherwise; `tests/test_gold_isolation.py` covers `part2/trackers/parity.py`. The real run on the class
clip is recorded in `progress/sam31-parity.md` (TICKET-038).
### AC-R07: re-prompting picks up late entrants
On a fake two-person clip where person 2 appears at 3 s, `local-open` creates a track for them within 2 s of entry
and does not duplicate person 1.

### Rule-Based ACs
- AC-R-NFR-01: no tracker reads a key it does not need. Verification: test (open trackers run with an
  unreadable key dir).
- AC-R-NFR-02: `api-sam31` keeps the `meta_api.Budget` guard. Verification: inspection and the existing
  `tests/test_meta_api.py`.

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| unknown tracker | exit 2 | `part2: unknown tracker "<x>"; choose local-open, bytetrack, api-sam31 or local-sam31` | AC-R01 |
| key missing | exit 1, no call | `part2: tracker <name> needs the key file <file> (or <ENV>); use --tracker local-open` | AC-R02 |
| budget reached, tracker named | exit 1 | `part2: tracker api-sam31: the spend cap of $<limit> is reached (ledger <file>)` | AC-R09 |
| key absent, budget reached or no parity, no tracker named | next step of the order runs | provenance `fallback_reason` | AC-R08 |
| key rejected (401/403) | exit 1 | `part2: tracker <name>: the key was refused` | AC-R03 |
| gated weights not granted | exit 1 | `part2: tracker local-sam31: access to facebook/sam3.1 is not granted for this token` | AC-R02 |
| no person in frame 0 or any re-prompt | exit 1 | `part2: no person found to track` | AC-R04 |
| GPU lock held | wait up to 10 min, then exit 1 | `part2: another GPU job is running` | AC-R04 |

## Edge Cases
- A person leaves and returns: SAM 2.1 keeps the id while the mask persists; after loss, a re-prompt box matched to
  the lost track's last box by IoU over 0.3 within 3 s reuses the id, else a new id (counted by `eval_tracks`).
- Crowded overlap: masks of two tracks overlapping above IoU 0.8 keep the older id on the larger mask.
- One-frame input: tracking reduces to detection; ids 0..n-1 by box area, largest first.

## Locked defaults (2026-10-28)
| Item | Decision | Why |
|---|---|---|
| Tracker order | scored: `api-sam31`, `local-open`; bulk and staging: `local-sam31` after parity, `api-sam31` within its cap, `local-open` | operator rulings 2026-10-28 (both keys verified) |
| Meta budget | run $25 (`META_BUDGET_USD`, default ledger); staging $10 total and $0.50 per job (`~/.simon/meta_spend_staging.jsonl`) | operator ruling 2026-10-28 |
| Parity rule | same id count, per-id coverage within 1 percentage point, label-free | operator ruling 2026-10-28 |
| SAM 2.1 model | `facebook/sam2.1-hiera-large` | ungated, Apache-2.0 |
| Detector | rtmlib YOLOX (same as the CPU backend) | one detector dependency |
| Re-prompt | every 2 s; new track when IoU < 0.3 to all live tracks | catches entrants (dance fixture: id 4 enters about frame 26) |
| Key dir | `PART2_KEY_DIR`, default `<key dir>/` | one key directory for every tool |
| ByteTrack thresholds | start at high 0.6, low 0.1, match 0.8, buffer 30; final values recorded at TICKET-017 | starting point only; not tuned on the scored labels |

## Negative Requirements
- MUST NOT print, log or write a key. Why: a secret is never read into a log or printed.
- MUST NOT fall back from a tracker named explicitly, nor fall back without provenance (and, on staging, the job
  result) naming it. Why: the result would misname its tracker.
- MUST NOT choose the bulk tracker by a score on `gt_tracks.json`. Why: gold isolation (ADR-0004).
- MUST NOT change the `tracks.json` shape. Why: Part 2's evals and every consumer read it.

## Compromises
### SAM 3.1 through a paid API for scored outputs
Short-term: `api-sam31` scores within a $25 run budget. Long-term: `local-sam31` for bulk work once parity passes
and the cu128 port holds. Trigger to revisit: the TICKET-038 parity result.

## Non-Requirements
- No new segmentation model training; no tracker ensemble.

## Assumptions
- ASM-004: SAM 2.1 plus the detector tracks the class fixture to coverage at least 95% and at most 1 swap per minute
  (now the fallback; reported, never gated).
- ASM-009: GPU memory free is at least 12 GiB most of the time.

## Implied Requirements Discovered
- A presence check that does not read the value (staging shows which trackers are available).
- Provenance in `tracks.json`, so check-2 can name the tracker without a side file.

## Dissent Review
Reviewed by: setup lane (architect archetype, model: opus). Date: 2026-10-28
### Concern 1: a reader confuses which tracker produced the scored result
Challenge: three trackers can produce `tracks.json`. Impact: a reviewer credits the wrong model. Mitigation: the
scored class result is `api-sam31` (operator ruling 2026-10-28) and check-2 names the tracker in each block.
Resolution: ADDRESSED_IN_SPEC.
### Concern 2: SAM 2.1 drifts on all-fours poses
Challenge: cat-cow poses are low and overlapping. Impact: coverage under 95%. Mitigation: ByteTrack as the second
option, AC-R06. Resolution: ACCEPTED_RISK.
### Concern 3: the HF token could reach a log through a library
Challenge: `huggingface_hub` may log request headers at debug level. Impact: leak. Mitigation: the adapter sets the
library loggers to WARNING and AC-R03 captures all output. Resolution: ADDRESSED_IN_SPEC.
### Pre-Mortem
1. SAM 2.1 video predictor memory on 89 full-HD frames exceeds free GPU memory. Likelihood: M, Impact: M,
   Mitigation: frames are 1280x720; offload frames to CPU (predictor option).
2. A key file holds a trailing newline and is rejected. Likelihood: M, Impact: L, Mitigation: strip whitespace on read.
3. ByteTrack swaps ids on crossings. Likelihood: M, Impact: M, Mitigation: it is the second option, not the default.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|---|---|---|---|
| Decision 1 registry | AC-R01 | `tests/test_trackers.py` | pending |
| Decision 1 fail closed, keys never printed | AC-R02, AC-R03 | `tests/test_keys.py` | pending |
| Decision 1 provenance | AC-R05 | `tests/test_trackers.py` | pending |
| README multi-person DoD | AC-R06 | `make check-2` | pending |
| Operator rulings 2026-10-28 (order, budget) | AC-R08, AC-R09 | `tests/test_trackers.py` | pending |
| Operator ruling 2026-10-28 (parity) | AC-R10 | `tests/test_tracker_parity.py` | pending |

## Delivery Verification Plan
`make test` exit 0; `make outputs` with the `scored` order and `make check-2`, the multi_person block naming
`api-sam31` and the `multi_person_local_open` block beside it, exit codes and the Meta ledger total in STATUS.md
(TICKET-018); the parity record (TICKET-038).
