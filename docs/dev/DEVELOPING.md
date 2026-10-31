# Developing Part 5

How to set up, run, check, test and debug Simon Part 5 (fault analysis) from a fresh clone on any
host. Field rules are in `docs/schemas.md`, who sends what in `CONTRACT.md`, the threshold protocol in
`docs/thresholds.md`, and the design history in `docs/design/README.md`.

## Setup from a fresh clone

Prerequisites:

- Python 3.10 or later (`pyproject.toml`).
- [uv](https://docs.astral.sh/uv/). Every Makefile target runs through `uv run`.
- `make`, `git`.
- No GPU, no network and no key for analysis, the checks or the tests. A network is needed only for
  `make contracts-check` and `make contracts-sync` without local checkouts, and for live phrasing.

```bash
git clone https://github.com/moalborati/simon-part-5-fault-analysis.git
cd simon-part-5-fault-analysis
uv sync              # numpy, plus pytest and jsonschema from the dev group
make test            # unit tests
make check-5         # the done-check
```

Runtime dependency: `numpy` only. `jsonschema` is a dev dependency; `part5 doctor` uses it when it is
installed and says which validators ran.

## Keys

Part 5 needs no key for anything except live phrasing through Muse Spark.

| Name | Read by Part 5 | How |
|---|---|---|
| `BASETEN_API_KEY` | yes, only for `--phrasing muse-spark` | From a file, never from an environment variable of that name. `PART5_BASETEN_KEY_FILE` names the file; without it the code uses its built-in default (`KEY_FILE` in `part5/phrasing/muse_spark.py`). The file is read at each call, stripped, and used only for the `Authorization` header. |
| `MODEL_API_KEY` | no | Not read anywhere in `part5/`. |
| `HF_TOKEN` | no | Not read anywhere in `part5/`. Part 5 downloads no model. |

A live call needs the key file and live mode: `--live` on `analyse` or `serve`, or `SIMON5_LIVE=1`, or
`META_LIVE=1`. Without either, the template line is kept and `phrasing.fallback_reason` says why.

Other environment variables the code reads:

| Variable | Default | Effect |
|---|---|---|
| `PART5_BASETEN_USAGE_FILE` | `~/.simon/baseten_usage.jsonl` | usage ledger, one line per Muse Spark call (token counts, model, UTC time, HTTP status; never the key or the text) |
| `PART5_MUSE_PER_MINUTE` | 30 | Muse Spark calls per process per minute |
| `PART5_PHRASING_BUDGET_S` | 20 | seconds one analysis may spend on phrasing |
| `PART5_PHRASING_CONCURRENCY` | 4 | model calls in flight at once |
| `PART5_OLLAMA_MODEL` | unset | model name for `--phrasing local-llm` (needs `ollama` on `PATH`, served on `127.0.0.1:11434`) |
| `PART3_DIR`, `PART4_DIR` | unset | local checkouts for `make contracts-check` and `make contracts-sync`; otherwise the repos are cloned from GitHub |

## Commands

```bash
# Analyse one take. Exit 0: analysis written. 1: an input or the output breaks the contract. 2: usage.
uv run part5 analyse \
  --expected fixtures/input/expected/exercise/animation.json \
  --follower fixtures/input/followers/exercise/exercise_45_good_02_arms_wider-left/skeleton.json \
  --out out/analysis.json --replay out/replay.json
# prints: out/analysis.json: 1 fault
#           - left arm too far out

# Options of analyse
#   --replay <file>               also write the replay (simon.replay.v1)
#   --expected-visibility <file>  the trainer's own skeleton.json or pose3d.json, whose conf says what the example shows
#   --phrasing template|local-llm|muse-spark   who writes faults[].coaching (default template)
#   --live                        live mode: muse-spark becomes the default phrasing

uv run python -m part5 doctor <file> [--for part5|part7] [--json]   # 0 accepted, 1 rejected, 2 unreadable
uv run python -m part5 contract [--schema <name>] [--json]           # schemas and the compatibility table
uv run python -m part5 report-real [--out <file>]                    # real takes, reported, never gated
uv run python -m part5 serve [--host 127.0.0.1] [--port 8725] [--base-path /] [--live]
uv run python -m part5.score_report --set <dir with labels.json> [--json]   # grade distribution of a set
```

`part5` and `python -m part5` are the same entry point (`part5/cli.py`). `make demo` serves the replay
page on `http://127.0.0.1:8735/` in the foreground.

The pipeline for one take (`part5/pipeline.py`): load, normalise, align (DTW on joint measures), guard,
measures, detect, words, then score (`part5/score.py`) and phrasing (`part5/phrasing/`).

## Done-checks

| Target | What it runs | What it gates | Exit |
|---|---|---|---|
| `make check-5` | `python -m part5.check`: analyses every labelled take, prints the `simon.part5.check.v1` JSON on stdout and a summary on stderr | the held-out set in `fixtures/input/heldout/`: good light at front, 45 and side, each with precision 0.85 or more, recall 0.75 or more and no faults on correct takes; every correct good-light held-out take scores A; the score never rises as a swept fault grows. Seed 5, low light, dropout, Part 3's kit and the stock takes are reported, not gated | 0 passed; 1 a gated criterion failed; 2 a take or set is missing, a take cannot be analysed, the held-out seed has no freeze record, or `part5/rules.json` differs from the hash frozen in `docs/thresholds.md` |
| `make check-5-contract` | `python -m part5.contract --check` | every schema in `contracts/` is valid, every committed fixture validates and loads through `part5.io`, and `fixtures/output/analysis*.json` rebuild byte for byte | 0 only with no failures; prints `{schemas, validated, rebuilt_identical, failures}` |
| `make report-real` | `python -m part5 report-real` | nothing: Part 3's labelled kit against `part3-squat`, Part 2's mismatch takes, the real lateral-raise takes and any stock takes, written to `out/report-real/report.json` | 0 when every real take was analysed; 2 when a set cannot be read or the report cannot be written |
| `make test` | `uv run pytest -q` | the unit tests | pytest's exit code |
| `make test-contract` | `pytest tests/test_contract.py` | Part 3 and Part 4 files load through `part5.io` and match their schemas | pytest's exit code |
| `make contracts-check` | `scripts/sync_contracts.py --check` | the copies under `contracts/part3/`, `contracts/part4/` and `fixtures/input/contract/` match Parts 3 and 4 | 0 equal; 1 drift; 2 an upstream cannot be read |

Generators: `make dummy-data` rebuilds the seed 5 set, `make output-examples` rewrites the shipped
`fixtures/output/analysis*.json`, `make heldout-data SEED=29|31|37` writes a held-out set (once per seed,
under the protocol in `docs/thresholds.md`). `make smoke-muse-spark` makes one live call; it is never
part of `make test` or `make check-5`.

## The output, field by field, for debugging

`analysis.json` is `simon.analysis.v1`. `schema_version` tells you which additions to expect: `1.2.0` for
an ordinary take, `1.3.0` when the take was compared one repetition at a time, `1.4.0` when it carries a
warning. From `1.5.0` (ADR-0014) every new document is `1.5.0` and carries cues, tempo and `insights`; the
earlier groups are told apart by their fields.

### Always analyse: `warnings`, `match`, the F cap

Since ADR-0012 a readable pair of inputs is always analysed and `analyse` exits 0. What used to be a
refusal is a top-level warning:

| `warnings[].code` | Meaning | What to check |
|---|---|---|
| `low_match` | the movement guard would have refused: `match.residual` above `limits.max_residual`, or `match.timing_corr` below `limits.min_timing_corr` | the right expected clip, the whole movement in the take, a very different tempo or rep count |
| `moving_part_out_of_frame` | the body part the example moves is not usable in the take | `diagnostics.visibility.moving_measures` against `moving_usable` |
| `not_enough_visible` | fewer than 3 measures are usable in both clips | `diagnostics.visibility.excluded` |
| `no_usable_measures` | nothing could carry timing, or most of the body could not be measured: no faults, score 0 | the follower's joints and `conf` |

Any warning caps `score.value` at 59 (grade F) and `score.capped_by` names the codes. On `low_match` each
fault carries `confidence: "low"` instead of a number. The limits live under `guard` in
`part5/rules.json` (`max_residual` 0.5677, `min_timing_corr` 0.8336).

`diagnostics.warnings` is a separate list of plain sentences, printed by the CLI as
`part5 analyse: warning: ...`. Today it holds one check: less than 60% of the follower clip matched the
movement. That is harmless for idle lead-in and tail, and a hint when the follower is much slower or
repeats the movement.

### The guard numbers

`diagnostics.guard`: `residual` (mean capped z cost per alignment path cell), `timing_corr` (median
Pearson correlation of the expected and matched follower series over the measures that carry timing),
`span_share` (matched share of follower frames; it only ever warns) and `limits`.

### Repetitions

When the whole-clip guard would refuse and either clip holds more than one repetition, the take is
compared one repetition at a time (`part5/reps.py`, `part5/repwise.py`). Then:

- `diagnostics.expected_reference`: `kind` (`first_rep` or `whole`), `frames`, `span_s`, `expected_reps`,
  `follower_reps` and the `measure` the cuts were taken on;
- `diagnostics.guard.reps`: per follower rep, `span_s`, `residual`, `timing_corr` (null when the rep could
  not be aligned) and `ok`; the top-level `residual` and `timing_corr` are medians over the reps;
- `faults[].reps`: the 0-based reps a fault was found in; a fault counts when found in at least half of
  the accepted reps, and the take is accepted when a strict majority of reps pass;
- `score.per_rep`: each accepted rep's `value` and `grade`.

Worked example on the committed real takes (8 fast reps against a trainer's 3):

```bash
R=fixtures/input/real/lateral-raise
uv run part5 analyse --expected $R/pexels-5319084/animation.json \
  --follower $R/pexels-40297504/animation.json --out out/rep.json
```

It writes schema `1.3.0`, `expected_reference.kind` `first_rep`, `expected_reps` 3, `follower_reps` 8,
eight `score.per_rep` entries and no faults.

### Visibility

`diagnostics.visibility` appears only when the take was compared on fewer than all measures:
`usable_measures` (a count), `excluded`, `rule`, `moving_measures` and `moving_usable`. A joint is unseen
in a frame when its `conf` is exactly 0.3 (Part 2's mark for a joint placed outside the image), and so
is its left or right counterpart. A measure is usable when all its joints are seen in at least 80% of
the clip's frames. A clip without any `conf` takes the other clip's usable set. Pass
`--expected-visibility` with the trainer's own skeleton when the expected clip (Part 4's animation)
carries no `conf`.

### Time, direction and phrasing per fault

- `follower_t_s`: start and end on the follower file's own clock; `at_s` is the start rounded to 0.1 s;
  `follower_runs` maps every counted run to follower frames.
- `lateral`: `left`, `right` or null in the subject's frame; `lateral_m` on one-sided `foot_out` faults.
- `text` (the plain line), `text_timed` (with ` at <t> s`) and `coaching` (the displayed line).
- `phrasing`: `requested`, `backend`, `model`, `fallback_reason`, `selected_by` and one record per fault.
  A model line that fails the word test (`part5.phrasing.template.line_problem`), a timeout, an HTTP
  error, the rate limit or the time budget falls back to `text_timed` for that fault, and the record
  says why. Phrasing never changes a scored field.

### Score

`score` is `simon.score.v1`: `value` 0 to 100, `grade` A (90+), B, C, D, F (below 60), `components`
(`faults`, `similarity`) and `params_sha256` of the `score` block in `part5/rules.json`. The formula is
at the top of `part5/score.py`.

### Replay

`--replay` writes `simon.replay.v1` (`contracts/replay.schema.json`): both normalised skeletons,
`expected_t`, `follower_t` and `exp_to_fol`, the follower frame shown at each expected frame. A take that
could not be aligned plays on a straight-line stand-in alignment.

## Common failures

| Symptom | Cause and fix |
|---|---|
| `part5 analyse: <file>: cannot read JSON` and exit 1 | a missing or malformed input path |
| exit 1 with a field named | the clip breaks the input contract; run `python -m part5 doctor <file>` for the fix |
| `doctor` says `simon.skeleton/1 (Part 3 native)` | rerun Part 3 with `--view part5` |
| `doctor` says Part 2 `pose3d.json` | Part 5 never reads it; run Part 3 `--view part5` on it |
| `make check-5` exits 2 naming `rules.json` | `part5/rules.json` changed after the freeze. Thresholds are tuned on seed 5 only; a change needs a new held-out attempt under `docs/thresholds.md` |
| `make check-5-contract` fails on `rebuilt_identical` | a pipeline change moved the goldens: run `make output-examples`, review the diff, commit it |
| `make contracts-check` exits 1 | Part 3 or Part 4 changed a copied file; run `make contracts-sync` and review |
| a correct take graded F with `low_match` | read `match` and `diagnostics.guard`; check the expected clip and the rep count |
| `coaching` equals `text_timed` in live mode | read `phrasing.fallback_reason` (no key, live calls off, rate limited, time budget spent, or the word test) |

## Tests

`make test` runs pytest over `tests/` (`tests/test_*.py`, with `tests/conftest.py` and `tests/fixtures/`).
The tests are offline: the Muse Spark and local LLM tests use stub clients, and every test forces the
`template` backend whatever the environment. One file covers each module (`test_pipeline_run.py`,
`test_guard.py`, `test_reps.py`, `test_visibility.py`, `test_score.py`, `test_replay.py`,
`test_time_fields.py`, `test_phrasing*.py`, `test_api.py`, `test_server.py` and the rest).

Run one file or one test: `uv run pytest -q tests/test_guard.py -k low_match`.

## Contract and how Part 7 calls this part

`CONTRACT.md` is the contract: what Part 5 accepts (Part 4's `animation.json`, Part 3's `--view part5`
and `--view part4` skeletons), what it writes, and Part 7's duties (read `warnings` and `score`, treat exit
0 as written, highlight `faults[].joints`, ignore unknown fields, show `coaching` when present). The
schemas are in `contracts/`; copies of Parts 3 and 4 live under `contracts/part3/` and `contracts/part4/`
and change only through `make contracts-sync`.

Part 7 pins this repo by commit and runs it from its own checkout, with that checkout as the working
directory:

1. `uv run python -m part5 contract` at setup;
2. `uv run python -m part5 doctor <file> --for part5` on the trainer's `animation.json` and on the
   follower skeleton (Part 3 `--view part5 --fps 30`);
3. `uv run python -m part5 analyse --expected <animation.json> --follower <skeleton.json>
   --out <work>/analysis.json --replay <work>/replay.json [--expected-visibility <trainer skeleton.json>]
   --phrasing template` (or `--phrasing muse-spark --live` for live phrasing), with
   `PART5_PHRASING_CONCURRENCY=4`.

Part 7 reads `--help` to find which of `--replay`, `--expected-visibility` and `--live` the pinned commit
offers, so keep those flag names stable.

## Known issues and limits

- The thresholds are tuned and gated on synthetic takes (`scripts/make_dummy_followers.py`). Real takes
  are reported by `make report-real`, never gated.
- The two stock takes in `fixtures/input/eval/real/` are labelled by eye (`label_source: visual`), so
  their precision and recall are indicative only.
- `part5 doctor` does not recognise `simon.replay.v1` yet: it rejects a replay file as unknown, although
  `docs/design/specs/journey-followup.md` (J-6) asks for it.
- `make score-heldout`, described in the same spec, is not in the Makefile; run the generator and
  `python -m part5.score_report --set <dir>` by hand.
- The earlier sections of `docs/schemas.md` still describe refusals and exit 3; the last section
  ("Always analysed") supersedes them.
- Live phrasing makes paid calls through Baseten and needs the key file on the host that runs the
  analysis or the server.
- Part 5 never fetches a URL. A Part 6 hand-off has to be downloaded first and its `files.animation`
  passed as `--expected`.
