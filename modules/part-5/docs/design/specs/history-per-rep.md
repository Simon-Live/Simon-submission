# Spec: per-rep fields for comparing takes, analysis 1.12.0 (`rep_sizes`, per-rep tempo, near-miss `margin_deg`)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-11-01
Linked PRD: none (moalborati/simon#61, operator instruction of 2026-11-01T21:03Z and 21:09Z; stakeholder-proxy ruling of 21:35Z)
Linked CRD: none
Request Type: feature-mod
Risk Level: low
Master spec: `part5-fault-analysis.md` ("Repetitions"). ADRs: ADR-0010 (repetition by repetition), ADR-0013 (windows),
ADR-0014 Amendment 4 (no tempo on a low match), ADR-0003 (detection is frozen). Ticket: TICKET-071. Companion specs:
`near-misses.md`, `integration-contract.md`.

## Overview
Part 7 compares takes with each other: the same fault across one follower's takes, the same rep across sessions, how close
a near miss came. Three things are missing for that. A fault of a take compared rep by rep carries one size for the whole
take (the median over its reps) and the list of reps it was found in, but not how big it was in each. `score.per_rep` has
each accepted rep's value and grade, but not which rep it is or how fast it was. A near miss has its size and its
threshold, but not the difference between them.

Analysis 1.12.0 adds three fields, all derived from what detection and the score already found:

- `faults[].rep_sizes`: for a fault of a take compared rep by rep, one `{rep, magnitude_deg, side, body_part}` for each rep
  in the fault's `reps`.
- `score.per_rep[].rep` and `.tempo_ratio`: the rep the entry is for and its tempo.
- `diagnostics.near_misses.items[].margin_deg`: the candidate's size past its threshold, in degrees.

Detection, the score and the insights are unchanged and read none of the three. `make check-5` prints the same bytes. A
1.11.0 document still validates, and every new document is 1.12.0 as every minor before it was.

## Why This Is Wrong (Dissent-First)
1. **A new number invites a new rule.** Sizes per rep and margins show which reps nearly failed, and someone will tune a
   threshold or the half rule against them. Answer: the fields are written after detection and the score, nothing reads
   them, ADR-0003 still bars retuning on what they show, and a test pins that both baseline digests leave them out.
2. **Sizes of different sides share one list.** A rep that found both sides gives the two sides' mean, a rep that found one
   gives that side's size. Answer: every entry names its side, and the fault's own `magnitude_deg` is the median of the
   entries on its side (every entry for a fault on `both`), which a test checks on the real eight-rep take.
3. **A negative margin that never occurs.** Detection lists a candidate only when a frame is past its threshold and a
   candidate's magnitude is the median of such frames, so `margin_deg` is 0 or more in everything written today. Answer: the
   ticket asks how far a candidate went past the threshold or stayed short of it, so the sign is defined once, in the schema
   and the docs, and the schema says no negative value is written now; the function that makes it is tested on the negative
   side, and the seed 5 takes of all three profiles are checked to hold only 0 or more.
4. **`per_rep` lists accepted reps only.** The position of an entry is then not its rep. Answer: `rep` is the follower
   repetition's index, the key that joins `faults[].reps`, `rep_sizes[].rep` and `score.timeline[rep]`.
5. **Two baselines hash these documents.** The fitness baseline hashes the faults and the score, the detection baseline the
   faults and the near misses. Answer: both digest functions leave the 1.12.0 keys out of the item that carries them, as
   they did for the 1.9.0 additions, and neither baseline is regenerated.

## User Story
As Part 7's pattern finder, I want the size, the side and the tempo of every rep and the margin of every near miss in the
analysis itself, so that I can compare takes like with like without re-deriving them from the clips.

### Jobs-to-be-Done
- Functional: say "your right elbow was most off in rep 5" and "this near miss was 3 degrees past its threshold in each of
  your last four takes" from the documents alone.
- Emotional: trust a pattern because it is built from the numbers Part 5 measured.
- Social: show a trainer one table of reps, sizes and tempo for a session.

## The fields

### `faults[].rep_sizes`
Written on a fault of a take compared one repetition at a time (`repwise.compare`), in the same place as `reps`, and absent
otherwise. It lists the fault's size in each rep that found it, in rep order, one entry for each rep in `reps`:

| Key | Meaning |
|---|---|
| `rep` | the follower repetition (0-based), the index `reps` uses |
| `magnitude_deg` | that rep's own size, signed like the fault's `magnitude_deg` (`more` positive, `less` negative) |
| `side` | the side that rep found the fault on: `left`, `right`, `both` or `center` |
| `body_part` | the body part of that rep's occurrence, the fault's for the same measure |

The entries are the occurrences `repwise.aggregate_faults` already keeps, listed rep by rep:

- A fault reported on `both` sizes itself from one occurrence per rep (`_once_per_rep`): the rep's `both` fault, else its
  larger one-sided fault. Each entry is that occurrence and its side is the side the rep found.
- A fault reported on one side sizes itself from that side's own occurrences. Its `reps` also holds the reps that found it
  as part of `both` (recheck N1); each of those has an entry that is the rep's own `both` fault, side `both`, whose size is
  the two sides' mean.
- A rep the guard refused is not an accepted rep and has no entry.

So the fault's own `magnitude_deg` is the median of the entries whose side is the fault's side (every entry for a fault on
`both`). A fault of a take compared as a whole has neither `reps` nor `rep_sizes`.

### `score.per_rep[].rep` and `.tempo_ratio`
`score.per_rep` lists the accepted reps' value and grade (1.3.0). Each entry now also has:

- `rep`: the follower repetition the entry is for. The timeline has one window per follower rep, so `rep` is also the
  position of its window in `score.timeline`. A rep that did not match is left out of `per_rep` and the others keep
  their own index.
- `tempo_ratio`: that window's `tempo.ratio` (follower seconds per example second, rounded to 0.01), a number, or null where
  the rep could not be timed (the example's rep is under 1 s) and for every rep of a take whose `match.quality` is `low`.
  That is TICKET-063's rule: `score.tempo_ratio` is the one place a ratio is made, and the entry copies the window's, so it
  cannot disagree with `score.timeline[rep].tempo.ratio` or with the take's `score.tempo`.

### `diagnostics.near_misses.items[].margin_deg`
`abs(magnitude_deg)` minus `threshold_deg`, rounded to 0.1 degree, and never `-0.0`. The sign:

- positive: the candidate went past the threshold by that many degrees before persistence (or the rep count) dropped it;
- 0: it sat on the threshold;
- negative: it stayed short of the threshold by that many degrees.

The size is `abs(magnitude_deg)`, so the sign does not depend on the direction. The margin uses the magnitude (the median
over the counted runs, else over every frame past the threshold) and not the peak, the same size the score's `r` uses for a
fault; a reader who wants the peak's margin has `peak_deg` and `threshold_deg`. Detection lists a candidate only when a frame
is past its threshold, so every value written today is 0 or more; the negative sign is defined so no reader has to guess it.
In rep mode the margin belongs to the item's own numbers (the rep that came closest), like the rest of the item.

## Acceptance Criteria
### AC-HR-01: additive schema
Given a new document, then `schema_version` is `1.12.0`, it validates against `contracts/analysis.schema.json` (version
`1.12.0`, whose description names the three fields and the sign of the margin) and against `validate_analysis`. Given a
1.11.0 document (the goldens with the three fields taken out), then it still validates against both. Verification:
`tests/test_history_per_rep.py`, `tests/test_contract_part7_history.py`, `tests/test_schema_compat.py`.
### AC-HR-02: rep sizes
Given a take compared rep by rep, then every fault has `rep_sizes` with one entry for each rep in `reps`, in order, signed
like the direction, with the side that rep found; the fault's `magnitude_deg` is the median of the entries on its side. Given
a fault reported on one side that a rep found as part of `both`, then that rep's entry has side `both` and the rep's own `both`
size. Given a rep the guard refused, then it has no entry. Given a take compared as a whole, then no fault has `rep_sizes`.
Verification: `tests/test_history_per_rep.py`.
### AC-HR-03: tempo per rep
Given a take compared rep by rep, then each `per_rep` entry has `rep` and `tempo_ratio` equal to the `tempo.ratio` of
`score.timeline[rep]`. Given a low match, then every `tempo_ratio` is null, under every profile. Given a rep whose ratio
`score.tempo_ratio` could not make, then its entry is null and the others keep theirs. Given a rep that did not match, then the
others keep their own index. Verification: `tests/test_history_per_rep.py`.
### AC-HR-04: margin
Given a near miss, then `margin_deg` is `abs(magnitude_deg)` minus `threshold_deg` to one decimal, for every reason and both
directions; the function is positive past the threshold, 0 on it and negative short of it, and never `-0.0`. Given the seed 5
takes under each profile, then every margin is 0 or more. Verification: `tests/test_history_per_rep.py`.
### AC-HR-05: validation
Given a document whose `rep_sizes`, `per_rep` entry or `margin_deg` breaks the rules above (entries not matching `reps`, a
side or body part that does not go with the measure, a size not signed like the direction, a ratio that is not a number or
null, a ratio that differs from the window's, a margin that is not the difference), then `validate_analysis` raises
`OutputError` naming the field, and the schema rejects the shapes it can. That the ratio is null on a low match is the
producer's rule (AC-HR-03), as it is for the windows' `tempo`, which the validator does not check either. Verification:
`tests/test_history_per_rep.py`.
### AC-HR-06: detection and the score are unchanged
Given the tree before and after, then `make check-5` prints the same bytes (compared with `cmp`), the fitness baseline
(`fixtures/profiles-fitness-baseline.json`) and the detection baseline (`fixtures/seed5-detection-baseline.json`) are not
regenerated and still match, and the digests do not see the three fields while they still see a changed fault, score or near
miss. Verification: `tests/test_history_per_rep.py`, `tests/test_near_misses.py`, `tests/test_detection_baseline.py`,
`tests/test_profiles.py`, the `cmp` below.
### AC-HR-07: goldens and docs
Given `make output-examples`, then the four analysis goldens differ from before in `schema_version` and the new fields only,
and the replay golden is unchanged. `CONTRACT.md`, `docs/schemas.md`, the contract row (`part5 contract`), the
integration spec and the schema description name 1.12.0. Verification: `make check-5-contract`, `tests/test_output_examples.py`,
`tests/test_contract_cli.py`.

### Rule-Based ACs
- AC-HR-NFR-01: no network call, no new dependency. Verification: `tests/conftest.py` guard, inspection.
- AC-HR-NFR-02: every file stays under 800 lines. Verification: inspection.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| `rep_sizes` empty, or not one entry per rep in `reps` | `OutputError` | `<source>: faults[i].rep_sizes must ...` | AC-HR-05 |
| an entry's side or body part does not go with the measure | `OutputError` | `faults[i].rep_sizes[j].side` or `.body_part` | AC-HR-05 |
| an entry's size is zero or not signed like the direction | `OutputError` | `faults[i].rep_sizes[j].magnitude_deg ...` | AC-HR-05 |
| `per_rep[i].rep` is not an index, or `tempo_ratio` is not a number of at least 0 or null | `OutputError` | `score.per_rep[i].rep` or `.tempo_ratio` | AC-HR-05 |
| `tempo_ratio` differs from the `tempo.ratio` of its window | `OutputError` | `score.per_rep[i].tempo_ratio must ...` | AC-HR-05 |
| `margin_deg` is not the difference | `OutputError` | `diagnostics.near_misses.items[i].margin_deg must ...` | AC-HR-05 |

## Edge Cases
- A single accepted rep: `rep_sizes` has one entry.
- A fault found as `both` in every rep: every entry has side `both`.
- A rep found the fault on both sides without merging them: the larger side stands for the rep, as for the fault's size.
- A near miss that sat exactly on its threshold after rounding: `margin_deg` is `0.0`.
- All reps unmatched: `per_rep` is empty, as before.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Compatibility | readers built on 1.11.0 | the three fields are optional and extra keys are allowed | AC-HR-01 |
| Reliability | determinism | byte-identical reruns | AC-HR-07 |
| Maintainability | file size | every file under 800 lines | AC-HR-NFR-02 |
| Performance | none measurable | no extra pass over the frames | AC-HR-06 |
| Security | none | no new input | none |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT change a fault, a score, an insight, a threshold or any existing field. Why: ADR-0003 and the ruling.
- MUST NOT be read by detection, the score, the insights, the cues or the phrasing. Why: a field that describes decisions
  must not make them.
- MUST NOT regenerate `fixtures/profiles-fitness-baseline.json` or `fixtures/seed5-detection-baseline.json`. Why: they were
  taken before the fields existed and prove that nothing else moved.
- MUST NOT make a second tempo ratio. Why: `score.tempo_ratio` is the one place (TICKET-063).

## Compromises
### The margin is on the magnitude
Short-term: `margin_deg` uses the median size, so a short spike far past the threshold shows a small margin.
Long-term: a reader who wants the peak has `peak_deg` and `threshold_deg`. Trigger to revisit: Part 7 asks for the peak's
margin as a field.

## Non-Requirements (Explicitly NOT Building)
- A per-rep list of near misses (a near miss stays one item for the take, `near-misses.md`).
- A tempo ratio for a rep that was not compared.
- Editing `contracts/history-fields.json` (TICKET-070) on the lane branch. The eight entries 1.12.0 adds (`faults[].rep_sizes`
  and its four keys, `score.per_rep[].rep` and `.tempo_ratio`, `diagnostics.near_misses.items[].margin_deg`) were added when
  the lane merged, and the file's `analysis_schema_version` moved to 1.12.0 with its own `version` at 1.1.0.
- A change to the staging page.

## Assumptions
None beyond the existing ones (ASM-001 to ASM-012).

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `docs/design/specs/history-per-rep.md` | this spec | TICKET-071 | yes |
| `docs/design/specs/history-per-rep.md`, `docs/design/README.md` | neutralised copy written by `make design-copies`, and its line in the index | TICKET-071 | yes |
| `part5/detect.py` | `margin_deg()`, and `Candidate.to_dict` writes it | TICKET-071 | yes |
| `part5/repwise.py` | `rep_sizes()`, and `_times` puts it in each fault's times | TICKET-071 | yes |
| `part5/score_report.py` | `per_rep` entries carry `rep` and `tempo_ratio` | TICKET-071 | yes |
| `part5/output.py` | `SCHEMA_VERSION` 1.12.0, `rep_sizes` written and validated, `per_rep` and `margin_deg` validated | TICKET-071 | yes |
| `part5/profiles_report.py` | both baseline digests leave the 1.12.0 keys out | TICKET-071 | yes |
| `part5/contract.py` | the analysis row of the compatibility table | TICKET-071 | yes |
| `contracts/analysis.schema.json` | version 1.12.0, `rep_sizes`, `per_rep` fields, `margin_deg`, the description | TICKET-071 | yes |
| `fixtures/output/analysis*.example.json` | regenerated by `make output-examples` | TICKET-071 | yes |
| `CONTRACT.md`, `docs/schemas.md`, `docs/dev/DEVELOPING.md`, `docs/design/specs/integration-contract.md`, `docs/design/specs/near-misses.md`, `docs/design/specs/part5-fault-analysis.md` | the version, the three fields, the sign, AC-C20 | TICKET-071 | yes |
| `tests/test_history_per_rep.py` (new) | AC-HR-01 to 06 | TICKET-071 | yes |
| `tests/test_contract_part7_history.py` and the version expectations in `test_cli.py`, `test_contract_cli.py`, `test_cues.py`, `test_doctor.py`, `test_feet.py`, `test_feet_faults.py`, `test_guard.py`, `test_near_misses.py`, `test_near_misses_reps.py`, `test_output.py`, `test_output_examples.py`, `test_part7_no_person.py`, `test_phrasing_lang.py`, `test_pipeline_run.py`, `test_profiles_wiring.py`, `test_reps.py`, `test_schema_compat.py`, `test_score_v2.py`, `test_visibility.py` | amended (schema `1.12.0`) | TICKET-071 | yes |
| `qa/recipes/cli/part5-contract.md` | the analysis version it expects | TICKET-071 | no (firm) |

## Delivery Verification Plan
- `uv run pytest -q tests/test_history_per_rep.py tests/test_contract_part7_history.py tests/test_near_misses.py
  tests/test_detection_baseline.py tests/test_design_copies.py` while building; `make test` once at the end.
- `make check-5` on the tree before the change and on the branch, each to a file, stdout compared with `cmp`.
- `make check-5-contract` 0 (the goldens rebuild with the new fields).
- `python3 scripts/make_design_copies.py --check` 0; the dash scan of the changed lines is empty.

### Device/Platform Strategy
Not applicable: no UI and no new endpoint. The staging page does not show these fields.

### Data (created through the product's own UI with synthetic accounts; never a DB or API seed)
- Synthetic accounts needed: none.
- Data each verification needs: the committed seed 5 fixtures and the real lateral-raise clips.

### Ratchet Initialization Plan
Not applicable: the floors in `progress/ratchets.json` must not drop.

### Boundary Layer Testing Plan
| Mapping Function | Input Format | Output Format | Test File |
|-----------------|-------------|---------------|-----------|
| `repwise.rep_sizes` | kept fault, rep indices, occurrences, reps | `[{rep, magnitude_deg, side, body_part}]` | `tests/test_history_per_rep.py` |
| `detect.margin_deg` | magnitude, threshold | degrees to 0.1 | `tests/test_history_per_rep.py` |
| `score_report._rep_timeline` (`per_rep`) | a rep-by-rep result | `{value, grade, rep, tempo_ratio}` entries | `tests/test_history_per_rep.py` |
| `output.validate_analysis` | a document | accepted or `OutputError` | `tests/test_history_per_rep.py` |

## Dissent Review (MANDATORY, hooks block implementation without this)
Reviewed by: TICKET-071 lane (implementer, self-review, model: sonnet). Independent review: the one consolidated review at
the merge.
Date: 2026-11-01

### Concern 1: the fields become inputs
Challenge: a margin or a per-rep size is the obvious thing to feed back into a threshold. Impact if right: a retune on one
take after the held-out seeds are spent. Mitigation: nothing in Part 5 reads them, both baselines hash a document without
them, and ADR-0003 still bars retuning on what they show. Resolution: ADDRESSED_IN_SPEC.

### Concern 2: `rep_sizes` and `reps` drift apart
Challenge: a later edit to the aggregation changes which reps a fault counts and the list no longer matches. Impact if right:
a pattern finder joins the wrong reps. Mitigation: `validate_analysis` requires one entry for each rep in `reps`, in order,
so a producer that drifts fails to write. Resolution: ADDRESSED_IN_SPEC.

### Concern 3: a negative margin is documented and never written
Challenge: a sign with no data behind it is untested in the field. Impact if right: a reader branches on a case that does not
occur. Mitigation: the schema and the docs say so in the same sentence as the sign, and the function is tested on it.
Resolution: ACCEPTED_RISK.

### Pre-Mortem: It's 6 months from now and this feature was a disaster. Why?
1. A reader treats a `both` entry's mean as one side's size. Likelihood: M, Impact: L, Mitigation: every entry names its side
   and the docs say what a `both` entry is.
2. `per_rep` is joined by position. Likelihood: L, Impact: M, Mitigation: `rep` is in every entry and the docs say why.
3. A producer fills `tempo_ratio` itself. Likelihood: L, Impact: M, Mitigation: the validator requires the window's ratio,
   and a test pins the null on a low match for every profile.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|-------------------|---------|------|--------|
| Ticket: size per rep with side and body part | AC-HR-02 | `tests/test_history_per_rep.py` | done |
| Ticket: tempo per rep, null where unmeasured (TICKET-063) | AC-HR-03 | `tests/test_history_per_rep.py` | done |
| Ticket: near-miss margin, sign defined | AC-HR-04 | `tests/test_history_per_rep.py` | done |
| Ticket: additive, 1.11.0 still validates | AC-HR-01, AC-HR-05 | `tests/test_history_per_rep.py`, `tests/test_contract_part7_history.py` | done |
| Ticket: detection and the score unchanged | AC-HR-06 | `cmp` of `make check-5`, the digests | done |
| Ticket: goldens for the new fields only, docs name 1.12.0 | AC-HR-07 | `make check-5-contract` | done |

## Deviations from PRD
None.
