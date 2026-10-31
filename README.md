# Simon Part 5: compare 3D animations and analyse faults


Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
This repo is **only** Simon Part 5. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way: that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #59. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 5).

## Input

The expected `animation.json` (or `skeleton.json`) plus a follower's `skeleton.json`. Fixtures in `fixtures/input/`. What Part 5 accepts, and from which part, is in `CONTRACT.md`.

## Output

`analysis.json`. Per fault: what differed, which joint/body part, the size of the difference, and a plain-words line (e.g. "left foot too far out", "elbows wider than the example"). A take of a different movement is still analysed: it carries a `low_match` warning and its grade is capped at F (ADR-0012). Fields: `docs/schemas.md`; schema: `contracts/analysis.schema.json`.

## Shared-file context (only what this part touches)

Canonical 17 joints (subject's left/right): nose, left_eye, right_eye, left_ear, right_ear, left_shoulder, right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee, right_knee, left_ankle, right_ankle. Coordinate frame: origin at the hip midpoint per frame; x = subject's left (horizontal), y = world up, z = anterior (x × y); metres and degrees. Measurements are joint angles and segment directions between corresponding joints in the two skeletons, compared at the same phase of the movement.

## Frontier model

none (rule maths is the measurement; plain-words analysis from the measurements)

## Definition of done

On labelled follower clips (correct and deliberate-fault takes, several angles): fault precision ≥0.85 and recall ≥0.75 in good light, every other angle reported separately; on correct takes it reports no faults.

Done-check: `make check-5` prints a metrics JSON and exits 0 only when every threshold passes. It gates good light at front, 45 and side on a held-out set (`fixtures/input/heldout/`, whose `labels.json` names the seed); the thresholds are tuned on the seed 5 set only, and every held-out attempt is recorded in `docs/thresholds.md` and `fixtures/heldout-attempts.json`.

## Demos

- **Isolated:** A follower clip replayed with each fault listed and the joint highlighted (`make demo`, http://127.0.0.1:8735/).
- **Integrated:** In Part 7, this analysis is what the follower is shown after a take.

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-5`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.

## Dev setup

```bash
uv sync                # Python ≥3.10 + numpy; pytest and jsonschema for the tests
make test              # unit tests
make check-5           # done-check
```

| Command | What it does | Exit |
|---|---|---|
| `make check-5` | Analyses every labelled take and prints the `simon.part5.check.v1` metrics JSON on stdout, a summary on stderr. Gates the held-out good-light slices; reports seed 5, low light, dropout and real takes. Runs the `fitness` profile only and prints `profiles_sha256` (the hash of `part5/profiles.json`) for information. | 0 gate passed, 1 gate failed, 2 a take or set is missing, `part5/profiles.json` is missing, the held-out seed has no freeze record, `rules.json` differs from the frozen hash, the `score` params in `rules.json` differ from the hash frozen in `fixtures/score-heldout.json`, or a scored seed scores differently from its recorded attempt |
| `make test` | Unit tests. | 0 |
| `make check-5-contract` | Validates every schema and committed fixture, and rebuilds the shipped `fixtures/output/analysis*.json` byte for byte. | 0 |
| `make report-real` | Real takes, reported and never gated: Part 3's kit against Part 4's `part3-squat`, and Part 2's takes. Writes `out/report-real/report.json`. | 0 when every real take was analysed |
| `make report-profiles` | Per-profile precision, recall and grades on the seed 5 tuning set (`dance`, `rehab`, `fitness`), reported as measured and never gated; a held-out set is refused (exit 2). Writes `out/report-profiles/report.json`. | 0 |
| `make demo` | The replay page on http://127.0.0.1:8735/ (foreground). | |
| `make dummy-data` | Regenerates the seed 5 set in `fixtures/input/followers/`. | 0 |
| `make heldout-data SEED=<n>` | Writes a held-out set to `fixtures/input/heldout/`. Only seeds 29, 31 and 37, each once, under the protocol in `docs/thresholds.md`. | 0; 2 without a held-out seed |
| `make output-examples` | Rewrites the two shipped `fixtures/output/analysis*.json`. | 0 |
| `make smoke-muse-spark` | One live Muse Spark call through Baseten (needs the key file). Never part of `make test` or `make check-5`. | 0 when a valid line came back |
| `make test-contract` | Part 3 and Part 4 files through `part5.io` (`CONTRACT.md`). | 0 |
| `make contracts-check`, `make contracts-sync` | Compare, or refresh, the copies under `contracts/` with Parts 3 and 4. | 0; 1 on drift, 2 when an upstream cannot be read |

```bash
uv run part5 analyse --expected fixtures/input/expected/exercise/animation.json \
  --follower fixtures/input/followers/exercise/<take_id>/skeleton.json --out out/analysis.json \
  [--phrasing template|local-llm|muse-spark] [--profile dance|rehab|fitness] \
  [--expected-feet pose3d.json --follower-feet pose3d.json]
uv run python -m part5 contract [--schema <name>] [--json]       # schemas and compatibility table
uv run python -m part5 doctor <file> [--for part5|part7] [--json] # is this file accepted, and the fix
uv run python -m part5 serve [--port 8725] [--base-path /]       # the web page and the analysis API
uv run python -m part5 report-real [--out out/report-real/report.json]
```

`part5 analyse` exits 0 when it wrote an analysis (with or without `warnings`), 1 for an input or write error and 2 for a usage error; exit 3 is no longer used (ADR-0012). `--phrasing` changes only each fault's `coaching` line and the `phrasing` record, never a scored field; `template` is the default. `muse-spark` sends only the measured fault record, and only when the key file named by `PART5_BASETEN_KEY_FILE` exists and live mode is on (`--live`, `SIMON5_LIVE=1` or `META_LIVE=1`); otherwise the template line is kept and the reason recorded.

## Develop and debug

- [`docs/dev/DEVELOPING.md`](docs/dev/DEVELOPING.md): setup from a fresh clone, keys, commands, the done-checks, debugging the output fields, tests, how Part 7 calls this part, known issues.
- [`docs/design/README.md`](docs/design/README.md): the design specs and architecture decision records behind the code.

Work is coordinated in GitHub issues: checklist #17, team chat #18.
