# Spec: Journey follow-up J1 (densified part4 keys; `run --out` creates its folder)

> Copy of the maintainers' working spec `docs/specs/journey-followup.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Status: Accepted
Date: 2026-10-30
Linked PRD: none. Requirements source: operator directive of 2026-10-30 (the full Simon app journey: a trainer
records a movement, others view it in the cloud, a viewer records or uploads their own take, the pipeline analyses
faults, 3D replays to rotate and compare, timed feedback, a score out of 100 with a grade from A to F) and the
journey research of 2026-10-30. Parent spec: `docs/design/specs/integration-contract.md` ("Keyframes input", "Contract and
doctor", "Conformance kit").
Request Type: feature-mod (J-1) and bug-fix (J-2)
Risk Level: routine (additive option and field; default output byte-identical)
Tickets: TICKET-036 (J-1), TICKET-037 (J-2). Milestone: J1.

## Overview
In the journey a trainer records a movement once and Part 1 picks a few named key moments from it. Part 4 animates
between keys, so a `--view part4` file built from those few keys strays from what the trainer did. The research run
of 2026-10-30 reported, for Part 1-shaped sparse keys, a median stray of 0.257 m and a worst of 0.540 m, against a
median of 0.006 m and a worst of 0.024 m for `every:10` (session scratchpad, `journey-c/`). J-1 adds
`--keyframes-densify every:<n>`: keep every named key of the given `keyframes.json` and add a key every n ticks
between them, never two keys on one tick. The trainer's named moments survive and the animation follows the take.
J-2 fixes two journey papercuts: `run --out a/b/skeleton.json` exits 1 "cannot write" when `a/b/` does not exist,
and the README's Part 5 follower example omits `--fps 30`.

## Why This Is Wrong (Dissent-First)
1. More keys make the long-way check (180 degree rule) more likely to pass, not less, but they also make every
   `part4` file larger: on the 213-tick research clip, `every:10` wrote 23 keys where Part 1 gave 3. Answer: size grows linearly
   with `frame_count / n`, and n is the caller's choice; the default stays off, so no file changes unasked.
2. The research medians do not reproduce under a simple metric. A nearest-native-frame distance over every joint and
   frame, computed on the same research files, gives a median of 0.076 m and a worst of 0.540 m for the 3 Part 1 keys,
   and a median of 0.004 m and a worst of 0.041 m for `every:10`. Answer: TICKET-036 writes the metric down
   (AC-D09) and records both the brief's numbers and the numbers it measures; the decision does not depend on which
   median is right, since both show the sparse file strays by an order of magnitude more.
3. Filler keys carry generated names (`key_<index>`), which a reader could mistake for trainer-named moments.
   Answer: `timeline.densify.added` counts them, and the named keys keep their own names.
4. An environment variable that changes output is a hidden switch. Answer: the same precedence as the body profile,
   and `timeline.densify.selected_by` records the channel in every densified file.

## User Story
As Part 7, I want Part 4's animation of a trainer's movement to follow the recording while keeping the key moments
Part 1 named, so that the expected clip a viewer compares against is the movement the trainer made.

### Jobs-to-be-Done
- Functional: one option turns sparse named keys into a dense, faithful key set.
- Emotional: the trainer sees their own movement, not a smoothed guess.
- Social: the expected clip can be trusted as the reference others are scored against.

## API / Interface Contract

### Command line (additions)
```
python3 -m part3 run --in <pose3d.json> --out <path> --view part4 --keyframes <keyframes.json>
    [--keyframes-densify every:<n>|off] [--keyframes-out <path>] ...
```
| Value | Meaning |
|---|---|
| `every:<n>` | n is a whole number from 1 to 300 (the same check and message as `--keyframes every:<n>`) |
| `off` | no densifying; lets the flag override the environment or the config file |

### Selection precedence (first set wins; same order as the body profile)
1. `--keyframes-densify`
2. environment variable `PART3_KEYFRAMES_DENSIFY`
3. config file table `[keyframes]`, key `densify` (`--config`, else `PART3_CONFIG`, else `./part3.toml`)
4. Python API keyword `keyframes_densify=`
5. default: off

The flag refuses misuse (below). The environment, the config file and the API keyword apply only when the run is
`--view part4` with a keyframes file; for any other view, or for `--keyframes every:<m>`, they are ignored, so a
globally set `PART3_KEYFRAMES_DENSIFY` never breaks a `part5` or native run. The staging server reads neither the
environment nor `part3.toml` (unchanged rule) and never densifies.

### Densify rule (`part3.keyframes.densify(timeline, n, selected_by) -> Timeline`, pure)
- Anchors: the ticks of the named keys that survived `_assign` (dropped keys stay dropped, with their reasons),
  plus tick 0 and the last tick `frame_count - 1`.
- Between each pair of consecutive anchors `a < b`, add ticks `a + n, a + 2n, ...` strictly below `b`.
- Tick 0 and the last tick become filler keys when no named key sits there, as `every:<n>` does today.
- Fillers are named `key_<index>`; named keys keep their names. No tick holds two keys.
- The part4 view then builds every key as today: a filler whose nearest input frame has no person is dropped with
  the existing missing-person reason, like any key.
- `n` larger than every gap adds only the end ticks.

### Output (additive; `simon.skeleton.v1` keeps its version under the version policy)
`timeline.densify`, present only when densifying ran: `{"every": <n>, "selected_by": "flag"|"env"|"config"|"api",
"added": <number of filler keys written>}`. Without densifying the file is byte-identical to today's (every
existing golden stays). `contracts/skeleton-part4.schema.json` gains the optional `timeline.densify` object
(`every` integer 1 to 300, `selected_by` enum, `added` integer 0 or more). The `--keyframes-out` companion lists every
key, fillers included, unchanged in shape.

### Python API (keyword-only additions; today's calls keep working)
```python
part3.views.render(skeleton, view="native", *, keyframes=None, keyframes_person=None, max_frames=None,
                   keyframes_densify=None, env=None, config=None) -> dict
part3.keyframes.densify(timeline, n, selected_by) -> Timeline
part3.keyframes.resolve_densify(flag=None, api=None, env=None, config=None) -> (n | None, selected_by | None)
part3.config.Config.densify  # the [keyframes] densify value, or None
```
`env` None means `os.environ`; `config` None discovers, False reads no file (the same contract as
`profiles.resolve`).

### Contract, doctor and conformance kit
- `CONTRACT.md` "The command line" table gets a `--keyframes-densify` row; the `part4` view paragraph says how to
  densify; `contracts/compatibility.json` gets a row: Part 3 `skeleton.json` (part4 view, densified) to Part 4,
  `works`, evidence the new golden. The generated tables are rebuilt with `python3 -m part3.contract build-docs`.
- `python3 -m part3 contract` prints the new row; `--json` carries it.
- `python3 -m part3 doctor <file> --for part4` adds one note (never a rejection) when consecutive keys are more than
  10 ticks apart: `keys are up to <g> ticks apart; Part 4 animates between them, so a fast movement strays from the
  take; rerun with --keyframes-densify every:10`. A densified file gets the note `densified every <n> ticks
  (<added> keys added, selected by <channel>)`.
- Conformance kit: new case `view-part4-part1-keyframes-densify-10`
  (`--view part4 --body part4-rig --keyframes inputs/keyframes.part1.json --keyframes-densify every:10
  --keyframes-out keyframes.json`), its golden built with `python3 -m part3.conformance build`;
  `make check-3-contract` rebuilds it byte for byte with every `PART3_` variable stripped (unchanged runner rule).

### J-2: `run --out` creates its folder
`part3 run` creates the parent folders of `--out` and of `--keyframes-out` before writing (`_write(..., mkdir=True)`
for single-file runs, as `--all-people` already does). Exit codes stay: 0 written, 2 input or option, 1 not
writable (for example a parent path that is a file, or a folder without write permission). Any folder this call
created stays when the write fails afterwards; files are still all-or-nothing.
README "Integration" step 3, Part 5 follower example, becomes:
```
python3 -m part3 run --in pose3d.json --out follower/skeleton.json --view part5 --fps 30
```
with one line saying `--fps 30` puts the follower on a uniform 30 fps clock.

## Acceptance Criteria
### AC-D01: named keys kept, fillers added between
Given a 213-tick timeline with named keys at ticks 60, 75 and 90, when densified with n = 10, then the keys are
ticks 0, 10, 20, 30, 40, 50, 60, 70, 75, 85, 90, 100, ..., 210, 212; ticks 60, 75 and 90 keep their names; every
other key is `key_<index>`; no tick repeats. (Fillers restart from each anchor: 75 to 90 gives 85 only.)
### AC-D02: no duplicate ticks
Given named keys on ticks that are multiples of n (for example 0, 30, 60 with n = 10) and a named key on the last
tick, when densified, then each tick appears once and the named key wins over a filler.
### AC-D03: dropped keys stay dropped
Given a Part 1 file with one key after the clip end and two keys on one tick, when densified, then
`timeline.dropped` lists the same entries and reasons as without densifying, and the dropped ticks are not anchors.
### AC-D04: n bounds and `off`
Given `every:0`, `every:301`, `every:x` on the flag, when run, then exit 2 with `--keyframes-densify every:<v>: n
must be a whole number from 1 to 300`; given `off`, then no `timeline.densify` and output identical to no option.
### AC-D05: misuse refused on the flag only
Given `--keyframes-densify every:10` with `--view part5` or native, then exit 2 `--keyframes-densify only applies to
--view part4`; with `--keyframes every:5`, then exit 2 `--keyframes-densify only applies to a keyframes file
(every:<n> already keys every n ticks)`; both before the input is read. Given `PART3_KEYFRAMES_DENSIFY=every:10`
with `--view part5`, then the run succeeds and the output equals the run without the variable.
### AC-D06: precedence
Given the flag, the variable, `[keyframes] densify` in a config file and the API keyword set to four different
values, when each higher channel is removed in turn, then the next one wins and `selected_by` names it; a bad value
on any channel exits 2 naming that channel (`PART3_KEYFRAMES_DENSIFY: n must be ...`, `<config path>:
keyframes.densify: ...`).
### AC-D07: default output unchanged
Given every existing conformance case, when rebuilt, then every golden is byte-identical (no `timeline.densify`
key), and `make check-3` metrics equal `demo/metrics.json`.
### AC-D08: Part 4's rules hold
Given the densified squat case, then `doctor --for part4` exits 0: key `t` equals `index / 30` within 1 µs, FK within
1 mm, keys strictly increase, the companion `keyframes.json` lists the same indices, the long-way rule holds.
### AC-D09: stray measured and recorded
Given Part 4's animator from a local read-only clone (through `scripts/neighbour-check.sh` or a recorded command; no
Part 4 code imported), the squat input, the conformance Part 1 keys, and the same keys densified every 10, when
each part4 file is animated by Part 4, then `progress/journey-densify.md` records, for both, the median and worst
distance in metres over every animated frame and every joint between Part 4's joint and Part 3's native joint at
the input frame nearest in time (no recentring), with the commands, the Part 4 commit and the exit codes, next to
the research numbers quoted in the Overview. The densified worst must be below the sparse worst.
### AC-D10: contract, doctor, kit
Given the changes, then `python3 -m part3 contract --json` holds the new compatibility row, `CONTRACT.md`'s
generated blocks equal `build-docs` output, `doctor` prints the sparse-keys note on the Part 1 keys golden and the
densified note on the new golden, and `make check-3-contract` exits 0 with 22 cases.
### AC-O01: `--out` folder created
Given `--out <tmp>/a/b/skeleton.json` where `a/` does not exist, when run, then exit 0 and the file exists; the same
for `--keyframes-out <tmp>/k/keyframes.json`. Given a parent path that is an existing file, then exit 1 with
`<path>: cannot write (<reason>)` and no output file.
### AC-O02: README example
Given README "Integration" step 3, then the Part 5 follower line carries `--view part5 --fps 30`, and running it
on `fixtures/input/part2-single/pose3d.json` with `--out <tmp>/follower/skeleton.json` exits 0 and the file
validates against `contracts/animation-part5.schema.json` with a uniform 30 fps clock.

### Rule-Based ACs
- AC-NFR-D01: densify is O(frame_count / n + keys) and adds under 0.5 s to the squat run. Verification: test timing.
- AC-NFR-D02: no new dependency. Verification: inspection of `requirements.txt`.

## Error Cases
| Condition | Behavior | Message format | AC Reference |
|---|---|---|---|
| bad n on the flag | exit 2, nothing written | `--keyframes-densify every:<v>: n must be a whole number from 1 to 300` | AC-D04 |
| bad value in the variable | exit 2 | `PART3_KEYFRAMES_DENSIFY: n must be a whole number from 1 to 300` | AC-D06 |
| bad value in the config file | exit 2 | `<path>: keyframes.densify: expected every:<n> or off` | AC-D06 |
| flag with another view | exit 2 | `--keyframes-densify only applies to --view part4` | AC-D05 |
| flag with `--keyframes every:<m>` | exit 2 | `--keyframes-densify only applies to a keyframes file (every:<n> already keys every n ticks)` | AC-D05 |
| `--out` parent is a file | exit 1 | `<path>: cannot write (<reason>)` | AC-O01 |

## Edge Cases
- One named key: anchors are 0, that key and the last tick (AC-D01 variant in tests).
- A one-tick clip: one key at tick 0, `added` 0 when it is named, 1 when it is not.
- n = 1: a key on every tick; equals `every:1` plus the named keys' names.
- A Part 4 `simon.keyframes.v1` input: densified the same way (its indices are the anchors).
- `--all-people`: densify applies per person, each file records it.
- A filler on a tick where the person is missing: dropped with the existing reason, counted out of `added`.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|---|---|---|---|
| Performance | densify cost | under 0.5 s on the squat | AC-NFR-D01 |
| Security | config and env | read on the CLI and API only; the staging server reads neither | AC-D05 |
| Reliability | errors | plain message, exit 2, nothing written | Error Cases |
| Compatibility | readers | additive optional field; version unchanged by policy | AC-D07 |
| Maintainability | tests | every AC named in a test | all |
| Accessibility | N/A | command line and files only | |

## Negative Requirements
- MUST NOT rename, move or drop a named key. Why: the trainer's moments are the point of Part 1.
- MUST NOT change any output when densifying is off. Why: every golden and consumer stays valid.
- MUST NOT import Part 4 code to measure the stray. Why: black-box rule.
- MUST NOT let an environment variable fail a run of another view. Why: Part 7 sets it once for all calls.

## Compromises
### End ticks are keyed
Short-term: tick 0 and the last tick get filler keys, matching `every:<n>`, so motion before the first named key and
after the last is followed. Long-term: if Part 4 adds hold or extrapolation rules, an option could leave the ends
alone. Trigger: a Part 4 contract change.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `part3/keyframes.py` | `densify`, `resolve_densify` | TICKET-036 | yes |
| `part3/views/part4.py` | `keyframes_densify` option, `timeline.densify` block | TICKET-036 | yes |
| `part3/views/__init__.py` | pass `keyframes_densify`, `env`, `config` to the part4 view | TICKET-036 | yes |
| `part3/cli.py` | `--keyframes-densify` option and checks (TICKET-036); `_write` creates parent folders (TICKET-037) | TICKET-036, TICKET-037 | yes |
| `part3/config.py` | `[keyframes] densify` | TICKET-036 | yes |
| `part3/doctor.py` | sparse-keys note and densified note | TICKET-036 | yes |
| `part3/contract.py` | nothing new in code expected; listed in case the generator needs the new row's evidence | TICKET-036 | yes |
| `part3/conformance.py` | case `view-part4-part1-keyframes-densify-10` | TICKET-036 | yes |
| `contracts/skeleton-part4.schema.json` | optional `timeline.densify` | TICKET-036 | yes |
| `contracts/compatibility.json` | densified part4 row | TICKET-036 | yes |
| `fixtures/conformance/cases.json`, `fixtures/conformance/golden/view-part4-part1-keyframes-densify-10/*` | new case and golden | TICKET-036 | yes |
| `CONTRACT.md`, `README.md`, `part3.toml.example` | option row, precedence, `[keyframes]` table (TICKET-036); follower example `--fps 30` (TICKET-037) | TICKET-036, TICKET-037 | yes |
| `docs/design/specs/integration-contract.md` | "Keyframes input" points at this spec | TICKET-036 | yes |
| `progress/journey-densify.md` | AC-D09 measurement | TICKET-036 | no (firm) |
| `tests/part3/test_keyframes_densify.py` | AC-D01 to AC-D06, AC-D08 | TICKET-036 | yes |
| `tests/part3/test_keyframes_densify_edges.py` | edge cases: filler in a gap, `--all-people`, API keyword, bad config value on a CLI run | TICKET-036 | yes |
| `tests/part3/test_doctor.py`, `tests/part3/test_conformance.py` | AC-D10 | TICKET-036 | yes |
| `tests/part3/test_cli_out_dir.py` | AC-O01, AC-O02 | TICKET-037 | yes |

## Delivery Verification Plan
- `python3 -m pytest tests/part3 tests/neighbour -q` exit 0 (`make test`).
- `make check-3` 0 with metrics equal to `demo/metrics.json`; `make check-3-contract` 0 with 22 cases.
- `python3 -m part3 contract --json` and `doctor --for part4` on the new golden, output recorded in the ticket.
- AC-D09 numbers in `progress/journey-densify.md` with commands and exit codes.
- `firm/staging/staging.sh up simon-part-3` and `verify simon-part-3` 0 (the staging page is unchanged).
- Publish with `scripts/simon-publish.sh --pull`, `--dry-run`, then a real run; `make test` in a fresh clone.

### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|---|---|---|---|
| Command line | pytest, `make check-3-contract` | n/a | TICKET-036, TICKET-037 lane |

### Data
The committed squat (`fixtures/input/part2-single/pose3d.json`) and `fixtures/conformance/inputs/keyframes.part1.json`.

## Dissent Review
### Concern: Part 7 could pass `every:<n>` instead and skip the named keys
True for the animation alone. Kept: the named keys mark the moments Part 1 found (top, bottom of a rep), which Part 6
and the app show by name; densifying keeps them and fixes the stray in one file.

## Deviations from PRD
- The brief asks to "bump each contract additively". Part 3's version policy keeps the version for an added field
  (`CONTRACT.md` "Version policy"), so `simon.skeleton.v1` keeps its version and gains an optional field.
- The brief's environment variable is extended with the config-file key and the API keyword, because "the existing
  precedence" for the body has those channels; `off` is added so a flag can override them.
