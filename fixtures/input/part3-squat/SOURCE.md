# Input fixture: Part 3's `--view part4` output (`part3-squat`)

- **What:** `skeleton.json` and `keyframes.json` exactly as Part 3 wrote them. Neither file was
  edited.
- **Producer:** `moalborati/simon-part-3-skeleton-consistency` at commit
  `6d339d5c6671ffb4796e96718c02c95a35faa286`, run inside a read-only clone of that repo:

  ```bash
  python3 -m part3 run --in fixtures/input/part2-single/pose3d.json \
    --out <this dir>/skeleton.json --view part4 --body part4-rig \
    --keyframes fixtures/conformance/inputs/keyframes.part1.json \
    --keyframes-out <this dir>/keyframes.json
  ```

  `make part3-squat PART3=<path to a Part 3 clone>` runs the same command and rebuilds
  `fixtures/output/part3-squat/animation.json`. Two runs gave identical bytes.
- **Inputs to Part 3:** Part 2's one-person squat (`pose3d.json`, 107 frames at 15 fps, SHA-256
  `433ae2edfe61b7e5c027f06ccdea289df34741225829f45fb5a652bb5147d857`) and a keyframes file in Part
  1's shape (two squats, start, bottom and top on a 60 fps video clock, SHA-256
  `9e39749a1f6d39bb26f0652fa53b90e45ef8e40e411c9bce7ddfa089696b6c84`). Part 3 mapped those keys to
  30 fps indices 38, 70, 100, 130, 162 and 192 of a 213-frame clip.
- **Outputs (SHA-256):** `skeleton.json`
  `032e823fea08d452172594e421abc42d3c0651bdf8ed7b2eb9efd73cf5a7f86e`, `keyframes.json`
  `f64dcc50e59d447226ae7773d52a68b024be8afe7b819cea1b4596336e183137`.
- **Checked by `make check-4`:** key poses within 1 mm, bone lengths within 1 mm of
  `rest_offsets_m`, hip midpoint at the origin, `interpolated` flags, the shipped `animation.json`
  against a rebuild, and both files against `contracts/`. There is no held-out answer key for this
  clip. The check also reports, without a threshold, the angle between the clip and Part 3's own
  per-frame poses between the keys (`part3_frames_max_angle_deg`). Six keys over two squats leave
  long gaps, and Part 3's frames are not posed on this rig (`rig.fit`), so that number is not held
  to 8°.
- **Read with care:** Part 3's `keyframes.json` carries no `movement`, so the clip's `movement` is
  `null`. Frames 0 to 37 and 193 to 212 hold the first and last key pose.
