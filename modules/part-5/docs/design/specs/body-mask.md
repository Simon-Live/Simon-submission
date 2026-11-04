# Spec: score the body you have, a declared mask applied at scoring (analysis 1.14.0)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-11-02
Linked PRD: none (hub TICKET-275, Part 5's share TICKET-084; the operator's fan-out order on moalborati/simon#61)
Linked CRD: none
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADRs: ADR-0023 (this change), ADR-0011 (compare only what the camera sees), ADR-0012
(always analyse), ADR-0013 (the score timeline), ADR-0019 (the score), ADR-0020 (the credit display). Ticket: TICKET-084.
Companion specs: `integration-contract.md`, `score-v3.md`, `score-credit.md`.

## Overview
A follower can declare that some limb chains are not scored: `seated` (the legs are not scored), or "not using" one or more
chains (an arm from the shoulder, a forearm from the elbow, a leg from the hip). Part 5 drops every measure that reads a
masked joint, on every frame of both the example and the follower, from detection and from the score, so a masked chain is
never scored, faulted, cued or named in an insight. Alignment, the movement guard and repetition segmentation still read the
whole body (ADR-0023). The analysis then carries an additive `body_mask` block that lists the scored and the not scored
chains. With no mask declared, the analysis is byte for byte what it was.

Ask this take (`docs/design/specs/ask-this-take.md`) reads the same block (R3 of the 1.14.0 review): its tools refuse to read an
angle at, or highlight, a joint the block lists as masked, and leave out the measures it lists as not scored, because the
replay still holds the masked limbs' made-up motion. The second opinion reads it too (N3 of the 1.14.0 recheck,
TICKET-084; `docs/design/specs/second-opinion.md` AC-SO-04): its guard refuses a note that names a body part the mask leaves
not scored, though the camera shows it, and a block that fails its check sends nothing.

The mask comes from the command line (`part5 analyse --mask`) or the analysis API (the `mask` field of `POST api/analyse`).
It does not come from `part5/profiles.json`: the profiles are tolerances for how picky judging is (ADR-0016), the loader
refuses a key it does not know, and adding a mask to a shipped profile would change the file and so `profiles_sha256`. The
"profile setting" of hub TICKET-275 is Part 7's own setting for a person, which Part 7 passes through the API.

## Why This Is Wrong (Dissent-First)
1. **The 3D model still invents the limb.** SAM 3D Body puts a mesh limb where the real one is absent or behind a chair, so
   the masked joints carry made-up motion. Answer: the mask applies at scoring, so nothing made up is scored; alignment still
   reads it, and ADR-0023 records why that is contained (each timing measure's cost is capped, a held limb is an offset the
   second alignment pass removes) and what stays a risk (the guard can call a take with a held arm a low match).
2. **The score is calibrated on the full body.** `z0` and `z1` of the similarity term and the fault penalties were fitted on
   seed 5 full-body takes. A masked take is scored on fewer measures, so its value is comparable only with takes scored under
   the same mask. Answer: stated here, in `docs/schemas.md` and in `CONTRACT.md`; `body_mask` says which mask a score was made
   under, and no number was refitted.
3. **A fault on both sides belongs to two chains.** Detection merges the same measure and direction on the left and the right
   into one `both` fault, sized as the mean of the two. Masking one side leaves the other side's fault, sized on that side
   alone, so its size, frames and cost can differ from the merged fault's. Answer: AC-BM-04 states the property per side and
   per measure family, and tests exactly that.
4. **There is no shin chain.** The hub ticket names chains "from shoulder, elbow, hip or knee". A shin mask would drop
   `foot_out` and `knee_valgus`, which explain a thigh fault in `part5/rules.json` (`explained_by` and
   `explained_by_opposite` of `thigh_out`): the thigh fault would then be reported where the full analysis drops it, so a
   shin mask would change a chain it does not cover. Answer: the shin is not offered; the leg is masked from the hip.
5. **Nobody who needs this tested it.** It was designed for and tested on seated and masked takes from the fixtures, not
   with wheelchair users or amputees. Answer: that is the limits line, in this spec, in `CONTRACT.md` and in the schema.

## User Story
As a follower who is seated, or who does not use a limb, I want Part 5 to score only the body I use, so that a limb I do not
move, or one the camera model invents, never costs me points or earns me a cue.

### Jobs-to-be-Done
- Functional job: a score and a fault list for the limbs the follower uses.
- Emotional job: not being told to fix a limb one does not have or cannot use.
- Social job: a coaching app that does not assume two arms, two legs and a standing body.

## The chains and the presets
Each chain hangs from a joint that stays scored and masks the joints below it (`part5/mask.py`, `CHAINS`). A measure is
dropped when any joint it reads is masked: `measures.MEASURE_JOINTS` for the body measures, `measures.VIEW_MEASURES` for the
head and shoulder view measures and, for the foot measures, the points `measures.compute_feet` reads.

| Chain | Hangs from | Masked joints | Body measures dropped (each of its own side) |
|---|---|---|---|
| `left_arm`, `right_arm` | the shoulder | elbow, wrist | `elbow_flexion`, `upper_arm_out`, `upper_arm_forward`, `forearm_out` |
| `left_forearm`, `right_forearm` | the elbow | wrist | `elbow_flexion`, `forearm_out` |
| `left_leg`, `right_leg` | the hip | knee, ankle, and the heel and toes of a feet file | `knee_flexion`, `knee_valgus`, `thigh_out`, `thigh_forward`, `foot_out`, and the foot measures `foot_rotation`, `ankle_inversion` |

The view measures `wrist_height` and `wrist_out` of a side read its wrist, so an arm or a forearm mask drops them too; they
are never reported or scored (ADR-0011) and are listed for completeness only. The four centre measures (`trunk_lean_forward`,
`trunk_lean_side`, `shoulder_tilt`, `head_forward`) read the shoulders, the hips and the nose, which no chain masks: they
are always scored.

Presets: `seated` is `left_leg` and `right_leg`; `full_body` masks nothing. Names are lower case and exact. A mask is a set:
naming a chain twice, or an arm and its own forearm, is the same as naming the arm. `full_body` cannot be combined with any
other name.

## How the mask meets ADR-0011 visibility
Visibility (`part5/visibility.py`) hides a joint the camera did not see (conf at the 0.3 unseen mark) before alignment,
because an unseen joint is not data. The mask hides a joint the follower declared, after alignment, because a declared limb
is a scoring choice: the joints are there (or invented) and timing may still be read from them (ADR-0023). Both are NaN:
`hide_masked` sets the dropped measures' series to NaN, which is what NaN at the masked joints on every frame gives through
`measures.compute` (AC-BM-02 tests the equivalence). The two never cancel each other: a measure is scored only when visibility
uses it and the mask does not drop it. `diagnostics.visibility` keeps reporting what the camera did not see, and `body_mask`
what the follower declared.

## What the score does
The take is scored on the remaining measures, by the shipped formula with no parameter changed (`part5/rules.json`, the score
params and `params_sha256` are untouched):
- **Faults (`components.faults`).** A sum of each remaining fault's cost in the window. Nothing is reweighted: a masked
  fault is simply not there. The fault ceiling (89 for one, 79 for two or more under v3) counts the remaining faults.
- **Similarity (`components.similarity`).** `mean_z` is the mean of the clipped `z` over every finite measure and frame
  cell of the window (`score.mean_z`); a dropped measure's cells are NaN and are left out, so the mean is over the remaining
  measures, each cell weighing one over their number. The similarity term renormalises in that sense and no other. Masking
  a chain the follower followed well can raise `mean_z`, so lower the score; masking one followed badly can raise it.
- **Credit (`score.credit`).** A dropped measure is not finite in any frame, so it fails the half-window rule and is not
  counted: `max_points` falls by its share and `percent` is earned over possible on the remaining measures.
- **Tempo (dance) and the warning cap.** Unchanged: they read no measure the mask drops.

AC-BM-10 verifies each line in code. When every chain is masked, the four centre measures remain, more than the visibility
minimum (`MIN_USABLE_MEASURES`, 3), so the take is scored on them and no warning fires because of the mask. No warning or
error exists for "too few scored measures": `not_enough_visible` and `no_usable_measures` are about what the camera saw and
are judged before the mask. If visibility has already left only limb measures and the mask drops those, the window has no
finite cell and the take gets the zero score of ADR-0012 (0, grade F) with whatever warnings visibility gave; the mask adds
no warning of its own.

## Acceptance Criteria
### AC-BM-01: Part 5 accepts a declared mask
Given `part5 analyse --mask seated` (or `--mask left_arm,right_leg`, or the API field `mask` as `"seated"` or
`["left_arm", "right_leg"]`)
When the take is analysed
Then the analysis carries `body_mask` and every measure reading a masked joint is dropped. `--mask` is listed in
`part5 analyse --help` with the names it takes.

### AC-BM-02: the same NaN as visibility, on every frame of both clips
Given a chain
When its masked joints are set to NaN in every frame of a clip
Then exactly the measures `BodyMask.measures` names are NaN in `measures.compute`, `compute_view` and `compute_feet`, and
every other series is unchanged; `hide_masked` gives the same series.

### AC-BM-03: alignment, the guard and segmentation read the whole body
Given any mask
When a take is analysed
Then `diagnostics.alignment_measures`, `alignment_residual`, `follower_span`, `diagnostics.guard`, `warnings`, `match` and
the repetition segmentation equal the unmasked analysis's.

### AC-BM-04: masking chain X leaves every other chain unchanged (property)
Given at least 3 committed seed 5 fixtures and every chain X
When the take is analysed with X masked and without a mask
Then, with D the sided measures X drops and F the measure families (side-less names) with a side in D:
- the per-side fault keys (measure, side, direction; a `both` fault counts as its left and its right) of the masked analysis
  are the unmasked analysis's keys minus those in D;
- every fault whose family is not in F is identical in both analyses, field for field, and so is every timeline miss whose
  family is not in F (its points included);
- every measure not in D has the same `z` row (the similarity term's per-frame contribution) in both;
- every near miss item whose family is not in F that the unmasked analysis lists is listed by the masked one.
A family in F on the other side keeps its keys; its size, frames and cost are that side's own when the unmasked fault was
a merged `both` (Dissent 3).

### AC-BM-05: a masked chain is never faulted, cued or named
Given a mask
Then no fault, timeline miss, insight or near miss names a dropped measure, and no fault line, cue or insight says the
masked limb ("left elbow", "hands" and so on, by chain).

### AC-BM-06: no mask, no change
Given no mask
Then the analysis is byte for byte the one Part 5 wrote before this change, apart from `schema_version` (1.14.0); the
committed goldens rebuild with only that line changed and `make check-5` prints the same stdout. Given `full_body`, the
analysis equals the unmasked one apart from `body_mask`.

### AC-BM-07: the `body_mask` block
Given a declared mask
Then the analysis has `body_mask`: `declared` (the names as given, in order, each once), `source` (`cli` or `api`),
`scored_chains` and `not_scored_chains` (a partition of the six chains, in `CHAINS` order: a chain is not scored when the
mask drops every measure it has, so the left arm is still scored when only its forearm is masked), `masked_joints` (the
canonical joints masked), `not_scored_measures` (the sided body and foot measures dropped) and `text` (the not scored line,
AC-BM-12). It is written only when a mask was declared. `validate_analysis` refuses a block of the wrong shape and a
document whose faults, misses, insights or near misses name a measure the block says is not scored.

### AC-BM-08: a bad name is refused with a typed error
Given `--mask left_hand`, an empty mask, a name in capitals, or `full_body` with another name
Then `parse_mask` raises `MaskError` naming the bad name and the names it takes; `part5 analyse` prints it as an option
error and exits 2 (as for an unknown `--profile`), and the API answers 400 with field `mask`.

### AC-BM-09: the API field
Given `POST api/analyse` with `mask` omitted or null, a string, or a list of strings
Then null or omitted analyses with no mask; a string is read as `--mask` reads it; a list names each chain or preset; any
other type, or a bad name, is a 400 naming `mask`.

### AC-BM-10: the renormalisation, verified
Given a masked take
Then `score.mean_z` of its aligned measures equals the mean of the clipped `z` cells of the remaining measures computed from
the unmasked take; `components.faults` of each window is the sum of its remaining misses' points; each window's credit counts
only the remaining measures.

### AC-BM-11: every chain masked
Given `left_arm,right_arm,left_leg,right_leg`
Then the take is scored on the four centre measures, with no warning the unmasked take did not have, `scored_chains` empty and
the text "Arms and legs not scored, by your setting."

### AC-BM-12: the words
`body_mask.text` names the maximal chains not scored (an arm holds its forearm; a pair reads as the plural): "Legs not scored,
by your setting.", "Left arm and right leg not scored, by your setting."; `full_body` reads "Whole body scored, by your
setting." The words follow the Writer's rules (no dash, no gloss, no figure). The limits line, in this spec, `CONTRACT.md`
and the schema: designed for and tested on seated and masked takes from the fixtures, not with wheelchair users or amputees.

### AC-BM-13: `doctor --for part7`
Given an analysis with `body_mask`
Then `part5 doctor <file> --for part7` notes the chains not scored and that the score compares only with takes under the same
mask.

### Rule-Based ACs
- AC-NFR-BM-01: `part5/rules.json`, `part5/detect.py`, the score params and `part5/profiles.json` are not changed.
  Verification method: inspection (`git diff`).
- AC-NFR-BM-02: no module over 800 lines; the mask's functions are small. Verification method: inspection.

## API / Interface Contract
`part5/mask.py`, a module of its own. The lane wrote it as the section "the declared body mask" of `part5/visibility.py`,
beside `hide_unseen`, because the spec gate of that workspace read its specs from the main checkout, which did not hold this
spec; once the spec was on main, the 1.14.0 round moved the section here unchanged (`mask.py` reads `ALL_JOINTS` from
`part5/visibility.py`):
- `CHAINS`: chain name to `(the joint it hangs from, the joints it masks)`; `PRESETS`: `seated`, `full_body`.
- `class MaskError(ValueError)`: a mask that names something Part 5 does not know.
- `parse_mask(text, source="cli") -> BodyMask`: a comma separated list of chain and preset names.
- `mask_from_request(value) -> BodyMask | None`: the API field; None for null.
- `BodyMask`: `declared`, `chains` (the expanded chains), `source`; `.joints`, `.measures` (every measure that reads a masked
  joint), `.not_scored_chains`, `.scored_chains`, `.block()`; `mask_text(not_scored_chains)` is the line.
- `hide_masked(mask, series) -> dict`: `series` with the dropped measures NaN; `series` itself when `mask` is None.
- `validate_mask_block(doc, fail)`: the `body_mask` checks `validate_analysis` runs.

`part5/pipeline.py`: `run(..., mask=None)`; `PipelineResult.mask`. `part5/repwise.py`: `compare(..., mask=None)`.
`part5/score_report.py`: `aligned_of(result, vis=None, mask=None)`. `part5/output.py`: `build_analysis(..., body_mask=None)`.
`part5/cli.py`: `--mask`. `part5/api.py`: the `mask` field. `part5/doctor.py`: the `--for part7` note.
`contracts/analysis.schema.json` 1.14.0: `body_mask`. `contracts/history-fields.json`: the `body_mask` paths.

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|-----------|----------|----------------|-------------|
| unknown name | `MaskError`; CLI exit 2; API 400 `mask` | `mask: unknown name 'left_hand'; use seated, full_body or a chain: left_arm, ...` | AC-BM-08 |
| empty text, empty list | `MaskError` | `mask: name a preset (seated, full_body) or at least one chain` | AC-BM-08 |
| `full_body` with another name | `MaskError` | `mask: full_body masks nothing and cannot be combined with ...` | AC-BM-08 |
| API value not a string or a list of strings | 400 `mask` | `mask: give a preset or chain name, or a list of them` | AC-BM-09 |

## Edge Cases
- Every chain masked: scored on the centre measures (AC-BM-11).
- An arm and its forearm both named: the arm; `declared` keeps both names (AC-BM-07).
- A take that could not be aligned: no faults and a zero score as before, and `body_mask` still written (AC-BM-07).
- A take compared rep by rep: each rep is detected on the masked series; segmentation reads the whole body (AC-BM-03).
- A pair with feet files: a leg mask drops that side's foot measures; `diagnostics.feet.compared` still says what the feet
  files allowed, and `body_mask.not_scored_measures` what the mask dropped.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|----------|------------|--------|-------------|
| Performance | a mask adds two dict copies per detection | no measurable change on seed 5 | n/a |
| Security | the API field is parsed, never used as a path | unknown names refused | AC-BM-09 |
| Accessibility | the not scored line is plain words | Writer rules | AC-BM-12 |
| Reliability | no mask is the old analysis | byte for byte | AC-BM-06 |
| Maintainability | tests for every AC | `tests/test_body_mask*.py` | all |
| Compatibility | additive field, minor version | schema 1.14.0 | AC-BM-07 |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT change alignment, the guard or segmentation. Why: AC-BM-04 and AC-BM-06 hold by construction only then.
- MUST NOT add a mask to `part5/profiles.json`. Why: `profiles_sha256` of the shipped profiles would change.
- MUST NOT write `body_mask` without a declared mask. Why: AC-BM-06.
- MUST NOT claim the mask was tested with wheelchair users or amputees. Why: it was not.

## Compromises
### Alignment reads the whole body
Short-term: timing and the guard read the masked limb (ADR-0023).
Long-term: a guard that leaves the masked measures out, if the staging pairs show a held limb makes a low match.
Migration path: a mask-aware guard behind its own ADR, with AC-BM-04 restated for it.
Trigger to revisit: an AC-3 staging pair (Part 7) where the unmasked take is a low match only because of the held limb.

## Non-Requirements (Explicitly NOT Building)
- The setting UI, the compare dimming and the staging takes: Part 7 owns them (hub AC-3, AC-4).
- A shin chain (Dissent 4).
- A profile setting in `part5/profiles.json` (Overview).

## Assumptions
None new. The mask is honest input: Part 5 does not check that a declared limb is absent or still.

## Implied Requirements Discovered
- The validator cross-check (AC-BM-07): a reader can trust that `not_scored_measures` never appear in faults.
- The explanation closure (Dissent 4): a chain's measures may explain only measures of the same chain; a test fails when
  `part5/rules.json` breaks it.

## Delivery Verification Plan (MANDATORY, from CRD)
The deliverable is a command line flag, an API field and an additive JSON block; there is no UI in Part 5's share.

### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|----------|------|----------|-------------|
| command line and API, GPU free | `uv run pytest -q tests/test_body_mask.py tests/test_body_mask_property.py tests/test_body_mask_surfaces.py` | n/a | the lane |

### Data
- Seed 5 fixtures (`fixtures/input/followers/`): `exercise_front_good_08_arms_wider-both+elbow_bent-right` (compared as a
  whole, a `both` arm fault), `dance_front_good_08_foot_out-left+trunk_lean-center` (compared rep by rep),
  `exercise_front_good_09_foot_turned_out-right` with its feet files (a foot measure) and
  `exercise_front_good_07_knee_caving-left` (a knee fault that explains others).
- The seated take: `fixtures/input/mismatch/part2-stretch/skeleton.json` (a real seated stretch) against itself, `seated`.

### User Journey Definition
| Step | User Action | Produces Data | Consumed By |
|------|-------------|---------------|-------------|
| 1 | `part5 analyse --expected E --follower F --mask seated --out a.json` | `a.json` with `body_mask` | Part 7 |
| 2 | `part5 doctor a.json --for part7` | the note | the reader |

### Ratchet Initialization Plan
- N/A: the engagement keeps no ratchet file for Part 5's tests.

### Boundary Layer Testing Plan
| Mapping Function | Input Format | Output Format | Test File |
|-----------------|-------------|---------------|-----------|
| `parse_mask`, `mask_from_request` | CLI text, API JSON | `BodyMask` | `tests/test_body_mask.py`, `tests/test_body_mask_surfaces.py` |
| `BodyMask.block` | `BodyMask` | `body_mask` JSON | `tests/test_body_mask.py` |

The files this spec covers: `part5/mask.py`, `part5/visibility.py` (`ALL_JOINTS`), `part5/pipeline.py`, `part5/repwise.py`, `part5/score_report.py`,
`part5/output.py`, `part5/cli.py`, `part5/api.py`, `part5/doctor.py`, `part5/contract.py`.

## Dissent Review (MANDATORY, hooks block implementation without this)
Reviewed by: the lane (implementer, model: opus), against Dissent 1 to 5 above
Date: 2026-11-02

### Concern 1: a mask that changes the alignment
Challenge: a held arm pulls the timing, so the other chains' faults move.
Impact if right: AC-BM-04 fails and the demo pair shows other faults changing.
Mitigation: the mask applies after alignment (ADR-0023).
Resolution: ADDRESSED_IN_SPEC

### Concern 2: the merged `both` fault
Challenge: "the other chains' contributions are unchanged" is false for a `both` fault.
Impact if right: a test that compares whole fault lists fails, or passes by excluding the case silently.
Mitigation: AC-BM-04 states the property per family and per side, and the test covers a `both` fixture.
Resolution: ADDRESSED_IN_SPEC

### Concern 3: a mask nobody can audit
Challenge: a follower can mask the limb that faulted to raise the score.
Impact if right: a score is not comparable across masks.
Mitigation: `body_mask` is in the document, `doctor` notes it and the contract says to compare only within one mask.
Resolution: ACCEPTED_RISK

### Pre-Mortem
1. Part 7 compares a masked score with an unmasked one. Likelihood: M, Impact: M, Mitigation: the contract paragraph and the
   doctor note.
2. The guard calls a take with a held arm a low match. Likelihood: M, Impact: M, Mitigation: ADR-0023's trigger to revisit.
3. A rules change makes a leg measure explain an arm one. Likelihood: L, Impact: M, Mitigation: the closure test.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|-------------------|---------|------|--------|
| hub AC-1 | AC-BM-01, AC-BM-07 | `test_body_mask_surfaces.py`, `test_body_mask.py` | passing |
| hub AC-2 | AC-BM-04 | `test_body_mask_property.py` | passing |
| hub AC-5 (Part 5's words) | AC-BM-12 | `test_body_mask.py` | passing |

## Test Scenarios (maps 1:1 to acceptance criteria)
- AC-BM-01 → `test_analyse_help_lists_mask_with_the_names_it_takes`, `test_cli_mask_writes_the_block_and_says_the_line`,
  `test_api_mask_field_masks_and_says_so`
- AC-BM-02 → `test_nan_at_the_masked_joints_is_exactly_the_dropped_measures`,
  `test_a_leg_mask_drops_its_foot_measures_the_way_nan_foot_points_do`
- AC-BM-03 → `test_alignment_guard_and_segmentation_ignore_the_mask`
- AC-BM-04 → `test_masking_a_chain_leaves_every_other_chain_unchanged` (4 fixtures by 6 chains),
  `test_a_chain_explains_only_measures_of_its_own_chain`
- AC-BM-05 → `test_a_masked_chain_is_never_faulted_cued_or_named`, `test_the_word_check_finds_the_limb_in_the_unmasked_analysis`
- AC-BM-06 → `test_full_body_is_the_unmasked_analysis_apart_from_the_block`,
  `test_no_mask_writes_no_block_and_the_same_bytes_as_a_call_that_names_none`, `test_cli_without_mask_writes_no_block`, and
  the existing golden rebuild (`tests/test_output_examples.py`, `make check-5-contract`)
- AC-BM-07 → `test_block_*`, `test_the_validator_*`, `test_the_schema_refuses_a_block_without_its_keys_or_with_an_unknown_chain`
- AC-BM-08 → `test_parse_refuses_a_bad_mask_with_a_typed_error`, `test_cli_bad_mask_exits_2_naming_it_and_writes_nothing`
- AC-BM-09 → `test_the_request_field_reads_null_a_string_or_a_list`, `test_api_mask_field_*`
- AC-BM-10 → `test_the_score_renormalises_on_the_remaining_measures`
- AC-BM-11 → `test_every_chain_masked_scores_the_centre`, `test_every_chain_masked_leaves_exactly_the_four_centre_measures`
- AC-BM-12 → `test_text_names_the_largest_chains_not_scored`, `test_the_example_in_docs_schemas_md_is_what_seated_writes`
- AC-BM-13 → `test_doctor_notes_the_mask_for_part7`, `test_doctor_has_no_mask_note_without_a_mask`
- ADR-0023's evidence → `test_a_held_arm_is_faulted_without_the_mask_and_not_with_it_and_the_guard_reads_it_both_times`;
  the seated take → `test_a_real_seated_stretch_against_itself_scores_without_its_legs`

## Amendments
- 2026-11-02 (the 1.14.0 round, lane fix114): the mask moves out of `part5/visibility.py` into `part5/mask.py`, byte for byte,
  as the API section above planned; `pipeline.py`, `repwise.py`, `score_report.py`, `output.py`, `cli.py` and `api.py` import
  it from there, and `tests/test_body_mask.py`, `tests/test_body_mask_property.py` and `tests/test_body_mask_surfaces.py`
  follow it. No behaviour changes.

## Deviations from PRD
| PRD item | Deviation | Reason |
|----------|-----------|--------|
| hub: chains from shoulder, elbow, hip or knee | no chain from the knee | Dissent 4 |
| hub: a profile setting | the CLI and the API only | `profiles.json` and `profiles_sha256` stay as shipped (Overview) |
