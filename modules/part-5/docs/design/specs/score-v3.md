# Spec: score v3 (simon.score.v3): v2's range weight and 89 ceiling, and a ceiling of 79 for two or more reported faults
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-11-01
Linked PRD: none (TICKET-060, operator ruling on moalborati/simon#61 of 2026-11-01T13:20Z, stakeholder-proxy ruling of 13:35Z)
Linked CRD: none
Request Type: feature-mod
Risk Level: medium
Master spec: `journey-followup.md` (J-4, the score). ADRs: ADR-0019 (this change), ADR-0018 (v2, amended), ADR-0007 (the v1
curve, amended), ADR-0013 (windows), ADR-0012 (the warning cap), ADR-0003 and ADR-0017 (detection seeds, untouched).
Ticket: TICKET-060. Companion spec: `score-v2.md` (the weight, the foot measures, the freeze code, which v3 reuses).

## Overview
`simon.score.v3` is v2 plus a second ceiling. A miss costs `penalty(r) * (0.5 + 0.5 * dur) * coverage * w`, `w` rising from
`range_floor` to 1 as the trainer's range of the missed measure in the window rises to `range_full` (3) detection
thresholds (`score-v2.md` AC-V2-01 to AC-V2-03, unchanged). A take whose `faults` list holds one entry scores at most
`fault_cap` (89); a take whose list holds two or more scores at most `fault_cap_many` (79). The ceiling is applied once, to
the mean of the windows, and `score.fault_cap` is the ceiling in force (89 or 79). `score.uncapped` holds the value before
every cap; `capped_by` is untouched. The `score` section of `part5/rules.json` carries the shipped v3 block, `score.v1`
(`e818635b...`) and `score.v2` (`60116de4...`) verbatim. Detection, its thresholds and `detection_sha256` are not touched.
The analysis schema goes to 1.11.0.

## Why This Is Wrong (Dissent-First)
1. **A ceiling by count is blunt.** Two faults of any size cap the take at C. Answer: ruled; the points under the ceiling
   still rank takes, and the timeline still shows each miss.
2. **Targets 2, 3 and 5 cannot fail on seed 61.** Answer: ADR-0019 says so (the sweep never reads the seed); the report prints, beside the targets, each exact double's
   value before the 79 ceiling, how many the ceiling lowered, ADR-0007's D or F count, the strict slice verdicts and the
   comparability sentence (AC-V3-09).
3. **`fault_cap` stops being a constant.** A reader that expects 89 reads a 79. Answer: additive and documented as the
   ceiling in force; Part 7 is told before it lands (AC-V3-11).
4. **v3 is designed after seed 59.** Answer: disclosed in ADR-0019; seed 61 has never been generated.

## User Story
As Part 7, I want a take that reports two or more faults never to read above C, and a take that reports one fault never above
B, with the ceiling in force named in the score, so that the grade agrees with the fault list the follower sees.

## Acceptance Criteria
### AC-V3-01: the two ceilings
Given a v3 block and a take whose `analysis.faults` holds `n` entries
When the take is scored (`score.compute`, `score.timeline_block`, `score_report.score_block`)
Then `n` 0: no ceiling and no `fault_cap`; `n` 1: the value is at most 89; `n` 2 or more: the value is at most 79
(`tests/test_score_v3.py`). Under a v1 block no take has a ceiling; under a v2 block the ceiling is 89 for any `n` 1 or more
(`tests/test_score_v2.py`, unchanged in meaning).

### AC-V3-02: `fault_cap` is the ceiling in force
Given a v3 take that reports at least one fault
Then `score.fault_cap` is the integer 89 for one reported fault and 79 for two or more, whether or not the ceiling lowered
the value; it is absent for a take with no faults and under v1. A take with faults on which nothing could be measured (value
0) carries the ceiling in force too.

### AC-V3-03: applied once, to the mean
The ceiling is applied to the mean of the windows (ADR-0013), once; no window is capped and there is no worst-window rule. The
count is of the take's `faults` list, whatever the window.

### AC-V3-04: `uncapped` and `capped_by`
`score.uncapped` is `{value, grade}` of the mean before every cap (the fault ceiling, then the warning cap of 59), present when
either lowered the value; with both, the value before the first. `capped_by` lists the warning codes only and never names a
ceiling. A two-fault take that the 79 ceiling lowered and that has no warning has `uncapped` and no `capped_by`.

### AC-V3-05: the rules keep v1 and v2 verbatim
`part5/rules.json` `score.v1` hashes to `e818635bb46b7062f57e335f2940edd35d01835edaaaffed9339fdbfb79eaa62` and `score.v2` to
`60116de4cede436c574b91b15a74a7f0c5561790ac6f61cf9181a8317575fe95`. Scoring with `score.rules_v1(rules)` or `score.rules_v2(rules)`
gives `simon.score.v1` and `simon.score.v2` values as before. The v3 block repeats v1's `base`, `slope`, `cap`, `z0`, `z1`,
`s_max` and `bands` at its top level, equal (`tests/test_score_v3.py`).

### AC-V3-06: calibration
`range_floor` is the value `score.choose_floor` picks from `score_report.measure_floors` run under the v3 code (the doubles
measured after the 79 ceiling) by ADR-0018's rule, unchanged; the shipped block equals the one `score_report.calibrate_set`
returns for rules that ship the v3 form. `python -m part5.score_report --calibrate-v3` runs it and refuses any set that is not
seed 5. The table is recorded in `docs/thresholds.md`, "Score v3", with no hand nudge.

### AC-V3-07: the freeze and `make check-5`
Given a v3 `score` block, `make check-5` exits 2 unless `fixtures/score-heldout.json` has a v3 entry in `freezes` whose
`params_sha256` is the block's, and it exits 2 (pointing to `make score-fallback`) when the recorded v3 attempt has `holds`
false or does not record it. An attempt is v3's when it says so, is for seed 61 or carries the v3 freeze's hash. A v1 block is
checked against the newest v1 attempt, which is never an attempt for seed 59 or 61 or one that carries a freeze's hash; a v2
block against the v2 freeze and the v2 attempt as before. A version is never judged by another version's attempt
(`tests/test_check_score.py`, on simulated records). It also exits 2 when the record holds more than one freeze of the shipped
version (a re-freeze; the newest would let a retuned block pass) and when the shipped block's hash differs from the
`params_sha256` of the version's recorded attempt (pre-freeze review R1).

### AC-V3-08: seed 61
`make score-heldout SEED=61` exits 2 until exactly one v3 freeze whose hash is the shipped block's exists, the rules ship v3,
the freeze names its `freeze_commit`, the tree is clean and `git diff <freeze_commit> HEAD` is empty under the code paths of
`score-v2.md` AC-V2-18 plus the `Makefile`, and `out/score-heldout/seed-61/` does not exist; it then runs once. "The tree is
clean" means no uncommitted change and no untracked file anywhere (the scorer runs from the repository root; the gitignored
`out/` and `.venv/` are not seen), and each modified file is named once in the refusal. While a score with a ceiling (v2 or v3)
ships, any other unrecorded seed (62, 63, ...) is refused too: no third series is opened in this run (pre-freeze review R2 to R4). The attempt it prints carries
`version` `simon.score.v3`, `scored_at`, `holds` and the measures published beside the targets. Seed 59 is refused as
recorded. Seeds of both detection series stay refused (`tests/test_score_heldout.py`, with a stubbed git and a real
temporary repository).

### AC-V3-09: the targets report, beside which the measures are published
`python -m part5.score_report --set <dir>` prints, for a v3 block, ADR-0018's five targets (fail closed, `all five hold: no`
when a target has no judged take or the sweep was not run, `targets_v2.holds` in the JSON), and beside them, as measured and
not as a target: for each take that reports exactly its two labelled faults, its value before and after the 79 ceiling, and
how many the ceiling lowered; the count of those takes that grade D or F (ADR-0007's reading) and C; the strict slice verdicts;
the comparability sentence (v3's wording: targets 2, 3 and 5 are settled before seed 61, the sweep being one fixed
`Random(1234)` take that never reads the seed and 3 and 5 holding by construction, so only 1 and 4 test anything on it); and
what the ceiling counts (the entries of `faults`; left and right of one measure are one `both` entry only for the same
direction with overlapping frames, otherwise two). The JSON carries the same under `beside_targets` (`tests/test_score_v3.py`).

### AC-V3-10: going back to v1 from a v3 tree
`make score-fallback` turns a tree that ships v3 (or v2) into a tree that ships v1: the `score` section becomes its `v1` block,
the v2 and v3 samples are removed, the goldens and the fitness baseline are written again, `fixtures/score-heldout.json` is
not touched. `make test` exits 0 on the result and `part5.check.recorded_score_hash` finds `e818635b...` for a v1 `make
check-5` with the v3 freeze and a seed 61 attempt in the record (`tests/test_score_fallback.py`; the proof on a copy of the
tree is in `docs/thresholds.md`).

### AC-V3-11: contract
`contracts/analysis.schema.json` 1.11.0 accepts `score.version` `simon.score.v3` and `score.fault_cap` 89 or 79, and still
validates a 1.10.0 document; `contracts/metrics.schema.json` accepts `simon.score.v3` in `report.score.version`;
`docs/schemas.md`, `CONTRACT.md`, `part5 contract`, `part5 doctor`, the goldens and, while the rules ship v3,
`fixtures/output/analysis.fault-capped.example.json` (one fault, 89) and `fixtures/output/analysis.double-capped.example.json`
(two faults, 79) carry it. `part5 doctor` notes the score version and the ceiling in force; on a warned document (`capped_by`
not empty) its note calls it "the fault ceiling" and adds that the warning cap at F binds lower, because the cap in force there
is the F cap (59), not the ceiling. `part5.output.validate_analysis`
refuses a v2 or v3 document whose `score.fault_cap` is not the ceiling in force for the faults it reports (89 for one or, under
v2, more; 79 for two or more under v3; absent for none), so a producer that wrote 89 on a two-fault v3 take does not validate,
and refuses a `simon.score.v1` score block that carries `fault_cap` at all (v1 has no ceiling to write; added after seed 61,
the pre-freeze recheck's residual) (`tests/test_score_v3.py`).

### AC-V3-12: the committed record survives seed 61
No test of `fixtures/score-heldout.json` depends on seed 61 being absent: a simulated record that holds the v3 freeze and a
seed 61 attempt, with `holds` true and with `holds` false, leaves `make test` green on a copy of the tree
(`tests/test_score_fallback.py`, `tests/test_score_heldout.py`, `tests/test_check_score.py`).

### AC-V3-13: detection untouched
`detection_sha256` is `c92ae9a8524c559741cdaebcd14bb5305e91479d19123e15c3a5e14efb1337fb`; `status`, `warnings`, the faults and
the near misses of every seed 5 take are byte-identical to those of main before v3
(`tests/test_detection_baseline.py`); `make check-5` on seed 73 exits 0 with its detection metrics identical.

### Rule-Based ACs
- AC-NFR-01: no new module under `part5/`; `part5/score.py`, `part5/score_report.py`, `part5/check.py` are extended.
  Verification method: inspection.
- AC-NFR-02: no live model call. Verification method: `tests/test_no_live_calls.py`.
- AC-NFR-03: the lines of any file that the teammate (the team) last wrote upstream are byte-identical; additions are on new lines.
  Verification method: `git blame` at `upstream/main` against the diff.

## API / Interface Contract
`score.compute(analysis, aligned, rules)`, `score.compute_timeline(...)`, `score.cap_by_warnings(block, analysis, rules)` keep
their shape. `score.timeline_block(windows, basis, rules, tempo, n_faults=0)` takes the number of entries in the take's `faults`
list where it took a boolean (`reports_fault`); `score.apply_fault_cap(block, n_faults, rules)` likewise. New in
`part5/score.py`: `VERSION_V2`, `VERSION_V3` (`VERSION` is gone: each use names its version), `SCORE_SEEDS` (`{v2: 59, v3: 61}`),
`KEPT_BLOCKS` (the frozen blocks a later version's section keeps), `FAULT_CAP_MANY`, `MANY_FAULTS`, `reported_faults(analysis)`,
`ceiling_of(p, n_faults)`, `rules_of(rules, version)`, `rules_v2(rules)`, `block_v3(v1, v2, floor)`, `ships(version, rules)`
(it replaces `ships_v2`) and `has_ceiling(rules)`. In `part5/score_report.py`: `v2_of(rules)`, `block_of(version, rules, floor)`,
`rules_with_floor(rules, floor, version)`, `uncapped_value(block)`, `calibrate_floor_set(..., version)` (it replaces
`calibrate_v2_set`), `beside_targets(entries, strict_verdicts)` and `beside_lines(beside)`, `comparability_of(version)` and
`COMPARABILITY_V3`, the flags `--calibrate-v2` and `--calibrate-v3`; the report's JSON key `targets_v2` holds ADR-0018's five
targets for v2 and v3 and `beside_targets` the measures beside them. In `part5/check.py`: `attempts_of(doc, version)`,
`recorded_score_hash(path, version)` and `require_held(path, version)` (it replaces `require_v2_held`) for v2 and v3. In
`scripts/make_score_heldout.py`: `version_of_seed(seed)`, `require_freeze(version, record, rules, root, git)`,
`require_frozen_code(commit, seed, root, git)`, `attempt_of(...)`. The `score` block gains no new field; `fault_cap` may be 79.

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|-----------|----------|----------------|-------------|
| `score` block with an unknown version | `ValueError` | `part5/rules.json has no simon.score.v1, simon.score.v2 or simon.score.v3 'score' block` | AC-V3-05 |
| v3 block, no v3 freeze record | `make check-5` exits 2 | `check-5: fixtures/score-heldout.json has no frozen score params ...` | AC-V3-07 |
| v3 block, recorded v3 attempt with `holds` false or absent | `make check-5` exits 2 | `check-5: ... did not hold every target on seed 61 ... run make score-fallback` | AC-V3-07 |
| `make score-heldout SEED=61` before the freeze | exit 2 | `score-heldout: seed 61 needs the simon.score.v3 freeze ...` | AC-V3-08 |
| `make score-heldout SEED=59` | exit 2 | `score-heldout: seed 59 is already recorded ...` | AC-V3-08 |
| `make score-heldout SEED=62` while v3 ships | exit 2 | `score-heldout: seed 62 is no score version's seed ...` | AC-V3-08 |
| v3 block, two v3 freezes or a block that differs from the recorded attempt's | `make check-5` exits 2 | `check-5: ... holds 2 simon.score.v3 freeze entries ...` or `... was scored with the score params of sha256 ...` | AC-V3-07 |
| v2 or v3 document with a `fault_cap` that is not the ceiling in force | `OutputError` | `score.fault_cap must be 79 for a simon.score.v3 take that reports 2 faults, got 89` | AC-V3-11 |
| `simon.score.v1` score block that carries `fault_cap` | `OutputError` | `score.fault_cap must be absent from a simon.score.v1 score block, which has no ceiling, got 89` | AC-V3-11 |

## Edge Cases
- A take with a warning and two faults: capped at 59, `fault_cap` 79, `uncapped` the value before the fault ceiling.
- A take whose faults are one measure on both sides: detection (`part5/detect.py`) merges them into one `both` entry only for
  the same direction with overlapping frames, so that is one fault; on two directions, or without overlapping frames, they are
  two entries and the 79 ceiling applies.
- A take nothing could be measured on: `zero_block`; `fault_cap` only when it reports a fault, 79 for two or more.
- A rep-by-rep take: the count is of `analysis.faults`, not of a rep's faults.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|----------|------------|--------|-------------|
| Performance | one count per take | negligible next to alignment | AC-NFR-01 |
| Reliability | an unreadable series degrades to `w` 1, never raises | tested (v2) | AC-V3-01 |
| Maintainability | no new module | inspection | AC-NFR-01 |
| Compatibility | 1.10.0 documents still validate | `tests/test_schema_compat.py` | AC-V3-11 |
| Security / Accessibility / Scalability | N/A: a pure function of the analysis | | |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT touch detection, `rules.json` outside `score`, `profiles.json`, a threshold or a detection seed. Why: ruling.
- MUST NOT put a ceiling in `capped_by`. Why: Part 7 reads it as the low-match warning.
- MUST NOT be tuned on seed 61, on seed 59 or on the real takes. Why: ADR-0007, ADR-0018, ADR-0019.
- MUST NOT add a window cost ceiling. Why: the ruling (Q3); TICKET-053 holds that family.

## Compromises
### The ceiling counts entries, not severity
Short-term: two faults of any size cap the take at C (ruled). Long-term: a severity-aware cap would need a new family and a
new score seed series. Trigger: Part 7 or the #59 reporter marks a two-fault take graded C as unfairly low (TICKET-053).

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `part5/score.py` | v3 ceilings by count, `block_v3`, `rules_v2`, version helpers, `SCORE_SEEDS`, `document_ceiling` | TICKET-060 | yes |
| `part5/score_report.py` | v3 targets and the measures beside them, `--calibrate-v3`, version-aware rule runner | TICKET-060 | yes |
| `part5/check.py` | freeze and `holds` by version, v1 lookup that skips v2 and v3 attempts | TICKET-060 | yes |
| `part5/rules.json` | `score` section only: v3 block, `v1`, `v2` | TICKET-060 | yes |
| `part5/output.py` | schema 1.11.0; `_validate_fault_cap` (R13) | TICKET-060 | yes |
| `part5/contract.py`, `part5/doctor.py` | rows, goldens, doctor notes | TICKET-060 | yes |
| `contracts/analysis.schema.json`, `contracts/metrics.schema.json` | 1.11.0, the score version enum, `fault_cap` | TICKET-060 | yes |
| `scripts/make_score_heldout.py` | seed 61, the freeze by version | TICKET-060 | yes |
| `scripts/make_output_examples.py` | the double-capped golden (only while the rules ship v3) | TICKET-060 | yes |
| `scripts/make_score_fallback.py`, `Makefile` | `make score-fallback` accepts a v3 tree | TICKET-060 | yes |
| `fixtures/output/*.example.json`, `fixtures/profiles-fitness-baseline.json` | regenerated | TICKET-060 | yes |
| `docs/thresholds-score-v3.md` (new, split out of `docs/thresholds.md` to keep it under 800 lines), `.simon-publish` (its allowlist line) | the seed 5 record, the real takes, the proofs | TICKET-060 | yes |
| `docs/schemas.md`, `docs/thresholds.md`, `CONTRACT.md`, `docs/dev/DEVELOPING.md`, `docs/design/specs/integration-contract.md` (AC-C18), `docs/design/specs/journey-followup.md`, `qa/recipes/cli/part5-contract.md` | fields, record, rows, the schema versions a recipe pins | TICKET-060 | yes |
| Tests: `tests/test_score_v3.py` (new), `tests/shipped_score.py` (the one home of the shared helpers, fixtures' bodies and frozen hashes), `tests/conftest.py` (`seed5_scored`, `report_as`), and updates to `test_score_v2.py`, `test_score_fallback.py`, `test_check_score.py`, `test_score_heldout.py`, `test_score.py`, `test_schema_compat.py`, `test_contract_part7_history.py`, `test_doctor.py`, `test_output_examples.py`, `test_reps.py`, `test_score_report.py`, `test_contract_cli.py`, `test_part7_no_person.py`, and the schema version pinned in `test_check.py`, `test_cli.py`, `test_cues.py`, `test_feet.py`, `test_feet_faults.py`, `test_guard.py`, `test_near_misses.py`, `test_near_misses_reps.py`, `test_output.py`, `test_phrasing_lang.py`, `test_pipeline_run.py`, `test_profiles_wiring.py`, `test_visibility.py` | per AC | TICKET-060 | yes |

## Delivery Verification Plan
- `make test` 0; `make check-5-contract` 0; `python3 scripts/make_design_copies.py --check` 0.
- `make score-fallback` on a throwaway copy with the v3 freeze and a simulated seed 61 attempt in the record: `make test` 0
  and the score lookup of `make check-5` green (AC-V3-10, AC-V3-12).
- `make check-5` on a throwaway copy with a simulated v3 freeze (never committed): exit 0 on seed 73, detection lines and
  slices byte-identical to main's (AC-V3-13).
- `make score-heldout SEED=61` once, by the orchestrator, after the freeze; the result is published pass or fail.

## Dissent Review
Reviewed by: the pre-freeze review the ruling names (one independent review and recheck before the freeze); the
stakeholder-proxy ruling of 2026-11-01T13:35Z.
Date: 2026-11-01

### Concern 1: targets 2, 3 and 5 are settled before seed 61
Challenge: a pass on all five reads as stronger than it is (pre-freeze review R6: the sweep reads no score seed).
Impact if right: v3 ships on a verdict that only 1 and 4 could have failed.
Mitigation: ADR-0019 states it; the report prints the pre-ceiling values, the lowered count, the D or F count, the strict
verdicts and the comparability sentence beside the targets.
Resolution: ADDRESSED_IN_SPEC

### Concern 2: v3 was designed after seeing seed 59
Challenge: the second ceiling answers a recorded miss, so a pass on 61 is not a clean test.
Impact if right: the verdict overstates generalisation.
Mitigation: the ceiling and its count are the ruling's, the floor is a rule's output on seed 5, nothing is fitted to 59; the
disclosure is in ADR-0019 and the publication repeats it.
Resolution: ACCEPTED_RISK

### Concern 3: `fault_cap` was a constant in v2
Challenge: a reader that hard-codes 89 misreads a 79.
Impact if right: a wrong sentence in the viewer.
Mitigation: the schema describes it as the ceiling in force; CONTRACT.md duty 10 and `part5 contract` say so; Part 7 is told
before the code lands.
Resolution: ADDRESSED_IN_SPEC
