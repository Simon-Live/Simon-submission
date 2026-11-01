# Spec: Muse Spark second opinion, varied lines and the follower's language (TICKET-045, TICKET-046, analysis 1.9.0)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-31
Linked PRD: none (Part 7 TICKET-144 and TICKET-145; rubric audit `simon-part-7/docs/audit/rubric-2026-10-31/meta-ai.md`
items 3 and 5)
Linked CRD: none
Request Type: feature-mod
Risk Level: medium
Master spec: `part5-fault-analysis.md` ("Phrasing registry"). ADRs: ADR-0005 (phrasing registry), ADR-0008 (AI phrasing
in live mode), ADR-0007 (score). Tickets: TICKET-045 (second opinion and line variety, Part 7 TICKET-144), TICKET-046
(language, Part 7 TICKET-145). Output contract C1, agreed with the Part 7 display lane on 2026-10-31. Assumption:
ASM-014.

## Overview
Part 5 measures faults from skeletons and, in live mode, asks Muse Spark to say each fault as one sentence. Three
additions, all optional and additive:

1. **Second opinion.** Given the teacher's recording and the student's take as video files (`--expected-video`,
   `--follower-video`) in live mode, Part 5 makes one Muse Spark 1.3 call on the Meta Model API (Responses, both clips
   uploaded through the Files API, the pattern of Part 1's `meta_client.py`) with the measured faults. The model
   returns, per fault, whether it agrees and a one-line reason, and up to two observations of its own with a time. A
   guardrail checker drops any item that names a body part the follower clip does not show, a time outside the clip,
   or banned words. The result is the top-level `second_opinion` block. Nothing reads it back: the score, the faults
   and the insights are what they were.
2. **Varied lines.** The timed prompt drops the optional "keep going" ending, gives each fault one of four sentence
   shapes by its position, and a check after phrasing sends any model line that repeats a non-fact phrase of an
   earlier line back to its template line. No phrase that is not a measured fact appears in two lines of one result.
3. **Language.** `--lang <bcp47>` (API field `lang`) asks Muse Spark to write each line in the follower's language. The
   model returns the English line and the translated line together; the English line must pass the existing word test
   (`template.line_problem`), and the translated line must carry the same time, no other number and one line. A
   language Part 5 does not list falls back to English. English is the default.

Schema `1.9.0`: `phrasing.lang` and, per fault, `phrasing.faults[i].text` and `phrasing.faults[i].lang` are written
in every new document; `phrasing.lang_requested` when the request named a language Part 5 does not list;
`second_opinion` when clips were given.

## Why This Is Wrong (Dissent-First)
1. **A model that disagrees with the measurement undermines the score.** Answer: the second opinion is labelled as
   the model's opinion, sits in its own block, and no code path reads it into `faults`, `score` or `insights`
   (AC-SO-05, tested by running a take with every verdict a dispute and comparing the score bytes).
2. **A video model can invent things.** Answer: the guardrail drops items naming a body part whose joints are missing
   from the follower skeleton, a time outside the clip, any other number, praise, or the words this product never uses
   (medical, injury, pain, rehab, therapy, diagnosis, coach). What is dropped is listed in `second_opinion.rejected`
   with its reason.
3. **It costs money on every analysis.** Answer: it only runs when both clips are given and live mode is on. Clips are
   cut to at most 60 s, 8 fps and 480 px wide before upload; the input tokens are counted first and the call is refused
   above a per-call ceiling (default $0.50) or when the ledger total would pass the spend cap (default $5.00). Every
   call writes one ledger line.
4. **A translated line cannot be held by an English word test.** Answer: the model returns both lines in one answer;
   the English line carries the facts through the existing test, the translated line is held to the time, the
   absence of other numbers, the absence of an English time phrase before the time (TICKET-052) and the absence of
   praise (the English phrases, and the common ones of ten other Latin script languages; a language in another script
   is checked for the English phrases only). That a translation says
   the same as its English twin is ASM-014, revisited by a native speaker read of three languages (Part 7 TICKET-145
   acceptance).
5. **Index-based sentence shapes are a crude way to get variety.** Answer: the lines are phrased in parallel, so no
   call sees the others; the shape gives each a different start and the repetition check is the guarantee.

## User Story
As a student checked against a teacher's recording, I want a second look from a model that watched both videos, lines
that do not repeat themselves, and lines in my language, so that the result reads as feedback on my take and not as a
template.

## Vocabulary
- **Verdict**: `{fault_index, agrees, note}`: the model's agree or dispute on one measured fault.
- **Observation**: `{at_s, text, label: "model_opinion"}`: something the model saw that the measurement does not hold.
- **Supported body part**: a body part group (`template.GROUPS`) at least one of whose joints is usable (finite and at
  confidence `io.MIN_CONF` or more) in at least half of the follower clip's frames; a side word narrows it to that
  side's joints.
- **Fact word**: a word of the fault's `text`, `text_timed`, landmarks, side, lateral or time, or a function word.
- **Repeated phrase**: a three-word run, with at least one word that is not a fact word for its line, that also
  occurs in an earlier line of the same result.

## The field: `second_opinion` (contract C1)
```json
"second_opinion": {
  "status": "ok",
  "reason": null,
  "backend": "meta-model-api",
  "model": "muse-spark-1.3",
  "lang": "en",
  "verdicts": [{"fault_index": 0, "agrees": true, "note": "The right knee stays straighter than the teacher's at 1.4 s."}],
  "observations": [{"at_s": 2.1, "text": "The take is slower than the recording through the second lowering.",
                    "label": "model_opinion"}],
  "rejected": [{"kind": "observation", "index": 1, "reason": "names a body part the clip does not show (head)"}],
  "usage": {"input_tokens": 9123, "output_tokens": 411, "usd": 0.013151}
}
```
- `status`: `ok` (the model answered and the answer was read), `fallback` (a call was attempted or prepared and
  failed; `reason` says why, `verdicts` and `observations` are empty), `skipped` (not attempted: live calls are off, no
  key; `reason` says why). Absent when no clip was given, so documents without clips are unchanged.
- `verdicts`: at most one per fault, in fault order; a fault the model left out or whose verdict was dropped has none.
- `observations`: at most 2, each `at_s` inside the follower clip.
- `note` and observation `text`: one line, at most 140 characters, English.
- `rejected` and `usage` are additive extras for debugging and cost; Part 7 need not read them. `usage.estimated` is
  `true` when the answer held no token counts and the pre-call estimate was recorded instead.

## Acceptance Criteria
- AC-SO-01: with both clips, live mode and a key, one Responses request carries both uploaded files (teacher first,
  each preceded by a text label) and the faults as JSON; the answer becomes `second_opinion` with `status: "ok"`.
- AC-SO-02: verdicts are kept only for a valid `fault_index`, once per fault, with a boolean `agrees` and a note that
  passes the guardrail.
- AC-SO-03: observations are kept only with `at_s` inside the clip and text passing the guardrail; at most 2.
- AC-SO-04: the guardrail rejects a body part the follower clip does not show (the words of `template.GROUPS` and
  common others such as back, shins, calves, waist, eyes, each mapped to the joints that show it), a side whose joints
  it does not show, a time in the text outside the clip, any other number (digits, units and number words as
  `template.NUMBER` holds them, and counts such as "twice"), praise, the banned words, a link or domain, a control
  character other than CR and LF, more than one line, and more than 140 characters; each rejection is listed with its
  reason. Three words are read by how they are used (TICKET-050): "back" is the trunk only as a noun ("the back
  rounds"), not in "steps back", "shifts to the back", "back and forth" or "the back hip", "shoulder", "ankle", "toe",
  "wrist", "foot", "side" and the like; "half" is a number as an amount ("by half", "half as much", "half a beat"), not
  as a stretch of the take ("the second half", "the other half"); "face" after a body-part noun is a verb ("your feet
  face out") and names no head, the same reading `template.line_problem` gives a fault line (AC-VA-05).
- AC-SO-05: disputes never change the measured score, faults or insights (byte comparison).
- AC-SO-06: no key, live off, one clip missing or unreadable, an upload or call failure, unreadable JSON, the per-call
  ceiling or the spend cap: the block says `skipped` or `fallback` with the reason, the analysis is written and the
  CLI exits 0. A reason never holds the key or the model's text.
- AC-SO-07: every attempted call appends one ledger line (model, UTC time, tokens, USD; never the key or text); the
  ledger is opened and locked (flock) before the call, after the spend cap is checked once for the total before any
  upload and again, with the call's estimate, under the lock; so a spend that cannot be recorded is not made and two
  processes cannot both pass the cap. A call whose cost is not known is recorded at its pre-call estimate (the counted
  input and the full output allowance) with `estimated: true`: one that fails with no answer from the API (timeout,
  connection error, unreadable body), one the API answered with a 5xx status (a gateway may answer after the model ran)
  and one answered with HTTP 200 and a body that holds no input and output token counts (TICKET-050). A call the API
  refused with a status below 500 (such as 429) is recorded at $0. Two things refuse the call, as a fallback block
  before anything is uploaded (TICKET-050): `PART5_META_SPEND_CAP_USD` or `PART5_META_CALL_MAX_USD` set to something that
  is not a finite amount of USD from 0 up (a limit that cannot be read must not run as another one; unset or blank is
  the default), and a ledger that exists and cannot be read (an unknown total is not a total of 0; no ledger yet is 0).
- AC-VA-01: the timed prompt offers no closing phrase and asks for one of four sentence shapes by fault position.
- AC-VA-02: after phrasing, a model line that repeats a non-fact phrase of an earlier line falls back to its template
  line with the reason `<backend>: repeats a phrase of another line`.
- AC-VA-03: over a real fixture take with several faults, no phrase that is not a fact word repeats across lines of
  the result, whether the model repeats a filler or not (tested with a mocked model).
- AC-VA-04 (Part 7, Muse Glimmer 30B wrote "Arms elbows wider than the example at 0.4 s"): the local backend's system
  message, and only its, ends with grammar rules (`local_llm.grammar`): name the body part once, with no two body-part
  nouns side by side; for a timed fault also write a sentence with a verb ("is" after one part, "are" after two or
  more), with one example for another record. The failing line is never shown to the model; Muse Spark's prompt is
  unchanged.
- AC-VA-05: `template.line_problem` rejects a line, timed or not, with two body-part nouns side by side, with the reason
  `doubles the body part (arms elbows)`; the registry sends such a line back to its template line. A conjunction,
  comma or preposition between two nouns is not a doubling.
- AC-LA-01: `--lang` and the API field `lang` take a BCP 47 tag; the primary subtag is matched against the listed
  languages; an unlisted or malformed tag falls back to `en` and `phrasing.lang_requested` keeps what was asked, with
  control characters dropped and at most 35 characters kept. A tag of nothing but white space (or empty) is English
  with no `lang_requested`.
- AC-LA-02: for a listed language other than English, a model line is accepted only when its English twin passes
  `template.line_problem` and the translated line says the same time once (dot or comma decimal), no other digit,
  one line, at most 200 characters, no praise phrase (`translated line adds praise`): the English phrases in every
  language and, for the ten Latin script languages of `lang.PRAISE`, their common phrases; a language in another script
  and Vietnamese are checked for the English phrases only (see Compromises). The translated line also keeps no English
  time phrase: when one of `lang.ENGLISH_TIME_WORDS` (at, around, about, by, near, after, before, approximately,
  roughly; whole word, any letter case) stands directly before the time number, written with a dot or a comma and with
  or without a following "s", the line is refused with the reason `translated line keeps an English time phrase` and
  the fault takes the AC-LA-03 fallback. The set leaves out every word a listed language writes in that place (in, a,
  en, um, om, bei, vers and the like), and `tests/test_phrasing_time_phrase.py` pins a correct time phrase in each
  listed language as passing. For a language other than English the first sentence shape of the prompt has no English
  example (`prompt.SHAPE_TIME_FIRST_OTHER`), since the model copied its "At 1.9 s" into the translated line (TICKET-052).
- AC-LA-03: a fault that falls back gets its English template line and `phrasing.faults[i].lang` `"en"`; the template
  backend writes English and says so in the fault's reason when another language was asked.
- AC-LA-04: `phrasing.lang` and every `phrasing.faults[i].text` and `.lang` are in every new document; `text` equals the
  fault's `coaching`, and the document check (`output.validate_analysis`) rejects a document where it does not.
- AC-SC-01: schema 1.9.0 validates the new fields; `part5 doctor` notes the second opinion and the language; goldens
  rebuilt; documents of 1.8.0 and earlier still validate.

## Error Cases
| Case | Result |
|---|---|
| Clip path missing | `second_opinion.status` `fallback`, reason `follower clip not readable` (or expected) |
| A clip that cannot be read or written when it is prepared or sent | `fallback`, `clip not readable` (or `clip could not be prepared`) |
| Only one clip given | `skipped`, reason `both clips are needed` |
| Not live or no key | `skipped`, reason as in phrasing (`no key`, `live calls are off ...`) |
| Key file unreadable or empty | `fallback`, `key file unreadable` or `key file is empty` |
| ffmpeg absent | the original file is uploaded when at most 50 MB, else `fallback`, `clip too large to send` |
| HTTP error, timeout | `fallback`, `HTTP <code> on <step>` or `timeout on <step>` (step: `upload`, `count`, `responses`) |
| Model answer not JSON | `fallback`, `unreadable answer` |
| Over the ceiling or the cap | `fallback`, `estimated $x over the per-call limit of $y` or `spend cap reached` (the cap is checked before the upload too) |
| A limit variable set to something that is not an amount of USD from 0 up | `fallback` before any upload, `<variable> is not an amount of USD from 0 up` (the variable's name, never its value) |
| Ledger not writable, or held by another process for more than the longest call | `fallback`, `usage ledger not writable` or `usage ledger busy` |
| Ledger there but not readable (no permission, not text, a directory) | `fallback` before any upload, `usage ledger not readable` |
| Unknown language | English, `phrasing.lang_requested` holds the tag |

## Edge Cases
- A take with no faults still gets observations (verdicts empty).
- A verdict for an index the take does not have is rejected, not an error.
- A fault without `at_s` (an old document): its line is untimed; the translated line must hold no digit.

## Negative Requirements (What This Feature Must NOT Do)
- No new user-visible text uses the words coach, rehab, medical or injury.
- `second_opinion` is never read by `score`, `insights`, detection or the replay.
- No key is printed, logged, written or put in a reason; no model text goes in a reason.
- No call runs in tests, `make check-5` or goldens.

## Compromises
- Notes and observations are English for now; their checker is the English word list. The translated fault lines are
  the language feature.
- The translated praise check lists the common phrases of ten Latin script languages next to the English ones; a
  language in another script (Russian, Arabic, Hindi, Japanese, Korean, Chinese) and Vietnamese are checked for the
  English phrases only. `contracts/student-words.json` carries the English phrases and not `lang.PRAISE`. Part 7 was
  asked on 2026-11-01 (comms message `iem-20261101T044438Z-simon-part-5-fa43`, topic `part5-contract`) whether its guard
  needs the per-language phrases there, and answered the same day (ack `iem-20261101T044658Z-simon-part-7-1bd3`): no,
  Part 7's main does not read `lang.PRAISE`; the history guard that reads `contracts/student-words.json` is in the
  long-context candidate (claude-template-54, not yet integrated), which will ask Part 5 directly if it needs
  per-language praise. So the file stays English only (TICKET-050).
- Of the English words a translated line may keep, only the time position is checked (`lang.ENGLISH_TIME_WORDS`
  directly before the time number). The live run of 2026-11-01 kept "At 0.0 s" in the line written to the first
  sentence shape, the same opening as the run of 2026-10-31, and the record called that line Spanish. Any other English
  word in a translated line still rests on ASM-014 and the native-speaker read. The fallback costs the follower their
  language on that fault: they get the English template line, with `lang` `"en"` and the reason in `fallback_reason`.
  Option (c), asking the model to rewrite the line in each language, is not built: its output cannot be checked
  without that read, so it would add a second unchecked step to a line already held only by ASM-014. It reopens if the
  native-speaker read (ASM-014) or a later live run shows that the fallback costs the follower their language
  (TICKET-052, decided by the stakeholder-proxy on 2026-11-01).
- Video tokens are priced from the API's own count; the list rates are Part 1's (`$1.25` input, `$4.25` output per
  million tokens).

## Assumptions
- ASM-014: a translated line that carries the same time and no other number, returned in one answer with an English
  twin that passes the word test, says the same fact.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `docs/design/specs/second-opinion.md` | this spec | TICKET-045, TICKET-046 | yes |
| `docs/design/specs/second-opinion.md`, `docs/design/README.md` | design copy and its index line | TICKET-045 | yes |
| `part5/opinion/__init__.py` | `attach`, `run`: the block, statuses, reasons | TICKET-045 | yes |
| `part5/opinion/meta_api.py` | Meta Model API client: key, clip preparation, upload, count, respond, delete, ledger, cap | TICKET-045 | yes |
| `part5/opinion/prompt.py` | the request: labels, files, faults, instructions | TICKET-045 | yes |
| `part5/opinion/guard.py` | parse the answer, the guardrail, supported body parts, document validation | TICKET-045 | yes |
| `part5/phrasing/__init__.py` | `lang`, shapes, `text` and `lang` per fault, variety pass | TICKET-045, TICKET-046 | yes |
| `part5/phrasing/prompt.py` | no closing phrase, shapes, the language request | TICKET-045, TICKET-046 | yes |
| `part5/phrasing/variety.py` | repeated phrase finder | TICKET-045 | yes |
| `part5/phrasing/lang.py` | listed languages, tag resolution, the translated line check, answer parsing | TICKET-046 | yes |
| `part5/phrasing/local_llm.py`, `part5/phrasing/muse_spark.py` | `shape` and `lang` passed to the messages | TICKET-045, TICKET-046 | yes |
| `part5/phrasing/muse_spark.py`, `part5/opinion/meta_api.py` | the key file and ledger helpers the two share (`path_of`, `unavailable_for`, `read_key_from`, `open_ledger_at` with its lock); the cap before upload, the estimate for a failed call, checked env amounts, `-map_metadata -1`, a fixed upload name | TICKET-045 | yes |
| `part5/phrasing/template.py`, `part5/phrasing/lang.py`, `part5/opinion/guard.py`, `part5/output.py` | public names (`GROUP_RX`, `TIME`, `praise`), one `json_object`, the translated praise check, the tag cleaned and capped, guard numbers, links, control characters and more body words, `text` equals `coaching` | TICKET-045, TICKET-046 | yes |
| `tests/test_second_opinion_hardening.py`, `tests/test_second_opinion_keys.py` (new) | the review's fixes B2 to B5 and R1 to R17 | TICKET-045 | yes |
| `part5/opinion/meta_api.py`, `part5/opinion/__init__.py`, `part5/phrasing/muse_spark.py` | the recheck's residuals: a 5xx and a 200 with no token counts recorded at the estimate (`failed_usage`, `answered_usage`, `estimated_usage`), an unreadable ledger and a malformed limit refuse the call (`spent`, `_env_usd`, `check_settings`), one ledger-line writer and time format for both clients (`append_line`, `utc_now`) | TICKET-050 | yes |
| `part5/opinion/guard.py`, `part5/phrasing/template.py` | "back", "half" and "face" read by how they are used (`_BACK`, `QUANTITY`, `without_face_verbs`, `parts_named`) | TICKET-050 | yes |
| `tests/test_second_opinion.py`, `tests/test_second_opinion_hardening.py`, `tests/test_second_opinion_keys.py`, `tests/test_phrasing_grammar.py` | the recheck's tests, the held ledger, the shared six-answer opener | TICKET-050 | yes |
| `part5/pipeline.py`, `part5/cli.py`, `part5/api.py` | `lang`; `--lang`, `--expected-video`, `--follower-video` | TICKET-045, TICKET-046 | yes |
| `part5/output.py` | `SCHEMA_VERSION` 1.9.0, phrasing lang and `second_opinion` validated | TICKET-045 | yes |
| `part5/doctor.py`, `part5/contract.py` | notes, table rows | TICKET-045 | yes |
| `part5/phrasing/lang.py`, `part5/phrasing/prompt.py`, `tests/test_phrasing_time_phrase.py` (new) | the English time phrase check in `check_translated` (`ENGLISH_TIME_WORDS`), shape 0 without its English example for another language (`SHAPE_TIME_FIRST_OTHER`), a time phrase pinned in each listed language, the recorded live lines | TICKET-052 | yes |
| `part5/phrasing/local_llm.py`, `part5/phrasing/__init__.py`, `tests/test_phrasing_local_settings.py`, `docs/dev/DEVELOPING.md` | `PART5_LOCAL_LLM_TIMEOUT_S` and `PART5_LOCAL_LLM_THINK` for a slow local model (Part 7 TICKET-147; documented in `part5-fault-analysis.md`) | TICKET-045 | yes |
| `part5/profiles_report.py` | the fitness baseline digest also leaves out the 1.9.0 fields | TICKET-045 | yes |
| `tests/conftest.py`, `tests/test_phrasing*.py`, `tests/test_live_fallback.py`, `tests/test_near_misses.py` | the Meta key and ledger in the hermetic guard; record entries with `text` and `lang`; the prompt's new rules | TICKET-045 | yes |
| `contracts/analysis.schema.json` | the fields, version 1.9.0 | TICKET-045 | yes |
| `fixtures/output/analysis.example.json`, `analysis.no-faults.example.json` | goldens regenerated | TICKET-045 | yes |
| `docs/schemas.md`, `CONTRACT.md`, `docs/design/specs/integration-contract.md`, `docs/design/specs/part5-fault-analysis.md` | the fields, the 1.9.0 row, compatibility rows | TICKET-045 | yes |
| `tests/test_second_opinion.py`, `tests/test_phrasing_variety.py`, `tests/test_phrasing_lang.py` (new) | the ACs | TICKET-045, TICKET-046 | yes |
| tests asserting the schema version | `1.9.0` | TICKET-045 | yes |
| `part5/phrasing/local_llm.py` (`grammar`, `extra_rules`), `part5/phrasing/template.py` (`_doubled_part`), `tests/test_phrasing_grammar.py`, `docs/dev/DEVELOPING.md` | the local grammar rules and the doubled body-part test (AC-VA-04, AC-VA-05; Part 7) | TICKET-045 | yes |

## Delivery Verification Plan
- `uv run pytest -q tests/test_second_opinion.py tests/test_phrasing_variety.py tests/test_phrasing_lang.py` while
  building; `make test` once at the end.
- `make check-5-contract` 0 (goldens rebuilt); `make check-5` stdout byte-identical to main (both the recorded red).
- One live call: `part5 analyse --live --lang es --expected-video <teacher mp4> --follower-video <take mp4>` on the
  stock pair pexels-5034562 and pexels-5034577, the document and the ledger line kept as evidence with the cost.
- `python3 scripts/make_design_copies.py --check` 0; no em dash or en dash in changed files.

### Device/Platform Strategy
Not applicable: CLI and API only. Part 7 displays the block (Part 7 TICKET-144).

### Data (created through the product's own UI with synthetic accounts; never a DB or API seed)
- Synthetic accounts needed: none. Data: committed fixtures; the cached Pexels clips for the live call.

### Ratchet Initialization Plan
Not applicable.

### Boundary Layer Testing Plan
| Mapping Function | Input Format | Output Format | Test File |
|-----------------|-------------|---------------|-----------|
| `opinion.guard.read_answer` | model text | verdicts, observations, rejected | `tests/test_second_opinion.py` |
| `opinion.prompt.request` | file ids, faults | Responses body | `tests/test_second_opinion.py` |
| `phrasing.lang.read_pair` | model text | `(english, translated)` | `tests/test_phrasing_lang.py` |
| `phrasing.variety.repeats` | lines, faults | indices that repeat | `tests/test_phrasing_variety.py` |

## Dissent Review (MANDATORY, hooks block implementation without this)
Reviewed by: lane rubric-coach (implementer, self-review, model: opus). Independent review: the one consolidated
review before the final gate.
Date: 2026-10-31

### Concern 1: the second opinion reads as a judge of the score
Challenge: a dispute next to a deducted point invites "the AI says I was right". Impact: users trust neither.
Mitigation: label `model_opinion`, separate block, the score never reads it. Resolution: ADDRESSED_IN_SPEC.

### Concern 2: cost runs away under Part 7 load
Challenge: one video call per analysis. Mitigation: opt-in by clips plus live mode, per-call ceiling, cumulative cap,
ledger. Resolution: ADDRESSED_IN_SPEC.

### Pre-Mortem: It's 6 months from now and this feature was a disaster. Why?
1. The model names a body part outside the frame and a student acts on it. Likelihood: M, Impact: M, Mitigation: the
   supported body part check.
2. A translation says the opposite direction. Likelihood: L, Impact: M, Mitigation: ASM-014 and the native read.
3. The variety pass sends most lines to the template. Likelihood: M, Impact: L, Mitigation: the reason is recorded per
   fault and the fallback rate is visible in `phrasing.faults`.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|-------------------|---------|------|--------|
| TICKET-144: one call, both clips, agree or dispute, two observations | AC-SO-01 to 03 | `tests/test_second_opinion.py` | done |
| Dispatch: guardrail on joints and times | AC-SO-04 | `tests/test_second_opinion.py` | done |
| TICKET-144: disputes never change the score | AC-SO-05 | `tests/test_second_opinion.py` | done |
| TICKET-144: spend cap and fallback | AC-SO-06, AC-SO-07 | `tests/test_second_opinion.py` | done |
| TICKET-144: no phrase repeated across lines | AC-VA-01 to 03 | `tests/test_phrasing_variety.py` | done |
| Part 7: the local model wrote "Arms elbows wider than the example at 0.4 s" | AC-VA-04, AC-VA-05 | `tests/test_phrasing_grammar.py` | done |
| TICKET-145: cues in the follower's language | AC-LA-01 to 04 | `tests/test_phrasing_lang.py` | done |
| TICKET-050 R16 live run: "At 0.0 s, tus codos ..." kept an English time phrase | AC-LA-02 | `tests/test_phrasing_time_phrase.py` | done |
| Contract C1 | AC-SC-01 | `tests/test_second_opinion.py`, `make check-5-contract` | done |

## Deviations from PRD
None. Contract C1 says the block is present with a status; this spec leaves it absent when no clip was given, so
documents of takes without clips do not change.
