# ADR-0006: Reproducible scored outputs, committed with a stamp that names how they were made

> Copy of `docs/adr/ADR-0006-reproducible-outputs-and-stamps.md` from the maintainers' working repo at `843de10`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted (stakeholder-proxy, 2026-10-28)
Date: 2026-10-28

## Context
`make check-2` scores `out/<mode>/` against `fixtures/input/<mode>/`, and `out/` is gitignored, so a clean
clone fails with "missing output" (exit 2 through make, measured at setup). `out/<mode>/stamp.json` holds
one sha256 over all pipeline code, `k8s/*-gpu.txt`, `k8s/setup_env.sh` and the frames
(`part2/check.py`), so a change to any profile file stales every mode, even modes it does not affect. The
recorded HPC result is not reproducible from the repo.

## Options Considered
### Option 1: keep outputs uncommitted; regenerate before every check
- Pros: no large files. Cons: no GPU means no check; teammates cannot verify. Effort: Low.
### Option 2: commit the scored outputs with a richer stamp; `make outputs` reproduces them
- Pros: a clean clone runs `make check-2` without a GPU; the stamp says which backend, tracker, models and
  environment made them. Cons: about a few MB of JSON per regeneration. Effort: Medium.

## Decision
Option 2. `make outputs` regenerates `fixtures/output/scored/{single,class}/` on this host (and
`fixtures/output/scored/cpu-single/` with `BACKEND=cpu`). `check-2` reads `fixtures/output/scored/` by
default; `make check-2 SCORED=out` scores `out/` for experiments. The stamp becomes `part2.stamp/2`:
backend, tracker, lifter, refine rungs, models with weight sha256, environment profile and its lock sha256,
code sha256 over only the files that mode's backend and tracker use, frames sha256, created time and GPU
name. A change to one profile's lock stales only outputs made with that profile. A v1 stamp reads as stale
with a plain message. The publish check moves from `make -s test` to `make -s check-2` when TICKET-022
commits the scored outputs. Spec: `docs/design/specs/check-2.md`.

## Consequences
- **Positive**: the DoD is checkable from a clean clone; the result names its producer.
- **Negative**: the repo grows by the scored JSON; regenerations add history.
- **Neutral**: `out/` stays the scratch area.

## Assumptions
- ASM-009 (GPU memory is free enough to regenerate when needed).

## Reversal Cost
Low: delete `fixtures/output/scored/` and point `check-2` back at `out/`.

## Pre-Mortem (MANDATORY)
1. The code hash misses a file a backend imports, so stale outputs pass. Likelihood: M, Impact: H.
   Mitigation: the file list per backend and tracker is declared in code and tested by importing.
2. Committed outputs are edited by hand. Likelihood: L, Impact: H. Mitigation: the stamp holds a sha256 of
   each output file; `check-2` refuses a mismatch.
3. Teammates regenerate on HPC with the old stamp. Likelihood: M, Impact: L. Mitigation: `stamp.py`
   writes v2 on every producer, including `k8s/gpu_outputs.sh` and `hpc/hpc_outputs.sh`.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect role)
- Committing outputs mixes data with code: they are fixtures, like the existing `fixtures/output/`.
- A clean-clone green does not prove the host can reproduce them: `make outputs` plus the stamp does.
- Per-mode hashing adds complexity: needed so profile changes do not invalidate unrelated modes.

## Code Backlinks (updated as code is written)
- `part2/stamp.py`, `part2/outputs.py`, `part2/check.py`, `scripts/simon-publish.sh` (`DEFAULT_CHECK_CMD`).
