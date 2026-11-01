# ADR-0002: Two inference backends (GPU and CPU) and separate dependency profiles

> Copy of `docs/adr/ADR-0002-backends-and-profiles.md` from the maintainers' working repo at `843de10`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted (stakeholder-proxy, 2026-10-28)
Date: 2026-10-28

## Context
Part 2's 3D stage is SAM 3D Body with ViTDet and MoGe-2, hard-coded to `cuda`, run on the HPC cluster (V100)
or the team's k3s pod with torch 2.5.1/cu124. This host has an RTX 5090 (32 GB, compute capability 12.0,
driver CUDA 13.3, no `nvcc`, no torch installed). torch 2.5.1/cu124 ships no sm_120 kernels. the team
asked (#46) for a path that needs no HPC and no GPU; the CPU probe there measured RTMPose-x 2D at mean
3.97% with 1/20 frames over 5%, and prototype A (RTMPose 2D plus MediaPipe depth) at 15.7 cm mean joint
distance from the GPU reference and bone CV about 15%. Muse proposed a 3D bar before building more.

## Options Considered
### Option 1: GPU only, port the team profile to the 5090
- Pros: one code path. Cons: no answer to #46; torch 2.5.1 cannot run on sm_120. Effort: Medium.
### Option 2: CPU only (RTMPose plus a lifter)
- Pros: runs anywhere. Cons: drops the frontier model the README names; 3D quality unproven. Effort: Medium.
### Option 3: a backend registry with both, separate dependency profiles
- Pros: the GPU backend keeps SAM 3D Body as the primary; the CPU backend answers #46; the team's
  profile and k8s/HPC targets keep working. Cons: two environments to maintain. Effort: High.

### Option 4: host SAM 3D Body on Baseten (considered 2026-10-28, rejected)
- Proposal (operator, 2026-10-28): use $100 of Baseten credits to host the team's exact stack (torch
  2.5.1/cu124) on a rented GPU as the reference backend and a staging fallback.
- Evidence against (operator, 2026-10-28, from the Baseten hackathon email; key checked with one chat call,
  HTTP 200): the key works only against the OpenAI-compatible endpoint `https://inference.baseten.co/v1`
  with the model `meta-models/muse-spark-open-1026`. No custom deployment and no `truss push`, so SAM 3D Body
  cannot run there. Rejected. `BASETEN_API_KEY` exists in the operator key directory; Part 2 does not use
  it, and Muse Spark is not used in Part 2.

## Decision
Option 3. `--backend gpu|cpu` (env `PART2_BACKEND`, the flag wins). Primary `gpu` = SAM 3D Body on torch
2.7 or newer with cu128 wheels on the local 5090, in its own profile under `envs/gpu-cu128/` with its venv
outside the tree. The team profile (`k8s/`, `hpc/`, torch 2.5.1) is untouched. `cpu` = RTMPose-x through
rtmlib (ONNX Runtime) plus a lifter registry: B `fixed-bones` (per-person bone lengths fitted over the
clip) and C `motionbert`; the default lifter is whichever better meets the 3D bar as measured
(TICKET-016). The 3D bar is Muse's, adopted unchanged: on the single fixture, mean per-joint distance to
the GPU reference at most 0.10 m and bone-length CV at most 0.05. It is reported by `make check-2` as the
separate block `cpu_backend_3d`, gated by `make check-2-cpu`, never folded into the README DoD.
The reference reproduction of the HPC 5.29% runs on the local `gpu` backend; `cpu` is the fallback. If
the cu128 port fails inside its timebox, the record says the reference could not be reproduced on this host
and the ladder runs on the backend that works. Staging fallback order: local `gpu`, then `cpu`. The cu128
setup checks the mirrored weights against the SHA-256 digests in `k8s/infer_one.py` (`OFFICIAL_SHA256`).
Specs: `docs/design/specs/backends-gpu-cpu.md`, `docs/design/specs/check-2.md`.

## Consequences
- **Positive**: real inference on this host; #46 gets a built, measured answer.
- **Negative**: detectron2 may not build on sm_120 without `nvcc` (ASM-003); the fallback takes person
  boxes from the detector, which differs slightly from the HPC run.
- **Neutral**: every output records its backend, lifter and models in `provenance`.

## Assumptions
- ASM-002, ASM-003, ASM-005, ASM-006, ASM-012.

## Reversal Cost
Medium: the registry is additive; removing a backend deletes its module and profile.

## Pre-Mortem (MANDATORY)
1. torch cu128 breaks a SAM 3D Body op. Likelihood: M, Impact: H. Mitigation: smoke test on one frame first
   (TICKET-011); the k8s/HPC path stays as the fallback producer.
2. Neither lifter meets the 3D bar. Likelihood: M, Impact: M. Mitigation: the CPU backend ships labelled
   "2D accurate, 3D approximate" with its numbers; the GPU backend stays primary.
3. GPU memory is taken by other host work. Likelihood: M, Impact: M. Mitigation: free-memory check before
   each job (ASM-009).

## Dissent (MANDATORY)
Reviewed by: setup lane (architect role)
- Muse voted B first: both are built behind one registry; measurement picks the default.
- the team excludes non-commercial licences: training-data caveats are handled in ADR-0005.
- Two profiles double the setup surface: the team profile is not edited, only a new one added.
- "A hosted GPU would make the reference independent of the risky local build" (operator, Baseten):
  agreed in principle; impossible with a key locked to one hosted chat model (Option 4).

## Code Backlinks (updated as code is written)
- `part2/backends/`, `part2/lifters/`, `envs/gpu-cu128/`, `envs/cpu/`.

## Amendment 2026-10-31: CPU variant `cpu-sam3db` (TICKET-044, approach B1)
Status: Accepted (stakeholder-proxy decision recorded on TICKET-044, 2026-10-31). Append-only: the Decision above
stands and this section adds to it.

### Context
The `cpu` route (RTMPose-x plus `fixed-bones`) misses the 3D bar: mean 0.2656 m against the GPU reference, with limb
depth from the fixed-bones lift as the diagnosed cause (STATUS.md, Limits). A probe at 3cb4699 ran the gpu backend's
SAM 3D Body on the CPU device (model load 23.4 s, one frame 46.7 s on 22 cores) once MoGe-2 ran in fp32 and the
pinned source's hard-coded CUDA moves were redirected.

### Decision
Add `cpu-sam3db` to the backend registry as a CPU variant: the same SAM 3D Body weights, ViTDet and MoGe-2 from the
`gpu-cu128` profile, on device `cpu` (`part2/backends/cpu_sam3db.py`). It joins the registry at runtime from
`part2/variants.py`, which every entry point that resolves names imports, because `part2/backends/__init__.py` and
`part2/lifters/__init__.py` are in the code closure of every committed scored stamp (ADR-0006): those files stay
unedited and no committed stamp goes stale. The two CUDA assumptions are redirected inside
Part 2 for the variant's own calls only: a thread-local torch function mode around each `process_one_image` call
keeps CUDA moves on the CPU, and the variant's own MoGe-2 instance runs `infer` with `use_fp16=False`. Third-party
files stay unedited and no torch attribute is replaced. Provenance names the backend, the device and the seconds per
frame. The variant is measured on the bar fixture through mode `cpu-sam3db-single` and
`make check-2-cpu CPU_MODE=cpu-sam3db-single`.

Unchanged: the `cpu` route as decided above (RTMPose-x through rtmlib on ONNX Runtime, lifters `fixed-bones` and
`motionbert`, both selectable), the default backend rule (`gpu` with CUDA, else `cpu`), the unknown-name message, the
bar and its place outside the README definition of done. Which CPU route becomes the default is set by measurement
(AC-B10, TICKET-044).

### Consequences
- **Positive**: a CPU route that runs the reference model itself, so its 3D can be compared with the GPU output model
  to model, foot points included.
- **Negative**: about 47 s per frame on 22 cores, so the 111 frame fixture takes about 1.5 h, and the variant needs the
  gpu-cu128 venv on a CPU host. A name that resolves only once `part2.variants` is imported is one more thing an entry
  point has to remember; `tests/test_variants.py` checks each one in a fresh interpreter.
- **Neutral**: the variant never takes the host GPU lock; `make outputs BACKEND=cpu-sam3db` hides CUDA as for `cpu`.

### Reversal Cost
Low: remove the `cpu-sam3db` entries of `part2/backends/__init__.py` (`CHOICES`, `_MODULES` and its install message),
`part2/backends/cpu_sam3db.py` and the `cpu-sam3db-single` mode of `part2/outputs.py`. (As first written this named the
`register()` call in `part2/variants.py`; the registration was folded into the registry files, see the note at the end.)

### Pre-Mortem
1. A later SAM 3D Body pin moves tensors to CUDA outside `process_one_image`. Likelihood: L, Impact: M. Mitigation:
   the one frame smoke fails loudly (`No CUDA GPUs are available`) before any long run.
2. The per-frame time makes the variant unusable for interactive runs. Likelihood: H, Impact: M. Mitigation: it is
   selected by name only and becomes a default only by measurement; the run app keeps `gpu` and `cpu`.

### Code Backlinks
- `part2/backends/cpu_sam3db.py`, `part2/backends/__init__.py` (registration), `part2/lifters/__init__.py` (the
  `bones-prior` default), `part2/outputs.py` (mode), `part2/check.py` (`--cpu-mode`), `tests/test_registry_entries.py`.

### Outcome (2026-10-31, TICKET-044; stakeholder-proxy ruling recorded on the ticket)
Each approach was measured once on the bar fixture (`fixtures/input/single`, 111 frames; bar: mean joint distance at
most 0.10 m, mean bone CV at most 0.05), against the refined `single` unless noted:
- `cpu` with `fixed-bones`: 0.2656 m, CV 0.0117, fail.
- `cpu` with `motionbert`: 0.2914 m, CV 0.140, fail (its figure of 2026-10-29, against the `single` of that date).
- `cpu` with `bones-prior` (B2): 0.145 m, CV 0.016, fail; about 2 s per frame.
- `cpu-sam3db` (B1): 0.0363 m, CV 0.0408, meets the bar; 31.74 s per frame on 8 threads plus a 23.7 s model load (the 2026-10-31 run); the 2026-11-01 regeneration, under host load, took 46.95 s per frame plus a 23.4 s model load.
  The reference is a refined model output (focal, kp2d-fit); the `cpu-sam3db` run is unrefined.

Decision. AC-B10 gives the default lifter of the `cpu` backend: none of the three passes, so the lowest mean wins and
`bones-prior` becomes the default (`part2/variants.py` sets it at run time; `part2/lifters/__init__.py` still says
`fixed-bones` and waits for the next full regeneration, because every scored stamp hashes it). `fixed-bones` and
`motionbert` stay selectable. `cpu-sam3db` meets the bar but stays selectable by name only, because of its speed: the
default backend without CUDA stays `cpu`, `--backend cpu` stays RTMPose-x, the run app keeps `gpu` and `cpu`, and
`cpu` stays labelled "3D approximate" (`part2/jobs.py` `CPU_3D_BAR_PASSED` stays False). The bar stays outside the
README definition of done.

Registration, folded (2026-10-31, TICKET-046): the runtime layer that the text above describes was folded into the
registry files themselves on 2026-10-31, so `cpu-sam3db` is an entry of `part2/backends/__init__.py` (named in the
unknown-backend message, never the default), `bones-prior` is an entry of `part2/lifters/__init__.py` with
`DEFAULT = "bones-prior"`, and `tests/test_registry_entries.py` checks every entry point in a fresh interpreter in
place of the removed module's test.

Backlinks corrected (2026-10-31, J3 review of TICKET-048): the Reversal Cost and Code Backlinks lines of this amendment
describe the code as it is, so they were rewritten in place to name the registry files instead of the removed
`part2/variants.py`. The Decision, Consequences and Outcome texts above are history and are unchanged.
