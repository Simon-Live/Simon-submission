# Simon Part 6 — Video recording / playback app


Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
This repo is **only** Simon Part 6. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way — that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #60. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 6).

## Input

The phone camera (record) and the catalog (playback). Catalog entries are built from the shared files below.

## Output

A catalog of expected movements: each entry is a recorded video plus the `keyframes.json`, `skeleton.json` and `animation.json` produced from it, with a name a trainer can find again.

## Shared-file context (only what this part touches)

A catalog entry: `{id, name, video_uri, keyframes, skeleton, animation, created_at}` referencing the shared files by name. This repo owns recording/playback/catalog UI only — it does not compute key frames, pose, or faults.

## Frontier model

none

## Definition of done

Record a movement and it appears in the catalog with its animation; play an entry back at full and half speed with play/pause/scrub, on a phone browser.

Done-check: `make check-6` — prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** Record 10 seconds, find it in the catalog, play its 3D animation.
- **Integrated:** Part 7 opens on this catalog ('pick a movement, then follow it').

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-6`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.
