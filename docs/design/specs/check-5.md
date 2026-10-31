# Spec: `make check-5`, the done-check (held-out gate, reported slices)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADR: ADR-0003. Tickets: TICKET-003 (lands #36), TICKET-018.
Use case: uc-done-check. Milestone: M2.

## Overview
`make check-5` (`uv run python -m part5.check`) analyses every labelled take, scores it with
`part5.evaluate` under the D4 match rule, and prints one metrics JSON on stdout with a short summary on
stderr. It exits 0 only when the gate passes: on the current held-out set (`fixtures/input/heldout/`,
whose `labels.json` names the seed: 29, then 31, then 37 under the protocol in `calibration.md`), each
of `good/front`, `good/45` and `good/side` reaches precision 0.85 or more, recall 0.75 or more, 0 faults on correct
takes, and no gated slice is empty (no takes, no labelled faults or no correct takes, as #36 4ca9a66
already enforces). Everything else is reported and never gated: the seed 5 tuning slices, low light,
the dropout variant, Part 3's kit and the stock takes, plus refusals per slice.

## Why This Is Wrong (Dissent-First)
1. The held-out seeds come from the same generator as seed 5, so a pass still says nothing about filmed takes.
   Answer: `data_source` says so in the JSON, and the real-take report rides in the same document.
2. Printing real-take numbers next to a green gate invites reading them as a pass. Answer: they sit under
   `report`, never under `gate`, and carry `gated: false`.
3. A slow check would be skipped. Answer: under 10 minutes, offline, deterministic.

## User Story
As the team, I run `make check-5` and read precision and recall per angle and lighting on a held-out
set, with good light gated at every angle and the rest reported.

## Metrics JSON (stdout, `contracts/metrics.schema.json`)
```json
{
  "format": "simon.part5.check.v1",
  "data_source": "synthetic: held-out takes (seed from fixtures/input/heldout/labels.json) from scripts/make_dummy_followers.py; thresholds tuned on seed 5 only",
  "gate": {
    "set": "fixtures/input/heldout", "seed": 29,
    "slices": ["good/front", "good/45", "good/side"],
    "thresholds": {"precision": 0.85, "recall": 0.75, "faults_on_correct_takes": 0},
    "passed": true, "failures": [],
    "metrics": {"format": "simon.part5.metrics.v1", "slices": {"good/front": {"tp": 0, "fp": 0, "fn": 0, "takes": 0, "correct_takes": 0, "faults_on_correct_takes": 0, "precision": 0.0, "recall": 0.0, "refused": 0}}}
  },
  "attempts": [
    {"seed": 29, "freeze_commit": "<sha>", "rules_sha256": "<sha256>", "approach": "<family>", "passed": false, "slices": {}}
  ],
  "tuning": {"set": "fixtures/input/followers", "seed": 5, "gated": false, "metrics": {"format": "simon.part5.metrics.v1"}},
  "report": {
    "low_light": {"gated": false, "slices": {}},
    "dropout": {"gated": false, "slices": {}},
    "kit": {"gated": false, "source": "Part 3 conformance kit", "takes": []},
    "stock": {"gated": false, "source": "fixtures/input/eval/real", "takes": []},
    "refusals": {"gated": false, "<slice>": 0},
    "score": {"gated": false, "version": "simon.score.v1"}
  },
  "rules_sha256": "<sha256 of part5/rules.json>"
}
```
The zeros above show shape only. Per-slice numbers keep the `simon.part5.metrics.v1` fields of #13 and
add `refused` (takes analysed with a warning and graded F, ADR-0012; the key keeps its name. Each such take scores its
labels as misses, and a correct take with a warning counts once in `faults_on_correct_takes`). The gated slices use
synthetic matching takes, which carry no warning, so they are unchanged.
`failures` lists one plain sentence per failed criterion, naming the slice and the number. `kit` and
`stock` entries follow `real-takes.md`. `attempts[]` lists every held-out attempt so far in seed order,
pass or fail. Earlier attempts come from `fixtures/heldout-attempts.json` (published, one entry
appended when an attempt is scored, never edited; `docs/thresholds.md` carries the same records); the
current attempt is computed by this run, is the last entry and matches `gate`.

## API / Interface Contract
- `python -m part5.check [--set <dir>] [--json-out <path>]`. Defaults: gate on `fixtures/input/heldout`
  with `gate.seed` read from its `labels.json` (never typed in code), tuning on `fixtures/input/followers`, reports from `fixtures/input/contract/part3/followers` and
  `fixtures/input/eval/real`. Also writes the same JSON to `out/check-5/metrics.json` (gitignored).
- stdout: the JSON only (`indent=2`). stderr: one line per gated slice, one `check-5: score <slice>` line per score
  slice (reported, never gated), then `check-5: PASS` or `check-5: FAIL (<n> criteria)`. A score line for a good-light
  slice ends in how the slice did against its grade target, in words that do not read like a gate result:
  `target met`, `target missed (reported, not gated)` or `target not judged (no takes)`; a slice with no target ends
  in `(reported)`. The words come from `TARGET_WORDS` in `part5/check.py`; the JSON (`report.score.heldout.targets`
  keeps `pass`, `fail` and `no takes`), the gate and every number are unchanged.
- Exit: 0 gate passed; 1 gate failed; 2 a labelled take could not be analysed (named), a set is missing, or
  `rules.json` is not the file frozen for the seed (AC-K07).
- Phrasing is `template` only; no network.

## Acceptance Criteria
### AC-K01: gate passes only when every gated slice passes
Given held-out metrics with one gated slice at precision 0.84, when gated, then exit 1 and `failures`
names that slice and number.
### AC-K02: empty slice fails
Given a gated slice with no takes, no labelled faults or no correct takes, then exit 1 (kept from #36).
### AC-K03: reported slices never gate
Given low light at precision 0.3, dropout at recall 0.5, and a kit take with every label missed, when the
gate is otherwise green, then exit 0.
### AC-K04: warned takes counted
Given a held-out take analysed with a warning and grade F (it was refused before ADR-0012), then its slice's `refused` is 1 and its labels count as
misses. A correct take with a warning is a wrong verdict: it counts once in the slice's `faults_on_correct_takes`,
so a guard that warns on correct takes cannot pass "0 faults on correct takes". Held-out warned takes are always
reported here per slice; a warned take that carries labels lowers recall and is never an AC-005 failure.
### AC-K05: pure stdout
Given a run, stdout parses as one JSON document that validates against `contracts/metrics.schema.json`.
### AC-K06: deterministic
Given two runs on the same tree, stdout is byte-identical.
### AC-K07: names the tuning seed and rules
Given a run, `tuning.seed` is 5, `gate.seed` equals the `seed` in `fixtures/input/heldout/labels.json`
(one of 29, 31, 37), and `detection_sha256` (the hash of `part5/rules.json` without its `score` key) equals the
`detection_sha256` in `docs/thresholds.md`, the detection rules frozen for the attempts (ADR-0007, AC-S06).
`rules_sha256` is the whole file's hash and is reported; it differs from the attempts' `60f2e60b...` since the
`score` block was added after the freeze. When the detection hash does not match, or the seed has no record
there, the check exits 2 instead of scoring. Every line of `docs/thresholds.md` that starts with `rules_sha256:` or
`detection_sha256:` holds a real 64-hex hash (the attempt template in that file is a list, not a copy-and-paste block,
so a search for the recorded hashes prints no placeholder). Verification: `tests/test_check.py`.
### AC-K10: the score params are frozen
Given `part5/rules.json` whose `score` block hashes (`score.params_sha256`) to something other than the
`params_sha256` of the newest attempt in `fixtures/score-heldout.json`, then the check exits 2 before it scores
anything, with `check-5: the score params in part5/rules.json (sha256 <12 hex>) differ from the ones frozen in
fixtures/score-heldout.json (sha256 <12 hex>); the score params are frozen once the held-out score report is
recorded (ADR-0007)`. The detection hash leaves `score` out (AC-K07), so without this a score edit passed unseen.
A missing or empty record exits 2 the same way (`has no frozen score params`). With the committed files the check
passes. Verification: `tests/test_check.py`.
### AC-K09: every attempt reported
Given two scored attempts (one red, one green), then `attempts[]` lists both in seed order with their
numbers and `passed`, and the exit code follows the current attempt only.
### AC-K08: unanalysable take
Given a labelled take whose file is missing, then exit 2 naming the `take_id`.
### AC-K11: a missed score target reads as reported on stderr
Given a held-out set where the good-light one-fault takes miss their grade target, then the `check-5: score good/1`
line ends `target missed (reported, not gated)`, the other good-light lines end `target met` or `target not judged
(no takes)`, the last line is still `check-5: PASS`, the exit is 0 and stdout is unchanged (`targets` reads `fail`).
Verification: `tests/test_check_score.py`.

### AC-K12: every report block carries `gated: false`, `refusals` included (metrics schema 1.2.0)
Given a run, each of the six `report` blocks (`low_light`, `dropout`, `kit`, `stock`, `refusals`, `score`) carries
`gated: false`. `refusals` stays a map of slice to count (`"good/front": 0`) and gains the one key `"gated": false`
beside the slice keys, so a reader of `refusals["<slice>"]` is unaffected; a reader that sums the values of the map
skips the `gated` key. `contracts/metrics.schema.json` `1.2.0` names it (optional, so a `1.1.0` document still
validates). Detection, scoring, the gate and every number are unchanged. Verification: `tests/test_check.py`,
`tests/test_contract_cli.py`.

### Rule-Based ACs
- AC-K-NFR-01: under 10 minutes on this host, offline. Verification: timed run, sockets blocked in test.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| Gated criterion fails | exit 1 | `good/45: precision 0.84 is below 0.85` | AC-K01 |
| Empty gated slice | exit 1 | `good/side: no correct takes, faults on correct takes can't be measured` | AC-K02 |
| Missing take file | exit 2 | `check-5: <take_id>: <file> not found` | AC-K08 |
| Missing set directory | exit 2 | `check-5: <dir> has no labels.json` | AC-K08 |
| No freeze record for the seed | exit 2 | `check-5: docs/thresholds.md has no freeze record (rules_sha256) for seed <n>; ...` | AC-K07 |
| `rules.json` differs from the frozen hash | exit 2 | `check-5: part5/rules.json differs from the hash frozen for seed <n> in docs/thresholds.md; ...` | AC-K07 |
| `score` params differ from the frozen hash | exit 2 | `check-5: the score params in part5/rules.json (sha256 <12 hex>) differ from the ones frozen in fixtures/score-heldout.json (sha256 <12 hex>); ...` | AC-K10 |
| A scored seed scores differently from its recorded attempt | exit 2 | `check-5: seed <n> scores differently from its recorded attempt in fixtures/heldout-attempts.json (<slices>); scoring changed after the freeze, which needs a new attempt on the next seed (docs/design/specs/calibration.md)` | AC-K09 |

## Edge Cases
- Held-out set not generated yet (before TICKET-018): exit 2 naming `make heldout-data SEED=29`.
- `docs/thresholds.md` has no `rules_sha256` for the set's seed, or it differs from the hash of
  `part5/rules.json` now: exit 2 naming the seed, nothing printed on stdout. A seed is scored once,
  against the rules frozen for it (ADR-0003); the freeze record is written before the seed is generated.
- `labels.json` seed not in 29, 31, 37: exit 2 naming the seed.
- A real-take fixture absent (stock not delivered): `stock.takes` is `[]` with `note` saying so.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | Wall clock | under 10 min | AC-K-NFR-01 |
| Reliability | Determinism | byte-identical | AC-K06 |

## Negative Requirements
- MUST NOT gate on seed 5, low light, dropout, kit or stock. Why: D3, ADR-0003.
- MUST NOT tune on held-out numbers, rescore a retired seed or drop an attempt from `attempts[]`.
  Why: ADR-0003.
- MUST NOT print anything but the JSON on stdout. Why: the publish script reads the last JSON line.

## Non-Requirements
- A per-take report in the JSON (it lives in `out/check-5/takes.json`, not in the gate document).

## Assumptions
ASM-002 on held-out seed independence and on D3 thresholds (`docs/assumptions/`).

## Delivery Verification Plan
- `make check-5` exit 0 at the M2 close-out with the JSON recorded in STATUS.md.
- Fresh clone of upstream after publish: `make check-5` exit 0 (TICKET-030).

## Dissent Review
### Concern 1: refusals as misses could hide a guard bug behind a recall drop
Kept: `refused` is printed per slice, so a recall drop caused by refusals is visible.
### Concern 2: one document mixes gate and report
Kept: one command, one JSON is what #14 asked for; `gated: false` marks every report block.

## Amendments
- 2026-10-31 (TICKET-042, `docs/design/specs/profiles.md`): `make check-5` runs the `fitness` profile only (no profile named,
  the rules unchanged) and prints `profiles_sha256`, the hash of `part5/profiles.json`, for information at the end of
  the document; it never reads the profiles file's contents and never calls the per-profile report. A missing
  `part5/profiles.json` is exit 2 (`check-5: part5/profiles.json not found`). The gate, `rules_sha256`,
  `detection_sha256` and the recorded attempts are as they were.

## Deviations from PRD
None.
