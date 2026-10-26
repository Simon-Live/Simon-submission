# Simon Part 1 — Key frame finder/splitter


Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
This repo is **only** Simon Part 1. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way — that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #55. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 1).

## Input

A movement video (trainer demo or follower take). Fixtures: `fixtures/input/` holds example videos or frame lists.

## Output

`keyframes.json` — the key frames of each repetition/section (e.g. start, bottom, top for a push-up), as frame indices with `t_ms`.

## Shared-file context (only what this part touches)

Output shape: `{video, fps, repetitions: [{rep, keyframes: [{name, frame, t_ms}]}]}`. Phase names are free-form snake_case from the movement (descend/bottom_pause/ascend/top for push-up).

## Frontier model

none

## Definition of done

On 3 hand-labelled videos, ≥90% of key frames land within 0.3 s of the labels, and the repetition/section count is exact.

Done-check: `make check-1` — prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** Video scrubber with the found key frames marked.
- **Integrated:** Part 4 animates between these key frames.

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-1`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.
