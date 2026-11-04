# Expected clips: copied from Part 4's shipped output

`<set>/animation.json` are byte-for-byte copies of Part 4's output fixtures
(`moalborati/simon-part-4-animate-keyframes`, `fixtures/output/<set>/animation.json`, **commit
`dc3d9f2e70a0d3e95efb60bea1e5ab7fc307d284`**, Part 4 `main` when refreshed for M2, TICKET-016).
Only the shared file is used; no Part 4 code. The same commit is `upstreams.part4.commit` in
`contracts/sources.lock.json`, and the three copies are the `pinned` entries of
`contracts/sources.json`: `python3 scripts/sync_contracts.py --check --part4 <checkout>` reports no
difference for them while Part 4's files are unchanged.

| set | movement | frames | fps | used for |
| --- | --- | ---: | ---: | --- |
| exercise | squat | 91 | 30 | every exercise follower take (seed 5 and held-out) |
| dance | step_touch | 121 | 30 | every dance follower take (seed 5 and held-out) |
| part3-squat | unnamed in the file | 213 | 30 | Part 3's follower kit (real-take report) and the guard's matched reference; no generated take |

Format `simon.animation.v1`: top level `format, fps, duration_s, frame_count, movement, set,
coordinate_frame, joints[17], bones[15], frames[]`; each frame
`{index, t, interpolated, joints: {name: [x, y, z]}}` in metres, hip midpoint at the origin,
x = subject's left, y = up, z = anterior.

Refresh rule (`docs/specs/calibration.md`): these clips were refreshed once, before the seed 5 tuning
set was regenerated and before any threshold was tuned. They are never refreshed again after a
held-out seed has been scored, because every tuned threshold and every guard limit depends on them.
Replacing them means regenerating seed 5 (`make dummy-data`) and retuning, in that order.
