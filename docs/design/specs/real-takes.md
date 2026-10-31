# Spec: real takes, reported and never gated (Part 3's kit and stock clips through Parts 2 and 3)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADRs: ADR-0003, ADR-0004. Tickets: TICKET-025 (kit),
TICKET-026 (stock). Use case: uc-real-takes. Milestone: M4. Upstream: #12, decision D2 on #18.

## Overview
`make report-real` (`uv run python -m part5 report-real`) analyses every real take and writes one report:
per take, the labels, the faults found, the match against the labels, and the guard status. Two sources:
Part 3's labelled follower kit (15 takes from PR #34, `fixtures/input/contract/part3/followers/`), scored
against Part 4's `part3-squat` output as the expected clip; and openly licensed stock clips (Pexels
licence, accepted by the team on #18): Part 2 (engagement `simon-part-2`) publishes each clip's
`pose3d.json`, Part 5 runs Part 3 `--view part5` on it as a black box, and labels are judged by eye
(`label_source: visual`). The report is never gated;
`make check-5` carries it under `report`.

## Why This Is Wrong (Dissent-First)
1. Visual labels are soft; a "miss" may be a labelling error. Answer: `label_source` is printed per take
   and the numbers are never gated.
2. The stock performer squats with arms forward while the Part 4 squat does not, so a stock follower
   against Part 4's clip manufactures faults (Muse, #18). Answer: stock 5034562 (side) is the expected
   clip for the stock followers.
3. Part 2's stock delivery may be late. Answer: the stock ticket waits for Part 2's IECB message until
   2026-11-01T12:00Z, then uses Part 2's committed outputs and the report says so.

## User Story
As the team, I see Part 5's report on real takes, reported and never gated.

## Fixtures (published)
- `fixtures/input/expected/part3-squat/animation.json`: copy of Part 4 main
  `fixtures/output/part3-squat/animation.json`, commit in `fixtures/input/expected/SOURCE.md`.
- `fixtures/input/eval/real/<take_id>/skeleton.json` and `SOURCE.md`. `SOURCE.md` keeps Part 2's fields
  per clip as Part 2 wrote them (title, licence, page URL, author or "not stated on the page", sha256 of
  the video, `time_range`, `part2_commit`) and adds `part3_commit` (the Part 3 upstream commit that ran
  `--view part5`) and who converted.
- `fixtures/input/eval/real/labels.json` in the #11 label format plus `label_source: "visual"`, the
  labeller (agent) and the expected clip per take. No video in the repo (`*.mp4` is ignored).
- Stock roles: expected Pexels 5034562 (side); followers 5034577 (front) and 8837221 (three-quarter).
- Matched real pairs (scored): Part 3's kit against Part 4's `part3-squat`; stock 5034577 (front) and
  8837221 (three-quarter) against stock 5034562 (side) as the expected clip.
- Mismatch takes (each is analysed against the squat with a `low_match` warning and grade F, exit 0; ADR-0012 replaces the old refusal and exit 3): Part
  2's committed `single` (a seated stretch, not a squat), `class` (cat-cow yoga) and `dance`, each
  through Part 3 `--view part5`.
- Fallback set (no stock message by 2026-11-01T12:00Z): only the kit pairs are scored, the three
  mismatch takes are reported, and `notes` says the stock takes are missing and names Part 2's commit.

## Kit type map (Part 3 kit `type` to Part 5 measure)
| Kit type | Part 5 measure | Direction |
|---|---|---|
| `feet_wide` | `foot_out` | `more` |
| `elbows_out` | `upper_arm_out` | `more` |
| `shallow_squat` | `knee_flexion` | `less` |
| `knee_caving` | `knee_valgus` | `more` |

Kit sides follow the kit label (`both` accepts either side, D4). Extra true faults that ride along (the
`elbow_flexion less` seen with `elbows_out` on #34) are listed as `unlabelled`, not hidden.

## Report JSON (`out/report-real/report.json`, also under `report` in check-5)
```json
{"format": "simon.part5.real_report.v1", "gated": false,
 "takes": [{"take_id": "", "source": "part3-kit|stock|part2-fallback", "expected": "", "follower": "",
            "label_source": "kit|visual", "labels": [], "faults": [], "matched": [], "missed": [],
            "unlabelled": [], "status": "ok|different_movement", "guard": {}}],
 "summary": {"kit": {"tp": 0, "fp": 0, "fn": 0}, "stock": {"tp": 0, "fp": 0, "fn": 0}},
 "notes": []}
```
Zeros show shape only. `notes` says when the stock set is the fallback.

## API / Interface Contract
- `python -m part5 report-real [--out <path>]` (code in `part5/real.py`). Exit 0 when every real take was
  analysed (a take with a warning counts as analysed); 2 when a fixture is missing or malformed (named).
- Stock arrival: right after its M2 (target 2026-10-31), `simon-part-2` publishes
  `fixtures/output/stock/<clip>/pose3d.json` and `SOURCE.md` per clip to its upstream repo and sends an
  IECB message naming the upstream commit. This engagement then:
  1. clones Part 2 upstream into a temp dir and checks out that commit; copies only
     `fixtures/output/stock/<clip>/pose3d.json` and `SOURCE.md` (data, no code);
  2. clones Part 3 upstream into a temp dir and runs `python3 -m part3 run --in <pose3d.json> --out
     <tmp> --view part5` there as a black box; copies the resulting `skeleton.json`;
  3. records `part2_commit` and `part3_commit` in each `SOURCE.md`, labels each follower by eye;
  4. removes both temp dirs with a trap (`find "$d" -delete`, never `rm -rf` on a variable).
  Nothing is taken from Part 2's local workspace; only its published upstream.
- Wait rule: TICKET-026 is `blocked` on that message. At 2026-11-01T12:00Z without it, the fallback set
  applies and is said so; a message that arrives later, before TICKET-028, swaps the stock takes in.

## Acceptance Criteria
### AC-R01: kit scored against part3-squat
Given the 15 kit takes, when reported, then each is analysed against `fixtures/input/expected/part3-squat`
and the summary prints tp, fp, fn per kit type.
### AC-R02: knee caving visible
Given the kit's three `knee_caving` takes, then each entry shows whether `knee_valgus` was found; the
number is reported as measured.
### AC-R03: stock labelled visually, with Part 2's provenance
Given each stock take, `label_source` is `visual` and `SOURCE.md` carries title, licence, page URL,
author (or "not stated on the page"), sha256 of the video, `time_range`, `part2_commit` and
`part3_commit`; `part2_commit` equals the commit named in Part 2's IECB message.
### AC-R04: fallback stated
Given no stock delivery, then `notes` says the fallback set is used and names Part 2's commit.
### AC-R05: never gated
Given every real take missed, `make check-5` still exits on the gate alone.
### AC-R06: mismatch analysed with a warning and grade F
Given Part 2's `single` (seated stretch), `class` (cat-cow yoga) and `dance` takes against the squat,
then each is `ok` with a `low_match` warning and grade F (CLI exit 0), and the report lists them as expected
warnings (`expected_refusals` and `refused_as_expected` keep their names and now count those warnings; ADR-0012).
The words a reader sees say "warned", never "refusal": the verdict of a mismatch take starts "analysed with a warning
and grade F, as expected" (or "NOT warned" when the guard accepted it). Part 2's `single` while it is the
provisional squat is a matched reference, and its row's verdict carries the reason itself, in one sentence: "a
matched reference, not a clip expected to be warned: it is the same movement as the example (provisional barbell back
squat)" (the parenthesis is the start of the manifest's `content`, up to its first comma). The manifest's longer `reason`
stays in the entry (`reason`) and in the `part2:` note. The JSON keys `expected_refusal`, `refused_as_expected` and
`refused` keep their names.
Verified by `tests/test_real.py` (the verdict wording and the keys).

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| Missing skeleton | exit 2 | `report-real: <take_id>: <file> not found` | AC-R01 |
| Label for unknown take | exit 2 | `report-real: labels.json names <take_id>, no such folder` | AC-R03 |

## Edge Cases
- Kit at 15 fps against a 30 fps expected clip: resampled (#37).
- A stock take with two repetitions: the span warning appears in the entry.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | Report | under 1 minute | AC-R01 |
| Legal | Licence | Pexels licence recorded per clip; no video committed | AC-R03 |

## Negative Requirements
- MUST NOT gate on real takes. Why: D3, ADR-0003.
- MUST NOT commit a video or a performer's name in demos. Why: Pexels licence note on #18.
- MUST NOT run or copy Parts 2 or 3's code inside Part 5; conversion is done by their owners or as black
  box tools in temp clones outside the published tree.

## Non-Requirements
- Filming our own takes (#12 human work). Low-light real takes.

## Assumptions
ASM on stock delivery timing and visual labels (`docs/assumptions/`).

## Delivery Verification Plan
- `make report-real` 0; the report JSON recorded as uc-real-takes evidence; the staging Real takes list.

## Dissent Review
### Concern 1: a stock take as expected clip changes the comparison basis between sources
Kept: each entry names its expected clip; the kit and stock summaries are separate.
### Concern 2: an agent labelling by eye
Kept: D2 accepts visual labels; the labeller and method are recorded per take.

## Deviations from PRD
None.

## Real multi-rep takes (ADR-0010)

`fixtures/input/real/lateral-raise/` holds a dumbbell lateral raise trainer (Pexels 5319084, 3 reps) and two
followers (40297504, 8 fast reps; 8836968, 2 slow reps), listed in its `manifest.json` with provenance in its
`SOURCE.md`. `make report-real` analyses both against the trainer, rep by rep, and reports each take, its
per-rep guard numbers (`reps`), the expected reference, its faults as found (unlabelled) and its score under
`summary.reps` and `reps:` notes. Reported, never gated; `make check-5` carries them under `report.stock`.

### AC-R07: the multi-rep words say what was measured, not a verdict
The words a reader sees for the multi-rep group (the `reps:` notes, the `report-real` stderr line and the Real takes
tab sentence, `viewer.md` AC-V09) use "matched", never "passed" or "accepted". The note reads `reps: <take_id>:
<state>, 8 of 8 reps matched the expected clip's first rep, score <n>, <k> fault(s) as found, unlabelled`; the stderr
line reads `report-real: reps 2 real multi-rep takes: 2 of 2 matched the example, 10 of 10 reps matched it rep by rep`;
the tab sentence reads `Multi-rep clips: 2 of 2 matched the example, 10 of 10 repetitions matched it rep by rep.`
The JSON keys `summary.reps.accepted` and `summary.reps.reps_passed` keep their names and values, and the movement
guard behind them is unchanged. Verified by `tests/test_real.py` and `staging/verify.mjs`.
