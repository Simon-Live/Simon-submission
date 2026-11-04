# Conformance kit

Golden input and output pairs for every profile, view and input adapter of Part 3, and follower takes for Part 5.
A neighbour can run its reader or writer against these files without running Part 3.

`make check-3-contract` validates every file here against `contracts/`, rebuilds the kit through
`python3 -m part3 run` into a temp folder, compares bytes, and checks every labelled fault is still visible in
Part 3's output. It prints one metrics JSON and exits 0 only when all of it passes. `python3 -m part3.conformance
build` regenerates the kit.

## Layout

| Path | Holds |
|---|---|
| `cases.json` | `[{id, input, args, outputs}]`. `input` is a repo path. `args` are the options after `run --in <input> --out <out>`; the value of `--keyframes-out` is a file name inside the case folder. |
| `inputs/` | Input variants of the real Part 2 squat (`fixtures/input/part2-single/pose3d.json`, referenced, not copied) and the option files the cases read. |
| `golden/<case id>/` | The outputs of a case, named in `outputs`. |
| `followers/labels.json` | Labels of the follower takes (`simon.part3.follower_labels/1`). |
| `followers/<take id>/` | `input/pose3d.json` (what Part 2 would send), `skeleton.json` (the `part5` view, what Part 5 reads), `skeleton.native.json` (the native view). |

Inputs: `pose3d.arrays.json` (joints as `[x, y, z, conf]`), `pose3d.joint-list.json` (joints as a list of 17),
`pose3d.extra-joints.json` (extra joint names), `pose3d.no-t_ms.json` (no `t_ms`, top-level `fps`), `pose3d.flat.json`
(joints on the frame, no `frame` number), `pose3d.two-people.json` (a second person with the string id `guest` in 87
of 107 frames), `keyframes.part1.json` (Part 1's shape, 60 fps video clock, two repetitions found from the squat's hip
height; the `video` name is a placeholder, no video is in the repo), `keyframes.part4.json` (`simon.keyframes.v1`, 30
fps), `profile.example.json` (`simon.body_profile/1`, a 1.62 m body).

## Follower takes

The real squat with one fault applied in the body frame, rendered from a camera at `front` (0 degrees), `45` and
`side` (90) with the synthetic set's Part 2 like errors (`part3/synth.py`, `part3/followers.py`). Each angle has a
`correct` take and four fault takes. Bone lengths are exact in every take; a fault never changes a length.

| Fault | Applied | `measure` read on Part 3's output |
|---|---|---|
| `feet_wide` | both ankles 0.10 m further out | lateral ankle position, metres |
| `elbows_out` | both upper arms 20 degrees further out, forearms follow | upper arm abduction in the frontal plane, degrees |
| `shallow_squat` | knee angle 25 degrees larger at the bottom, growing with squat depth | knee interior angle, degrees |
| `knee_caving` | one knee turned 12 degrees inward at the bottom (left at `front` and `side`, right at `45`) | thigh turn about the vertical axis, degrees |

`measured_in_output` in a label is the size measured on the native output against the correct take at the same
angle, on the labelled side or the mean of both. It is in the unit of the applied size (`magnitude_m` or
`magnitude_deg`). A fault counts as visible when each labelled side measures 0.5 to 1.5 times the applied size and an
unlabelled side stays under half of it. A correct take stays under half of every applied size against the native
output of the real squat (`golden/default/skeleton.json`).

Label paths (`follower`, `input`) are relative to this folder.
