# Spec: Part 5, fault analysis (expected clip and follower take in, `analysis.json` out)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature (takeover of an in-flight part)
Risk Level: medium
Registry: `engagements/simon-part-5.yaml` in the hub (milestones S0, M1 to M4; use cases uc-analyse-take,
uc-correct-take, uc-wrong-movement, uc-done-check, uc-real-takes, uc-integration-contract).
ADRs: ADR-0001 (workspace and publish), ADR-0002 (takeover and PR landing), ADR-0003 (held-out calibration
and gate), ADR-0004 (knee caving and movement guard), ADR-0005 (phrasing registry), ADR-0006 (viewer and
joint mapping). Companion specs: `integration-contract.md`, `check-5.md`, `calibration.md`,
`real-takes.md`, `staging.md`, `viewer.md`, `neighbour-check.md`, `simon-publish.md`.

## Overview
Part 5 compares a follower's 3D take with the expected clip at the same phase of the movement and
reports each fault: the measure, the joint, the side, the direction, the size, the frames and a
plain-words line, as `analysis.json` for Part 7. The pipeline on upstream main (`06fd4a2`) already
loads, normalises, aligns (DTW), measures 24 per-frame quantities, detects faults and words them; 172
tests pass. This spec covers what the takeover adds: the three open PRs landed, knee caving, a guard
that refuses a different movement, persistence and overlap rules (#30), dropout and confidence takes
(#25), expected clips refreshed from Part 4 main, a held-out calibration and gate, a coaching phrasing
registry, the integration contract, a staging app with a 3D replay, and a report on real takes.

## Why This Is Wrong (Dissent-First)
1. The thresholds were tuned on the same 96 takes that gate `make check-5` (P = R = 1.00 in good light).
   A green check on that set proves fit, not skill. Answer: a held-out seed gates; seed 5 stays the
   tuning set (ADR-0003).
2. Synthetic faults are clean rotations of a limb chain; real faults are not. Answer: real takes (Part 3's
   kit, stock clips) are scored and reported on every run, never gated, and never hidden (`real-takes.md`).
3. A pipeline that always finds "the closest phase" turns any movement into faults (cat-cow yoga against
   the squat reports 9). Answer: the movement guard refuses before detection (ADR-0004).
4. Part 3's kit labels `knee_caving` and Part 5 has no measure for it, so a common squat fault is
   invisible. Answer: the `knee_valgus` measure (ADR-0004).
5. Refreshing the expected clips moves every take and every tuned threshold. Answer: refresh once, at the
   start of M2, before tuning; never after a held-out seed is scored.

## User Story
As a follower, I want each fault said in plain words and shown on a replay of my take over the expected
movement, so that I know what to change. As Part 7, I want one validated `analysis.json` per take with a
status I can trust.

### Jobs-to-be-Done
- Functional: say what differed, where, by how much and when.
- Emotional: a correct take is told so, not given noise.
- Social: the team can show a measured, honest done-check.

## Pipeline (in this order; `part5.pipeline.analyse`)
1. Load both clips (`part5.io.load_clip`): `simon.animation.v1` frames or `simon.skeleton.v1` keyframes;
   missing or `null` joints and `conf` below 0.3 are masked (unchanged).
2. Resample the follower onto the expected clip's clock (PR #37, d181e99). `follower_frames` and
   `follower_span` keep indexing the follower file as given.
3. Normalise (unchanged).
4. Measures (`part5.measures.compute`): the 24 existing ones plus `left_knee_valgus` and
   `right_knee_valgus` (below).
5. Availability check: under 50% measurable is an `AnalysisError` (unchanged, exit 1).
6. Alignment (`part5.align.align`, unchanged): two-pass DTW, open begin and end.
7. Movement guard (`part5.guard.check_movement`, new). A refused take stops here: `analysis.json` is
   written with `status.code: "different_movement"` and `faults: []`.
8. Detection (`part5.detect.detect`) with the persistence and overlap rules below.
9. Per-fault canonical joints (`part5.joints_map.fault_joints`, new; ADR-0006).
10. Words (`part5.words.describe`, unchanged template) and coaching phrasing
    (`part5.phrasing.phrase`, new; ADR-0005).
11. Build and validate (`part5.output.build_analysis`).

## Measures added
### `knee_valgus` (left and right)
For hip h, knee k and ankle a of one leg, with `inward = -OUT[side]` (toward the midline):
`d = ((k - h) - proj_{(a - h)}(k - h)) . inward`, `knee_valgus = degrees(atan2(d, |k - h|))`.
Positive means the knee sits inside the hip to ankle line (knee caving). It is 0 for a straight leg in
the frontal plane and does not depend on body size. `MeasureSpec(f"{side}_knee_valgus",
f"{side}_knee", side, "legs", "direction", "knee caving in, inside the hip to ankle line")`.
Rules entry `knee_valgus: {"threshold_deg": <tuned on seed 5>}`, starting value 8.0. Words: `more` reads
"left knee caving in", `less` reads "left knee pushed out". The first plan said `explained_by` gains
`"knee_valgus": ["foot_out"]` only if tuning showed it; the rules decided on seed 5 before the freeze
(`fbb0bea`) and frozen in `part5/rules.json` are different and are the ones in force: no `foot_out`
entry for `knee_valgus`, and a kept `knee_valgus` fault explains away two faults of the same take that
overlap it, `explained_by.knee_flexion: ["knee_valgus"]` (same side, same direction) and
`explained_by_opposite.thigh_out: ["knee_valgus"]` (same side, the other direction: `knee_valgus`
`more`, a knee caving in, explains `thigh_out` `less`, the thigh pulled in). `explained_by_opposite`
is `explained_by` with the kept fault in the other direction (`part5/detect.py`). Why: the MEASURES
lane injected 15 to 25 degrees of knee caving, noise-free, into both expected clips; every injection
also raised `thigh_out` `less` and, from 20 degrees, `knee_flexion` `more` on the same side, so one
knee caving fault was reported as two or three; with these two entries each injection reports exactly
one `knee_valgus` fault, `more`, on its side (`tests/test_detect.py`, AC-003). Changing either entry
is a rule change after the freeze, not a fix.
Label type `knee_caving` maps to measure `knee_valgus` in `LABEL_TYPE_TO_MEASURE`; Part 3's kit type
`knee_caving` maps to the same measure in the real-take adapter.

## Movement guard (ADR-0004)
`part5.guard.check_movement(alignment, exp_measures, fol_measures, rules) -> GuardResult(ok: bool,
code: str, text: str, stats: dict)`.
- Statistics, from the alignment's second pass: `residual` (mean capped z cost per path cell, as
  `Alignment.residual`), `timing_corr` (median over the timing measures of the Pearson correlation
  between the expected series and the follower series sampled at `exp_to_fol`, NaN-masked), and
  `span_share` (matched follower frames over follower frames).
- Refuse when `residual > guard.max_residual` or `timing_corr < guard.min_timing_corr`. The two limits
  live in `part5/rules.json` under `"guard"` and are calibrated on the seed 5 tuning set
  (`calibration.md`): every tuning take against its own expected clip must pass, and every mismatch
  pair must be refused (each exercise take against the dance clip and each dance take against the
  exercise clip, plus Part 2's `class` (cat-cow yoga), `dance` and `single` (a seated stretch) takes
  through Part 3 `--view part5` against the squat; `single` counts only once Part 2 publishes its seated-stretch output; while the committed `single/pose3d.json` is the provisional squat clip (sha256 `433ae2ed`), it is a matched squat pair, reported and never in the mismatch population (stakeholder-proxy, 2026-10-29)). Each
  limit sits at the midpoint of the gap between the two populations; when the populations overlap, the
  limit keeps every matched tuning take passing and the overlap is reported in `docs/thresholds.md`.
- `span_share` keeps its current role (a warning under 0.6), never a refusal.
- Status text, plain words, no numbers: "This take does not look like the expected movement, so no
  faults are listed. Check that you picked the right movement and that the whole movement is in the
  take." Stats go in `diagnostics.guard`.

## Repetitions (ADR-0010; schema 1.3.0)
Real clips hold several repetitions and the counts rarely match (a trainer's 3 slow reps, a follower's 8 fast
ones), which the slope-limited whole-clip alignment cannot follow. `part5/reps.py` cuts a clip into reps and
`part5/repwise.py` compares one rep at a time. It runs only when the whole-clip guard refuses (or the whole-clip
alignment cannot run) and either clip has two or more cycles; a pair the whole-clip guard accepts is analysed
as before, so seed 5, the held-out seeds and the goldens do not move.
- **Segmentation**: the measure with the largest p95 minus p5 range (at least 15 degrees), smoothed over 0.25 s;
  turning points that stand out by 35% of the range; cuts at the dips or at the peaks, whichever gives more cycles
  (ties to the dips), at least 0.6 s apart. Fewer than two cycles: one segment, the whole clip. The follower
  prefers the expected clip's measure and cut type when it moves that measure at least half as much as its own best.
- **Reference**: the expected clip's first complete rep, or the whole clip when it has one
  (`diagnostics.expected_reference.kind`: `first_rep` or `whole`).
- **Per rep**: each follower rep is resampled to the reference's frame count, then aligned, guarded (frozen
  limits) and detected on its own. A rep passes when the guard passes and the matched span covers at least 60% of
  it. A follower that is one segment is compared whole against the reference.
- **Verdict**: accepted when a strict majority of follower reps pass and at least one; otherwise
  `different_movement`, no faults, nothing new in the document. `diagnostics.guard.residual` and `timing_corr` are
  medians over the reps, and `diagnostics.guard.reps` is `[{span_s, residual, timing_corr, ok}]`.
- **Faults**: a fault (same measure, side, direction) counts when found in at least half of the accepted reps, or
  always for a single rep. It is reported once: `at_s`, `follower_t_s` and `follower_runs` from its first
  occurrence on the follower file's clock, the median `magnitude_deg`, the largest `peak_deg`, and `reps`, the rep
  indices it was found in.
- **Score**: `score.compute` per accepted rep (over the reported faults), then the mean of the components;
  `score.per_rep` lists each rep's value and grade.
- **Replay**: the expected rep tiled once per follower rep against the whole follower take; `exp_to_fol` maps each
  tiled frame to the follower file's frames; the optional `reps` list holds each rep's expected frames, follower
  frames and verdict.
- **Document**: a take compared this way carries `schema_version` `1.3.0`; any other take keeps `1.2.0`.

## Detection changes (#30)
- Persistence: a fault counts when the frames of all runs past threshold in one direction, each run at
  least `min_run_frames` long (default 4 at the expected clock), sum to at least `min_fraction` of the
  expected clip (floor `min_frames_floor`). `expected_frames` and `follower_frames` stay the longest
  run (unchanged meaning); the new additive field `runs` lists every counted run as
  `[[start, end], ...]` in expected frames; `magnitude_deg` is the median over all counted runs.
- Overlap: `_drop_explained` and `_merge_sides` require an overlap of at least `min_overlap` (default
  0.5) of the shorter run's frames, and only faults that are kept can explain others away.
- New rules keys: `min_run_frames`, `min_overlap`. Starting values are the defaults above; tuning on
  seed 5 may change them, and the final values go in `docs/thresholds.md`.

## Output additions (`simon.analysis.v1`, additive; schema version 1.1.0)
Every addition is optional for a v1.0 reader; `CONTRACT.md` names Part 7's duties.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | `"1.1.0"` |
| `status` | object | `{code: "ok" \| "different_movement", text: string}`; `faults` is `[]` unless `ok` |
| `phrasing` | object | `{requested, backend, model, fallback_reason, faults: [{backend, fallback_reason}]}`; `backend` is the requested backend when it phrased at least one fault, else `template`; `faults` holds one entry per fault, in fault order, naming the backend that phrased it and any fallback reason |
| `faults[].joints` | list of canonical joint names | what to highlight (ADR-0006 mapping) |
| `faults[].runs` | list of `[start, end]` | every counted run, expected frames |
| `faults[].coaching` | string | the backend's line; equals `text` for `template` |
| `diagnostics.guard` | object | `residual`, `timing_corr`, `span_share`, limits |

`text`, `measure`, `side`, `direction` and every scored field never depend on the phrasing backend.

## Coaching phrasing registry (ADR-0005)
`part5.phrasing.phrase(faults, backend="template", **opts) -> (lines, record)`.
- `template` (default; the only backend in tests and `check-5`): returns each fault's `text`.
- `local-llm`: Ollama on `http://127.0.0.1:11434` when `command -v ollama` succeeds and a model is
  pulled; model name from `PART5_OLLAMA_MODEL`. Any failure (no binary, no model, timeout 10 s, a line
  that drops the joint, side or direction) falls back to `template` with `fallback_reason`.
- `muse-spark` (Muse Spark served by Baseten; ADR-0005): OpenAI-compatible chat completions,
  `POST https://inference.baseten.co/v1/chat/completions`, header `Authorization: Bearer <key>`, model
  exactly `meta-models/muse-spark-open-1026`, `max_tokens` 512 or more (a reasoning model: a short budget
  is spent on reasoning and returns empty content), timeout 10 s, stdlib `urllib` (no new dependency).
  The key is the file the file named by `PART5_BASETEN_KEY_FILE` (mode 600; path overridable by
  `PART5_BASETEN_KEY_FILE` for tests), read into memory at the call, whitespace stripped, never printed,
  logged, written or sent anywhere but that header. Live calls only when the key file exists and
  `META_LIVE=1` (#20). The request carries the measured fault record only: measure, joint, side,
  direction, magnitude, threshold, frames. Each call's `usage` block (prompt, completion and reasoning
  token counts, model, UTC time, HTTP status; never the key or the text) is appended to
  `~/.simon/baseten_usage.jsonl`. Without a key: `template`, `fallback_reason: "no key"`. Operator ask #335's
  Muse Spark item is satisfied by this key.
- Validation, per fault: the line must name the same body part and side and carry the direction's
  meaning (word test), and must add no number and no fault that the record does not hold. A line that
  fails, a timeout, an HTTP error or empty content falls back to `text` for that fault, and the
  `phrasing` record lists the backend that ran and the fallback reason per fault.
- Never used in tests or `check-5`: tests drive the adapter through an injected client. A separate
  opt-in live smoke target, `make smoke-muse-spark`, makes one real call; it is never part of
  `make test`, `make check-5` or the publish check.

## CLI (`python -m part5` and the `part5` script)
```
part5 analyse --expected <file> --follower <file> --out <analysis.json> [--phrasing template|local-llm|muse-spark]
part5 contract [--schema <name>] [--json]
part5 doctor <file> [--for part5|part7] [--json]
part5 serve [--host 127.0.0.1] [--port 8725] [--base-path /]
part5 report-real [--out out/report-real/report.json]
```
`analyse` exits 0 when it wrote an `ok` analysis, 1 for an input, alignment or write error (unchanged
messages), 3 when it wrote a refused analysis (`different_movement`). Exit 3 means a valid
`analysis.json` was written; a caller that expects the family convention 0, 1, 2 (Part 7 at 90aa473,
Part 3 `CONTRACT.md` row for Part 7) treats 0 and 3 as "written, read `status`" (`CONTRACT.md` names
the mapping). `contract` and `doctor`:
`integration-contract.md`. `serve`: `staging.md`. `report-real`: `real-takes.md`.

## Makefile targets (published)
| Target | Command | Exit |
|---|---|---|
| `check-5` | `uv run python -m part5.check` | 0 only when the gate passes (`check-5.md`) |
| `check-5-contract` | `uv run python -m part5.contract --check` | 0 when every schema, fixture and golden output validates |
| `test` | `uv run pytest -q` | pytest |
| `dummy-data` | `python3 scripts/make_dummy_followers.py` (seed 5, tuning set) | 0 |
| `heldout-data` | `python3 scripts/make_dummy_followers.py --seed $(SEED) --out fixtures/input/heldout --dropout-variant`; `SEED` is required (29, then 31, then 37; `calibration.md`) | 0; 2 without `SEED` |
| `output-examples` | `uv run python scripts/make_output_examples.py` | 0 |
| `report-real` | `uv run python -m part5 report-real` | 0 when every real take was analysed (refusals count as analysed) |
| `demo` | `uv run python -m part5 serve --port 8735` | foreground server for the isolated demo (#16); its own port, so it never clashes with `scripts/dev.sh` on 8725 |
| `smoke-muse-spark` | `META_LIVE=1 uv run python -m part5.phrasing.smoke` | opt-in live call to Muse Spark; 0 when a valid line came back; never run by `test`, `check-5` or the publish check |
| `test-contract`, `contracts-check`, `contracts-sync` | from PR #34 | unchanged |

## Locked defaults (2026-10-28; final, nothing here is asked)
| Item | Decision | Why |
|---|---|---|
| Merge order | #37, then #36, then #34, on local main, the team's commits kept | ADR-0002; all three touch `Makefile` or `docs/schemas.md` |
| #34 fix | `contracts-check` turns a missing upstream file into a plain message and exit 2, never a traceback | Muse's review on #34 |
| Tuning set | Seed 5, `fixtures/input/followers/`, regenerated once from the refreshed expected clips | ADR-0003 |
| Held-out set | Seeds 29, 31, 37 in that order, `fixtures/input/heldout/` (own `labels.json` naming the seed); each generated once after a freeze commit, scored once, then retired | ADR-0003; never 5 |
| Retuning | Never on held-out numbers; a retry needs a distinct approach family and the next seed; every attempt published; red after seed 37 ends DEGRADED with every attempt's numbers | ADR-0003, `calibration.md` |
| Take grid | 2 sets x 3 angles x 2 lights x 9 takes: 2 correct, 6 single-fault (one per type, `knee_caving` added), 1 double | 54 per set, 108 per seed (clean); `--dropout-variant` adds 72 dropout copies, 180 per held-out seed (corrected 2026-10-29: the first text said 108 per set) |
| Dropout variant | `--dropout-variant` adds one dropout copy of every side and 45 degree take with per-joint `conf` and far-side bursts (#25); slices `dropout/<angle>`, reported, never gated | #25 |
| `knee_caving` size | Knee moved inward by 15 to 25 degrees of `knee_valgus` over the full-strength window, both sets | ADR-0004 |
| Expected clips | Part 4 main `fixtures/output/{exercise,dance}/animation.json`, commit recorded in `fixtures/input/expected/SOURCE.md` and `contracts/sources.lock.json` | Refresh once (M2 start) |
| Kit expected clip | Part 4 main `fixtures/output/part3-squat/animation.json` copied to `fixtures/input/expected/part3-squat/animation.json` | Best match for Part 3's kit |
| Guard limits | `rules.json` `"guard": {"max_residual", "min_timing_corr"}`, calibrated on seed 5 and the mismatch pairs | ADR-0004 |
| Refusal | `status.code: "different_movement"`, `faults: []`, CLI exit 3, staging shows the status text | uc-wrong-movement |
| Gate | Held-out `good/front`, `good/45`, `good/side`: P >= 0.85, R >= 0.75, 0 faults on correct takes, no empty slice | D3 on #18, ADR-0003 |
| Reported, never gated | Seed 5 slices, low light, dropout, Part 3 kit, stock takes | D3, D2 |
| Match rule | D4: measure + side + direction, `both` label accepts either side, trunk at body-part level | #18 |
| Phrasing default | `template`; `check-5` and tests run `template` only | ADR-0005 |
| Ports | Local dev 8725 (`scripts/dev.sh`), `make demo` 8735, staging 7123 under `/simon-part-5/` | Registry; demo and dev never clash |
| Upload cap | 16 MiB per file, 6000 frames per clip (the follower counted once on the expected clip's clock; the expected clip at most 240 fps and with a usable frame rate; expected frames times follower frames at most 4,000,000, since the alignment's cost arrays grow with that product), checked in `part5/pipeline.py` before resampling | Same order as Part 3's 16 MiB |
| Numbers in output | Degrees rounded to 2 decimals, confidence and phase to 3 (unchanged where already set) | Byte-stable reruns |
| Black box | No code of Parts 2, 3, 4, 6 or 7 is imported or copied; their files only | README rule |

## Acceptance Criteria
### AC-001: landed PRs
Given local main after landing, when `git log` is read, then #37, #36 and #34 appear in that order with
the team's commits (or `Co-authored-by`), `make test` exits 0 and `make check-5` prints its metrics JSON.
### AC-002: knee valgus measure
Given a leg whose knee is placed so that its offset inside the hip to ankle line reads 20 degrees by the
formula above (`degrees(atan2(d, |k - h|))`), when `compute` runs, then `knee_valgus` reads 20 plus or
minus 1 degree on that side and 0 plus or minus 1 on the other; a straight leg reads 0 plus or minus 0.5.
(A leg swung toward the midline about the hip by beta reads `atan(sin(beta))`, so 20 degrees of the measure
is a swing of 21.3 degrees; a 20 degree swing reads 18.9.) Verification: `tests/test_measures.py`.
### AC-003: knee caving detected
Given seed 5 `knee_caving` takes in good light, when analysed, then each reports `knee_valgus` with the
labelled side and direction `more`.
### AC-004: movement guard refuses
Given the squat expected clip and Part 2's `class` (cat-cow yoga), `dance` or `single` (a seated stretch,
once Part 2 publishes it; the provisional squat `single` is a matched pair) take (through Part 3
`--view part5`), or any dance take against the exercise clip, when analysed, then `status.code` is `different_movement`,
`faults` is `[]` and the CLI exits 3.
### AC-005: movement guard accepts
Given every seed 5 take against its own expected clip, when analysed, then none is refused. Held-out
refusals are not an AC-005 failure: they are reported per slice under AC-K04 and lower recall.
### AC-006: persistence across runs
Given a 25 degree `upper_arm_out` fault held for 15% of the clip in three runs of 5% each, when detected
with `min_fraction` 0.12, then one fault is reported with three `runs`.
### AC-007: overlap
Given a 6.1 degree `foot_out` overlapping a 30 degree `thigh_out` by one frame, when detected, then
`thigh_out` is kept; a dropped fault never explains another away.
### AC-008: dropout takes load and score
Given the dropout variant, when loaded, then masked joints come through `part5.io` and `check-5`
reports `dropout/<angle>` slices.
### AC-009: canonical joints per fault
Given any fault, `joints` lists canonical joint names that exist in the 17-joint list (mapping in
ADR-0006), never empty.
### AC-010: phrasing record
Given `--phrasing muse-spark` with no key file, when analysed, then `phrasing.backend` is `template`,
`fallback_reason` names the missing key without the path's contents, and the scored fields equal those
of a `template` run. Given an injected client that returns empty content, an HTTP error, a timeout, or a
line with the wrong side or an added number for one fault, then that fault alone falls back to `text`
and the per-fault record names the reason; the other faults keep the backend's line.
### AC-011: refused analysis validates
Given a refused take, `analysis.json` validates against `contracts/analysis.schema.json`.
### AC-012: determinism
Given the same inputs, two runs write byte-identical `analysis.json` (template phrasing).

### AC-REP-1: segmentation
Given a measure series with three cycles, one cycle, none, or small ripple, when `reps.segment` runs, then it
returns three spans, one whole span, one whole span, and no extra cut. Verification: `tests/test_reps.py`.
### AC-REP-2: real multi-rep takes are compared
Given the real lateral-raise trainer and its 8-rep and 2-rep followers, when analysed, then both are `ok`, every rep
passes the frozen limits, the document is 1.3.0 and validates against `contracts/analysis.schema.json`, and the
replay validates against `contracts/replay.schema.json`. Verification: `tests/test_reps.py`.
### AC-REP-3: different movements stay refused
Given Part 2's dance, class, single and stretch and the stock squat against the lateral raise (and the squat against
the dance, class and stretch), when analysed, then each is `different_movement` with `faults: []`.
Verification: `tests/test_reps.py`.
### AC-REP-4: seed 5 unchanged
Given every seed 5 take against its expected clip, when analysed, then none is compared rep by rep and its document
stays 1.2.0 with no rep field; `make check-5` metrics are unchanged. Verification: `tests/test_reps.py`, `make check-5`.
### AC-REP-5: aggregation
Given reps with faults, then a fault found in at least half of the accepted reps is reported once with the median
magnitude and its `reps`; the score is the mean of the per-rep components. Verification: `tests/test_reps.py`.

### AC-VIS-1: a full-body pair is compared as before
Given a pair whose clips have no `conf`, or whose joints are all seen (conf not the 0.3 mark, or the 0.3 mark on one
side of a left/right pair only, as in a side view), then every measure is usable, the analysis has no
`diagnostics.visibility` and `make check-5` and the goldens are unchanged. Verification: `tests/test_visibility.py`,
`make check-5`, `make check-5-contract`.
### AC-VIS-2: only what the camera sees is compared (ADR-0011)
Given a clip with both joints of a pair at conf 0.3 (outside the image), then a measure is usable in that clip when
every joint it reads is seen in at least 80% of its frames; a clip with no conf takes the other clip's set, or the set
of `--expected-visibility`; the pair is compared on the intersection. Alignment, the guard, detection, faults and the
score use only those measures, in the frames where the joints are seen. `diagnostics.visibility`
`{usable_measures, excluded, rule}` is added (schema 1.3.0). Verification: `tests/test_visibility.py`.
### AC-VIS-3: upper-body takes of a full-body movement
Given a squat take with hips, knees and ankles at conf 0.3 against the squat, then it is accepted with the faults its
arms show; the same cut against a different upper-body movement (the real lateral raise against the salute) is refused.
Verification: `tests/test_visibility.py`.
### AC-VIS-4: not enough visible
Given fewer than 3 usable measures, then `status.code` is `not_enough_visible`, `faults` is `[]`, `score` is null, the
text asks for more of the body in frame and `part5 analyse` exits 3. Verification: `tests/test_visibility.py`.
### AC-VIS-5: the part the example moves must be in frame
Given a partial pair, when none of the measures that move in the expected clip (robust range above 20 degrees, among
those the example shows) is usable in the take, then `status.code` is `moving_part_out_of_frame`, `faults` is `[]`,
`score` is null, the text names the body part ("Your right arm is mostly out of frame, so it can't be compared. Step
back so your whole arm stays in view, then record again.") and `diagnostics.visibility` has `moving_measures` and
`moving_usable`. The operator's seated selfie salute (trainer `arm-salute-8b6512a8`, take edfadd7f3848, pose JSON under
`tests/local/selfie-salute/`, not published, `--expected-visibility` the trainer's skeleton) gives this status naming
the right arm. Verification: `tests/test_visibility.py`.

### Rule-Based ACs
- AC-NFR-001: `make check-5` runs offline in under 10 minutes on this host. Verification: test.
- AC-NFR-002: no network call in any test or in `check-5`. Verification: test with sockets blocked.
- AC-NFR-003: the Baseten key never appears in output, logs, errors, the usage ledger or a staging
  response. Verification: test with a sentinel key.
- AC-NFR-004: every muse-spark call appends one usage line to `~/.simon/baseten_usage.jsonl` (path
  overridable for tests) with the response's token counts. Verification: test with an injected client.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| Malformed input | exit 1, nothing written | `part5 analyse: <file>: <field>: <what>` (unchanged) | AC-001 |
| Under 50% measurable | exit 1 | unchanged | AC-001 |
| Follower over 2x faster | exit 1 | unchanged | AC-001 |
| Different movement | exit 3, refused analysis written | status text above | AC-004 |
| Phrasing backend fails | template used, `fallback_reason` | `"<backend>: <reason>"` | AC-010 |
| Unknown `--phrasing` | exit 2 (argparse) | argparse | AC-010 |

## Edge Cases
- Expected clip from `simon.skeleton.v1` keyframes: resampling uses the median keyframe step (#37 note).
- A take that is mostly idle: `span_share` warning, not a refusal (AC-005).
- Both knees caving: merged to `both` under the overlap rule.
- Dropout of a whole far-side leg in a side take: `knee_valgus` NaN there; coverage drops; no fault from
  missing data.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | One analysis | under 2 s on a 300-frame take | AC-NFR-001 |
| Security | Secrets | key file read only in the adapter | AC-NFR-003 |
| Reliability | Determinism | byte-identical reruns | AC-012 |
| Maintainability | Tests | every AC named in a test | all |
| Compatibility | Python | 3.10 or later, numpy only at run time | |

## Negative Requirements
- MUST NOT retune any threshold or guard limit on held-out numbers. Why: ADR-0003.
- MUST NOT list faults for a refused take. Why: uc-wrong-movement.
- MUST NOT let a phrasing backend change a scored field. Why: #20.
- MUST NOT import or copy code from another part. Why: README rule.
- MUST NOT publish a firm file. Why: ADR-0001.

## Compromises
### Synthetic gate
Short-term: the gate is synthetic held-out takes. Long-term: filmed takes with known faults (#12).
Trigger to revisit: the team films its own takes.

## Non-Requirements
- Reading video, building 3D from video, animating keyframes, the Part 7 app.
- A trained model for faults (rule maths only, README).

## Assumptions
ASM-001 to ASM-012 in `docs/assumptions/` (ASM-008: Part 4 main's expected clips are final for the refresh; ASM-010 to ASM-012: the viewer, staging and hand-off assumptions).

## Files (every new or changed source file; the write gate reads this table)
| File | Ticket | Published |
|---|---|---|
| `part5/check.py` (from #36, then held-out gate and reports) | TICKET-003, TICKET-018 | yes |
| `part5/pipeline.py` (resample from #37, guard, joints, phrasing) | TICKET-002, TICKET-015 | yes |
| `part5/measures.py` (`knee_valgus`) | TICKET-014 | yes |
| `part5/align.py` (`knee_valgus` kept out of the alignment measures, so alignment is unchanged) | TICKET-014 | yes |
| `part5/detect.py` (persistence, overlap) | TICKET-013 | yes |
| `part5/rules.json` | TICKET-013, TICKET-014, TICKET-015, TICKET-016 | yes |
| `part5/words.py` (knee lines) | TICKET-014 | yes |
| `part5/evaluate.py` (label map, refusal counts) | TICKET-014, TICKET-015 | yes |
| `part5/output.py` (additive fields) | TICKET-015, TICKET-019, TICKET-020 | yes |
| `part5/cli.py`, `part5/__main__.py` | TICKET-009, TICKET-010, TICKET-015 | yes |
| `part5/guard.py` | TICKET-015 | yes |
| `part5/joints_map.py` | TICKET-019 | yes |
| `part5/phrasing/__init__.py`, `template.py`, `local_llm.py`, `muse_spark.py` | TICKET-020 | yes |
| `part5/contract.py`, `part5/doctor.py` | TICKET-009, TICKET-010, TICKET-011 | yes |
| `part5/calibrate.py` | TICKET-015, TICKET-016 | yes |
| `part5/real.py` | TICKET-025, TICKET-026 | yes |
| `part5/reps.py`, `part5/repwise.py` (repetition segmentation and rep-by-rep comparison, ADR-0010) | critical-path J | yes |
| `part5/pipeline.py`, `part5/output.py`, `part5/score.py`, `part5/score_report.py`, `part5/replay.py`, `contracts/analysis.schema.json` (rep fields, 1.3.0) | critical-path J | yes |
| `fixtures/input/real/lateral-raise/*` (trainer and two followers, manifest, SOURCE.md) | critical-path J | yes |
| `tests/test_reps.py` | critical-path J | yes |
| `part5/visibility.py`, `part5/measures.py` (`MEASURE_JOINTS`, `VIEW_MEASURES`), `part5/io.py` (`Clip.conf`), `part5/align.py`, `part5/guard.py`, `part5/pipeline.py`, `part5/repwise.py`, `part5/output.py`, `part5/cli.py`, `contracts/analysis.schema.json` (visibility, `not_enough_visible`) | critical-path J-visible | yes |
| `docs/design/adr/ADR-0011-compare-only-what-the-camera-sees.md` | critical-path J-visible | yes |
| `tests/test_visibility.py`, `tests/test_cli.py`, `tests/test_reps.py` (updated expectations) | critical-path J-visible | yes |
| `tests/local/selfie-salute/*` (the operator's own recording as pose JSON, used with permission for testing, never published) | critical-path J-visible | no (local) |
| `part5/replay.py`, `part5/api.py`, `part5/server.py` | TICKET-006, TICKET-021, TICKET-022 | yes |
| `web/index.html`, `web/app.js`, `web/api.js`, `web/viewer.js`, `web/joints.js`, `web/preview.js`, `web/style.css`, `web/icon.svg` | TICKET-007, TICKET-021 to TICKET-023 | yes |
| `web/vendor/three/*` (three.js r170, unchanged) | TICKET-021 | yes |
| `web/vendor/README.md` (npm `three@0.170.0`, sha256 per vendored file) | TICKET-021 | yes |
| `contracts/analysis.schema.json`, `input-animation.schema.json`, `input-skeleton.schema.json`, `labels.schema.json`, `metrics.schema.json` | TICKET-009 | yes |
| (`metrics.schema.json` describes the `make check-5` document, format `simon.part5.check.v1`, which wraps per-slice `simon.part5.metrics.v1` numbers) | TICKET-009, TICKET-018 | yes |
| `scripts/make_dummy_followers.py` (knee caving, dropout variant, `--out`) | TICKET-014, TICKET-017 | yes (upstream-owned) |
| `scripts/sync_contracts.py` (from #34, plain errors) | TICKET-004 | yes (upstream-owned) |
| `docs/schemas.md`, `docs/thresholds.md`, `CONTRACT.md`, `README.md` | TICKET-009, TICKET-018, TICKET-027 | yes |
| `scripts/dev.sh`, `scripts/neighbour-check.sh` | TICKET-006, TICKET-012 | no (firm) |
| `scripts/import-stock-takes.sh` (Part 2 stock `pose3d.json` at its IECB commit through Part 3 `--view part5`, temp clones) | TICKET-026 | no (firm) |
| `qa/recipes/*` (QA recipes, ADR-0020) | TICKET-024 | no (firm) |
| `scripts/oneshot-launch.sh`, `scripts/oneshot-watch.sh`, `tests/test-oneshot-watch.sh` (`docs/design/specs/oneshot-watch.md`) | setup | no (firm) |
| `part5/phrasing/smoke.py` (`make smoke-muse-spark`) | TICKET-020 | yes |
| `staging/up.sh`, `down.sh`, `health.sh`, `env.sh`, `verify.sh`, `verify.mjs`, `walkthrough.mjs`, `DEMO.md` | TICKET-008, TICKET-024 | no (firm) |
| Tests: `tests/test_*.py` per module above | with each ticket | yes |

## Delivery Verification Plan
- `make test` 0; `make check-5` 0 (held-out gate); `make check-5-contract` 0; `make report-real` 0.
- `staging.sh up simon-part-5` 0 and `staging.sh verify simon-part-5` 0 (S0, M3).
- QA recipes driven through the real UI with two witnesses and a negative assertion (ADR-0020).
- `scripts/neighbour-check.sh` result recorded (red is reported).
- One consolidated review, `/delivery-review` PASS, `scripts/check-delivery-ready.sh` 0,
  the maintainers' use-case check.
- Publish, then a fresh clone of upstream: `make check-5` 0 and `make test` 0.

### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|---|---|---|---|
| Desktop Chromium | Playwright 1.61.1 (`staging/verify.mjs`) | 1440 | viewer lane |
| Phone width | Playwright 1.61.1 | 390 | viewer lane |

### Data
Synthetic takes and real-take fixtures only, picked through the UI; uploads use committed fixtures.

### Ratchet Initialization Plan
End of M1: `scripts/ratchet-update.sh`; the M1 close-out checks `progress/ratchets.json` floors.

## Dissent Review
### Concern 1: the guard can refuse a real follower who is slow and sloppy
A slow, faulty take raises the residual. Kept: the limit is set so every matched tuning take passes,
including low light and double faults, and refusals on held-out are counted, not hidden.
### Concern 2: a new seed from the same generator is not independent data
True: it shares the generator's fault model. Kept: it is the honest step available before filming; the
real-take report is the counterweight, and the limit is stated in `check-5` output (`data_source`).

## Deviations from PRD
None. Scope additions are the operator's 2026-10-28 decisions (ADR-0002 to ADR-0006).
