# Contract: `skeleton.json` (output, read by Parts 4 and 5) and the `make check-3` metrics JSON

> Copy of the maintainers' working spec `docs/specs/contract-skeleton-output.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Written by `python3 -m part3 run`. Validated by `python3 -m part3.schema` before every write.
`frames` keeps the `pose3d.json` shape exactly, so a `skeleton.json` is also a valid `pose3d.json`.

## Shape
```json
{
  "schema": "simon.skeleton/1",
  "units": {"length": "m", "angle": "deg", "time": "ms"},
  "frame": {"origin": "hip_midpoint", "x": "subject_left", "y": "body_up", "z": "anterior",
            "up_source": "standing_frames"},
  "joints": ["nose", "left_eye", "...", "right_ankle"],
  "bones": [{"name": "left_thigh", "from": "left_hip", "to": "left_knee"}],
  "standard": {"stature_m": 1.70, "sources": ["<the sources values of part3/standard_body.json>"]},
  "bone_lengths_m": {"left_thigh": 0.0},
  "person": {"id": 0, "rule": "most_frames", "candidates": {"0": 107},
             "frames_present": 107, "frames_dropped": 0, "few_frames": false,
             "measured_bone_lengths_m": {"left_thigh": 0.0},
             "flips_repaired_total": {"body": 0, "legs": 0, "arms": 0, "face": 0}},
  "mirror": {"setting": "auto", "applied": false, "reason": "auto: no mirrored key in input"},
  "input": {"sha256": "<hex of the pose3d.json bytes>"},
  "frames": [{"frame": 0, "t_ms": 0.0,
              "people": [{"id": 0,
                          "joints": {"nose": {"x": 0.0, "y": 0.0, "z": 0.0, "conf": 1.0}},
                          "flips_repaired": []}]}]
}
```
Zeros are placeholders for shape only; real values come from `part3/standard_body.json` and the run.

| Field | Rule |
|---|---|
| `schema` | exactly `simon.skeleton/1`; a breaking change bumps the number |
| `frame.up_source` | `standing_frames`, `two_footed_frames` (a one-legged clip: up from the frames with both feet down, TICKET-038), `input_up` (fewer than 5 standing frames: the input's +y, Part 2's world up) or `all_frames` (the same case with `PART3_UP_FALLBACK=all_frames`); spec step 5 |
| `joints` | the 17 canonical names in canonical order |
| `bones` | exactly the 18 bones in the table below, in that order; `root` and `neck` are virtual midpoints |
| `bone_lengths_m` | the one standard reference body, identical in every `skeleton.json` |
| `person` | the one person kept (spec step 2) with the rule, candidates and frame counts |
| `mirror` | the `--flip` setting, whether mirroring was applied, and why |
| `frames[]` | same `frame` and `t_ms` as the input, same order; `people` holds 0 or 1 entry |
| `frames[].people[].joints` | 17 joints, metres, 4 decimals; `conf` copied from the input joint |
| `frames[].people[].flips_repaired` | subset of `body`, `legs`, `arms`, `face`; empty when none |

## Bones (final names, order and lengths; shared with Part 6's consumer fixture)
`root` = hip midpoint, `neck` = shoulder midpoint. Lengths from `part3/standard_body.json` (stature
1.70 m, sources in `docs/design/specs/part3-skeleton.md` step 6).

| # | name | from | to | length (m) |
|---|---|---|---|---|
| 1 | left_pelvis | root | left_hip | 0.1250 |
| 2 | right_pelvis | root | right_hip | 0.1250 |
| 3 | left_thigh | left_hip | left_knee | 0.4165 |
| 4 | right_thigh | right_hip | right_knee | 0.4165 |
| 5 | left_shank | left_knee | left_ankle | 0.4182 |
| 6 | right_shank | right_knee | right_ankle | 0.4182 |
| 7 | spine | root | neck | 0.4896 |
| 8 | left_clavicle | neck | left_shoulder | 0.1979 |
| 9 | right_clavicle | neck | right_shoulder | 0.1979 |
| 10 | left_upper_arm | left_shoulder | left_elbow | 0.3162 |
| 11 | right_upper_arm | right_shoulder | right_elbow | 0.3162 |
| 12 | left_forearm | left_elbow | left_wrist | 0.2482 |
| 13 | right_forearm | right_elbow | right_wrist | 0.2482 |
| 14 | head | neck | nose | 0.1907 |
| 15 | left_eye_link | nose | left_eye | 0.0618 |
| 16 | right_eye_link | nose | right_eye | 0.0618 |
| 17 | left_ear_link | left_eye | left_ear | 0.0774 |
| 18 | right_ear_link | right_eye | right_ear | 0.0774 |

Invariants Parts 4 and 5 may rely on: bone lengths recomputed from `joints` equal `bone_lengths_m`
within rounding; up from the body, never the camera; left hip at positive x; face at positive z; no
frame has left and right swapped; one person.

## Metrics JSON printed by `make check-3` (field names final, 2026-10-27; `signal` text and `frame_map` set by the audit the same day)
```json
{
  "part": 3,
  "data_source": "synthetic",
  "data": {"real_clip": "fixtures/input/part2-single/pose3d.json",
           "takes": "fixtures/input/synthetic-4take/"},
  "alignment": {"method": "dtw", "reference_take": 1, "band_fraction": 0.25,
                "signal": "mean of 8 interior joint angles in degrees, 5-frame centred moving average",
                "frame_map": "middle paired frame, 3-frame centred mean, linear interpolation"},
  "angles": ["left_elbow", "right_elbow", "left_shoulder", "right_shoulder",
             "left_hip", "right_hip", "left_knee", "right_knee", "trunk_inclination"],
  "thresholds": {
    "bone_length_variation_max":     {"value": 0.0, "max": 0.02, "pass": true},
    "lr_flips":                      {"value": 0,   "max": 0,    "pass": true},
    "joint_angle_agreement_p95_deg": {"value": 0.0, "max": 10.0, "pass": true},
    "negative_control_p95_deg":      {"value": 0.0, "min_exclusive": 10.0, "pass": true}
  },
  "context": {"agreement_median_deg": 0.0, "agreement_mean_deg": 0.0, "agreement_max_deg": 0.0,
              "agreement_per_angle_p95_deg": {"left_elbow": 0.0},
              "agreement_linear_p95_deg": 0.0, "frames_compared": 0,
              "input_bone_length_variation_max": 0.0,
              "flips_injected": 27, "flips_repaired": 0, "real_clip_flips_detected_after_repair": 0,
              "up_error_max_deg": 0.0, "mirror_take_max_angle_diff_deg": 0.0},
  "pass": true
}
```
- `bone_length_variation_max`: max over clips, bones and frames of |L / bone_lengths_m - 1|; passes
  when below 0.02.
- `lr_flips`: frames whose labels disagree with truth on the synthetic takes, plus frames the detector
  still flags in the real clip's output; passes at 0.
- `joint_angle_agreement_p95_deg`: spec section "Phase alignment"; passes when at most 10.0.
- `negative_control_p95_deg`: passes when strictly above 10.0.
- `agreement_per_angle_p95_deg` holds all 9 angle names; `frames_compared` counts take-1 frames used.
- Printed with `indent=2`, numbers rounded to 3 decimals for printing only; pass and fail use the
  unrounded values. Also written to `out/check-3/metrics.json`.
- `pass` is true only when every threshold passes; the exit code is 0 exactly when `pass` is true.
- `data_source` for the agreement metric is always `synthetic` (the multi-angle set is a synthetic
  angle-invariance test; real input is one take at any angle, so no real multi-angle set will exist).
