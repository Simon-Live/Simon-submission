# Spec: near-miss diagnostics, `diagnostics.near_misses` (TICKET-043, analysis 1.8.0)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-31
Linked PRD: none (moalborati/simon#59, item 3)
Linked CRD: none
Request Type: feature-mod
Risk Level: medium
Master spec: `part5-fault-analysis.md` ("Detection changes (#30)", "Repetitions"). ADRs: ADR-0010 (repetitions),
ADR-0016 (profiles), ADR-0003 (detection is frozen for a held-out attempt). Ticket: TICKET-043. Ruling: STATUS.md
Decisions, 2026-10-31T22:30Z (stakeholder-proxy: near-miss diagnostics first, no detection change). Companion specs:
`profiles.md`, `integration-contract.md`, `calibration.md`.

## Overview
A real Romanian deadlift (RDL) follow take scored 100 / A with 0 faults and `analysis.json` could not say why: whether
the follower matched the example, or a real difference stayed just under the persistence rule. Detection keeps a fault
only when it lasts long enough, and drops it when another kept fault explains it; a dropped candidate leaves no trace.
This feature records every candidate that detection considered and dropped in one additive field,
`diagnostics.near_misses`: what it was (measure, side, direction, joint), how big it was, how many frames were past
the threshold and where, what persistence needed, and why it was dropped (`persistence` with the shortfall, or
`explained_by` naming the kept fault). It changes nothing else: detection, the faults list, the score, the insights and
every existing field are what they were, and `make check-5` prints the same bytes. The schema is `1.8.0`.

The field is a diagnostic for people and for Part 7's "why no fault?" panel. It is not shown to the follower and it is
not scored.

## Why This Is Wrong (Dissent-First)
1. **A list of "almost faults" invites a detection change.** Once the dropped candidates are visible, someone will
   lower a threshold to turn them into faults, on one clip. Answer: this feature records, it never decides; ADR-0003
   still bars retuning on held-out numbers, and the stakeholder ruling schedules the persistence change
   (TICKET-044) after, on seed 5 only. The spec says in Negative Requirements that no fault, score or insight reads a
   near miss.
2. **It could change the gate by accident.** `detect.py` is on the gate's path. Answer: `detect()` still returns the
   faults list and builds no near miss (its call does not collect them); the faults come from the same code path in
   `detect_full`, which collects; the fitness baseline hash of all 156 seed 5 takes is the proof that every other
   field is byte-identical (AC-NM-01), and `make check-5` stdout is compared byte for byte with the tree before.
3. **Noise would fill the list.** Every measure and side has frames past a threshold now and then. Answer: only
   candidates with at least one frame past their threshold count, they are sorted by size, at most 10 are listed and
   the count of the rest is stated (`total`, `omitted`). A document grows by at most about 5 KB.
4. **"Size" of a candidate that never lasted is not the size of a fault.** A fault's magnitude is the median over its
   counted runs; a candidate may have no counted run. Answer: the definition is one sentence (AC-NM-04): the median
   over the counted runs when there are any, else over every frame past the threshold, rounded like a fault's.
5. **Rep mode has no single "the take" to explain.** Faults of a rep-by-rep take are aggregated over reps (ADR-0010).
   Answer: near misses live at the take level and are aggregated the same way, one per measure, side and direction,
   with the reps they crossed the threshold in (AC-NM-12); a per-rep list would repeat the same candidate eight times.
6. **A profile has two configs.** Under a profile, explanation is judged at the baseline and survivors are re-tested at
   the looser config (ADR-0016). Answer: a candidate is evaluated at the profile's own config first (persistence), then
   explanation at the baseline; the document says which in the reason (AC-NM-11).

## User Story
As a person reading an `analysis.json` that has no faults, I want to see which candidates came close and why they were
dropped, so that I can tell a clean take from a take that missed the persistence rule by a few frames.

### Jobs-to-be-Done
- Functional: explain a score of 100 with 0 faults, or a missing fault, from the document alone.
- Emotional: trust a "no faults" result because the near misses say what was looked at.
- Social: the team can answer a reporter ("why did my RDL score 100?") with numbers, not a guess.

## Vocabulary
- **Candidate**: one measure on one side in one direction (`more` or `less` than the example) with at least one frame
  past its threshold, evaluated at the config in force. Sides are not merged: a candidate is `left`, `right` or
  `center`, never `both` (merging is for reported faults).
- **Frames over**: the frames of the (median-filtered) difference past the threshold in the candidate's direction.
- **Counted frames**: the frames over that sit in runs of at least `min_run_frames`. Persistence counts these.
- **Needed frames**: `min_frames` when the config gives it, else `max(floor, round(min_fraction x n))`, with `n` the
  length of the expected rep the frames fall in (the clip's, for an example of one rep; the reference rep's, in rep
  mode) and `floor` the duration the measure's floor names (`min_frames_floor_body`, or `min_frames_floor` for a foot measure; frames at 30 fps) in frames at the example's rate, at most
  three quarters of `n` (`persistence.floor_frames`). Persistence holds when the counted frames are at least the needed
  frames and there is at least one counted run (`persistence.judge`); a candidate that fails is the longest run of the rep
  its counted and needed frames describe (pre-freeze review B4).
- **Near miss**: a candidate that is not a reported fault, with the reason.

## What is recorded
`detect.detect_full(exp_m, fol_m, alignment, rules=None)` returns `Detection(faults, candidates)`. `faults` is exactly
what `detect()` returns (`detect` is `detect_full(...).faults` with collection switched off). Every candidate is a
`detect.Candidate`, tagged with its outcome:

| Outcome | Meaning |
|---|---|
| `reported` | it is, or was merged into, a fault of the take |
| `persistence` | the counted frames are fewer than the needed frames (or no run is long enough) |
| `explained_by` | it persists, and a kept fault explains it (`rules["explained_by"]`, `rules["explained_by_opposite"]`) |

The first test that fails names the reason, in the order detection runs them: persistence, then explanation.
`diagnostics.near_misses` lists the candidates whose outcome is not `reported`.

### Fields of an item
| Field | Meaning |
|---|---|
| `measure`, `side`, `joint`, `body_part`, `direction` | as for a fault; `side` is `left`, `right` or `center` |
| `magnitude_deg`, `peak_deg` | as for a fault: the signed median and the largest signed value of the smoothed difference, over the counted runs when there are any, else over every frame past the threshold; one decimal |
| `threshold_deg` | the threshold in force |
| `expected_frames`, `follower_frames` | the longest run past the threshold (the earliest on a tie), expected-clip frames and the matched follower file frames; for a candidate that persists this is the run a fault would report (fitness) |
| `frames_over` | frames past the threshold, any run length |
| `counted_frames` | those in runs of at least `min_run_frames` |
| `needed_frames` | what persistence needed |
| `min_run_frames` | the run length that counts |
| `reason` | `persistence`, `explained_by`, `reps` or `fitness` (the last two in rep mode only) |
| `shortfall_frames` | `reason` `persistence`: `needed_frames - counted_frames`, at least 0 |
| `explained_by` | `reason` `explained_by`: `{measure, side, direction}` of the kept fault that explains it, as that fault is reported (a cause merged to `both` reads `both`); the largest magnitude when several explain it |
| `reps` | rep mode: the 0-based reps in which the candidate crossed the threshold |
| `found_in_reps`, `needed_reps` | rep mode, `reason` `reps` or `fitness`: see below |

Example, the RDL take's trunk lean: `{"measure": "trunk_lean_forward", "side": "center", "direction": "less",
"frames_over": 68, "counted_frames": 68, "needed_frames": 114, "min_run_frames": 4, "reason": "persistence",
"shortfall_frames": 46, ...}`.

## The field: `diagnostics.near_misses`
```
"near_misses": {"total": 6, "omitted": 0, "items": [ {item}, ... ]}
```
- `total`: how many near misses there are. `items`: at most `detect.MAX_NEAR_MISSES` (10) of them, the largest first:
  by `abs(magnitude_deg)` descending, then `measure`, `side`, `direction` ascending (so the order is fixed).
  `omitted`: `total` minus the items listed.
- **Bound**: only candidates (at least one frame past the threshold) are ever listed, at most 10 items, one count of the rest.
- **Present whenever detection ran**, also with `total` 0 and `items` `[]`: "nothing came close" is a finding, and
  "absent" means the take could not be compared. A take that could not be aligned (`_unaligned`, ADR-0012) ran no
  detection and has no `near_misses`.
- Every document is `1.8.0`; the field is optional in the schema, so a reader built on 1.7.0 ignores it (the schema
  allows extra `diagnostics` fields).

## Rep mode (ADR-0010)
Faults of a take compared rep by rep are reported once at the take level (found in at least half of the accepted reps,
`reps` listing where). Near misses live at the same level and follow the same grouping. Each accepted rep is detected
on its own and yields candidates (reported ones included). Per measure, side and direction that the take does not
report (no reported fault of the same measure and direction on that side or on `both`):
- the item is the record of the rep where the candidate came closest to being reported (most counted frames, the
  earliest rep on a tie), its `expected_frames` shifted onto the expected file like a fault's (`diagnostics.expected_reference.frames[0]`, since attempt 4 the start of that rep's reference
  added), its `follower_frames` on the follower file;
- `reps` lists every accepted rep in which it crossed the threshold;
- `reason`: `persistence` or `explained_by` as in that rep when no rep reported it; `reps` when some rep reported it
  but fewer than half of the accepted reps did, with `found_in_reps` (the reps that found its side of it, alone or as part of `both`, the same count the half rule makes)
  and `needed_reps` (half the accepted reps, rounded up); `fitness` when the half rule passed but a profile's take-level
  check dropped it (a profile never reports a take-level fault that `fitness` does not, `profiles.md`).
Reps that did not pass the guard take no part. A take compared as a whole has no `reps`, `found_in_reps` or `needed_reps`.

## Profiles (ADR-0016)
Under a profile other than `fitness`, the candidate is evaluated at the profile's own config (its relaxed threshold,
`min_fraction` and `min_run_frames`), because the near misses are what the profile's detection dropped. The profile's
persistence is tested first: a candidate that fitness reports but the profile's looser config no longer finds is a
`persistence` near miss with the profile's numbers. Explanation is judged at the baseline, as detection does it:
`explained_by` names a fault that `fitness` reports, which the profile may itself have dropped (it then has its own
`persistence` entry, if it had a frame past the profile's threshold). A profile finds nothing fitness does not, so no
candidate is dropped for being unknown to fitness. `fitness` itself is the same code with no second config.

## Acceptance Criteria
### AC-NM-01: purely additive
Given any pair, when detected with and without collecting candidates, then the faults are equal (every field, order
included). Given every seed 5 take analysed under `fitness`, then the SHA-256 of the analysis without `profile`,
`schema_version` and `diagnostics.near_misses` equals `fixtures/profiles-fitness-baseline.json` (taken before the
feature), so the faults, the score, the insights and every other field are unchanged. `make check-5` prints the same
bytes and exits as before. Verification: `tests/test_near_misses.py`, `tests/test_profiles.py`
(`test_fitness_matches_the_prefeature_baseline`), `make check-5` compared with `cmp`.
### AC-NM-02: candidates and outcomes
Given a measure with frames past its threshold, then it is a candidate; one with none is not. A candidate is
`reported` iff a fault of the same measure and direction reports its side (or `both`); every fault is the
`reported` outcome of a candidate. Verification: `tests/test_near_misses.py`.
### AC-NM-03: persistence shortfall
Given a candidate whose counted frames are fewer than the needed frames, then its item has `reason` `persistence`,
`frames_over`, `counted_frames`, `needed_frames` (from `min_fraction`, `min_frames_floor` or `min_frames`),
`min_run_frames` and `shortfall_frames` equal to needed minus counted. Runs shorter than `min_run_frames` add to
`frames_over` and not to `counted_frames`. Verification: `tests/test_near_misses.py`.
### AC-NM-04: size
Given a candidate that persists, then its `magnitude_deg` and `peak_deg` equal the fault's. Given one that does not,
then they are the median and the largest signed value over its counted runs, or over every frame past the threshold
when no run is long enough; the sign follows the direction (`more` positive, `less` negative). Verification: `tests/test_near_misses.py`.
### AC-NM-05: frames
Given a candidate, then `expected_frames` is its longest run past the threshold (the earliest on a tie) and
`follower_frames` the matched frames of the follower file as given (resampling mapped back, as for a fault). Verification:
`tests/test_near_misses.py`, `tests/test_pipeline_run.py`.
### AC-NM-06: explained_by
Given a candidate that persists and a kept fault that explains it, then its item has `reason` `explained_by` and
`explained_by` naming that fault's measure, side and direction as reported. A dropped fault never explains another
(a chain is named from its root). When two kept faults explain it, the larger magnitude is named. Verification:
`tests/test_near_misses.py`.
### AC-NM-07: the bound
Given more than 10 near misses, then `items` holds the 10 largest, `total` the count and `omitted` the rest, and the
order is by `abs(magnitude_deg)` descending with a fixed tie break. Verification: `tests/test_near_misses.py`.
### AC-NM-08: no candidates, and no detection
Given a take with no frame past any threshold, then `near_misses` is `{"total": 0, "omitted": 0, "items": []}`. Given a
take that could not be aligned, then the key is absent. Verification: `tests/test_near_misses.py`.
### AC-NM-09: sides and NaN
Given a left fault that persists and a right one that does not, then the right one is a near miss with side `right` and
the left is not; sides are never merged. Given frames where the difference is not a number, then they are never past a
threshold and count in no field. Verification: `tests/test_near_misses.py`.
### AC-NM-10: determinism
Given the same inputs, two runs write byte-identical `analysis.json` (AC-012). Verification: `tests/test_near_misses.py`.
### AC-NM-11: profiles
Given a profile and a candidate the profile's looser config no longer finds, then it is a `persistence` near miss with
the profile's threshold and needed frames; given one explained at the baseline, `explained_by` names the baseline fault;
a profile's near misses never include a candidate that is a reported fault of the profile. Verification: `tests/test_near_misses.py`.
### AC-NM-12: rep mode
Given a take compared rep by rep, then `near_misses` is at the take level, one item per measure, side and direction
that the take does not report, with `reps`, the closest rep's numbers, `expected_frames` on the expected file, and the
reasons above. Verification: `tests/test_near_misses_reps.py`.
### AC-NM-13: contract
Given a new document, then it is `schema_version` `1.8.0`, validates against `contracts/analysis.schema.json` and
`validate_analysis`; a malformed `near_misses` (wrong counts, an unknown reason, a side `both`, a missing field) is an
`OutputError` naming the field; the 1.1.0 schema still accepts an unwarned document, since `diagnostics` allows extras.
`part5 doctor --for part7` notes how many near misses a document lists. `make check-5-contract` rebuilds the goldens
byte for byte. Verification: `tests/test_near_misses.py`, `tests/test_schema_compat.py`, `tests/test_doctor.py`,
`tests/test_output_examples.py`, `make check-5-contract`.
### AC-NM-14: the RDL reproduction
Given the reporter's take (private repository, see "Reproduction note"), then `trunk_lean_forward` is listed with about
68 frames over against 114 needed, and `left_upper_arm_forward` and `head_forward` are listed with their shortfalls.
Verification: the command below, run by hand (the data is not in this repository); `tests/test_near_misses.py` holds a
synthetic take with the same shape (68 of 114).

### Rule-Based ACs
- AC-NM-NFR-01: no network call, no new dependency. Verification: `tests/conftest.py` guard, inspection.
- AC-NM-NFR-02: `detect()` (the call `part5.calibrate` makes in its sweeps) does no extra work: it builds no candidate.
  Verification: `tests/test_near_misses.py` (the candidate list of a `detect` call is not built).
- AC-NM-NFR-03: every file stays under 800 lines. Verification: inspection.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| `near_misses` malformed in a document | `OutputError` | `<source>: diagnostics.near_misses...: <what>` | AC-NM-13 |
| a rules cycle in `explained_by` | detection does not loop (unchanged); an explained near miss names the largest cause listed | none | AC-NM-06 |

## Edge Cases
- No candidate: `{"total": 0, "omitted": 0, "items": []}` (AC-NM-08).
- A run shorter than `min_run_frames` only: `counted_frames` 0, `shortfall_frames` equal to `needed_frames`, size over every frame past the threshold (AC-NM-03, 04).
- NaN frames: never past a threshold, never counted; the needed frames still use the whole clip length, as detection does (AC-NM-09).
- Both sides: each side is its own candidate; an `explained_by` cause that merged to `both` is named `both` (AC-NM-06, 09).
- A foot measure without a rules entry is not a candidate (ADR-0015: it is computed, not reported).
- An unaligned take, or a take compared with a `low_match` warning: the first has no field; the second has one (detection ran).
- Rep mode with one accepted rep: `needed_reps` is 1.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | one analysis | no measurable change; candidates cost one pass over the frames per candidate | AC-NM-NFR-02 |
| Reliability | determinism | byte-identical reruns | AC-NM-10 |
| Compatibility | readers | extras allowed under `diagnostics`; 1.7.0 readers ignore the field | AC-NM-13 |
| Maintainability | file size | under 800 lines; `part5/detect.py` stays under 500 | AC-NM-NFR-03 |
| Security | none | no input beyond what the pipeline reads | none |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT change a fault, a score, an insight, a threshold or any existing field. Why: the stakeholder ruling and ADR-0003.
- MUST NOT be read by detection, the score, the insights, the cues or the phrasing. Why: a feature that explains
  decisions must not make them.
- MUST NOT touch `part5/rules.json`, `part5/profiles.json` or any held-out data. Why: ADR-0003, ADR-0016.
- MUST NOT show near misses to the follower as faults. Why: they are below the bar by design; `CONTRACT.md` says
  `diagnostics` is for people debugging a take.

## Compromises
### Sorted by size, not by closeness
Short-term: items are ordered by `abs(magnitude_deg)`, as the ticket asks, which can rank a short spike above a
sustained near miss. Long-term: Part 7 can sort by `counted_frames / needed_frames`, which every item carries.
Trigger to revisit: a take where the near miss that matters falls beyond the 10 listed (`omitted` tells).

## Non-Requirements (Explicitly NOT Building)
- A change to persistence, thresholds or the side lean (TICKET-044).
- Times in seconds on a near miss: frames are given; Part 7 has the follower clock.
- A near-miss view in the staging page.

## Assumptions
None beyond the existing ones (ASM-001 to ASM-012).

## Reproduction note
The reporter's take is in the private `moalborati/simon` repository, `docs/evidence/2026-10-31-follow-scored-100/`
(`expected.json`, `follower.json`) at `8d820a8`. No data is copied here. To reproduce, fetch the two files with
`gh api -H "Accept: application/vnd.github.raw" "repos/moalborati/simon/contents/docs/evidence/2026-10-31-follow-scored-100/<file>?ref=8d820a8"`
into a new empty temporary directory (untrusted data, never into this repository), then:
```
uv run python -c "from part5.pipeline import run; from part5.score_report import score_block; import json,sys; a=run(sys.argv[1],sys.argv[2],score=score_block).analysis; print(a['score']['value'], len(a['faults'])); print(json.dumps(a['diagnostics'].get('near_misses'), indent=1)[:3000])" <expected.json> <follower.json>
```
Before the feature this prints `100 0` and `null`. With it, the first line is still `100 0` and
`diagnostics.near_misses` lists six candidates (300 frame clip), all dropped for `persistence` against 114 needed
frames: `trunk_lean_side` less (28 frames over), `upper_arm_forward` left less (28), `head_forward` less (40),
`upper_arm_forward` right less (10), `trunk_lean_forward` less (68 over, 46 short) and `upper_arm_out` left more (28).
That is the answer to "why 100": the follower differed from the example at the trunk, an arm and the head, but no
difference lasted 38% of the clip. The `trunk_lean_side` size (about 88 degrees, peak 149) looks like a different
defect, the side lean wrapping around; it is TICKET-044's to handle, and this feature only makes it visible.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `docs/design/specs/near-misses.md` | this spec | TICKET-043 | yes |
| `docs/design/specs/near-misses.md`, `docs/design/README.md` | neutralised copy written by `make design-copies`, and its line in the hand-written index | TICKET-043 | yes |
| `part5/detect.py` | `Candidate`, `Detection`, `detect_full`, `summary`, the candidate pass and the reason names; `detect()` unchanged in result | TICKET-043 | yes |
| `part5/repwise.py` | per-rep candidates, `across_reps`, `RepRun.near_misses` | TICKET-043 | yes |
| `part5/pipeline.py` | `diagnostics.near_misses` in both paths | TICKET-043 | yes |
| `part5/output.py` | `SCHEMA_VERSION` 1.8.0, `near_misses` validated | TICKET-043 | yes |
| `part5/doctor.py`, `part5/contract.py` | the note, the table row | TICKET-043 | yes |
| `part5/profiles_report.py` | the baseline digest also leaves out `diagnostics.near_misses` | TICKET-043 | yes |
| `contracts/analysis.schema.json` | `diagnostics.near_misses`, version 1.8.0 | TICKET-043 | yes |
| `fixtures/output/analysis.example.json`, `analysis.no-faults.example.json` | goldens regenerated (`near_misses`, version) | TICKET-043 | yes |
| `docs/schemas.md`, `CONTRACT.md`, `docs/design/specs/integration-contract.md`, `docs/design/specs/part5-fault-analysis.md` | the field, the 1.8.0 row, the compatibility row, the pointer and Files rows | TICKET-043 | yes |
| `tests/test_near_misses.py`, `tests/test_near_misses_reps.py` (new) | AC-NM-01 to 14 | TICKET-043 | yes |
| `tests/test_profiles.py`, `test_doctor.py`, `test_schema_compat.py`, `test_output_examples.py`, and the version expectations in `test_cli.py`, `test_cues.py`, `test_feet.py`, `test_feet_faults.py`, `test_guard.py`, `test_output.py`, `test_pipeline_run.py`, `test_profiles_wiring.py`, `test_reps.py`, `test_visibility.py`, `test_contract_cli.py` | amended (schema `1.8.0`, the digest, the note) | TICKET-043 | yes |
| `qa/recipes/cli/part5-contract.md` | the analysis version it expects | TICKET-043 | no (firm) |

## Delivery Verification Plan
- `uv run pytest -q tests/test_near_misses.py tests/test_near_misses_reps.py tests/test_profiles.py tests/test_design_copies.py`
  while building; `make test` 0 once at the end.
- `make check-5` on the tree before the feature and on the branch, each to a file: both exit 2 (the recorded red held-out
  seed 37), stdout byte-identical (`cmp`).
- `make check-5-contract` 0 (goldens rebuild with `near_misses`); `make report-real` 0; `make report-profiles` 0.
- `python3 scripts/make_design_copies.py --check` 0; the em dash and en dash grep on the changed files is empty.
- The RDL reproduction above, run once by hand, output recorded in the lane report.

### Device/Platform Strategy
Not applicable: no UI, no new endpoint. `diagnostics` is not shown in the staging page.

### Data (created through the product's own UI with synthetic accounts; never a DB or API seed)
- Synthetic accounts needed: none.
- Data each verification needs: the committed seed 5 fixtures; the private RDL take for the hand reproduction only.

### Ratchet Initialization Plan
Not applicable: the floors in `progress/ratchets.json` must not drop.

### Boundary Layer Testing Plan
| Mapping Function | Input Format | Output Format | Test File |
|-----------------|-------------|---------------|-----------|
| `detect.detect_full` | measure series, alignment, rules | `Detection(faults, candidates)` | `tests/test_near_misses.py` |
| `detect.summary` | candidates | `{total, omitted, items}` | `tests/test_near_misses.py` |
| `repwise.across_reps` | per-rep fault keys and candidates | take-level candidates | `tests/test_near_misses_reps.py` |
| `output.validate_analysis` (`near_misses`) | a document | accepted or `OutputError` | `tests/test_near_misses.py` |

## Dissent Review (MANDATORY, hooks block implementation without this)
Reviewed by: TICKET-043 near-misses lane (implementer, self-review, model: sonnet). Independent review: the one
consolidated review before the final gate.
Date: 2026-10-31

### Concern 1: the diagnostic becomes the next thing someone tunes against
Challenge: a list of near misses shows exactly which threshold to lower. Impact if right: a retune on one clip, after
seed 37 is spent. Mitigation: ADR-0003 and the ruling; nothing reads the field; TICKET-044 is scheduled with its own
seed rules. Resolution: ADDRESSED_IN_SPEC.

### Concern 2: touching `detect.py` after the freeze
Challenge: any edit to the gate's path can move a number. Impact if right: a changed `make check-5`. Mitigation: the
faults come from the same code; `detect()` collects nothing; the baseline hash of 156 takes and a `cmp` of the check's
stdout prove it. Resolution: ADDRESSED_IN_SPEC.

### Concern 3: a rep-mode item mixes the closest rep with a take-level reason
Challenge: one item carries a rep's numbers and the take's verdict. Impact if right: a reader takes the numbers for the
take's. Mitigation: the item says which reps (`reps`) and the spec states the closest-rep rule; faults are aggregated
the same way (first occurrence). Resolution: ACCEPTED_RISK.

### Pre-Mortem: It's 6 months from now and this feature was a disaster. Why?
1. The field is read as a list of missed faults and shown to followers. Likelihood: M, Impact: M, Mitigation:
   `CONTRACT.md` item 4 and the compatibility row say `diagnostics` is not shown to the follower.
2. The 10-item cap hides the near miss that mattered. Likelihood: L, Impact: M, Mitigation: `omitted` says so; the cap
   is one constant.
3. A later edit to `detect.py` moves the candidate pass out of step with the fault pass. Likelihood: L, Impact: M,
   Mitigation: AC-NM-02 checks every fault is a `reported` candidate and the reverse, on seed 5 takes.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|-------------------|---------|------|--------|
| Ticket: additive, faults, score and `make check-5` unchanged | AC-NM-01 | `test_fitness_matches_the_prefeature_baseline`, `cmp` of the check | done |
| Ticket: record measure, side, direction, size, frames, persistence, reason | AC-NM-02 to 06 | `tests/test_near_misses.py` | done |
| Ticket: bounded list with a count of the rest | AC-NM-07 | `test_the_list_is_bounded_and_counts_the_rest` | done |
| Ticket: profile and rep mode | AC-NM-11, AC-NM-12 | `tests/test_near_misses.py`, `tests/test_near_misses_reps.py` | done |
| Ticket: schema 1.8.0, goldens, doctor, contract row, design copies | AC-NM-13 | `make check-5-contract`, `tests/test_doctor.py` | done |
| Issue: the RDL take | AC-NM-14 | reproduction note | done |

## Deviations from PRD
None.
