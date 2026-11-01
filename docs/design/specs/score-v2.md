# Spec: score v2 (simon.score.v2): misses weighted by the trainer's range, a ceiling for a take that reports a fault
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-31
Linked PRD: none (TICKET-047, stakeholder-proxy ruling 2026-11-01T05:00Z)
Linked CRD: none
Request Type: feature-mod
Risk Level: medium
Master spec: `journey-followup.md` (J-4, the score). ADRs: ADR-0018 (this change), ADR-0007 (the v1 curve, amended),
ADR-0013 (windows), ADR-0012 (the warning cap), ADR-0003 and ADR-0017 (detection seeds, untouched). Ticket: TICKET-047.

## Overview
`simon.score.v2` is v1's formula with a weight on each miss and a ceiling for a take that reports a fault. A miss costs
`penalty(r) * (0.5 + 0.5 * dur) * coverage * w`, where `w` rises from `range_floor` to 1 as the trainer's range of the
missed measure in the window rises to `range_full` (3) detection thresholds. A take whose `faults` list is not empty
scores at most `fault_cap` (89), and says so in the new field `score.fault_cap`. `score.uncapped` holds the value before
every cap. Detection, its thresholds and `detection_sha256` are not touched. The analysis schema goes to 1.10.0.

## Why This Is Wrong (Dissent-First)
1. **The weight punishes the wrong thing.** A measure the trainer holds still is where a posture fault shows. Answer:
   the floor (fitted on seed 5 so doubles stay at C or lower) keeps a posture fault costly; the direction is the
   ruling's.
2. **The ceiling hides a small fault behind the same B as a large one.** Answer: ruled; the points under 89 still rank
   takes, and the timeline still shows each miss.
3. **A new field in a score block Part 7 already parses.** Answer: additive, optional, `capped_by` untouched, schema
   1.10.0 with a sample document (AC-V2-12).

## User Story
As Part 7, I want a take that reports a fault never to read A, and a fault on a measure the exercise does not move not to
read as a heavy miss, so that the grade agrees with the fault list the follower sees.

## Acceptance Criteria
### AC-V2-01: the weight
Given a v2 block and a fault on a measure whose expected series moves `u` thresholds in the window
When the window is scored
Then the miss costs `penalty * (0.5 + 0.5 * dur) * coverage * min(1, max(range_floor, u / range_full))`, and the window
value and `components.faults` add up from those costs (`tests/test_score_v2.py`).

### AC-V2-02: which series, and when the range is unknown
Given a fault with side `left`, `right`, `both` or `center`
When its trainer series is looked up
Then it is `{side}_{measure}`, the larger range of the two sides, or the bare name. The foot measures are looked up the
same way: the trainer's foot series (`PipelineResult.foot_expected`, the compared foot measures on the expected clip's own
frames; a rep take's reference rep holds its slice in its reference measures) is part of the score's input beside the
body measures. A fault whose series is not in the score's input (no feet file, a foot measure that was not compared) or has
no finite value in the window has `w` 1. Detection is unchanged by this input
(`tests/test_detection_baseline.py`, `tests/test_score_v2.py`).

### AC-V2-03: the window is the window
Given a take scored in windows (ADR-0013)
Then the range is taken over that window's expected frames; a rep take uses the reference rep's frames.

### AC-V2-04: the ceiling and its field
Given a v2 take whose `faults` list is not empty
Then `score.value` is at most 89, `score.fault_cap` is the integer 89 (whether or not it lowered the value), and
`capped_by` is absent unless a warning capped the score. Given a take with no faults, `fault_cap` is absent and the value
is not capped. Under a v1 block no take has a `fault_cap`.

### AC-V2-05: `uncapped` is the value before every cap
Given a faulted take with no warning whose mean of windows is above 89
Then `value` is 89, `uncapped` is `{value, grade}` of the mean before the cap and there is no `capped_by`. Given a
warning as well, `uncapped` is still the value before the first cap and `capped_by` names the warning codes only.

### AC-V2-06: the mean of the windows
The take is the mean of its compared windows (ADR-0013); the ceiling is applied to that mean and not to a window, and no
worst-window rule exists.

### AC-V2-07: v1 stays reproducible
`part5/rules.json` `score.v1` hashes to the `params_sha256` recorded for seeds 47 and 53, and scoring with it gives
`simon.score.v1` values with no `fault_cap`. The v2 block repeats v1's `base`, `slope`, `cap`, `z0`, `z1`, `s_max` and
`bands` at its top level and they are equal.

### AC-V2-08: calibration
`range_floor` is the value `score.choose_floor` picks from `score_report.measure_floors` (the seed 5 takes through the
pipeline, the sweep included) under the rule in ADR-0018, and the shipped block equals the one `score_report.calibrate_set`
returns for rules that ship the v2 form. On seed 5: every correct good-light take is an A, the worst single good-light fault is 70 or above,
every good-light double that is reported exactly is 75 or below, and the sweep never rises.

### AC-V2-09: the freeze
Given a v2 `score` block
Then `make check-5` exits 2 unless `fixtures/score-heldout.json` has a v2 entry in `freezes` whose `params_sha256` is the
block's, and exits as it did with it. A v1 block is checked against the newest v1 attempt as before.

### AC-V2-10: seeds 59 and 61
`make score-heldout SEED=59` exits 2 until a v2 freeze whose hash is the shipped block's exists, and runs once it does;
`SEED=61` exits 2 as reserved. Seeds 47 and 53 stay refused as recorded.

### AC-V2-18: the score code is frozen with the params
`make score-heldout SEED=59` also exits 2 unless the freeze entry names its `freeze_commit`, that commit is in the history, the
working tree is clean (tracked changes anywhere, untracked files under the code paths) and `git diff <freeze_commit> HEAD --
<code paths>` is empty; the code paths are `part5`, `scripts`, `contracts`, `fixtures/input/expected`,
`fixtures/input/expected-feet`, `pyproject.toml` and `uv.lock`. The commit that records the freeze touches
`fixtures/score-heldout.json` and `docs/thresholds.md` only, so it is allowed. It also exits 2 when the record holds more than
one v2 freeze entry, and when `out/score-heldout/seed-59/` already exists (one freeze, one generation). Tested with a stubbed
git and with a real temporary repository (`tests/test_score_heldout.py`).

### AC-V2-19: a failed seed 59 is on the record
The script prints `scored_at` (`git rev-parse HEAD`), `holds` from the JSON report (`score_report --json-out`) and the exact
JSON line to append to `attempts` (`version` `simon.score.v2`, `freeze_commit`, `params_sha256`, `scored_at`, `holds`, the
commands, the labels hash, slices, targets). `make check-5` exits 2 for a v2 block whose recorded v2 attempt has `holds` false
or does not record it, with a message pointing to `make score-fallback`; an attempt is v2's when it says so, is for seed 59 or
carries the v2 freeze's hash, so a failed attempt recorded without its `version` is caught; a v1 block is never judged by a v2
attempt (`tests/test_check_score.py`, both branches on simulated records).

### AC-V2-11: the targets report, and it fails closed
`python -m part5.score_report --set <dir>` prints, for a v2 block, the five targets of ADR-0018 with the takes that
break each, the takes whose reported faults differ from their labels, the strict slice verdicts beside them and the
comparability sentence (what a pass shows). A target with no judged take does not hold (stakeholder-proxy ruling of
2026-11-01T05:45Z, ADR-0003 #36): when target 1, 3, 4 or 5 has `n` 0, or the sweep was not run, the summary says `all five
hold: no` and the JSON `targets_v2` carries `holds: false` (`tests/test_score_v2.py`).

### AC-V2-14: going back to v1 is a tested command
`make score-fallback` (`scripts/make_score_fallback.py`) turns a tree that ships v2 into a tree that ships v1: the
`score` section of `part5/rules.json` becomes its `v1` block (every other key as it was, the detection hash unchanged), the
v2 sample is removed, the goldens and the fitness baseline are written again; `fixtures/score-heldout.json` is not touched.
The tests that depend on the shipped version read `tests/shipped_score.py`, so `make test` exits 0 on the result, and
`part5.check.recorded_score_hash` finds `e818635b...` for a v1 `make check-5` with the v2 freeze and a seed 59 attempt in the
record (`tests/test_score_fallback.py`; the proof on a copy of the tree is in `docs/thresholds.md`).

### AC-V2-15: the committed record survives seed 59
No test of `fixtures/score-heldout.json` depends on seed 59 being absent: the v1 attempts are the ones of seeds 47 and 53,
and `check_seed("59")` is "already recorded" once an attempt for it exists (`tests/test_score_heldout.py`,
`tests/test_score_v2.py`, on the simulated record in `tests/test_score_fallback.py`).

### AC-V2-16: the zero block says its ceiling
A take with faults on which nothing could be measured (value 0, no window compared) carries `fault_cap` 89; a take without
faults does not (`tests/test_score_v2.py`).

### AC-V2-17: the doctor names the score version
`part5 doctor` notes `score version <version>: score.value compares only within one score.version`, and CONTRACT.md duty 10
says so (`tests/test_doctor.py`).

### AC-V2-12: contract
`contracts/analysis.schema.json` 1.10.0 accepts `score.version` `simon.score.v2`, `score.fault_cap` and the wider
meaning of `uncapped`, and still validates a 1.9.0 document; `docs/schemas.md`, `CONTRACT.md`, `part5 contract`, `part5
doctor`, the goldens and, while the rules ship v2, `fixtures/output/analysis.fault-capped.example.json` (a take that
reports a fault and hits the ceiling) carry it. `score.version` says which score a 1.10.0 document carries.

### AC-V2-13: detection untouched
`detection_sha256` is unchanged; `status`, `warnings`, the faults and the near misses of every seed 5 take are byte-identical
to those of main before score v2: `fixtures/seed5-detection-baseline.json` holds their hashes
(`python -m part5.profiles_report --write-detection-baseline`) and `tests/test_detection_baseline.py` compares them.

### Rule-Based ACs
- AC-NFR-01: no new module under `part5/`; `part5/score.py`, `part5/score_report.py`, `part5/pipeline.py` and
  `part5/profiles_report.py` are extended. Verification method: inspection.
- AC-NFR-02: no live model call. Verification method: `tests/test_no_live_calls.py`.

## API / Interface Contract
`score.compute(analysis, aligned, rules)`, `score.compute_timeline(...)`, `score.timeline_block(windows, basis, rules,
tempo, reports_fault=False)`, `score.cap_by_warnings(block, analysis, rules)` keep their shape. New in `part5/score.py`:
`VERSION_V1`, `VERSIONS`, `trainer_range(fault, expected, rules)` (the range in thresholds, None when unknown),
`weight(u, p)`, `miss_cost(x, p)`, `apply_fault_cap(block, reports_fault, rules)`, `rules_v1(rules)`, `floor_holds(m)`,
`choose_floor(measured)`, `block_v2(v1, floor)`. New in `part5/score_report.py`: `targets_of(version)`,
`shipped_targets()`, `reports_exactly(take, analysis)`, `targets_v2(entries)`, `targets_v2_lines(...)`, `v1_of(rules)`,
`rules_with_floor(rules, floor)`, `measure_floor(s)`, `calibrate_v2_set(...)`, `scored_results(...)`, and the flags
`--calibrate-v2` and `--params-sha256`. In `part5/check.py`: `score_version(path)`, `recorded_score_hash(path, version)`
(a v2 block is frozen by `freezes`, a v1 block by the newest v1 attempt) and `require_score_frozen(current, recorded,
version)`. In `scripts/make_score_heldout.py`: `require_v2_freeze(record, rules)`, seed 59 needs it, seed 61 is refused.
The `score` block gains `fault_cap` (integer, optional).

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|-----------|----------|----------------|-------------|
| `score` block with an unknown version | `ValueError` | `part5/rules.json has no simon.score.v2 'score' block` | AC-V2-07 |
| v2 block, no v2 freeze record | `make check-5` exits 2 | `check-5: fixtures/score-heldout.json has no frozen score params ...` | AC-V2-09 |
| `make score-heldout SEED=59` before the freeze | exit 2 | `score-heldout: seed 59 needs the simon.score.v2 freeze ...` | AC-V2-10 |
| `make score-heldout SEED=61` | exit 2 | `score-heldout: seed 61 is reserved ...` | AC-V2-10 |

## Edge Cases
- A fault in a window the trainer's series has no finite value in: `w` 1 (AC-V2-02).
- A take with a warning and a fault: capped at 59, `fault_cap` present, `uncapped` the value before the fault cap (AC-V2-05).
- A take nothing could be measured on: `zero_block`; `fault_cap` only when it reports a fault (AC-V2-16).

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|----------|------------|--------|-------------|
| Performance | one range per fault per window | negligible next to alignment | AC-NFR-01 |
| Reliability | an unreadable series degrades to `w` 1, never raises | tested | AC-V2-02 |
| Maintainability | no new module | inspection | AC-NFR-01 |
| Compatibility | 1.9.0 documents still validate | `tests/test_schema_compat.py` | AC-V2-12 |
| Security / Accessibility / Scalability | N/A: a pure function of the analysis | | |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT touch detection, `rules.json` outside `score`, `profiles.json`, a threshold or a detection seed. Why: ruling.
- MUST NOT put the fault cap in `capped_by`. Why: Part 7 reads it as the low-match warning.
- MUST NOT be tuned on a held-out seed, on the real takes or on seed 59. Why: ADR-0007 and ADR-0018.

## Compromises
### The foot weight is judged on synthetic feet
Short-term: the foot measures take the range weight from the trainer's foot series (ruling of 2026-11-01T05:45Z, Q4), and the
series the weight reads is the synthetic feet of the seed 5 sets, a proxy for Part 2's estimated feet (ASM-013). A fault whose
series is not in the score's input still weighs 1. Long-term: judge the weight on real feet. Trigger: a real take with feet
files marks a foot fault as not a fault, or a labelled real set exists.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `part5/score.py` | v2 weight, fault cap, `uncapped`, `rules_v1`, `choose_floor`, `block_v2` | TICKET-047 | yes |
| `part5/score_report.py` | v2 targets and the fail-closed clause, trainer feet in the score's input, `--calibrate-v2` (seed 5 only), `--params-sha256`, `calibrate_set` | TICKET-047 | yes |
| `part5/calibrate.py` | one line: `TUNING_SEED` is imported from `score_report`, not defined a fourth time | TICKET-047 | yes |
| `part5/pipeline.py` | `PipelineResult.foot_expected` (the trainer's foot series, read by the score only) | TICKET-047 | yes |
| `part5/profiles_report.py` | `detection_digest`, `--write-detection-baseline`, the baseline comment | TICKET-047 | yes |
| `part5/check.py` | freeze lookup by version, report version, `require_v2_held`, `TUNING_SEED` imported | TICKET-047 | yes |
| `part5/rules.json` | `score` section only | TICKET-047 | yes |
| `part5/output.py` | schema 1.10.0 | TICKET-047 | yes |
| `part5/contract.py`, `part5/doctor.py` | rows, goldens, doctor notes | TICKET-047 | yes |
| `contracts/analysis.schema.json`, `contracts/metrics.schema.json` | 1.10.0, the score version enum | TICKET-047 | yes |
| `scripts/make_score_heldout.py` | seeds 59 and 61, the frozen code (git), `scored_at`, `holds` | TICKET-047 | yes |
| `scripts/make_output_examples.py` | the fault-capped golden (only while the rules ship v2) | TICKET-047 | yes |
| `scripts/make_score_fallback.py`, `Makefile` | `make score-fallback`: going back to v1 | TICKET-047 | yes |
| `fixtures/output/*.example.json`, `fixtures/profiles-fitness-baseline.json` | regenerated | TICKET-047 | yes |
| `fixtures/seed5-detection-baseline.json` | what detection finds in every seed 5 take, hashed (new) | TICKET-047 | yes |
| `docs/schemas.md`, `docs/thresholds.md`, `CONTRACT.md`, `docs/dev/DEVELOPING.md`, `docs/design/specs/journey-followup.md` | fields, record, rows | TICKET-047 | yes |
| Tests: `tests/test_score_v2.py`, `test_score_fallback.py`, `test_detection_baseline.py`, `shipped_score.py` and updates to `test_score.py`, `test_check_score.py`, `test_score_heldout.py`, `test_schema_compat.py`, `test_contract_part7_history.py`, `test_doctor.py`, `test_output_examples.py`, `test_reps.py`, `test_score_timeline.py`, `test_score_report.py` | per AC | TICKET-047 | yes |

## Delivery Verification Plan
- `make test` 0; `make check-5-contract` 0; `python3 scripts/make_design_copies.py --check` 0.
- `make score-fallback` on a throwaway copy with the v2 freeze and a simulated seed 59 attempt in the record: `make test` 0
  and the score lookup of `make check-5` green (AC-V2-14).
- `make check-5` is run by the orchestrator once the freeze is recorded (exit 0 on seed 73, detection metrics and
  `detection_sha256` byte-identical).
- `make score-heldout SEED=59` once, by the orchestrator, after the freeze; the result is published pass or fail.
