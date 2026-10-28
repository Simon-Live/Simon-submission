# Part 3 integration contract

Part 3 turns a Part 2 `pose3d.json` into a `skeleton.json` with one fixed set of bone lengths, a standard facing and no left/right flips. This page is what Parts 2, 4, 5 and 7 need to plug into it without reading its code. Every file Part 3 reads or writes has a JSON Schema in `contracts/`, and two commands check a file for you.

## Check a file now

```
python3 -m part3 contract                    # the schemas and the compatibility table
python3 -m part3 contract --schema skeleton  # one schema, exactly as stored
python3 -m part3 doctor skeleton.json --for part5
```

`doctor` names the file's kind and version, validates it, and says for each consumer whether it accepts the file. A consumer that would reject it comes with the field and the option that fixes it:

```
$ python3 -m part3 doctor skeleton.json --for part5
file: skeleton.json
kind: native (Part 3 skeleton.json, native), version simon.skeleton/1
valid: yes
note: body profile simon-standard (selected by default)
Part 3 accepts: a skeleton.json is also a valid pose3d.json
Part 4 would reject: no "format" and no keyframes[] (Part 4 reads simon.skeleton.v1); fix: python3 -m part3 run ... --view part4 --keyframes <keyframes.json>
Part 5 would reject: no "format"; fix: python3 -m part3 run ... --view part5
```

Exit codes of `doctor`: 0 the file is a known kind and valid, 1 it is valid but the consumer named by `--for` would reject it, 2 it cannot be read, is not JSON, is of an unknown kind or is invalid. A message is one plain line that names the field. `--json` prints the same report as JSON.

## Files and schemas

Each schema is a JSON Schema draft 2020-12 document with `$id`, `title`, `x-simon-version`, `x-direction` (input, output or both), `x-producer` and `x-consumers`. Any JSON Schema validator reads them. Part 3 checks them with a small validator in the standard library (`part3/jsonschema_lite.py`), so you do not need a package.

<!-- schema-table:begin -->
| Name | Version | Direction | File | Producer | Consumers |
|---|---|---|---|---|---|
| `animation-part5` | `simon.animation.v1` | output | `contracts/animation-part5.schema.json` | Part 3 or Part 4 | Part 5, Part 6 |
| `body-profile` | `simon.body_profile/1` | input | `contracts/body-profile.schema.json` | you (any team) | Part 3 |
| `follower-labels` | `simon.part3.follower_labels/1` | output | `contracts/follower-labels.schema.json` | Part 3 | Part 5 |
| `keyframes-part1` | `part1.keyframes/2026-10-28` | input | `contracts/keyframes-part1.schema.json` | Part 1 | Part 3 |
| `keyframes-part4` | `simon.keyframes.v1` | both | `contracts/keyframes-part4.schema.json` | Part 4 or Part 3 (--keyframes-out) | Part 3, Part 4 |
| `people-index` | `simon.part3.people/1` | output | `contracts/people-index.schema.json` | Part 3 | callers of --all-people |
| `pose3d` | `part2.pose3d/2026-10-28` | input | `contracts/pose3d.schema.json` | Part 2 | Part 3 |
| `skeleton` | `simon.skeleton/1` | output | `contracts/skeleton.schema.json` | Part 3 | Part 3 (as pose3d input), Part 7 |
| `skeleton-part4` | `simon.skeleton.v1` | output | `contracts/skeleton-part4.schema.json` | Part 3 | Part 4, Part 5 |
<!-- schema-table:end -->

A schema cannot say everything. For the `part4` view, key order, key times equal to `index / 30`, forward kinematics that reproduce each key, the 180 degree rule between neighbouring keys and the `keyframes.json` beside the file are checked by `python3 -m part3 doctor <skeleton.json> --for part4`. A rule `doctor` cannot check counts as a rejection. Part 3's own validator (`python3 -m part3.schema <skeleton.json>`) checks the native skeleton only: rounding, bone lengths against the profile and frame counts. `doctor` also checks that every frame keeps the bone lengths of the file within 2%.

`doctor` names a `simon.skeleton.v1` file that Part 3 did not write (Part 4's own fixtures have no native `frames` or `input` block) as `simon.skeleton.v1 (not written by Part 3)` and still gives the Part 4 and Part 5 verdicts for it.

## Compatibility

Which producer file works with which consumer, as checked against the neighbour commits named in the evidence column. `works` needs no option. `works with option` needs the option shown. `rejected` names the option that makes the file acceptable. The consumer version is the commit the row was checked against; for Part 3 it is `part3 phase 2`.

<!-- compatibility-table:begin -->
| Producer | File | Version | Consumer | Consumer version | Result | Option | Evidence |
|---|---|---|---|---|---|---|---|
| Part 2 | pose3d.json | `part2.pose3d/2026-10-28` | Part 3 | part3 phase 2 | works |  | Part 2 7e11a7f README 'Shared-file context'; fixtures/input/part2-single/pose3d.json is the make check-3 input |
| Part 2 | pose3d.json with several people per frame | `part2.pose3d/2026-10-28` | Part 3 | part3 phase 2 | works with option | `--person <id> or --all-people` | Part 2 7e11a7f README 'Output': pose3d.json per tracked person; without an option Part 3 keeps the id seen in most frames |
| Part 2 | pose3d.json without t_ms | `part2.pose3d/2026-10-28` | Part 3 | part3 phase 2 | works with option | `--input-fps <n>` | adapter derive-t_ms; a top-level fps in the file does the same; Part 2 7e11a7f writes t_ms, so this covers hand-made files |
| Part 2 | pose3d.json with joints as arrays | `part2.pose3d/2026-10-28` | Part 3 | part3 phase 2 | works |  | adapter joint-arrays; the adapters that fired are listed in input.adapters of the output |
| Part 1 | keyframes.json | `part1.keyframes/2026-10-28` | Part 3 | part3 phase 2 | works with option | `--view part4 --keyframes <keyframes.json>` | Part 1 775aa1e contracts/keyframes.schema.json and keyframes.example.json: format simon.keyframes/part1, people[].repetitions[].keyframes[] name, frame, t_ms on the video clock (files without format, as up to 2108c7c, read the same); Part 3 maps them onto the 30 fps index by time |
| Part 4 | keyframes.json | `simon.keyframes.v1` | Part 3 | part3 phase 2 | works |  | Part 4 9f4c073 fixtures/input/exercise/keyframes.json; pass it to --keyframes and the kind is detected; its fps must be 30 |
| Part 3 | skeleton.json (native) | `simon.skeleton/1` | Part 4 | 9f4c073 | rejected | `--view part4 --keyframes <keyframes.json>` | Part 4 9f4c073 README 'The file is rejected': no keyframes[], no rest_offsets_m, no local_rotations |
| Part 3 | skeleton.json (part4 view) | `simon.skeleton.v1` | Part 4 | 9f4c073 | works | `none (--view part4 uses --body part4-rig unless a body is named)` | Part 4 9f4c073 README 'Edge cases': fps 30, key t = index / 30 within 1 microsecond, FK within 1 mm; rig.fit reports the residual of snapping key poses to the rig; Part 4's own animator on this view (local neighbour check, 2026-10-28): key error 0.0 m, bone deviation 0.0000013 m. Condition (README 'The file is rejected'): works when no joint turns more than 180 degrees between neighbouring keys in rotation-vector space; Part 3's part4 view refuses to write a clip that breaks this and names the joint and the keys, and the arms rest in a T-pose so an arm overhead or hanging stays 90 degrees from rest |
| Part 3 | keyframes.json (written by --keyframes-out) | `simon.keyframes.v1` | Part 4 | 9f4c073 | works | `--keyframes-out <path>` | Part 4 9f4c073 README 'What goes in': keyframes.json sits beside skeleton.json and lists the same key indices |
| Part 3 | skeleton.json (native) | `simon.skeleton/1` | Part 5 | c292a15 | rejected | `--view part5` | Part 5 c292a15 part5/io.py parse_clip: a file without format is rejected |
| Part 3 | skeleton.json (part5 view) | `simon.animation.v1` | Part 5 (follower clip) | c292a15 | works |  | Part 5 c292a15 docs/schemas.md 'Follower clip': assumes the simon.animation.v1 shape (open decision 1 in its #18) |
| Part 3 | skeleton.json (part4 view) | `simon.skeleton.v1` | Part 5 (expected clip) | c292a15 | works |  | Part 5 c292a15 docs/schemas.md 'Expected skeleton alternative': keyframes[] with joints as [x, y, z], extra fields ignored |
| Part 3 | skeleton.json (part5 view) | `simon.animation.v1` | Part 6 | 59f923f | works |  | Part 6 59f923f part6/formats.py read_animation: fps must be a number above 0 (E5) and each frame's t is read as given; the part5 view always writes fps, so python3 -m part6 doctor and import accept the golden view-part5 file and every follower skeleton.json |
| Part 3 | skeleton.json (native) | `simon.skeleton/1` | Part 3 (as pose3d.json) | part3 phase 2 | works |  | frames keeps the pose3d.json shape and unknown keys are ignored, so a skeleton.json is a valid input |
| Part 3 | command line and files | `python3 -m part3 run` | Part 7 | 90aa473 | works |  | Part 7 90aa473 consumes parts through files and commands; exit 0 written, 1 not writable, 2 input or option breaks the contract |
<!-- compatibility-table:end -->

The same rows are in `contracts/compatibility.json` and in the output of `python3 -m part3 contract`.

## Coordinate frame and units

- Origin: the hip midpoint of each frame. Positions are metres. Angles are degrees.
- `x` is the subject's own left, `y` is up, `z` is `x` cross `y` and points to the front of the body (anterior).
- Native `skeleton.json` names `y` as `body_up`: Part 3 takes up from the body (feet to shoulders over standing frames). A clip with fewer than 5 standing frames, such as floor work or a seated stretch, uses Part 2's own `y` (world up for a level camera) and says `up_source: input_up`; `PART3_UP_FALLBACK=all_frames` uses the mean feet-to-shoulders line over every frame instead. The `part4` and `part5` views name it `world_up` in `coordinate_frame`, which is what Part 4 and Part 5 expect. The numbers are the same.
- Times: `t_ms` in the native file is milliseconds on the input clock. `t` in the views is seconds.
- Left and right are the subject's, not the viewer's.

## The 17 joints

In this order: `nose`, `left_eye`, `right_eye`, `left_ear`, `right_ear`, `left_shoulder`, `right_shoulder`, `left_elbow`, `right_elbow`, `left_wrist`, `right_wrist`, `left_hip`, `right_hip`, `left_knee`, `right_knee`, `left_ankle`, `right_ankle`.

## The 18 bones

`root` is the hip midpoint and `neck` is the shoulder midpoint. Lengths are the default profile `simon-standard` (stature 1.70 m). Another profile changes the lengths and nothing else.

| # | Name | From | To | Length (m) |
|---|---|---|---|---|
| 1 | `left_pelvis` | `root` | `left_hip` | 0.1250 |
| 2 | `right_pelvis` | `root` | `right_hip` | 0.1250 |
| 3 | `left_thigh` | `left_hip` | `left_knee` | 0.4165 |
| 4 | `right_thigh` | `right_hip` | `right_knee` | 0.4165 |
| 5 | `left_shank` | `left_knee` | `left_ankle` | 0.4182 |
| 6 | `right_shank` | `right_knee` | `right_ankle` | 0.4182 |
| 7 | `spine` | `root` | `neck` | 0.4896 |
| 8 | `left_clavicle` | `neck` | `left_shoulder` | 0.1979 |
| 9 | `right_clavicle` | `neck` | `right_shoulder` | 0.1979 |
| 10 | `left_upper_arm` | `left_shoulder` | `left_elbow` | 0.3162 |
| 11 | `right_upper_arm` | `right_shoulder` | `right_elbow` | 0.3162 |
| 12 | `left_forearm` | `left_elbow` | `left_wrist` | 0.2482 |
| 13 | `right_forearm` | `right_elbow` | `right_wrist` | 0.2482 |
| 14 | `head` | `neck` | `nose` | 0.1907 |
| 15 | `left_eye_link` | `nose` | `left_eye` | 0.0618 |
| 16 | `right_eye_link` | `nose` | `right_eye` | 0.0618 |
| 17 | `left_ear_link` | `left_eye` | `left_ear` | 0.0774 |
| 18 | `right_ear_link` | `right_eye` | `right_ear` | 0.0774 |

## The command line

```
python3 -m part3 run --in <pose3d.json> --out <path> [--flip auto|on|off]
    [--body simon-standard|part4-rig|measured|file:<path>] [--stature <m>] [--config <part3.toml>]
    [--view native|part4|part5] [--keyframes <keyframes.json>|every:<n>] [--keyframes-person <id>]
    [--keyframes-out <path>] [--fps <n>] [--input-fps <n>] [--person <id> | --all-people]
python3 -m part3 contract [--json] [--schema <name>]
python3 -m part3 doctor <file> [--for part3|part4|part5] [--json]
```

| Option | What it does | Default |
|---|---|---|
| `--in` | The `pose3d.json` to read. Looser shapes are accepted through input adapters (see below). | required |
| `--out` | The file to write. With `--all-people` it is a folder. | required |
| `--flip` | Mirror correction for selfie recordings: `auto` reads `mirrored` in the input, `on` and `off` force it. | `auto` |
| `--body` | The body profile: `simon-standard`, `part4-rig`, `measured` or `file:<path>`. | `part4-rig` with `--view part4`, `simon-standard` otherwise |
| `--stature` | Scales every bone length to this stature, 0.5 to 2.5 m. | none |
| `--config` | A `part3.toml` file. Without it Part 3 reads `PART3_CONFIG`, then `./part3.toml` when it exists. | none |
| `--view` | The output shape: `native`, `part4` or `part5`. | `native` |
| `--keyframes` | Needed by `--view part4`. A Part 1 `keyframes.json`, a Part 4 `simon.keyframes.v1` file, or `every:<n>` (n from 1 to 300). | none |
| `--keyframes-person` | Which person of a Part 1 file supplies the keys. | the first listed |
| `--keyframes-out` | Writes the `simon.keyframes.v1` file Part 4 reads beside `skeleton.json`. It must name a different file from `--out`. | not written |
| `--fps` | Resamples to a uniform grid, 1 to 240 frames per second, keeping the source clock. | no resampling |
| `--input-fps` | Frame rate for a file whose frames carry no `t_ms`. A top-level `fps` in the file does the same. | none |
| `--person` | Keeps the person with this id. An absent id exits 2 and lists the ids present. | the id seen in most frames |
| `--all-people` | Writes `<out>/person-<slug>/skeleton.json` for every id and `<out>/people.json`. The slug is the id, or `p<k>` by position when the id has characters other than letters, digits, `_` and `-`. Excludes `--person`. | off |

Exit codes of `run`: 0 written, 2 the input or an option breaks the contract (the message names the field or the option and nothing is written), 1 the output is not writable.

Input adapters run before validation, in this order. `flat-joints` wraps a frame with `joints` and no `people` as person 0. `joint-arrays` turns `[x, y, z]` or `[x, y, z, conf]` joints into objects. `extra-joints` drops joint names outside the canonical 17. `frame-index` numbers frames that have no `frame`. `derive-t_ms` computes `t_ms` from `--input-fps` or a top-level `fps`. The adapters that fired are listed in `input.adapters` of the output. Extra keys are ignored everywhere.

## Body profile selection

A profile is a name, a stature and the 18 bone lengths, with the source of the numbers. The output records the profile, its numbers and the channel that chose it (`body.selected_by`). When no channel names a body, the view chooses it and `body.reason` says why.

The first channel that is set wins:

1. the command line flag `--body`
2. the environment variable `PART3_BODY`
3. the config file (`[body] profile = "..."` in `part3.toml`)
4. the `body=` parameter of the Python API
5. the default of the view: `part4-rig` for `--view part4`, because Part 4's animator rejects bone lengths more than 1 mm off its rig, and `simon-standard` for every other view

Stature follows the same order: `--stature`, `PART3_STATURE`, `stature` in the config file, the `stature=` parameter, none. A `file:` profile is a JSON file that validates against `contracts/body-profile.schema.json`. `left_pelvis` must equal `right_pelvis` and `left_clavicle` must equal `right_clavicle`, so the hip and shoulder midpoints stay put. An unknown name, a stature out of range or a bad profile file exits 2 and names the channel and the field.

## Output views

- `native`: `simon.skeleton/1`, the full record of the run.
- `part4`: the native document plus what Part 4 reads. `format` is `simon.skeleton.v1` and `fps` is 30, the rate of its timeline (key `t` is `index / fps`). It adds `rest_offsets_m`, a 30 fps `timeline` and `keyframes[]` with `joints` as `[x, y, z]`, `conf` and `local_rotations` (quaternions `x, y, z, w`, 19 per key). It needs `--keyframes`. A key that falls where the person is missing from the clip (the input frame nearest the key has no person) is left out and listed in `timeline.dropped`. Part 4 accepts the file when no joint turns more than 180 degrees between neighbouring keys in rotation-vector space (its README, "The file is rejected"). Part 3 checks this itself: the `part4` view refuses to write a clip that breaks it (exit 2) and says which joint and which keys. The arms rest in a T-pose (`rest_offsets_m` puts each elbow and wrist on the x axis), so an arm overhead and an arm hanging are both 90 degrees from rest. If a fast movement still breaks the rule, add keys between the two named keys (a smaller `every:<n>`) or use another view.
- `part5`: `simon.animation.v1` with `frames[]` that hold the person, `joints` as `[x, y, z]` lists and the hip midpoint at the origin. `fps` is always there, so Part 6 accepts the file: the `--fps` rate when resampled, otherwise 1000 over the median step between input frames (3 decimals), and 30 for a one-frame clip. When the input steps are not uniform, `fps` is the nominal rate and each frame's `t` stays the time of record.

One pipeline makes the native skeleton. The views are functions of it.

## Conformance kit and Part 5 fault names

`fixtures/conformance/followers/labels.json` uses Part 5's label field names (`type`, `measure`, `body_part`, `joints`, `side`, `direction`, `magnitude_deg` or `magnitude_m`, `text`) plus `measured_in_output`, the size Part 3's output still shows. The kit has its own fault types. Part 5's label file (`fixtures/input/followers/labels.json`, c292a15) has others. The table pairs each kit type with the closest Part 5 type and says how each side measures it:

| Part 3 kit `type` | Closest Part 5 `type` | How the kit measures it | How Part 5 measures it |
|---|---|---|---|
| `feet_wide` | `foot_out` | `ankle_lateral_offset`: how far the ankle sits to the side of the hip midpoint, in metres (`magnitude_m`). One label for both feet. | `thigh_direction`: how far the thigh points out from the body, in degrees (`magnitude_deg`). One label per side, at the hip. |
| `elbows_out` | `arms_wider` | `upper_arm_abduction`: the upper arm angle out from the body in the frontal plane, in degrees. One label for both shoulders. | `upper_arm_direction`: the upper arm direction out from the body, in degrees. One label per side, or `both`. |
| `shallow_squat` | `knees_shallow` | `knee_angle_at_bottom`: the knee interior angle at the bottom of each repetition, in degrees. It grows as the knee straightens. | `knee_flexion`: the knee bend, in degrees, with a `peak_deg`. It shrinks as the knee straightens. |
| `knee_caving` | none (Part 5 has no knee-valgus type) | `thigh_inward_turn_at_bottom`: the thigh turned inward about the vertical axis at the bottom, in degrees. One knee. | none |
| `correct` | a take with `correct: true` and no faults | none | none |

`elbows_out` and `arms_wider` are the closest match: both read how far the upper arm points out from the body, in degrees. `feet_wide` and `foot_out` do not match. One is a distance at the ankle in metres and the other is an angle at the thigh in degrees, so a size in one is not a size in the other. `shallow_squat` and `knees_shallow` both give a change in knee bend in degrees, but the kit reads the interior angle and Part 5 reads the bend (180 minus the interior angle).

Part 5 grades follower clips with its own measures. It does not read these labels. The labels are for a test to compare against. They say which fault each take carries and, in `measured_in_output`, how much of it Part 3's output still shows.

## Version policy

Each file carries its version in `schema` or `format`. A change that only adds fields keeps the version, so readers that ignore unknown keys keep working. A change that removes or renames a field bumps the version. Part 2's `pose3d.json` and Part 1's `keyframes.json` carry no version field, so their schemas carry a dated version (for example `part2.pose3d/2026-10-28`) that names the state Part 3 was checked against.

## Open question to Part 4

Part 4's rig moves the children of the pelvis, the neck and the nose rigidly. Part 3 keeps the direction of every bone, so the hip line, the spine and the head can bend against each other. No set of local rotations reproduces such a pose exactly. The `part4` view therefore snaps each key pose to the rig. Its `joints` are the forward kinematics of its `local_rotations`, so Part 4's 1 mm rule holds. `rig.fit` reports how far the snapped pose is from the native frame: `max_m`, `mean_m`, `worst_joint` and `worst_index`. On the Part 2 squat fixture with a key on every frame (`every:1`) the largest residual is 4.906 mm, the mean is 1.130 mm and the worst joint is `left_hip`.

A chest joint and a head joint in Part 4's rig, or per-key rest offsets, would remove the residual. Part 4 can decide that later. Nothing waits on it. The `part4` view uses `part4-rig` unless a body is named, so the bone lengths match Part 4's rig. Read `rig.fit` for the residual.

The `part4` view works under one condition: no joint turns more than 180 degrees between neighbouring keys in rotation-vector space, the rule in Part 4's README. Part 3 fits each key after the one before it: a shoulder or a hip takes the twist about its own bone that keeps its rotation and the elbow's or knee's closest to the previous key, so a bent elbow swinging behind the head keeps its axis (the twist moves no joint). A joint that still swings through a half turn between two keys can flip its rotation axis. The `part4` view then refuses to write the file and names the joint and the keys, for example `left_shoulder turns 329.6 degrees between keys 30 and 40`. Because the arms rest in a T-pose, an arm hanging and an arm overhead are both 90 degrees from rest. `doctor --for part4` applies the same rule to a file from any producer.

## How to integrate in five steps

1. Find your file in the compatibility table. The row says whether it works, needs an option, or is rejected and what fixes it.
2. Read the schema with `python3 -m part3 contract --schema <name>` and check your producer's output against it with any JSON Schema validator.
3. Run `python3 -m part3 doctor <your file> --for part3` (or `part4`, `part5`). Exit 0 means the consumer accepts it. Otherwise the message names the field and the option.
4. Run Part 3 with the options the table names, for example `python3 -m part3 run --in pose3d.json --out out/skeleton.json --view part4 --keyframes keyframes.json --keyframes-out out/keyframes.json` (the `part4` view picks the `part4-rig` body itself).
5. Run `doctor` on the output with `--for` set to the consumer, then hand the file over. If the contract needs to change, open an issue on `moalborati/simon-part-3-skeleton-consistency` that names the file kind and the field.

`make check-3-contract` rebuilds the golden files in `fixtures/conformance/` byte for byte and validates each against its schema, so a change that breaks a neighbour shows up there first.
