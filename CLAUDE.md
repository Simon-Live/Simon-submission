# Agent instructions — Simon Part 7 only

You are working on **Part 7: Stitching into one app** and nothing else. Read `README.md` in this repo; it is the whole task context. Do not go looking for other parts' code or repos.

- Input: The outputs of Parts 1–6, consumed only through their shared files (`keyframes.json`, `tracks.json`, `pose3d.json`, `skeleton.json`, `animation.json`, `analysis.json`, catalog entries).
- Output: The Simon app: pick (or record) an expected movement from the catalog → watch its animation → perform it to camera → get the Part 5 fault analysis.
- Done when: End to end on a movement the app was never hand-configured for: record it via Part 6, follow it, and the faults reported match running Parts 2–5 directly on the same recorded follower clip.
- Done-check: `make check-7` (write it; the Makefile stub fails until you do).
- Black box: consume other parts only through the shared files named in `README.md`, from `fixtures/input/`. Never import another part.
- End work with the done-check output in your final message.
