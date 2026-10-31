# ADR-0002: Two inference backends (GPU and CPU) and separate dependency profiles

> Copy of `docs/adr/ADR-0002-backends-and-profiles.md` from the maintainers' working repo at `e846ede`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

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
