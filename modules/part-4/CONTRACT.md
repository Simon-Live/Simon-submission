# Part 4 contract

Check a file against Part 4's schemas before you send it or after you read it:

```bash
PYTHONPATH=src python3 -m simon_anim.contract validate skeleton  <dir>/skeleton.json
PYTHONPATH=src python3 -m simon_anim.contract validate keyframes <dir>/keyframes.json
PYTHONPATH=src python3 -m simon_anim.contract validate animation <dir>/animation.json
```

Each prints one line per broken field and exits 0 only when the file is valid. The tests check
every verdict against the `jsonschema` package (draft 2020-12) as well.

| File | Schema | Part 4 | Written by | Read by |
| --- | --- | --- | --- | --- |
| `keyframes.json` | [`contracts/keyframes.schema.json`](contracts/keyframes.schema.json) | reads | Part 3 (`--keyframes-out`) | Part 4 |
| `skeleton.json` | [`contracts/skeleton.schema.json`](contracts/skeleton.schema.json) | reads | Part 3 (`--view part4`) | Part 4 |
| `animation.json` | [`contracts/animation.schema.json`](contracts/animation.schema.json) | writes | Part 4 | Parts 5 and 6 |

The schemas are generated from `src/simon_anim/contract.py` (`make contracts`). `make check-4` fails
when a committed schema differs from that module or when any fixture breaks its schema. The
animator validates both inputs against the schemas before it reads them, so a file a schema rejects
is never animated. Rules a schema cannot state are listed under `x-rules` in each schema and are
enforced by `src/simon_anim/interpolate.py`.

## Units, frame and clock

| Item | Value |
| --- | --- |
| Positions | metres, `[x, y, z]` |
| Origin | hip midpoint, every frame |
| Axes | `x` the subject's left, `y` world up, `z` anterior (`z = x × y`) |
| Rotations | local quaternions `(x, y, z, w)`, normalized on read |
| Clock | 30 fps. Frame `index` runs from 0 to `frame_count - 1`, and `t = index / 30` seconds |
| Key times | `t` must equal `index / 30` within one microsecond |
| Clip length | `frame_count = round(duration_s × 30) + 1` |

## `animation.json` (`simon.animation.v1`)

Every object in this file is closed: a field the schema does not list is an error, so a new field
means a new format. Two exceptions joined v1. `producer` is a required constant (A-P4-06), because
Part 6 reads a declared producer and Parts 5 and 6 detect the file by `format`. `unseen_joints` and
`frames[].conf` are optional and additive: a reader that ignores them reads the file as before (see
"Visibility" below).

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | `"simon.animation.v1"` | the version |
| `producer` | `"part4"` | the part that wrote the file; always `part4` |
| `fps` | `30` | |
| `duration_s`, `frame_count` | number, integer | the clock above |
| `movement` | string or `null` | from `keyframes.json`, else `skeleton.json`, else `null` |
| `set` | string or `null` | from `keyframes.json`, else `skeleton.json`, else the `--set` name |
| `coordinate_frame` | object | the frame above, fixed |
| `joints` | 17 names | the canonical order in the README |
| `bones` | 15 objects | `name`, `parent`, `child`, `length_m`: the lengths every frame keeps within 1 mm |
| `unseen_joints` | list of joint names, optional | joints at or below conf 0.3 at every key frame, in canonical order. Present, possibly empty, exactly when frames carry `conf` |
| `frames[]` | objects | `index`, `t`, `interpolated`, `joints` (17 `[x, y, z]`), and optionally `conf` |
| `frames[].conf` | object, optional | joint name to number in 0..1, all 17 joints. Same shape Part 5 reads from follower files |

`interpolated` is `false` on exactly the key indices of `keyframes.json` and `true` on every other
frame, including frames before the first key and after the last, which hold the nearest key pose.

### Visibility (`frames[].conf`, `unseen_joints`)

Part 3 gives a joint the camera never saw conf 0.3 on its key frames. Part 4 writes positions for
every joint, so without these fields a reader draws that joint as measured. Both fields are optional.

- Source: `keyframes[].conf` in `skeleton.json` (joint name to number in 0..1), else the `conf` of
  a `{x, y, z, conf}` joint, else 1.0. A value outside 0..1 or not a number is refused.
- A key frame carries its key's own values.
- A filled frame carries the **minimum of the two neighbouring keys**, joint by joint, so a joint
  that is unseen at either end of a gap stays unseen across it. Frames before the first key and
  after the last carry the nearest key's values. The result is a step function of the keys, never
  a blend between 0.3 and 1.0.
- `unseen_joints` lists the joints at or below 0.3 at every key frame (never seen in the clip).
- When every joint at every key is 1.0, or the input carries no confidence, neither field is
  written and the file is byte-identical to one built before they existed. Absent `conf` means
  seen, as in Part 5 (`conf.get(name, 1.0)`).
- Positions, `interpolated` and `bones` do not depend on conf.

## `keyframes.json` and `skeleton.json` (`simon.keyframes.v1`, `simon.skeleton.v1`)

Required in `keyframes.json`: `format`, `fps` (30), `duration_s`, `frame_count`, and `keyframes[]`
with `index` and `t`. `name`, `set` and `movement` are optional.

Required in `skeleton.json`: `format`, `rest_offsets_m` (all 18 rig joints, each with its standard
`parent` and a three-number `offset`), and `keyframes[]` with `index`, `t`, `joints` (17 positions,
as `[x, y, z]` or `{x, y, z, conf}`) and `local_rotations` (19 quaternions, pelvis and neck
included). Optional per key: `conf`, a joint name to 0..1 map (Part 3's `--view part4` writes it). When present, `fps` must be 30 and `joints` must be the canonical 17 in order.

Both inputs accept extra fields and ignore them. The README section "Edge cases" lists every
rejection with its reason.

## What each part sends or reads

| Part | Direction | What |
| --- | --- | --- |
| Part 1 | upstream of Part 3 | Its `keyframes.json` is on the video clock, per person, and is not read by Part 4. Part 3 maps it onto the 30 fps index with `--keyframes`. |
| Part 3 | sends | `python3 -m part3 run ... --view part4 --body part4-rig --keyframes <keys> --keyframes-out <dir>/keyframes.json` writes both inputs. `fixtures/input/part3-squat/` is that output, unedited. Its `keyframes.json` has no `movement`, so the clip's `movement` is `null`. |
| Part 5 | reads | `animation.json` as the expected movement. Copy `contracts/animation.schema.json` from this repo instead of deriving one. |
| Part 6 | reads | `animation.json`, detected by `format` and `frames[0].joints`. |

## Versioning

The version is the `format` field of each file. A change that adds, removes or renames a field, or
changes a unit, the frame or the clock, gets a new `format` value (for example
`simon.animation.v2`), and Part 4 refuses a `format` it does not know. The 9f4c073 rebuild of the
shipped clips changed joint positions without changing the format; copies taken before it
(366d628) differ from the current `fixtures/output/` by up to 0.136 m (dance) and 0.124 m (exercise), so refresh them together with
anything built from them.

The shortest-arc change after f1693dc (A-P4-07, A-P4-08) left the exercise, dance, long and minute
joint positions unchanged and added `producer` to every file. It moved the in-between frames of
`part3-squat` by up to 0.0176 m (right ankle; wrists up to 0.0049 m). Part 3 writes each knee and
elbow rotation as a pure swing from rest, and two swings about different axes differ by a twist
about the shank or forearm, which Part 4 now takes out. Its key frames did not move. A schema copied before this change rejects the new files (closed
objects), so copy `contracts/animation.schema.json` again together with the outputs.

The optional `unseen_joints` and `frames[].conf` (visibility) change no position and leave the
four synthetic clips byte-identical; only `part3-squat`, whose input carries conf 0.3, gained
them. The published schema now lists both fields. A schema copied before this change rejects a file
that carries them (closed objects), so a reader that pins `contracts/animation.schema.json` should
copy it again. A reader that does not validate against it, such as Part 5's loader, keeps working.

### Rotations Part 4 now accepts

Before the change, a key pair was refused when a joint's rotation vector (angle kept in 0 to 180°)
stepped more than 180°. That refused a folded elbow swinging about the upper arm and any joint
passing through 180°. Part 3 worked around the first with a shoulder twist (its ASM-020); that
twist is no longer needed by Part 4, and leaving it in is harmless. The rule now applies after the
shortest arc described in the README, "How one in-between frame is made".
