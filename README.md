# Simon Part 7 — Stitching into one app

This repo is **only** Simon Part 7. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way — that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #61. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 7).

## Input

The outputs of Parts 1–6, consumed only through their shared files (`keyframes.json`, `tracks.json`, `pose3d.json`, `skeleton.json`, `animation.json`, `analysis.json`, catalog entries).

## Output

The Simon app: pick (or record) an expected movement from the catalog → watch its animation → perform it to camera → get the Part 5 fault analysis.

## Shared-file context (only what this part touches)

Black-box rule is strictest here: this repo calls the other parts through their files/demos only. No importing another part's code.

## Frontier model

none (stitches Parts 1–6 through their shared files)

## Definition of done

End to end on a movement the app was never hand-configured for: record it via Part 6, follow it, and the faults reported match running Parts 2–5 directly on the same recorded follower clip.

Done-check: `make check-7` — prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** n/a — this part is the integrated demo.
- **Integrated:** The submission demo: one take records an exercise, a follower is analysed against it.

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-7`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.
