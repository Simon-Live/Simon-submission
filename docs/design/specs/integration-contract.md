# Spec: Part 5 integration contract (schemas, compatibility table, `part5 contract`, `part5 doctor`, `make check-5-contract`)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADRs: ADR-0002, ADR-0004, ADR-0006. Tickets: TICKET-004 (lands #34),
TICKET-009, TICKET-010, TICKET-011. Milestone M1 (stitch-ready, target 2026-10-29).
Revised 2026-10-31 for the J1 additions (`journey-followup.md`: the `replay` schema, `metrics` 1.1.0, the goldens
with a score and a replay) and ADR-0012 (always analyse: no refusal, no exit 3). Where the text below says refused,
it describes a document written before schema 1.4.0.

## Overview
Part 5 publishes what it reads and writes as versioned JSON Schemas under `contracts/`, a compatibility
table in `CONTRACT.md`, and two commands in the same family style as Parts 3 and 6: `part5 contract`
prints the schemas and the table, `part5 doctor <file>` names a file's kind and version, validates it and
says in plain words what a consumer would reject and which option fixes it. `make check-5-contract`
proves the schemas, the fixtures and the golden outputs agree. PR #34 (landed first, TICKET-004) brings
the copies of Parts 3 and 4's schemas under `contracts/part3/` and `contracts/part4/`, the shared fixtures
and `scripts/sync_contracts.py`; this spec adds Part 5's own schemas at the top of `contracts/`.

## Why This Is Wrong (Dissent-First)
1. Part 7 is an empty scaffold, so the consumer side of the table is a promise, not a test. Answer: the
   `--for part7` verdict is defined by the analysis schema plus one rule (read `status` before `faults`),
   and the result preview screen (`viewer.md`) exercises it.
2. Six schemas and a hand-written loader can drift. Answer: `make check-5-contract` validates every
   committed fixture against its schema and loads it through `part5.io`; a disagreement fails.
3. `simon.analysis.v1` grows new fields (status, joints, runs, coaching, phrasing). A v1.0 reader that
   ignores `status` shows "no faults" on a refused take (before ADR-0012; since then it ignores `warnings` and
   shows no grade F). Answer: the table names that duty for Part 7 and `doctor --for part7` warns on a refused
   analysis and lists the warnings of a warned one.

## User Story
As Part 7 (or Parts 3, 4 and 6), I want to read Part 5's contract and check a file before stitching, so
that a mismatch is found in seconds with the fix named.

## Schemas (`contracts/`, published)
| Name | File | `version` | Describes |
|---|---|---|---|
| `analysis` | `contracts/analysis.schema.json` | `1.5.0` (`1.1.0` when this spec was written) | Part 5's output, `simon.analysis.v1` with the additive fields of the master spec and `journey-followup.md` |
| `input-animation` | `contracts/input-animation.schema.json` | `1.0.0` | expected or follower clip in `simon.animation.v1` (frames, optional `null` joints and `conf`) |
| `input-skeleton` | `contracts/input-skeleton.schema.json` | `1.0.0` | expected clip in `simon.skeleton.v1` (keyframes) |
| `labels` | `contracts/labels.schema.json` | `1.0.0` | `labels.json` of the synthetic sets and the real takes (`label_source` optional) |
| `metrics` | `contracts/metrics.schema.json` | `1.1.0` | the `make check-5` document (`simon.part5.check.v1`, `check-5.md`), with the score report (`gate.sweep`, `report.score`) |
| `replay` | `contracts/replay.schema.json` | `1.0.0` | the `replay.json` of `part5 analyse --replay` (`simon.replay.v1`, `journey-followup.md` J-3) |

Each schema is JSON Schema draft 2020-12 with `$id` `https://github.com/moalborati/simon-part-5-fault-analysis/contracts/<name>.schema.json`
and a top-level `version` string. Extra properties are allowed wherever `docs/schemas.md` allows them.
The copies from Parts 3 and 4 stay under `contracts/part3/` and `contracts/part4/` exactly as #34 ships
them; `contracts/sources.json` and `sources.lock.json` record their commits.

## Compatibility table (in `CONTRACT.md`, printed by `part5 contract`)
| Producer | File | `format` | Part 5 role | Verdict | Fix |
|---|---|---|---|---|---|
| Part 2 | `pose3d.json` | `part2.pose3d/2026-10-28` (Part 3 `CONTRACT.md`) | none | rejected | run Part 3 `--view part5` on it; `doctor` exits 1 with "run Part 3 --view part5" |
| Part 3 `run --view part5` | `skeleton.json` | `simon.animation.v1` | follower or expected | works | |
| Part 3 `run --view part4` | `skeleton.json` | `simon.skeleton.v1` | expected | works | |
| Part 3 native | `skeleton.json` | `simon.skeleton/1` (no `format`) | none | rejected | rerun Part 3 with `--view part5` |
| Part 4 | `animation.json` | `simon.animation.v1` | expected | works | |
| Part 6 Follow hand-off (event detail) | `{v: 1, id, name, category, link, manifest, files: {keyframes, skeleton, animation, video}}` | none | none | works with an option | download `files.animation` and pass it as `--expected`; Part 5 never fetches URLs |
| Part 6 Follow hand-off (framed message, Part 6 `CONTRACT.md` "The hand-off to Part 7") | the same object with `type: "simon:follow"` | none | none | works with an option | same fix; `doctor` names it as the hand-off |
| Part 5 | `analysis.json` | `simon.analysis.v1` | output for Part 7 | works | Part 7 reads `warnings` and `score` (ADR-0012); before 1.4.0 it read `status` before `faults` |
| Part 5 `analyse --replay <replay.json>` | `replay.json` | `simon.replay.v1` | output for Part 7 | works | optional second file; times are in `expected_t` and `follower_t` |
| Part 5 `analyse --live` | live mode (`--live`, `serve --live`, `SIMON5_LIVE=1`, `META_LIVE=1`) | `simon.analysis.v1` with `phrasing.selected_by` `live` | option for Part 7 | works with an option | needs the Baseten key file on the host; the template stays the default for tests and `make check-5` |
| Part 5 | `part5 analyse` exit code | 0 analysis written (with or without warnings), 1 unreadable or invalid input file or write error, 2 usage; 3 is no longer used (ADR-0012) | for Part 7 | works with a mapping | Part 7 at 90aa473 expects the family codes 0 written, 1 not writable, 2 input or option breaks the contract (Part 3 `CONTRACT.md`, row for Part 7): 0 is "written" (read `warnings`), 1 and 2 are failures |
| Part 5 | `labels.json` | none | evaluation | works | |

Each row also names the producer's commit it was checked against (filled by TICKET-009 from
`contracts/sources.lock.json` and the neighbour check; never typed from memory).

## API / Interface Contract
```
python -m part5 contract [--schema <name>] [--json]
python -m part5 doctor <file> [--for part5|part7] [--json]
make check-5-contract        # uv run python -m part5.contract --check
```
- `contract` prints the schema list and the compatibility table; `--schema <name>` prints that schema
  verbatim (for any JSON Schema validator); `--json` prints `{schemas: [...], table: [...]}`. Exit 0;
  an unknown schema name exits 2 naming the valid names.
- `doctor` reads one file, names its kind and version (`simon.animation.v1`, `simon.skeleton.v1`,
  `simon.skeleton/1 (Part 3 native)`, `simon:follow v1 hand-off (Part 6)` (event detail or framed message), `part2.pose3d (Part 2)`, `simon.analysis.v1 1.5.0`,
  `simon.replay.v1 1.0.0`, `labels`), validates it against the matching schema and, for `--for part5` (default), loads it through
  `part5.io`. Output: one verdict line, then one line per problem: field path, what is wrong, the option
  that fixes it. `--for part7` checks an `analysis.json` for Part 7, warns when `status.code` is not `ok` or the take
  has `warnings`, and notes the score, the timed faults and the faults at confidence `"low"`; a `replay.json` is
  accepted for either consumer once its lengths, indexes and times agree (AC-C13). Exit 0 accepted, 1 rejected, 2 unreadable (not JSON, missing, or not a file).
- `part5.contract.check()` validates: every schema is a valid draft 2020-12 schema; every committed
  fixture under `fixtures/input/` and `fixtures/output/` validates against its schema; the golden
  analysis outputs and the golden replay in `fixtures/output/` rebuild byte for byte from the pipeline (the
  `part5 analyse` path with the score hook, template phrasing forced). It prints one JSON summary `{schemas, validated, rebuilt_identical, failures}` and exits 0 only when
  `failures` is empty.
- Code lives in `part5/contract.py` and `part5/doctor.py`; `jsonschema` stays a dev dependency (from
  #34); the run-time validator for `doctor` uses it when installed and falls back to `part5.io` and
  `part5.output` validators otherwise, saying which ran.

## Acceptance Criteria
### AC-C01: schemas published
Given `contracts/`, when listed, then the six schemas exist, each with `$id` and `version`, and each is a
valid draft 2020-12 schema.
### AC-C02: fixtures validate
Given every file under `fixtures/input/expected/`, `fixtures/input/followers/`, `fixtures/input/heldout/`,
`fixtures/input/contract/`, `fixtures/input/eval/real/` and `fixtures/output/`, when `make check-5-contract`
runs, then each validates against its schema and each clip loads through `part5.io`.
### AC-C03: golden outputs rebuild
Given `fixtures/output/analysis*.json` and `replay.example.json`, when rebuilt by the pipeline (the way
`part5 analyse` writes them, score included), then they are byte-identical.
### AC-C04: contract command
Given `python -m part5 contract`, then the table above prints with every row; `--schema analysis` prints
the file byte for byte; `--json` parses.
### AC-C05: doctor accepts
Given Part 4's `animation.json` and Part 3's `--view part5` follower, when `doctor --for part5` runs, then
exit 0 and the kind line names the format and version.
### AC-C06: doctor rejects with the fix
Given Part 3's native `skeleton.json`, when `doctor --for part5` runs, then exit 1 and the message says
the file has no `format` and names `--view part5` as the fix.
### AC-C07: Part 6 hand-off
Given a hand-off object `{v: 1, id, files: {...}}`, or the framed message with `type: "simon:follow"`,
when `doctor` runs, then it names the hand-off kind, exits 1 for `--for part5` and says to download
`files.animation` and pass it as `--expected`.
### AC-C08: Part 7 check
Given an analysis written before 1.4.0 that was refused, when `doctor --for part7` runs, then exit 0 with a
warning that `status.code` is `different_movement` and `faults` is empty by design; given a 1.4.0 or later take
with `warnings`, exit 0 and each warning is listed; an analysis missing `format` exits 1.
### AC-C09: unreadable
Given a missing file or invalid JSON, `doctor` exits 2 naming the file.
### AC-C11: Part 2 pose3d
Given a Part 2 `pose3d.json`, when `doctor --for part5` runs, then it names the file as Part 2's
`pose3d.json`, exits 1 and says "run Part 3 --view part5".
### AC-C12: exit-code mapping published
Given `python -m part5 contract`, then the table carries the `part5 analyse` exit-code row with the
Part 7 mapping, and `CONTRACT.md` states that 0 means an analysis was written and that exit 3 is no longer
produced (ADR-0012).
### AC-C13: replay
Given a `replay.json`, when `doctor` runs (either `--for`), then exit 0 naming `simon.replay.v1 1.0.0` when the
schema holds and the lengths of `expected`, `expected_t` and `exp_to_fol` and of `follower` and `follower_t`
agree, every `exp_to_fol` and bone index is in range and both `t` lists strictly increase; otherwise exit 1 naming
the field (`journey-followup.md` AC-R03; `tests/test_doctor.py`).
### AC-C10: #34 plain errors
Given `PART3_DIR` pointing at a checkout that lacks a copied file, when `make contracts-check` runs, then
it exits 2 with a plain message naming the missing upstream path, never a traceback (TICKET-004).

### Rule-Based ACs
- AC-C-NFR-01: `contract` and `doctor` run offline. Verification: test with sockets blocked.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| Unknown `--schema` | exit 2 | `part5 contract: no schema named <x>; one of analysis, input-animation, ...` | AC-C04 |
| Not JSON | exit 2 | `part5 doctor: <file>: not JSON (<line>:<col>)` | AC-C09 |
| Schema violation | exit 1 | `<field path>: <what>; fix: <option>` | AC-C06 |
| Hand-off object or framed message | exit 1 for part5 | `Part 6 hand-off; fix: download files.animation and pass it as --expected` | AC-C07 |
| Part 2 `pose3d.json` | exit 1 | `Part 2 pose3d.json; fix: run Part 3 --view part5` | AC-C11 |
| Missing upstream copy in `contracts-check` | exit 2 | `contracts-check: <repo> has no <path> at <commit>` | AC-C10 |

## Edge Cases
- A `simon.skeleton.v1` file not written by Part 3 (Part 4's own fixtures): named as such, still judged.
- An `analysis.json` of schema 1.0 (no `schema_version`): accepted for Part 7 with a note that `joints`
  is absent and the viewer's fallback mapping applies (ADR-0006).
- `labels.json` of Part 3's kit (`simon.part3.follower_labels/1`): named as Part 3's labels, validated
  against `contracts/part3/follower-labels.schema.json`.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | `make check-5-contract` | under 2 minutes | AC-C02 |
| Reliability | Determinism | byte-identical rebuilds | AC-C03 |
| Compatibility | Python 3.10 or later | `uv run` | all |

## Negative Requirements
- MUST NOT fetch a URL (hand-off files included). Why: Part 5 is offline and a black box.
- MUST NOT import or copy another part's code; copies are files under `contracts/part3|part4/` only.
- MUST NOT edit a copied schema by hand; `make contracts-sync` refreshes them.

## Non-Requirements
- Building Part 7. Analysing Part 2's `pose3d.json` (`doctor` names it and points to Part 3; it never
  validates its fields).

## Assumptions
ASM-005 (Part 7 reads `status` first) and ASM-012 (the Part 6 hand-off shape), `docs/assumptions/`.

## Delivery Verification Plan
- `make check-5-contract` 0, `make test-contract` 0, `make test` 0.
- `python -m part5 contract` and `doctor` frames recorded as uc-integration-contract evidence.
- The neighbour check (`neighbour-check.md`) runs `doctor` on Parts 3 and 4's current files.

## Dissent Review
### Concern 1: two validators (schema and loader) double the maintenance
Kept: the schema is what other parts can run without Python; the loader is what Part 5 actually does.
`check-5-contract` fails on any disagreement, so drift shows the same day.
### Concern 2: versioning an additive change as 1.1.0 while `format` stays `simon.analysis.v1`
Kept: a format string change would break every v1 reader for fields they may ignore; the schema
version tells a careful reader what to expect.

## Deviations from PRD
None.
