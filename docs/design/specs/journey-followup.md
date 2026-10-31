# Spec: Journey follow-up J1 (timed faults, screen direction, replay contract, score, AI phrasing)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-30
Request Type: feature-mod (additive contract for Part 7)
Risk Level: medium (a live model on the user-facing path; a new gated number)
Requirements source: operator directive of 2026-10-30, build the full Simon app journey: a trainer records a
movement; others view it in the cloud; a viewer records or uploads their own take; the pipeline analyses faults; 3D
simulations to rotate and compare; feedback like "Foot is too far right at 2s"; a score out of 100 with a grade from
A to F. Verbatim: "fault text should be dynamic, using AI to generate a human understandable message". Research
evidence of 2026-10-30 (session scratchpad `journey-b/`: `score/score.py`, `params.json`, `collect.py`, `sweep.py`).
Parent spec: `docs/design/specs/part5-fault-analysis.md`. Companion specs: `check-5.md`, `integration-contract.md`,
`calibration.md`, `staging.md`, `viewer.md`.
ADRs: ADR-0007 (score), ADR-0008 (AI phrasing default in live mode), ADR-0009 (time, direction and replay as an
additive contract). Revised 2026-10-31 for ADR-0012 (always analyse: no refusal, no exit 3, `score` never null, a
warning caps the grade at F), ADR-0013 (the score as a timeline of windows) and ADR-0014 (cues, tempo, insights),
which supersede the refusal wording below where they differ; the schema is now 1.5.0.
Tickets: TICKET-032 (J-1), TICKET-033 (J-2), TICKET-034 (J-3), TICKET-035 (J-4), TICKET-036 (J-5),
TICKET-037 (J-5 review), TICKET-038 (J-6). Milestone: J1.

## Overview
Part 7 shows a viewer what went wrong in their take, when, which way, how well they did overall, and a 3D replay
to rotate. Part 5 already finds each fault and its frames; it does not say when in seconds, which way on the body,
or how good the take was, and its replay payload lives only inside the staging API. This spec adds, all optional for
a reader of schema 1.1.0:
- J-1 time per fault: `follower_t_s`, `at_s`, `follower_runs`, `text_timed`;
- J-2 direction: `lateral` (`left`, `right` or `null`) and timed words that say "too far right", "too far left",
  "arm too low" and "thigh not raised enough"; `lateral_m` on `foot_out`;
- J-3 replay as a file: `part5 analyse --replay <replay.json>` writes `simon.replay.v1`;
- J-4 score: `score` (`simon.score.v1`), a value out of 100 and a grade from A to F;
- J-5 AI phrasing: in live mode, Muse Spark writes one friendly coaching line per fault that includes the time; a
  validator holds it to the measured facts and anything else falls back to the timed template;
- J-6 the contract rows, `contract`, `doctor`, regenerated goldens and the publish.
`analysis.json` goes to schema version 1.2.0. The template stays the default for tests, `check-5` and every
deterministic run.

## Why This Is Wrong (Dissent-First)
1. A single number invites the viewer to chase the number. Answer: the faults stay first in the output; the score is
   one more field, its two components are shown, and a take with a warning gets a score capped at F (ADR-0012),
   never `null`.
2. The score is calibrated on synthetic takes (seed 5), the same generator as its held-out seeds. Answer: stated in
   ADR-0007 and in the `check-5` output; the gate is narrow (correct good-light takes at A, monotonic in fault size)
   and every other target is reported, never tuned on.
3. A language model on the user path can state a wrong fact in friendly words. Answer: the validator accepts only the
   measured body part, side, direction and time, and no other number or body part beyond a short landmark list;
   anything else falls back to the template line with the time (ADR-0008).
4. `lateral` reads like the screen's left and right, which is the mirror of the subject's when the camera faces the
   viewer. Answer: it is the subject's own left and right, like `side`, and `CONTRACT.md` tells Part 7 to mirror it
   only when it draws a mirrored view.
5. The research medians and targets come from one prototype run. Answer: the prototype is reproduced first
   (AC-S01), and the held-out seeds 47 and 53 are generated only after the freeze commit.

## User Story
As a viewer, I want each fault said in plain friendly words with the moment it happened and the way to correct it,
a score with a grade, and a replay I can rotate, so that I know what to change and whether I am improving.
As Part 7, I want all of it in versioned files I can validate.

### Jobs-to-be-Done
- Functional: "your right foot drifts too far to the right at 1.9 s", 82 out of 100, grade B, and a replay.
- Emotional: encouragement that is still true.
- Social: a grade worth sharing because it is consistent.

## API / Interface Contract

### J-1 Time per fault (`faults[]`, all optional in 1.2.0)
| Field | Type | Rule |
|---|---|---|
| `follower_t_s` | `[start_s, end_s]`, numbers | the follower file's own `t` (seconds, as written in the file) at `follower_frames[0]` and `follower_frames[1]`; 3 decimals |
| `at_s` | number | `follower_t_s[0]` rounded half up to 0.1 s |
| `follower_runs` | list of `[start, end]`, integers | one entry per `runs` entry, same order: each expected frame `s` and `e` mapped through the alignment (`exp_to_fol`) and then `to_original` to the follower file's frame index; `follower_runs[k]` for the reported run (the longest; under a profile other than fitness, the one `profiles.md` names) equals `follower_frames`; a fault merged to side `both` reports the span of its two sides' runs, so none of its entries need equal `follower_frames` |
| `text_timed` | string | the timed words line (J-2 vocabulary) plus ` at {at_s:.1f} s`, for example `right foot too far right at 1.9 s` |

`text`, `follower_frames` and every 1.1.0 field keep their meaning and values. A clip whose frames carry no `t`
gets it from `index / fps` (the loader's existing rule), so `follower_t_s` always exists on an `ok` analysis.

### J-2 Direction (`faults[]`, optional in 1.2.0)
`lateral`: `"left"`, `"right"` or `null`, in the subject's own frame (the same frame as `side`). Rule:

| Measure | `direction` | `side` left | `side` right | `side` both or center |
|---|---|---|---|---|
| `foot_out`, `thigh_out`, `upper_arm_out`, `forearm_out` | `more` (out) | `left` | `right` | `null` |
| same | `less` (in) | `right` | `left` | `null` |
| `knee_valgus` | `more` (caving in) | `right` | `left` | `null` |
| `knee_valgus` | `less` (pushed out) | `left` | `right` | `null` |
| `trunk_lean_side` | `more` | n/a | n/a | `left` |
| `trunk_lean_side` | `less` | n/a | n/a | `right` |
| every other measure | either | `null` | `null` | `null` |

Timed words vocabulary (`part5.words.describe_timed`; `text` is unchanged). `{q}` is the existing size qualifier
("slightly ", "", "much "); `{nq}` is the one for "not ... enough" phrases ("not quite", "not", "nowhere near"), where
"slightly" or "much" in front of "not" would read wrong; both-side and centre lines are the existing ones.

| Measure | `direction` | One side, timed words | `lateral` |
|---|---|---|---|
| `foot_out` | `more` | `{side} foot {q}too far {lateral}` | out side |
| `foot_out` | `less` | `{side} foot {q}too far {lateral}` | in side |
| `thigh_out` | `more`, `less` | `{side} knee {q}too far {lateral}` | per table above |
| `upper_arm_out` | `more`, `less` | `{side} arm {q}too far {lateral}` | per table above |
| `forearm_out` | `more`, `less` | `{side} hand {q}too far {lateral}` | per table above |
| `knee_valgus` | `more`, `less` | unchanged (`{side} knee caving in`, `{side} knee pushed out`) | per table above |
| `thigh_forward` | `less` | `{side} thigh {nq} raised enough` (both: `thighs {nq} raised enough`), the same words as `text` ("right thigh not raised enough"); never "too low", which reads as squatting too deep (2026-10-31) | `null` |
| `upper_arm_forward` | `less` | `{side} arm {q}too low` (both: `arms {q}too low`) | `null` |
| every other case | | the existing `text` words | `null` |

`lateral_m` (optional number, metres, 2 decimals): on `foot_out` faults with side `left` or `right` only. The median,
over the counted runs, of `|x_follower| - |x_expected|` of that ankle in the normalised clips (hip-centred, `x` is the
subject's left, metres as given by the inputs), follower frames taken through `exp_to_fol`. Positive means further
out. Absent on every other fault.

### J-3 Replay file (`simon.replay.v1`, `contracts/replay.schema.json`, schema version 1.0.0)
`part5 analyse --expected <file> --follower <file> --out <analysis.json> --replay <replay.json>` writes the payload
`part5.replay.build_replay` already builds for the staging viewer, plus four keys:

| Key | Type | Meaning |
|---|---|---|
| `format` | `"simon.replay.v1"` | new |
| `schema_version` | `"1.0.0"` | new |
| `fps` | number | the expected clip's frame rate (unchanged) |
| `joints` | 17 names | canonical order (unchanged) |
| `bones` | list of `[i, j]` | joint index pairs the viewer draws (unchanged) |
| `expected` | list per expected frame of 17 entries `[x, y, z]` or `null` | normalised expected clip, 4 decimals (unchanged) |
| `follower` | list per follower file frame, same shape | normalised follower clip on its own frames (unchanged) |
| `expected_t` | list of numbers, one per expected frame | new: the expected clip's `t` in seconds |
| `follower_t` | list of numbers, one per follower frame | new: the follower file's own `t` in seconds |
| `exp_to_fol` | list of integers, one per expected frame | follower file frame shown at each expected frame (unchanged) |
| `coordinate_frame` | object | new: Part 5's frame (`origin hip_midpoint`, `x subject_left`, `y world_up`, `z anterior`, metres) |

The staging API's `replay` in `POST api/analyse` gains the same four new keys; the web viewer ignores them. The replay
is written after `analysis.json`, also for a take with warnings (a take that could not be aligned plays on a
straight-line stand-in alignment, ADR-0012); exit 1 writes neither file.
`part5 doctor <replay.json> [--for part7]` names `simon.replay.v1`, validates the schema and checks: the lengths of
`expected`, `expected_t` and `exp_to_fol` agree, `follower` and `follower_t` agree, every `exp_to_fol` index and
every bone index is in range, and both `t` lists strictly increase.

### J-4 Score (`score`, top level, optional in 1.2.0; `simon.score.v1`)
```
"score": {"version": "simon.score.v1", "value": 82, "grade": "B",
          "components": {"faults": 14.62, "similarity": 3.10}, "params_sha256": "<64 hex>"}
```
`score` is never `null` from schema 1.4.0 (ADR-0012): a take nothing could be measured on scores 0, grade F, and a
take with `warnings` is capped at 59 (grade F) with `capped_by` naming the codes; before 1.4.0 a refused take had
`score: null`. The value is (ADR-0007, ADR-0013 for the windows):
- per fault, `r = |magnitude_deg| / threshold_deg`, `penalty = min(cap, base + slope * (r - 1))`,
  `dur = (sum over runs of end - start + 1) / N` with N the expected clip's frame count,
  `F = sum of penalty * (0.5 + 0.5 * dur) * coverage`;
- similarity, over every measure in `part5.measures.MEASURES` aligned through `exp_to_fol` (resampled follower):
  `z = |follower - expected| / threshold` (the measure's `threshold_deg`, else the default), clipped to [0, 2],
  `mean_z` the mean over finite values, `S = s_max * clip((mean_z - z0) / (z1 - z0), 0, 1)`;
- `value = clamp(round_half_up(100 - F - S), 0, 100)`, an integer;
- `grade`: A 90 and above, B 80 to 89, C 70 to 79, D 60 to 69, F below 60;
- `components.faults` = F and `components.similarity` = S, each rounded to 2 decimals;
- `params_sha256` = sha256 of the `score` block of `part5/rules.json` serialised as
  `json.dumps(block, sort_keys=True, separators=(",", ":"))`.

Params in `part5/rules.json` under `"score"`: `{"version", "z0", "z1", "s_max", "base", "slope", "cap", "bands",
"calibrated_on"}`, calibrated by `python -m part5.calibrate --score --set fixtures/input/followers` on seed 5 only.
The research prototype gave `z0 0.289`, `z1 0.732`, `s_max 4.0`, `base 16`, `slope 5.9`, `cap 31.1`.

### J-5 Phrasing (`phrasing`, `faults[].coaching`)
Live mode is on when any of: `part5 analyse --live`, `part5 serve --live`, `SIMON5_LIVE=1`, `META_LIVE=1`. In live
mode the default backend is `muse-spark`; elsewhere it stays `template`. An explicit `--phrasing` (or the API's
`phrasing`) always wins. `make check-5`, `make check-5-contract`, `make output-examples` and every test force
`template` whatever the environment.

Muse Spark through Baseten as today (`part5/phrasing/muse_spark.py`): model `meta-models/muse-spark-open-1026`, key
file, `max_tokens` 2048 (at least 512), timeout 10 s per call, stdlib
`urllib`, usage ledger `~/.simon/baseten_usage.jsonl`. Live calls need the key file and live mode (the live switch
replaces "`META_LIVE=1` only"). The request carries: measure, body part, joint, side, direction, `lateral`,
magnitude, threshold, `at_s` formatted to 0.1 s, and `text_timed`; the instruction asks for one calm, friendly
coaching sentence in plain words that includes the time and carries no praise (AC-P09), as in "Your right foot drifts
too far to the right at 1.9 s; keep it under your hip".

Validator (`part5.phrasing.template.line_problem(fault, line, timed=True)`), all must hold:
- one line, at most 160 characters;
- the time appears exactly once, as `{at_s:.1f}` followed by ` s`, `s` or ` seconds`; no other digit or number word;
- the side word before the body part equals `side` (both and centre as today); any other `left` or `right` is a
  direction word and must equal `lateral`;
- the body part is one the measure allows (today's `NAMES`), plus only these landmarks: `foot_out`: hip, shoulder;
  `knee_valgus`: foot, hip; `thigh_out`: foot; `upper_arm_out`: trunk; `forearm_out`: elbow; no other body part;
- the direction's meaning: today's rules, plus `(too far |to the |toward the )<lateral>` counting as the fault's
  direction when `lateral` is set, and the other side's word counting as the wrong direction;
- no praise (AC-P09, 2026-10-31): none of `PRAISE_PHRASES` ("nice effort", "great job", "well done", "good job", "nice
  work" and the rest of the list), word-bounded and in any case, the words joined by spaces or hyphens, zero-width
  characters ignored; the reason is `adds praise`. The untimed test holds a line to the same check.

Per fault, a failed check, a timeout, an HTTP error, empty content, the rate limit or the time budget falls back to
`text_timed`. `coaching` is then `text_timed`; the `template` backend also writes `coaching = text_timed` in 1.2.0.
Per-fault record: `phrasing.faults[k] = {backend, model, fallback_reason}` (`model` added; `null` for template).
`phrasing.selected_by`: `"flag"`, `"live"` or `"default"` (added). Limits: the server keeps its per-client limit (6
requests a minute) and adds a process-wide limit of 30 model calls a minute (`PART5_MUSE_PER_MINUTE`); one analysis
spends at most 20 s on phrasing (`PART5_PHRASING_BUDGET_S`; a call starts only while the time spent so far
plus the 10 s timeout fits in it); faults past either limit fall back with reason
`rate limited` or `time budget spent`.

### J-6 Contract
- `contracts/analysis.schema.json` version `1.2.0` at J1, `1.5.0` now (all new fields optional; a 1.1.0 and a 1.0
  document still validate); `contracts/replay.schema.json` `1.0.0`; `contracts/metrics.schema.json` `1.1.0` (the
  score report `check-5` writes: `gate.sweep`, `report.score` and `detection_sha256`, additive).
- `CONTRACT.md` generated compatibility rows (from `part5/contract.py`) for Part 7: `analysis.json` 1.2.0 fields
  (works; since ADR-0012 `status.code` is always `ok` and `score` is never null, so Part 7 reads `warnings` and
  `score`), `replay.json` `simon.replay.v1` (works), `part5 analyse --live` (works with an option; needs the key file
  on the host). The schema table lists `replay`.
- `part5 contract` prints the new schema and rows; `part5 doctor` handles `simon.replay.v1` and, for an analysis,
  notes `score` and the timed fields when present (`--for part7`); it accepts a warned 1.5.0 analysis (warnings
  `low_match`, faults at confidence `"low"`, the score capped at F, cues, insights, tempo) and a minimal 1.4.0
  document (status `ok`, `faults: []`, no `confidence`), which is what Part 7 writes as its own fallback.
- `make check-5-contract` goldens regenerated with `make output-examples` (template phrasing, deterministic), plus a
  golden replay `fixtures/output/replay.example.json`. The goldens are built through the path `part5 analyse` uses,
  the score hook included (`part5.contract.golden_run`), so they carry the score, its timeline, the tempo and the
  insights real output carries; `check-5-contract` rebuilds all three byte for byte.

### CLI after J1
```
part5 analyse --expected <file> --follower <file> --out <analysis.json> [--replay <replay.json>]
              [--phrasing template|local-llm|muse-spark] [--live]
part5 serve [--host 127.0.0.1] [--port 8725] [--base-path /] [--live]
part5 contract [--schema <name>] [--json]
part5 doctor <file> [--for part5|part7] [--json]
part5 report-real [--out out/report-real/report.json]
```
Exit codes: 0 analysis written (with or without warnings), 1 input or write error, 2 usage. Exit 3 (a refused
analysis written) is no longer produced since ADR-0012.

### `make check-5` additions (score)
- Report, per slice of every set it already reads (seed 5 tuning, the held-out set, kit, stock): `score: {n, min,
  median, max, grades: {A, B, C, D, F}}`, never gated except as below.
- Gate (added to the existing gate): every correct (no labelled fault) good-light take of the held-out set scores A;
  and the monotonicity sweep passes: for `foot_out` right (0 to 28 degrees in steps of 4), `arms_wider` both (0 to
  35 in steps of 5) and `trunk_lean` centre (0 to 30 in steps of 5), each built with
  `scripts/make_dummy_followers.py` on the exercise expected clip with a fixed `random.Random(1234)`, the score never
  rises as the size grows. The sweep writes its takes under `out/check-5/sweep/` only.
- Low light is reported, never graded against a target.

### Held-out score report (`make score-heldout SEED=<n>`; 47 and 53 were the two)
`python3 scripts/make_dummy_followers.py --seed <n> --out out/score-heldout/seed-<n> --dropout-variant` then
`python -m part5.score_report --set out/score-heldout/seed-<n>`; prints the per-slice distribution and the target
verdicts, and the `labels.json` sha256. Run by `scripts/make_score_heldout.py`, which refuses (exit 2, a plain
message, before it generates or scores anything) a seed already in `fixtures/score-heldout.json`: a recorded seed is
retired, and 47 and 53 are. Each seed is generated once after the score freeze commit; never committed under
`fixtures/` (the generator is deterministic; `labels.json` sha256 is recorded). Results go in `docs/thresholds.md`
"Score" and append-only `fixtures/score-heldout.json`, written by hand as measured.

## Research evidence (2026-10-30; none of it is a held-out result)
Prototype `journey-b/score/score.py` with `params.json` above, rerun on 2026-10-30. Grades per slice, `light/labelled
faults`. Seed 5 is the calibration set; 31 belongs to the threshold protocol; 41 and 43 were seen by the research.

| Seed | good/0 | good/1 | good/2 | low/0 | low/1 | low/2 |
|---|---|---|---|---|---|---|
| 5 | A 12 | B 28, C 8 | D 6 | A 7, B 3, D 1, F 1 | A 1, B 8, C 14, D 8, F 5 | D 2, F 4 |
| 31 | A 20 | A 1, B 45, C 14 | D 10 | A 15, B 3, F 2 | A 4, B 15, C 23, D 8, F 10 | D 4, F 6 |
| 41 | A 20 | B 45, C 15 | D 7, F 3 | A 12, B 7, F 1 | A 6, B 17, C 19, D 6, F 12 | D 2, F 8 |
| 43 | A 20 | A 4, B 44, C 12 | D 8, F 2 | A 9, B 7, F 4 | A 6, B 19, C 13, D 10, F 12 | C 2, D 1, F 7 |

A single-fault take at A is one whose fault was not detected. Sweep (`sweep.py`, exercise clip, seed 1234), score
and grade by size: `foot_out` right 0 to 8 degrees 100 A, then 12: 86 B, 16: 83 B, 20: 81 B, 24: 79 C, 28: 77 C;
`arms_wider` both 0 and 5: 100 A, then 10: 87 B down to 35: 74 C; `trunk_lean` centre 0 and 5: 100 A, then 10: 87 B
down to 30: 76 C. Never rising. Below the detection threshold no fault is counted and the similarity term stays at 0.

## Acceptance Criteria
### J-1 time
#### AC-T01: times from the follower file
Given a follower whose frames carry `t` starting at 0.0 at 30 fps and a fault whose `follower_frames` is [57, 90],
when analysed, then `follower_t_s` is [1.9, 3.0] and `at_s` is 1.9; given a follower whose `t` starts at 5.0, then
the times are the file's own (6.9, 8.0), not shifted.
#### AC-T02: every run mapped
Given a fault with three `runs`, then `follower_runs` has three entries in the same order, each mapped through
`exp_to_fol` and `to_original`, and the entry of the reported run (the longest, or under a profile other than fitness the one `profiles.md` names) equals `follower_frames`.
#### AC-T03: rounding
Given `follower_t_s[0]` of 1.85 and 1.849, then `at_s` is 1.9 and 1.8 (half up, decimal-safe).
#### AC-T04: timed text
Given the research `foot_out` take (`exercise_front_good_03_foot_out-right`), then `text_timed` is the timed words
plus ` at <at_s> s` with one decimal, and `text` equals its 1.1.0 value byte for byte.
### J-2 direction
#### AC-L01: lateral table
Given each row of the lateral table, when a fault of that measure, direction and side is built, then `lateral`
matches the table; every other measure gives `null`.
#### AC-L02: timed words
Given every measure, direction and side, then `describe_timed` gives the vocabulary table's words, and every
timed line passes `line_problem(fault, line, timed=True)` with its own `at_s` (the template can never fail its own
validator). A `thigh_forward` timed line says "not raised enough" (never "too low"), and the validator refuses a
line that calls such a thigh "too low", "lower" or "hanging": those words carry no direction for that measure, so
the line falls back to `text_timed`.
#### AC-L03: foot offset
Given a right `foot_out` fault with the ankle moved 0.08 m further out over its runs, then `lateral_m` is 0.08 within
0.01; given a `knee_flexion` fault, then `lateral_m` is absent.
### J-3 replay
#### AC-R01: replay written
Given `--replay <path>`, when the take is ok or has warnings, then the file validates against
`contracts/replay.schema.json`, its unchanged keys equal the staging API's `replay` for the same inputs, and
`expected_t`, `follower_t` equal the clips' `t`.
#### AC-R02: nothing on failure
Given an input error (exit 1), then neither file exists; given an unwritable replay path, then exit 1 with
`part5 analyse: cannot write <path> (<reason>)` and the analysis that was written stays.
#### AC-R03: doctor
Given a valid replay, then `part5 doctor` exits 0 naming `simon.replay.v1 1.0.0`; given one with `exp_to_fol`
shorter than `expected`, an index out of range, or decreasing `t`, then exit 1 naming the field.
### J-4 score
#### AC-S01: prototype reproduced
Given seed 5, when `python -m part5.calibrate --score` runs, then it writes the `score` block and its values equal the
research prototype's (`z0 0.289`, `z1 0.732`, `s_max 4.0`, `base 16`, `slope 5.9`, `cap 31.1`); any difference is
explained in `docs/thresholds.md` "Score" before the freeze commit.
#### AC-S02: formula
Given hand-built faults and measures, then `value`, `grade`, `components` and `params_sha256` equal the formula above,
including `round_half_up` at .5, the clamp at 0 and 100, and each band edge (90 A, 89 B, 60 D, 59 F).
#### AC-S03: take with a warning
Given a take with a warning (ADR-0012; before it, a refused take had `score: null`), then `score` is never `null`,
its `value` is at most 59, its `grade` is `F`, `capped_by` names the warning codes and the analysis validates.
#### AC-S04: check-5 gate
Given the held-out set, then `make check-5` reports the grade distribution per slice and exits 1 when any correct
good-light take is below A or the sweep rises at any step (tested with injected scores); low light never gates.
#### AC-S05: held-out report
Given the score freeze commit, when seeds 47 and 53 are generated and scored once each, then `docs/thresholds.md`
"Score" and `fixtures/score-heldout.json` record per slice the distribution and each target's verdict (correct
good-light all A; single faults B or C; double faults D or F; monotonic), as measured, pass or fail, with the freeze
commit, `params_sha256`, the generator command and the `labels.json` sha256. No param changes after the freeze.
#### AC-S06: freeze check keeps working
Given `part5/rules.json` with the new `score` block, then `make check-5` still accepts the detection rules frozen at
`fbb0bea` (ADR-0007, "Freeze check"), and any change to a detection key still exits 2.
### J-5 phrasing
#### AC-P01: live default
Given `SIMON5_LIVE=1`, `META_LIVE=1`, `--live` or `serve --live`, with no `--phrasing`, then `phrasing.requested` is
`muse-spark` and `selected_by` is `live`; with `--phrasing template`, then `template` and `flag`; with none of them,
then `template` and `default`.
#### AC-P02: deterministic paths stay template
Given `SIMON5_LIVE=1` and `META_LIVE=1` in the environment, when `make check-5`, `make check-5-contract` and
`make output-examples` run, then every analysis is `template` and the goldens are byte-identical.
#### AC-P03: validator
Given an injected client, then the example line ("Your right foot drifts too far to the right at 1.9 s; keep it
under your hip") passes for a right `foot_out` `more` fault at 1.9 s; these fail with the reason named: no time,
"2.0 s" instead of "1.9 s", the time twice, "8 degrees", "to the left", "left foot", "your shoulder" on a
`knee_flexion` fault, two lines, 161 characters.
#### AC-P04: fallback per fault
Given an injected client that times out, returns HTTP 500, returns empty content or fails the validator for one of
three faults, then that fault's `coaching` is its `text_timed`, its record names `backend: template`, `model: null`
and the reason, and the other two keep the model's lines with `backend: muse-spark` and the model name.
#### AC-P05: limits and ledger
Given 31 calls inside a minute in one process, then the 31st falls back with `rate limited`; given a client that
takes 8 s per call and four faults, then the third and fourth fall back with `time budget spent`; every call made
appends one ledger line, and the key never appears in output, logs, errors, the ledger or a staging response
(sentinel key test).
#### AC-P06: live smoke stays opt-in
`make smoke-muse-spark` makes one live call with the timed prompt and exits 0 only when the line passes the timed
validator; `make test`, `make check-5` and the publish check never call it.
#### AC-P07: quality review (TICKET-037)
Given 20 lines generated live on the real stock takes (`fixtures/input/eval/real/`, filled from Part 3's kit takes
when the stock takes yield fewer than 20 faults), then `docs/phrasing-review.md` records each line, its fault record,
the validator verdict, a readability mark and a fact-fidelity mark, the ledger token totals, and the summary; any
line that passed the validator but misstates a fact opens a ticket.
#### AC-P08: the timed prompt asks for normal punctuation (TICKET-041)
Given the system message of the timed prompt (`part5/phrasing/prompt.py`), then it asks for normal punctuation: a comma
before a closing phrase such as "keep going", and a full stop at the end (the 2026-10-31 live line
read "nice effort keep going"). The validator is not touched by this AC, so the prompt cannot widen what a line may
claim. Verification: `tests/test_phrasing_timed.py` (the prompt text only; no live call, the key is never read).
#### AC-P09: no praise in a fault line (ADR-0008, R2)
Given the timed prompt, then it names no praise phrase ("nice effort" and "almost there" are gone) and asks for a line
with no praise or congratulation at the start or the end; an ending such as "keep going" is allowed. Given a model
line that holds one of `template.PRAISE_PHRASES` ("nice effort", "great job", "well done", "good job", "nice work",
"nice try", "great start", "looking good", "excellent work", "solid effort", "you're doing great", "you are doing great"
and the rest of the list), in any case and any place, with the words of the phrase joined by spaces or hyphens
("nice-effort") and with or without zero-width characters (U+200B, U+200C, U+200D, U+2060, U+FEFF; one that is the only
separator of two words reads as a space), then the validator rejects it with the reason `adds praise` on both paths,
the timed (`timed=True`) and the untimed one, so a live fault line without a time is held to it too. That fault's
`coaching` is its `text_timed` (timed) or its `text` (untimed), its record names `backend: template`, `model: null` and
`fallback_reason: "<backend>: adds praise"` (`muse-spark: adds praise`, or `local-llm: adds praise` for the local model;
a free string in the schema, so the schema is unchanged), and the other faults keep the model's lines. A line without
praise passes as before: "good form otherwise", "well aligned otherwise" and "keep going" are not praise, and the rest
of the untimed test is unchanged. Verification: `tests/test_phrasing_timed.py` (the validator on both paths, injected
client, no live call), `tests/test_phrasing_muse_spark.py` and `tests/test_phrasing_local_llm.py` (an untimed praised
line falls back with the backend's reason), and the live re-review in `docs/phrasing-review.md` ("Re-review
2026-10-31"), which is opt-in and never part of `make test`.
### J-6 contract
#### AC-C01: old readers
Given a 1.2.0 `analysis.json`, then it validates against the 1.1.0 schema at `28d20ef` and loads through the 1.1.0
`part5.output.validate_analysis` (extra fields allowed). This holds for every later version of a take that carries no
warning (the goldens included). A take analysed with a `low_match` warning (1.4.0, ADR-0012) is the one deliberate
exception: its faults carry `confidence: "low"`, which the 1.1.0 schema rejects, so it fails on `faults[*].confidence`
and nowhere else. Verification: `tests/test_schema_compat.py`, which vendors that schema and the two goldens under
`tests/fixtures/`.
#### AC-C02: contract and doctor
Given the changes, then `part5 contract --json` lists `replay` and the new rows, `CONTRACT.md`'s generated block
equals the generator, and `doctor --for part7` on the new goldens exits 0, as it does on a warned 1.5.0 analysis and
on a minimal 1.4.0 document with `faults: []` and no `confidence` (`tests/test_doctor.py`).
#### AC-C03: goldens
Given `make output-examples`, then `fixtures/output/analysis.example.json`, `analysis.no-faults.example.json` and
`replay.example.json` are rebuilt deterministically (the analysis goldens carry `score`, `timeline`, `tempo` and
`insights`, the way `part5 analyse` writes them) and `make check-5-contract` exits 0 (`tests/test_output_examples.py`).
#### AC-C04: published
Given the publish, then a fresh clone of upstream passes `make test`, `make check-5` and `make check-5-contract`.

### Rule-Based ACs
- AC-NFR-J01: no network call in any test or in `check-5` (sockets blocked). Verification: test.
- AC-NFR-J02: two template runs write byte-identical `analysis.json` and `replay.json`. Verification: test.
- AC-NFR-J03: `make check-5` with the sweep stays under 10 minutes on this host. Verification: timed run.
- AC-NFR-J04: the key never leaves the adapter. Verification: sentinel test (AC-P05).

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| Replay path not writable | exit 1; the analysis stays | `part5 analyse: cannot write <path> (<reason>)` | AC-R02 |
| Live mode without the key file | template with time, per fault | `fallback_reason: "no key"` | AC-P01 |
| Model line fails the validator (praise included: `adds praise`) | that fault falls back | `"muse-spark: <reason>"` | AC-P03, AC-P04, AC-P09 |
| Timeout, HTTP error, empty content | that fault falls back | unchanged reasons: `"muse-spark: timeout after 10 s"`, `"muse-spark: HTTP <code>"`, `"muse-spark: empty content"` | AC-P04 |
| Rate limit or budget | that fault falls back | `"rate limited"`, `"time budget spent"` (plain, as the code writes them: they are not a call's failure) | AC-P05 |
| Detection rules changed after the freeze | `check-5` exit 2 | unchanged freeze message | AC-S06 |
| Unknown `--phrasing` | exit 2 (argparse) | argparse | AC-P01 |

## Edge Cases
- A fault that starts on the follower's first frame: `at_s` is the file's first `t` (0.0 for Part 3 files).
- Two runs mapped to the same follower frames (a follower that held still): kept as two entries.
- `side: both`: `lateral` is `null`; the timed words are the existing both-side line.
- No faults: `score.components.faults` is 0 and the value comes from similarity alone; `phrasing.faults` is `[]`.
- A take with every measure missing at a frame: those cells are left out of `mean_z` (NaN-masked).
- `at_s` of 10.0 and above: formatted `10.0 s`; the validator matches the whole number token, not a substring.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | phrasing time | at most 20 s per analysis in live mode | AC-P05 |
| Performance | `check-5` | under 10 minutes | AC-NFR-J03 |
| Security | secrets | key read only in the adapter; sentinel test | AC-NFR-J04 |
| Reliability | determinism | byte-identical template runs | AC-NFR-J02 |
| Compatibility | readers of 1.1.0 | every new field optional | AC-C01 |
| Maintainability | tests | every AC named in a test | all |
| Accessibility | copy | one sentence, plain words, the time in seconds | AC-P03 |

## Negative Requirements
- MUST NOT let phrasing change `text`, a scored field or the score. Why: #20, ADR-0005.
- MUST NOT tune any score param on seeds 29, 31, 37, 41, 43, 47 or 53. Why: ADR-0007.
- MUST NOT make a live call in tests, `check-5`, `check-5-contract`, `output-examples` or the publish check.
- MUST NOT change a detection threshold or guard limit. Why: ADR-0003 freeze.
- MUST NOT rename or reshape a 1.1.0 field or a replay key. Why: Part 7 and the staging viewer read them.

## Compromises
### Synthetic calibration
Short-term: seed 5 synthetic takes calibrate the score. Long-term: filmed takes with known faults (#12). Trigger:
the team films its own takes.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `part5/pipeline.py` | times, follower runs, lateral, score, replay, live default | TICKET-032 to TICKET-036 | yes |
| `part5/detect.py` | expose per-run follower mapping inputs (no rule change) | TICKET-032 | yes |
| `part5/output.py` | schema 1.2.0 fields and validation | TICKET-032 to TICKET-036 | yes |
| `part5/words.py` | `describe_timed`, lateral and "too low" words | TICKET-032, TICKET-033 | yes |
| `part5/lateral.py` | lateral table and `lateral_m` | TICKET-033 | yes |
| `part5/replay.py` | `simon.replay.v1` keys, `write_replay` | TICKET-034 | yes |
| `part5/score.py` | `simon.score.v1` | TICKET-035 | yes |
| `part5/score_report.py` | held-out score report | TICKET-035 | yes |
| `part5/calibrate.py` | `--score` | TICKET-035 | yes |
| `part5/check.py` | score report, score gate, sweep, freeze check (ADR-0007) | TICKET-035 | yes |
| `part5/rules.json` | `score` block | TICKET-035 | yes |
| `part5/phrasing/__init__.py`, `template.py`, `prompt.py`, `muse_spark.py`, `local_llm.py`, `smoke.py` | live default, timed prompt (`prompt.py`) and validator, limits, per-fault model | TICKET-036 | yes |
| `part5/cli.py` | `--replay`, `--live`, `serve --live` | TICKET-034, TICKET-036 | yes |
| `part5/api.py`, `part5/server.py` | replay keys, live default, process-wide limit | TICKET-034, TICKET-036 | yes |
| `part5/contract.py`, `part5/doctor.py` | rows, replay schema, doctor support, `replay_problems`, `golden_run` | TICKET-034, TICKET-038 | yes |
| `contracts/analysis.schema.json`, `contracts/replay.schema.json`, `contracts/metrics.schema.json` | 1.2.0, 1.0.0, 1.1.0 | TICKET-032 to TICKET-035 | yes |
| `scripts/make_output_examples.py` | replay golden, forced template, the CLI's path with the score hook | TICKET-038 | yes |
| `scripts/make_score_heldout.py` | `make score-heldout`: scores one unrecorded seed, refuses a recorded one | TICKET-035 | yes |
| `scripts/make_design_copies.py` | regenerates `docs/design/` from `docs/specs/` and `docs/adr/`, with a leak guard | TICKET-038 | yes |
| `fixtures/output/analysis.example.json`, `analysis.no-faults.example.json`, `replay.example.json` | regenerated goldens | TICKET-038 | yes |
| `fixtures/score-heldout.json` | append-only held-out score record | TICKET-035 | yes |
| `Makefile` | `score-heldout` and `design-copies` targets | TICKET-035, TICKET-038 | yes |
| `docs/schemas.md`, `docs/thresholds.md`, `CONTRACT.md`, `README.md` | fields, score section, rows, live mode | TICKET-032 to TICKET-038 | yes |
| `docs/design/README.md`, `docs/design/specs/*.md`, `docs/design/adr/*.md` | generated neutralised copies | TICKET-038 | yes |
| `docs/phrasing-review.md` | AC-P07 record | TICKET-037 | yes |
| Tests: `tests/test_time_fields.py`, `test_lateral.py`, `test_replay_contract.py`, `test_score.py`, `test_check_score.py`, `test_phrasing_timed.py`, `test_output_examples.py`, `test_score_heldout.py`, `test_design_copies.py`, plus updates to `test_output.py`, `test_cli.py`, `test_api.py`, `test_contract_cli.py`, `test_doctor.py`, `test_phrasing*.py`, `test_words.py` | per AC | with each ticket | yes |

## Delivery Verification Plan
- `make test` 0; `make check-5` 0 (score gate included); `make check-5-contract` 0; `make report-real` 0.
- `make score-heldout SEED=47` and `SEED=53` once each after the freeze; results recorded as measured.
- `make smoke-muse-spark` once, opt-in, ledger line recorded; TICKET-037 review recorded.
- `staging.sh up simon-part-5` and `verify simon-part-5` 0; QA recipe: analyse a stock take on the page
  in live mode and see a timed line and the score (two witnesses: the API JSON and the rendered page; negative: no
  fault row without a time, since ADR-0012 the score is never null and a different movement is analysed with a
  `low_match` warning and grade F).
- One consolidated review, `/delivery-review` PASS, then publish and a fresh-clone check (TICKET-038).

### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|---|---|---|---|
| Desktop Chromium | Playwright (`staging/verify.mjs`) | 1440 | TICKET-036 lane |
| Phone width | Playwright | 390 | TICKET-036 lane |

### Data
Seed 5 (calibration), the current held-out set (gate), seeds 47 and 53 (report only, generated after the freeze),
Part 3's kit and the stock takes (reported).

## Dissent Review
### Concern: `coaching` changes value for template runs
In 1.1.0, `coaching` equals `text` for `template`; in 1.2.0 it equals `text_timed`. A reader that compared the two
would notice. Kept: no consumer compares them (Part 7 shows `coaching`), the change is documented in `CONTRACT.md`,
and the fallback of a model line must carry the time to meet the directive.
### Concern: the score gate reuses the threshold protocol's held-out set
It is a regression gate, not a held-out claim: the claim lives on seeds 47 and 53, scored once.

## Deviations from PRD
- Similarity term: the brief says "all 18 measures"; `part5.measures.MEASURES` holds 22 per-frame measures today
  (20 plus the two `knee_valgus`), and the research prototype (`collect.py`) iterates all of them. This spec follows
  the prototype: every measure in `MEASURES`. Changing it would move `z0` and `z1`.
- `round_half_up` is clamped to 0 to 100, as the prototype does (`max(0, ...)`).
- Replay per-frame times are two added arrays (`expected_t`, `follower_t`) instead of reshaping each frame into
  `{t, joints}`, so the staging viewer and any reader of today's payload keep working (ADR-0009).
- `phrasing.faults[k].model` and `phrasing.selected_by` are added to record the per-fault model and how the backend
  was chosen.
