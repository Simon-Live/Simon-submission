# Input fixture: Part 2 one-person squat (`pose3d.json`)

- **What:** Part 2's provisional one-person output, copied unchanged from
  `moalborati/simon-part-2-images-to-3d` `fixtures/output/single/pose3d.json` at commit
  `836e9647d20c1befd70be61958b0e366b8d358f9` (2026-10-26). SHA-256 of this file:
  `433ae2edfe61b7e5c027f06ccdea289df34741225829f45fb5a652bb5147d857`.
- **Content:** 107 frames at 15 fps (7.07 s), one person (`id` 0), two barbell back squats.
  Shape `{frames: [{frame, t_ms, people: [{id, joints: {<17 joints>: {x, y, z, conf}}}]}]}`, per-frame
  body frame: origin at the hip midpoint, x = subject's left, y = up, z = anterior, metres.
- **Source clip:** "Squat - exercise demonstration video" by FitnessScape, CC BY 3.0,
  <https://commons.wikimedia.org/wiki/File:Squat_-_exercise_demonstration_video.webm>.
  This file is derived pose data only; the video is not in this repo.
- **Read with care (from Part 2):** `conf` is not calibrated. It is 1.0 when the joint was inside the
  image and 0.3 when the model extrapolated it outside the frame. `right_ankle` is 0.3 in every frame
  and `left_ankle` in 19 frames. "Up" is the camera's up, so a tilted camera tilts every pose.
- **Provisional:** Part 2 will replace this with project footage; refresh the copy when it does.
