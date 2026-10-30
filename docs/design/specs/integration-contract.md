# Spec: Part 2 integration contract, `contract` and `doctor`, writer rules

> Copy of `docs/specs/integration-contract.md` from the maintainers' working repo at `68ecdcc`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Requirements source: registry milestone M1 ("stitch-ready") and use case
uc-integration-contract; stakeholder-proxy decisions 6 and 9 (2026-10-28).
Request Type: feature-mod
Risk Level: medium
Tickets: TICKET-006 (contract), TICKET-007 (doctor), TICKET-008 (writer rules), TICKET-010 (publish and threads).
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
| `provenance` | optional object: `{contract_version, backend, tracker, lifter, refine: [..], models: [{name, source, weights_sha256}], part2_commit, created_utc, licence_notes}`. Readers ignore it. |

### Compatibility table (rows in `contracts/compatibility.json` and `CONTRACT.md`)
| Producer file | Version | Consumer | Result | Option | Evidence |
|---|---|---|---|---|---|
| pose3d.json, one person | part2.pose3d/2026-10-28 | Part 3 | works | | Part 3 CONTRACT row for Part 2 7e11a7f; neighbour check |
| pose3d.json, several people | same | Part 3 | works with option | Part 3 `--person <id>` or `--all-people`, or the `pose3d_person_<id>.json` file | Part 3 CONTRACT row |
| pose3d.json with `mirrored` | same | Part 3 | works | Part 3 `--flip auto` reads it | Part 3 ADR-0005 |
| pose3d.json with `provenance`, `t0_pts_ms` | same | Part 3 | works | | extra keys ignored (Part 3 CONTRACT) |
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
| `contracts/*.schema.json`, `contracts/compatibility.json`, `contracts/consumers/*`, `CONTRACT.md` | data |
| `Makefile` | `check-2-contract`; `contract-sync` and `contract-check` retargeted |
| `tests/test_contract.py`, `tests/test_doctor.py`, `tests/test_provenance.py`, `tests/test_schema.py` | tests |

## Acceptance Criteria
### AC-C01: Schemas
Each of the four schemas is draft 2020-12 with `$id`, `title` and `x-simon-version`; every committed
`fixtures/output/**` file of that kind validates; a mutated copy per rule (missing field, wrong type,
NaN) fails with the path named.
### AC-C02: Part 3 consumer copy
Every committed `pose3d*.json` passes `validate_part3` against `contracts/consumers/part3-pose3d.schema.json`.
### AC-C03: `contract` command
`python -m part2 contract` prints four schema rows and every table row; `--json` parses and holds the
same rows as `contracts/compatibility.json`; `--schema pose3d` prints the file byte for byte.
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
| Schema name unknown | contract exit 2 | `contract: no schema 'x'; schemas: pose3d, tracks, camera, frames` | AC-C03 |
| Contract break | validate raises | `<path>: <rule>` | AC-C01, C07 |

## Edge Cases
- Empty `frames`: valid for the schema, `doctor` says Part 3 would reject it (no person).
- Person id as a string: valid (README allows integer or string).
- A frame with `people: []`: valid.

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

## Delivery Verification Plan
`make test` 0, `make check-2-contract` 0, `python -m part2 contract` and `doctor` terminal frames for
uc-integration-contract, neighbour check JSON (TICKET-009), fresh-clone `make check-2-contract` 0 at M5.
