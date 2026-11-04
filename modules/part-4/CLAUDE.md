# Agent instructions — Simon Part 4 only

You are working on **Part 4: Animate 3D models between key frames** and nothing else. Read `README.md` in this repo; it is the whole task context. Do not go looking for other parts' code or repos.

- Input: `skeleton.json` (Part 3) sampled at the key frames in `keyframes.json` (Part 1). Fixtures in `fixtures/input/`.
- Output: `animation.json` — a smooth 30 fps 3D animation of the expected movement.
- Done when: With some in-between frames hidden, the animation rebuilds them within 8° per joint; bone lengths stay fixed throughout.
- Done-check: `make check-4` (write it; the Makefile stub fails until you do).
- Black box: consume other parts only through the shared files named in `README.md`, from `fixtures/input/`. Never import another part.
- End work with the done-check output in your final message.
