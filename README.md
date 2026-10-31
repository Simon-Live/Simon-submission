# Simon Part 7: Stitching into one app


Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
This repo is **only** Simon Part 7. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way: that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #61. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 7).

## Input

The outputs of Parts 1–6, consumed only through their shared files (`keyframes.json`, `tracks.json`, `pose3d.json`, `skeleton.json`, `animation.json`, `analysis.json`, catalog entries).

## Output

The Simon app: pick (or record) an expected movement from the catalog → watch its animation → perform it to camera → get the Part 5 fault analysis.

## Shared-file context (only what this part touches)

Black-box rule is strictest here: this repo calls the other parts through their files/demos only. No importing another part's code.

## How Part 7 uses Parts 1 to 6

Parts 1 to 6 are git submodules at `modules/part-1` to `modules/part-6`. Each one follows the latest `main` of its the team part repo. There is no pin file and nothing to reconcile: whatever the part repos publish is what Part 7 runs. Part 7 still reads them only through their CLIs and shared files.

- **Clone:** `git clone --recursive https://github.com/moalborati/simon-part-7-stitching-app.git`. Without `--recursive`, run `make parts` after cloning.
- **Update and set up the parts:** `make parts` brings every module to the latest `main` and sets each part up. It is safe to repeat: a part that has not moved is skipped. It stops and names the part when one fails.
- **See what is checked out:** `uv run python -m part7 parts-status` prints each part's path, commit, URL and branch as JSON. Add `--check-remote` to also read each part's remote `main`; it exits 3 when any part has moved on and 0 when all are current.
- **When a part pushes:** staging notices and redeploys itself within about 10 minutes. It runs `make parts` and restarts the app on the new commits. If `make parts` fails, the old app keeps running.
- **When a part push breaks Part 7:** run `make parts`, then `make test` and `make check-7` to see the failure. The fix belongs in the part repo (ask its owner) or, if Part 7 must adapt to a changed contract, in Part 7's adapter under `part7/parts/`. To get back to a working state right away, check out the last good commit inside that module (`git -C modules/part-N checkout <sha>`); `make parts` moves it forward again, so this is for a short investigation only.

## Frontier model

none (stitches Parts 1–6 through their shared files)

## Definition of done

End to end on a movement the app was never hand-configured for: record it via Part 6, follow it, and the faults reported match running Parts 2–5 directly on the same recorded follower clip.

Done-check: `make check-7` prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** n/a, this part is the integrated demo.
- **Integrated:** The submission demo: one take records an exercise, a follower is analysed against it.

## Develop and debug

- [docs/dev/DEVELOPING.md](docs/dev/DEVELOPING.md): set up a host from a fresh clone, run the app (`make dev`), debug a job, run the tests, update the parts.
- [docs/design/](docs/design/README.md): the specs and architecture decisions behind the code.

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-7`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.
