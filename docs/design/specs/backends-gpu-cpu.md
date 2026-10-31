# Spec: Part 2 inference backends (GPU on the local RTX 5090, CPU with a lifter registry)

> Copy of `docs/specs/backends-gpu-cpu.md` from the maintainers' working repo at `e846ede`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Requirements source: locked decision 2 (stakeholder-proxy 2026-10-28), hub registry
`engagements/simon-part-2.yaml` milestone M2, upstream issue #46 (route decided by the team 2026-10-28: a CPU
pose model for the no-HPC backend). Parent spec: `docs/design/specs/part2-images-to-3d.md`.
Request Type: new-feature
Risk Level: medium (new dependency profiles on a new GPU architecture; the done-check outputs depend on them)
Tickets: TICKET-011 (GPU profile cu128), TICKET-012 (backend registry), TICKET-013 (CPU 2D), TICKET-014 (lifter B),
TICKET-015 (lifter C), TICKET-016 (3D bar and default lifter).
ADRs: ADR-0002 (backends and profiles), ADR-0005 (licences), ADR-0006 (reproducible outputs and stamps),
ADR-0007 (takeover and upstream etiquette).

## Overview
`part2 run` gains `--backend gpu|cpu` (environment `PART2_BACKEND`; the flag wins). Both backends write the same
`body3d.json` that `part2/body3d.py` writes today, so `canonical.write`, `multi3d`, the evals and every output
schema stay unchanged. The GPU backend is SAM 3D Body with MoGe-2 field of view, run on the local RTX 5090 from a
separate dependency profile (`envs/gpu-cu128/`, torch 2.7 or newer with CUDA 12.8 wheels, which carry sm_120
kernels). The team's torch 2.5.1/cu124 profile (`k8s/`, `hpc/`) is not touched and keeps working. The CPU backend
is RTMPose-x 2D through rtmlib on ONNX Runtime CPU, followed by a 3D lifter chosen from a registry: B
`fixed-bones` (no extra model) and C `motionbert` (a learned temporal lifter). The default lifter is whichever
better meets the 3D bar adopted from Muse on #46: on the single fixture, mean per-joint distance to the GPU
reference at most 0.10 m and bone-length CV at most 0.05. The bar is reported in `make check-2` as a separate
block and gates only the CPU backend (`make check-2-cpu`); it never enters the README definition of done.

## Why This Is Wrong (Dissent-First)
- A second torch profile doubles the environments to keep alive. The team profile is used only on k8s and HPC,
  which this run cannot reach; leaving it untouched is cheaper than migrating it, and the cu128 profile is the
  only one that runs on sm_120. Both are pinned files, so drift shows in a diff.
- detectron2 has no wheel for torch 2.7/cu128 and this host has no `nvcc`. SAM 3D Body uses it only for the
  ViTDet person detector. If the CPU-op build fails inside 45 minutes, person boxes come from the rtmlib detector
  through the existing `boxes=` argument, and provenance names the detector, so the GPU output differs from
  the cluster's in the box source only.
- `eval_reproj` measures 2D reprojection, so a CPU backend can pass it with a poor 3D shape (prototype A on #46:
  3.97% mean reprojection, 15.7 cm from the GPU reference, bone CV about 15%). The 3D bar exists to catch exactly
  that; a CPU backend that misses it is labelled "3D approximate" everywhere it is shown.
- The GPU reference is itself a model output, not ground truth. The bar measures agreement with SAM 3D Body, which
  is the strongest 3D signal available without motion capture; the spec says so wherever the number appears.

## User Story
As the team, I want Part 2 to run on this host's GPU and on any CPU with the same output files, so that outputs
are reproducible without HPC and the app can run where no GPU exists.

### Jobs-to-be-Done
- Functional: `make outputs` and `part2 run` work on this host with no HPC or k8s access.
- Emotional: trust that a CPU result says how good its 3D is.
- Social: teammates can reproduce the GPU numbers from pinned files.

## Interface

### Command line
```
part2 run --mode single|multi --input <video|dir|photo> --out <dir> [--backend gpu|cpu] [--lifter fixed-bones|motionbert]
          [--tracker ...] [--fps N] [--smooth] [--mirrored]
make setup-gpu      # creates the cu128 venv and installs SAM 3D Body, MoGe-2 and the weights (envs/gpu-cu128/setup.sh)
make setup-cpu      # installs the CPU extras into the uv project venv (envs/cpu/requirements.txt)
make check-2-cpu    # prints the cpu_backend_3d block, exits 0 only when the 3D bar passes
```
Precedence for each choice: flag, then environment (`PART2_BACKEND`, `PART2_LIFTER`), then the default.
Default backend: `gpu` when `torch.cuda.is_available()` in the running interpreter, else `cpu`. Default lifter:
`fixed-bones`, set by TICKET-016 from the measurement in "Locked defaults" below.

### Python API
```python
from part2 import backends, lifters
b = backends.get("gpu")          # or "cpu"; unknown name raises backends.UnknownBackend(name, known)
b.name, b.available()            # available() -> (bool, reason): imports and device checked, nothing loaded
doc = b.estimate(frames_dir, out_path, boxes=None)   # writes and returns body3d.json, same shape as body3d.py
backends.names()                 # ["cpu", "gpu"]
l = lifters.get("fixed-bones")   # or "motionbert"
cam3d = l.lift(kp2d, conf, K, image_size, fps)        # kp2d (n, 17, 2) px; conf (n, 17); returns (n, 17, 3) metres, camera frame
```
`body3d.json` (unchanged shape, `part2/body3d.py` docstring): `{model, camera_frame: "opencv", K, image_size,
frames: [{frame, t_ms, people: [{id, bbox, kp3d_cam, kp2d, reproj_self_px}]}]}`. Both backends add an optional
top-level `provenance` object (below); `model` names the backend's model string (`sam-3d-body-dinov3` or
`rtmpose-x+<lifter>`). TICKET-043: the gpu backend's people also carry `extra_kp3d_cam` and `extra_kp2d`, the six
foot points of MHR70 rows 15 to 20, which become pose3d.json's optional `extra_joints`
(`docs/design/specs/integration-contract.md` "Extra joints"); the cpu backend's people carry none (RTMPose-x gives 17 points).

### GPU backend (`part2/backends/gpu_sam3db.py`)
- Wraps `part2.body3d.estimate`; `body3d.load_estimator` gains a device argument (`cuda` default, never hard-coded
  in two places) and reads `SAM3D_REPO` and `SAM3D_CKPT` as today.
- Profile `envs/gpu-cu128/`: `requirements.txt` (torch, torchvision from the cu128 index, version 2.7 or newer,
  exact pins written at TICKET-011), `constraints.txt`, `setup.sh`. `setup.sh` creates the venv at
  `~/.local/state/simon-part-2/venvs/gpu-cu128` with `uv venv`, installs the pins and `-e .`, clones the SAM 3D
  Body source at a pinned commit into `~/.local/state/simon-part-2/src/sam-3d-body`, installs MoGe-2 with
  `--no-deps` as `k8s/setup_env.sh` does, downloads `jetjodh/sam-3d-body-dinov3` (`model.ckpt`,
  `assets/mhr_model.pt`, `model_config.yaml`) into the Hugging Face cache, checks `model.ckpt` and
  `assets/mhr_model.pt` against the SHA-256 digests of `OFFICIAL_SHA256` in `k8s/infer_one.py` (parsed from
  that file with `ast`, never copied, so the team's values stay the one source) and exits 1 naming the file on
  a mismatch, and prints the `SAM3D_REPO` and `SAM3D_CKPT` values to export. It is idempotent and never writes
  inside the repo tree. The digests go into `provenance.models[].weights_sha256`.
- detectron2: `setup.sh` tries `FORCE_CUDA=0` build of the pinned commit with a 45 minute timeout. On failure it
  records `detector: rtmlib-yolox` in `~/.local/state/simon-part-2/venvs/gpu-cu128/part2-profile.json`, and
  single mode then runs the rtmlib person detector first and passes its boxes to `estimate(boxes=...)`.
- Smoke: `python -m part2.backends gpu --smoke` runs one fixture frame and prints device, CUDA capability, peak
  memory and seconds.

### CPU backend (`part2/backends/cpu_rtm.py`)
- rtmlib `Body` in `mode="performance"` (RTMPose-x plus its YOLOX person detector), ONNX Runtime
  `CPUExecutionProvider`. Weights download to `~/.cache/rtmlib` on first use. Single mode keeps the detection that
  best overlaps the previous frame's box (`body3d.choose_subject`); with `boxes=` given (multi mode), the detector
  is skipped and RTMPose runs on each given box.
- `K`: focal = image long side in px, principal point at the image centre (prototype A on #46), recorded in
  `body3d.json` `K` and in provenance as `focal_source: "long-side"`.
- 2D in COCO-17 order equals `part2.joints.CANONICAL`; `kp2d` is written as given; `kp3d_cam` comes from the lifter,
  translated so its reprojection matches `kp2d` in the least-squares sense (root depth solved by a 1D search over
  1 to 20 m); `reproj_self_px` as in `body3d.py`.

### Lifter B, `fixed-bones` (`part2/lifters/fixed_bones.py`)
Input: per person, `kp2d (n, 17, 2)`, `conf (n, 17)`, `K`. Output `(n, 17, 3)` camera frame.
1. Normalised rays: `r[t, j] = K^-1 [u, v, 1]`.
2. Initial depth per frame from scale: `Z[t] = f * H_ref / h2d[t]`, where `h2d[t]` is the 2D distance from the nose to
   the ankle midpoint and `H_ref = 1.60 m` (seated or standing does not matter: only ratios are used in step 3).
3. Bone lengths over the clip: for each of the 12 non-face bones of `part2.joints.BONES`, per frame take the 2D
   length times `Z[t] / f` as a lower bound on the 3D length; the bone length `L_b` is the 90th percentile of those
   lower bounds over frames where both ends have `conf >= 0.5` (a bone seen near-parallel to the image is at full
   length in the frames where it is longest). Left and right pairs are set to their mean. Face bones keep their
   per-frame 2D length at depth `Z[t]`.
4. Per frame, walk the tree from the hip midpoint (depth `Z[t]`) outwards: for a bone from a placed joint `P` to a
   child on ray `r`, solve `norm(s*r - P) = L_b` for `s` (a quadratic). Two roots mean the child is nearer or farther
   than `P`; no real root means the 2D is longer than `L_b` allows, so take the closest point on the ray (`s` at
   the vertex) and count it in `clipped`.
5. Depth signs: choose each limb's root (near or far) to minimise `E = sum over limbs of (sign change versus the
   previous frame) + w * joint-angle penalty` with `w = 1` and the penalty 1 for an elbow or knee bent backwards
   past 10 degrees. Solved by exhaustive search over the 2^8 limb sign choices per frame (8 limb bones).
6. Temporal: a centred median over 5 frames on each joint's depth only, then step 4 again with the smoothed depth
   as the tie-breaker. Bone lengths stay fixed, so the bone-length CV of the output is 0 for the 12 bones up to
   the clipped frames.
Tests use a synthetic skeleton projected through a known `K` and check recovered depth signs, lengths within 2%
and the clipped count on a forced-long bone.

### Lifter C, `motionbert` (`part2/lifters/motionbert.py`)
- MotionBERT 3D pose model on CPU through torch CPU (the CPU extras pin a CPU torch wheel). Weights source and
  file hash are measured at TICKET-015 and written into this section and `provenance.models`.
- Input: the 2D sequence mapped COCO-17 to H36M-17, normalised to `[-1, 1]` by the image size, in windows of 243
  frames (a shorter clip is padded by repeating the edge frames; windows overlap by half and the middle part of
  each window is kept).
- COCO-17 to H36M-17 input mapping (H36M index: source):

| H36M | joint | from COCO-17 |
|---|---|---|
| 0 | pelvis | mean of left_hip, right_hip |
| 1, 2, 3 | right hip, knee, ankle | right_hip, right_knee, right_ankle |
| 4, 5, 6 | left hip, knee, ankle | left_hip, left_knee, left_ankle |
| 7 | spine | mean of pelvis and thorax |
| 8 | thorax | mean of left_shoulder, right_shoulder |
| 9 | neck/nose | nose |
| 10 | head | mean of left_eye, right_eye, left_ear, right_ear |
| 11, 12, 13 | left shoulder, elbow, wrist | left_shoulder, left_elbow, left_wrist |
| 14, 15, 16 | right shoulder, elbow, wrist | right_shoulder, right_elbow, right_wrist |

- Output H36M-17 back to COCO-17: shoulders, elbows, wrists, hips, knees, ankles one to one; nose from index 9;
  eyes and ears placed from index 10 with the 2D offsets of each eye and ear from the head point at the lifted head
  depth. Root-relative output is scaled so the mean of the 12 bone lengths matches lifter B's fitted mean, then
  placed by the root depth search above.

### 3D bar (`part2/eval_3d.py`, TICKET-016)
`evaluate(cpu_pose3d, gpu_pose3d) -> {pass, mean_m, p95_m, worst_joint, bone_cv_mean, bone_cv_max, frames, lifter}`
on `fixtures/output/scored/cpu-single/pose3d.json` against `fixtures/output/scored/single/pose3d.json`, matched on
`frame`, person id 0, canonical frame (hip-centred). `mean_m`: mean over frames and the 17 joints of the Euclidean
distance. `bone_cv_mean`: mean over the 12 non-face bones of each bone's standard deviation over frames divided by
its mean; `bone_cv_max` also reported. Pass: `mean_m <= 0.10` and `bone_cv_mean <= 0.05`. Printed by `make check-2`
as block `cpu_backend_3d`; the top-level `pass` ignores it. `make check-2-cpu` exits 0 only when it passes, 1 when
it fails, 2 when an input file is missing.

### Provenance (optional top-level object in body3d.json, pose3d.json, tracks.json)
`{backend, tracker, lifter, refine: [], detector, focal_source, models: [{name, source, weights_sha256, licence}],
env_profile, part2_commit, created_utc, licence_notes: [..]}`. `licence_notes` carries the ADR-0005 caveat line
for RTMPose and MotionBERT when either ran. Written by `part2/provenance.py` (named in the master spec).
`part2_commit` is `provenance.part2_commit()` for every writer, the cpu backend and the trackers included: HEAD,
plus `+dirty` when a tracked file differs, `unknown` without git (check-2.md AC-K16, review residual N3).

## Files
| File | Role |
|---|---|
| `part2/backends/__init__.py` | registry: `get`, `names`, `UnknownBackend`, resolution of flag, env and default; `python -m part2.backends <name> --smoke` |
| `part2/backends/gpu_sam3db.py` | GPU backend wrapping `part2/body3d.py` |
| `part2/backends/cpu_rtm.py` | CPU backend: rtmlib detector and RTMPose-x, focal, root depth search |
| `part2/lifters/__init__.py` | lifter registry: `get`, `names`, `UnknownLifter` |
| `part2/lifters/fixed_bones.py` | lifter B |
| `part2/lifters/motionbert.py` | lifter C, joint mapping tables |
| `part2/eval_3d.py` | the 3D bar |
| `part2/body3d.py` (modified) | device argument; no other behaviour change. TICKET-043: the six foot points per person and `moved_feet` (spec `integration-contract.md`) |
| `part2/cli.py` (modified) | `--backend`, `--lifter`; the NO_GPU_ENV message names `make setup-gpu` and `--backend cpu` |
| `part2/check.py` (modified) | adds the `cpu_backend_3d` block (layout in `docs/design/specs/check-2.md`) |
| `envs/gpu-cu128/requirements.txt`, `envs/gpu-cu128/constraints.txt`, `envs/gpu-cu128/setup.sh` | GPU profile (published under `envs/**`) |
| `envs/gpu-cu128/check_weights.py` | reads `OFFICIAL_SHA256` from `k8s/infer_one.py` with `ast` and checks the downloaded files (AC-B12); called by `setup.sh` |
| `tests/test_check_weights.py` | AC-B12 with a copy of `k8s/infer_one.py` and fake files |
| `envs/cpu/requirements.txt` | CPU extras: rtmlib, onnxruntime, CPU torch for lifter C (exact pins at TICKET-013) |
| `Makefile` (modified) | `setup-gpu`, `setup-cpu`, `check-2-cpu` |
| `tests/test_backends.py`, `tests/test_lifter_fixed_bones.py`, `tests/test_lifter_motionbert.py`, `tests/test_eval_3d.py` | tests; heavy models are faked, the real models run in `make outputs` |

## Acceptance Criteria
### AC-B01: registry and precedence
`part2 run --backend cpu` with `PART2_BACKEND=gpu` runs the CPU backend; with no flag the environment wins; with
neither, `gpu` when CUDA is available, else `cpu`. An unknown name exits 2: `part2: unknown backend "x"; choose gpu or cpu`.
Test: `tests/test_backends.py`.
### AC-B02: same output shape
Both backends' `body3d.json` pass the same shape check as `body3d.py` output, and `canonical.write` turns each into
a `pose3d.json` that `schema.validate_pose3d` and `contracts/pose3d.schema.json` accept. Test with fake models.
### AC-B03: GPU backend on this host
After `make setup-gpu`, `python -m part2.backends gpu --smoke` exits 0 on the RTX 5090 (device `cuda`, capability
12.0) and prints peak memory and seconds; `part2 run --mode single --backend gpu` on `fixtures/input/single/frames`
writes 111 frames of output. Verification: demonstration, numbers in TICKET-011.
### AC-B12: mirrored weights match the official checksums
`envs/gpu-cu128/setup.sh` computes the SHA-256 of `model.ckpt` and `assets/mhr_model.pt` and compares them with
`OFFICIAL_SHA256` read from `k8s/infer_one.py`; a mismatch exits 1 with
`setup-gpu: <file> from <repo> does not match the official checksum`. Test: `tests/test_check_weights.py` runs
`envs/gpu-cu128/check_weights.py` on a copy of `k8s/infer_one.py` and one-byte fake files (no download).
### AC-B04: team profile untouched
`k8s/requirements-gpu.txt`, `k8s/constraints-gpu.txt`, `k8s/setup_env.sh` and `hpc/*` are byte-identical to
upstream main after this work; the `gpu-*` and `hpc-*` make targets are unchanged. Verification: `git diff
upstream/main -- k8s hpc` empty.
### AC-B05: GPU unavailable is a plain refusal
`--backend gpu` without CUDA or without the profile exits 1 with `part2: the gpu backend needs CUDA and the
gpu-cu128 profile (make setup-gpu); use --backend cpu`, no traceback.
### AC-B06: CPU backend
`part2 run --mode single --backend cpu` on the single fixture runs with no GPU visible (`CUDA_VISIBLE_DEVICES=`),
writes `pose3d.json` and `camera.json`, and `eval-reproj` on it reports numbers (recorded at TICKET-013).
### AC-B07: lifter B recovers a synthetic skeleton
On a synthetic 60-frame skeleton projected through a known `K` with 2 px noise, `fixed-bones` recovers bone
lengths within 2%, depth signs on at least 95% of limb-frames, and output bone CV under 0.01.
### AC-B08: lifter C mapping round trip
COCO-17 to H36M-17 and back keeps the 12 limb joints exactly and places eyes and ears on the head side of the neck;
windows cover every frame exactly once in the kept middles (tests on clips of 1, 100, 243 and 500 frames).
### AC-B09: 3D bar reported and gated
`make check-2` prints `cpu_backend_3d` with `mean_m`, `p95_m`, `worst_joint`, `bone_cv_mean`, `bone_cv_max`,
`lifter`, `pass`; top-level `pass` does not change with it. `make check-2-cpu` exits 0, 1 or 2 as specified.
Test: `tests/test_eval_3d.py` with hand-built files (identical files: 0 m, CV 0, pass; a 0.2 m offset: fail).
### AC-B10: default lifter by measurement
TICKET-016 runs both lifters on the single fixture, records both blocks in the ticket, sets the default to the one
that passes (both pass: lower `mean_m`; neither: lower `mean_m`, and the CPU backend is labelled "3D approximate"
in the run app and the README) and writes it in Locked defaults.
### AC-B11: provenance
Every output of either backend carries `provenance.backend`, `models[].weights_sha256` and, for the CPU backend,
`lifter` and the ADR-0005 licence note. Files without `provenance` still validate.

### Rule-Based ACs
- AC-B-NFR-01: nothing under the repo tree is written by `setup.sh` or the first model download. Verification: test
  (`git status --porcelain` unchanged after `make setup-gpu`), inspection.
- AC-B-NFR-02: `import part2` and `make test` work without torch, rtmlib or onnxruntime installed. Verification:
  test in the plain uv venv.
- AC-B-NFR-03: one GPU inference at a time on this host (`make outputs`, the run app's job worker and `part2 run`
  use the same lock file `~/.local/state/simon-part-2/gpu.lock`; `part2 run` holds it around each gpu backend
  estimate and the SAM trackers around tracking, never one inside the other). Verification: test
  (`tests/test_cli.py`, `tests/test_jobs.py`).

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| unknown backend or lifter | exit 2 | `part2: unknown backend "<x>"; choose gpu or cpu` | AC-B01 |
| gpu requested, no CUDA or no profile | exit 1 | `part2: the gpu backend needs CUDA and the gpu-cu128 profile (make setup-gpu); use --backend cpu` | AC-B05 |
| cpu extras missing | exit 1 | `part2: the cpu backend needs make setup-cpu` | AC-B06 |
| weights download fails | exit 1 | `part2: could not download <model> weights from <source>` | AC-B03 |
| CUDA out of memory | exit 1, partial outputs removed | `part2: the GPU ran out of memory; free memory or use --backend cpu` | AC-B03 |
| no person found in any frame | exit 1 | `part2: no person found in <n> frames` | AC-B02 |
| GPU lock held | wait up to 10 min, then exit 1 | `part2: another GPU job is running` | AC-B-NFR-03 |

## Edge Cases
- One-frame input (a photo): lifter B uses the single frame for lengths; lifter C pads to 243 (AC-B07, AC-B08).
- A joint with `conf < 0.5` in every frame: its bone length falls back to the left/right partner or the clip mean
  ratio table of the GPU reference fixture; counted in provenance as `fallback_bones`.
- Person partly out of frame: RTMPose still returns 17 points; `conf` rules from the existing writer apply.

## Locked defaults (2026-10-28)
| Item | Decision | Why |
|---|---|---|
| GPU torch | 2.7 or newer, cu128 wheels; exact pins at TICKET-011 | first wheels with sm_120 kernels (ASM-002) |
| GPU venv | `~/.local/state/simon-part-2/venvs/gpu-cu128` | outside the tree, shared by the dev and staging checkouts |
| SAM 3D Body source | `~/.local/state/simon-part-2/src/sam-3d-body` at a pinned commit (`SAM3D_REPO`) | same layout as k8s |
| Weights | `jetjodh/sam-3d-body-dinov3` mirror in the HF cache (`SAM3D_CKPT` = snapshot dir), SHA-256 checked against `k8s/infer_one.py` `OFFICIAL_SHA256` | public, no token (ASM-006); same check as the team's k8s path |
| Reference reproduction | local `gpu` backend; `cpu` as the fallback; no hosted backend | ADR-0002 Option 4 (Baseten rejected: key locked to one chat model) |
| detectron2 | `FORCE_CUDA=0` build, 45 min timebox, else rtmlib YOLOX boxes | no nvcc on this host (ASM-003) |
| CPU 2D | rtmlib `Body`, `performance` mode (RTMPose-x), ONNX Runtime CPU | #46 probe: mean 3.97%, 1 of 20 frames over (ASM-005) |
| CPU focal | image long side, centre principal point | prototype A on #46 |
| Default lifter | `fixed-bones`. Measured 2026-10-29 on `fixtures/input/single` (111 frames) against the local gpu output `fixtures/output/scored/single`: `fixed-bones` mean_m 0.2682, p95_m 0.8112, bone_cv_mean 0.0117, bone_cv_max 0.0571; `motionbert` mean_m 0.2914, p95_m 0.5987, bone_cv_mean 0.1400, bone_cv_max 0.4028. Neither passes, so the lower mean_m wins and the CPU backend is "3D approximate" | AC-B10 (TICKET-016) |
| 3D bar | mean per-joint distance <= 0.10 m and mean bone CV <= 0.05 vs the GPU reference on the single fixture | Muse on #46, adopted unchanged |
| GPU lock | `~/.local/state/simon-part-2/gpu.lock` (flock) | one inference at a time |

## Negative Requirements
- MUST NOT change `k8s/` or `hpc/` files or targets. Why: teammates run them on k8s and HPC.
- MUST NOT fold the 3D bar into the top-level `pass` of `make check-2`. Why: the README definition of done is
  upstream's.
- MUST NOT put weights, venvs or downloaded sources in the tree. Why: size and licences.
- MUST NOT call the CPU backend's 3D accurate when it fails the bar.

## Compromises
### Box source on sm_120
Short-term: rtmlib boxes when detectron2 cannot build. Long-term: a detectron2 wheel for cu128 or the ViTDet
detector ported to plain torch. Trigger to revisit: a detectron2 release with sm_120 support.
### Reference is a model
Short-term: GPU output as the 3D reference. Long-term: a motion-capture labelled clip. Trigger: such a clip arrives.

## Non-Requirements
- No Meta API pose backend (`--backend api` from #46 is parked by the team's decision; Wonder-crop artifacts stay).
- No training or fine-tuning of any model.

## Assumptions
- ASM-001: uv is on PATH through `~/.local/bin`.
- ASM-002: torch 2.7 or newer cu128 wheels run SAM 3D Body on sm_120.
- ASM-003: detectron2 builds without nvcc, or boxes come from the detector.
- ASM-005: rtmlib RTMPose-x ONNX runs on CPU at about 2 s per person-frame.
- ASM-006: the mirror `jetjodh/sam-3d-body-dinov3` holds the same weights as `facebook/sam-3d-body-dinov3`.
- ASM-009: GPU memory free is at least 12 GiB most of the time.
- ASM-012: MotionBERT weights are downloadable without a login.

## Implied Requirements Discovered
- A GPU lock shared by `make outputs` and the run app (two inferences on one card crashed the team's shared GPU on
  2026-10-27, thread #18).
- `import part2` without torch, so `make test` and the CPU path stay light.

## Dissent Review
Reviewed by: setup lane (architect archetype, model: opus). Date: 2026-10-28
### Concern 1: the mirror weights may differ from Meta's
Challenge: a re-upload could be altered. Impact if right: numbers not comparable to HPC. Mitigation: setup checks
the team's official SHA-256 digests (AC-B12); TICKET-019 reproduces the HPC baseline on the single fixture; a
large gap is investigated before the ladder.
Resolution: ADDRESSED_IN_SPEC.
### Concern 2: lifter B's fixed lengths hide real limb foreshortening errors
Challenge: a wrong length makes every frame wrong in the same way. Impact: low CV, high distance. Mitigation: the
bar checks distance and CV together. Resolution: ADDRESSED_IN_SPEC.
### Concern 3: MotionBERT's training data terms
Challenge: Human3.6M terms are research-only. Impact: not usable in an app without sign-off. Mitigation: ADR-0005,
operator ask #336 decided 2026-10-28 (accept with the caveat), caveat in provenance and README. Resolution: ACCEPTED_RISK.
### Pre-Mortem
1. torch cu128 fails on SAM 3D Body. Likelihood: M, Impact: H, Mitigation: CPU backend still produces outputs;
   STATUS records the error; DEGRADED path in the brief.
2. The 5090 is busy with other host work. Likelihood: M, Impact: M, Mitigation: GPU lock, memory check, retries.
3. Neither lifter meets the bar. Likelihood: M, Impact: M, Mitigation: AC-B10 labelling.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|---|---|---|---|
| Decision 2 backend switch | AC-B01, AC-B05 | `tests/test_backends.py` | pending |
| Decision 2 same outputs | AC-B02, AC-B11 | `tests/test_backends.py` | pending |
| Decision 2 primary GPU on the 5090 | AC-B03, AC-B04, AC-B12 | demonstration (TICKET-011), `tests/test_backends.py` | pending |
| Decision 2 CPU plus lifters B and C | AC-B06, AC-B07, AC-B08 | `tests/test_lifter_*.py` | pending |
| Decision 2 3D bar | AC-B09, AC-B10 | `tests/test_eval_3d.py` | pending |

## Delivery Verification Plan
`make test` exit 0; `make setup-gpu` and the smoke exit 0 with numbers in TICKET-011; `make outputs BACKEND=gpu`
and `make outputs BACKEND=cpu` then `make check-2` and `make check-2-cpu`, exit codes in STATUS.md (TICKET-018,
TICKET-016). Staging names the backend on every result (`docs/design/specs/run-app.md`).
