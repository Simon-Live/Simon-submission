# Output fixtures (for Parts 3–5)

Real Part 2 output so the next parts can start before Part 2 is finished. Same shape as the
shared files in the top-level README; nothing else is needed to read them.

## `single/` — one-person clip (provisional)

- `pose3d.json`: 107 frames (15 fps resample of a 7.1 s clip), one person (`id` 0), two
  barbell back squats. Canonical frame per frame: origin at the hip midpoint, x = subject's left,
  y = up, z = anterior, metres.
- `camera.json`: sidecar to project joints back to the 1280×720 video (`p_cam = R·p + t`, then `K`).
  Parts 3–5 don't need it.
- Source clip: "Squat - exercise demonstration video" by FitnessScape, CC BY 3.0,
  <https://commons.wikimedia.org/wiki/File:Squat_-_exercise_demonstration_video.webm>
  (derived pose data only; the video itself is not in this repo).
- Produced by `part2 run --mode single --fps 15` with SAM 3D Body on the HPC cluster (V100), commit of
  `part2/` at the time of this PR; no smoothing.

**Read with care:**
- `conf` is **not** a calibrated confidence: 1.0 when the model placed the joint inside the
  image, 0.3 when it extrapolated the joint outside the frame. Occluded-but-in-frame joints are 1.0.
- "Up" is the camera's up (a level camera is assumed); a tilted camera tilts every pose.
- Provisional: the real one-person fixture comes from the project footage (#5) once chosen.

## `class/`: multi-person, the scored clip (`tracks.json` + `pose3d.json` + `camera.json`)

- 89 frames (5 fps, 17.6 s), 7 people, ids 0–6, all present in every frame. Yoga class doing cat–cow on mats.
- These are the exact outputs `make check-2` scored on `f47e03f`: multi-person **pass**, coverage 1.0
  against the hand-verified ID keyframes, 0 ID swaps.
- Source clip: "People Doing the Cat Cow Pose in a Yoga Class" by Yan Krukau, Pexels video 8480627,
  Pexels licence (see `fixtures/input/class/SOURCE.md`).
- Produced by `make hpc-outputs`: SAM 3.1 tracking via the Meta API, then SAM 3D Body per tracked box on
  the HPC cluster (V100).

## `dance/`: multi-person stress test (`tracks.json` + `pose3d.json` + `camera.json`)

- 79 frames (5 fps, 15.5 s), 5 ids over the clip, 3–5 people per frame. Dancers cross and swap places;
  the camera pans; ids 0 and 2 leave on the left and id 4 enters around frame 26.
- No ground truth: this is a qualitative demo, not done-check evidence. IDs hold through the
  crossings. 3D is reliable for fully visible dancers (id 3: hip centre inside its own box in 79/79
  frames) and unreliable for dancers cut off by the frame edge or hidden behind someone
  (67/289 person-frames have the hip centre outside the person's own box). Around frame 40 the
  entering dancer's skeleton lands on the striped-shirt dancer.
- Source clip: "Women Dancing All Together", Pexels video 8956007, Pexels licence.
- Produced like `class/` (HPC job 2513739).

`conf` in both means the same as in `single/` (above): 1.0 when the joint lies inside the image, 0.3 when
it was extrapolated outside the frame. It is not a calibrated probability.
