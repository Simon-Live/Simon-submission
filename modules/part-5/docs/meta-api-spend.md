# Meta API spend: Part 5

Part 5 calls one Meta model: Muse Spark (`meta-models/muse-spark-open-1026`) served by Baseten. It rewords each
fault as a coaching line (#20, ADR-0005, ADR-0008). No field that `make check-5` scores depends on it.

## When a call is made

| Run | Muse Spark called? |
|---|---|
| `make test`, `make check-5`, `make check-5-contract`, `make output-examples` | No. Phrasing is forced to `template`. |
| `part5 analyse` without live mode | No. `template`, or with `--phrasing muse-spark` the template line and the reason "live calls are off". |
| Live mode on (`--live`, `SIMON5_LIVE=1` or `META_LIVE=1`) and the key file present | Yes, one call per fault. |
| The same, with `--lang` (or the API field `lang`) a listed language other than English | One more call per analysis, for its cues and reasons (below). |
| Live mode on and no key file | No. The template line and the reason "no key". |

Every fault records its wording in `analysis.json` under `phrasing.faults[k]`: `backend`, `model` and
`fallback_reason`. A call that fails, times out or breaks the validator falls back to the template line for that
fault.

## Budget guard

| Limit | Value | Where |
|---|---|---|
| Calls per minute, per process | 30 (`PART5_MUSE_PER_MINUTE`) | `part5/phrasing/muse_spark.py` |
| Timeout per call | 10 s | `part5/phrasing/__init__.py` |
| Time one analysis may spend on phrasing | 20 s (`PART5_PHRASING_BUDGET_S`) | `part5/phrasing/__init__.py` |
| Muse Spark requests per client on the analysis server | 6 a minute, one at a time | `part5/api.py` |
| `max_tokens` per call | 2048, reasoning effort low | `part5/phrasing/muse_spark.py` |

## Ledger

Every call, whether it succeeds or not, appends one line to `~/.simon/baseten_usage.jsonl` (`PART5_BASETEN_USAGE_FILE`
in tests): UTC time, model, HTTP status and token counts. The key and the text never go in it.

Totals on the maintainers' host, read from that file on 2026-10-31 (last line 17:33:28Z):

| Calls | HTTP 200 | Prompt tokens | Completion tokens | Of which reasoning |
|---|---|---|---|---|
| 160 | 160 | 88,311 | 132,536 | 128,118 |

Calls by day: 1 on 2026-10-29, 37 on 2026-10-30, 122 on 2026-10-31. `docs/phrasing-review.md` counts 88 calls for
its first review, more than the ledger held then; the ledger is the record. No price per token is recorded here, so
the spend is given in tokens.

The 2026-10-31 no-praise re-review (`docs/phrasing-review.md`, "Re-review 2026-10-31") is 20 of those calls: HTTP 200
each, 12,324 prompt tokens, 14,363 completion tokens, 13,872 of them reasoning (the ledger held 140 lines before it
and 160 after).

## Cues in the follower's language (TICKET-080, `docs/specs/language-cues.md`)

For a listed language other than English, after the fault lines, `phrase_cues` makes one more call to the same backend and the
same key, limit and ledger: one request with every distinct English cue and reason of the document (usually 2 to 8 texts), own
timeout 20 s, an answer allowance of 6000 tokens (`BATCH_MAX_TOKENS`). It is skipped when the backend cannot run, and when the
document has no cue or reason. It appends one ledger line like every call. Nothing about the person or the clip is sent, only the
template text of the cues.

The one live run of each of Spanish, Arabic and Hindi on seed 5 Take 03 (2026-11-02, `fixtures/output/lang/PROVENANCE.md`) made
six calls, ledger lines 1222 to 1227: 3,393 prompt tokens and 5,556 completion tokens (5,200 of them reasoning), all HTTP 200.
At the list rates above (a stated estimate, the Baseten ledger has no USD) that is about USD 0.028 for the three, about
USD 0.009, 0.010 and 0.008 for Spanish, Arabic and Hindi. A fault line costs about 700 prompt and 1,000 completion tokens, the cue
call about 440 prompt and 570 to 1,190 completion tokens.

## History opinion (TICKET-072, branch `lane/history-opinion`)

The history opinion (`part5 history-opinion`, `POST api/history-opinion`, `docs/specs/history-opinion.md`) is a second
Meta call, separate from the Baseten phrasing above: one text-only Responses call to Muse Spark 1.3 on the Meta Model API
through the same client, per-call ceiling, spend cap and ledger as the per-take second opinion (`part5/opinion/meta_api.py`
and `docs/specs/second-opinion.md`). No field that `make check-5` scores depends on it.

| Run | Called? |
|---|---|
| `make test`, `make check-5`, `make check-5-contract`, `make output-examples` | No. Tests use a fake client. |
| `part5 history-opinion` or the route, with live mode off or no Meta Model API key file | No. A `skipped` document with the reason. |
| The same with live mode on and the key, and at least one fault with a second | Yes, one call per request. |

| Limit | Value | Where |
|---|---|---|
| Per-call ceiling | $0.50 (`PART5_META_CALL_MAX_USD`), on the counted input plus the full output allowance | `part5/opinion/meta_api.py` |
| Output allowance | 8000 tokens for a history call (`HISTORY_MAX_OUTPUT_TOKENS`) and for the per-take opinion (`SECOND_MAX_OUTPUT_TOKENS`, raised from 3000 by TICKET-102 after a live call used 3000 of 3000 and was cut off); 3000 is the default of a request that names none (`MAX_OUTPUT_TOKENS`); the estimate, the ceiling check and an estimated ledger line use the request's own | `part5/opinion/prompt.py`, `part5/opinion/meta_api.py` |
| Spend cap on the ledger total | $5.00 (`PART5_META_SPEND_CAP_USD`) | `part5/opinion/meta_api.py` |
| Takes, faults per take | 40 takes, 30 faults each | `part5/opinion/prompt.py` |
| Route requests per client | 6 a minute, one at a time, as for Muse Spark phrasing; 50 s timeout on the call | `part5/api.py` |

Every attempted call appends one line to `~/.simon/meta_usage.jsonl` (`PART5_META_USAGE_FILE` in tests): UTC time, model,
HTTP status, tokens, USD, `purpose` `history_opinion` and `prompt_version`. The key and the text never go in it. The stable
part of the request comes first and the question last, so cached input is priced at the cache rate when the provider reports it.

## Ask this take (TICKET-081, branch `lane/ask`)

Ask this take (`part5 ask`, `POST api/ask`, `docs/specs/ask-this-take.md`, ADR-0022) is a third Meta call: a tool-calling
agent on `muse-wonder-1.0` (a preview model with tool calling, Model API pay-as-you-go Standard mode) through the same
client, per-call ceiling, spend cap and ledger as the second opinion and the history opinion. No field that `make check-5`
scores depends on it.

| Run | Called? |
|---|---|
| `make test`, `make check-5`, `make check-5-contract`, `make output-examples` | No. Tests use a scripted fake client. |
| `part5 ask` or the route, with live mode off or no Meta Model API key file | No. The cached demo answer when the question and the take are its own, else the measured facts, with the reason. |
| The same with live mode on and the key | Yes: one call per turn, at most 4 turns per question. |

| Limit | Value | Where |
|---|---|---|
| Rates per million tokens | input $4.00, cached input $0.20, output $20.00 (dev.meta.ai pricing, checked 2026-11-02) | `part5/opinion/prompt.py` `ASK_RATES` |
| Rate limit (the provider's, per team) | 3,000 requests and 4,000,000 tokens a minute | dev.meta.ai |
| Turns and tool calls per question | 4 model calls, 8 tool calls; the last turn has no tools and says so (`prompt.ASK_LAST_TURN`); the turn before it keeps its tools and asks for the `seek` and the `spotlight` (`prompt.ASK_SEEK_TURN`) | `part5/ask/agent.py` |
| Output allowance per turn | 3000 tokens (`ASK_MAX_OUTPUT_TOKENS`), $0.06 at the output rate | `part5/opinion/prompt.py` |
| Per-call ceiling | $0.50 (`PART5_META_CALL_MAX_USD`) on each turn's estimate, and on what the question has spent plus the next turn's estimate | `part5/opinion/meta_api.py`, `part5/ask/agent.py` |
| Spend cap on the ledger total | $5.00 (`PART5_META_SPEND_CAP_USD`), shared with the other Meta calls | `part5/opinion/meta_api.py` |
| Route requests per client | 6 a minute, one at a time, as for the other paid routes; 50 s timeout on each call | `part5/api.py` |

Every attempted call appends one line to `~/.simon/meta_usage.jsonl`: UTC time, `model` `muse-wonder-1.0`, HTTP status,
tokens, USD, `purpose` `ask`, `prompt_version` and `turn`. The key and the text never go in it. The answer's `spend`
sums the lines of the calls that answered.

Live record, 2026-11-02. One live exchange, through `part5 ask --live --stream` on the seed 5 Take 03 analysis and replay
as `POST api/analyse` builds them for the page (fitness, template wording), with the question "Why is my right foot
flagged, and when is it furthest out?". Four ledger lines (05:11:54Z to 05:12:42Z, HTTP 200 each): 1501, 1795, 2270 and
1354 input tokens (116 and 1780 of them cached on turns 2 and 3), 293, 1093, 904 and 2146 output tokens, $0.011864,
$0.028599, $0.020396 and $0.048336, $0.109195 in all. Five tool calls (`get_faults`, `compare_with_teacher`,
`get_joint_angle`, `seek`, `spotlight`); the answer passed the validator with no number replaced. Its document is
`fixtures/output/ask.example.json`, the demo's cached answer until the fifth exchange below replaced it. The ledger total before it was $1.812258.

Second live exchange, 2026-11-02 (lane/fix114b, R14 of the 1.14.0 consolidated review: the cached answer says the code name
`foot_out`). One exchange through `part5 ask --live --stream` on the same Take 03 analysis and replay, built the same way, with
the same question, meant to replace the cache after a trial change that gave each measure in the tool results a `plain_name`
("foot out from under the hip" for `foot_out`) and added one instruction sentence (prompt `ask-2`). Four ledger lines (lines 155
to 158 of the file, 12:15:50Z to 12:16:48Z, HTTP 200 each, `prompt_version` `ask-2`): 1531, 1842, 2339 and 1432 input tokens
(1780 of them cached on turn 3), 427, 928, 670 and 2091 output tokens, $0.014664, $0.025928, $0.015992 and $0.047548,
$0.104132 in all. The model answered no turn with text: on the fourth turn, sent without tools, it still asked for tool calls,
so the exchange ended with the measured facts (`no answer within the turn limit`) after four tool calls (`get_faults`,
`compare_with_teacher` twice, `get_joint_angle`) and no UI action. That document cannot be the cache, whose `source` must be
`model`, and the cache's `take_sha256` covers the `get_faults` result, so the trial change was taken back with it: the shipped
cache stays the first exchange's, code name included. The ledger total before it was $2.104426.

Third and fourth live exchanges, 2026-11-02 (lane/fix114c, N4 of the 1.14.0 recheck: the last turn now says that no tool is
left, prompt `ask-3`). Each went through `part5 ask --live --stream --out` on the same Take 03 analysis and replay, built the
same way (their `take_sha256` is the cache's), with the same question; each made four calls, HTTP 200 each, and the stream's
events equal the document's lists.
- Third: ledger lines 174 to 177 (13:55:21Z to 13:56:14Z): 1501, 1797, 2228 and 1351 input tokens (1396 and 116 of them
  cached on turns 2 and 3), 235, 663, 698 and 1244 output tokens, $0.010704, $0.015143, $0.022431 and $0.030284, $0.078562 in
  all. The ledger total before it was $2.336343.
- Fourth: ledger lines 179 to 182 (14:01:36Z to 14:02:35Z; line 178 is another caller's second opinion): 1501, 1795, 2026 and
  1353 input tokens (116 and 1396 of them cached on turns 1 and 2), 269, 1159, 597 and 1371 output tokens, $0.010943,
  $0.025055, $0.020044 and $0.032832, $0.088874 in all. The ledger total before it was $2.425726.

Both answered on the fourth turn, the one sent without tools and with the new message, after the same four tool calls
(`get_faults`, `get_joint_angle`, `compare_with_teacher` twice), and both answers passed the validator with no number
replaced (`source` `model`, `validated` true). Neither says the code name `foot_out` ("the right ankle's foot-out measure, the
foot out from under the hip"; "the right ankle's foot-out angle from under the hip"). Neither made a UI action: the model
spent its tool turns reading and had no tool left to call `seek` or `spotlight` with. The shipped example must carry UI
actions (`tests/test_ask_cli_api.py`, the demo's seek and spotlight), so neither document replaced the cache: it stays the
first exchange's, code name included. The two documents are kept outside the repository with the lane's evidence.

Fifth live exchange, 2026-11-02 (lane/askseek, TICKET-081: the turn before the last now asks for the `seek` and the
`spotlight`, prompt `ask-4`). One exchange through `part5 ask --live --stream --out` on the same Take 03 analysis and replay,
built the same way (their `take_sha256` is the cache's), with the same question, HTTP 200 on all four calls. Ledger lines 187 to
190 of the file (14:35:30Z to 14:36:25Z): 1501, 1797, 2339 and 1663 input tokens (1396 and 116 of them cached on turns 2 and
3), 284, 915, 967 and 1693 output tokens, $0.011684, $0.020183, $0.028255 and $0.040512, $0.100634 in all. The ledger total
before it was $2.549331. Six tool calls (`get_faults`, `get_joint_angle`, `compare_with_teacher`, `seek`, `spotlight`,
`compare_with_teacher`), and two UI actions: `seek` to 2.77 s and `spotlight` of the right ankle at 2.77 s, the time the
answer gives as the furthest out. The answer passed the validator with no number replaced (`source` `model`, `validated`
true) and says no code name ("the right ankle was measured too far out from under the hip"). It is now
`fixtures/output/ask.example.json`, copied byte for byte from the file `part5 ask --out` wrote, so R14 of the 1.14.0
consolidated review (the code name `foot_out` in the cached answer) is closed with it. This was the only exchange of the lane.
In 1.14.1 (TICKET-100) the file's `take_sha256` was recomputed for the canonical number form of `Take.sha256()` (every number a float, -0.0 as 0.0), through the product path from the same take, with no new call; no other byte changed.
