# Spec: Part 2, images to 3D (video or photo in, `pose3d.json` and `tracks.json` out)

> Copy of `docs/specs/part2-images-to-3d.md` from the maintainers' working repo at `1c8cb7e`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Scope source: this repo's `README.md` (Part 2 of moalborati/simon `docs/MINI-APPS.md`)
and the hub registry `engagements/simon-part-2.yaml` (milestones S0, M1 to M5, six use cases).
Request Type: new-feature (takeover of an in-flight part)
Risk Level: medium
Tickets: TICKET-001 to TICKET-035 (this spec is the master index; detail specs below own their ACs).
ADRs: ADR-0001 (workspace and publish), ADR-0002 (backends and profiles), ADR-0003 (tracker registry),
ADR-0004 (one-person ladder, gold read-only), ADR-0005 (licences), ADR-0006 (reproducible outputs and
stamps), ADR-0007 (takeover and upstream etiquette).
Detail specs: `integration-contract.md`, `backends-gpu-cpu.md`, `tracker-registry.md`, `check-2.md`,
`staging.md`, `neighbour-check.md`, `stock-takes.md`, `simon-publish.md`, `oneshot-watch.md`.

## Overview
Part 2 turns video frames (or one photo) into 3D: one `pose3d.json` per run with every tracked person
(17 canonical joints, hip-centred, y up, metres) and, in multi-person mode, a `tracks.json` with a
stable id, box, mask and confidence per person per frame. The team built the pipeline on the HPC cluster and
a k3s pod (SAM 3D Body for 3D, SAM 3.1 through the paid Meta API for tracking). This takeover keeps
that path working and adds: a published contract with `contract` and `doctor` commands (M1), a local
GPU backend on the RTX 5090 and a CPU backend behind a backend registry, a tracker registry with
SAM 3.1 first and an open local fallback (M2), `make check-2` green on committed, reproducible outputs (M3), a staging app that
runs the real pipeline on uploads (S0, M4), and real stock takes for Part 5 (right after M2).

## Why This Is Wrong (Dissent-First)
- The one-person bar was measured on one seated side-view clip with 20 clicked frames, which says
  little about a standing trainer filmed from the front (ASM-011). The operator ruled on #337 that camera
  angle must not matter: no new filming; a second scored set of human-annotated COCO val2017 keypoints at
  any angle is added (TICKET-037), and the gate needs every set green.
- A paid tracker first in the scored order spends money on every scored run. It is the tracker the team
  scored (coverage 1.0, 0 swaps); spend is capped ($25 for the run, $10 on staging with $0.50 per job) and
  the open `local-open` fallback is measured beside it, never gated (ADR-0003).
- A 2D-guided refinement can lower reprojection error while making the 3D worse, because
  `eval_reproj` sees only 2D. The CPU 3D bar (mean distance to the GPU reference, bone CV) is reported
  beside it so a 2D win that bends the body shows up (check-2.md).
- Torch 2.7 or newer on sm_120 with no nvcc may not build detectron2 (ASM-003); the fallback changes
  the person detector and therefore the boxes SAM 3D Body sees.

## User Story
As a trainer, follower or teammate building Parts 3 to 7, I want to give Part 2 a phone video or a
photo and get `pose3d.json` (and `tracks.json` for a class) that my part reads unchanged, so that the
movement can be normalised, animated, compared and catalogued.

### Jobs-to-be-Done
- Functional: 3D joints per person per frame with stable ids, in a documented, versioned shape.
- Emotional: trust that the numbers come from the code on main, on this host, today (stamps).
- Social: teammates can rerun every step without a GPU pod or a paid key.

## Inputs
| Input | Shape | Source |
|---|---|---|
| Video | `.mp4`, `.mov`, `.webm`; resampled with `--fps` (default: native rate for the CLI, 10 fps on staging) | CLI `--input`, staging upload |
| Image directory | numbered images; `--fps` stamps `t_ms` | CLI `--input` |
| Photo | one `.jpg`, `.jpeg` or `.png`; one frame, `t_ms` 0 | CLI `--input` (a file with an image suffix), staging upload |
| One-person fixture | `fixtures/input/single/{frames/, labels_2d.json}`: Pexels 6019962, seated side view, 111 frames at 5 fps, 20 labelled frames | committed |
| Class fixture | `fixtures/input/class/{frames/, gt_tracks.json}`: Pexels 8480627, 7 people, 89 frames at 5 fps | committed |

## Outputs
| File | Shape (full rules in `integration-contract.md`) | Mode |
|---|---|---|
| `frames/frames.json` | `[{frame, t_ms, file}]` | both |
| `pose3d.json` | `{frames: [{frame, t_ms, people: [{id, joints: {<17>: {x, y, z, conf}}}]}], mirrored?, t0_pts_ms?, provenance?}` | both |
| `pose3d_person_<id>.json` | same shape, one person | multi |
| `camera.json` | per-frame `R`, `t`, `K` sidecar to project joints back onto the frames | both |
| `tracks.json` | `{frames: [{frame, people: [{id, bbox, mask_rle, confidence}]}], provenance?}` | multi |
| `stamp.json` | `part2.stamp/2` (ADR-0006, `check-2.md`) | `make outputs` only |

## Backends and trackers (summary; detail in `backends-gpu-cpu.md` and `tracker-registry.md`)
| Registry | Name | What runs | Needs |
|---|---|---|---|
| backend | `gpu` (default when CUDA is available) | SAM 3D Body (DINOv3) + MoGe-2 FOV, person boxes from ViTDet or the tracker's detector | GPU profile `envs/gpu-cu128/` on this host, or the team profile on HPC or k3s |
| backend | `cpu` | rtmlib RTMPose-x 2D (ONNX Runtime CPU) then a lifter | `envs/cpu/` |
| lifter (cpu only) | `fixed-bones` (B) | constant per-person bone lengths fitted over the clip, per-frame depth solved | nothing extra |
| lifter (cpu only) | `motionbert` (C) | MotionBERT temporal lifter on the RTMPose 2D sequence | its weights (ASM-012) |
| tracker | `api-sam31` (first in the scored order) | the team's `part2/track.py` through the Meta API | key file `MODEL_API_KEY` (verified 2026-10-28) and budget |
| tracker | `local-sam31` (first in the bulk order once parity passes) | gated `facebook/sam3.1` weights on the local GPU | key file `HF_TOKEN` (verified 2026-10-28), cu128 profile |
| tracker | `local-open` (fallback, last in every order) | SAM 2.1 hiera-large video predictor prompted by detector boxes | ungated weights |
| tracker | `bytetrack` | detector boxes plus ByteTrack association, box masks | nothing extra |

Selection: flag, then environment (`PART2_BACKEND`, `PART2_TRACKER`, `PART2_LIFTER`), then the default (for
trackers, the order in `tracker-registry.md`: scored `api-sam31`, `local-open`; bulk `local-sam31` after parity,
`api-sam31` within its cap, `local-open`).
Every output records what ran in the optional `provenance` block.

## Command line
```
part2 frames --input <video|dir|photo> --out <dir> [--fps N]
part2 run --mode single|multi --input <video|dir|photo> --out <dir> [--fps N]
          [--backend gpu|cpu] [--tracker api-sam31|local-sam31|local-open|bytetrack]
          [--lifter fixed-bones|motionbert] [--mirrored] [--smooth]
          [--refine RUNGS]           # single only; focal,kp2d-fit is what the scored outputs use
part2 check                                  # make check-2: metrics JSON, exit 0 only if the DoD passes
part2 eval-reproj --pose3d P --camera C --labels L [--rule every_frame|mean] [--per-frame]
part2 annotate joints|ids --frames D --out F [...]          # unchanged (team tool)
part2 demo viewer|overlay --run D [...]                     # unchanged (team tool)
part2 outputs [--backend gpu|cpu] [--tracker NAME] [--mode single|class|all]   # make outputs
part2 stock [--clip pexels-<id>]                            # make stock-outputs
python -m part2 contract [--json] [--schema <name>]
python -m part2 doctor <file> [--for part3|part5|part6]
```
Make targets: `setup`, `setup-gpu`, `setup-cpu`, `test`, `run-single`, `run-multi`, `check-2`,
`check-2-cpu`, `check-2-contract`, `contract-sync`, `contract-check`, `outputs`, `stock-outputs`, and
the team's `gpu-*` and `hpc-*` targets unchanged.

## Files (source and tests this spec covers; the master index)
A new file under `part2/` or `web/` must be named here (or in a detail spec) before it is written.
| File | Role | Ticket | Detail spec |
|---|---|---|---|
| `part2/__main__.py` | `python -m part2` entry, dispatches to `cli.main` | TICKET-006 | integration-contract |
| `part2/contract.py` | from PR #47, extended: schemas, compatibility table, `contract` command, sync | TICKET-006 | integration-contract |
| `part2/doctor.py` | `doctor <file> --for ...` | TICKET-007 | integration-contract |
| `part2/provenance.py` | builds and validates the optional `provenance` block | TICKET-008 | integration-contract |
| `part2/backends/__init__.py` | backend registry, selection order | TICKET-012 | backends-gpu-cpu |
| `part2/backends/gpu_sam3db.py` | SAM 3D Body backend (wraps `body3d.py`) | TICKET-012 | backends-gpu-cpu |
| `part2/backends/cpu_rtm.py` | RTMPose-x 2D plus person detector on CPU | TICKET-013 | backends-gpu-cpu |
| `part2/lifters/__init__.py` | lifter registry | TICKET-014 | backends-gpu-cpu |
| `part2/lifters/fixed_bones.py` | lifter B | TICKET-014 | backends-gpu-cpu |
| `part2/lifters/motionbert.py` | lifter C, H36M-17 to COCO-17 mapping | TICKET-015 | backends-gpu-cpu |
| `part2/eval_3d.py` | 3D bar: mean distance to the GPU reference, bone CV | TICKET-016 | check-2 |
| `part2/trackers/__init__.py` | tracker registry, selection order | TICKET-017 | tracker-registry |
| `part2/keys.py` | reads operator key files (`MODEL_API_KEY`, `HF_TOKEN`), never prints them | TICKET-017 | tracker-registry |
| `part2/trackers/local_open.py` | SAM 2.1 plus detector prompts | TICKET-017 | tracker-registry |
| `part2/trackers/bytetrack.py` | ByteTrack association | TICKET-017 | tracker-registry |
| `part2/trackers/api_sam31.py` | adapter over `part2/track.py` | TICKET-017 | tracker-registry |
| `part2/trackers/local_sam31.py` | gated SAM 3.1 weights | TICKET-017 | tracker-registry |
| `part2/stamp.py` | stamp v2 write, read, freshness | TICKET-018 | check-2 |
| `part2/outputs.py` | `part2 outputs` / `make outputs` driver | TICKET-018 | check-2 |
| `part2/refine/__init__.py` | ladder rung registry | TICKET-020 | check-2 |
| `part2/refine/kp2d_fit.py` | rung 1: fit to RTMPose 2D keeping bone lengths and depth prior | TICKET-020 | check-2 |
| `part2/refine/temporal.py` | rung 2: temporal smoothing | TICKET-021 | check-2 |
| `part2/refine/focal.py` | rung 3: focal and FOV fit | TICKET-021 | check-2 |
| `part2/refine/ensemble.py` | rung 4: ensemble, per-frame label-free rule (not built, rung 4 not needed) | TICKET-021 | check-2 |
| `part2/hashing.py` | shared sha256 of a file | TICKET-030 | check-2 |
| `tests/test_gold_isolation.py` | refine and trackers never import the evals or name a label file | TICKET-020 | check-2 |
| `tests/test_imports.py` | AC-NFR-001: every module under `part2/` imports without torch, sam2, sam3, rtmlib or onnxruntime | TICKET-030 | |
| `envs/gpu-cu128/check_weights.py`, `tests/test_check_weights.py` | mirrored weights against `k8s/infer_one.py` `OFFICIAL_SHA256` | TICKET-011 | backends-gpu-cpu |
| `part2/stock.py` | stock take download, convert, SOURCE.md (author, sha256, time range, part2_commit) | TICKET-028 | stock-takes |
| `part2/server.py` | stdlib HTTP app (browse, contract, run) | TICKET-003 | run-app |
| `part2/runapi.py` | upload, job and download endpoints | TICKET-024 | run-app |
| `part2/jobs.py` | one-worker job queue, timeout, cancel | TICKET-023 | run-app |
| `part2/gpu_guard.py` | free GPU memory check through `nvidia-smi` | TICKET-023 | run-app |
| `web/index.html`, `web/browse.js` | browse committed outputs | TICKET-003 | run-app |
| `web/contract.html` | contract page | TICKET-003 | run-app |
| `web/viewer.js` | canvas 3D renderer extracted from the `part2/demo.py` viewer | TICKET-003 | run-app |
| `web/run.html`, `web/run.js`, `web/overlay.js` | run page, class overlay | TICKET-025 | run-app |
| `web/style.css`, `web/icon.svg` | shared style and icon | TICKET-003 | run-app |
| `contracts/{pose3d,tracks,camera,frames}.schema.json`, `contracts/compatibility.json`, `contracts/consumers/part3-pose3d.schema.json` (+ `.source.json`), `CONTRACT.md` | contract (data) | TICKET-006 | integration-contract |
| `envs/gpu-cu128/{requirements.txt,constraints.txt,setup.sh}`, `envs/cpu/requirements.txt` | dependency profiles | TICKET-011, 013 | backends-gpu-cpu |
| `fixtures/output/scored/<mode>/`, `fixtures/output/stock/pexels-<id>/` | committed outputs (data) | TICKET-018, 028 | check-2, stock-takes |
| modified: `part2/cli.py`, `check.py`, `schema.py`, `canonical.py`, `body3d.py`, `track.py`, `multi3d.py`, `demo.py`, `annotate.html` (page title only), `frames.py` (docstring only), `Makefile`, `README.md`, `pyproject.toml`, `uv.lock`, `.gitignore`, `fixtures/output/README.md`, `demos/README.md` | | per ticket | |
| `tests/test_<module>.py` for each module above, `tests/conftest.py` | part tests, published | per ticket | |
| firm only: `scripts/dev.sh`, `scripts/neighbour-check.sh`, `scripts/neighbour_check.py`, `scripts/oneshot-launch.sh`, `scripts/oneshot-watch.sh`, `staging/*`, `qa/recipes/*`, `package.json`, `package-lock.json`, `tests/staging/test_staging_scripts.py`, `tests/publish/test-simon-publish.sh`, `tests/test-oneshot-watch.sh` | never published | per ticket | staging, neighbour-check, simon-publish, oneshot-watch |

## Acceptance Criteria
### AC-001: Existing behaviour kept
Given the team's targets (`make test`, `make run-single`, `make run-multi`, `gpu-*`, `hpc-*`)
When this run's changes are merged
Then `make test` passes, the k8s and hpc files are unchanged except for documented additions, and
`part2 run` without `--backend` or `--tracker` on a host with the team profile behaves as before
except that it records `provenance`.

### AC-002: Backend and tracker selection
Given `--backend`, `PART2_BACKEND` and no option
When `part2 run` starts
Then the flag wins over the environment, the environment over the default; an unknown name exits 2
naming the valid names; the chosen names appear in `provenance` (test per order).

### AC-003: Photo input
Given one `.jpg` or `.png`
When `part2 run --mode single --input photo.jpg --out D`
Then `D/frames/frames.json` has one record with `t_ms` 0 and `D/pose3d.json` has one frame with one
person (test with a committed fixture frame).

### AC-004: `--mirrored`
`part2 run --mirrored` writes top-level `"mirrored": true`; without it the key is absent.

### AC-005: Outputs validate
Every `pose3d.json` and `tracks.json` the pipeline writes, for every backend and tracker, validates
against `contracts/` and Part 2's validators (contract tests over `fixtures/output/**`).

### AC-006: Done-check
`make check-2` prints one metrics JSON and exits 0 only when the README DoD passes (`check-2.md`).

### AC-007: Contract commands
`python -m part2 contract` and `python -m part2 doctor` behave as in `integration-contract.md`.

### AC-008: Staging
the maintainers' staging verify exits 0 for S0 and again for M4 (`staging.md`).

### AC-009: Stock takes
`make stock-outputs` produces `fixtures/output/stock/pexels-<id>/` for the three clips (`stock-takes.md`).

### AC-010: Publish
Upstream receives only allowlisted paths through `scripts/simon-publish.sh` (`simon-publish.md`).

### Rule-Based ACs
- AC-NFR-001: no file under `part2/` imports torch at module import time; `make test` runs without
  torch. Verification: test (import every module in a torch-free venv).
- AC-NFR-002: no key, token or login is printed, logged or written to an output. Verification: test
  (tracker adapters with a fake key file; grep of outputs and logs).
- AC-NFR-003: no model weight, upload or downloaded video is committed. Verification: inspection of
  `git ls-files` sizes and suffixes at TICKET-030.

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| Unknown backend, tracker or lifter | exit 2 | `part2: unknown backend 'x'; choose gpu or cpu` | AC-002 |
| `gpu` chosen, no CUDA or no GPU profile | exit 1 | `part2: backend gpu needs CUDA and the GPU profile (make setup-gpu); use --backend cpu` | AC-002 |
| Tracker key missing | exit 1 | `part2: tracker api-sam31 needs the key file MODEL_API_KEY (or the MODEL_API_KEY variable); use --tracker local-open` | AC-002 |
| Unreadable video or photo | exit 1 | `part2: cannot decode <file>` | AC-003 |
| No person found in any frame | exit 1, nothing written | `part2: no person found in <n> frames` | AC-005 |
| Output would break the contract | exit 1, file not written | `part2: output breaks the contract at <path>: <rule>` | AC-005 |

## Edge Cases
- A frame with nobody: `people: []` in both files (AC-005).
- A person who leaves and returns: same id when the tracker keeps it; a new id otherwise, counted as
  a swap by `eval_tracks` (tracker-registry.md).
- Vertical video (the single fixture is 720x1280): handled; `K` uses the real image size.
- A 1-frame video: same as a photo (AC-003).

## Locked defaults (2026-10-28; final, nothing here is asked)
| Item | Decision | Why |
|---|---|---|
| Default backend | `gpu` when CUDA and the GPU profile import, else exit 1 naming `--backend cpu` | No silent quality drop. |
| Tracker order | scored and reference: `api-sam31`, then `local-open`; staging and bulk: `local-sam31` once parity passes, else `api-sam31` within its cap, else `local-open`; output records which ran | Operator rulings 2026-10-28 (#335 answered: both keys verified). |
| Meta spend | run $25 (`META_BUDGET_USD`, default ledger), recorded in STATUS each milestone; staging ledger `~/.simon/meta_spend_staging.jsonl`, $10 total, $0.50 per job, then the next tracker with a note in the job result | Operator ruling 2026-10-28. |
| One-person scored sets | seated clip (20 frames, unchanged) and COCO val2017 human-annotated keypoints (20 or more images, any angle); the gate needs every set green | Operator ruling on #337 (2026-10-28). |
| Research-only training data | RTMPose and MotionBERT accepted with the caveat | Operator ruling on #336 (2026-10-28), ADR-0005. |
| Default lifter | set by the TICKET-016 measurement and written into `backends-gpu-cpu.md` | Decision 2: measured, not guessed. |
| CLI fps | native rate unless `--fps`; staging 10 fps | Keeps the team CLI behaviour. |
| `t_ms` | milliseconds from the first decoded frame (`pts[k] - pts[0]`), plus optional `t0_pts_ms` | Keeps `frames.py`; posted on #18. |
| `mirrored` | optional boolean, written only with `--mirrored` | Part 3 ADR-0005 reads absent as not mirrored. |
| NaN and infinity | rejected everywhere | Closes the hole Muse found on #47. |
| `provenance` | optional, additive, never required by a reader | Backward compatible. |
| Contract versions | `part2.pose3d/2026-10-28`, `part2.tracks/2026-10-28`, `part2.camera/2026-10-28`, `part2.frames/2026-10-28` | Additive fields keep the version. |
| Ports | dev 8722 (`scripts/dev.sh`), staging 7122 under `/simon-part-2/` | Registry. |
| GPU lock | the staging job worker and `make outputs` share `~/.local/state/simon-part-2/gpu.lock`; one GPU inference at a time on this host | `run-app.md`, shared GPU (ASM-009). |
| Weights and sources | under `~/.cache` and `~/.local/state/simon-part-2/`, never in the tree | Registry dormancy notes. |
| Tests | `uv run pytest -q` over `tests/`; GPU tests skip without CUDA and say so | Clean clones run them. |
| Gold set | test set only: rung and tracker parameters fixed from label-free objectives, committed, scored once, every scoring counted in `progress/ladder.md`; `part2/refine/**` and `part2/trackers/**` never import the evals or read labels (`tests/test_gold_isolation.py`) | ADR-0004, setup review B2. |
| Reference reproduction | HPC 5.29% reproduced on the local `gpu` (cu128) backend; if that port fails, recorded as not reproduced on this host and the ladder runs on `cpu` | ADR-0002 (Baseten rejected), ADR-0004. |
| Staging backends and trackers | local `gpu`, then `cpu`; trackers in the bulk order (`local-sam31` after parity, `api-sam31` within the staging cap, `local-open`), plus `bytetrack` | No hosted backend; visitor spend capped by the operator (2026-10-28). |
| Operator keys | files named after their variable in the operator key directory (`MODEL_API_KEY`, `HF_TOKEN`), 700/600, read by `part2/keys.py` at use only; env variable of the same name is a test channel | One convention. |
| Stock takes | milestone M2, published right after commit, then the IECB message names the upstream commit | Part 5 needs them early (setup review B6). |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT change the one-person threshold, the labels, the body-height rule or the every-frame rule.
  Why: ADR-0004, gold read-only.
- MUST NOT break the team's torch 2.5.1 profile, `k8s/` or `hpc/` targets. Why: teammates use them.
- MUST NOT import or copy another part's code. Why: README black-box rule.
- MUST NOT remove or rename a field of a published shape. Why: Parts 3 to 7 read them unchanged.

## Compromises
### Two one-person sets, no new filming
Short-term: the seated clip plus COCO val2017 human-annotated images (operator ruling on #337). Long-term:
more open human-annotated sets. Trigger to revisit: a teammate supplies clicked labels on another clip.
### Paid API for scored tracking
Short-term: `api-sam31` within a $25 run budget. Long-term: `local-sam31` for bulk work after parity.
Trigger: the TICKET-038 parity result.

## Non-Requirements (Explicitly NOT Building)
- The Meta API VLM 2D route of #46 (parked by the team, 2026-10-28).
- Any Part 3 to 7 feature; Part 2 only checks its outputs against them (neighbour check).

## Assumptions
ASM-001 to ASM-012 (`docs/assumptions/`): uv on PATH, cu128 torch on sm_120, detectron2 or detector
boxes, open tracker quality, RTMPose CPU speed, mirror weights identical, Pexels downloads, teammates
pushing, GPU memory, Part 3 rows stable, seated fixture representative, MotionBERT weights public.

## Implied Requirements Discovered
- A photo needs a `t_ms`: 0 (from the staging use case uc-photo-to-3d).
- Every output must name its backend and tracker, or a visitor cannot tell a CPU result from a GPU one
  (registry use cases name "the backend and tracker recorded").
- The stamp must survive a profile change in another mode (decision 4), so it is per mode.

## Delivery Verification Plan (MANDATORY)
### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|---|---|---|---|
| Linux host, RTX 5090 | `make test`, `make check-2`, `make check-2-contract`, `make outputs` | n/a | run session |
| Chromium | Playwright 1.61.1 via `scripts/with-browser-slot.sh` | 1280x720 and 390x844 | staging verify, QA recipe drivers |
### Data
Committed fixtures only (single, class, dance, scored, stock); staging uploads are synthetic visitor
actions with committed fixture clips rebuilt into a short video by ffmpeg at verify time.
### Ratchet Initialization Plan
- When: end of S0. Script: `scripts/ratchet-update.sh`. Verified by: the S0 close-out.

## Dissent Review (MANDATORY)
Reviewed by: setup lane (architect archetype, model: opus)
Date: 2026-10-28
### Concern 1: a refined model that only fits the 20 labels
Challenge: rung 1 fits RTMPose 2D on every frame, not the labels, but RTMPose shares the hip
convention the labels inherited (Muse, #18). Impact if right: green check, worse 3D. Mitigation: the
3D bar against the unrefined GPU output is reported for every rung (check-2.md). Resolution:
ADDRESSED_IN_SPEC.
### Concern 2: the open tracker fails the class clip
Challenge: SAM 2.1 drift on seven people on all fours. Impact: multi-person red. Mitigation: ByteTrack
as the second open option; the result is reported honestly. Resolution: ACCEPTED_RISK.
### Concern 3: one host is a single point of failure
Challenge: the scored outputs are reproducible only on an sm_120 GPU. Impact: teammates cannot
regenerate them. Mitigation: committed outputs plus stamps; the team profile still runs on HPC.
Resolution: ACCEPTED_RISK.
### Pre-Mortem
1. detectron2 never builds and detector boxes shift SAM 3D Body's crops. Likelihood M, Impact M,
   Mitigation: boxes recorded in provenance; the baseline (TICKET-019) is measured with them.
2. GPU memory taken by other host work stalls staging jobs. Likelihood M, Impact M, Mitigation: the
   12 GiB guard queues the job and says so.
3. A teammate pushes a conflicting change to `check.py`. Likelihood M, Impact M, Mitigation:
   `--pull` before each publish; teammate objection wins (ADR-0007).

## Requirements Traceability
| Requirement Source | Spec AC | Ticket | Status |
|---|---|---|---|
| README Output shapes | AC-005, integration-contract AC-C01..C10 | TICKET-006, 007, 008 | pending |
| README DoD one-person and multi-person | AC-006, check-2 AC-K01..K14 | TICKET-018 to 022, 037 | pending |
| README Demos (photo beside 3D, class with stable colours) | AC-003, AC-008 | TICKET-003, 023 to 027 | pending |
| Registry M1 stitch-ready (Part 3 accepts every output; Part 5 meets the expected outcome per pair) | AC-007, neighbour-check AC-N01..N06 | TICKET-006 to 010, 028 | pending |
| Registry M2 backends | AC-002, backends and tracker specs | TICKET-011 to 018, 038 | pending |
| Registry uc-stock-takes-for-part5 | AC-009, stock-takes AC-T01..T06 | TICKET-028 | pending |
| Upstream protocol | AC-010, simon-publish AC-P1..P11 | TICKET-001, 002, 010, 022, 032 | pending |

## Test Scenarios (maps 1:1 to acceptance criteria)
- AC-001 → `tests/test_cli.py::test_defaults_unchanged`, full `make test`
- AC-002 → `tests/test_backends.py::test_selection_order`, `tests/test_trackers.py::test_selection_order`
- AC-003 → `tests/test_frames.py::test_photo_one_frame`, `tests/test_cli.py::test_run_photo` (GPU-gated)
- AC-004 → `tests/test_cli.py::test_mirrored_flag`
- AC-005 → `tests/test_contract.py`
- AC-006 → `tests/test_check.py`
- AC-007 → `tests/test_contract.py`, `tests/test_doctor.py`
- AC-NFR-001 → `tests/test_imports.py::test_no_torch_at_import`
- AC-NFR-002 → `tests/test_trackers.py::test_key_never_printed`

## Deviations from PRD
| PRD item | Deviation | Reason |
|---|---|---|
| README "Frontier model: SAM 3.1 (multi-person tracking)" | none for scored outputs (SAM 3.1 through the API); bulk work moves to local SAM 3.1 after parity, and SAM 2.1 runs only as the fallback | both keys verified 2026-10-28 (ADR-0003, #335) |
| README "20 hand-clicked frames including side views" | angle is not chased; a second human-annotated set at any angle is scored too | operator ruling on #337 (2026-10-28), ADR-0004 |
