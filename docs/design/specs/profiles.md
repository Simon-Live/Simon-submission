# Spec: analysis profiles, `--profile {dance,rehab,fitness}` (TICKET-042)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-31
Linked PRD: none (Part 7's request for the operator's dance, rehab and fitness modes)
Linked CRD: none
Request Type: feature-mod
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADRs: ADR-0016 (this feature), ADR-0003 (held-out calibration and gate),
ADR-0007 (the score stays outside the detection hash), ADR-0013 (score windows), ADR-0014 (cues and tempo),
ADR-0015 (foot measures). Ticket: TICKET-042. Ruling: STATUS.md Decisions, 2026-10-31T17:05Z (stakeholder-proxy,
accepted, Part 7 told yes). Companion specs: `check-5.md`, `calibration.md`, `staging.md`,
`integration-contract.md`, `foot-keypoints.md`.

## Overview
Part 7 offers three modes, dance, rehab and fitness. Part 5 owns the analysis, so the mode selects a **profile**:
`part5 analyse --profile {dance,rehab,fitness}` and the same `profile` field on `POST api/analyse`, always echoed as
`analysis.profile`. A profile does four things and nothing else: it multiplies detection thresholds by a factor of at
least 1, relaxes how long a deviation must last, swaps one tempo cue, and (dance only) charges the score for tempo.
`fitness` is the identity and the default: all multipliers 1, nothing overridden, output unchanged. `dance` and `rehab`
only loosen, so they never report a fault `fitness` does not. The profiles live in their own file,
`part5/profiles.json`, read by `part5/profiles.py`; `part5/rules.json`, `rules_sha256` and `detection_sha256` never
change, and `make check-5` runs `fitness` only. The numbers in the file are **set by hand**: nothing was tuned on any
seed, and the per-profile precision and recall on seed 5 are reported, never gated, never run on a held-out seed.

**Sequencing.** Drafted on new files now; implementation (phase 2) starts from main with TICKET-040 merged (the foot
measures `foot_rotation` and `ankle_inversion` in `rules.json` and `cues.py`, schema `1.6.0`), so profiles cover them and
the new schema is `1.7.0`. Nothing merges before TICKET-040's seed 37 is scored once, and it merges before the final
consolidated review. If it is not merged with its checks by the final gate, it stays open and the run ends DEGRADED
naming it; it is never abandoned and never published half-wired (the `--help` rule below).

## Why This Is Wrong (Dissent-First)
1. **The values are guesses.** No labelled dancer or patient take exists; the multipliers are round numbers a person
   chose. Answer: ADR-0016 and this spec say so; they are never presented as calibrated; the per-profile seed 5 report
   shows what they do to the synthetic faults, as measured, with no target; changing a value after that report needs an
   ADR-0016 amendment (the report must not become a tuning loop).
2. **Multipliers on thresholds do not by themselves make a profile loosen-only.** `explained_by` drops a fault when a
   kept fault in another measure explains it. If a profile loosens the cause (a position measure) but not the effect
   (a range measure), the cause stops being reported, the effect is no longer explained, and the profile reports a fault
   `fitness` does not (a knee caving in by 11 degrees with a knee flexion difference of 10 degrees on the same side:
   `fitness` reports the caving knee and drops "Straighten your knee more" as explained; `rehab` at 1.5 times tolerates the
   11 degrees and would then say "Straighten your knee more"). Answer: explanation is judged
   at the `fitness` thresholds and only then are the surviving faults re-tested against the profile's looser
   thresholds (Detection below, AC-PROF-04); loosen-only holds by construction and a test proves it, rather than
   holding on seed 5 by luck.
3. **Loosen-only means no profile can be stricter.** An athlete may want tighter tolerances. Answer: refused here on
   purpose. A stricter profile can raise false faults on correct takes, which is exactly what the gate (ADR-0003)
   guards on a held-out seed, and the ruling keeps profiles off every held-out seed (seed 37 is also the last one left,
   reserved for TICKET-040). Loosen-only is what lets the gate's "0 faults on correct takes" transfer to `dance` and
   `rehab` without a held-out measurement of their own (ADR-0016).
4. **Scores are not comparable across profiles.** A dance 84 and a fitness 84 mean different things. Answer:
   `analysis.profile` is always echoed; `docs/schemas.md` and `CONTRACT.md` say a score is read within its profile; the
   dance and rehab scores are not calibrated against the score targets (the frozen `score` params are untouched, and
   the dance tempo charge is a run-time addition).
5. **`rehab` says "Slower is fine" about a tempo that may be unsafe.** A patient who is far slower may need a nudge.
   Answer: only the "speed up" cue is replaced; "Slow down to match the trainer" (a follower faster than the example)
   stays in every profile, which is the direction that matters for safety.

## User Story
As Part 7, I want to pass the operator's mode to Part 5 and get the same `analysis.json` shape back with the mode
named, so that a dancer, a patient and a gym-goer are each judged against tolerances that suit them.
As a follower, I want a patient's slower pace to be called fine and a dancer's looser posture not to be nagged, without
anyone hiding a real range-of-motion miss.

### Jobs-to-be-Done
- Functional job: pick a tolerance set per user type with one flag or one field.
- Emotional job: a rehab user is not told off for pace; a dancer is not marked down for style.
- Social job: the team can say the profiles are hand-set, loosen-only and provably never noisier than `fitness`.

## Vocabulary
- **Profile**: a named entry in `part5/profiles.json`: tolerances per cue kind (optionally per measure) and a tempo block.
- **Cue kind**: `range` or `position`, the `cue_kind` already given to each measure by `part5/cues.py` (`CUES`). Range
  measures say how far a joint bends or a limb lifts (`elbow_flexion`, `knee_flexion`, `upper_arm_out`,
  `upper_arm_forward`, `thigh_forward`); position measures say where a body part sits (`forearm_out`, `thigh_out`,
  `foot_out`, `knee_valgus`, `trunk_lean_forward`, `trunk_lean_side`, `shoulder_tilt`, `head_forward`, and, once
  TICKET-040 is merged, `foot_rotation` and `ankle_inversion`). A profile never keeps its own list of measures: a new
  measure gets its kind from the cue table, so the two foot measures are covered the moment they have a cue.
- **Effective rules**: `rules.json` after a profile is applied: a new dict, the input untouched.
- **Baseline**: the unrelaxed per-measure detection config (`fitness`) a non-fitness profile relaxes.

## The profiles file (`part5/profiles.json`)
One JSON object, read by `part5.profiles.load()`, validated on every read. Not part of `rules.json`, not covered by
`rules_sha256` or `detection_sha256`; `make check-5` prints its `sha256` as information (`profiles_sha256`).
```json
{
  "_comment": "Set by hand; not tuned on any seed (docs/design/specs/profiles.md, ADR-0016). Every number only loosens.",
  "version": "simon.profiles.v1",
  "default": "fitness",
  "profiles": {
    "dance": {
      "kinds": {
        "range":    {"threshold_multiplier": 1.0,  "min_fraction_multiplier": 1.0,  "min_run_frames_add": 0},
        "position": {"threshold_multiplier": 1.25, "min_fraction_multiplier": 1.15, "min_run_frames_add": 2}
      },
      "measures": {},
      "tempo": {"cues": {}, "weight": 40.0, "cap": 20.0}
    },
    "rehab": {
      "kinds": {
        "range":    {"threshold_multiplier": 1.0, "min_fraction_multiplier": 1.0, "min_run_frames_add": 0},
        "position": {"threshold_multiplier": 1.5, "min_fraction_multiplier": 1.0, "min_run_frames_add": 0}
      },
      "measures": {},
      "tempo": {"cues": {"speed_up": "Slower is fine"}, "weight": 0.0, "cap": 0.0}
    },
    "fitness": {
      "kinds": {
        "range":    {"threshold_multiplier": 1.0, "min_fraction_multiplier": 1.0, "min_run_frames_add": 0},
        "position": {"threshold_multiplier": 1.0, "min_fraction_multiplier": 1.0, "min_run_frames_add": 0}
      },
      "measures": {},
      "tempo": {"cues": {}, "weight": 0.0, "cap": 0.0}
    }
  }
}
```
| Key | Meaning | Rule |
|---|---|---|
| `version` | `simon.profiles.v1` | exact |
| `default` | the profile used when none is named | must be a key of `profiles`; `fitness` |
| `profiles` | name to profile; the file order is the order shown in `--help` and `api/samples`, and a page shows the name with a capital | names are lower case words (`^[a-z][a-z0-9_]*$`); `fitness` must exist |
| `kinds.<kind>` | the tolerance for every measure of that cue kind | both `range` and `position` present |
| `measures.<name>` | a tolerance for one measure; it replaces the kind's tolerance for that measure, key by key | name must be a key of `cues.CUES`; may be empty; no shipped profile uses it |
| `threshold_multiplier` | effective `threshold_deg` is the measure's `rules.json` threshold times this, rounded to 6 places | number, at least 1 |
| `min_fraction_multiplier` | effective `min_fraction` (and `min_frames`, if a rules entry has one, rounded up) is the rules value times this | number, at least 1; `apply` refuses a product over 1 |
| `min_run_frames_add` | effective `min_run_frames` is the rules value (default 4) plus this | integer, at least 0 |
| `tempo.cues` | tempo cues replaced in this profile | keys only `speed_up` and `slow_down`; each value at most 6 words (`cues.MAX_WORDS`), capitalised, no dash |
| `tempo.weight` | dance: score points charged per 1.0 of tempo ratio outside the 0.85 to 1.15 band | number, at least 0; 0 charges nothing |
| `tempo.cap` | the most points tempo can cost one window | number, at least 0 |

**Shipped values, by hand, and why they are these numbers.**
- `fitness`: the identity (below).
- `rehab`: position measures at 1.5 times their threshold; range measures at 1; persistence unchanged; the "speed up"
  cue becomes "Slower is fine". The ticket asks for wider position tolerances, range-of-motion faults kept, and a pace
  that is not pushed. 1.5 is a round number (a patient is allowed half as much again).
- `dance`: position measures at 1.25 times their threshold, a position deviation must last 15% longer (`min_fraction`
  times 1.15) and at least 2 frames more per run; range measures unchanged; tempo costs 40 points per 1.0 of ratio
  outside the cue band, at most 20 per window. The dancer's posture is style, the lift and the bend are choreography,
  and a take far off the music's pace should cost a visible share of the grade (a ratio of 1.40 costs 10 points).
- Effective thresholds are computed, never typed. On `rules.json` as it stands before TICKET-040: position thresholds
  `forearm_out` 17, `thigh_out` 13, `foot_out` 6, `knee_valgus` 9, `trunk_lean_forward` 9, `trunk_lean_side` 9,
  `shoulder_tilt` 9, `head_forward` 18 become 25.5, 19.5, 9, 13.5, 13.5, 13.5, 13.5, 27 under `rehab` and 21.25, 16.25,
  7.5, 11.25, 11.25, 11.25, 11.25, 22.5 under `dance`; the range thresholds `elbow_flexion` 20, `knee_flexion` 9,
  `upper_arm_out` 10, `upper_arm_forward` 15, `thigh_forward` 15 do not move. The foot measures take the position
  multiplier from the cue table without an entry of their own.
- Expectation, not a target: on seed 5 `rehab` and `dance` lose recall on the position fault types (`foot_out`,
  `knee_caving`, and some of `trunk_lean`) and none on the range types (`arms_wider`, `elbow_bent`, `knees_shallow`).
  The numbers are recorded as measured (docs/thresholds.md "Profiles").

## Applying a profile
`part5.profiles.apply(rules, name=None)` returns the **effective rules**.
- `name` of `None` or `fitness`: returns `rules` itself, the same object. Nothing else runs, so the `fitness` code path is
  exactly today's.
- Otherwise a new dict: for every measure in `cues.CUES`, `measures[g]` is the full config
  `{**rules["default"], **rules["measures"].get(g, {})}` with `threshold_deg`, `min_fraction` (and `min_frames`) and
  `min_run_frames` relaxed by the measure's tolerance (the kind's, overridden key by key by `profile.measures[g]`).
  `default`, `guard`, `explained_by`, `explained_by_opposite`, `smooth_frames`, `tolerance_frames`, `min_overlap`,
  `min_frames_floor` and `score` are copied unchanged. A new key `profile` holds
  `{"name", "baseline", "tempo"}`: `baseline[g]` is the unrelaxed full config of each measure (what `fitness` uses),
  `tempo` is the profile's tempo block.
- A measure that is in `rules["measures"]` and not in `cues.CUES`, or the other way round, is a `ProfileError` (every
  generic measure has a cue; `tests/test_cues.py`).
- The pipeline calls it once per analysis: `run(..., profile=None)` does
  `rules = profiles.apply(rules or load_rules(), profile)` before anything reads `rules`, and keeps `rules` and the
  profile name on `PipelineResult` so the score hook reads the same effective rules. `repwise.compare` receives the
  effective rules and passes them to `detect`, so rep mode is covered.

### Detection (the loosen-only construction)
`detect.detect` is unchanged when `rules` has no `profile` key (the `fitness` path). With one, for each measure and
direction it builds the fault twice, with the baseline config and with the effective config, then:
1. the baseline faults go through `_drop_explained` exactly as today (explanation is judged at the `fitness`
   thresholds, so an explained fault stays explained in every profile);
2. each surviving baseline fault is replaced by its effective counterpart (same measure, side, direction), and dropped
   if the effective config finds none (the deviation no longer clears the looser threshold or lasts long enough);
3. `_merge_sides` merges what is left, as today.
Why it is loosen-only: effective thresholds are at least the baseline's, so the frames flagged under the profile are a
subset of those flagged at baseline. Every run counted under the profile (at least the longer minimum run) lies inside a
flagged baseline run that is long enough to count there, and the profile's counted total, which must reach a minimum at
least as large as the baseline's, is at most the baseline's counted total. So whenever the profile finds a fault for a
measure, side and direction, the baseline finds it too, and step 1 only ever removes from the baseline set. The reported
fault carries the profile's numbers: `threshold_deg` is the effective threshold, `magnitude_deg`, `runs` and
`confidence` come from the effective config.
The smoothing, the alignment, the movement guard, visibility and the cue vocabulary are not touched by any profile.

### The identity rule for fitness
`fitness` has every multiplier 1.0, every `min_run_frames_add` 0, no `measures` entry, no tempo cue override and a tempo
`weight` of 0. Consequences, all tested (AC-PROF-02): `apply(rules, "fitness") is rules`; `--profile fitness` and no
flag give byte-identical files (both carry `"profile": "fitness"`); and for every take of seed 5 the `fitness` analysis,
without `profile` and `schema_version`, hashes to the value recorded before any wiring edit
(`fixtures/profiles-fitness-baseline.json`, written once by `python -m part5.profiles_report --write-baseline` at the
first phase 2 commit). The only difference from a pre-feature document is the `profile` field and the schema version.

### The loosen-only invariant
**Definition.** A fault `p` of a profile is *covered* by the `fitness` analysis of the same take when, for every side `s`
in `sides(p.side)`, some `fitness` fault `f` has the same `measure` and `direction` and `s` in `sides(f.side)`;
`sides("both")` is `{left, right}` and `sides(x)` is `{x}` otherwise. (A fault that `fitness` reports on both sides may be
reported on one side by a profile.) **Invariant:** every fault a profile reports is covered. A test proves it for
`dance` and `rehab` on all 108 takes of seed 5 and on the Part 3 kit takes, which are reported material and not held-out
(AC-PROF-05); a construction test proves it where seed 5 would not show it (AC-PROF-04).
**Scope.** The invariant is about faults. It does not cover the score: a profile's thresholds change `r` and the
similarity term (so the score can only be compared within a profile), and the dance tempo charge deliberately lowers
the score. It does not cover tempo cues (the swapped cue is a different text for the same event). In rep mode the
per-rep faults are covered by construction; the take-level rule ("found in at least half of the accepted reps") is the
`fitness` rule applied to each profile's per-rep faults and is left alone, because changing it would move `fitness`.
A contrived split (a fault seen on both sides in some reps and on one side in others) could pass the half rule under a
profile and not under `fitness`; the seed 5 and kit tests do not show it and no test claims otherwise.
**What it buys.** On any correct take where `fitness` reports 0 faults, every profile reports 0, so the gate's "0 faults
on correct takes" holds for `dance` and `rehab` without a held-out run of their own (ADR-0016). Recall is not guaranteed.

## Tempo
Tempo is the follower's time over the example's for the same stretch (`cues.tempo_block`, ADR-0014): below 0.85 the
follower is faster and the cue is "Slow down to match the trainer" (`slow_down`); above 1.15 it is slower and the cue is
"Speed up to match the trainer" (`speed_up`).
- **Cue substitution.** `cues.tempo_cue(ratio, overrides=None)` and `tempo_block(ratio, overrides=None)` take the
  profile's `tempo.cues`. `rehab` replaces `speed_up` with "Slower is fine", in every window's `tempo.cue`, in
  `score.tempo.cue` and in the tempo item of `insights` (which reads `score.tempo`). The `ratio` is untouched. The
  wording is confirmed by the Writer skill before this spec is marked Implemented.
- **Dance weight, at run time.** The frozen score params (`rules.json` `score`, `params_sha256`, ADR-0007) are not
  touched and not read differently. When the profile's `tempo.weight` is above 0, each compared window is charged
  `T = min(cap, weight * max(0, 0.85 - ratio, ratio - 1.15))` points (0 when the ratio is unmeasured); the window's
  unrounded value becomes `clamp(100 - F - S - T, 0, 100)`, its grade comes from the frozen bands, its
  `components.tempo` is `T` rounded to 2 places, and the take's value and `components.tempo` are means over the compared
  windows as `faults` and `similarity` already are (ADR-0013), so the components still add up to the value. A profile
  with weight 0 writes no `components.tempo` key at all. `score.cap_by_warnings` and `zero_block` are unchanged (a zero
  block has no tempo component).
- **Insight points.** The tempo item in `insights` carries `points` equal to the take's `components.tempo` when the
  profile charges tempo, and null otherwise (null as in ADR-0014).

| Ratio | Cue (fitness, dance) | Cue (rehab) | Dance charge (weight 40, cap 20) |
|---|---|---|---|
| 0.60 | Slow down to match the trainer | Slow down to match the trainer | 10.0 |
| 0.85 to 1.15 | none | none | 0 |
| 1.25 | Speed up to match the trainer | Slower is fine | 4.0 |
| 1.40 | Speed up to match the trainer | Slower is fine | 10.0 |
| 2.00 | Speed up to match the trainer | Slower is fine | 20.0 (capped from 34.0) |
| unmeasured | none | none | 0 |

## Output and schema (1.7.0)
- `analysis.profile`: a string, the name of the profile that produced the document; **always present** in every new
  document. `schema_version` is `1.7.0` on every new document (the 1.5.0 and 1.6.0 precedent: a writer has one version;
  `profile` being always present is why). Placed after `schema_version`.
- `contracts/analysis.schema.json` (version `1.7.0`): `profile` is `{"type": "string", "minLength": 1}`, not in
  `required`, so documents of 1.0 to 1.6.0 still validate. There is no enum in the schema: the set of profiles is data
  in `profiles.json`, and a profile added later is not a schema change. `output.validate_analysis` requires `profile`
  to be a non-empty string when `schema_version` is `1.7.0` or later and accepts its absence before that; a document
  without `profile` is read as `fitness`.
- `part5 doctor --for part7` notes `profile <name>: scores compare within one profile` for a document that has one, and
  `no profile (written before 1.7.0): read it as fitness` for one that does not; a 1.7.0 document without a valid
  `profile` is rejected by `validate_analysis` as it is for any broken field.
- `CONTRACT.md`: the analysis row says `1.7.0` and names `profile` in the optional-field list; the table gains a row
  "Part 5 `analyse --profile`" (option for Part 7, works with an option: pass `--profile` or the API field, probe
  `part5 analyse --help` for `--profile`, omitted means fitness). `docs/schemas.md` gains the `1.7.0` row, the field and
  the sentence "Tempo is not scored, except under the dance profile". `part5 contract` and `api/contract` print the
  updated table (`contract.TABLE_ROWS`).
- Goldens (`fixtures/output/*.example.json`) are regenerated by `make output-examples`; they carry `"profile": "fitness"`.
- `contracts/metrics.schema.json` (version `1.3.0`): an optional top-level `profiles_sha256` (64 hex), beside
  `rules_sha256` and `detection_sha256`.

## Interfaces
**CLI.** `part5 analyse ... [--profile {dance,rehab,fitness}]`; the choices come from `profiles.names()` in file order.
Omitted means `fitness`. An unknown value, including a different case, is argparse's usage error, **exit 2**, nothing
written. The argument is added to the parser in the **last wiring commit**, after the pipeline, output, schema, API,
doctor and contract parts work, so `part5 analyse --help` shows `--profile` only once the whole feature is wired; Part 7
decides from that probe (AC-PROF-11). The API field and the `api/samples` lists are switched on in that same commit, so
no surface offers a profile before the pipeline echoes it.
**API.** `POST api/analyse` takes an optional `profile` (string). Omitted or `null` means `fitness`. Any other value
that is not a name in the file (wrong case, empty, not text) is **HTTP 400** with `{error: {field: "profile",
message: "profile: must be one of ['dance', 'rehab', 'fitness']"}}`, before any file is parsed or analysis started.
`GET api/samples` gains `profiles` (the names in file order) and `profile_default` (`fitness`), additive, so a page can
build a select; the response of `api/analyse` is unchanged apart from `analysis.profile`.
**Module** `part5.profiles` (no import of another Part; imports `json`, `hashlib`, `pathlib`, `part5.cues` and the
constant `part5.detect.DEFAULT_MIN_RUN_FRAMES`; `detect` reads `rules["profile"]` and never imports `profiles`, so
`pipeline` and `output` can import it without a cycle):
- `ProfileError(ValueError)`; `PROFILES_PATH`.
- `load(path=PROFILES_PATH) -> dict`: the validated document; `ProfileError` names the file and the field.
- `names(doc=None) -> list[str]`, `default(doc=None) -> str`, `require(name, doc=None) -> str` (the name, or a
  `ProfileError` whose message is the `profile: must be one of [...]` sentence the API returns).
- `kind_of(measure) -> "range" | "position"`: from `cues.CUES`; `ProfileError` for a measure it lacks.
- `apply(rules, name=None, doc=None) -> dict`: above.
- `tempo_of(rules) -> {"cues", "weight", "cap"}`: from `rules["profile"]["tempo"]`, or, when the rules have no
  `profile` key, the identity block `{"cues": {}, "weight": 0.0, "cap": 0.0}`.
- `file_sha256(path=PROFILES_PATH) -> str`: sha256 of the file's bytes.

**Module** `part5.profiles_report` (imports the pipeline; nothing imports it): `python -m part5.profiles_report
[--set DIR] [--json-out PATH]` prints the seed 5 report; `--write-baseline` writes the fitness baseline.
**Other modules (wiring, phase 2).** `pipeline.run(..., profile=None)`, `PipelineResult.rules` and `.profile`;
`output.build_analysis(..., profile)`; `cues.tempo_cue/tempo_block(ratio, overrides=None)`;
`score.tempo_points(ratio, weight, cap)`, `window_score(..., tempo_points=0.0)`, and the timeline builders read the
profile's tempo block from the rules they are given; `score_report.score_block(result, rules=None)` falls back to
`result.rules`; `insights._tempo_insight` reads `score.components.tempo`.

## Per-profile report on seed 5 (`make report-profiles`)
`python -m part5.profiles_report` analyses the seed 5 tuning set (`fixtures/input/followers`) under each profile and
prints, per profile and per slice, the precision, recall and faults on correct takes (`evaluate.evaluate_corpus`, the
same match rule as `check-5`), the grade distribution, the number of profile faults and the number not covered by
`fitness` (must be 0), and a timing line (seconds per take). It exits 0 when it ran, whatever the numbers, and has no
target, no pass or fail, no gate. It
exits 2 when the set is missing or unreadable or when `labels.json` names a seed other than 5 ("the profile report runs
on the tuning set only, never on a held-out seed"). It is not called by `make check-5` or by `make test` beyond the
small cases of AC-PROF-14. The numbers are recorded once, as measured, in `docs/thresholds.md` under "Profiles", with
the sentence that the values are set by hand.

## Acceptance Criteria
Each AC has a unique ID; each test below is in `tests/test_profiles.py` unless a file is named.

### AC-PROF-01: the file and the loader
Given `part5/profiles.json` as shipped
When `profiles.load()` reads it
Then it returns dance, rehab and fitness in that order, `default` is `fitness`, every key and number is valid, and a
file with any of these raises `ProfileError` naming the field: no `fitness`, `default` not a profile, a missing kind, a
multiplier below 1, `min_run_frames_add` negative or not an integer, `min_fraction_multiplier` below 1, a tempo cue key
other than `speed_up` and `slow_down`, a tempo cue over 6 words, with a dash or empty, a negative `weight` or `cap`, a
`measures` key that is not in `cues.CUES`, a profile name that is not lower case words. Nothing in the file can make a
profile stricter than `fitness`. Tests: `test_shipped_file_is_valid`, `test_loader_rejects` (parametrized over each
case), `test_apply_rejects_a_min_fraction_past_one`.

### AC-PROF-02: fitness is the identity
Given the `fitness` profile
When it is applied, or named on the CLI or the API, or left out
Then `profiles.json` has every multiplier 1.0, every add 0, no `measures` entry, no tempo cue and a weight of 0;
`apply(rules, "fitness")` and `apply(rules, None)` return `rules` itself; the CLI writes byte-identical files with
`--profile fitness` and with no flag; the API answers the same `analysis` for `profile: "fitness"`, `null` and omitted;
and for each of the 108 takes of seed 5 the `fitness` analysis minus `profile` and `schema_version` hashes to the value
in `fixtures/profiles-fitness-baseline.json`. Tests: `test_fitness_entry_is_all_ones`,
`test_apply_fitness_returns_the_rules_unchanged`, `test_fitness_matches_the_prefeature_baseline`;
`tests/test_profiles_wiring.py`: `test_cli_fitness_equals_no_flag`, `test_api_fitness_equals_omitted`.

### AC-PROF-03: effective rules
Given the shipped profiles and `rules.json`
When a profile is applied
Then for every measure of `rules.json` (so `foot_rotation` and `ankle_inversion` too, once TICKET-040 has added them)
the effective `threshold_deg` is the rules threshold times the kind's
multiplier, `min_fraction` is multiplied, `min_run_frames` has the add; range measures are unchanged under `dance` and
`rehab`; a `measures` entry overrides its kind key by key (proved on a custom profile file); the input rules are not
mutated; `default`, `guard`, `explained_by*`, `score` and the smoothing keys are equal to the input's; every measure in
`cues.CUES` and every key of `rules["measures"]` has a kind. A deviation held for fewer frames than the relaxed run
length is reported by `fitness` and not by `dance`. Tests: `test_thresholds_scale_by_kind`,
`test_every_measure_has_a_kind` (includes the two foot measures once they exist),
`test_measure_override_beats_kind`, `test_apply_does_not_mutate_or_touch_score`, `test_persistence_relaxation`.

### AC-PROF-04: an explained fault stays explained
Given synthetic differences where a position cause clears its `fitness` threshold but not its `rehab` threshold, and its
range effect clears its own threshold in both
When `detect.detect` runs under `fitness` and under `rehab`
Then `fitness` reports the cause and not the effect, and `rehab` reports neither: the cause is under its looser threshold
and the effect stays explained. Six cases, the six pairs of `rules.json` whose cause is a position measure:
`foot_out` explaining `thigh_out`; `knee_valgus` explaining `knee_flexion` (same direction) and `thigh_out`
(`explained_by_opposite`); `trunk_lean_forward` explaining `thigh_forward`, `upper_arm_forward` and `head_forward`.
Where the effect is also a position measure it is loosened too, and the case puts it over its own looser threshold.
The seventh pair (`upper_arm_out` explaining `forearm_out`) has a range cause that no profile loosens, so the trap does
not arise; AC-PROF-05 covers it on real data. Tests:
`test_explained_fault_stays_explained_when_its_cause_is_tolerated` (parametrized), `test_naive_multipliers_would_fail`
(the same cases run on `rules` with the thresholds multiplied and no `profile.baseline` do report the effect, so the
construction is what holds the invariant and the test would notice if it were dropped).

### AC-PROF-05: dance and rehab never report a fault fitness does not
Given all 108 takes of seed 5 and the Part 3 kit takes (`fixtures/input/contract/part3/followers`)
When each is analysed under `fitness`, `dance` and `rehab`
Then every fault of `dance` and of `rehab` is covered by the take's `fitness` faults (definition above), and a take
with no `fitness` fault has no fault under either profile. The helper handles `both`. Never run on a held-out set.
Tests: `test_dance_and_rehab_never_report_a_fault_fitness_does_not` (seed 5 and kit), `test_covered_handles_both_sides`.

### AC-PROF-06: range faults are kept
Given the same takes
When analysed under `rehab` and `dance`
Then the faults of range-kind measures equal `fitness`'s (same measure, side, direction, `magnitude_deg` and
`threshold_deg`), so no range-of-motion fault is lost. Test: `test_range_faults_equal_fitness`.

### AC-PROF-07: rehab says "Slower is fine"
Given a window or take whose tempo ratio is above 1.15
When the profile is `rehab`
Then `tempo.cue`, `score.tempo.cue` and the tempo item of `insights` read "Slower is fine" (3 words, kind `tempo`) and the
ratio is unchanged; a ratio below 0.85 still reads "Slow down to match the trainer"; `fitness` and `dance` still read
"Speed up to match the trainer". Tests: `test_cue_overrides`, `test_rehab_says_slower_is_fine_end_to_end` (a seed 5
take whose ratio exceeds 1.15, found by the test).

### AC-PROF-08: dance weights tempo, the score params stay frozen
Given the `dance` profile and windows with known tempo ratios
When the take is scored
Then each compared window is charged `min(cap, weight * max(0, 0.85 - r, r - 1.15))` (the table above), its value
is `clamp(round_half_up(100 - F - S - T))`, the grade comes from the frozen bands, `components.tempo` is present in the
windows and the take (their means) and `faults + similarity + tempo` equals `100 - value` within rounding; a window with
no measured ratio is charged 0; `rehab` and `fitness` have no `components.tempo` key and score as before;
`score.params_sha256` equals the `fitness` take's and the hash of `rules.json`'s `score` block, and `apply` leaves that
block byte-equal; the tempo insight's `points` equals the take's `components.tempo` for dance and is null otherwise.
Tests: `test_tempo_points_formula`, `test_dance_score_adds_up`, `test_only_dance_has_a_tempo_component`,
`test_score_params_are_untouched_by_a_profile`, `test_tempo_insight_points_for_dance_only`.

### AC-PROF-09: `analysis.profile` is always present; schema 1.7.0
Given any analysis built by `pipeline.run` (the CLI, the API, `make check-5`, `make output-examples`, the real-take report)
When it is read
Then it has `profile` equal to the profile that produced it and `schema_version` `1.7.0` (`output.SCHEMA_VERSION`);
`contracts/analysis.schema.json` accepts documents of 1.0 to 1.6.0 without it and rejects a `profile` that is not a
non-empty string; `validate_analysis` rejects a 1.7.0 document without it; the goldens carry `"profile": "fitness"`.
Tests (`tests/test_profiles_wiring.py`): `test_every_entry_point_writes_profile`, `test_schema_accepts_older_documents`,
`test_validate_requires_profile_from_1_7_0`, `test_schema_rejects_a_bad_profile`; `tests/test_output_examples.py`
(golden rebuild) and `tests/test_schema_compat.py` (version expectations updated); `make check-5-contract` exits 0.

### AC-PROF-10: unknown profile and the API field
Given an unknown profile
When it is given on the CLI
Then the exit code is 2, a usage message names the choices, and nothing is written.
When it is given to `POST api/analyse` (wrong case, empty, a number, a list)
Then the answer is 400 with field `profile` and the message `profile: must be one of ['dance', 'rehab', 'fitness']`,
before any analysis; `null` and omitted mean `fitness`; a valid profile is echoed; `GET api/samples` lists `profiles`
and `profile_default`. Tests (`tests/test_profiles_wiring.py`): `test_cli_unknown_profile_exits_2`,
`test_api_unknown_profile_is_400`, `test_api_profile_defaults_to_fitness`, `test_api_samples_list_profiles`.

### AC-PROF-11: the flag, and `--help` only when wired
Given the finished wiring
When `part5 analyse --expected E --follower F --profile rehab --out O` runs for each profile
Then `O` is valid, `profile` is that name, faults and score follow the profile, and `part5 analyse --help` lists
`--profile {dance,rehab,fitness}`. One test fails if the flag is listed and a run does not echo the profile, or the
other way round, so neither half can ship alone; the flag is added in the last wiring commit.
Tests (`tests/test_profiles_wiring.py`): `test_help_lists_profile`, `test_every_profile_flows_through_cli_and_api`.

### AC-PROF-12: doctor and the contract table
Given a 1.7.0 document and a 1.6.0 one
When `part5 doctor --for part7` reads them
Then the first prints the `profile <name>` note and exits 0, the second prints the "read it as fitness" note and exits
0; `part5 contract` and `api/contract` list the "Part 5 `analyse --profile`" row and the updated analysis row, and
`CONTRACT.md` carries the same rows. Tests: `tests/test_doctor.py`, `tests/test_contract_cli.py` (amended),
`make check-5-contract` exits 0.

### AC-PROF-13: check-5 runs fitness only and does not move
Given the frozen held-out record
When `make check-5` runs after the feature
Then it exits 0, `gate.metrics.slices` and `attempts` equal the committed record in `fixtures/heldout-attempts.json` (seed
31, and seed 37 once TICKET-040 has scored it; the existing `require_unchanged_scores` passes), `rules_sha256` and `detection_sha256` equal their pre-feature values,
`git diff <base> -- part5/rules.json` is empty, and the only addition is `profiles_sha256`, equal to
`profiles.file_sha256()`. Tests (`tests/test_check.py`, amended): `test_check_reports_profiles_sha256`,
`test_check_numbers_unchanged_by_profiles`; delivery commands in the plan below.

### AC-PROF-14: per-profile report on seed 5 only
Given the seed 5 set
When `python -m part5.profiles_report` runs
Then it prints precision, recall, faults on correct takes, the grade distribution and the uncovered-fault count per
profile and slice with no verdict word, and exits 0 whatever the numbers; given a set whose `labels.json` names another
seed (a held-out set) it exits 2 and analyses nothing; `check.py` and `make check-5` never call it. Tests
(`tests/test_profiles_wiring.py`): `test_report_has_no_verdicts_and_exits_0`, `test_report_refuses_a_heldout_set`,
`test_check_5_does_not_run_the_report`. The full seed 5 run is `make report-profiles`.

### AC-PROF-15: the staging page offers the mode
Given the page at `QA_BASE_URL`
When a visitor chooses "Rehab" in the select "Mode" and presses Analyse
Then the request body carries `profile: "rehab"`, the result region names the mode, and the downloaded `analysis.json`
has `profile` `rehab`; with the select untouched the request carries `fitness`; the select lists the names from
`api/samples`. Verification: QA recipe `qa/recipes/compare/analyse-rehab-mode.md` (two witnesses, the API JSON and the
rendered page; negative assertion: an untouched page sends and shows `fitness`), `staging/verify.mjs`
(an API call with `profile: "rehab"`), `tests/test_web_logic.py` for the pure helper that builds the request.

### Rule-Based ACs
- AC-PROF-NFR-01: determinism. Two runs of the same take and profile with the template phrasing write byte-identical
  files. Verification method: test (`test_profiles_are_deterministic`).
- AC-PROF-NFR-02: speed. One analysis under a profile takes under 2 s on a 300-frame take, as the master spec. Measured
  before the feature: about 0.025 s per seed 5 take. Verification method: `make report-profiles` timing line.
- AC-PROF-NFR-03: size and hygiene. No source file over 800 lines; no em dash or en dash in the tree
  (`firm/check-em-dash.sh` exit 0); every cue of every profile is at most 6 words. Verification method: inspection and
  the gate.
- AC-PROF-NFR-04: the profile code imports nothing of another Part and reads only `profiles.json`, `rules.json` and
  `cues.py`. Verification method: inspection (the black-box rule).

## Error Cases
| Condition | Behavior | Message format | AC Reference |
|---|---|---|---|
| Unknown profile on the CLI | argparse usage error, exit 2, nothing written | argparse's `argument --profile: invalid choice: ...`, naming the three choices | AC-PROF-10 |
| Unknown or non-text profile on the API | 400, field `profile` | `profile: must be one of ['dance', 'rehab', 'fitness']` | AC-PROF-10 |
| `profiles.json` invalid | `ProfileError` (a `ValueError`); CLI exit 1 with `part5 analyse: <file>: <field>: ...`, nothing written; API HTTP 500 with the generic message and the trace in the server log, as for a broken `rules.json`; `make check-5` still prints the file's hash (it hashes bytes and parses nothing) | names the file and the field | AC-PROF-01 |
| `profiles.json` missing | as above for the CLI and the API; `make check-5` exits 2 (`check-5: part5/profiles.json not found`), like a missing set | names the file | AC-PROF-13 |
| A rules entry makes `min_fraction` times the multiplier exceed 1 | `ProfileError` from `apply` | `profile <name>: <measure> min_fraction <x> times <m> is over 1` | AC-PROF-01 |
| `--report` on a held-out set | exit 2, nothing analysed | `the profile report runs on the tuning set only (seed 5), not seed N` | AC-PROF-14 |
| `--report` set missing | exit 2 | as `check.py`: `<set> has no labels.json` | AC-PROF-14 |

## Edge Cases
- A profile name in a different case (`Rehab`): unknown, rejected on both surfaces (AC-PROF-10).
- `--profile` with `--live` or any `--phrasing`: independent; the profile never changes `coaching` or `phrasing`.
- A measure with no cue entry: `ProfileError` at `apply`, caught by the cue-table test long before a user sees it (AC-PROF-03).
- A take with a warning (low match, F cap): profile applies as usual; `capped_by` and the 59 cap stay (AC-PROF-08).
- A zero-score take (nothing aligned): no windows, no `components.tempo`, `profile` still echoed (AC-PROF-09).
- Unmeasured tempo (window under 1 s of example time): no cue, no charge, in every profile (AC-PROF-07, 08).
- Rep mode: the effective rules reach each rep's detection; see the invariant's scope for the take-level rule (AC-PROF-05).
- A fault `fitness` reports on `both` sides that a profile keeps on one: allowed, covered (AC-PROF-05).
- TICKET-040 not merged: `rules.json` and `cues.py` lack the foot measures; profiles need no change, the tests that
  name them skip nothing because they iterate over the measures present (AC-PROF-03).

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC Reference |
|----------|------------|--------|-------------|
| Performance | Response time | under 2 s per take on 300 frames; two detections per measure only for non-fitness profiles | AC-PROF-NFR-02 |
| Performance | Throughput | N/A: the API runs one analysis at a time (staging.md) | |
| Security | Authentication, authorization | N/A: unchanged, no new endpoint | |
| Security | Data protection | no secret; the profile name is the only new request value and is matched against a fixed list | AC-PROF-10 |
| Accessibility | WCAG, screen reader | the select has a label, a hint and a focus order like the other selects | AC-PROF-15 |
| Scalability | Data volume | unchanged | |
| Reliability | Error handling | a bad profile fails fast with a named field; `fitness` has no new code path | AC-PROF-01, 02, 10 |
| Maintainability | Code coverage | every AC has a named test; new files are small | AC-PROF-NFR-03 |
| Compatibility | Browsers, devices | as the existing page (desktop 1440 and phone 390) | AC-PROF-15 |
| Compatibility | Consumers | documents before 1.7.0 validate; no profile means fitness | AC-PROF-09 |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT change `part5/rules.json`, `rules_sha256` or `detection_sha256`. Why: the freeze records (ADR-0003, ADR-0007).
- MUST NOT make any profile stricter than `fitness`, in a threshold, a persistence rule or a cue. Why: loosen-only is
  what lets the gate's result transfer (ADR-0016).
- MUST NOT change `fitness` output other than by `profile` and the schema version. Why: check-5 numbers and goldens.
- MUST NOT run, report or tune a profile on a held-out seed, or on seed 5 as a gate. Why: ADR-0003; the ruling.
- MUST NOT change the frozen `score` params or their hash. Why: ADR-0007; the dance charge is a run-time addition.
- MUST NOT advertise `--profile` in `--help` before the pipeline, API, schema and doctor parts work. Why: Part 7 decides
  from that probe; a half-wired flag would mislead it.
- MUST NOT import another Part's code. Why: black box.

## Compromises
### Hand-set values
Short-term: round numbers a person chose, recorded as hand-set. Long-term: values from labelled dance and rehab takes.
Migration path: Part 7 or the operator supplies labelled takes; a new profile version and a new ADR calibrate them on a
tuning set, with a held-out set per the protocol. Trigger to revisit: the first labelled take set, or a user report that a
profile nags or misses.
### Rep-mode take rule left alone
Short-term: the half-of-reps rule is the `fitness` rule on each profile's faults. Long-term: count at side granularity.
Migration path: change `repwise` aggregation with its own held-out check. Trigger: a rep-mode take that shows the split.

## Non-Requirements (Explicitly NOT Building)
- A stricter profile or a user-defined profile, because loosen-only is the design and the profile set is three names.
- Per-profile movement guard limits, because the guard decides whether the pair matches at all, not how picky to be.
- Per-profile phrasing, words or cues other than the one tempo cue, because Part 7 asked for tolerances and pace.
- Calibrating dance or rehab score bands, because the bands are frozen on fitness (ADR-0007).
- A profile select in Part 7 (Part 7's own work); the staging page select is Part 5's demo of the field.

## Assumptions
- Part 7 treats `analysis.profile` as informational and reads scores within one profile. (Told yes on the bus,
  2026-10-31.)
- Every generic measure has a cue entry and therefore a cue kind (`tests/test_cues.py`); if one is added without a cue the
  profile test fails loudly.
- The two foot measures are position measures (ADR-0015, `cue_kind` `position`); if TICKET-040 changes that, the
  profile follows the cue table with no edit to `profiles.json`.

## Implied Requirements Discovered
- The score hook gets only the `PipelineResult`, so it would read the fitness thresholds for a dance take: the result must
  carry the effective rules (found by following `score_block` from `cli.py`).
- The score's similarity term and per-fault ratio read thresholds, so they move with the profile; the spec says scores
  compare within a profile (found by reading `score.threshold_of`).
- `explained_by` makes naive multipliers non-monotone (Why This Is Wrong, 2): found by working the knee valgus case by hand.
- `api/samples` must list the profiles for a page select; `contract.TABLE_ROWS` and `CONTRACT.md` are kept equal by
  `tests/test_contract_cli.py`, so both change together (found by grepping the table).
- A tempo cue override must also reach the insights, which copy the cue from `score.tempo` (found in `insights.py`).

## Files (every new or changed source file; the write gate reads this table)
Phase 1 (this commit) writes only the first three rows. Everything else is phase 2.
| File | Change | Ticket | Published |
|---|---|---|---|
| `docs/design/specs/profiles.md` | this spec | TICKET-042 | yes |
| `docs/design/adr/ADR-0016-analysis-profiles.md` | decision | TICKET-042 | yes |
| `docs/design/specs/profiles.md`, `docs/design/adr/ADR-0016-analysis-profiles.md`, `docs/design/README.md` | neutralised copies written by `make design-copies`, and their two lines in the hand-written index (`tests/test_design_copies.py` fails without them) | TICKET-042 | yes |
| `part5/profiles.json` (new) | the three profiles, hand-set | TICKET-042 | yes |
| `part5/profiles.py` (new) | `load`, `names`, `default`, `require`, `kind_of`, `apply`, `tempo_of`, `file_sha256` | TICKET-042 | yes |
| `part5/profiles_report.py` (new) | the seed 5 report (`make report-profiles`) and `--write-baseline` | TICKET-042 | yes |
| `tests/test_profiles.py` (new) | AC-PROF-01 to 08, NFR-01 | TICKET-042 | yes |
| `tests/test_profiles_wiring.py` (new) | AC-PROF-09 to 11, 13, 14 | TICKET-042 | yes |
| `fixtures/profiles-fitness-baseline.json` (new) | sha256 per seed 5 take of the fitness analysis, written once before any wiring edit | TICKET-042 | yes |
| `part5/detect.py` | baseline/effective detection when `rules["profile"]` is present; the `fitness` path unchanged | TICKET-042 | yes |
| `part5/cues.py` | `tempo_cue` and `tempo_block` take `overrides` | TICKET-042 | yes |
| `part5/score.py` | `tempo_points`, the tempo term in `window_score`, `timeline_block`, `compute_timeline` | TICKET-042 | yes |
| `part5/score_report.py` | `score_block` reads `result.rules`; `_rep_timeline` passes the tempo overrides and charge | TICKET-042 | yes |
| `part5/insights.py` | the tempo item's `points` | TICKET-042 | yes |
| `part5/pipeline.py` | `run(..., profile=None)`, `PipelineResult.rules` and `.profile`, `build_analysis(profile=...)` | TICKET-042 | yes |
| `part5/output.py` | `SCHEMA_VERSION` 1.7.0, `profile` written and validated | TICKET-042 | yes |
| `part5/cli.py` | `--profile`, added in the last wiring commit | TICKET-042 | yes |
| `part5/api.py` | the `profile` request field, 400, `api/samples` `profiles` and `profile_default` | TICKET-042 | yes |
| `part5/doctor.py`, `part5/contract.py` | the profile notes, the table rows | TICKET-042 | yes |
| `part5/check.py` | `profiles_sha256` as information; nothing else | TICKET-042 | yes |
| `contracts/analysis.schema.json`, `contracts/metrics.schema.json` | `profile` (1.7.0), `profiles_sha256` (1.3.0) | TICKET-042 | yes |
| `fixtures/output/analysis.example.json`, `analysis.no-faults.example.json` | goldens regenerated (`profile`, version) | TICKET-042 | yes |
| `scripts/make_output_examples.py` | checked; changed only if it builds the document by a path that skips `profile` | TICKET-042 | yes |
| `Makefile` | `report-profiles` target | TICKET-042 | yes |
| `web/index.html`, `web/app.js`, `web/api.js` | the "Mode" select, the request field, the result line | TICKET-042 | yes |
| `staging/verify.mjs` | an API call with `profile: "rehab"` | TICKET-042 | yes |
| `qa/recipes/compare/analyse-rehab-mode.md` (new) | the QA recipe for AC-PROF-15 | TICKET-042 | yes |
| `docs/schemas.md`, `docs/thresholds.md`, `CONTRACT.md` | the field and the 1.7.0 row; the "Profiles" record; the rows and Part 7 duty | TICKET-042 | yes |
| `docs/design/specs/staging.md`, `docs/design/specs/integration-contract.md`, `docs/design/specs/check-5.md`, `docs/design/specs/calibration.md` | one amendment line each (API field, rows, `profiles_sha256`, profiles are never calibrated) | TICKET-042 | yes |
| `tests/test_cues.py` (tempo overrides and insights), `test_score.py`, `test_score_timeline.py`, `test_detect.py`, `test_output.py`, `test_cli.py`, `test_api.py`, `test_check.py`, `test_doctor.py`, `test_contract_cli.py`, `test_schema_compat.py`, `test_output_examples.py`, `test_web_logic.py`, and the version expectations in the other tests | amended and added cases (schema version `1.7.0`, the new field) | TICKET-042 | yes |

## Delivery Verification Plan
- Phase 1 (this commit): `python3 scripts/make_design_copies.py --check` exits 0; `uv run pytest -q
  tests/test_design_copies.py` passes; `firm/check-em-dash.sh` on the tree exits 0. No code is touched.
- Phase 2, in order: write `fixtures/profiles-fitness-baseline.json` first, from the pre-wiring tree; then the module,
  hooks and wiring, with `--profile` last; then `uv run pytest -q tests/test_profiles.py tests/test_profiles_wiring.py`.
- Merge gate: `make test` 0; `make check-5` 0 with `gate.metrics.slices` and `attempts` equal to the committed record,
  `rules_sha256` and `detection_sha256` unchanged, `git diff <base> -- part5/rules.json` empty; `make check-5-contract` 0;
  `make output-examples` then `git diff --stat fixtures/output` shows only `profile` and the version;
  `make report-profiles` run once, numbers recorded in `docs/thresholds.md` "Profiles" (not gated);
  `python3 scripts/make_design_copies.py --check` 0; the em-dash gate 0.
- Delivery: staging `up` and `verify` 0 from merged code; QA recipe `analyse-rehab-mode`; `/delivery-review` PASS; Part 7
  told the commit on the bus. If any of these is missing at the final gate the ticket stays open and the run ends
  DEGRADED naming it.

### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|----------|------|----------|-------------|
| Desktop Chromium | Playwright (`staging/verify.mjs`, QA recipe) | 1440px | viewer lane |
| Phone width | Playwright | 390px | viewer lane |
| Terminal | `part5 analyse --help` and a run per profile | n/a | integration lane |

### Data (created through the product's own UI with synthetic accounts; never a DB or API seed)
- Synthetic accounts needed: none (no login in this product).
- Data each verification needs: the committed fixtures only; the recipe picks "Squat (exercise)" and a take with a
  position fault through the page's own pickers.
- Empty states acceptable for: the page before Analyse.
- Populated states required for: the result region after Analyse under "Rehab".

### Ratchet Initialization Plan
Not applicable: no new milestone; the existing floors in `progress/ratchets.json` must not drop.

### Boundary Layer Testing Plan
| Mapping Function | Input Format | Output Format | Test File |
|-----------------|-------------|---------------|-----------|
| `profiles.apply` | `rules.json` dict and a profile name | effective rules with `profile.baseline` | `tests/test_profiles.py` |
| `profiles.kind_of` | measure name | `range` or `position` from `cues.CUES` | `tests/test_profiles.py` |
| `api._analyse` profile reading | request JSON `profile` | a name or a 400 | `tests/test_profiles_wiring.py` |

## Dissent Review (MANDATORY, hooks block implementation without this)
Reviewed by: TICKET-042 profiles lane (implementer, self-review, model: sonnet). Independent review: the one
consolidated review before the final gate.
Date: 2026-10-31

### Concern 1: hand-set numbers will be read as calibrated
Challenge: a table of multipliers and a report with precision and recall looks like a calibration.
Impact if right: Part 7 or an operator trusts a dancer's grade as if validated. Mitigation: the file, this spec, ADR-0016
and `docs/thresholds.md` all say "set by hand"; the report prints no verdict; scores compare within a profile.
Resolution: ADDRESSED_IN_SPEC.

### Concern 2: the second detection pass is clever code on the gate's path
Challenge: touching `detect.py` after the freeze could move `fitness`. Impact if right: a changed check-5 number after
seed 37 is spent. Mitigation: the new branch runs only when `rules["profile"]` exists; `fitness` returns the rules
object itself; the baseline hash of all 108 seed 5 takes and the unchanged held-out record prove it; the construction
is covered by its own failing-if-removed test. Resolution: ADDRESSED_IN_SPEC.

### Concern 3: dance tempo charge makes the dance score lower than fitness for the same take
Challenge: "dance only loosens" is contradicted by a charge that lowers the score. Impact if right: a reader sees a dance
grade below the fitness grade and calls it a bug. Mitigation: the invariant is stated for faults only; the score scope is
stated; `components.tempo` shows the charge and the timeline still adds up. Resolution: ACCEPTED_RISK (it is the
operator's request: "weights tempo in the score").

### Pre-Mortem: It's 6 months from now and this feature was a disaster. Why?
1. A later edit to `profiles.json` sets a multiplier below 1 or adds a measure override that is stricter, and a profile
   starts raising false faults. Likelihood: L, Impact: H, Mitigation: the loader refuses numbers below 1; the seed 5
   covered-fault test fails; `profiles_sha256` is printed on every check.
2. `fitness` drifts because the profile wiring touches a shared function. Likelihood: M, Impact: H, Mitigation: the
   baseline-hash test on seed 5 and the unchanged `make check-5` record; `--profile` ships last.
3. Part 7 shows dance and fitness grades side by side as if equal. Likelihood: M, Impact: M, Mitigation: `profile` is in
   every document, the contract row names the duty, `doctor --for part7` prints the note.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|-------------------|---------|------|--------|
| Ticket: own file, `rules.json` and both hashes unchanged, `profiles_sha256` information | AC-PROF-01, AC-PROF-13 | `tests/test_profiles.py`, `tests/test_check.py` | pending |
| Ticket: fitness identity and default, `profile` always present | AC-PROF-02, AC-PROF-09 | `test_fitness_*`, `test_every_entry_point_writes_profile` | pending |
| Ticket: dance and rehab only loosen, a test proves it | AC-PROF-04, AC-PROF-05, AC-PROF-06 | `test_dance_and_rehab_never_report_a_fault_fitness_does_not` | pending |
| Ticket: rehab widens position, keeps range, says "Slower is fine" | AC-PROF-03, 06, 07 | `test_thresholds_scale_by_kind`, `test_cue_overrides` | pending |
| Ticket: dance loosens position and weights tempo at run time, score params frozen | AC-PROF-03, AC-PROF-08 | `test_dance_score_adds_up`, `test_score_params_are_untouched_by_a_profile` | pending |
| Ticket: check-5 fitness only, per-profile seed 5 report, never gated or held-out, values by hand | AC-PROF-13, AC-PROF-14 | `test_report_refuses_a_heldout_set` | pending |
| Ticket: unknown profile exit 2 / 400, next minor schema, goldens, doctor, contract row | AC-PROF-09, 10, 12 | `test_cli_unknown_profile_exits_2`, `test_api_unknown_profile_is_400` | pending |
| Ticket: `--help` shows `--profile` only when wired | AC-PROF-11 | `test_help_lists_profile`, `test_every_profile_flows_through_cli_and_api` | pending |
| Ticket: foot measures covered (TICKET-040) | AC-PROF-03 | `test_every_measure_has_a_kind` | pending |

## Test Scenarios (maps 1:1 to acceptance criteria)
- AC-PROF-01 to AC-PROF-08 and AC-PROF-NFR-01 to `tests/test_profiles.py`, the test names listed in each AC.
- AC-PROF-09 to AC-PROF-11, AC-PROF-13 and AC-PROF-14 to `tests/test_profiles_wiring.py` and the amended tests named in Files.
- AC-PROF-12 to `tests/test_doctor.py`, `tests/test_contract_cli.py` and `make check-5-contract`.
- AC-PROF-13 also to `make check-5`; AC-PROF-14 also to `make report-profiles`; AC-PROF-15 to the QA recipe and
  `staging/verify.mjs`.

## Deviations from PRD
| PRD item | Deviation | Reason |
|----------|-----------|--------|
| Ticket: multipliers on thresholds only | multipliers also on `min_fraction` and an addition to the run length, per cue kind | the lane brief asks for `min_fraction` and run-length relaxations; one tolerance shape per kind keeps the file small |
| Ticket: "`analysis.profile` additive in the next minor schema" | every new document is `1.7.0` | `profile` is always present, so one writer has one version, as 1.5.0 and 1.6.0 did |
| ADR-0014 / `docs/schemas.md`: "Tempo is not scored" | scored under the dance profile only | the operator's dance mode asks for it; ADR-0016 amends the line |
