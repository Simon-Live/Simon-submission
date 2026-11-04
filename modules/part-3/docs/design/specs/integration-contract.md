# Spec: Part 3 integration contract, body profiles, output views, input adapters and conformance kit

> Copy of the maintainers' working spec `docs/specs/integration-contract.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Requirements source: `goals/phase2-simon-part-3.md` sections 1 to 4 (operator directive 2026-10-28).
Parent spec: `docs/design/specs/part3-skeleton.md`. Sibling: `docs/design/specs/compare-mode.md` (staging).
Request Type: feature-mod
Risk Level: medium (the files other teams build against tomorrow)
Tickets: TICKET-022 (contract), TICKET-023 (profiles), TICKET-024 (adapters, native and part5 views, fps, people),
TICKET-025 (rig and part4 view), TICKET-026 (conformance kit), TICKET-027 (neighbour check).

Covers these files:
- Contract (TICKET-022): `CONTRACT.md`, `contracts/*.schema.json`, `contracts/compatibility.json`,
  `part3/contract.py`, `part3/doctor.py`, `part3/jsonschema_lite.py`; tests `tests/part3/test_contract.py`,
  `tests/part3/test_doctor.py`, `tests/part3/test_jsonschema_lite.py`.
- Profiles (TICKET-023): `part3/profiles.py`, `part3/config.py`, `part3/standard.py` (unchanged API, profile
  reads it), `part3.toml.example`; tests `tests/part3/test_profiles.py`, `tests/part3/test_config.py`.
- Adapters, views, fps, people (TICKET-024): `part3/adapters/__init__.py`, `part3/adapters/*.py`,
  `part3/views/__init__.py`, `part3/views/native.py`, `part3/views/part5.py`, `part3/resample.py`,
  `part3/people.py`, `part3/person.py` (requested id), `part3/cli.py`, `part3/schema.py`; tests
  `tests/part3/test_adapters.py`, `tests/part3/test_views.py`, `tests/part3/test_resample.py`,
  `tests/part3/test_people.py`, `tests/part3/test_cli_phase2.py`.
- Rig and part4 view (TICKET-025): `part3/rig.py`, `part3/keyframes.py`, `part3/views/part4.py`; tests
  `tests/part3/test_rig.py`, `tests/part3/test_keyframes.py`, `tests/part3/test_view_part4.py`,
  `tests/part3/test_long_way.py`, `tests/part3/part4rules.py`.
- Shared constants: `part3/joints.py` (`COORDINATE_FRAME`), `part3/schema.py` (public `is_number`, `is_finite`).
- Conformance kit (TICKET-026): `part3/followers.py`, `part3/conformance.py`, `fixtures/conformance/**`,
  `Makefile` target `check-3-contract`; tests `tests/part3/test_followers.py`, `tests/part3/test_conformance.py`.
- Neighbour check (TICKET-027, firm layer, never published): `scripts/neighbour-check.sh`,
  `scripts/neighbour_check.py`; test `tests/neighbour/test_neighbour_check.py`.
- Docs: `README.md` (sections "Integration" and "Options"), `fixtures/output/README.md`, `.simon-publish`
  (adds `CONTRACT.md`, `contracts/**`, `part3.toml.example`).

## Overview
Tomorrow the six parts are stitched. Part 3 must plug into Part 2 (input), Part 4 and Part 5 (outputs) and Part 7
(calls the CLI) without anyone reading its code. This spec adds: a published contract (`CONTRACT.md`, one JSON
Schema per file Part 3 reads or writes, a compatibility table, `python3 -m part3 contract` and
`python3 -m part3 doctor <file>`); switchable body profiles; output views as a registry (native, part4, part5) with
`--fps`, `--person` and `--all-people`; tolerant input adapters as a registry; and a conformance kit of golden files
checked by `make check-3-contract`. One pipeline runs underneath every option; `make check-3` metrics stay
identical on the default options.

Ecosystem facts, re-checked 2026-10-28 in the read-only clones (they override the brief where they differ):
- Part 2 (`7e11a7f`): `pose3d.json` is `{frames: [{frame, t_ms, people: [{id, joints: {<17>: {x, y, z, conf}}}]}]}`,
  no version field; multi-person mode writes a `pose3d.json` per tracked person.
- Part 1 (`6fac92f`): `keyframes.json` is `{video, fps (e.g. 60.0), analysis_fps, quality, people: [{id,
  repetitions: [{rep, movement, keyframes: [{name, frame, t_ms}]}]}]}` on the original video clock; no version field.
- Part 4 (`9f4c073`): reads `skeleton.json` `format: simon.skeleton.v1` with `keyframes[]` (`index`, `t`, `name`,
  `joints` as `[x, y, z]` or `{x, y, z, conf}`, `local_rotations` as `(x, y, z, w)` for 19 joints), `root_joint`
  `pelvis`, `virtual_joints` `["pelvis", "neck"]` (no chest; the brief's chest is gone), `rest_offsets_m` with fixed
  parents, plus `keyframes.json` `simon.keyframes.v1` (`fps` 30, `duration_s`, `frame_count`, `keyframes[{index, t,
  name}]`) in the same directory. Its rig now uses Part 3's own 1.70 m lengths (README "The body and the coordinate
  frame": thigh 0.4165, shank 0.4182, upper arm 0.3162, forearm 0.2482, spine 0.4896 m); the brief's 0.42, 0.40,
  0.28, 0.25 m are superseded. Its check rejects a key whose FK from `local_rotations` and `rest_offsets_m` misses the
  key `joints` by over 1 mm.
- Part 5 (`c292a15`, `part5/io.py`, `docs/schemas.md`): reads `format` `simon.animation.v1` (`frames[{index, t,
  interpolated, joints: {name: [x, y, z]}, conf: {name: 0..1}}]`) or `simon.skeleton.v1` (`keyframes[]`, same joint
  shape, extra fields ignored). It rejects a file without `format`, joints that are not `[x, y, z]` lists, a hip
  midpoint over 1 cm from the origin, times that do not strictly increase, and a `coordinate_frame` field with a
  different value (`y` must be `world_up`). So Part 5 rejects today's native `skeleton.json`; the part5 view fixes that.
  Its fault labels (`simon.part5.labels.v1`) carry `type`, `measure`, `body_part`, `joints`, `side`, `direction`,
  `magnitude_deg`, `text`.
- Part 7 (`90aa473`): consumes every part through its files only; it will call `python3 -m part3 run`.

## Why This Is Wrong (Dissent-First)
- Three output shapes triple the surface that can drift. Mitigated: one pipeline makes the native skeleton; views are
  pure functions of it; every view has a schema, golden files and a byte-for-byte rebuild in `make check-3-contract`.
- Part 4's rig moves the children of the pelvis, neck and nose rigidly, while Part 3 keeps every bone's own direction
  (the hip line, spine and head can bend relative to each other). No set of local rotations reproduces such a pose
  exactly. The part4 view therefore writes the FK pose of fitted rotations as its key `joints` (Part 4's 1 mm rule
  holds by construction) and reports the fit residual against the native frames. Hiding that residual would be a lie;
  it is a number in the file and in the contract.
- A JSON Schema library would be a new dependency for every neighbour. Instead the schemas are standard draft 2020-12
  documents (any validator works) and Part 3 checks them with a small stdlib validator of the keywords it uses; a test
  cross-checks it with `jsonschema` when that package is installed.
- Env and config selection make output depend on ambient state. Mitigated: the output records the profile, its
  numbers, its source and which channel selected it (`body.selected_by`); the staging server ignores env and config.
- Tolerant adapters can hide a producer's bug. Mitigated: every adapter that fires is named in `input.adapters`, and
  `doctor` says which one would fire and why.

## User Story
As a team owning Part 2, 4, 5 or 7
I want to read one contract, pick a body and an output shape with one option, and check my file with one command
So that stitching tomorrow is a config choice, not a code change in somebody else's repo.

### Jobs-to-be-Done
- Functional job: produce a skeleton file the next part accepts without editing either part.
- Emotional job: confidence that a red result names the field and the fix.
- Social job: Part 3 is the easy neighbour to integrate.

## Pipeline and options (API / Interface Contract)

### Command line
```
python3 -m part3 run --in <pose3d.json> --out <path> [--flip auto|on|off]
    [--body simon-standard|part4-rig|measured|file:<path>] [--stature <m>] [--config <part3.toml>]
    [--view native|part4|part5] [--keyframes <keyframes.json>|every:<n>] [--keyframes-densify every:<n>|off] [--keyframes-person <id>]
    [--keyframes-out <path>] [--fps <n>] [--input-fps <n>] [--person <id> | --all-people]
python3 -m part3 contract [--json] [--schema <name>]
python3 -m part3 doctor <file> [--for part3|part4|part5] [--json]
```
Exit codes stay as today for `run`: 0 written, 2 input or option breaks the contract (message names the field or the
option, nothing written), 1 output not writable. `contract` exits 0 (2 for an unknown schema name). `doctor` exits 0
when the file is a known kind and valid for it, 1 when valid but the consumer named by `--for` would reject it,
2 when unreadable, not JSON, of unknown kind, or invalid for its kind.

### Python API (Part 7 and the staging server call these; keyword-only additions keep today's calls working)
```python
part3.cli.process(doc, flip="auto", sha256=None, trace=None, *, body=None, stature=None, person=None,
                  fps=None, input_fps=None, env=None, config=None, max_frames=None) -> dict   # native skeleton
part3.cli.process_all(doc, **same) -> list[tuple[id, dict]]                  # one native skeleton per tracked id
part3.views.render(skeleton, view="native", *, keyframes=None, keyframes_person=None, max_frames=None) -> dict
part3.views.REGISTRY  # {name: module}; a module has NAME, DESCRIPTION, SCHEMA (contracts file name),
                      # render(skeleton, **opts) -> dict
part3.views.keyframes_doc(rendered) -> dict | None   # the simon.keyframes.v1 companion of a part4 render
part3.adapters.adapt(doc, input_fps=None) -> (canonical_doc, [adapter names])   # never mutates doc
part3.adapters.REGISTRY  # ordered list of modules: NAME, DESCRIPTION, applies(doc) -> bool,
                         # apply(doc, input_fps) -> doc
part3.profiles.resolve(flag=None, api=None, stature_flag=None, stature_api=None, env=None, config=None)
    -> Selection(name, selected_by, spec)      # env None means os.environ; config None means discover
part3.profiles.lengths_for(selection, measured_lengths) -> Body(name, stature_m, scale, bone_lengths_m,
                                                                   source, sources, symmetrized, selected_by)
part3.rig.fit(joints_17x3, rest_offsets) -> (local_rotations, fk_joints, residual_m_per_joint)
part3.rig.forward(local_rotations, rest_offsets) -> joints   # Part 4's convention, below
part3.rig.rest_offsets(bone_lengths_m) -> {joint: {"parent", "offset"}}
part3.keyframes.load(doc, t0_ms, t_last_ms, person=None) -> Timeline(fps=30, frame_count, duration_s, keys, dropped,
                                                                       source_kind, person)
part3.contract.main(argv) -> int ; part3.doctor.main(argv) -> int ; part3.doctor.diagnose(doc) -> Report
part3.jsonschema_lite.validate(instance, schema) -> list[str]   # error paths, empty when valid
```
`process(doc)` with no new arguments returns today's skeleton plus the `body` block and `input.adapters` (below);
`make check-3` metrics are identical.

Errors the API raises are `ContractError`s with a `path` and a `msg` (`str()` reads `<path>: <msg>`). Four subclasses
let a caller tell a refusal apart by type, never by its path or wording (TICKET-032, TICKET-033); the command line
prints the same text and exits 2 for each:
- `part3.schema.FrameCapError` (also an `OptionError`, so `str()` reads `<option> <message>` for the `--fps` grid and
  `<path>: <message>` for the `--keyframes` timeline): the output frame grid (`resample.grid_count`) or the part4 key
  timeline (`keyframes.frame_count`) would hold more frames than the cap. Its `timeline` attribute is True for the
  key timeline and False for the grid.
- `part3.schema.FrameRateError`: the clip cannot be resampled at the chosen `fps` for a reason that is not the cap. It
  has `times` False for `--fps: no output frame holds the person; use a higher --fps` and True for `pose3d.frames[i].t_ms:
  must increase for --fps`.
- `part3.schema.ViewError`: a View cannot write the clip. Every refusal a view module raises is one (the part5 view
  whose times do not increase, the part4 view with no keys, the long way below). It has `page_text`, the sentence a page
  shows for it with no command line option in it (`view_refusal_text(label, detail)`); `colon=False` gives the
  `<option> <message>` reading. The view registry's own checks (an unregistered view, an option another view owns) stay
  `ContractError`s for the command line.
- `part3.schema.LongWayError` (a `ViewError`): Part 4 would reject the keys. It has `joint`, `degrees`,
  `from_index`, `to_index` and `limit_deg`, its path is `--view part4`, and its `page_text` is built from those.

A test (`tests/part3/test_typed_refusals.py`) scans `part3/` with `ast` and fails on a `ContractError` or `OptionError`
raised with a path that starts with `--` unless it is listed there as command-line only, so a new option refusal is
typed or deliberately listed.

### Body profiles (TICKET-023)
A profile is `{name, stature_m, bone_lengths_m (the 18 contract bones), source, sources[]}`.

| Name | Numbers | Source recorded |
|---|---|---|
| `simon-standard` (default except `--view part4`) | `part3/standard_body.json`, 1.70 m | that file and its `sources` |
| `part4-rig` | thigh 0.4165, shank 0.4182, upper arm 0.3162, forearm 0.2482, spine 0.4896 from Part 4's README; pelvis half-width 0.125, clavicle 0.1979, head 0.1907, eye link 0.0618, ear link 0.0774 from Part 4's `fixtures/input/exercise/skeleton.json` `bone_lengths_m`; stature 1.70 | `"moalborati/simon-part-4-animate-keyframes 9f4c073: README 'The body and the coordinate frame'; fixtures/input/exercise/skeleton.json bone_lengths_m"` |
| `measured` | the subject's median input lengths (`person.measured_bone_lengths_m`), each left/right pair replaced by its mean (`symmetrized: true`), fixed for the whole clip; stature estimated as the chain sum used by the run page | `"measured: median input bone lengths of this clip"` |
| `file:<path>` | a JSON file `{"schema": "simon.body_profile/1", "name", "stature_m", "bone_lengths_m", "source"}`, validated against `contracts/body-profile.schema.json` and the rules below | the file's `source` and path |

Numbers are typed into `part3/profiles.py` as data with the source string beside them; nothing reads Part 4's repo
at run time. Rules for any profile: all 18 bones present, each finite and in [0.005, 1.5] m; stature in [0.5, 2.5] m;
`left_pelvis == right_pelvis` and `left_clavicle == right_clavicle` (else the hip and shoulder midpoints move; a
`file:` profile breaking this exits 2 naming the bone). `--stature <m>` (0.5 to 2.5) scales every length by
`stature / profile.stature_m` and records `scale`. Selection precedence, first set wins: CLI flag `--body`, environment
`PART3_BODY`, config file, API parameter `body=`, then the default of the view: `part4-rig` for `--view part4`
(Part 4's animator rejects bone lengths more than 1 mm off its rig; assumption ASM-012, TICKET-035) and
`simon-standard` for every other view (ASM-013). Stature: `--stature`, `PART3_STATURE`,
config `stature`, API `stature=`, none. Config file: `--config <path>`, else `PART3_CONFIG`, else `./part3.toml` when
it exists; TOML `[body] profile = "..."`, `stature = 1.80` (`tomllib`). A relative `file:` path in a config file is
relative to that file's directory; elsewhere relative to the working directory. An unknown profile name, a bad
stature, a bad config file or a bad `file:` profile exits 2 with a message naming the channel and the field.

Output (every view): `bone_lengths_m` is the chosen profile's (scaled) numbers; `standard.stature_m` its stature;
`standard.sources` its sources; new block
`body: {profile, selected_by: flag|env|config|api|default, stature_m, scale, source, symmetrized}`, plus `reason` (a
text) only when the view chose the profile, for example `"default for --view part4: Part 4's animator rejects bone
lengths more than 1 mm off its rig (assumption ASM-012); name a body to choose another"`. A body named on any
channel wins and records no `reason`. Every frame is rebuilt on those lengths, so bone variation is 0 to rounding (<2%
for every profile).

### Input adapters (TICKET-024)
`adapters.adapt` runs each registered adapter in order when `applies(doc)` is true, then the existing validator runs.
Registry order and behaviour:
1. `flat-joints`: a frame with `joints` and no `people` becomes `people: [{id: 0, joints}]`.
2. `joint-arrays`: a person's `joints` given as `{name: [x, y, z]}` or `{name: [x, y, z, conf]}`, or as a list of 17
   such arrays in canonical order, becomes `{name: {x, y, z, conf}}`; a missing conf becomes 1.0.
3. `extra-joints`: joint names outside the canonical 17 are dropped (a missing canonical joint still fails).
4. `frame-index`: frames without `frame` get their list position.
5. `derive-t_ms`: frames without `t_ms` get `frame * 1000 / fps`, fps from `--input-fps` (API `input_fps`) or a
   top-level numeric `fps`; neither gives exit 2 `pose3d.frames[0].t_ms: missing; pass --input-fps <n> or add a
   top-level fps`.
Extra keys anywhere are ignored (as today). The output records `input.adapters` (names that fired, in order; `[]` for
a canonical Part 2 file). A new tolerated shape is one module plus one registry line.

### People (TICKET-024)
`--person <id>` keeps that id (`person.rule: "requested"`, `person.requested: <id>`); the CLI string matches an
integer id when it is all digits, else a string id; an absent id exits 2 listing the ids present (at most 20).
`--all-people` (excludes `--person`) treats `--out` as a directory and writes `<out>/person-<slug>/skeleton.json` for
every id (slug = the id when it matches `[A-Za-z0-9_-]{1,40}`, else its position `p<k>`), each a full single-person
file in the chosen view (with part4, `keyframes.json` beside each), plus `<out>/people.json`
`{"schema": "simon.part3.people/1", "people": [{"id", "dir", "frames_present", "file"}]}` in first-seen order. An id
whose frames all fail the hip check is listed with `"skipped": "<reason>"` and no file.

### Resampling `--fps <n>` (TICKET-024)
`n` in [1, 240]. Applied after the rebuild, before the view. Output frames `frame = i` on a uniform grid from the
first to the last input frame time (`t_ms = t0 + i * 1000 / n`, 3 decimals, the source clock kept), each with
`source: {"frames": [fa, fb], "weight": w}` (the bracketing input frames, `w` the share of `fb`). A frame whose two
brackets both hold the person gets the joint-wise linear blend re-rebuilt on the profile lengths (bone lengths stay
fixed); otherwise its `people` is empty. Top-level `resample: {fps: n, source_frames: N, method:
"linear blend then fixed-length rebuild"}`. Without `--fps` nothing changes.
Frame cap (review B1): a grid of more than `resample.MAX_FRAMES` = 100,000 frames, or a clip span that is not finite,
exits 2 (`--fps <n> would write <N> frames; the limit is 100000`, a `FrameCapError`); the same cap applies to the
part4 timeline's `frame_count` (`--keyframes: the 30 fps timeline would have <N> ticks; the limit is 100000`, also a
`FrameCapError`). `process` and
`views.render` take `max_frames=` (default the cap); the staging server passes 20,000 and refuses a request whose
span times its frame rate (the chosen fps, 30 for part4) exceeds that before it runs anything.

### Views (TICKET-024, TICKET-025)
- `native` (default): today's `simon.skeleton/1` plus `body` and `input.adapters`.
- `part5` (`contracts/animation-part5.schema.json`): `{"format": "simon.animation.v1", "producer": "part3",
  "view": "part5", "fps": n (always), "duration_s", "frame_count", "coordinate_frame": {"origin":
  "hip_midpoint", "x": "subject_left", "y": "world_up", "z": "anterior", "position_unit": "metres",
  "angle_unit": "degrees"}, "joints": [17], "bones": [{name, parent, child, length_m}], "body", "person", "mirror",
  "source": {"schema": "simon.skeleton/1", "sha256"}, "frames_skipped": k, "frames": [{"index", "t", "interpolated":
  false, "joints": {name: [x, y, z]}, "conf": {name: c}}]}`. Only frames holding the person are written; `t` is
  seconds from the first input frame (6 decimals); `index` is the input `frame` (the grid index when resampled).
  `y` is `world_up` because Part 3's body up is its estimate of world up; native keeps `body_up`.
  `fps` is always written, a number above 0, because Part 6 (`59f923f`, `part6/formats.py` `read_animation`) rejects a
  `simon.animation.v1` file without it (`fps: must be a number above 0`). It is the output clock's rate: the `--fps`
  rate when resampled; otherwise 1000 over the median step between consecutive input `t_ms` (every input frame,
  with or without the person; only positive steps; an even count of steps takes the mean of the two middle ones),
  rounded to 3 decimals (the unrounded rate if rounding gives 0); 30 when no positive step exists (a one-frame clip).
  On a non-uniform clock `fps` is the nominal rate and each frame's `t` stays the time of record (Part 5 and Part 6
  both read `t` when it is present). The Part 2 squat (15 fps, steps of 66.667 ms) writes `fps: 15.0`.
- `part4` (`contracts/skeleton-part4.schema.json`): the native document plus `format: "simon.skeleton.v1"`, `fps: 30` (required; added 2026-10-28 for Part 5, which reads a top-level fps),
  `coordinate_frame` (as part5), `root_joint: "pelvis"`, `virtual_joints: ["pelvis", "neck"]`, `rest_offsets_m`,
  `timeline: {fps: 30, duration_s, frame_count, t0_ms, source_kind: part1|part4|every, person, dropped: [{name,
  t_ms, reason}]}`, `rig: {convention, fit: {max_m, mean_m, worst_joint, worst_index}}` and `keyframes[]`. The native
  `frames` stay. `--keyframes` is required (exit 2 `--view part4 needs --keyframes <keyframes.json> or every:<n>`).

### Part 4 rig and rotations (TICKET-025, KNOWN RISK in the brief)
Hierarchy (child: parent), exactly Part 4's: left_hip, right_hip, neck: pelvis; left_knee: left_hip; left_ankle:
left_knee; right_knee: right_hip; right_ankle: right_knee; left_shoulder, right_shoulder, nose: neck; left_elbow:
left_shoulder; left_wrist: left_elbow; right_elbow: right_shoulder; right_wrist: right_elbow; left_eye, right_eye:
nose; left_ear: left_eye; right_ear: right_eye. `pelvis` sits at the origin; `neck` is the shoulder midpoint.
Rest offsets (parent frame, metres, lengths from the profile): hips `(±pelvis, 0, 0)`; knee `(0, -thigh, 0)`; ankle
`(0, -shank, 0)`; neck `(0, spine, 0)`; shoulders `(±clavicle, 0, 0)`; elbow `(±upper_arm, 0, 0)`; wrist
`(±forearm, 0, 0)` (arms rest in a T-pose, review B2: Part 4 rejects a joint passing 180 degrees from its rest
direction, and from a T-pose an arm overhead or hanging is 90 degrees away); nose, eyes, ears point as in `standard_body.json` `neutral_head_m` (nose minus neck, eye minus
nose, ear minus eye), scaled to the profile's head, eye link and ear link lengths.
Convention: quaternions `(x, y, z, w)`, Hamilton product, active rotation; `global[j] = global[parent] * local[j]`;
`position[j] = position[parent] + rotate(global[parent], offset[j])`; output positions minus the hip midpoint. Leaves
(ankles, wrists, ears) carry identity. Fit per key: a joint with several children takes the weighted Kabsch rotation
of its rest offsets onto the target child vectors (weights = canonical joints in each child's subtree: hips 3, neck
11; shoulders 3, nose 5; eyes 2); a joint with one child takes the shortest arc from the rest direction to the target
direction in its parent's frame; every target is measured from the already fitted parent position. Twist continuity
(stitching 2026-10-28, ASM-020): a shoulder or a hip then turns about its own bone by the twist that minimises the
larger of two Part 4 steps from the previous key, its own and the elbow's or knee's (the first key: their angles
from rest), searched every 5 degrees and then every 0.5 degrees, with 0.001 per radian of twist as the tie-break, and
kept only when it beats no twist. The twist moves no joint, so positions and `rig.fit` are unchanged; it keeps an
elbow bent behind the head from flipping its axis between neighbouring keys (Part 2's seated stretch clip failed the
long-way rule at every `every:<n>` without it).
Quaternions are written with `w >= 0`, 6 decimals; key joints are the FK result, 6 decimals.
Self-check (review B2): after the keys are built the view applies Part 4's long-way rule (`rig.long_way`: each key's
quaternion aligned to the previous key's hemisphere, as a rotation vector keeping that sign, the angle 0 to 360 degrees so a joint passing 180 degrees stays next to its previous key (TICKET-042, Part 4's `_rotvec_unwrapped`); a step
over 180 degrees between neighbouring keys is rejected). Any such step exits 2 and writes nothing: `--view part4: Part 4
would reject this clip: <joint> turns <deg> degrees between keys <a> and <b> (Part 4 allows 180); add keys between them
(a smaller every:<n>) or use another view` (a `LongWayError`, a `ViewError` whose path is `--view part4`; the
next step after the semicolon is the one constant `rig.LONG_WAY_FIX`, which `doctor` prints as its fix as well).

### Keyframes input (TICKET-025)

Densifying sparse named keys (`--keyframes-densify every:<n>`, `timeline.densify`) is specified in `docs/design/specs/journey-followup.md` (TICKET-036).
`--keyframes <path>` accepts Part 1's file (detected by `people[].repetitions`) or Part 4's `simon.keyframes.v1`;
`every:<n>` (n in [1, 300]) keys ticks 0, n, 2n and the last tick. Timeline: `t0` = first input frame `t_ms`,
`frame_count = floor((t_last - t0) * 30 / 1000 + 1e-9) + 1`, `duration_s = (frame_count - 1) / 30`. Part 1: the
person `--keyframes-person <id>` (else the first listed), every repetition's keys in time order, `index = round((t_ms -
t0) * 30 / 1000)`; Part 4: its `index` as given (its `fps` must be 30). A key before tick 0, after the last tick, or on
an index already taken is dropped into `timeline.dropped` with the reason; none left exits 2. Each key's pose is the
native frame holding the person nearest in time to `t0 + index * 1000 / 30` (ties to the earlier). A key whose nearest
input frame (with or without the person, ties to the earlier) holds no person sits where the person is missing; it is
dropped into `timeline.dropped` with the reason `the input frame nearest the key has no person (the person is missing
there)` (ASM-021), and none left exits 2. Key entries are
`{index, t: index/30 (6 decimals), name, source_frame, source_t_ms, joints, conf, local_rotations}`.
`--keyframes-out <path>` writes `{"format": "simon.keyframes.v1", "producer": "part3", "fps": 30, "duration_s",
"frame_count", "keyframes": [{index, t, name}]}`, the file Part 4 reads beside `skeleton.json`. It must name a different
file from `--out` (the same real path, a symlink or a hard link to it); otherwise exit 2 with `--keyframes-out must differ
from --out`, before the input is read.

### Contract and doctor (TICKET-022)
`contracts/` holds one draft 2020-12 schema per file, each with `$id`, `title`, `x-simon-version` and, where Part 3
writes it, a `const` version field: `pose3d.schema.json` (Part 2 input; producer has no version field, called
`part2.pose3d/2026-10-28`), `keyframes-part1.schema.json`, `keyframes-part4.schema.json` (`simon.keyframes.v1`, read
and written), `body-profile.schema.json` (`simon.body_profile/1`), `skeleton.schema.json` (`simon.skeleton/1`),
`skeleton-part4.schema.json` (`simon.skeleton.v1`), `animation-part5.schema.json` (`simon.animation.v1`),
`people-index.schema.json` (`simon.part3.people/1`), `follower-labels.schema.json` (`simon.part3.follower_labels/1`).
`contracts/compatibility.json` is the table (producer, file, version, consumer, consumer version, result `works` |
`works with option` | `rejected`, option, evidence). `CONTRACT.md` renders the same table and states the frame, units,
joints, bones, version policy (additive fields keep the version; a removed or renamed field bumps it) and how to ask.
`python3 -m part3 contract` prints the schema list (name, version, direction, file) and the table; `--json` prints
`{schemas, compatibility}`; `--schema <name>` prints one schema verbatim.
`doctor` reads one file, names its kind and version, validates it (schema plus Part 3's own validator), and for each
consumer (Part 3 input, Part 4, Part 5) prints `accepts` or `would reject: <reason>; fix: <option>`, e.g. a native
skeleton: `Part 5 would reject: no "format"; fix: python3 -m part3 run ... --view part5`; a pose3d without `t_ms`:
`Part 3 accepts with adapter derive-t_ms only with --input-fps <n>`; a part4 view: Part 4's rules (fps 30, key `t` =
`index / 30` within 1 µs, strictly increasing keys inside the clip, rest parents, FK residual under 1 mm, canonical
joints list, no quaternion with norm under 1e-8, the long-way rule, a `keyframes.json` beside it with the same key
indices). A rule doctor cannot check is a rejection, never an accept (review B3). A `simon.skeleton.v1` file not
written by Part 3 (Part 4's own fixtures) is named as such and still gets the Part 4 and Part 5 verdicts. Plain words,
one line per finding, never a stack trace.

### Conformance kit (TICKET-026)
`fixtures/conformance/` holds `cases.json` (case id, input file, CLI options, expected output files), `inputs/`
(the Part 2 squat; a joints-as-arrays copy; a copy without `t_ms` plus `fps`; a two-person copy; Part 1 and Part 4
style keyframes files; an example `file:` profile), `golden/<case>/` (the outputs), and `followers/` (Part 5 follower
takes). Cases cover every profile (`simon-standard`, `part4-rig`, `measured`, `file:`, `--stature 1.85`), every view
(`native`, `part4` from Part 1 keyframes, `part4` from Part 4 keyframes with `--keyframes-out`, `part4` with a named
`simon-standard` body over the view's `part4-rig` default, `part5`, `--fps 30`),
`--person`, `--all-people` and each adapter. Follower takes: the squat with faults applied in the body frame before
camera rendering (Part 2-like noise, the synth module's errors): `correct`; `feet_wide` (both ankles out, size in m);
`elbows_out` (upper arms abducted, deg); `shallow_squat` (knee flexion scaled down at the bottom, deg); `knee_caving`
(knees moved medially at the bottom, deg of valgus); each at `front`, `45` and `side` azimuths; each written as
`input/pose3d.json`, `skeleton.json` (part5 view) and `skeleton.native.json`, with `followers/labels.json`
(`simon.part3.follower_labels/1`, Part 5's label field names: `take_id`, `angle`, `camera_yaw_deg`, `correct`,
`faults: [{type, measure, body_part, joints, side, direction, magnitude_deg | magnitude_m, text,
measured_in_output}]`). `measured_in_output` is the fault size measured on Part 3's output against the correct take
at the same angle, so Part 5 sees what survives normalization.
`make check-3-contract` (`python3 -m part3.conformance check`): validates every golden and follower file against its
schema, rebuilds every case and follower take into a temp directory and compares bytes, checks every labelled fault is
still visible in the output (`measured_in_output` within 50% of the applied size and on the labelled side) and every
correct take shows none over the fault thresholds, prints a metrics JSON and exits 0 only when every check passes.
`python3 -m part3.conformance build` regenerates the kit.

### Neighbour check (TICKET-027, local only)
`scripts/neighbour-check.sh [--clones <dir>]` (default the read-only clone directory named in the brief; never
published, never in CI): copies Part 2's newest `pose3d.json` files (by commit time) and Part 4's `fixtures/input/`
into a temp dir; runs Part 3 on each Part 2 file (native, part5 and `--view part4 --body part4-rig --keyframes
every:10 --keyframes-out`; `--body part4-rig` is the part4 default since ASM-012 and is kept explicit there) and runs `doctor` on each output; then `git clone` Part 4's clone into a temp dir, puts
Part 3's part4 output and keyframes into its `fixtures/input/exercise/`, runs `make animate` there, and applies Part 4's
key-drift rule to its `fixtures/output/exercise/animation.json` (each key frame within 1 mm of Part 3's key joints,
bone lengths within 1 mm of `rest_offsets_m`, hip midpoint within 1 mm). Prints a JSON result with every command and
exit code; exits non-zero on any red result and says which. Never edits a clone; the temp dirs are removed.

## Acceptance Criteria
### Contract (TICKET-022)
- AC-C01: Given the repo, when `python3 -m part3 contract` runs, then it prints every schema in `contracts/` with name,
  version, direction and file, and the compatibility table; `--json` parses; `--schema skeleton` prints the file bytes.
- AC-C02: Every schema is valid draft 2020-12 (meta-validated by `jsonschema` when installed) and has `$id`, `title`,
  `x-simon-version`; every file Part 3 writes carries its version field.
- AC-C03: `jsonschema_lite.validate` agrees with `jsonschema` on every golden file and on mutated copies (missing
  field, wrong type, wrong const) when `jsonschema` is installed; without it the test still runs the stdlib path.
- AC-C04: `doctor` on each kind (Part 2 pose3d, tolerated pose3d forms, native, part4, part5, keyframes Part 1 and
  Part 4, body profile, people index, labels) names the kind and version and exits 0; on a broken file it exits 2 and
  names the field; on an unknown JSON it exits 2 `unknown kind`.
- AC-C05: `doctor <native skeleton> --for part5` exits 1 and prints the Part 5 rejection and the `--view part5` fix;
  `--for part4` names `--view part4 --keyframes`; a pose3d without `t_ms` names `--input-fps`; a two-person pose3d names
  `--person` and `--all-people`.
- AC-C06: `doctor` on a part4 view whose key `t` is off by 1 ms, or whose FK residual exceeds 1 mm, reports the
  Part 4 rule broken.
- AC-C07: `CONTRACT.md` and `contract` print the same compatibility rows as `contracts/compatibility.json`.
### Profiles (TICKET-023)
- AC-B01: Default run: `body.profile` `simon-standard`, `selected_by` `default`, metrics of `make check-3` unchanged.
- AC-B07 (TICKET-035, ASM-012): `--view part4` with no body on any channel gives `body.profile` `part4-rig`,
  `selected_by` `default` and a `body.reason` naming the view; a body named on any channel (flag, `PART3_BODY`,
  `part3.toml`, API `body=`, the run page) wins and records no `reason`; every other view keeps `simon-standard` with
  no `reason`. A `reason` on a body that a channel chose fails `validate_block`.
- AC-B02: `--body part4-rig`, `measured`, `file:<valid>` each give output whose `bone_lengths_m` equals the profile
  numbers (scaled), whose `body.source` names the source, and whose bone variation is under 2% (0 to rounding).
- AC-B03: `--stature 1.85` scales every length by 1.85 / 1.70 and records `scale`.
- AC-B04: Precedence: flag beats `PART3_BODY` beats `part3.toml` beats API `body=` beats default; each records its
  `selected_by`; same for stature.
- AC-B05: An unknown name, a stature out of range, a `file:` profile missing a bone, with unequal pelvis halves, with a
  bad number, or unreadable, and a bad TOML file each exit 2 naming the channel and field; nothing is written.
- AC-B06: `measured` lengths are the symmetrized medians and are the same in every frame.
### Adapters, people, resampling, views (TICKET-024)
- AC-A01: Each adapter fires only on its shape, the result validates, and `input.adapters` names it; a canonical Part 2
  file records `[]` and its native output is unchanged apart from `body` and `input.adapters`.
- AC-A02: Joints as arrays, as a list of 17, with extra joint names, without `frame`, and without `t_ms` plus
  `--input-fps 30` or a top-level `fps` all run; without `t_ms` and without fps exits 2 naming `--input-fps`.
- AC-V01: `--person <id>` keeps that id; an absent id exits 2 listing the ids; `--person` with `--all-people` exits 2.
- AC-V02: `--all-people` writes one valid single-person file per id and a `people.json` that validates.
- AC-V03: `--fps 30` writes a uniform grid with `source` brackets, bone variation under 2%, `resample` block; a
  frame bracketed by an absent person is empty.
- AC-V04: `--view part5` validates against its schema, passes Part 5's documented input rules (format, joints as lists,
  hip midpoint within 1 cm, strictly increasing `t`, coordinate frame values) checked by Part 3's own test, and writes
  only frames holding the person.
- AC-V06: `--view part5` always writes `fps` above 0 and the schema requires it: the resample rate when resampled, the
  median-step rate of the input clock otherwise (15.0 for the Part 2 squat, 20.0 for steps 40, 50, 50, 200 ms), 30 for
  a one-frame clip, above 0 for a very slow clock; every committed part5 golden and follower file carries it, and
  Part 6's `python3 -m part6 doctor` accepts them.
- AC-V05: A new view or adapter is one module and one registry entry (a test registers a dummy view and renders it).
### Rig and part4 (TICKET-025)
- AC-P01: Round trip: random rig-consistent poses (local rotations up to 120 degrees) through `forward`, `fit` and
  `forward` again match within 1e-6 m on every joint, for every profile.
- AC-P02: On the Part 2 squat with Part 1 style keyframes, every key's `joints` equals `forward(local_rotations,
  rest_offsets_m)` within 1 mm (Part 4's rule), key `t` equals `index / 30` within 1 µs, keys strictly increase inside
  the clip, `rest_offsets_m` parents match the hierarchy, and `rig.fit` reports the native residual.
- AC-P03: Part 1 keyframes at 60 fps map to the 30 fps index by time; keys outside the clip or colliding are dropped
  with reasons; `every:10` keys every tenth tick and the last; Part 4 keyframes keep their index; `--keyframes-out`
  validates as `simon.keyframes.v1` and lists the same indices as `keyframes[]`.
- AC-P04: `--view part4` without `--keyframes`, with an unreadable or unknown keyframes file, or with no key left exits
  2 naming the problem.
### Conformance kit (TICKET-026)
- AC-K01: `make check-3-contract` exits 0 on a clean checkout and prints a metrics JSON with counts of cases, files
  validated, files rebuilt identical and faults visible.
- AC-K02: Changing one byte of a golden file, or one coordinate in a follower take, makes it exit 1 naming the file.
- AC-K03: Every labelled fault (feet_wide, elbows_out, shallow_squat, knee_caving at front, 45 and side) is visible in
  Part 3's output within 50% of its applied size on the labelled side; correct takes show no fault.
### Neighbour check (TICKET-027)
- AC-N01: The script prints every command and exit code as JSON and exits non-zero naming the failing step when a
  Part 2 file fails or Part 4's key-drift rule breaks; it never writes inside a clone (test with a fake clone dir).

### Rule-Based ACs
- AC-NFR-001: `process` on the 107-frame squat with any profile and view runs in under 2 s. Verification: test timing.
- AC-NFR-002: No new runtime dependency (stdlib and numpy only). Verification: inspection of `requirements.txt`.
- AC-NFR-003: Every message for a bad file or option names the field or option; no traceback. Verification: tests.

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| unknown `--body` / `PART3_BODY` / config profile | exit 2 | `<channel>: unknown body profile "<x>"; choose simon-standard, part4-rig, measured or file:<path>` | AC-B05 |
| `file:` profile invalid | exit 2 | `body file:<path>: bone_lengths_m.<bone>: <reason>` | AC-B05 |
| stature out of range | exit 2 | `<channel>: stature must be 0.5 to 2.5 m (got <x>)` | AC-B05 |
| bad `part3.toml` | exit 2 | `<path>: not valid TOML (<reason>)` or `<path>: body.profile: expected a string` | AC-B05 |
| no `t_ms`, no fps | exit 2 | `pose3d.frames[0].t_ms: missing; pass --input-fps <n> or add a top-level fps` | AC-A02 |
| `--person` absent | exit 2 | `--person <id>: not in the input (ids: 0, 1)` | AC-V01 |
| part4 without keyframes | exit 2 | `--view part4 needs --keyframes <keyframes.json> or every:<n>` | AC-P04 |
| keyframes unknown kind | exit 2 | `<path>: not a Part 1 or Part 4 keyframes file` | AC-P04 |
| no key inside the clip | exit 2 | `<path>: no keyframe falls inside the clip (0 to <ms> ms)` | AC-P04 |
| `--fps` out of range | exit 2 | `--fps must be 1 to 240` | AC-V03 |
| doctor on unknown JSON | exit 2 | `<path>: unknown kind (not a file of the Part 3 contract)` | AC-C04 |

## Edge Cases
- A one-frame clip with part4: one key at index 0, frame_count 1 (AC-P03).
- Resampling a clip whose person is absent in the middle leaves a gap, never a blend across it (AC-V03).
- An id `"a/b"` gets slug `p<k>` (AC-V02).
- Antiparallel shortest arc (180 degrees): any perpendicular axis, deterministic (AC-P01).
- `--stature` with `measured` scales the measured lengths (AC-B03).

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|---|---|---|---|
| Performance | run time on the squat | < 2 s any option | AC-NFR-001 |
| Security | `file:` and config paths | read only, CLI and API only; the staging server refuses them | AC-B05, compare-mode AC-M07 |
| Maintainability | new view or adapter | one module plus one registry line | AC-V05 |
| Compatibility | Python | 3.11+ (tomllib), numpy | AC-NFR-002 |
| Reliability | errors | plain message, exit 2, nothing written | AC-NFR-003 |
| Accessibility | N/A | command line and files only | |
| Scalability | clip length | linear in frames | |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT import, copy or vendor code from another part. Why: black-box rule; numbers are typed in with a source.
- MUST NOT change native output or `make check-3` metrics on default options beyond the two additive blocks.
- MUST NOT write key `joints` that Part 4's FK cannot reproduce. Why: Part 4 rejects them.
- MUST NOT hide the rig fit residual or a dropped key. Why: truthful evidence.
- MUST NOT publish the neighbour check. Why: it reads other teams' clones.

## Compromises
### Rig fit residual
Short-term: key poses are snapped to Part 4's rig and the residual is reported. Long-term: if Part 4 adds a chest and
a head joint (or per-key rest offsets), the residual goes to zero; the contract names that as the open question.
### Part 5 follower format
Short-term: the part5 view follows Part 5's own assumption (open decision 1 in its #18). Long-term: whichever shape
Part 5 settles on becomes a view module.

## Traceability
| AC | Test |
|---|---|
| AC-C01..C07 | `tests/part3/test_contract.py`, `test_doctor.py`, `test_jsonschema_lite.py` |
| AC-B01..B06 | `tests/part3/test_profiles.py`, `test_config.py`, `test_cli_phase2.py` |
| AC-A01..A02, AC-V01..V06 | `tests/part3/test_adapters.py`, `test_people.py`, `test_resample.py`, `test_views.py`, `test_cli_phase2.py` |
| AC-P01..P04 | `tests/part3/test_rig.py`, `test_keyframes.py`, `test_view_part4.py` |
| AC-K01..K03 | `tests/part3/test_conformance.py`, `test_followers.py`, `make check-3-contract` |
| AC-N01 | `tests/neighbour/test_neighbour_check.py` |

## Dissent Review
- "Snap to the rig is a silent pose change": answered by `rig.fit` in every part4 file and the contract's open question.
- "A homemade schema validator will disagree with real ones": answered by the cross-check test (AC-C03).
- "API parameter as the lowest channel surprises a caller": kept because the brief fixes the order and it lets an
  operator switch Part 7's body with `PART3_BODY` without a code change; `selected_by` makes it visible.

## Delivery Verification Plan
- `python3 -m pytest tests/part3 tests/neighbour -q` runs every test named in the Traceability table.
- `make check-3` prints metrics identical to `demo/metrics.json`; `make check-3-contract` exits 0 (TICKET-026).
- `python3 -m part3 contract` and `python3 -m part3 doctor` on each golden file, output inspected (TICKET-022).
- `scripts/neighbour-check.sh` runs locally against the read-only clones; its JSON result and exit code are recorded in
  STATUS.md; it is never published (TICKET-027).
- One consolidated independent review of the integrated main, then `/delivery-review`.
