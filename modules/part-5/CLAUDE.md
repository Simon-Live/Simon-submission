# Agent instructions — Simon Part 5 only

You are working on **Part 5: Compare 3D animations and analyse faults** and nothing else. Read `README.md` in this repo; it is the whole task context. Do not go looking for other parts' code or repos.

- Input: The expected `animation.json` (or `skeleton.json`) plus a follower's `skeleton.json`. Fixtures in `fixtures/input/`.
- Output: `analysis.json` — per fault: what differed, which joint/body part, the size of the difference, and a plain-words line (e.g. "left foot too far out", "elbows wider than the example").
- Done when: On labelled follower clips (correct and deliberate-fault takes, several angles): fault precision ≥0.85 and recall ≥0.75 in good light, every other angle reported separately; on correct takes it reports no faults.
- Done-check: `make check-5` (write it; the Makefile stub fails until you do).
- Black box: consume other parts only through the shared files named in `README.md`, from `fixtures/input/`. Never import another part.
- End work with the done-check output in your final message.
