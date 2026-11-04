# Agent instructions — Simon Part 6 only

You are working on **Part 6: Video recording / playback app** and nothing else. Read `README.md` in this repo; it is the whole task context. Do not go looking for other parts' code or repos.

- Input: The phone camera (record) and the catalog (playback). Catalog entries are built from the shared files below.
- Output: A catalog of expected movements: each entry is a recorded video plus the `keyframes.json`, `skeleton.json` and `animation.json` produced from it, with a name a trainer can find again.
- Done when: Record a movement and it appears in the catalog with its animation; play an entry back at full and half speed with play/pause/scrub, on a phone browser.
- Done-check: `make check-6` (write it; the Makefile stub fails until you do).
- Black box: consume other parts only through the shared files named in `README.md`, from `fixtures/input/`. Never import another part.
- End work with the done-check output in your final message.
