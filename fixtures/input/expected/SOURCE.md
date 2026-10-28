# Expected clips: copied from Part 4's shipped output

`<set>/animation.json` are byte-for-byte copies of Part 4's output fixtures
(`moalborati/simon-part-4-animate-keyframes`, `fixtures/output/<set>/animation.json`, commit `366d628`).
Only the shared file is used; no Part 4 code.

| set | movement | frames | fps |
| --- | --- | ---: | ---: |
| exercise | squat | 91 | 30 |
| dance | step_touch | 121 | 30 |

Format `simon.animation.v1`: top level `format, fps, duration_s, frame_count, movement, set,
coordinate_frame, joints[17], bones[15], frames[]`; each frame
`{index, t, interpolated, joints: {name: [x, y, z]}}` in metres, hip midpoint at the origin,
x = subject's left, y = up, z = anterior. Replace these files when Part 4 ships a new version.
