# Developing Part 5

How to set up, run, check, test and debug Simon Part 5 (fault analysis) from a fresh clone on any
host. Field rules are in `docs/schemas.md`, who sends what in `CONTRACT.md`, the threshold protocol in
`docs/thresholds.md`, and the design history in `docs/design/README.md` (copies of the working specs and ADRs,
regenerated from their sources by `scripts/make_design_copies.py`, never edited by hand).

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
| `MODEL_API_KEY` | yes, only for the second opinion (`--expected-video` and `--follower-video` in live mode) | From a file, never from an environment variable of that name. `PART5_META_KEY_FILE` names the file; without it the code uses its built-in default (`KEY_FILE` in `part5/opinion/meta_api.py`). Read at each call, stripped, used only for the `Authorization` header. |
| `HF_TOKEN` | no | Not read anywhere in `part5/`. Part 5 downloads no model. |

A live call needs the key file and live mode: `--live` on `analyse` or `serve`, or `SIMON5_LIVE=1`, or
`META_LIVE=1`. Without either, the template line is kept and `phrasing.fallback_reason` says why.

Other environment variables the code reads:

| Variable | Default | Effect |
|---|---|---|
| `PART5_BASETEN_USAGE_FILE` | `~/.simon/baseten_usage.jsonl` | usage ledger, one line per Muse Spark call (token counts, model, UTC time, HTTP status; never the key or the text) |
| `PART5_MUSE_PER_MINUTE` | 30 | Muse Spark calls per process per minute |
| `PART5_META_KEY_FILE` | `~/.config/firm/operator-keys/MODEL_API_KEY` | the key file of the second opinion (Meta Model API, `--expected-video` with `--follower-video` in live mode); read at the call, stripped, used for the `Authorization` header only. Tests point it at a path that does not exist |
| `PART5_META_USAGE_FILE` | `~/.simon/meta_usage.jsonl` | ledger of the second opinion, one line per call (model, UTC time, HTTP status, tokens, USD; never the key or the text). It is opened and locked before the call and held until the call is recorded, so two processes cannot both pass the cap. A call that failed with no answer from the API (a timeout, a connection error) is recorded at its pre-call estimate with `estimated: true` |
| `PART5_META_SPEND_CAP_USD` | 5.00 | total USD the ledger may reach; checked before the clips are uploaded and again, with the call's estimate, before the call. A value that is not a finite number of 0 or more keeps the default and logs a warning |
| `PART5_META_CALL_MAX_USD` | 0.50 | USD one call may be estimated at (the counted input plus the full output allowance, at Part 1's list rates); same rule for a bad value |
| `PART5_PHRASING_BUDGET_S` | 20 | seconds one analysis may spend on phrasing |
| `PART5_PHRASING_CONCURRENCY` | 4 | model calls in flight at once |
| `PART5_OLLAMA_MODEL` | unset | model name for `--phrasing local-llm` (needs `ollama` on `PATH`, served on `127.0.0.1:11434`) |
| `PART5_LOCAL_LLM_TIMEOUT_S` | unset (10 s, the phrasing default) | per-call timeout of `--phrasing local-llm` in seconds, for a slow model such as `muse-glimmer:30b`; a value that is not a positive number keeps the default and logs a warning. A call starts only while the time spent plus this timeout fits in `PART5_PHRASING_BUDGET_S`, so raise that too (for example 60 and 300) |
| `PART5_LOCAL_LLM_THINK` | unset (the model's own behaviour) | `0` or `false` sends `reasoning_effort: "none"` and `think: false` with each `--phrasing local-llm` request, so a thinking model answers without a reasoning pass (Ollama's `/v1` endpoint honours the first and ignores the second); unset or `true` sends neither |
| `PART5_LOCAL_LLM_MAX_TOKENS` | 2048 | completion allowance of `--phrasing local-llm` (a positive whole number; any other value keeps 2048 and logs a warning). A thinking model reasons first: `muse-glimmer:30b` uses about 935 tokens on the timed prompt. An answer cut off at the allowance with no content falls back with `local-llm: cut off at max_tokens` |
| `PART3_DIR`, `PART4_DIR` | unset | local checkouts for `make contracts-check` and `make contracts-sync`; otherwise the repos are cloned from GitHub |

The system message of `--phrasing local-llm` (and only that backend's) ends with grammar rules, `local_llm.grammar`: name
the body part once, and for a timed fault write a sentence with a verb ("is" after one part, "are" after two or more).
Muse Glimmer 30B had written "Arms elbows wider than the example at 0.4 s", the record's group word laid in front of the
part the words name. The word test, for every backend, also rejects two body-part nouns side by side
(`doubles the body part (arms elbows)`), so such a line falls back to its template line
(`docs/specs/second-opinion.md`, AC-VA-04 and AC-VA-05).

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
#   --profile dance|rehab|fitness  how picky the take is judged (default fitness, the analysis as it was)
#   --expected-feet / --follower-feet <pose3d.json>   Part 2's heel and toe points, for the two foot measures
#   --expected-feet-person / --follower-feet-person N the people[].id to read in those files (default 0)
#   --live                        live mode: muse-spark becomes the default phrasing

uv run python -m part5 doctor <file> [--for part5|part7] [--json]   # 0 accepted, 1 rejected, 2 unreadable
#   a clip, an analysis.json (--for part7) or a replay.json (simon.replay.v1, either --for)
uv run python -m part5 contract [--schema <name>] [--json]           # schemas and the compatibility table
uv run python -m part5 report-real [--out <file>]                    # real takes, reported, never gated
uv run python -m part5.profiles_report [--json-out <file>]           # dance, rehab, fitness on seed 5 (make report-profiles)
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
| `make check-5` | `python -m part5.check`: analyses every labelled take under the `fitness` profile, prints the `simon.part5.check.v1` JSON (with `profiles_sha256`, for information) on stdout and a summary on stderr | the held-out set in `fixtures/input/heldout/`: good light at front, 45 and side, each with precision 0.85 or more, recall 0.75 or more and no faults on correct takes; every correct good-light held-out take scores A; the score never rises as a swept fault grows. Seed 5, low light, dropout, Part 3's kit and the stock takes are reported, not gated | 0 passed; 1 a gated criterion failed; 2 a take or set is missing, a take cannot be analysed, `part5/profiles.json` is missing, the held-out seed has no freeze record, or `part5/rules.json` differs from the hash frozen in `docs/thresholds.md` |
| `make check-5-contract` | `python -m part5.contract --check` | every schema in `contracts/` is valid, every committed fixture validates and loads through `part5.io` (a replay is checked for lengths, indexes and times), and `fixtures/output/analysis*.json` and `replay.example.json` rebuild byte for byte, the score included | 0 only with no failures; prints `{schemas, validated, rebuilt_identical, failures}` |
| `make report-real` | `python -m part5 report-real` | nothing: Part 3's labelled kit against `part3-squat`, Part 2's mismatch takes, the real lateral-raise takes and any stock takes, written to `out/report-real/report.json` | 0 when every real take was analysed; 2 when a set cannot be read or the report cannot be written |
| `make report-profiles` | `python -m part5.profiles_report --json-out out/report-profiles/report.json` | nothing: `dance`, `rehab` and `fitness` on the seed 5 tuning set, precision, recall and grades as measured; a held-out set is refused | 0; 2 for a held-out set or a set that cannot be read |
| `make test` | `uv run pytest -q` | the unit tests | pytest's exit code |
| `make test-contract` | `pytest tests/test_contract.py` | Part 3 and Part 4 files load through `part5.io` and match their schemas | pytest's exit code |
| `make contracts-check` | `scripts/sync_contracts.py --check` | the copies under `contracts/part3/`, `contracts/part4/` and `fixtures/input/contract/` match Parts 3 and 4 | 0 equal; 1 drift; 2 an upstream cannot be read |

Generators: `make dummy-data` rebuilds the seed 5 set, `make output-examples` rewrites the shipped
`fixtures/output/analysis*.json` and `replay.example.json` (through the path `part5 analyse` uses, with the score
hook and the `template` phrasing forced), `make heldout-data SEED=29|31|37` writes a held-out set (once per seed,
under the protocol in `docs/thresholds.md`). `make score-heldout SEED=<n>` generates a set under
`out/score-heldout/seed-<n>/` and prints its score distribution; it refuses (exit 2) a seed already recorded in
`fixtures/score-heldout.json`, since a recorded seed is retired. `make design-copies` rewrites `docs/design/specs/`
and `docs/design/adr/` from `docs/specs/` and `docs/adr/` (`python3 scripts/make_design_copies.py --check` exits 1
when a copy differs). `make smoke-muse-spark` makes one live call; it is never part of `make test` or
`make check-5`.

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

When the whole-clip guard would refuse and either clip holds more than one repetition, or (since attempt 4, ADR-0017) the
expected clip holds two or more whatever the guard says, the take is compared one repetition at a time (`part5/reps.py`,
`part5/repwise.py`; each follower rep against the example rep that matches it, the foot measures included, persistence
judged in the rep: `docs/specs/rep-persistence.md`). Then:

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

Part 7 reads `--help` to find which of `--replay`, `--expected-visibility`, `--live`, `--profile` and the
feet flags the pinned commit offers, so keep those flag names stable.

Two optional inputs change what the call can do:

- **Profiles** (`part5/profiles.json`, `docs/specs/profiles.md`): `--profile dance|rehab|fitness`, or the
  `profile` field of `POST api/analyse`, is the operator's mode. Send nothing for `fitness`, the default and the
  analysis as it always was. `dance` and `rehab` only loosen how picky detection is, so for the same take they report
  no fault `fitness` does not (also take by take in rep mode); their tolerances are set by hand, and a score is
  read within its profile, never compared across profiles. Every document carries `profile`. A name that is not
  one of the three is exit 2 on the command line and HTTP 400 on the API; `GET api/samples` lists the names
  (`profiles`, `profile_default`).
- **Feet** (`--expected-feet`, `--follower-feet`, with `--expected-feet-person` and `--follower-feet-person`
  for the `people[].id`): Part 2's own `pose3d.json`, which alone carries the heel and toe points (Part 3 does not).
  Both clips need one for the foot measures (`foot_rotation`, `ankle_inversion`) to be compared, and a take
  compared rep by rep does not compare them; with either file alone, or none, they are hidden and
  `diagnostics.feet` says why. A file that cannot be read, is nested too
  deeply or is not a Part 2 `pose3d.json` is exit 1 with a plain message.

## Known issues and limits

- The thresholds are tuned and gated on synthetic takes (`scripts/make_dummy_followers.py`). Real takes
  are reported by `make report-real`, never gated.
- The two stock takes in `fixtures/input/eval/real/` are labelled by eye (`label_source: visual`), so
  their precision and recall are indicative only.
- The score is calibrated on synthetic takes (seed 5) and its held-out record (seeds 47 and 53) is synthetic too;
  `docs/thresholds.md` "Score" says what passed and what did not, as measured.
- Live phrasing makes paid calls through Baseten and needs the key file on the host that runs the
  analysis or the server.
- Part 5 never fetches a URL. A Part 6 hand-off has to be downloaded first and its `files.animation`
  passed as `--expected`.
