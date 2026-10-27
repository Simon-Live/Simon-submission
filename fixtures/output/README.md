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

## `class/` — multi-person (`tracks.json` + `pose3d.json`)

Follows from #10/#11.
