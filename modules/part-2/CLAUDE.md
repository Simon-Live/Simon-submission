# Agent instructions — Simon Part 2 only

You are working on **Part 2: Images to 3D models** and nothing else. Read `README.md` in this repo; it is the whole task context. Do not go looking for other parts' code or repos.

- Input: Video frames. Two modes: a one-person recording (trainer or single follower) and a multi-person class recording.
- Output: `pose3d.json` per tracked person; multi-person mode also writes `tracks.json` (stable ID, box, mask, confidence per person per frame).
- Done when: One-person: on 20 hand-clicked frames including side views, 3D joints reproject within 5% of body height. Multi-person: class clip with ≥5 people, each tracked on ≥95% of frames with ≤1 ID swap per minute, each with a pose3d stream.
- Done-check: `make check-2` (write it; the Makefile stub fails until you do).
- Black box: consume other parts only through the shared files named in `README.md`, from `fixtures/input/`. Never import another part.
- End work with the done-check output in your final message.
