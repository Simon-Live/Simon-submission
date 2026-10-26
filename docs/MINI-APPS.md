# Simon scope: 7 parts

**This is Simon's scope. Nothing else is in scope.** Defined by Mo on [#1](https://github.com/moalborati/simon/issues/1) and [#27](https://github.com/moalborati/simon/issues/27), confirmed by the team Oct 26. "Part" and "mini-app" mean the same thing: a small piece that does one thing, can be built and demoed alone, and has a definition of done an AI can check. Earlier lists (the 8-app and 16-app splits, and PLAN.md's P0–P18 roadmap) are superseded — see [progress.md](progress.md).

What Simon does: a trainer records an expected movement once. A follower performs it in front of a camera. Simon compares the follower's 3D movement against the expected 3D movement and tells them what differed ("left foot too far out").

```
trainer video ─► Part 1 key frames ─┐
trainer video ─► Part 2 images→3D ─► Part 3 skeleton consistency ─► Part 4 animate between key frames ─► expected 3D animation
follower video ─► Part 2 ─► Part 3 ───────────────────────────────────────────────────────────────────► Part 5 compare + fault analysis
Part 6 recording / playback / catalog  (records the expected movements Parts 1–4 run on, plays animations back)
Part 7 stitching  (Parts 1–6 in one app: record an expected movement, follow it, get fault analysis)
```

**Frontier models, highlighted where used:** SAM 3D Body (images → 3D) and SAM 3.1 (multi-person tracking) in Part 2. The other parts need no frontier model; do not invent one per part.

## Shared files

Parts connect only through these files. Each part ships a small fixture of its output, so the next part can start before it exists.

| File | Written by | What it holds |
|---|---|---|
| `keyframes.json` | Part 1 | Key frame times/indices per movement (start, bottom, top, …) |
| `tracks.json` | Part 2 | Per frame: each person's ID, box, mask, confidence (`schemas/tracks.schema.json`) |
| `pose3d.json` | Part 2 | Per frame, per person: 17 canonical 3D joints (`schemas/pose3d.schema.json`; joints and coordinate frame as in `schemas/movement.schema.json`) |
| `skeleton.json` | Part 3 | `pose3d.json` cleaned: fixed bone lengths, standard facing, no left/right flips |
| `animation.json` | Part 4 | Smooth 30 fps expected 3D animation between the key frames |
| `analysis.json` | Part 5 | Per-movement fault report: what differed, which joint, by how much, in plain words |
| catalog entry | Part 6 | A recorded expected movement: its video, key frames, and animation, named and searchable |

## The 7 parts

Each part's done-check is `make check-<n>` (written as part of that part). It prints a metrics JSON and exits 0 only when every threshold passes.

### Part 1 — Key frame finder/splitter

- **Input:** a movement video (trainer demo or follower take).
- **Output:** `keyframes.json` — the key frames of each repetition/section (e.g. start, bottom, top for a push-up).
- **Done when:** on 3 hand-labelled videos, ≥90% of key frames land within 0.3 s of the labels, and the repetition/section count is exact. `make check-1`.
- **Isolated demo:** video scrubber with the found key frames marked.
- **Integrated demo:** Part 4 animates between these key frames.

### Part 2 — Images to 3D models

- **Input:** video frames. Two modes: a **one-person** recording (trainer or single follower) and a **multi-person class** recording.
- **Output:** `pose3d.json` for every tracked person; in multi-person mode also `tracks.json` (stable ID per person from **SAM 3.1** multi-object tracking; 3D from **SAM 3D Body**).
- **Done when:** one-person — on 20 hand-clicked frames including side views, 3D joints reproject within 5% of body height. Multi-person — on a class clip with ≥5 people, each person is tracked on ≥95% of frames with ≤1 ID swap per minute, and each has a `pose3d` stream. `make check-2`.
- **Isolated demo:** a photo beside its rotatable 3D skeleton; a class clip with coloured, stable per-person skeletons.
- **Integrated demo:** Parts 3–5 consume its `pose3d.json` unchanged.

### Part 3 — Align 3D model / skeleton consistency

- **Input:** `pose3d.json` (Part 2, any camera angle).
- **Output:** `skeleton.json` — the same motion with one fixed set of bone lengths, rotated to a standard facing, scaled to standard limb lengths, and no left/right label flips.
- **Done when:** bone-length variation <2% across a clip; zero left/right flips; the same movement filmed from 4 synced phones produces skeletons whose joint angles agree within 10°. `make check-3`.
- **Isolated demo:** the 4 phone views going in, the 4 aligned skeletons overlapping.
- **Integrated demo:** Part 4 and Part 5 only ever see `skeleton.json`, so camera angle is already removed for them. (This is the "any angle" claim.)

### Part 4 — Animate 3D models between key frames

- **Input:** `skeleton.json` sampled at Part 1's key frames.
- **Output:** `animation.json` — a smooth 30 fps 3D animation of the expected movement.
- **Done when:** with some in-between frames hidden, the animation rebuilds them within 8° per joint; bone lengths stay fixed throughout. `make check-4`.
- **Isolated demo:** the expected movement playing as a 3D animation you can orbit.
- **Integrated demo:** this animation is the reference Part 5 compares followers against, and what Part 6 plays back.

### Part 5 — Compare 3D animations and analyse faults

- **Input:** the expected `animation.json` (or its `skeleton.json`) and a follower's `skeleton.json`.
- **Output:** `analysis.json` — for each fault: what differed, the joint/body part, the size of the difference, and a plain-words line (e.g. "left foot too far out", "elbows wider than the example"). The rule maths in `tools/measures.py` is the reference for the measurements.
- **Done when:** on labelled follower clips (correct and deliberate-fault takes, several angles), faults are found with precision ≥0.85 and recall ≥0.75 in good light, every other angle reported separately; on correct takes it reports no faults. `make check-5`.
- **Isolated demo:** a follower clip replayed with each fault listed and the joint highlighted.
- **Integrated demo:** in Part 7, this analysis is what the follower is shown after a take.

### Part 6 — Video recording / playback app

- **Input:** the phone camera (record) and the catalog (play back).
- **Output:** a catalog of expected movements: each entry is a recorded video plus the `keyframes.json`, `skeleton.json` and `animation.json` Parts 1–4 produced from it, with a name a trainer can find again.
- **Done when:** record a movement, and it appears in the catalog with its animation; play an entry back at full and half speed with play/pause/scrub, on a phone browser. `make check-6`.
- **Isolated demo:** record 10 seconds, find it in the catalog, play its 3D animation.
- **Integrated demo:** Part 7 opens on this catalog ("pick a movement, then follow it").

### Part 7 — Stitching into one app

- **Input:** Parts 1–6.
- **Output:** the Simon app: pick (or record) an expected movement from the catalog → watch its animation → perform it to camera → get the Part 5 fault analysis.
- **Done when:** end to end on a movement the app has never been hand-configured for: record it in Part 6, follow it, and the faults reported match running Parts 2–5 on the same recorded follower clip directly. `make check-7`.
- **Isolated demo:** n/a — this part *is* the integrated demo.
- **Integrated demo:** the submission demo: one take records an exercise, a follower is analysed against it.

## Order of work

Parts 1–5 can be built in parallel against fixtures from day 1. Part 6 needs only the file formats. Part 7 is last. Scope questions go on the part's issue; scope changes need Mo or the team to say so on #27 or #1 — agents do not widen scope on their own.
