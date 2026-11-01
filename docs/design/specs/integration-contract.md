# Spec: Part 5 integration contract (schemas, compatibility table, `part5 contract`, `part5 doctor`, `make check-5-contract`)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADRs: ADR-0002, ADR-0004, ADR-0006. Tickets: TICKET-004 (lands #34),
TICKET-009, TICKET-010, TICKET-011, TICKET-049. Milestone M1 (stitch-ready, target 2026-10-29).
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
2. Seven schemas and a hand-written loader can drift. Answer: `make check-5-contract` validates every
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
| `analysis` | `contracts/analysis.schema.json` | `1.9.0` (`1.1.0` when this spec was written) | Part 5's output, `simon.analysis.v1` with the additive fields of the master spec, `journey-followup.md`, `foot-keypoints.md` (`diagnostics.feet`), `profiles.md` (`profile`), `near-misses.md` (`diagnostics.near_misses`) and `second-opinion.md` (`phrasing.lang`, `second_opinion`) |
| `input-animation` | `contracts/input-animation.schema.json` | `1.0.0` | expected or follower clip in `simon.animation.v1` (frames, optional `null` joints and `conf`) |
| `input-skeleton` | `contracts/input-skeleton.schema.json` | `1.0.0` | expected clip in `simon.skeleton.v1` (keyframes) |
| `labels` | `contracts/labels.schema.json` | `1.0.0` | `labels.json` of the synthetic sets and the real takes (`label_source` optional) |
| `metrics` | `contracts/metrics.schema.json` | `1.3.0` | the `make check-5` document (`simon.part5.check.v1`, `check-5.md`), with the score report (`gate.sweep`, `report.score`); 1.2.0 adds `report.refusals.gated: false`; 1.3.0 adds `profiles_sha256` |
| `replay` | `contracts/replay.schema.json` | `1.0.0` | the `replay.json` of `part5 analyse --replay` (`simon.replay.v1`, `journey-followup.md` J-3) |
| `input-feet` | `contracts/input-feet.schema.json` | `1.0.0` | the optional feet side file: a Part 2 `pose3d.json` with `extra_joints`, no `format` (`--expected-feet`, `--follower-feet`, ADR-0015) |

Each schema is JSON Schema draft 2020-12 with `$id` `https://github.com/moalborati/simon-part-5-fault-analysis/contracts/<name>.schema.json`
and a top-level `version` string. Extra properties are allowed wherever `docs/schemas.md` allows them.
The copies from Parts 3 and 4 stay under `contracts/part3/` and `contracts/part4/` exactly as #34 ships
them; `contracts/sources.json` and `sources.lock.json` record their commits.

## Compatibility table (in `CONTRACT.md`, printed by `part5 contract`)
| Producer | File | `format` | Part 5 role | Verdict | Fix | Checked against |
|---|---|---|---|---|---|---|
| Part 2 | `pose3d.json` | `part2.pose3d/2026-10-28` (Part 3 CONTRACT.md) | none | rejected | as a clip it is rejected: run Part 3 `--view part5` on it; `doctor` accepts it as the optional feet side input (exit 0, with a note that it is not a clip) and exits 1 only when it is not that either, with "run Part 3 --view part5" | Part 2 2e06d58 |
| Part 2 foot points | `pose3d.json` with `extra_joints` | `part2.pose3d/2026-10-28` (Part 2 CONTRACT.md "Extra joints (optional)") | optional feet side input (`--expected-feet`, `--follower-feet`) | works with an option | pass the trainer's and the follower's own Part 2 `pose3d.json` beside the Part 3 `skeleton.json` (Part 3 does not carry `extra_joints`); a file without them is accepted and the foot measures are hidden, with the reason in `diagnostics.feet`; `doctor` accepts it with a note | Part 2 e8ac336 |
| Part 3 `run --view part5` | `skeleton.json` | `simon.animation.v1` | follower or expected | works |  | Part 3 fd96379 |
| Part 3 `run --view part4` | `skeleton.json` | `simon.skeleton.v1` | expected | works |  | Part 3 fd96379 |
| Part 3 native | `skeleton.json` | `simon.skeleton/1` (no `format`) | none | rejected | rerun Part 3 with `--view part5` | Part 3 fd96379 |
| Part 4 | `animation.json` | `simon.animation.v1` | expected | works |  | Part 4 dc3d9f2 |
| Part 6 Follow hand-off (event detail) | `{v: 1, id, name, category, link, manifest, files: {keyframes, skeleton, animation, video}}` | none | none | works with an option | download `files.animation` and pass it as `--expected`; Part 5 never fetches URLs | Part 6 fc3249a |
| Part 6 Follow hand-off (framed message, Part 6 CONTRACT.md "The hand-off to Part 7") | `{v: 1, id, name, category, link, manifest, files: {keyframes, skeleton, animation, video}}` with `type: "simon:follow"` | none | none | works with an option | download `files.animation` and pass it as `--expected`; Part 5 never fetches URLs | Part 6 fc3249a |
| Part 5 | `analysis.json` | `simon.analysis.v1` | output for Part 7 | works | Part 7 reads `warnings` and `score` (ADR-0012); each fault's `confidence` is a number or the literal `"low"`; the 1.2.0 to 1.9.0 fields (`at_s`, `text_timed`, `lateral`, `score`, `cue`, `insights`, `diagnostics.feet`, `profile`, `diagnostics.near_misses`, `phrasing.lang`, `phrasing.faults[].text`, `second_opinion`) are all optional; 1.8.0 adds `diagnostics.near_misses` (the candidate faults detection considered and dropped: near misses additive, optional, for debugging, never shown to the follower); 1.9.0 adds `phrasing.lang` and `phrasing.faults[].text` and `.lang` (show `text`, the line in the follower's language) and the top-level `second_opinion` (Muse Spark's view of the take, label it as the model's opinion; the score never reads it), `score.uncapped` (the value and grade before a warning capped them at 59 F, present only when the cap lowered them) and the optional top-level `source` (the producing part; absent means part5) with the warning code `no_person` (written only by Part 7's own analysis, never by Part 5); a foot fault (measure `foot_rotation` or `ankle_inversion`, body part `feet`) needs a reader built on the 1.6.0 schema, whose `measure` and `body_part` enums list them; read a score within its `profile` | Part 5 (this repo) |
| Part 7 own analysis for a take with no person | `analysis.json` with `source: "part7"` | `simon.analysis.v1` (`schema_version` 1.4.0, as Part 7 writes it today) with `source` and the warning `no_person` (schema 1.9.0) | none | works | Part 7 writes it when Part 2 finds nobody in the take: `source` `part7`, the warning `no_person`, `faults: []`, `expected` and `follower` with their real `path`, a score of 0 (F) and no `match`, because nothing was compared; `part5 doctor <file> --for part7` accepts it and notes that nothing was looked at; Part 5 never writes `no_person` or `source` | Part 5 TICKET-048 (the document Part 7 described, moalborati/simon#61) |
| Part 5 `analyse --replay <replay.json>` | `replay.json` | `simon.replay.v1` | output for Part 7 | works | optional second file; `expected_t` and `follower_t` carry the times in seconds; check it with `part5 doctor <replay.json>` | Part 5 (this repo) |
| Part 5 `analyse --live` | live mode (`--live`, `serve --live`, `SIMON5_LIVE=1`, `META_LIVE=1`) | `simon.analysis.v1` with `phrasing.selected_by` `live` | option for Part 7 | works with an option | needs the Baseten key file on the host that runs Part 5; without it each fault keeps its timed template line (`fallback_reason: "no key"`); the template stays the default for tests and `make check-5` | Part 5 (this repo) |
| Part 5 `analyse --lang` | the follower's language (`--lang <bcp47>`, API field `lang`) | `simon.analysis.v1` 1.9.0 with `phrasing.lang` | option for Part 7 | works with an option | pass the follower's BCP 47 tag; with `--live` Muse Spark writes each line in it and `phrasing.faults[i].text` holds it (`phrasing.faults[i].lang` says the line's language: `en` for a line that fell back); an unlisted tag falls back to English and `phrasing.lang_requested` keeps it; probe `part5 analyse --help` for `--lang` | Part 5 (this repo) |
| Part 5 `analyse --expected-video --follower-video` | the two clips as video files, with `--live` | `simon.analysis.v1` 1.9.0 with `second_opinion` | option for Part 7 | works with an option | pass the teacher's and the student's video with `--live`; the block is `ok`, `fallback` or `skipped` with a `reason`; show `verdicts` (agree or dispute per `fault_index`, with `note`) and at most 2 `observations` (`at_s`, `text`), labelled as the model's opinion; needs the Meta Model API key file on the host that runs Part 5 | Part 5 (this repo) |
| Part 5 `analyse --profile` | analysis profile (`--profile {dance,rehab,fitness}`, API field `profile`) | `simon.analysis.v1` 1.7.0 with `profile` | option for Part 7 | works with an option | pass the operator's mode as `--profile` or as the `profile` field of `POST api/analyse`; probe `part5 analyse --help` for `--profile` before relying on it; omitted means `fitness`, the analysis as it was; every document names its `profile`, and a score is read within one profile (a dance 84 and a fitness 84 differ) | Part 5 (this repo) |
| Part 5 | `part5 analyse` exit code | 0 analysis written (with or without warnings), 1 unreadable or invalid input file or write error, 2 usage; 3 is no longer used (ADR-0012) | for Part 7 | works with a mapping | Part 7 at 90aa473 expects the family codes 0 written, 1 not writable, 2 input or option breaks the contract (Part 3 CONTRACT.md, row for Part 7): 0 is "written" (read `warnings`), 1 and 2 are failures; 3 is no longer produced | Part 7 90aa473 (as Part 3 CONTRACT.md records it) |
| Part 5 | `labels.json` | none | evaluation | works |  | Part 5 (this repo) |

The last column is the producer commit each row was checked against (from `contracts/sources.lock.json` and the
neighbour check; never typed from memory).

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
  `simon.skeleton/1 (Part 3 native)`, `simon:follow v1 hand-off (Part 6)` (event detail or framed message), `part2.pose3d (Part 2)`, `simon.analysis.v1 1.9.0`,
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
Given `contracts/`, when listed, then the seven schemas exist (the first six, and `input-feet` for the optional
feet side file, ADR-0015), each with `$id` and `version`, and each is a valid draft 2020-12 schema.
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
`pose3d.json`, accepts it as the optional feet side input (ADR-0015) and exits 0 with a note that it is not a clip
and where the body comes from ("run Part 3 --view part5"). A `pose3d.json`-like file that is not that shape either
exits 1 and says "run Part 3 --view part5".
### AC-C12: exit-code mapping published
Given `python -m part5 contract`, then the table carries the `part5 analyse` exit-code row with the
Part 7 mapping, and `CONTRACT.md` states that 0 means an analysis was written and that exit 3 is no longer
produced (ADR-0012).
### AC-C13: replay
Given a `replay.json`, when `doctor` runs (either `--for`), then exit 0 naming `simon.replay.v1 1.0.0` when the
schema holds and the lengths of `expected`, `expected_t` and `exp_to_fol` and of `follower` and `follower_t`
agree, every `exp_to_fol` and bone index is in range and both `t` lists strictly increase; otherwise exit 1 naming
the field (`journey-followup.md` AC-R03; `tests/test_doctor.py`).
### AC-C14: Part 7's no-person analysis and the uncapped score (analysis 1.9.0, TICKET-048, Part 7 TICKET-155)
Given Part 7's own analysis for a take in which Part 2 found nobody (`schema_version` 1.4.0, `source` `part7`, the
warning `no_person`, `faults` `[]`, `expected` and `follower` with their `path`, a score of 0 grade F, no `match`;
the committed example is `fixtures/input/contract/part7/analysis.no-person.json`), when the schema, `part5.output`
and `part5 doctor --for part7` read it, then it validates and the doctor exits 0 with the warning listed and two notes
(who wrote it; that `faults: []` means nothing was looked at). `source` is an optional non-empty string (absent means
`part5`); `no_person` is a `warnings[].code` that Part 5 never writes (`pipeline.WARNING_ORDER` and the goldens do not
carry it); a `match` is required for every other warning code and checked when present. `score.uncapped`
(`{value, grade}`, written only when the warning cap lowered the value) validates and the doctor notes the value it
had before the cap. `tests/test_part7_no_person.py`.
### AC-C15: the fields Part 7's takes-over-time report reads (TICKET-049, Part 7 TICKET-183)
Part 7 reads these fields across many takes, without importing Part 5. For every analysis schema version from `1.5.0`
(`1.5.0`, `1.6.0`, `1.7.0`, `1.8.0`, `1.9.0`; a new version added to `contracts/analysis.schema.json` fails the test until
it is listed), `tests/test_contract_part7_history.py` pins each field's name, JSON type and meaning in the schema and in a
document derived from the committed goldens (`fixtures/output/analysis*.example.json`) by removing what the later
versions added, and pins which fields the schema leaves optional and what their absence means:

| Field | JSON type | In the schema | Since | Meaning; what absence means |
|---|---|---|---|---|
| `faults[].measure` | string, one of the schema's `measure` values | required | 1.0.0 (`foot_rotation`, `ankle_inversion` 1.6.0) | what differed, side-less (`upper_arm_out`, `knee_flexion`, ...) |
| `faults[].side` | `left`, `right`, `both` or `center` | required | 1.0.0 | the subject's own side |
| `faults[].at_s` | number | optional | 1.2.0 | seconds on the follower file's own clock: `follower_t_s[0]` rounded half up to 0.1. Absent: the fault is untimed (a document before 1.2.0); leave it off a time axis |
| `faults[].follower_t_s` | `[start, end]` numbers | optional | 1.2.0 | seconds on the follower file's own clock at `follower_frames[0]` and `[1]`. Absent as for `at_s` |
| `faults[].text_timed` | non-empty string | optional | 1.2.0 | the timed words plus ` at <at_s> s`. Absent: show `text` |
| `faults[].cue` | string of 1 to 6 words | optional | 1.5.0 | what to do, an imperative. Absent: a document before 1.5.0 |
| `score.timeline[].misses[].cue` | string of 1 to 6 words | optional | 1.5.0 | the `cue` of the fault the miss came from; `misses` exists on a compared window only. Absent: before 1.5.0 |
| `score.value` | integer 0 to 100 | optional (`score`) | 1.2.0 | the take's score; never null from 1.4.0; capped at 59 when `warnings` exist. `score` absent: the producer does not score |
| `score.grade` | `A`, `B`, `C`, `D` or `F` | optional (`score`) | 1.2.0 | the grade of `value`, within the document's `profile` |

The follower's duration has no field in `analysis.json` (the `follower` object is `{path}` plus whatever ids the caller
passed in, such as `take_id`). The test pins what exists: `score.timeline[-1].t_s[1]`, the end of the compared span on
the follower file's clock (equal to the duration when the whole clip was compared, less when the follower stood still
at the end), and, from the optional `replay.json`, `follower_t[-1]`, the last frame time of the follower file. A
dedicated field is an additive change to `part5/` and is not made by TICKET-049.
### AC-C16: the student-words file (TICKET-049)
Given `contracts/student-words.json` (`format` `simon.student-words.v1`, `version`, `banned`, `praise`, the rules that
apply them, `ignored_characters`, `sources` and `lists_sha256`), when `scripts/make_student_words.py` (`make
student-words`) runs, then it writes the file from Part 5's own constants, imported and never copied: `banned` is the
word stems of `part5.opinion.guard.BANNED`, `praise` is `part5.phrasing.template.PRAISE_PHRASES` in order and
`ignored_characters` are the zero-width characters `template` reads past. `tests/test_student_words.py` fails when the
committed file differs from what the script generates, so the file cannot drift from the validator, and checks that a
matcher built from the file alone agrees with the validator on a set of lines. `--check` exits 1 on a difference. The
file is a published contract (`contracts/**`, written by the published `scripts/make_*.py`) and is listed in
`CONTRACT.md`; it adds no schema and no `part5/` code.
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
| Part 2 `pose3d.json` | exit 0 with a note (a feet side input, not a clip); exit 1 when it is not that shape either | `Part 2 pose3d.json; fix: run Part 3 --view part5` | AC-C11 |
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
- `tests/test_contract_part7_history.py` and `tests/test_student_words.py` 0 (AC-C15, AC-C16); `python3 scripts/make_student_words.py --check` 0.
- `python -m part5 contract` and `doctor` frames recorded as uc-integration-contract evidence.
- The neighbour check (`neighbour-check.md`) runs `doctor` on Parts 3 and 4's current files.

## Dissent Review
### Concern 1: two validators (schema and loader) double the maintenance
Kept: the schema is what other parts can run without Python; the loader is what Part 5 actually does.
`check-5-contract` fails on any disagreement, so drift shows the same day.
### Concern 2: versioning an additive change as 1.1.0 while `format` stays `simon.analysis.v1`
Kept: a format string change would break every v1 reader for fields they may ignore; the schema
version tells a careful reader what to expect.

## Amendments
- 2026-10-31 (TICKET-042, `docs/design/specs/profiles.md`): the analysis schema is `1.7.0` (`profile`, always written, optional
  in the schema) and the metrics schema `1.3.0` (`profiles_sha256`); the table has a row "Part 5 `analyse --profile`" and
  the analysis row names `profile`; `part5 doctor --for part7` notes the profile ("scores compare within one profile",
  or "read it as fitness" for a document before `1.7.0`); `CONTRACT.md` carries the same rows and a Part 7 duty.
- 2026-10-31 (TICKET-045, TICKET-046, `docs/design/specs/second-opinion.md`): the analysis schema is `1.9.0` (`phrasing.lang`, `phrasing.faults[].text` and `.lang` in every new document; `second_opinion` when clips were given). Two rows added: `analyse --lang` and `analyse --expected-video --follower-video`.
- 2026-11-01 (TICKET-048, Part 7 TICKET-155; AC-C14): the same analysis schema `1.9.0` also carries the optional top-level
  `source`, the `no_person` warning code (Part 7's own analysis only; `match` not required when it is the only code) and
  `score.uncapped`. One row added: "Part 7 own analysis for a take with no person"; the analysis row names the three;
  the table above is the one `part5 contract` prints (the `--lang` and video rows, missing from this copy, are in it).
- 2026-11-01 (TICKET-049, Part 7 TICKET-183; AC-C15, AC-C16): no schema change. The fields of Part 7's takes-over-time
  report are pinned for every analysis version from `1.5.0` (`tests/test_contract_part7_history.py`) and named in
  `CONTRACT.md` (Part 7's duty 10); `contracts/student-words.json` is generated from the validator's own word lists
  (`scripts/make_student_words.py`, `make student-words`, `tests/test_student_words.py`). The follower duration has no
  analysis field; the test pins the two places it can be read.
- 2026-10-31 (TICKET-043, `docs/design/specs/near-misses.md`): the analysis schema is `1.8.0` (`diagnostics.near_misses`, written
  whenever the take was compared, optional in the schema); the analysis row says so ("near misses additive, optional");
  `part5 doctor --for part7` notes how many near misses a document lists; `CONTRACT.md` carries the same row and sentence.
- 2026-10-31 (final QA): the two tables above are the ones `part5 contract` prints: seven schemas (`input-feet` added),
  the rows "Part 2 foot points" and "Part 5 `analyse --profile`", the current `--replay` and `--live` rows and the
  "Checked against" column.

## Deviations from PRD
None.
