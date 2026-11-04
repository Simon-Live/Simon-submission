# Agent instructions — Simon Part 3 only

You are working on **Part 3: Align 3D model / skeleton consistency** and nothing else. Read `README.md` in this repo; it is the whole task context. Do not go looking for other parts' code or repos.

- Input: `pose3d.json` (from Part 2, any camera angle). Fixtures in `fixtures/input/`.
- Output: `skeleton.json` — the same motion with one fixed set of bone lengths, rotated to a standard facing, scaled to standard limb lengths, no left/right label flips.
- Done when: Bone-length variation <2% across a clip; zero left/right flips; the same movement filmed from 4 synced phones produces skeletons whose joint angles agree within 10°.
- Done-check: `make check-3` (write it; the Makefile stub fails until you do).
- Black box: consume other parts only through the shared files named in `README.md`, from `fixtures/input/`. Never import another part.
- End work with the done-check output in your final message.
