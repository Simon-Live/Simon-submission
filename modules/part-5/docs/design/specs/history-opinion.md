# Spec: Muse Spark history opinion over a series of analyses (TICKET-072)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted (merged in the follow-up at c143552 and published upstream in ec67dc1, 2026-11-02; the split into
`part5/history_*.py` modules is open in TICKET-076)
Date: 2026-11-01
Linked PRD: none (the operator's long-context instruction on moalborati/simon#61, 21:03Z and 21:09Z; stakeholder-proxy
ruling 2026-11-01T21:35Z; Part 7 ranks it third after TICKET-070 and TICKET-071)
Linked CRD: none
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. Sibling spec: `second-opinion.md` (the per-take opinion this mirrors, with the
same client, spend guard and ledger). ADRs: ADR-0005 (phrasing registry), ADR-0008 (AI phrasing in live mode).
Tickets: TICKET-072; it reads the allowlist that TICKET-070 writes (`contracts/history-fields.json`). Assumption:
ASM-014 for a translated sentence.

## Overview
Part 5 already gives a per-take second opinion from two clips. This adds a second entry point for a person's history:
`part5 history-opinion <analysis.json> [<analysis.json> ...]` reads a series of `analysis.json` files, takes only the
fields on an allowlist from each, asks Muse Spark 1.3 on the Meta Model API what the series shows, and returns
observations labelled `model_opinion`. There is no video and no upload: one text-only Responses call through the same
client, per-call ceiling, spend cap and ledger as the per-take opinion. Each observation must point at one fault of
one take by take id, second, measure, side and body part. A guard drops any observation that does not, or whose
sentence adds a number, a body part or a side that the cited fault does not hold, and counts what it dropped.
Nothing in `analysis.json` changes, and nothing reads the document back: it is a separate file.

An optional route, `POST api/history-opinion`, does the same for a caller that holds the analyses in memory (Part 7).

## Why This Is Wrong (Dissent-First)
1. **A model asked about a series can invent a trend or a number.** Answer: an observation is grounded by its
   citation, not by its sentence. The five cited values must be one fault of one take in the input; the sentence may
   carry no number at all; the size shown next to it (`evidence`) is copied by code from the cited fault, never taken
   from the model. What the guard cannot check is whether the sentence's claim about the series is true (see
   Compromises). The label `model_opinion` and the count of what was dropped say so.
2. **It sends a person's history to a model.** Answer: only the fields on the allowlist go, each as a short
   identifier or a number, and nothing else: no free text from the analysis (`text`, `coaching`, `cue`, `phrasing`),
   no file path, no clip name, no `second_opinion`. A field that does not have the shape its entry says is left out.
3. **It costs money on every call.** Answer: the same guard as the per-take opinion, with its own ledger purpose: the
   key and live mode are needed, the input is counted before the call, the call is refused above the per-call ceiling
   (default $0.50) or when the ledger total would pass the cap (default $5.00), and every attempted call writes one
   ledger line. The stable text comes first and the question last, so the provider's prompt cache can apply and cached
   input is priced at the cache rate.
4. **"Ordered by time" is not in an analysis.** An `analysis.json` carries no recording date. Answer: the series is
   read in the order given, oldest first, and each take gets a position; a shell glob over file names gives file name
   order. The caller owns the order, and the take id is the name the model must cite.
5. **A free sentence about several takes cannot name one body part.** Answer: one observation is about one fault; it
   cites the take where the fault is clearest and may speak of "the earlier takes" or "the later takes" in words. It
   may name no body part but the cited fault's, and no number or take id.

## User Story
As Part 7, or a coach reading a person's results over many weeks, I want a short second opinion on the series that
points at the takes it is about, so that I can check each observation against the numbers and ignore it if it is wrong.

## Vocabulary
- **Take id**: the name of a take in the series: `--take-id` (one per file, in order), else the file name without
  `.json`, else (a file called `analysis.json`) the name of its folder. It is 1 to 64 ASCII letters, digits, dots,
  underscores, plus signs and hyphens, starting with a letter or digit (the whole string: no trailing newline), and
  is unique in the series.
- **Position**: the take's place in the series, from 1, in the order given.
- **Allowlist**: `prompt.READS`, the paths read from each analysis and whether a list row needs each. The kind of each
  value and the meaning sent to the model are read from `contracts/history-fields.json` (TICKET-070) by
  `prompt.load_allowlist()`, so the model is told what Part 7 is promised. Its version in the document is
  `history-fields-` and the contract's own `version`.
- **Facts**: the allowlisted values of one take, as a small JSON object.
- **Citation**: `{take, at_s, measure, side, body_part}` on an observation.
- **Evidence**: `{direction, magnitude_deg}` copied from the cited fault; keys the fault lacks are left out.

## The command
```
part5 history-opinion <analysis.json> [<analysis.json> ...] [--take-id ID ...] [--lang TAG]
                      [--max-observations N] [--live] [--out FILE]
```
- `--take-id`: given once per file, in file order (or not at all).
- `--lang`: a BCP 47 tag; the sentences are also written in that language (see Language).
- `--max-observations`: 1 to 10, default 5.
- `--live`: live mode, as for `analyse` (`SIMON5_LIVE=1` or `META_LIVE=1` work too).
- `--out`: write the document here (a summary line goes to stdout). Without it the document is printed to stdout and
  the summary goes to stderr.
- Exit code: `0` a document was produced, whatever its `status` (a missing key or a failed call is a `skipped` or
  `fallback` document, as for the per-take opinion); `1` an input or output problem (a file that cannot be read, is
  not JSON, is not an analysis, holds no faults list, is over 16 MiB; more than 40 files; `--out` not writable); `2` a
  usage error (no files, a `--take-id` count that is not the file count, a take id that is not valid or is used twice,
  `--max-observations` out of range).

## The document
```json
{
  "format": "simon.history_opinion.v1",
  "label": "model_opinion",
  "status": "ok",
  "reason": null,
  "backend": "meta-model-api",
  "model": "muse-spark-1.3",
  "prompt_version": "history-opinion-2",
  "allowlist_version": "history-fields-1.1.0",
  "lang": "en",
  "takes": [{"take_id": "take_01", "position": 1, "faults_sent": 2, "faults_omitted": 0}],
  "observations": [
    {"take_id": "take_03", "at_s": 0.7, "measure": "elbow_flexion", "side": "right", "body_part": "arms",
     "text": "The right elbow bends more than the recording in the later takes too.", "lang": "en",
     "evidence": {"direction": "more", "magnitude_deg": 36.1}, "label": "model_opinion"}
  ],
  "dropped": {"count": 1, "reasons": {"adds a number": 1}},
  "translation_fallbacks": 0,
  "usage": {"input_tokens": 1830, "output_tokens": 210, "cached_tokens": 0, "usd": 0.003180}
}
```
- `status`: `ok` (the model answered and the answer was read; `observations` may be empty), `fallback` (a call was
  prepared or attempted and failed; `reason` says why; `observations` is empty), `skipped` (no call was attempted: no
  key, live mode off, or no take holds a fault with a second to cite; `reason` says why). `model` is null unless `ok`.
- `reason` never holds the key, and the model's answer is never put in it; an HTTP failure's reason may carry the API's
  own scrubbed error text (docs/design/specs/second-opinion.md AC-SO-06, `meta_api._scrubbed`).
- `takes`: one row per take, in order. `faults_omitted` counts faults left out of the facts (over 30 in a take, or a
  fault row that did not have a valid measure, side, body part and direction).
- `observations`: at most `--max-observations`, in the model's order (most useful first). `at_s` is the cited fault's
  own value. `lang` is the language of `text`. `text_en` (the English twin that passed the guard) is present when
  `lang` is not `en`.
- `dropped.count` is the number of model observations not kept; `dropped.reasons` counts them by reason.
- `lang_requested` is present when the tag asked for is not a listed language's bare tag, as for `phrasing`
  (`phrasing.lang.resolve`); `lang` is then the language used (English for an unlisted tag).
- `translation_fallbacks`: observations that kept their English `text` because the translated line failed its check.
- `usage` is present when a call was answered or attempted with a recorded cost (`usage.estimated` is true when the
  cost was recorded at the pre-call estimate).

## The allowlist (read from the history contract)
| Path | Kind | Row needs it |
|---|---|---|
| `schema_version` | id | |
| `profile` | id | |
| `status.code` | id | |
| `score.version` | id | |
| `score.value` | score | |
| `score.grade` | id | |
| `warnings[].code` | id | yes |
| `faults[].measure` | id | yes |
| `faults[].side` | id | yes |
| `faults[].body_part` | id | yes |
| `faults[].direction` | id | yes |
| `faults[].magnitude_deg` | number | |
| `faults[].at_s` | seconds | |

Which paths may be read is this list (`prompt.READS`); the contract cannot add one. The meaning sent to the model is the
`meaning` of the path's entry in `contracts/history-fields.json`, with its whitespace collapsed, and the kind follows the
entry's `units`: `none` is `id`, `score points` is `score`, `degrees` is `number`, `seconds` is `seconds`. A file that
cannot be read, has no `version` such as `1.1.0`, or lacks a listed path with units and a meaning stops the opinion with
a `ContractError`: the CLI exits 1 with a plain message and the API answers 500, and no call is made.

Kinds: `id` is a string of 1 to 40 ASCII letters, digits, dots, underscores and hyphens, starting with a letter or
digit (the whole string); `score` a whole number from 0 to 100, not a bool or a float;
`number` a finite number of at most 1e6, rounded to 2 decimals; `seconds` a finite number from 0 to 36000, rounded to
0.1. A value of another kind is left out; a list row missing a needed value is left out and counted. A take keeps at
most 30 fault rows and 5 warning rows, in document order (faults are sorted largest first).

## The request
One Responses body, three `input_text` items in one user message, stable content first:
1. the instructions, with the field guide built from the allowlist meanings (identical for every call of one
   `prompt_version`);
2. the facts: `Takes, oldest first (JSON): [...]` with sorted keys and no extra spaces (identical for one series);
3. the question, last: how many observations at most, and the language.
The model is `muse-spark-1.3`, reasoning effort low, `max_output_tokens` 8000 (`prompt.HISTORY_MAX_OUTPUT_TOKENS`; the
per-take opinion keeps 3000). The 8000 is twice the 3000 the model was seen to use, for its reasoning, plus 1400 for a reply
of 10 observations; at the output rate it adds at most $0.034 to the input, far under the $0.50 per-call ceiling. The
instructions ask for a reply of only JSON: `{"observations": [{"take", "at_s", "measure", "side", "body_part", "text", "line"}]}`, with `line` only
when a language other than English is asked for. They ask for one plain sentence of at most 140 characters, no number
and no take id, only the cited fault's body part, no praise, no health words, and no cause or comparison with other
people. The guard enforces each rule; the prompt only asks.

## Language
For a listed language other than English the model returns the English `text` and the same sentence as `line` in that
language. The English `text` goes through the guard below. The `line` must pass `phrasing.lang.check_translated` with
no time (one line, at most 200 characters, no digit, no praise phrase of the listed languages or English, then no
control character, link or banned word: `opinion.guard.unsafe_problem`, N2 of the 1.14.0 recheck). A passing
line becomes the observation's `text` (`lang` is that language, `text_en` the English twin); a failing or missing one
leaves the English `text` with `lang` `en` and counts under `translation_fallbacks`. That a translation says the same
as its twin is ASM-014. An unlisted tag is English.

## Acceptance Criteria
- AC-HO-01 (allowlist): the facts hold only allowlisted paths. A document whose other fields hold sentinel text (a
  `text`, `coaching`, `cue`, a clip path, a `second_opinion`, an extra top-level key) sends none of it. A value that
  is not of its kind is left out; a fault row without a valid measure, side, body part or direction is left out and
  counted in `faults_omitted`. The kinds and meanings are the history
  contract's: a contract file that cannot be read or lacks a path the opinion reads stops the run before any call (the CLI
  exits 1, the route answers 500).
- AC-HO-02 (series): take ids come from `--take-id`, else the file name, else the folder name for `analysis.json`;
  they must be valid and unique; the series is in the order given with positions from 1. At most 40 takes, 16 MiB a
  file. A file that is not a Part 5 analysis (not an object, `format` not `simon.analysis.*`, no `faults` list) is an
  error naming the file.
- AC-HO-03 (request): with a key and live mode, one text-only Responses request carries the instructions, the facts
  and the question in that order, and the first two items are byte-identical for two questions about one series. No
  file is uploaded. The request holds no path, no file name and no key.
- AC-HO-04 (guard, citation): an observation is kept only when its `take` is a take id of the series, its `at_s` (to
  0.1 s) is the `at_s` of a fault of that take, its `measure`, `side` and `body_part` are each a value of that take's
  faults, and the five together are one fault of that take. The first check that fails names the reason: `take not in
  the input`, `second not in the input`, `measure not in the input`, `side not in the input`, `body part not in the
  input`, `values are not one fault of that take`. A second observation for the same fault is `second observation for
  the same fault`; one past the limit is `more than N observations`; a non-object item is `not an object`.
- AC-HO-05 (guard, sentence): the `text` is refused when it is empty, has more than one line, is over 140 characters,
  has a control character, a link, a word this product never uses, praise, any number (digits, units, number words,
  counts such as "twice" or "half" as an amount) or any time, a body part group that is not one the cited measure
  names (`phrasing.template.NAMES`; the body part's groups when a measure is not listed), or a side word that is not
  the cited side. It uses `opinion.guard.text_problem`, so it reads "back", "half" and "face" as that guard does. The
  reason is the guard's, with the three clip-worded reasons said for a fault. The order of the series is known, so a
  sentence that speaks of earlier takes (`earlier`, `previous` or `prior` before `take`) is refused for the first take
  (`speaks of earlier takes but the cited take is the first`), and one that speaks of later takes (`later`, `next` or
  `following`) for the last (`speaks of later takes but the cited take is the last`); a series of one take is both.
  Advice about the follower's own next take ("in your next take", a possessive before `next take`) is not a claim
  about another take of the series and passes on the last take too (TICKET-076 R9). The possessive excuses `next take`
  only: "your later takes" and "your following takes" are claims about other takes and are refused on the last take
  (R2 of the 1.14.1 review).
- AC-HO-06 (no invented numbers): every number in an observation is in the input: `at_s`, `evidence.direction` and
  `evidence.magnitude_deg` are the cited fault's, and `text` has none. A model that returns a different `at_s` or a
  `magnitude_deg` of its own changes nothing in the kept values.
- AC-HO-07 (statuses): no key or live mode off is `skipped` with the phrasing reason (`no key`, `live calls are off
  ...`) and no call; no fault with a second is `skipped`, `no fault with a second to cite`, and no call. A failed
  call, an unreadable answer (not JSON, no `observations` list), the per-call ceiling or the cap is
  `fallback` with the reason and exit code 0. An unreadable answer whose API token count shows the whole output
  allowance used says `answer cut off at the output limit`; an estimated count never does.
- AC-HO-08 (spend and ledger): the call goes through `meta_api.call`, the one place that counts, checks the budget
  under the locked ledger, sends and records. Every attempted call writes one ledger line with `purpose`
  `history_opinion` and `prompt_version`, the model, UTC time, HTTP status, tokens and USD, never the key or text; a
  failed call with no known cost is recorded at the pre-call estimate (`estimated: true`), a refusal below 500 at $0.
  The two limit variables are checked before the call and an unreadable ledger refuses it, as for the per-take
  opinion.
- AC-HO-09 (language): a listed language other than English asks for `line`; a passing line is shown with its twin; a
  failing one falls back to English and is counted; an unlisted tag is English with `lang_requested`. A line passes
  when `check_translated` accepts it, which includes no control character, no link and no word this product never
  uses (`opinion.guard.unsafe_problem`, the same checks the English text gets; `check_translated` runs it itself
  since N2 of the 1.14.0 recheck); its English twin is checked as above.
- AC-HO-10 (exit codes): `0` for ok, fallback and skipped documents; `1` for input and output problems; `2` for usage
  errors, as in the command section.
- AC-HO-11 (route): `POST api/history-opinion` takes `{"analyses": [{"take_id": "...", "analysis": {...}}, ...],
  "lang": "es", "max_observations": 3}` and answers the document with 200. Limits as for `api/analyse`: a body over
  `MAX_BODY_BYTES` is 413; not JSON, not an object, no `analyses` list, an empty or longer-than-40 list, a missing,
  invalid or repeated `take_id`, an entry that is not an analysis, `lang` or `max_observations` of the wrong type or
  range is 400 naming the field; a GET is 405. A request that will make a call counts against the Muse Spark limit
  of the client (6 a minute, one at a time, 429 over it); a request that cannot (no key, live mode off) does not. The
  call uses a 50 s timeout, below the analysis limit. The timeout bounds the HTTP call, not the route: the route does
  not run under the analysis thread's limit, and a call that waits for the ledger lock waits at most
  `meta_api.LOCK_WAIT_S` (330 s) while another process's call holds it.
- AC-HO-12 (nothing else changes): the input files are not written; `analysis.json` and its schema are unchanged;
  `make check-5` stdout is byte-identical.

## Error Cases
| Case | Result |
|---|---|
| No files | usage error, exit 2 |
| `--take-id` count is not the file count, an invalid or repeated take id | usage error, exit 2 |
| A file missing, unreadable, over 16 MiB, not JSON, not an analysis | `part5 history-opinion: <file>: <why>`, exit 1 |
| More than 40 files | exit 1 |
| `--out` not writable | exit 1 |
| No key or live mode off | document `skipped`, reason as in phrasing, exit 0 |
| No fault with a second to cite | document `skipped`, exit 0, no call |
| Key file unreadable or empty | `fallback`, `key file unreadable` or `key file is empty` |
| HTTP error, timeout | `fallback`, `HTTP <code> on responses` or `timeout on responses` (count: `on count`) |
| Answer not JSON, no `observations` list, body not an object | `fallback`, `unreadable answer`, usage kept |
| An `output` item, message `content` or content part of the wrong shape (`[5]`, `"content": 5`, `["text"]`; N1 of the 1.14.0 recheck, TICKET-081) | `fallback`, `unreadable answer` |
| The same, with the API's own count showing the whole output allowance used | `fallback`, `answer cut off at the output limit`, usage kept |
| Over the ceiling or the cap | `fallback`, `estimated $x over the per-call limit of $y` or `spend cap reached` |
| A limit variable that is not an amount of USD from 0 up | `fallback` before the call, `<variable> is not an amount of USD from 0 up` |
| Ledger not writable, busy or not readable | `fallback`, `usage ledger not writable`, `usage ledger busy` or `usage ledger not readable` |

## Edge Cases
- One take: allowed; the model is asked what the take shows, and observations about repetition across takes drop out
  with the rest of what cannot be grounded.
- A take with no faults (a correct take) is sent with `faults: []`; it adds no citable fault.
- An old document without `at_s`, `body_part` or `score`: the missing values are left out; its faults without a second
  cannot be cited.
- A take id inside the sentence is refused as a number only when it holds a digit; the instructions ask for none.
- The model cites a fault that exists in another take under this take's id: refused, `values are not one fault of that
  take`.

## Negative Requirements (What This Feature Must NOT Do)
- It must not change `analysis.json`, its schema or any score, and nothing reads the document back.
- It must not send a field that is not on the allowlist, a path, a file name or the key; the key is never printed,
  logged, written or put in a reason, and no model text goes in a reason.
- It must not make a call in tests, `make check-5` or goldens; tests use a fake client only.
- It must not use the words coach, rehab, medical or injury in a sentence a student reads.

## Compromises
- The guard grounds the citation and bars numbers, extra body parts and wrong sides in the sentence. It cannot read
  whether "the right elbow bends more in the later takes too" is true of the series. A reader checks it against the
  cited take and the `evidence`. Trigger to revisit: a read of live answers against the facts shows wrong trend
  claims; the answer then is a structured `trend` field (repeats, new, gone, grows, shrinks) that code checks across
  the takes, not a longer prompt.
- The allowlist is read from `contracts/history-fields.json` since the follow-up merge (`prompt_version`
  `history-opinion-2`, `allowlist_version` `history-fields-1.1.0`). A change to the contract's meanings changes what the
  model is told, so the file's `version` is in the document and a change to `READS` raises `prompt_version`.
- Score and warning facts give the model context, but an observation must cite a fault, so a sentence about the score
  alone cannot be kept. Trigger to revisit: Part 7 asks for score observations.
- The per-rep fields of analysis 1.12.0 (TICKET-071) are not read; adding them is an allowlist entry and a
  `prompt_version` bump.
- The sentence is in English for the guard and a translation is held only by `check_translated` and ASM-014.
- Live record, 2026-11-01. Two live calls were logged under `history_opinion`. The first (21:40:41Z, prompt
  `history-opinion-1`, output allowance 3000) is recorded as HTTP 200 with 3000 of 3000 output tokens and no readable
  JSON, at $0.014; its ledger line holds 1000 input tokens and no `estimated` flag. That was a real call: the
  independent delta review (7a148c7..9eae4e2) found that the v1 prompt is 3914 characters, which predicts about 1016
  tokens, that the scratch files show `live-history.json` written at that second, and that the test which uses these
  figures copied the call, not the reverse. The second (23:21Z, prompt `history-opinion-2`, allowance 8000), over the four
  golden analyses in `fixtures/output/`, came back `ok` with 3 observations, none dropped, 1135 input and 2112 output
  tokens, $0.010395. Those 2112 tokens would also have fitted in 3000, so the larger allowance is headroom for a longer
  series and a tail of long reasoning, not proof of a cause. The three kept sentences passed the guard, but they read
  awkwardly ("Right arms bending in this take goes away in the later takes against the recording") and the four goldens
  are not one person's series, so the trend claims are unchecked. Trigger to revisit: a read of live answers over a real
  series shows wrong trend claims; the answer is the structured `trend` field above. Awkward wording alone is a prompt
  change and raises `prompt_version`.
- Order is the caller's. A sort by a recording date would need a date in the analysis.
- Placement. The code sits in the existing opinion modules (`prompt.py`, `guard.py`, `__init__.py`) and in `cli.py` and
  `api.py`, not in new `history_*.py` files: it was built in a worktree whose write gate reads the main checkout's
  specs, which did not hold this one, so a new file under `part5/` was refused. Trigger to revisit: at the merge
  acceptance, with this spec on main, split the second halves of `prompt.py` and `guard.py` and the history part of
  `__init__.py` into four new modules named after what they hold (facts, prompt, guard, run); no behaviour changes.

## Assumptions
- ASM-014: a translated line returned with an English twin that passes the guard says the same thing.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `docs/design/specs/history-opinion.md`, `docs/design/specs/history-opinion.md`, `docs/design/README.md` | this spec, its design copy, the index line | TICKET-072 | yes |
| `part5/opinion/prompt.py` | the allowlist (`READS`, read from the history contract by `load_allowlist`), `ContractError`, `facts_of`, `build_series`, `Series`, take ids and their errors, the history instructions, `HISTORY_MAX_OUTPUT_TOKENS` and `history_request` | TICKET-072 | yes |
| `part5/opinion/guard.py` | `read_history_answer`: the citation guard, the sentence guard, language, drops | TICKET-072 | yes |
| `part5/opinion/__init__.py` | `series_from_files`, `series_from_request`, `history_run`, the document; the per-take `_ask` uses `meta_api.call` and `preflight` | TICKET-072 | yes |
| `part5/opinion/meta_api.py` | `call` (count, budget, send, record in one place, priced at the request's own `max_output_tokens`), `preflight`, the ledger `purpose` and extra fields | TICKET-072 | yes |
| `part5/cli.py` | the `history-opinion` subcommand, its exit codes and summary line | TICKET-072 | yes |
| `part5/api.py` | `POST api/history-opinion`; a history contract the server cannot read is a 500 | TICKET-072 | yes |
| `docs/meta-api-spend.md`, `docs/design/specs/part5-fault-analysis.md` | the history opinion in the spend notes and the master Files table | TICKET-072 | yes |
| `tests/test_history_opinion.py`, `tests/test_history_opinion_guard.py`, `tests/test_history_opinion_cli.py` | the ACs | TICKET-072 | yes |

## Delivery Verification Plan
- `uv run pytest -q tests/test_history_opinion.py tests/test_history_opinion_guard.py tests/test_history_opinion_cli.py
  tests/test_second_opinion.py tests/test_second_opinion_hardening.py tests/test_second_opinion_keys.py` while
  building; `make test` once at the end.
- `make check-5` stdout byte-identical to the candidate's; `make check-5-contract` 0;
  `python3 scripts/make_design_copies.py --check` 0; no em dash, en dash or spaced hyphen in changed files.
- At most one live call: `part5 history-opinion` over the committed golden analyses under `fixtures/output/` with
  `--live`, only when the key file is configured; its ledger line and cost are recorded as evidence. Tests never call.

### Device/Platform Strategy
Not applicable: command line and API only. Part 7 displays the document, if it chooses to.

### Data (created through the product's own UI with synthetic accounts; never a DB or API seed)
- Synthetic accounts needed: none. Data: the committed golden analyses and fixtures built in the tests.

### Ratchet Initialization Plan
Not applicable.

### Boundary Layer Testing Plan
| Mapping Function | Input Format | Output Format | Test File |
|-----------------|-------------|---------------|-----------|
| `prompt.facts_of` | an analysis document | allowlisted facts | `tests/test_history_opinion.py` |
| `prompt.build_series` | documents and take ids | series with the faults that can be cited | `tests/test_history_opinion.py` |
| `prompt.history_request` | series, language, limit | Responses body | `tests/test_history_opinion.py` |
| `guard.read_history_answer` | model text, series | observations, drops | `tests/test_history_opinion_guard.py` |

## Dissent Review (MANDATORY, hooks block implementation without this)
Reviewed by: lane history-opinion (implementer, self-review). Independent review: the one consolidated review at the
merge acceptance after the DONE publish.
Date: 2026-11-01

### Concern 1: the opinion reads as a verdict on the person
Challenge: a sentence about "the later takes" can sound like a judgement of progress. Impact: users trust or resent it.
Mitigation: label `model_opinion` on the document and on each observation, no number in the sentence, evidence from the
measurement beside it, nothing reads it back. Resolution: ADDRESSED_IN_SPEC.

### Concern 2: the allowlist drifts from the contract
Challenge: TICKET-070 may name other paths. Impact: the model sees fields Part 7 does not promise. Mitigation: one
one list of paths, one loader that reads the contract, a version string in the document, the prompt version raised on a change. Resolution:
ADDRESSED_IN_SPEC.

### Pre-Mortem: It's 6 months from now and this feature was a disaster. Why?
1. Part 7 shows the sentences as fact and a wrong trend claim reaches a student. Likelihood: M, Impact: M, Mitigation:
   the label, the citation to check, the structured `trend` field named in Compromises.
2. A coach pastes a long series and the cost surprises them. Likelihood: L, Impact: M, Mitigation: 40 takes, 30 faults a
   take, the per-call ceiling and the cap, and one ledger line per call.
3. A crafted analysis tries to steer the model through a field value. Likelihood: L, Impact: L, Mitigation: every
   allowlisted string is a short identifier; a free sentence never reaches the model, and the guard drops what cites
   nothing real.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|-------------------|---------|------|--------|
| TICKET-072: reads only the allowlisted fields | AC-HO-01, AC-HO-02 | `tests/test_history_opinion.py` | built on the branch |
| TICKET-072: through the existing backend and ledger, stable content first | AC-HO-03, AC-HO-08 | `tests/test_history_opinion.py` | built on the branch |
| TICKET-072: each observation cites a take and a second; unground is dropped | AC-HO-04 to AC-HO-06 | `tests/test_history_opinion_guard.py` | built on the branch |
| TICKET-072: statuses, language, exit codes | AC-HO-07, AC-HO-09, AC-HO-10 | `tests/test_history_opinion_cli.py` | built on the branch |
| TICKET-072: an API route if it fits | AC-HO-11 | `tests/test_history_opinion_cli.py` | built on the branch |
| TICKET-072: no change to analysis.json | AC-HO-12 | `tests/test_history_opinion_cli.py`, `make check-5` | built on the branch |

## Deviations from PRD
None. The ticket says "an API route if it fits the server"; it fits: one new entry in `ROUTES`, the same body limit,
the same per-client Muse Spark limit, and no change to the server module.
