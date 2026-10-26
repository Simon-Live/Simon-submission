# Agent instructions — Simon Part 1 only

You are working on **Part 1: Key frame finder/splitter** and nothing else. Read `README.md` in this repo; it is the whole task context. Do not go looking for other parts' code or repos.

- Input: A movement video (trainer demo or follower take). Fixtures: `fixtures/input/` holds example videos or frame lists.
- Output: `keyframes.json` — the key frames of each repetition/section (e.g. start, bottom, top for a push-up), as frame indices with `t_ms`.
- Done when: On 3 hand-labelled videos, ≥90% of key frames land within 0.3 s of the labels, and the repetition/section count is exact.
- Done-check: `make check-1` (write it; the Makefile stub fails until you do).
- Black box: consume other parts only through the shared files named in `README.md`, from `fixtures/input/`. Never import another part.
- End work with the done-check output in your final message.
