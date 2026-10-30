# ADR-0002: Python 3.12 with numpy, plain static viewer

> Copy of the maintainers' working ADR `docs/adr/ADR-0002-stack.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Date: 2026-10-27. Status: accepted.

## Context
Part 3 is geometry on small arrays (17 joints, hundreds of frames). Part 2 ships Python. The host has
Python 3.12.3, numpy 2.4.6 and pytest 9.1.0 installed. The isolated demo is a local 3D page (no staging,
operator 2026-10-27).

## Options Considered
### Option 1: Python + numpy, stdlib everything else
Fast enough, no install step on this host, easy for teammates to run.
### Option 2: Python + scipy (Rotation, DTW helpers)
Less code for rotations and DTW, but a second heavy dependency for two small functions.
### Option 3: JavaScript end to end
One language with the viewer, but the team's tooling and Part 2 are Python.

## Decision
Option 1. `requirements.txt` pins `numpy==2.4.6` and `pytest==9.1.0`; `make setup` creates `.venv`
with them, and the Makefile falls back to the system `python3` when it already has both. DTW and
rotations are written in numpy. The viewer is static HTML, CSS and JavaScript modules using three.js
r170, vendored in `web/vendor/three/` (no CDN at run time, no build), served locally by
`python3 -m http.server` (`make demo`).

Verified on this host 2026-10-27 (prep lane): `python3 --version` gives 3.12.3; `python3 -c "import
numpy, pytest"` gives 2.4.6 and 9.1.0, exit 0; GNU Make 4.3. No `.venv` is needed here; `make setup`
(`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`) is for other hosts and needs
network.

## Consequences
No compiled dependencies beyond numpy; the viewer works offline. ES modules do not load over
`file://`, so the page is always served by `make demo`.

## Assumptions
ASM-006 (numpy 2.4.6 stays available on the hosts that run `make check-3`).

## Reversal Cost
Low: scipy can be added later behind the same functions.

## Pre-Mortem (MANDATORY)
A teammate on Python 3.10 cannot run it. Guard: README states Python 3.11 or later; no 3.12-only syntax.

## Dissent (MANDATORY)
Vendoring 1.3 MB of three.js adds weight to the upstream repo. Accepted (prep lane 2026-10-27,
replacing the earlier hand-written canvas plan): orbit and zoom come tested, the pin is one
directory with its hashes in `VERSION`, and no network is needed.

## Code Backlinks (updated as code is written)
`requirements.txt`, `Makefile`, `web/vendor/three/VERSION`.
