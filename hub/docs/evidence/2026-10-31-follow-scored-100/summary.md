# Follow take 994306b52be0 vs rdl-d0fd491a: scored 100 / A with 0 faults

Part 5 d7df0de, Part 2 f1d0dc7 (Modal, serverless route), Part 7 serverless-modal 22d09a7. 300 expected frames at 30 fps, basis windows.

| measure | threshold | trainer min..max | follower min..max | max abs smoothed diff | frames over | longest run (s) |
|---|---|---|---|---|---|---|
| left_elbow_flexion | 20 | 6..26 | 6..20 | 13.3 | 0 | 0.0 |
| left_knee_flexion | 9 | 10..31 | 8..26 | 8.7 | 0 | 0.0 |
| left_upper_arm_out | 10 | -7..16 | -3..15 | 13.4 | 28 | 0.6 |
| left_upper_arm_forward | 15 | 4..76 | 3..51 | 25.7 | 28 | 0.9 |
| left_forearm_out | 17 | -17..8 | -9..9 | 12.0 | 0 | 0.0 |
| left_thigh_out | 13 | 4..10 | 4..9 | 3.2 | 0 | 0.0 |
| left_thigh_forward | 15 | 10..37 | 9..36 | 3.3 | 0 | 0.0 |
| left_foot_out | 6 | 3..8 | 3..8 | 3.2 | 0 | 0.0 |
| right_elbow_flexion | 20 | 13..28 | 10..20 | 14.5 | 0 | 0.0 |
| right_knee_flexion | 9 | 7..33 | 3..26 | 6.9 | 0 | 0.0 |
| right_upper_arm_out | 10 | -1..13 | 8..13 | 8.7 | 0 | 0.0 |
| right_upper_arm_forward | 15 | 10..72 | 12..55 | 17.0 | 10 | 0.3 |
| right_forearm_out | 17 | -14..-2 | -8..3 | 14.0 | 0 | 0.0 |
| right_thigh_out | 13 | -2..10 | -1..6 | 3.7 | 0 | 0.0 |
| right_thigh_forward | 15 | 8..36 | 7..36 | 4.1 | 0 | 0.0 |
| right_foot_out | 6 | -2..7 | -1..5 | 3.1 | 0 | 0.0 |
| trunk_lean_forward | 9 | -5..93 | -2..68 | 26.7 | 68 | 1.6 |
| trunk_lean_side | 9 | 1..155 | 2..8 | 149.1 | 28 | 0.9 |
| shoulder_tilt | 9 | -8..-0 | -4..-1 | 5.5 | 0 | 0.0 |
| head_forward | 18 | -8..51 | -19..36 | 21.0 | 40 | 1.2 |
| left_knee_valgus | 9 | -4..-0 | -2..0 | 1.9 | 0 | 0.0 |
| right_knee_valgus | 9 | -3..0 | -2..0 | 1.8 | 0 | 0.0 |

Persistence needed: max(min_frames_floor 8, round(min_fraction 0.38 x 300)) = 114 frames, in runs of at least 4.

Files: expected.json and follower.json (the Part 5 inputs as Part 7 passed them), analysis.json (Part 5's output), measures-per-frame.csv (every measure, trainer / follower / smoothed diff / over threshold, per expected frame), job.json, step-logs.txt.
