# Spec: Part 2 inference backends (GPU on the local RTX 5090, CPU with a lifter registry)

> Copy of `docs/specs/backends-gpu-cpu.md` from the maintainers' working repo at `f43deee`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Requirements source: locked decision 2 (stakeholder-proxy 2026-10-28), hub registry
`engagements/simon-part-2.yaml` milestone M2, upstream issue #46 (route decided by the team 2026-10-28: a CPU
pose model for the no-HPC backend). Parent spec: `docs/design/specs/part2-images-to-3d.md`.
Request Type: new-feature
Risk Level: medium (new dependency profiles on a new GPU architecture; the done-check outputs depend on them)
Tickets: TICKET-011 (GPU profile cu128), TICKET-012 (backend registry), TICKET-013 (CPU 2D), TICKET-014 (lifter B),
TICKET-015 (lifter C), TICKET-016 (3D bar and default lifter), TICKET-044 (`cpu-sam3db`, `bones-prior`), TICKET-046
(their registry entries and the review residuals R6 to R12), TICKET-047 (`NoPersonFound`, exit 4).
ADRs: ADR-0002 (backends and profiles), ADR-0005 (licences), ADR-0006 (reproducible outputs and stamps),
ADR-0007 (takeover and upstream etiquette).

## Overview
`part2 run` gains `--backend gpu|cpu` (environment `PART2_BACKEND`; the flag wins). Both backends write the same
`body3d.json` that `part2/body3d.py` writes today, so `canonical.write`, `multi3d`, the evals and every output
schema stay unchanged. The GPU backend is SAM 3D Body with MoGe-2 field of view, run on the local RTX 5090 from a
separate dependency profile (`envs/gpu-cu128/`, torch 2.7 or newer with CUDA 12.8 wheels, which carry sm_120
kernels). The team's torch 2.5.1/cu124 profile (`k8s/`, `hpc/`) is not touched and keeps working. The CPU backend
is RTMPose-x 2D through rtmlib on ONNX Runtime CPU, followed by a 3D lifter chosen from a registry: B
`fixed-bones` (no extra model), B2 `bones-prior` (TICKET-044) and C `motionbert` (a learned temporal lifter). The
default lifter is whichever better meets the 3D bar adopted from Muse on #46: on the single fixture, mean per-joint distance to the GPU
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
part2 run --mode single|multi --input <video|dir|photo> --out <dir> [--backend gpu|cpu|cpu-sam3db] [--lifter bones-prior|fixed-bones|motionbert]
          [--tracker ...] [--fps N] [--smooth] [--mirrored]
make setup-gpu      # creates the cu128 venv and installs SAM 3D Body, MoGe-2 and the weights (envs/gpu-cu128/setup.sh)
make setup-cpu      # installs the CPU extras into the uv project venv (envs/cpu/requirements.txt)
make check-2-cpu    # prints the cpu_backend_3d block, exits 0 only when the 3D bar passes
make check-2-cpu CPU_MODE=cpu-sam3db-single   # the same bar on the CPU variant's dir (TICKET-044 B1)
```
Precedence for each choice: flag, then environment (`PART2_BACKEND`, `PART2_LIFTER`), then the default.
Default backend: `gpu` when `torch.cuda.is_available()` in the running interpreter, else `cpu` (`cpu-sam3db` is
chosen by name only). Default lifter: `bones-prior`, set by AC-B10 from the measurements in "Locked defaults" below.
`part2/lifters/__init__.py` says `DEFAULT = "bones-prior"` and registers it, with the three measurements in the comment
beside it; `lifters.resolve()` returns `bones-prior` with no flag and no `PART2_LIFTER`, and an explicit `--lifter` or
`PART2_LIFTER` still wins. (TICKET-044 first set the default at run time from a separate module because the registry
files were hashed into every committed scored stamp; TICKET-046 folded it into the files on 2026-10-31.)

### Python API
```python
from part2 import backends, lifters
b = backends.get("gpu")          # or "cpu", "cpu-sam3db"; unknown name raises backends.UnknownBackend(name, known)
b.name, b.available()            # available() -> (bool, reason): imports and device checked, nothing loaded
doc = b.estimate(frames_dir, out_path, boxes=None)   # writes and returns body3d.json, same shape as body3d.py
                                 # gpu and cpu-sam3db also take mesh=<mesh3d.Collector> for `run --mesh` (mesh3d.md AC-M10)
backends.names()                 # ["cpu", "cpu-sam3db", "gpu"]
l = lifters.get("bones-prior")   # or "fixed-bones", "motionbert"; lifters.names() is sorted
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

### CPU variant `cpu-sam3db` (`part2/backends/cpu_sam3db.py`, TICKET-044 approach B1)
- The gpu backend's model on the CPU device: SAM 3D Body with ViTDet boxes and MoGe-2 focal, the same weights and
  the same `gpu-cu128` profile (its venv carries torch and the SAM 3D Body dependencies), run with `device="cpu"` and
  `CUDA_VISIBLE_DEVICES=` so nothing reaches the GPU; it never takes the host GPU lock. It is selected by name only
  (`--backend cpu-sam3db`, `PART2_BACKEND=cpu-sam3db`): the default backend stays `gpu` or `cpu` by CUDA, the
  unknown-name message lists all three (AC-B01), and the `cpu` route (RTMPose-x through rtmlib with lifter `bones-prior`, `fixed-bones` or
  `motionbert`) stays as decided and selectable. `--backend cpu` stays RTMPose-x, the run app keeps `gpu` and `cpu`,
  and `cpu` stays labelled "3D approximate" (`part2/jobs.py` `CPU_3D_BAR_PASSED` stays False).
- Registration: `part2/backends/__init__.py` holds the entry (`_MODULES["cpu-sam3db"]`, its `REFUSAL` line and the
  name in `CHOICES`, after `gpu` and `cpu`); `cpu_sam3db.REFUSAL` reads that line. `resolve()` and `default()` never
  pick it. No module registers anything at run time and every entry point sees it on import (TICKET-046, 2026-10-31:
  the runtime layer of TICKET-044 was folded into the registry files).
- Two CUDA assumptions in third-party code are redirected inside Part 2 for this backend's own calls; the source under
  `~/.local/state/simon-part-2/src/` is never edited and no torch attribute is replaced:
  1. The pinned SAM 3D Body source moves tensors by hand (`recursive_to(batch, "cuda")` in
     `sam_3d_body_estimator.py`; `recursive_to(..., "cuda")` and `.cuda()` in `models/meta_arch/sam3d_body.py`).
     Each `process_one_image` call runs inside `on_cpu()`, a `torch.overrides.TorchFunctionMode` (thread-local,
     active only for that call) under which `Tensor.cuda` keeps the tensor on the CPU and `Tensor.to` or any
     `device=` argument naming CUDA names the CPU instead. The focal rung's re-runs wrap the same estimator.
  2. MoGe-2's `infer` autocasts to fp16 by default, which fails on the CPU: the backend's own MoGe-2 instance gets an
     `infer` with `use_fp16=False`; the `MoGeModel` class and any other instance keep theirs.
- `available()` checks the profile, torch, the SAM 3D Body source and the two weight files; it needs no CUDA. The
  checks are `gpu_sam3db.Backend.install_problem()`, one function that both backends call: the gpu backend asks it
  for a CUDA device too (`needs_cuda`, checked right after torch), the variant does not, and the refusal texts are
  the same for everything else.
- Output: `body3d.json` of the `body3d.py` shape with the six foot points (`extra_kp3d_cam`, `extra_kp2d`), so
  `pose3d.json` carries `extra_joints` as the gpu backend's does. Provenance: the gpu backend's (`detector`,
  `focal_source: "moge2"`, `models` from the profile, `env_profile`) with `backend: "cpu-sam3db"`, `device: "cpu"`
  and `timing: {load_s, seconds, frames, seconds_per_frame, threads, warm}` of the last estimate; `pose3d.json` gets
  the same keys through `output_steps.pose_extras`. `load_s` is the model load that estimate paid for and `warm` says
  whether the model was already loaded: the call that loads it reports its load seconds and `warm: false` (a batch
  run, or the first request of a worker started without preload); a call on a model loaded earlier (the next requests
  of a warm worker, and every request after the worker's preload) reports `load_s: 0.0` and `warm: true`. A file made
  before `warm` existed has the first five keys only, and `check.cpu_speed` reads it as it always did.
- Speed: the probe of 2026-10-31 at 3cb4699 measured a 23.4 s model load and 46.7 s for one frame on 22 cores. The
  bar run (torch limited to 8 threads on cores 0 to 7) measured 31.74 s per frame plus a 23.7 s model load on 2026-10-31; the 2026-11-01 regeneration, under host load, measured 46.95 s per frame plus a 23.4 s model load. Every
  run records its own seconds per frame in `provenance.timing`; `make check-2-cpu` prints it beside the bar.
- Measurement: `part2.outputs` mode `cpu-sam3db-single` (backend `cpu-sam3db`, `fixtures/input/single/frames`,
  one-person, no refine rung by default as for `cpu-single`; `--refine kp2d-fit` applies) writes
  `<scored>/cpu-sam3db-single/` with a stamp. The bar run is committed as `fixtures/output/scored/cpu-sam3db-single`
  (made 2026-10-31), so its bar reproduces with `make check-2-cpu CPU_MODE=cpu-sam3db-single`; plain
  `make check-2-cpu` keeps scoring `cpu-single`.
  `make check-2-cpu CPU_MODE=cpu-sam3db-single` (environment `PART2_CPU_MODE`; flag `python -m part2.check --block
  cpu_backend_3d --cpu-mode NAME`, which wins) scores that dir of the scored dir against `single` with the same eval,
  stamp checks and exit codes; without it the block scores `cpu-single` exactly as before. The name is a dir of the
  scored dir, never a path.
- Smoke: `CUDA_VISIBLE_DEVICES= ~/.local/state/simon-part-2/venvs/gpu-cu128/bin/python -m part2.backends cpu-sam3db
  --smoke` runs one fixture frame and prints load and per-frame seconds, threads and whether the foot points came out.

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

### Lifter B2, `bones-prior` (`part2/lifters/bones_prior.py`, TICKET-044 approach B2)
Lifter B's lift with a depth-sign and joint-limit prior. numpy only, deterministic, no model. `bones-prior` is in
`lifters._REGISTRY` (`part2/lifters/__init__.py`) like the other two lifters, loaded on first use, and is the default
(AC-B10): `--lifter bones-prior` and `PART2_LIFTER=bones-prior` resolve, and `stamp.entry_modules` names
`part2.lifters.bones_prior`. It calls lifter B's public functions in `fixed_bones.py` (`facing` among them, TICKET-046
R12).

Method:
1. Steps 1 to 4 of lifter B, by its own functions: rays, bone lengths over the clip scaled to a standing chain,
   per-frame root depth, and the tree placement whose ten sign bits (hip line, left torso side, eight limb bones)
   give 1024 candidate poses per frame, every joint on its ray at its bone length.
2. Prior: per frame and candidate, in the trunk frame (x the hip line, u the hip midpoint to shoulder midpoint made
   normal to x, f = x cross u the front), each joint limit below adds the degrees by which the candidate leaves its
   range, weighted by how well that angle is defined (a limb pointing sideways has no sagittal angle; a straight
   limb has no bend direction); the sum is divided by `DEG_UNIT`, and `W_WIDTH` times the relative shoulder width
   error is added (lifter B's term). A term counts only where its joints have `conf >= 0.5`.
3. Temporal: Viterbi over the clip. A bit that flips between frames t-1 and t costs `W_JUMP` times the distance its
   joint jumps (the gap between the bone's two roots over the bone length, mean of both frames), so a bone crossing
   the image plane flips for free and a foreshortened bone flips only when the prior insists. Lifter B's step 6
   (median depth re-pick) is not used. The forward pass runs chunk by chunk (`fixed_bones.CHUNK` frames) as each
   chunk's costs are made, so the jump costs of a finished chunk are dropped: what a clip keeps per frame is the
   unary cost row (1024 float64) and the back pointers (1024 int32), about 12 KB, not those plus the 82 KB of jump
   costs. The arithmetic is unchanged, so the path and the prior cost are bit for bit what the whole-clip pass gave
   (AC-BP09).
4. Output: each face joint on its ray at the shoulder midpoint's depth plus the depth part of `FACE_FWD` along the
   trunk's front (in profile the offset lies in the image and the depth stays the shoulders'), then every joint
   scaled along its ray by `H_CHAIN / 1.60`. Every joint stays on its ray, so reprojection onto `kp2d` is exact as
   in lifter B; the ten tree bones keep their length, and the right torso side and the shoulder width stay lifter
   B's best fit to both.
`lifter_info` carries lifter B's keys (with `H_ref_m` = `H_CHAIN`) plus `sign_flips` and `prior_cost_mean`.

Parameters and where each comes from. Anatomical ranges are the AAOS average ranges of motion (American Academy of
Orthopaedic Surgeons, Joint Motion: Method of Measuring and Recording, 1965; tabulated in Greene and Heckman, The
Clinical Measurement of Joint Motion, AAOS 1994); horizontal abduction from Norkin and White, Measurement of Joint
Motion: A Guide to Goniometry.

| Constant | Value | Source |
|---|---|---|
| `HIP_EXT` | 30 deg | AAOS hip extension 30: the thigh's sagittal angle in the trunk frame stays in [-30, 180] |
| `HIP_ADD` | 30 deg | AAOS hip adduction 30 (abduction is not limited: stretches exceed the 45 deg average) |
| knee, elbow | extension 0 | AAOS knee 0 to 135 and elbow 0 to 150 flexion, extension 0: a backward bend costs its angle times the share of the bend against the neutral direction (the axis is the body's left made normal to the proximal segment); a sideways bend, as a rotated hip gives in cross-legged sitting, costs nothing, and flexion has no upper limit (deep squats and cross-legged knees pass 135) |
| `SH_HEXT` | 45 deg | horizontal abduction 45 (Norkin and White): the upper arm's angle behind the frontal plane is at most `SH_HEXT * (1 - d.u)`, 45 at shoulder height, 0 straight up (AAOS flexion 180), about 67 at 30 deg below horizontal (AAOS extension 60 lies inside) |
| `SPINE_ROT` | 45 deg | AAOS thoracolumbar rotation 45: the shoulder line's twist against the hip line about the trunk axis |
| `fixed_bones.LEAN_BACK_DEG` | 30 deg | lifter B's own posture limit, reused: the trunk leaning back from camera up |
| `FACE_TURN` | 90 deg | lifter B's facing term in degrees: the nose to ears direction never points behind the body's front |
| `W_WIDTH` | 1 | lifter B's value, reused |
| `DEG_UNIT` | 30 deg | tuned on the tuning clips (table below) |
| `W_JUMP` | 3 | tuned on the tuning clips (table below) |
| `H_CHAIN` | 1.50 m | the standing chain (nose to shoulder midpoint, torso, thigh, shin) of the GPU outputs on the tuning clips: median over 15 people 1.5002 m (stock takes 1.447, 1.463, 1.520; class 1.449 to 1.594; dance 1.460 to 1.567) |
| `FACE_FWD` | nose 0.15, eyes 0.13, ears 0.03 m | the same 15 GPU people: median offset in front of the shoulder midpoint along the trunk front, nose 0.154, eyes 0.132 and 0.119, ears 0.038 and 0.027, rounded to the centimetre and made symmetric |

Tuning clips (the bar fixture `fixtures/input/single`, `fixtures/output/scored/single` and `scored/cpu-single` were
never read by any tuning or diagnostic run): the stock takes `pexels-5034562` (side, 154 frames), `pexels-5034577`
(front, 166) and `pexels-8837221` (three-quarter, 256), frames from the stock cache `~/.cache/simon-part-2/stock`,
against their committed GPU `fixtures/output/stock/<take>/pose3d.json`; and the class clip (`fixtures/input/class`,
89 frames, 7 people, 623 person-frames; RTMPose-x on the tracker boxes of `fixtures/output/scored/class/tracks.json`,
never `gt_tracks.json`) against `fixtures/output/scored/class/pose3d.json`. `H_CHAIN` and `FACE_FWD` also use the
GPU `fixtures/output/dance/pose3d.json` (no frames needed). The COCO set was not used. RTMPose-x 2D ran once per clip
(scratch, outside the repo); scoring is `eval_3d.evaluate` per person id, the number is mean_m, and "mean" is the
unweighted mean over the four clips. Selection rule, fixed before the grid: lowest mean, ties within 0.001 m broken
by the lower worst clip.

| Run | Setting | side | front | 3/4 | class | mean |
|---|---|---|---|---|---|---|
| D0 | lifter B `fixed-bones` (baseline) | 0.2165 | 0.1459 | 0.2016 | 0.3239 | 0.2220 |
| D1 | lifter B placement, sign bits chosen per frame by the GPU reference (upper bound for any sign prior) | 0.1156 | 0.1064 | 0.1602 | 0.2275 | 0.1524 |
| T1 | first version: hinge as a signed sagittal angle in [0, 135] knee and [0, 150] elbow, `DEG_UNIT` 30, `W_JUMP` 1, no face offsets, chain 1.60 | 0.1783 | 0.1456 | 0.2470 | | |
| T2 | T1 plus `FACE_FWD` | 0.1844 | 0.1355 | | | |
| T3 | T1 plus `H_CHAIN` 1.50 | 0.1713 | 0.1295 | | | |
| T4 | T1 plus both | 0.1761 | 0.1186 | 0.2361 | 0.2650 | 0.1990 |
| T5 | T4, one term off at a time on 3/4: hip extension, adduction, knee, shoulder behind, face turn, width each 0.2361; elbow off 0.2762; twist off 0.2293 | | | | | |
| T6 | T4, twist off (`SPINE_ROT` 180) | 0.1836 | 0.1186 | 0.2293 | 0.2685 | 0.2000 |
| T7 | T4, every limit off (temporal, width, scale and face only) | 0.1863 | 0.1727 | 0.3029 | 0.2830 | 0.2362 |
| T8 | an eleventh bit, the right shoulder on its own root from the right hip (rejected) | 0.1902 | 0.2116 | 0.2569 | 0.2418 | 0.2251 |
| T9 | T8, twist off | 0.1746 | 0.2116 | 0.2360 | 0.3161 | 0.2346 |
| T10 | T8, `W_WIDTH` 5 (a `W_WIDTH` 15 run was stopped unfinished) | 0.1903 | 0.2122 | 0.2551 | 0.2906 | 0.2370 |
| T11 | current hinge (backward bend only), ten bits, `DEG_UNIT` 30, `W_JUMP` 1 | 0.1761 | 0.1186 | 0.2361 | 0.2846 | 0.2039 |
| T12 | T11, twist off | 0.1836 | 0.1186 | 0.2293 | 0.2898 | 0.2053 |
| G1 | T11 grid: `DEG_UNIT` 10, `W_JUMP` 0.3 | 0.1795 | 0.1207 | 0.2293 | 0.2940 | 0.2059 |
| G2 | `DEG_UNIT` 10, `W_JUMP` 1 | 0.1684 | 0.1179 | 0.2361 | 0.2805 | 0.2007 |
| G3 | `DEG_UNIT` 10, `W_JUMP` 3 | 0.1761 | 0.1186 | 0.2319 | 0.2838 | 0.2026 |
| G4 | `DEG_UNIT` 30, `W_JUMP` 0.3 | 0.1763 | 0.1179 | 0.2294 | 0.2951 | 0.2047 |
| G5 | `DEG_UNIT` 30, `W_JUMP` 3 (chosen; committed code rerun gives the same) | 0.1760 | 0.1174 | 0.2319 | 0.2774 | 0.2007 |
| G6 | `DEG_UNIT` 90, `W_JUMP` 0.3 | 0.1761 | 0.1183 | 0.2293 | 0.2840 | 0.2019 |
| G7 | `DEG_UNIT` 90, `W_JUMP` 1 | 0.1760 | 0.1170 | 0.2302 | 0.2796 | 0.2007 |
| G8 | `DEG_UNIT` 90, `W_JUMP` 3 | 0.1743 | 0.1171 | 0.2319 | 0.2805 | 0.2010 |
| A1 | attribution: lifter B's signs with `FACE_FWD` and `H_CHAIN` only | 0.2083 | 0.1190 | 0.2040 | 0.3103 | 0.2104 |

G2, G5 and G7 tie at 0.2007; G5 has the lowest worst clip (0.2774). Bone CV of G5: 0.0069, 0.0083, 0.0032, 0.0080.
The first `H_CHAIN` count also took `fixtures/output/single` (the squat, lifter B's `RATIO` source; 16 people, median
1.5017 m); it was dropped because the brief's clip list does not name it, which moves the median to 1.5002 m.
Diagnostics on the tuning clips (measured at D0 and T4): lifter B's shoulder line is twisted 119 and 113 deg (medians)
off its own hip line on the side and 3/4 takes, where the GPU's twist medians are 4 and 1 deg; T4 brings them to 9
and 17 deg. On the 3/4 squat T4 then leans the trunk back (median 6 deg) where the GPU leans forward (median 25 deg),
differing by over 20 deg in 52% of frames, which is why that clip is worse than lifter B. Even the D1 upper bound
misses 0.10 m on every tuning clip, so the bar likely needs more than the sign prior.

One bar measurement (orchestrator, once, with `bones-prior` in the registry):
`make outputs BACKEND=cpu LIFTER=bones-prior SCORED=<scratch>` then
`uv run python -m part2.eval_3d --cpu <scratch>/cpu-single/pose3d.json --lifter bones-prior` (reference: the
default `fixtures/output/scored/single/pose3d.json`; exit 0 pass, 1 fail, 2 missing). Before the wiring, the same
lift: `uv run python -m part2.backends.cpu_rtm fixtures/input/single/frames <scratch> --lifters bones-prior`
then `eval_3d --cpu <scratch>/bones-prior/pose3d.json`. One revision is allowed after a label-free
diagnostic (for example the trunk lean or twist distributions of the output, not its distance to the reference),
recorded in this table first.

B2 acceptance criteria (tests in `tests/test_lifter_bones_prior.py` unless stated):
- AC-BP01: registration. `lifters.names()` is `["bones-prior", "fixed-bones", "motionbert"]` and `DEFAULT` is
  `bones-prior`; `lifters.get`, `resolve` and `stamp.entry_modules` work for it; `import part2.lifters` does not import
  the module (it loads on first use) and neither it nor its use imports torch, rtmlib or onnxruntime.
- AC-BP02: an elbow that would bend backwards gets the flexed sign. In a single photo with the forearms raised toward
  the camera, both wrists come out nearer the camera than their elbows; a candidate with the mirrored forearm costs
  over 60 deg.
- AC-BP03: a cross-legged seated pose keeps knees and hips in limits: knee and hip extension excess under 1 deg on
  every seated frame, knees nearer the camera than the hips as in truth.
- AC-BP04: temporal continuity. A sign whose joint jumps a bone length stays through one frame that prefers the other
  root; with a near-parallel bone (gap 0.1) it flips; on the moving synthetic clip of lifter B's AC-B07, depth signs
  agree with truth on at least 95% of limb-frames and bone CV stays under 0.01, tree bones at their fitted length.
- AC-BP05: every output joint lies on its ray (reprojection within 1e-6 px), bone lengths are lifter B's times
  `H_CHAIN / 1.60`, the nose sits `FACE_FWD` (scaled) nearer the camera than the shoulders facing the camera and
  level with them in profile.
- AC-BP06: through the cpu backend the output is `rtmpose-x+bones-prior` with lifter B's body3d shape, provenance
  `lifter: bones-prior`, no extra models, and `lifter_info` holding lifter B's keys plus `sign_flips` and
  `prior_cost_mean`.
- AC-BP07: deterministic (two runs equal), numpy only (no torch, rtmlib or onnxruntime imported), bad shapes refused
  with `bones-prior: expected kp2d (n, 17, 2) and conf (n, 17)`.
- AC-BP08: parameters fixed away from the bar fixture: every tuning run is in the table above before the one bar
  measurement, and its result is recorded beside it (inspection).
- AC-BP09: the chunked forward pass equals the whole-clip pass. `solve` on a noisy 200-frame synthetic clip (six
  chunks and a partial one, all 1024 configurations) and at every chunk boundary (1, 2, 32, 33 and 65 frames, on every
  16th configuration) gives the same path and the same prior cost as the pre-change implementation copied into the
  test, with `np.array_equal` (no tolerance: no operation or its order changed). The traced peak memory grows by under
  24 KB per extra frame between 64 and 256 frames (the copied pre-change code: over 60 KB).

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
| `part2/backends/__init__.py` | registry: `get`, `names`, `UnknownBackend`, resolution of flag, env and default; `python -m part2.backends <name> --smoke`. TICKET-046: holds the `cpu-sam3db` entry (`_MODULES`, `REFUSAL`, `CHOICES`). TICKET-047: `NoPersonFound(RuntimeError)` with `exit_code = 4`, the one exception for "no person in any frame" (see AC-B02) |
| `part2/backends/gpu_sam3db.py` | GPU backend wrapping `part2/body3d.py`; `install_problem()` is the one list of profile, torch, CUDA, source and weight checks that `available()` of this backend and of `cpu-sam3db` call (TICKET-046 R7) |
| `part2/backends/cpu_rtm.py` | CPU backend: rtmlib detector and RTMPose-x, focal, root depth search |
| `part2/lifters/__init__.py` | lifter registry: `get`, `names`, `UnknownLifter`; registers `bones-prior` and names it `DEFAULT` with the measurements beside it (TICKET-046) |
| `part2/lifters/fixed_bones.py` | lifter B; `facing` is public for `bones_prior` (TICKET-046 R12) |
| `part2/lifters/motionbert.py` | lifter C, joint mapping tables |
| `part2/backends/cpu_sam3db.py` | TICKET-044 (J3, approach B1): SAM 3D Body run on the CPU device as an added `cpu` variant; fp32 MoGe and the pinned source's CUDA moves redirected to the CPU inside Part 2, the third-party source unedited; `timing` with `warm` (TICKET-046 R11) |
| `part2/lifters/bones_prior.py` | TICKET-044 (J3, approach B2): lifter `bones-prior`, the `fixed-bones` lift with a depth-sign and joint-limit prior whose parameters are fixed away from the bar fixture; the Viterbi forward pass in chunks (TICKET-046 R8) |
| `tests/test_cpu_sam3db.py`, `tests/test_lifter_bones_prior.py` | TICKET-044 tests; TICKET-046: the shared install check, the timing of a warm request, the chunked Viterbi equal to the copied pre-change code |
| `tests/test_registry_entries.py` | TICKET-046 test, replacing the TICKET-044 test of the removed runtime layer: the registry files name `cpu-sam3db`, `bones-prior` and the default; every entry point (`part2 run`, `part2.outputs`, `part2.check`, the worker, `part2.backends`, `python -m part2.backends.cpu_rtm`) resolves them in a fresh interpreter; the flag and `PART2_LIFTER` still win; a bad lifter or backend is refused naming all the names |
| `part2/eval_3d.py` | the 3D bar; `no_cpu(backend)` words the `no cpu outputs` status with the `make outputs BACKEND=` that makes the dir asked for (AC-B25) |
| `part2/body3d.py` (modified) | device argument; no other behaviour change. TICKET-043: the six foot points per person and `moved_feet` (spec `integration-contract.md`) |
| `part2/cli.py` (modified) | `--backend`, `--lifter`; the NO_GPU_ENV message names `make setup-gpu` and `--backend cpu`; TICKET-046: a refused key is recognised by `CredentialRefused.tracker` (`docs/design/specs/tracker-registry.md`) |
| `part2/worker.py`, `part2/backends/__main__.py` (modified) | TICKET-044: the variant names resolve in `serve` and `python -m part2.backends` (TICKET-046: from the registry files, with no import of a runtime layer) |
| `part2/check.py` (modified) | adds the `cpu_backend_3d` block (layout in `docs/design/specs/check-2.md`); TICKET-044: `--cpu-mode` and `PART2_CPU_MODE` pick the CPU dir, `seconds_per_frame` from `provenance.timing`, a dir that is not a CPU backend's output is refused (AC-B25) |
| `part2/outputs.py` (modified) | TICKET-044: mode `cpu-sam3db-single`, the variant's refusal line (AC-B24) |
| `envs/gpu-cu128/requirements.txt`, `envs/gpu-cu128/constraints.txt`, `envs/gpu-cu128/setup.sh` | GPU profile (published under `envs/**`) |
| `envs/gpu-cu128/check_weights.py` | reads `OFFICIAL_SHA256` from `k8s/infer_one.py` with `ast` and checks the downloaded files (AC-B12); called by `setup.sh` |
| `tests/test_check_weights.py` | AC-B12 with a copy of `k8s/infer_one.py` and fake files |
| `envs/cpu/requirements.txt` | CPU extras: rtmlib, onnxruntime, CPU torch for lifter C (exact pins at TICKET-013) |
| `Makefile` (modified) | `setup-gpu`, `setup-cpu`, `check-2-cpu` (TICKET-044: `CPU_MODE`; `make outputs BACKEND=cpu-sam3db` hides CUDA as for `cpu`) |
| `tests/test_backends.py`, `tests/test_lifter_fixed_bones.py`, `tests/test_lifter_motionbert.py`, `tests/test_eval_3d.py` | tests; heavy models are faked, the real models run in `make outputs` |
| `part2/backends/cpu_rtm.py` (modified) | TICKET-046: `python -m part2.backends.cpu_rtm --help` shows the `--lifters` default, every registered lifter |

## Acceptance Criteria
### AC-B01: registry and precedence
`part2 run --backend cpu` with `PART2_BACKEND=gpu` runs the CPU backend; with no flag the environment wins; with
neither, `gpu` when CUDA is available, else `cpu`. An unknown name exits 2: `part2: unknown backend "x"; choose gpu or cpu or cpu-sam3db`.
Test: `tests/test_backends.py`, `tests/test_registry_entries.py`.
### AC-B02: same output shape
Both backends' `body3d.json` pass the same shape check as `body3d.py` output, and `canonical.write` turns each into
a `pose3d.json` that `schema.validate_pose3d` and `contracts/pose3d.schema.json` accept. Test with fake models.
When no frame has a person, all three backends (`gpu`, `cpu`, `cpu-sam3db`) raise `backends.NoPersonFound` with
`no person found in <n> frames` (unchanged text) and no `pose3d.json` is written; `part2 run` prints `part2: <message>` and
exits 4, not 1 (`part2-images-to-3d.md` AC-011, `CONTRACT.md` "Exit codes"). `backends.NoPersonFound` is defined in
`part2/backends/__init__.py`, which imports no torch and no other `part2` module. Tests: `tests/test_backends.py`,
`tests/test_cpu_rtm.py`, `tests/test_cpu_sam3db.py`.
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
TICKET-016 ran the lifters on the single fixture, recorded each block in the ticket, set the default to the one that
passes (more than one passes: lower `mean_m`; none: lower `mean_m`, and the CPU backend is labelled "3D approximate"
in the run app and the README) and wrote it in Locked defaults. With three lifters (`bones-prior` added by
TICKET-044) none passes, so the lowest `mean_m` wins and `bones-prior` is the default (0.145 m against 0.2656 m for
`fixed-bones` and 0.2914 m for `motionbert`). Test: `tests/test_registry_entries.py` (the file says `DEFAULT =
"bones-prior"`; every entry point resolves `bones-prior` with no lifter named in a fresh interpreter, `python -m
part2.backends.cpu_rtm` included; `--lifter fixed-bones` and `PART2_LIFTER` still win).
### AC-B11: provenance
Every output of either backend carries `provenance.backend`, `models[].weights_sha256` and, for the CPU backend,
`lifter` and the ADR-0005 licence note. Files without `provenance` still validate.

### AC-B20: the CPU variant is registered beside gpu and cpu
`backends.names()` is `["cpu", "cpu-sam3db", "gpu"]` from `part2/backends/__init__.py` alone, in every entry point and
with no torch imported. `backends.get("cpu-sam3db")` is the variant on device `cpu`;
`--backend cpu-sam3db` and `PART2_BACKEND=cpu-sam3db` select it; with neither, the default stays `gpu` or `cpu` by
CUDA (`resolve()` never picks the variant), and an unknown name exits 2 with `unknown backend "x"; choose gpu or cpu or
cpu-sam3db`. `available()` is true with no CUDA device when the profile, torch,
the source and the weights are present, and names the first one missing otherwise. Without the profile,
`python -m part2.backends cpu-sam3db [--smoke]` exits 1 with `part2: the cpu-sam3db backend needs the gpu-cu128
profile and its venv python (make setup-gpu)`. Test: `tests/test_cpu_sam3db.py`, `tests/test_registry_entries.py`
(each entry point in a fresh interpreter).
### AC-B21: the CPU redirections are scoped
Loading and running the variant leaves `torch.Tensor.cuda`, `torch.Tensor.to` and the `MoGeModel.infer` class
attribute as they were; only the variant's own MoGe-2 instance runs without fp16; each `process_one_image` call (also
through the focal rung's `FixedK`) runs inside one `on_cpu()` mode that ends with the call, and under it `.cuda()`,
`.to("cuda")` and `device="cuda"` give CPU tensors; and the mode ends when `process_one_image` raises. Test:
`tests/test_cpu_sam3db.py` (fake torch for the scope, the focal rung and the raising call; the real-torch tests skip
under `make test`, which has no torch). The command that runs them, on the CPU in the gpu-cu128 venv (pytest on its
own path, see `docs/dev/DEVELOPING.md` section 7): `CUDA_VISIBLE_DEVICES=
PYTHONPATH=.:$HOME/.local/state/simon-part-2/pytest-only ~/.local/state/simon-part-2/venvs/gpu-cu128/bin/python -m
pytest -q tests/test_cpu_sam3db.py` (36 passed, none skipped, exit 0 on 2026-10-31, after TICKET-046).
### AC-B22: device and provenance
The `provenance` of `body3d.json` and `pose3d.json` names `backend: "cpu-sam3db"`, `device: "cpu"`, the same `models`
(names, sources and SHA-256) as the gpu backend's profile, `detector`, `focal_source: "moge2"` and `timing`. People
carry the six foot points and `pose3d.json` validates with `extra_joints`. Test: `tests/test_cpu_sam3db.py`.
### AC-B23: its speed is recorded
Every estimate records `timing.seconds_per_frame` with `load_s`, `seconds`, `frames`, `threads` and `warm`
(`load_s` is the load that estimate paid for: 0.0 and `warm: true` on a model loaded earlier, as for every request
after the first of a warm worker); the smoke prints them; `make check-2-cpu CPU_MODE=cpu-sam3db-single` prints `seconds_per_frame` and `timing` beside the bar, and the
bar fixture's figure is recorded with the bar measurement in TICKET-044. Test: `tests/test_cpu_sam3db.py`;
demonstration: the smoke.
### AC-B24: scored mode
`python -m part2.outputs --backend cpu-sam3db` runs only `cpu-sam3db-single` on `fixtures/input/single/frames`,
without the host GPU lock, into `<scored>/cpu-sam3db-single/` with a fresh stamp whose code files include
`cpu_sam3db.py`, `gpu_sam3db.py` and `body3d.py`; the variant's module is in no other mode's stamp. When the variant
cannot run, exit 1 with the refusal of AC-B20 and the reason. Test: `tests/test_cpu_sam3db.py`.
### AC-B25: the bar on a named CPU dir
`make check-2-cpu` without `CPU_MODE` prints the block as before (it scores `cpu-single`, and a file without
`provenance.timing` adds no speed keys). With `CPU_MODE=<name>` (or `PART2_CPU_MODE`, or `--cpu-mode`, which wins) it
scores `<scored>/<name>` against `<scored>/single` with the same eval, stamp checks and exit codes (2 when the named
dir has no `pose3d.json`, and `status` then names the `make outputs BACKEND=` that makes the dir: `cpu-sam3db` for
`cpu-sam3db-single`, `cpu` otherwise). A name with a path separator or dots is refused (exit 1, `status` starting
`error: ValueError:`). The reference `single`, or a dir whose `stamp.json` names a backend other than `cpu` and
`cpu-sam3db`, is not a CPU mode: refused with exit 1 and one `status` line naming the dir and its backend (before,
`CPU_MODE=single` scored the reference against itself and passed with a mean of 0.0). A dir with no readable backend
(no stamp, a v1 stamp) is left to the stamp check. `make check-2` keeps its gated blocks and top-level `pass`. Test:
`tests/test_cpu_sam3db.py`.
### AC-B26: RTMPose-x and both lifters stay selectable
Adding the variant changes neither the `cpu` backend (RTMPose-x through rtmlib) nor the other lifters nor mode
`cpu-single`: `backends.get("cpu")` is still `cpu_rtm.Backend`, `fixed-bones` and `motionbert` stay registered beside
`bones-prior`, and
`--backend cpu` makes `cpu-single` only. Test: `tests/test_cpu_sam3db.py`, `tests/test_cpu_rtm.py`,
`tests/test_outputs.py`.

### AC-B27: `run --mesh` works on the CPU variant (TICKET-048)
`cpu-sam3db` runs the same SAM 3D Body as `gpu`, so `estimate(..., mesh=collector)` hands the collector to
`body3d.estimate` through the one helper `gpu_sam3db.mesh_kwargs`, and the pair equals the gpu run's on the same
input; without a collector the `body3d.estimate` call is unchanged, and `install_problem`, the `warm` timing and
the no-person exit 4 are untouched. Spec: `mesh3d.md` AC-M10, AC-M11. Test: `tests/test_mesh3d.py`.

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
| unknown backend or lifter | exit 2 | `part2: unknown backend "<x>"; choose gpu or cpu or cpu-sam3db`, or `part2: unknown lifter "<x>"; choose bones-prior or fixed-bones or motionbert` | AC-B01 |
| gpu requested, no CUDA or no profile | exit 1 | `part2: the gpu backend needs CUDA and the gpu-cu128 profile (make setup-gpu); use --backend cpu` | AC-B05 |
| cpu extras missing | exit 1 | `part2: the cpu backend needs make setup-cpu` | AC-B06 |
| weights download fails | exit 1 | `part2: could not download <model> weights from <source>` | AC-B03 |
| CUDA out of memory | exit 1, partial outputs removed | `part2: the GPU ran out of memory; free memory or use --backend cpu` | AC-B03 |
| no person found in any frame | exit 4 (`NoPersonFound`, TICKET-047); no `pose3d.json` | `part2: no person found in <n> frames` | AC-B02 |
| cpu-sam3db requested without the gpu-cu128 profile, torch, source or weights | exit 1 | `part2: the cpu-sam3db backend needs the gpu-cu128 profile and its venv python (make setup-gpu)` | AC-B20 |
| `CPU_MODE`, `PART2_CPU_MODE` or `--cpu-mode` names a path | block fails, exit 1 | `error: ValueError: PART2_CPU_MODE or --cpu-mode names a mode dir of the scored dir, not the path "<x>"` | AC-B25 |
| `CPU_MODE`, `PART2_CPU_MODE` or `--cpu-mode` names the reference `single` or a dir made by a non-CPU backend | block fails, exit 1 | `<dir> is the GPU reference (backend <b>), not a CPU mode dir; choose a dir made by cpu or cpu-sam3db` or `<dir> was made by backend <b>, not a CPU backend; choose a dir made by cpu or cpu-sam3db` | AC-B25 |
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
| Default lifter | `bones-prior` (2026-10-31, TICKET-044), `DEFAULT` in `part2/lifters/__init__.py` (TICKET-046; TICKET-016 had set `fixed-bones`). Measured on `fixtures/input/single` (111 frames), each against its own reference: `bones-prior` mean_m 0.145, p95_m 0.3789, bone_cv_mean 0.016, bone_cv_max 0.1117, against the refined `fixtures/output/scored/single` (about 2 s per frame); `fixed-bones` mean_m 0.2656, p95_m 0.7993, bone_cv_mean 0.0117, bone_cv_max 0.0571, against the refined `single`; `motionbert` mean_m 0.2914, p95_m 0.5987, bone_cv_mean 0.1400, bone_cv_max 0.4028, against the local gpu `single` of 2026-10-29 (its first measurement: `fixed-bones` was 0.2682 m against that reference). None of the three passes, so the lowest mean_m wins and the `cpu` backend is "3D approximate". `cpu-sam3db` (a backend, not a lifter, no lifter) meets the bar: mean_m 0.0363, p95_m 0.0808, bone_cv_mean 0.0408, bone_cv_max 0.0981, 111 of 111 frames, 31.74 s per frame on 8 threads plus 23.7 s load; the reference is refined and the run is unrefined; chosen by name only. These are the 2026-10-31 figures the decision rests on; the sets committed on 2026-11-01 give `bones-prior` p95_m 0.3788 (mean_m 0.1451) and `cpu-sam3db` p95_m 0.0807 at 46.95 s per frame plus 23.4 s load under host load, the other figures unchanged | AC-B10 (TICKET-016, TICKET-044) |
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
3. No lifter meets the bar. Likelihood: M, Impact: M, Mitigation: AC-B10 labelling. (It happened with all three; the
   backend `cpu-sam3db` meets the bar by name only, TICKET-044.)

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|---|---|---|---|
| Decision 2 backend switch | AC-B01, AC-B05 | `tests/test_backends.py` | pending |
| Decision 2 same outputs | AC-B02, AC-B11 | `tests/test_backends.py` | pending |
| Decision 2 primary GPU on the 5090 | AC-B03, AC-B04, AC-B12 | demonstration (TICKET-011), `tests/test_backends.py` | pending |
| Decision 2 CPU plus lifters B and C | AC-B06, AC-B07, AC-B08 | `tests/test_lifter_*.py` | pending |
| Decision 2 3D bar | AC-B09, AC-B10 | `tests/test_eval_3d.py` | pending |
| TICKET-044 B1: SAM 3D Body on the CPU device | AC-B20 to AC-B26 | `tests/test_cpu_sam3db.py` | pending (bar fixture measurement) |

## Delivery Verification Plan
`make test` exit 0; `make setup-gpu` and the smoke exit 0 with numbers in TICKET-011; `make outputs BACKEND=gpu`
and `make outputs BACKEND=cpu` then `make check-2` and `make check-2-cpu`, exit codes in STATUS.md (TICKET-018,
TICKET-016). Staging names the backend on every result (`docs/design/specs/run-app.md`). TICKET-044 B1:
`uv run pytest -q tests/test_cpu_sam3db.py` exit 0, the smoke with `CUDA_VISIBLE_DEVICES=`, then
`make outputs BACKEND=cpu-sam3db` (which hides CUDA) and
`make check-2-cpu CPU_MODE=cpu-sam3db-single`, with exit codes and seconds per frame in TICKET-044 and STATUS.md.
