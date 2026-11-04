# Spec: cues in the follower's language, written by the model, with provenance (analysis 1.14.0)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-11-02
Linked PRD: none (hub TICKET-266, Part 5's share; moalborati/simon#61 operator fan-out order of 2026-11-02T04:10Z)
Linked CRD: none
Request Type: feature-mod
Risk Level: medium (a second model call per non-English analysis; no field the score or `make check-5` reads)
Master spec: `second-opinion.md` (AC-LA-01 to AC-LA-04, the follower's language for fault lines). Companions:
`part5-fault-analysis.md` (the phrasing registry), `journey-followup.md` (the live phrasing), `integration-contract.md`.
Ticket: TICKET-080. Assumption: ASM-015.

## Overview
Today a request in another language (`--lang es`, `ar`, `hi` or any other of the 18 languages in `part5/phrasing/lang.py`)
gets the fault line (`faults[].coaching`, `phrasing.faults[].text`) written by the model in that language, and nothing
else. Every cue and every "why" in the document is still an English template: `faults[].cue`, each
`score.timeline[].misses[].cue`, `score.timeline[].tempo.cue`, `score.tempo.cue`, `insights[].cue` and `insights[].why`.
From 1.14.0, for a listed language other than English, Part 5 asks the model, in one more batched call after the fault lines,
to write those cues and reasons in the requested language. Each one passes a word test or keeps its English text with the
reason. The result is written in a new, additive record `phrasing.cues[]`, one entry per field with the path, the text, the
language, the backend, the model and the fallback reason, so a reader sees which model wrote each string and never mistakes
a template for a translation. The English fields stay exactly as they were, so no reader breaks. A second, additive marker,
`phrasing.native_review`, says that no native reader has checked the text; it is `false` for every language today.

## Which cue strings are English today (found by running the pipeline, seed 5 Take 03, `--lang es`)
With a model fault line in the requested language, these strings in the document are still English templates:
| Path | Where it comes from | In scope |
|---|---|---|
| `faults[i].cue` | `part5/cues.py` `cue_for(measure, direction, side)` | yes |
| `score.timeline[k].misses[j].cue` | copied from the fault by `score.miss_entry` | yes |
| `score.timeline[k].tempo.cue`, `score.tempo.cue` | `cues.tempo_cue` (`Slow down to match the trainer`, `Speed up to match the trainer`, a profile's words, `Slower is fine`) | yes |
| `insights[i].cue` | the miss's or the tempo cue | yes |
| `insights[i].why` | `part5/insights.py`: the fault's `text_timed` words, or for a tempo item `Your reps took 1.3 times the trainer's time`; a model clause is used only for language `en` | yes |
Not cues, and left English on purpose (a later ticket may take them): `faults[i].text` and `text_timed` (the plain-words
fragments the cue and the insight are built from), `status.text`, `warnings[].text`, `diagnostics.*`,
`score.timeline[].misses[].text` (it repeats the fault line, which is already in the requested language when the model
wrote it). Verified by `tests/test_language_cues.py` (AC-LC-01) which lists these paths from a real document.

## Why This Is Wrong (Dissent-First)
1. **The model can say something other than the English.** A cue translated into Arabic or Hindi could name the other side,
   or give advice nobody wrote. Part 5 has no word test in those languages. Answer: the text is held to what can be checked
   in any language (numbers, one line, length, no praise, no English time phrase, written in the script of the language and
   not a copy of the English); the side and the meaning rest on ASM-015 and a native read, and `phrasing.native_review:
   false` says the read has not happened. This is the same residual risk as ASM-014 for the fault lines, and it is stated
   rather than hidden.
2. **A second call costs money and time for a string that rarely changes.** The same 15 cues repeat in every take. Answer:
   one batched call per analysis carries every distinct string (not one call per path), and the call is skipped when there
   is none or the backend is unavailable. A cache of translations would be reasonable later, but it would make a cue a stored
   fixture, which is what the hub's AC-1 forbids ("names the model, not a fixture").
3. **Two translations of one fact can disagree.** The fault line and the "why" of the same fault are written by two calls.
   Answer: they are separate fields with separate provenance, the cue and the why come from the English templates both
   times, and a reader that wants one voice shows `phrasing.faults[i].text` for the fault and `phrasing.cues[]` for the
   action. Not solved; recorded.
4. **Overwriting `cue` would be simpler for readers.** Answer: Part 7 and others read `cue` as the English imperative of at
   most 6 words (schema 1.5.0, `contracts/student-words.json`, `history-fields.json`), and history comparisons group by it.
   The translation is an additive record; the original fields do not move (AC-LC-06).
5. **A marker per document is coarse.** One boolean cannot say that Spanish was read and Hindi was not. Answer: today no
   language is read, so the boolean is exact; the registry `lang.NATIVE_REVIEWED` is the one place a language is added when a
   native reader signs off, and the field stays a boolean that is true only for such a language.

## User Story
As a follower who asked for Spanish, Arabic or Hindi
I want the action to take and the reason, not only the fault line, in my language
So that the whole result reads in one language and I can tell the model wrote it and a native reader has not checked it.

### Jobs-to-be-Done
- Functional job: give every cue and reason of a result in the requested language, with the model that wrote each named.
- Emotional job: the result feels written for the follower, not translated at the edges.
- Social job: Part 7 can say "not reviewed by a native reader" instead of implying a checked translation.

## The record
Every analysis from 1.14.0 whose `phrasing.lang` is a listed language other than `en` carries, inside `phrasing`:
| Key | Meaning |
|---|---|
| `cues` | a list, one entry per translatable field present in the document, in document order: `faults[i].cue` in fault order, then each timeline window's misses and its tempo, then `score.tempo.cue`, then each insight's `cue` and `why` |
| `cues[].path` | the field the entry is about, as `faults[0].cue`, `score.timeline[2].misses[0].cue`, `score.timeline[2].tempo.cue`, `score.tempo.cue`, `insights[1].why` |
| `cues[].text` | the text to show: the model's text in the language, or the English text of the field when the entry fell back |
| `cues[].lang` | the language of `text`: the requested one, or `en` for a fallback |
| `cues[].backend`, `cues[].model` | who wrote `text`: `muse-spark` and its model, or `local-llm` and its model; `template` and `null` for a fallback |
| `cues[].fallback_reason` | `null`, or why the English text is shown: `muse-spark: translation adds a number`, `rate limited`, `no key`, `template lines are English only` and the like (never a key or the model's text) |
| `native_review` | `false` for every language until `lang.NATIVE_REVIEWED` names it; present exactly when `phrasing.lang` is not `en` |
An English request (no `lang`, `en`, or an unlisted tag that falls back to English) has neither key, so its document is what it
was apart from `schema_version`. `phrasing.faults[]` is unchanged and keeps the fault lines.

## How the model is asked
After the fault lines (and the variety pass) and after the score and the insights are final, one request:
- The distinct `(role, text)` pairs of the paths above, where `role` is `cue` for a path ending in `.cue` and `reason` for
  `.why`. At most about 30 pairs for any take, usually 2 to 8. A pair shared by several paths is translated once and written
  to each path.
- System text: translate for a person copying a movement, calm and matter-of-fact; say exactly what the English says; add no
  praise, advice, body part or number; keep `left` and `right` as the English has them; write every word in the language;
  keep each number as the English writes it, in Western digits; reply with only a JSON object
  `{"items": [{"id": 0, "text": "..."}]}`.
- The user message is the JSON list of `{id, kind, text}` (`kind` is the role). The text is the English template text; nothing about the person or
  the clip is sent.
- The call goes through the backend of the fault lines (`muse-spark`, or `local-llm`): the same key file, live switch,
  per-minute limit and usage ledger as one fault line, with its own timeout of 20 s and an answer allowance of 6000 tokens
  (a batch of up to 30 texts, and a reasoning model spends most of it on reasoning). It appends one ledger line, like every call.
- If the backend is unavailable (the template, no key, live calls off) no call is made and every entry falls back with that
  reason. With nothing to translate, no call is made and `cues` is `[]`.

## How an answer is checked
Each item is checked on its own (`lang.check_cue`); one bad item does not spoil the others. A failure keeps the English text
for that item, with the reason `<backend>: <what>`:
- The answer must be a JSON object with an `items` list; an item has the `id` asked for and a string `text`. Missing, unreadable
  or repeated ids: `no translation returned` for the items concerned, `unreadable answer` for the whole reply.
- One line, not empty, no more than 60 characters and 10 words for a cue, no more than 200 characters for a reason
  (`translation is empty or too long`, `translation has more than one line`).
- No control character (a tab, a zero-width character, a bidi override, embedding or isolate such as U+202E), no link and
  none of the words this product does not use: `opinion.guard.unsafe_problem`, as for the history opinion's translations
  (`translation has a control character`, `translation has a link`, `translation uses a word this product does not use`;
  R7 of the 1.14.0 review). The word list is English, so it catches a banned word left untranslated, not its translation.
- No praise: the English phrases in every language and the phrases of `lang.PRAISE` for the Latin-script languages
  (`translation adds praise`), as for a fault line.
- A cue holds no digit (`translation adds a number`). A reason holds exactly the numbers of its English text, no more and no
  fewer, a comma or a point as decimal separator (`translation changes the numbers`); the time is therefore said once, and with
  the right value, whenever the English says it.
- No English time phrase: an English time word (`lang.ENGLISH_TIME_WORDS`) directly before a number
  (`translation keeps an English time phrase`).
- It is in the language: a language with its own script (`ar`, `hi`, `ru`, `ja`, `ko`, `zh`) needs at least half of its
  letters in that script; a Latin-script language must not be a copy of the English, nor share half or more of the English's
  words of three letters or more (`translation is not in the language asked`).
The same checks run for all 18 languages. `lang.check_translated` (the fault lines) holds a translated fault line to
`unsafe_problem` in the same way since N2 of the 1.14.0 recheck (TICKET-080); its other checks are unchanged.

## Acceptance Criteria
### AC-LC-01: the strings, listed from a real document
Given a Spanish analysis of seed 5 Take 03 with template phrasing, then the fields listed under "Which cue strings are
English today" hold English text, and the collector (`cues.cue_fields`) lists exactly the in-scope paths, in document
order, including a tempo cue and a miss of a take compared window by window. Tests: `tests/test_language_cues.py`.

### AC-LC-02: written by the model in one batched call, with provenance
Given live mode, a key and `lang` `es`, `ar` or `hi`, when the analysis is made, then one request after the fault lines carries
every distinct string, and for each path `phrasing.cues[]` holds the model's text, the requested language, the backend and
the model, and `fallback_reason` `null`. The same English text on several paths is translated once. Exactly one extra ledger
line is appended. Tests: `tests/test_language_cues.py` with the fake transport, which asserts the request body and the ledger.

### AC-LC-03: a bad item falls back alone, and says why
Given an item that has a digit (cue), changes a number (reason), says the time twice or with an English time word, adds praise,
has a link, a control character or a banned word, runs over the length, spans lines, repeats the English, is in the wrong
script, or is missing, then that entry keeps the English
text with `lang` `en`, `backend` `template`, `model` `null` and the reason, and the other entries keep their translation.
Given a failed call (HTTP error, timeout, rate limit, empty content) or a reply that is not the JSON asked for, then every entry
falls back with that reason. Tests: `tests/test_language_cues.py`, `tests/test_phrasing_lang.py` (unchanged).

### AC-LC-04: no model, no call
Given the template backend, no key, or live calls off, with `lang` `es`, then no request is made, every path has an entry in
English with `backend` `template` and the reason (`template lines are English only`, `no key`, `live calls are off ...`), and
`native_review` is `false`. Tests: `tests/test_language_cues.py`.

### AC-LC-05: the marker
Given `phrasing.lang` other than `en`, then `phrasing.native_review` is `false` (it is `true` only for a language listed in
`lang.NATIVE_REVIEWED`, which is empty). Given English, then the key is absent. Tests: `tests/test_language_cues.py`.

### AC-LC-06: additive, English unchanged
Given an English request, then the document is the 1.13.0 document with `schema_version` 1.14.0 and nothing else changed (the
four goldens, rebuilt by `make output-examples`, differ from 1.13.0 only in that string). Given a non-English request, then
`faults[].cue`, the misses' and tempo cues, `insights[].cue` and `why` and `faults[].coaching` are what they would be without
the cue call. The schema (`contracts/analysis.schema.json` 1.14.0) validates `phrasing.cues` and `phrasing.native_review`; the
document check refuses a `cues` entry whose `path` does not resolve to a string in the document, whose `text` is empty, whose
`backend` is unknown (not a name of `phrasing.BACKENDS`, the schema's enum; R10 of the 1.14.0 review), or a `native_review`
that is not a boolean. A 1.13.0 document still validates. Tests:
`tests/test_language_cues.py`, `tests/test_output.py`, `tests/test_contract_part7_history.py`.

### AC-LC-07: the doctor
Given a 1.14.0 document with `phrasing.cues`, then `part5 doctor <file> --for part7` adds one note: how many cues were written
by which model in which language, how many kept English and the first reason, and that no native reader has checked them
(show `phrasing.native_review`). Tests: `tests/test_doctor.py`.

### AC-LC-08: the viewer reads right to left
Given a result whose fault lines, cues or reasons are Arabic, then each element that shows text from `phrasing` (the fault line,
the insight's cue and reason, the preview card's line) has `dir="auto"`, so Arabic text is right to left and a number inside it
keeps its digits in order; the translated cue and reason are shown instead of the English when `phrasing.cues` has them; and a
document with `phrasing.native_review` `false` shows "Not reviewed by a native reader." Tests: `tests/test_web_logic.py`
(pure functions in Node) and `tests/staging/test_web_files.py`.

### AC-LC-09: one live proof per language, inside the cap
Given the key and live mode, `part5 analyse ... --live --lang es`, `ar` and `hi` on seed 5 Take 03 write
`fixtures/output/lang/analysis.<tag>.json`, at most 6 live calls in all (one fault line and one cue call per language), each
in `~/.simon/baseten_usage.jsonl`. `fixtures/output/lang/PROVENANCE.md` names the command, the model and the ledger lines, never
the key. If a call is refused (no key, live off, a cap), the refusal reason is reported and nothing is faked. These files are
recorded outputs: `make check-5-contract` validates and loads them but does not rebuild them (a model's text is not
rebuilt). Tests: `tests/test_language_cues.py` (the recorded files validate, hold only model or fallback entries and name the model).

### AC-LC-10: nothing else moves
Given the commit before, then `make check-5` prints the same stdout (`cmp` exit 0), `part5/rules.json`, `part5/detect.py`,
`part5/profiles.json` and the score are untouched, and a document made with template phrasing is what it was.
Verified by `git diff --stat` of those files against the base commit, `cmp` of `make check-5` stdout against a `git archive`
export of the base commit, and the whole suite (no test pins the base commit, which would break once other lanes merge).

## API / Interface Contract
- `part5.cues.cue_fields(doc) -> [CueField(path, role, text)]`, in document order; `role` is `ROLE_CUE` or `ROLE_REASON`.
- `part5.phrasing.prompt.cue_messages(texts, language) -> chat messages`, `texts` a list of `(role, English text)`;
  `part5.phrasing.lang.read_items(reply, count) -> {id: text}` (ValueError `unreadable answer`).
- `part5.phrasing.phrase_cues(analysis, backend, *, timeout_s, client, live, lang) -> analysis` sets `phrasing.cues` and
  `phrasing.native_review` for a language other than English and returns the document unchanged for English.
- `part5.phrasing.muse_spark.complete(chat, *, timeout_s, client)` and `part5.phrasing.local_llm.complete(...)`: one reply for a
  chat that is already built, through the same key, rate limit and ledger as `line`.
- `part5.phrasing.lang.check_cue(role, source, text, language) -> None | reason`, `lang.NATIVE_REVIEWED`, `lang.SCRIPTS`,
  `lang.native_review(language)`.
- The pipeline calls `phrase_cues` once, last (`part5/pipeline.py` `_cued`, from `_finish`), so the insights it reads are final.

## Error Cases
| Condition | Behavior | Message | AC |
|---|---|---|---|
| backend unavailable | every entry in English, no call | the backend's reason | AC-LC-04 |
| HTTP error, timeout, empty content | every entry falls back | `muse-spark: HTTP 500` and the like | AC-LC-03 |
| reply is not the JSON asked for | every entry falls back | `muse-spark: unreadable answer` | AC-LC-03 |
| one item fails its check | that entry falls back | `muse-spark: translation adds a number` and the like | AC-LC-03 |
| rate limit | every entry falls back | `rate limited` | AC-LC-03 |
| `cues[].path` does not resolve | `OutputError` | `phrasing.cues[i].path ...` | AC-LC-06 |
| `cues[].backend` unknown | `OutputError` | `phrasing.cues[i].backend must be one of [...]` | AC-LC-06 |

## Edge Cases
- A correct take with no faults and no tempo cue: `cues` is `[]`, `native_review` `false`, no call (AC-LC-04).
- A correct take whose only cue is a tempo cue: one cue call, no fault call (the fault lines say `no faults to phrase`).
- The same cue on three paths (the fault, its miss, its insight): one translation, three entries (AC-LC-02).
- A comma decimal (`1,9 s`) in a Spanish reason is the same number as `1.9` (AC-LC-03).
- A profile's own tempo words (`rehab`: `Slower is fine`) are translated like any other cue.
- An unlisted tag (`tlh`) is English: no `cues`, no `native_review`, `lang_requested` as before.
- A region tag (`es-MX`) resolves to `es`; `phrasing.lang_requested` keeps `es-MX` as before.
- The replay file is untouched.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | one extra call, on its own timeout | at most 20 s after the fault lines; the API's 60 s limit holds with the 20 s phrasing budget | AC-LC-02 |
| Security | the key is read at the call and never written; the reasons hold no text of the model | the existing `muse_spark` rules, and a test that the key is absent from the document and the reasons | AC-LC-02 |
| Reliability | any failure keeps the English text | AC-LC-03 | AC-LC-03 |
| Compatibility | additive; a 1.13.0 reader ignores it | schema 1.14.0 | AC-LC-06 |
| Accessibility | text direction follows the text | `dir="auto"` | AC-LC-08 |
| Scalability, Maintainability | no new dependency; the check is one function per concern | | |

## Negative Requirements (What This Feature Must NOT Do)
- MUST NOT change `faults[].cue`, `cue_kind`, the misses', tempo or insight cues, `insights[].why`, `coaching`, the score or the
  detection. Why: readers group by the English cue; the score never reads a phrasing field.
- MUST NOT store or reuse a translation between analyses. Why: the hub's AC-1 wants the model named for the analysis, not a fixture.
- MUST NOT call a model in a test, in `make check-5`, `make check-5-contract` or `make output-examples`. Why: ADR-0008.
- MUST NOT claim a language is native-reviewed. Why: none is; `lang.NATIVE_REVIEWED` is empty until a person signs.
- MUST NOT put the key, a path to it or a model's text in a reason or in the ledger.

## Compromises
### The side and the meaning of a translation rest on the model and a native read
Short-term: numbers, script, shape and length are checked; "left" is not checked in Arabic or Hindi (ASM-015); `native_review` says so.
Long-term: a native reader per language reads a sample (the same recipe as ASM-014) and signs; or a per-language side-word test for
the three languages Part 7 ships.
Migration path: add the language to `lang.NATIVE_REVIEWED` when a reader signs; add a side test beside `check_cue`.
Trigger to revisit: the first native read, or a mismatch reported by Part 7.

### One boolean for the review marker
Short-term: `phrasing.native_review` (AC-LC-05). Long-term: a list of the languages and readers if some are read and some not.
Trigger to revisit: the first language that a native reader signs.

## Non-Requirements (Explicitly NOT Building)
- Speech, `navigator.language` and any Part 7 UI: Part 7 (hub TICKET-266 AC-2 to AC-4).
- A translation of `faults[].text`, `text_timed`, `status.text` or `warnings[].text`.
- A cache of translations, or a cue vocabulary per language written by hand.
- A native read of the text, which only a person can do.

## Assumptions
- ASM-015: a translated cue or reason that passes the checks above says what its English text says, including left and right
  (links to `docs/assumptions/ASM-015.yaml`). ASM-014 is the same assumption for the fault lines.

## Implied Requirements Discovered
- The pipeline makes the insights twice (after phrasing, and again with the score); the cue call has to run after the second so it
  sees the final `insights[].why` (found reading `part5/pipeline.py` `_finish`).
- `make check-5-contract` rebuilds every `analysis*.json` under `fixtures/output/`, which a live output cannot be; the check is
  narrowed to the files directly in that directory so the recorded outputs under `fixtures/output/lang/` are validated and loaded
  but not rebuilt (found while placing the live proof).
- The write gate (`scripts/enforce-gates.sh`) looks for a covering spec in the main checkout's `docs/specs/`, so a lane's new
  `part5/` file named only in the lane's own spec is refused; the cue code therefore sits in the files that already have specs
  (`cues.py`, `lang.py`, `prompt.py`, `phrasing/__init__.py`) and no new module was added.
- The Baseten ledger records tokens, not USD; the proof reports tokens and a USD figure at the list rates `docs/meta-api-spend.md`
  already uses for the Meta Model API, labelled as an estimate.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `docs/design/specs/language-cues.md`, `docs/design/specs/language-cues.md`, `docs/design/README.md` | this spec, its neutralised copy and its index line | TICKET-080 | yes |
| `docs/assumptions/ASM-015.yaml` | the assumption | TICKET-080 | no (firm) |
| `part5/cues.py` | `CueField`, `cue_fields` (every cue and reason of a document), `ROLE_CUE`, `ROLE_REASON`; `validate_cues`, the check of `phrasing.cues` and `phrasing.native_review` that `validate_analysis` runs (moved here from `part5/output.py` unchanged in the 1.14.0 round: the merge of lane/v114 with the 1.13.0 review fixes took that module to 823 lines, past the 800 line limit) | TICKET-080 | yes |
| `part5/phrasing/lang.py` | `check_cue`, `read_items`, `SCRIPTS`, `NATIVE_REVIEWED`, `native_review` | TICKET-080 | yes |
| `part5/phrasing/prompt.py` | `SYSTEM_CUES`, `cue_messages` | TICKET-080 | yes |
| `part5/phrasing/__init__.py` | `phrase_cues` and the entries it writes | TICKET-080 | yes |
| `part5/phrasing/muse_spark.py`, `part5/phrasing/local_llm.py` | `complete` (one reply for a built chat); `line` shares the call | TICKET-080 | yes |
| `part5/pipeline.py` | `_cued` calls `phrase_cues` last | TICKET-080 | yes |
| `part5/output.py` | `SCHEMA_VERSION` 1.14.0; `validate_analysis` runs `cues.validate_cues` | TICKET-080 | yes |
| `part5/contract.py`, `part5/doctor.py` | the compatibility row and the golden rule for recorded outputs; the doctor note | TICKET-080 | yes |
| `contracts/analysis.schema.json`, `contracts/history-fields.json` | version 1.14.0, `phrasing.cues`, `phrasing.native_review`; history fields | TICKET-080 | yes |
| `fixtures/output/analysis*.example.json` | regenerated by `make output-examples` (only `schema_version` changes) | TICKET-080 | yes |
| `fixtures/output/lang/analysis.{es,ar,hi}.json`, `fixtures/output/lang/PROVENANCE.md` | the live proof | TICKET-080 | yes |
| `CONTRACT.md`, `docs/schemas.md`, `docs/meta-api-spend.md` | the 1.14.0 paragraph, the cue call | TICKET-080 | yes |
| `web/joints.js`, `web/app.js`, `web/preview.js`, `web/style.css` | `dir="auto"`, translated cue and reason, the review note | TICKET-080 | yes |
| `tests/test_language_cues.py` and the tests that pin the schema version | AC-LC-01 to AC-LC-10 | TICKET-080 | yes |

## Delivery Verification Plan
- While building: `uv run pytest -q tests/test_language_cues.py tests/test_phrasing_lang.py tests/test_phrasing_muse_spark.py
  tests/test_output.py tests/test_doctor.py tests/test_contract_history_fields.py tests/test_contract_part7_history.py
  tests/test_web_logic.py tests/test_design_copies.py`.
- At the end, once each: `uv run make test`; `uv run make check-5` with stdout compared by `cmp` against a run at the commit before in
  a `git archive` export; `uv run make check-5-contract`; `make contracts-check`; `python scripts/make_design_copies.py --check`.
- The live proof is three CLI runs (AC-LC-09) with the live switch on, inside the spend cap, recorded in the usage ledger.

### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|----------|------|----------|-------------|
| the page in `web/` | Node functions in `tests/test_web_logic.py`; the staging browser drive is the maintainers' (Arabic at 412 px, `qa/recipes`) | 412 px | the integration lane |

### Data (created through the product's own UI with synthetic accounts; never a DB or API seed)
- Synthetic accounts needed: none.
- Data each verification needs: the committed seed 5 Take 03 (`exercise_front_good_03_foot_out-right`) and the exercise example.

### Ratchet Initialization Plan
Not applicable: the floors in `progress/ratchets.json` must not drop.

## Dissent Review
Reviewed by: the implementing lane against the review of TICKET-046 and TICKET-052 (language lines), on 2026-11-02.

### Concern 1: a translated cue may name the wrong side
Challenge: nothing in the checks reads left and right in Arabic or Hindi.
Impact if right: a follower is told to move the wrong foot.
Mitigation: ASM-015 states it; `native_review` is `false`; the English `cue` stays beside it; the fault line already carries the
English twin check.
Resolution: ACCEPTED_RISK until a native read.

### Concern 2: the extra call makes a slow analysis slower
Challenge: 20 s more on top of 20 s.
Impact if right: the API's 60 s limit.
Mitigation: its own timeout, one call, skipped when nothing is to be written; a failure returns English.
Resolution: ADDRESSED_IN_SPEC.

### Concern 3: a file in `fixtures/output/` that cannot be rebuilt
Challenge: the contract check rebuilds every golden byte for byte.
Impact if right: `make check-5-contract` fails on the recorded outputs.
Mitigation: only files directly in `fixtures/output/` are goldens; the recorded ones are validated and loaded.
Resolution: ADDRESSED_IN_SPEC (AC-LC-09).

### Pre-Mortem: It's 6 months from now and this feature was a disaster. Why?
1. A Hindi cue told a follower to bend the wrong knee and `native_review` was ignored by the viewer. Likelihood: M, Impact: H,
   Mitigation: the viewer shows the note; the English cue stays; ASM-015 revisit on the first mismatch.
2. The model started to reply with prose around the JSON. Likelihood: M, Impact: L, Mitigation: the reader takes the object between
   the first `{` and the last `}` (as `lang.json_object`); anything else falls back with `unreadable answer`.
3. A new cue was added in English and nobody added it to the collector. Likelihood: L, Impact: M, Mitigation: the collector walks
   the document's cue fields, not a list of cues; a test lists every path of a rep-by-rep take.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|-------------------|---------|------|--------|
| Hub TICKET-266 AC-1: cue provenance names the model | AC-LC-02 | `tests/test_language_cues.py` | passing |
| Ticket 080: fallback to English with the reason | AC-LC-03, AC-LC-04 | `tests/test_language_cues.py` | passing |
| Ticket 080: the marker | AC-LC-05 | `tests/test_language_cues.py` | passing |
| Ticket 080: additive 1.14.0, English byte-identical | AC-LC-06 | `tests/test_language_cues.py`, the goldens | passing |
| Ticket 080: `doctor --for part7` note | AC-LC-07 | `tests/test_doctor.py` | passing |
| Hub TICKET-266 AC-4: `dir` for Arabic | AC-LC-08 | `tests/test_web_logic.py` | passing |
| Ticket 080: one live run each | AC-LC-09 | `fixtures/output/lang/PROVENANCE.md` | recorded |

## Test Scenarios (maps 1:1 to acceptance criteria)
- AC-LC-01 to AC-LC-10 as listed above, all in `tests/test_language_cues.py` unless named.

## Deviations from PRD
| PRD item | Deviation | Reason |
|----------|-----------|--------|
| Hub AC-1 "three finished staging follow jobs" | Part 5's share is the analysis files under `fixtures/output/lang/` made by the CLI | the staging jobs are Part 7's; Part 5 supplies the model-written cues and the provenance they read |
| Hub AC-2 to AC-4 (MMS-TTS, `navigator.language`, Part 7's 412 px block) | not built here | Part 7's |
