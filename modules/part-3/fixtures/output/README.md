# Output fixtures: `skeleton.json` from Part 3

Parts 4 and 5 can build against these files before Part 3 runs on new footage. Each one is the exact output of `make run` on the input named below; `make test` checks that a rerun reproduces them byte for byte.

| File | Input (`fixtures/input/`) | Data | Input SHA-256 |
|---|---|---|---|
| `part2-single/skeleton.json` | `part2-single/pose3d.json` | real Part 2 output, one squat clip, 107 frames at 15 fps | `433ae2edfe61b7e5c027f06ccdea289df34741225829f45fb5a652bb5147d857` |
| `synthetic-4take/take-1/skeleton.json` | `synthetic-4take/take-1/pose3d.json` | synthetic take 1, camera azimuth 0 degrees, 113 frames at 15 fps | `881bc04962c717f5487a1e07dec7c611c0931f4e6696dcc1823f5500cf0d5284` |
| `synthetic-4take/take-2/skeleton.json` | `synthetic-4take/take-2/pose3d.json` | synthetic take 2, camera azimuth 45 degrees, 121 frames at 15 fps | `80f035962925fecfce5b20e9bd8707552d6320c3222c0b51bd55c715d8c4feee` |
| `synthetic-4take/take-3/skeleton.json` | `synthetic-4take/take-3/pose3d.json` | synthetic take 3, camera azimuth 90 degrees, 107 frames at 15 fps | `fe4ae60eae61f9b38645b639d044f015de0fc48a512de5c3ea833da90dc742b7` |
| `synthetic-4take/take-4/skeleton.json` | `synthetic-4take/take-4/pose3d.json` | synthetic take 4, camera azimuth 180 degrees, 121 frames at 15 fps | `5631b0898497e5f8af91872ef03c82649415416a61e31c50bf9d8ed7b3edf421` |

Regenerate one: `make run IN=fixtures/input/part2-single/pose3d.json OUT=fixtures/output/part2-single/skeleton.json`.

## Format

`skeleton.json` keeps the `pose3d.json` shape (`frames[].people[].joints.<name>.{x, y, z, conf}`), so a `pose3d.json` reader reads it. Added top-level keys:

| Key | Holds |
|---|---|
| `schema` | `simon.skeleton/1` |
| `frame` | origin hip midpoint, x subject's left, y body up, z anterior; `up_source` is `standing_frames` or `all_frames` |
| `joints`, `bones` | the 17 joint names and the 18 bones (`root` = hip midpoint, `neck` = shoulder midpoint) |
| `bone_lengths_m`, `standard` | the body the frames are built on (the default `simon-standard`, stature 1.70 m) and its sources |
| `body` | which body profile was used and who chose it: `profile`, `selected_by` (`flag`, `env`, `config`, `api` or `default`), `stature_m`, `scale`, `source`, `symmetrized`; `stature_selected_by` appears only when a stature was asked for |
| `person` | the person kept, the rule (`most_frames`, or `requested` with `--person`), candidates, frame counts, the performer's measured bone lengths, label flips repaired |
| `mirror` | the `--flip` setting, whether it was applied, and why |
| `input` | `sha256` of the input file; `adapters` names the input adapters that fired (`[]` for a canonical Part 2 file) |
| `resample` | only with `--fps`: the grid, the number of input frames and the method; each frame then also has `source` (its two bracketing input frames and the weight of the second) |

Per frame, `people` holds 0 or 1 entry; `flips_repaired` lists the label groups repaired in that frame (`body`, `legs`, `arms`, `face`).

## Invariants you can rely on

- Same frames and `t_ms` as the input, in the same order.
- Bone lengths recomputed from `joints` equal `bone_lengths_m` within rounding (4 decimals, 0.1 mm), in every frame of every file.
- `bone_lengths_m` is the chosen profile's in every frame of one file. With the default profile it is identical in every `skeleton.json`, so two recordings or two people compare joint by joint; compare files that name the same `body.profile`.
- Up comes from the body, never the camera; left hip at positive x; face at positive z.
- No frame has left and right swapped; one person per file.

## Limits

- With the default profile the bone lengths are the standard body's, not the performer's. The performer's are in `person.measured_bone_lengths_m`; `--body measured` builds on them.
- `conf` is copied from Part 2: 1.0 inside the image, 0.3 when Part 2 extrapolated the joint outside it. In the real clip `right_ankle` is 0.3 in every frame and `left_ankle` in 19 frames; their positions follow the input direction.
- A whole-body turn on the spot is not represented: Part 2 removes rotation per frame.
- A mirrored recording is corrected only with `--flip on` or a top-level `"mirrored": true` in the input.
- One fixed 5-frame mean removes per-frame jitter; nothing else smooths and timing is never changed.
- The `synthetic-4take` files are synthetic: the real Part 2 squat rendered from four camera angles with Part 2-like errors (`fixtures/input/synthetic-4take/SOURCE.md`). Real input is one take at any angle.
