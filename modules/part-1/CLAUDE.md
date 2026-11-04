# Agent instructions — Simon Part 1 only

You are working on **Part 1: Key frame finder/splitter** and nothing else. Read `README.md` in this repo; it is the whole task context. Do not go looking for other parts' code or repos.

- Input: A movement video dropped in `inbox/`. Do not draw stand-in clips.
- Output: `keyframes.json` — the key frames of each repetition/section (e.g. start, bottom, top for a push-up), as frame indices with `t_ms`.
- Done when: On 3 hand-labelled videos, ≥90% of key frames land within 0.3 s of the labels, and the repetition/section count is exact.
- Done-check: `make check-1` compares `fixtures/labels/` with `out/<name>/keyframes.json`.
- Black box: consume other parts only through the shared files named in `README.md`. Never import another part.
- End work with the done-check output in your final message.
