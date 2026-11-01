# Spec: Part 2 integration contract, `contract` and `doctor`, writer rules

> Copy of `docs/specs/integration-contract.md` from the maintainers' working repo at `f43deee`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Requirements source: registry milestone M1 ("stitch-ready") and use case
uc-integration-contract; stakeholder-proxy decisions 6 and 9 (2026-10-28).
Request Type: feature-mod
Risk Level: medium
Tickets: TICKET-006 (contract), TICKET-007 (doctor), TICKET-008 (writer rules), TICKET-010 (publish and threads),
TICKET-043 (foot points in `extra_joints`, Part 5 request IECB iem-20261031T055936Z-simon-part-5-a82c),
TICKET-048 (the fifth schema, `mesh3d`; spec `mesh3d.md`).
ADRs: ADR-0001, ADR-0006, ADR-0007. Master spec: `part2-images-to-3d.md`.
Base: PR #47 (branch `contract/part3-pose3d`, commits e049c30 and 29e3e8b): `CONTRACT.md`,
`contracts/pose3d.schema.json` (Part 3's consumer schema copied byte for byte),
`contracts/pose3d.schema.source.json`, `part2/contract.py` (`validate`, `sync`, `sync --check`),
`tests/test_contract.py`, Makefile `contract-sync` and `contract-check`. TICKET-002 merges it into
local main; this spec extends it.

## Overview
Parts 3, 4, 5, 6 and 7 must plug into Part 2 without reading its code. Part 2 publishes one schema per
file it writes, a compatibility table, and two commands in the same family as Part 3 and Part 6:
`python -m part2 contract` lists schemas and the table; `python -m part2 doctor <file> --for <consumer>`
names a file's kind and version, validates it and says in plain words what a consumer would reject and
which option fixes it. Writer rules close the open items from #18 and #47: `mirrored`, the `t_ms` zero,
NaN and infinity, and an optional `provenance` block. All additions are optional fields, so Part 3's
CONTRACT rows for Part 2 at `7e11a7f` stay valid (ASM-010).

## Why This Is Wrong (Dissent-First)
- Part 2 files carry no version field. A dated version (`part2.pose3d/2026-10-28`) names the state but
  a reader cannot see it in the file. Adding a required version field would break Part 3's reader;
  `provenance.contract_version` is optional and carries it.
- `doctor --for part6` checks a consumer that does not read Part 2 files (PR #47 Neighbours: "Does not
  read Part 2 files"). It checks Part 6's generic reader rules only, and says so.
- Part 3's schema copy can drift from Part 3 main. `make contract-check` (from #47) catches it; it needs
  a `gh` login, so it is not part of `make test`.

## User Story
As the owner of Part 3, 4, 5, 6 or 7, I want to check my copy of a Part 2 file in one command, so that
stitching day finds format problems before runtime.

### Jobs-to-be-Done
- Functional: a verdict per consumer with the fix. Emotional: no surprise on stitching day. Social: the
  same command names as Parts 3 and 6.

## Interface
### Files
| File | Kind | Version | Writer |
|---|---|---|---|
| `contracts/pose3d.schema.json` | `pose3d` | `part2.pose3d/2026-10-28` | Part 2's own promise (draft 2020-12, `x-simon-version`) |
| `contracts/tracks.schema.json` | `tracks` | `part2.tracks/2026-10-28` | Part 2 |
| `contracts/camera.schema.json` | `camera` | `part2.camera/2026-10-28` | Part 2 |
| `contracts/frames.schema.json` | `frames` | `part2.frames/2026-10-28` | Part 2 |
| `contracts/mesh3d.schema.json` | `mesh3d` | `part2.mesh3d/2026-10-31` | Part 2, optional (`part2 run --mesh`, TICKET-048): the header of `mesh3d.json`; its `mesh3d.bin` is checked by `part2 doctor` |
| `contracts/consumers/part3-pose3d.schema.json` + `.source.json` | Part 3's consumer schema, byte copy | Part 3 main commit in the sidecar | moved from PR #47's `contracts/pose3d.schema.json` |
| `contracts/compatibility.json` | the table | n/a | Part 2 |
| `CONTRACT.md` | the page: shapes, frame, units, joints, version policy, table, how to check, how to ask | n/a | Part 2 |

`make contract-sync` and `make contract-check` (PR #47) now read and write
`contracts/consumers/part3-pose3d.schema.json`.

### Commands
```
python -m part2 contract                    # schema list (name, version, direction, file) and the table
python -m part2 contract --json             # {"schemas": [...], "compatibility": [...]}
python -m part2 contract --schema pose3d    # one schema verbatim
python -m part2 doctor <file> [--for part3|part5|part6] [--json]
make check-2-contract                       # every committed output against every schema and consumer rule
```
`doctor` output, one line per finding:
```
<file>: kind pose3d, version part2.pose3d/2026-10-28 (by shape), 3 people, 89 frames
Part 3: accepts with option: several people; fix: python3 -m part3 run ... --person <id> or --all-people
Part 5: would reject: Part 5 reads skeleton.json; fix: run Part 3 first (--view part5)
Part 6: accepts (generic reader: 17 joints, finite numbers, person id 0 played)
```
Exit 0 when the named consumer (or, without `--for`, Part 3) accepts with or without an option; 1 when
it would reject; 2 when the file is not JSON or of no known kind.

### Python API
`part2.contract.validate(doc, kind) -> None` raises `ContractError(path, msg)`;
`part2.contract.validate_part3(doc)` (PR #47) unchanged;
`part2.doctor.diagnose(path, consumer=None) -> {"kind", "version", "detected_by", "findings": [{consumer, verdict, reason, fix}]}`.

### Writer rules (TICKET-008)
| Field | Rule |
|---|---|
| `t_ms` | milliseconds from the first decoded frame of the input: `t_ms = (pts[k] - pts[0]) * 1000`, as `part2/frames.py` writes today. For a file whose first PTS is 0 this equals milliseconds from file start. Join with Part 1 on `t_ms`, never on frame numbers. |
| `t0_pts_ms` | optional top-level number: the first decoded frame's PTS in ms, so a consumer can rebase onto the file clock. Written by `part2 frames` and copied into `pose3d.json` and `tracks.json`. |
| `mirrored` | optional top-level boolean; `part2 run --mirrored` writes `true`; absent means not mirrored. |
| NaN, infinity | rejected in `schema.validate_pose3d`, `schema.validate_tracks`, `contract.validate` for `conf`, `fps`, coordinates, `t_ms`, bbox and confidence. JSON is written with `allow_nan=False`. |
| `provenance` | optional object: `{contract_version, backend, tracker, lifter, refine: [..], models: [{name, source, weights_sha256}], part2_commit, created_utc, licence_notes, extra_joints?}`. Readers ignore it. |
| `frames[].people[].extra_joints` | optional object beside `joints` (TICKET-043, "Extra joints" below): the six foot points, each `{x, y, z, conf}`. Written only by the gpu backend. |

### Extra joints (TICKET-043)
Part 5 asked for the heel, big toe and small toe of each foot. Part 3's consumer schema and
`contracts/pose3d.schema.json` set `additionalProperties: false` on `joints` only, so the 17 `joints` keep exactly
their names and the foot points go in a new optional per-person object beside them.

| Field | Rule |
|---|---|
| `extra_joints` | Optional object on a person. Names: `left_big_toe`, `left_small_toe`, `left_heel`, `right_big_toe`, `right_small_toe`, `right_heel` (`part2.joints.EXTRA`, written in that order). Any of the six may be left out; no other name is allowed (`additionalProperties: false`). |
| `extra_joints.<name>` | The shape of a joint: `x, y, z` finite numbers in metres in the same canonical frame as `joints` (same per-frame `R` and `t`, rounded to 0.1 mm), `conf` in [0, 1] by the joints' rule (1.0 when the point projects inside the image, 0.3 when the model placed it outside). Never null, as in `joints`: a point a writer lacks is left out. |
| Source | SAM 3D Body's MHR70 keypoints 15 to 20 (left big toe tip, left small toe tip, left heel, right big toe tip, right small toe tip, right heel; `sam_3d_body/metadata/mhr70.py`). `part2/body3d.py` writes them into `body3d.json` as `extra_kp3d_cam` and `extra_kp2d` per person; `part2/canonical.py` turns them into `extra_joints`. |
| Who writes it | The gpu backend, for every person it writes. The cpu backend (RTMPose-x gives 17 points) writes none. |
| `provenance.extra_joints` | When the file carries a `provenance` block and any person carries foot points: the list of names the file holds, in `EXTRA` order. Absent when the file holds none (the cpu backend), so its presence says the points were written and `provenance.backend` says by which backend. Each `pose3d_person_<id>.json` names the points of its own person. |
| Refine rungs | `kp2d-fit` and `temporal` move the 17 joints; each foot point moves rigidly with its own ankle's displacement (left points with `left_ankle`, right with `right_ankle`), so ankle to foot vectors keep the model's values, and `extra_kp2d` becomes the projection of the moved points, as `kp2d` does for the joints. `focal` re-runs SAM 3D Body, so it takes the feet of the run it chooses. `part2 run --smooth` (One-Euro on the joints) moves the foot points with their ankles the same way. |
| Mirrored file | With `"mirrored": true`, `extra_joints` carry the same labels as `joints`. Part 3 mirrors `joints` and does not touch `extra_joints`, so a reader that mirrors the joints must also swap the `left_` and `right_` names of the feet and negate x. `CONTRACT.md` says so in "`mirrored`" and in "Extra joints (optional)", and the table has a row for Part 5 reading the feet directly. Test: `tests/test_contract.py`. |
| Version | Additive under the version policy: `part2.pose3d/2026-10-28` stays. |

### Compatibility table (rows in `contracts/compatibility.json` and `CONTRACT.md`)
| Producer file | Version | Consumer | Result | Option | Evidence |
|---|---|---|---|---|---|
| pose3d.json, one person | part2.pose3d/2026-10-28 | Part 3 | works | | Part 3 CONTRACT row for Part 2 7e11a7f; neighbour check |
| pose3d.json, several people | same | Part 3 | works with option | Part 3 `--person <id>` or `--all-people`, or the `pose3d_person_<id>.json` file | Part 3 CONTRACT row |
| pose3d.json with `mirrored` | same | Part 3 | works | Part 3 `--flip auto` reads it | Part 3 ADR-0005 |
| pose3d.json with `provenance`, `t0_pts_ms` | same | Part 3 | works | | extra keys ignored (Part 3 CONTRACT) |
| pose3d.json with `extra_joints` | same | Part 3 | works | | Part 3's schema sets additionalProperties false on `joints` only; tests/test_extra_joints.py |
| pose3d.json with `extra_joints` | same | Part 5 (feet read directly) | works with option | read `extra_joints` in Part 2's canonical frame (x subject's left, y up, z anterior, metres); with `mirrored: true`, swap the `left_` and `right_` names and negate x, as for `joints`, because Part 3 does not touch `extra_joints` | tests/test_extra_joints.py; CONTRACT.md "Extra joints (optional)" |
| pose3d.json | same | Part 4 | via Part 3 | Part 3 `--view part4` | Part 4 reads Part 3's skeleton |
| pose3d.json | same | Part 5 | via Part 3 | Part 3 `--view part5` | Part 5 `analyse` reads skeleton.json |
| pose3d.json | same | Part 6 | works with its generic reader only | none; Part 6 has no Part 2 kind | Part 6 CONTRACT "What every reader accepts" |
| pose3d.json, tracks.json | same | Part 7 | works | | Part 7 stitches through the files named here |
| tracks.json | part2.tracks/2026-10-28 | none today | n/a | | PR #47: Part 3 does not read it |
| pose3d.json, tracks.json (`t_ms`, `t0_pts_ms`) | same | Part 1 (time join) | works with option | join on `t_ms` when both sides count from the first decoded frame; when `t0_pts_ms` is present and not 0, file time = `t_ms + t0_pts_ms` | `frames.py` rule; `doctor` warns (AC-C11) |

## Files
| File | Role |
|---|---|
| `part2/__main__.py` | `python -m part2` entry |
| `part2/contract.py` | schemas, table, `contract` command, `validate`, `sync` (PR #47 base) |
| `part2/doctor.py` | `doctor` |
| `part2/provenance.py` | build and check `provenance` |
| `part2/schema.py`, `part2/frames.py`, `part2/canonical.py`, `part2/multi3d.py`, `part2/cli.py` | modified for the writer rules |
| `contracts/*.schema.json` (five since TICKET-048), `contracts/compatibility.json`, `contracts/consumers/*`, `CONTRACT.md` | data |
| `Makefile` | `check-2-contract`; `contract-sync` and `contract-check` retargeted |
| `tests/test_contract.py`, `tests/test_doctor.py`, `tests/test_provenance.py`, `tests/test_schema.py` | tests |
| `part2/foot_check.py` | TICKET-043: the measured, ungated foot-point check (`python -m part2.foot_check`, `make check-feet`): coverage and segment-length consistency of `extra_joints`, reported apart from the README gate |
| `tests/test_foot_check.py`, `tests/test_extra_joints.py` | TICKET-043 tests |
| `part2/joints.py`, `part2/body3d.py`, `part2/canonical.py`, `part2/multi3d.py`, `part2/schema.py`, `part2/doctor.py`, `part2/refine/__init__.py`, `part2/refine/kp2d_fit.py`, `part2/refine/temporal.py` | TICKET-043 (modified): `EXTRA`, `MHR70_EXTRA`, `EXTRA_ANKLE`, `follow_ankles`; the six points from MHR70 and `moved_feet` (projecting through `lifters.project`, the one guarded projection, as the rungs do); `extra_joints` and `provenance.extra_joints`; per-person provenance line; validation; the doctor line and its public `people_in` (also read by `foot_check`); feet follow the refined ankles through the one shared `refine.with_joints` |
| `contracts/pose3d.schema.json`, `CONTRACT.md`, `Makefile` | TICKET-043 (modified): `$defs/extra_joints`, `provenance.extra_joints`; section "Extra joints (optional)"; target `check-feet` |

## Acceptance Criteria
### AC-C01: Schemas
Each of the five schemas (`pose3d`, `tracks`, `camera`, `frames`, and `mesh3d` of TICKET-048) is draft 2020-12 with
`$id`, `title` and `x-simon-version`; every committed `fixtures/output/**` file of the first four kinds validates (a
`mesh3d.json` is never committed, `mesh3d.md` AC-M15); a mutated copy per rule (missing field, wrong type, NaN) fails
with the path named.
### AC-C02: Part 3 consumer copy
Every committed `pose3d*.json` passes `validate_part3` against `contracts/consumers/part3-pose3d.schema.json`.
### AC-C03: `contract` command
`python -m part2 contract` prints five schema rows (`mesh3d` last, `part2.mesh3d/2026-10-31`) and every table row;
`--json` parses and holds the same rows as `contracts/compatibility.json`; `--schema pose3d` (or any of the five)
prints the file byte for byte. The contract page and `GET api/contract` list the same five, and the staging `contract`
check downloads every `contracts/*.schema.json` it finds, so the fifth is covered without a literal count there.
`contracts/compatibility.json` has no `mesh3d` row: its rows name `pose3d.json` and `tracks.json` and there is none
for `camera.json` or `frames.json`, so a row for one optional file would break the pattern; `doctor` says that no
consumer reads `mesh3d.json` (`mesh3d.md` AC-M07).
### AC-C04: `doctor` verdicts
For each committed output and for crafted files (several people, no `t_ms`, NaN `conf`, a skeleton.json,
a non-JSON file) `doctor` prints the kind, the version, one verdict per consumer and exits 0, 1 or 2 as
in Interface (one test per case). No stack trace on any input.
### AC-C05: `mirrored`
`part2 run --mirrored` output has `"mirrored": true` and `doctor --for part3` accepts it; a string value
is rejected by `contract.validate` with the path.
### AC-C06: `t_ms` and `t0_pts_ms`
A video whose first PTS is not 0 (built by ffmpeg in the test with `-output_ts_offset`) gives `t_ms`
starting at 0 and `t0_pts_ms` equal to the offset; CONTRACT.md states the rule.
### AC-C07: NaN and infinity
A document with NaN or infinity in any numeric field fails every validator; writers never emit one
(`allow_nan=False`).
### AC-C08: `provenance`
Every writer adds `provenance` with the backend and tracker that ran; removing it keeps the file valid.
### AC-C09: Backward compatibility
Part 3's rows for Part 2 `7e11a7f` hold: the neighbour check (TICKET-009) runs Part 3 `doctor` on every
committed output and Part 3 accepts each (with the option its row names).
### AC-C11: Part 1 time-join warning
Given a file with `t0_pts_ms` present and not 0, when `doctor` runs with any `--for`, then it prints
`warning: t0_pts_ms is <v>; a consumer joining on file time (Part 1) must add it to t_ms` and the exit code
is unchanged; with `t0_pts_ms` absent or 0 no warning (test).
### AC-C10: `make check-2-contract`
Validates every committed output against its schema, the Part 3 copy and `doctor --for part3`; prints a
metrics JSON (`files`, `valid`, `failures`) and exits 0 only when all pass. Runs without a GPU.
### AC-C12: `extra_joints` from the gpu backend, none from the cpu backend (TICKET-043)
Given a SAM 3D Body output of 70 keypoints, `body3d._person` writes `extra_kp3d_cam` and `extra_kp2d` from MHR70
rows 15 to 20 and leaves the 17 joints and `reproj_self_px` as before; `canonical.convert` writes `extra_joints` in
`EXTRA` order through the joints' own `R` and `t`, so a subject seen from any yaw gives back its canonical foot
points; a foot point outside the image gets conf 0.3. The cpu backend's people carry no foot points and its
`pose3d.json` has no `extra_joints`. `kp2d-fit`, `temporal` and `--smooth` move each foot point by its own ankle's
displacement; `focal` returns the feet of the run it chose. Test: `tests/test_extra_joints.py`.
### AC-C13: schema and validators (TICKET-043)
`contracts/pose3d.schema.json` gains `$defs/extra_joints` (`additionalProperties: false`, the six names, none
required, each a `$defs/joint`) and the person property `extra_joints`; `provenance.extra_joints` lists names that
match `^(left|right)_(big_toe|small_toe|heel)$`; `x-simon-version` stays
`part2.pose3d/2026-10-28` and no required field is added. `contract.validate` and `schema.validate_pose3d` accept a
file with and without `extra_joints` and any subset of the six names, and reject an unknown name, a null entry, a
missing coordinate, a non-number, NaN or infinity and a conf outside [0, 1], naming the path; `contract.validate` also
rejects a `provenance.extra_joints` item that is not one of the six names. `contract.validate_part3` (Part 3's
consumer schema) accepts a file with `extra_joints`. Test: `tests/test_extra_joints.py`.
### AC-C14: provenance line (TICKET-043)
A written file whose people carry foot points has `provenance.extra_joints` listing them in `EXTRA` order; a file
that holds none has no such key, even when its block was copied from a file that did; each
`pose3d_person_<id>.json` lists its own person's points. `provenance.validate` accepts the key. Test:
`tests/test_extra_joints.py`.
### AC-C15: `doctor` mentions extra joints (TICKET-043)
For a pose3d file whose people carry `extra_joints`, `doctor` prints one more line, `extra joints: <names> on <k> of
<n> person-frames (optional extra_joints beside the 17 joints)`, and `--json` has `extra_joints: {names,
person_frames, of}` (null without them). Every verdict and exit code for Part 3, Part 5 and Part 6 is the same as for
the same file without `extra_joints`. Test: `tests/test_extra_joints.py`.
### AC-C16: the foot check, measured and ungated (TICKET-043)
`python -m part2.foot_check <pose3d.json ...>` prints one JSON report: per file `person_frames`, `with_all_six`,
`coverage` (person-frames whose `extra_joints` holds all six points with finite x, y, z, over all person-frames),
`points`, `low_conf` (fraction of present points with conf below 0.5), `points_with_ankle` and `points_without_ankle`
(a point whose own ankle is missing, null or not finite cannot be measured and is counted in neither of the next two),
`points_within_bound`, `within_bound` (over `points_with_ankle`, 0.0 when there are none) and `max_ankle_m` (each foot
point's distance to its own ankle against 0.35 m; null when no point could be measured), and per person the mean and the
coefficient of variation (std over mean, null below two frames) of ankle to heel, ankle to big toe and big toe to
small toe on each side (people are keyed by their id written as JSON, so id 0 and id "0" are two people); a
`summary` over the readable files. The bound: an adult foot measures under about 0.30 m from
the back of the heel to the tip of the big toe and the ankle sits between the two, so no point of a plausible foot is
farther than that from its own ankle; the rest is margin for model error. It exits 0 whatever the numbers and 2 only
when a named or expected file cannot be read, is not JSON or has no frames list (that file's entry names the error; the
others are still reported). It is reported, never gated: `make check-2` does not read it. With no file, or with
`--scored <dir>`, it names every file of the gpu backend's scored sets under the scored dir: one `pose3d.json` per mode
`part2/outputs.py` `MODES` lists for the gpu backend (so a gpu mode added there is checked with no edit here) and, for
`coco-single`, one per image of `fixtures/input/coco/images/images.json` (`coco_set.MANIFEST`), so a file that is
missing is reported as unreadable and not dropped. The scored dir is chosen as for `make check-2` (`part2.check.scored_dir`):
the flag, then `PART2_SCORED_DIR`, then `fixtures/output/scored`. Files named without `--scored` are checked alone.
`make check-feet` passes `--scored` only for `SCORED=<dir>`, so both targets read the same directory. Test:
`tests/test_foot_check.py` (known numbers on synthetic files).

### Rule-Based ACs
- AC-C-NFR-01: no field is removed or renamed in any shape. Verification: test (the 7e11a7f fixtures
  still validate).
- AC-C-NFR-02: `doctor` reads only the given file. Verification: inspection.

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| File is not JSON | doctor exit 2 | `<file>: not JSON (line <n>)` | AC-C04 |
| Unknown kind | doctor exit 2 | `<file>: not a Part 2 file (no frames list)` | AC-C04 |
| Unknown `--for` | exit 2 | `doctor: unknown consumer 'x'; choose part3, part5 or part6` | AC-C04 |
| Schema name unknown | contract exit 2 | `contract: no schema 'x'; schemas: pose3d, tracks, camera, frames, mesh3d` | AC-C03 |
| Contract break | validate raises | `<path>: <rule>` | AC-C01, C07 |
| Unknown name inside `extra_joints` | validate raises | `pose3d.frames[i].people[k].extra_joints: unexpected key(s) [...]` (`contract`) or `unknown name(s) [...]` (`schema`) | AC-C13 |
| Null, non-number or out-of-range entry in `extra_joints` | validate raises | `pose3d.frames[i].people[k].extra_joints.<name>[.<key>]: <rule>` | AC-C13 |
| cpu backend run | no `extra_joints` written, no `provenance.extra_joints` | none (not an error) | AC-C12, C14 |
| Foot check on an unreadable file | that file reported with `error`, exit 2 | `<file>: cannot read (...)`, `<file>: not JSON (line <n>)`, `<file>: not a pose3d file (no frames list)` | AC-C16 |

## Edge Cases
- Empty `frames`: valid for the schema, `doctor` says Part 3 would reject it (no person).
- Person id as a string: valid (README allows integer or string).
- A frame with `people: []`: valid.
- A person whose feet lie outside the image (low-confidence feet): the points are still written, with conf 0.3, as
  for any joint outside the image; the foot check counts them in `low_conf`.
- A file where some people carry foot points and others do not, or a person carries only some of the six: valid;
  `doctor` counts the person-frames that carry any, the foot check counts coverage only for all six.
- A null foot point: invalid for every validator (as in `joints`); the foot check, which reads files that may not
  validate, counts it as missing.
- A file without `extra_joints` (every file before TICKET-043, every cpu output): valid; `doctor` prints no extra
  line; the foot check reports coverage 0.0.

## Locked defaults (final)
| Item | Decision |
|---|---|
| Version policy | additive fields keep the version; a removed or renamed field bumps the date |
| Part 3 copy location | `contracts/consumers/part3-pose3d.schema.json` (moved from PR #47's name, which now holds Part 2's own schema) |
| Part 6 verdict | generic reader rules only, stated in the output |
| doctor default consumer | Part 3 |
| Output style | plain words, one line per finding, `--json` for machines |

## Negative Requirements
- MUST NOT add a required field. Why: Part 3 reads files unchanged.
- MUST NOT import Part 3, 5 or 6 code. Why: black box; consumer rules are copied as data or restated.

## Compromises
### Dated version without a field
Short-term: version lives in the schema and optional `provenance.contract_version`. Trigger to revisit:
a breaking change.

## Assumptions
ASM-010 (Part 3 rows stay valid for additive fields), ASM-008 (teammates may push during the run).

## Dissent Review
Reviewed by: setup lane (architect, opus), 2026-10-28.
### Concern 1: moving PR #47's schema file
Challenge: a teammate may already link `contracts/pose3d.schema.json` as Part 3's copy. Impact: a broken
link. Mitigation: CONTRACT.md says where the copy moved; the move ships with the merge of #47's content.
Resolution: ADDRESSED_IN_SPEC.
### Concern 2: `t0_pts_ms` is new surface
Challenge: nobody asked for it. Impact: unused field. Mitigation: optional, answers Muse's question on #18.
Resolution: ACCEPTED_RISK.
### Concern 3: Part 6 verdict misleads
Challenge: "accepts" for a consumer that never reads Part 2 files. Mitigation: the line says "generic
reader". Resolution: ADDRESSED_IN_SPEC.
### Pre-Mortem
1. Part 3 changes its schema on stitching day. L M, Mitigation: `make contract-check`.
2. A writer path skips `provenance`. L L, Mitigation: AC-C08 test per writer.
3. NaN reaches a file through a code path the tests miss. L M, Mitigation: `allow_nan=False` at write.

## Requirements Traceability
| Requirement | AC | Ticket |
|---|---|---|
| M1 published contract and schemas | AC-C01, C02, C03, C10 | TICKET-006 |
| M1 doctor | AC-C04 | TICKET-007 |
| M1 mirrored, t_ms, NaN rules | AC-C05, C06, C07, C08 | TICKET-008 |
| Backward compatibility with Part 3 | AC-C09 | TICKET-009 |
| #47 merged, #18 and #46 DECISION posts | (publish) | TICKET-010 |
| Part 5 foot points (IECB iem-20261031T055936Z-simon-part-5-a82c) | AC-C12, C13, C14, C15, C16 | TICKET-043 |

## Delivery Verification Plan
`make test` 0, `make check-2-contract` 0, `python -m part2 contract` and `doctor` terminal frames for
uc-integration-contract, neighbour check JSON (TICKET-009), fresh-clone `make check-2-contract` 0 at M5.
TICKET-043: `uv run pytest -q tests/test_extra_joints.py tests/test_foot_check.py` 0 on the lane; after the scored
outputs are regenerated on the GPU, `make check-2-contract` 0, `make check-2` 0, `doctor` on a regenerated gpu
output shows the extra joints line, and `make check-feet` prints the report (exit 0; numbers recorded, not gated).
