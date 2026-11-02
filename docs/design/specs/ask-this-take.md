# Spec: Ask this take, a Muse Wonder tool-calling agent over one analysed take (TICKET-081)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted (contract first: this spec and `contracts/ask.schema.json` go to Part 7 before the code lands)
Date: 2026-11-02
Linked PRD: none (the hub's TICKET-269, Part 5's share in TICKET-081; the operator's fan-out order of 2026-11-02 04:10Z)
Linked CRD: none
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. Sibling specs: `history-opinion.md` and `second-opinion.md` (the same key, live
switch, spend ledger and caps). ADR: ADR-0022 (the model, the validator, the spend reported only).

## Overview
A follower asks one question about one analysed take ("why is my right foot flagged?", "when is my knee bent the
most?") and gets a short answer in plain words, with the moments the answer is about. Part 5 answers it with
`muse-wonder-1.0` on the Meta Model API's Responses endpoint, as an agent with five tools that read only the take it
was given: `get_faults`, `get_joint_angle`, `compare_with_teacher`, and two actions for the player, `seek` and
`spotlight`, which the server records and returns and never carries out. Every number in the answer must be a number
some tool returned in that same exchange, within its rounding; an answer that says any other number is replaced by
the measured facts, a template answer built from the tool results, and the replacement is logged. The model calls go
through Part 5's one spend path (`meta_api.call`: the per-call ceiling, the spend cap and the locked ledger) with the
ledger purpose `ask`. With no key, live mode off or a failed call, a cached answer (for the demo take) or the measured
facts come back with the reason. The surfaces are `POST api/ask` (JSON, or a `text/event-stream` that sends each
tool call as it happens so the page can move while the agent answers) and `part5 ask`. Nothing in `analysis.json`
changes, and `make check-5` does not call it.

Part 5 has no users. Who may ask about which take is Part 7's job ownership: Part 7 must refuse a question about
another user's take before it calls Part 5, with no tool call (the hub's AC-3 negative). Part 5 answers about the
two documents it is sent and nothing else.

## Why This Is Wrong (Dissent-First)
1. A model that reads numbers back can still misread them. The validator checks that each number in the answer is a
   number some tool returned, not that it is said about the right thing ("your knee bends 36.1 degrees" when 36.1 is
   the elbow). Mitigation: the tools return few, named numbers; the answer is labelled as the model's; the tool calls
   and their results ship beside it so Part 7 can show the evidence. A check of meaning is not built (Compromises).
2. A preview model can be slow, rate limited or withdrawn. Mitigation: a call timeout, a turn limit, the measured
   facts on any failure, and one cached answer for the demo take, so the demo never depends on a live call.
3. Streaming adds a second response shape to a server that has only had JSON. Mitigation: the stream is opt-in
   (`stream: true`), its last event is the same document the JSON route returns, and an error before the stream
   starts is the usual JSON error with its status.
4. The model may answer a question that is not about the take (a medical question, another take). Mitigation: the
   instructions say to answer only about this take; the answer passes the student word guard
   (`opinion.guard.unsafe_problem`: no link, no control character, none of the words this product never uses) and the
   number validator, or it is replaced. Who may ask is Part 7's (Overview).

## User Story
As a follower looking at my analysed take
I want to ask a question in my own words and see the player move to the moment the answer is about
So that I understand what was measured without reading the fault table

## Vocabulary
- **Take**: one `analysis.json` (`simon.analysis.v1`) and the `replay.json` (`simon.replay.v1`) written with it by
  `part5 analyse --replay`. The tools read only these two documents.
- **The take's clock**: seconds as written in the follower file, `replay.follower_t` (the clock of `faults[].at_s`).
  Every `t` in a tool argument, a tool result and a UI action is on it.
- **Exchange**: one question, from the first model call to the answer. The model may call tools over several model
  calls (turns); "a tool result of the same exchange" is any result returned for this question.
- **Measured facts**: the answer Part 5 writes itself from the tool results of the exchange, in fixed sentences.

## The request (`contracts/ask.schema.json`, `$defs.request`)
```json
{"question": "Why is my right foot flagged?", "analysis": {"format": "simon.analysis.v1", "...": "..."},
 "replay": {"format": "simon.replay.v1", "...": "..."}, "stream": false}
```
- `question`: text, 1 to 500 characters after the outer blanks are removed (`MAX_QUESTION_CHARS`).
- `analysis`: a Part 5 analysis (an object, `format` `simon.analysis.*`, a `faults` list).
- `replay`: the replay of the same take (`format` `simon.replay.v1`; its lengths and indexes pass the checks
  `make check-5-contract` applies, `contract.replay_problems`). Every fault's `follower_frames` must lie inside the
  replay's follower frames, else the two are not of one take.
- `stream`: optional, `true` for the event stream; anything but `true`, `false` or absent is refused.

## The response (`simon.ask.v1`, `contracts/ask.schema.json`)
```json
{
  "format": "simon.ask.v1",
  "schema_version": "1.0.0",
  "question": "Why is my right foot flagged?",
  "answer": "Your right foot sits 9.8 degrees further out than the example's at 1.9 s.",
  "source": "model",
  "model": "muse-wonder-1.0",
  "live": true,
  "validated": true,
  "replaced_numbers": [],
  "fallback_reason": null,
  "take_sha256": "3f1c...",
  "tool_calls": [
    {"name": "get_faults", "arguments": {}, "ok": true, "result": {"count": 1, "faults": ["..."], "take": {"start_s": 0.0, "end_s": 3.433333}, "warnings": []}},
    {"name": "seek", "arguments": {"t": 1.9}, "ok": true, "result": {"type": "seek", "t": 1.9, "limb": null}}
  ],
  "ui_actions": [
    {"type": "seek", "t": 1.9, "limb": null},
    {"type": "spotlight", "t": 1.9, "limb": "right_leg", "joints": ["right_hip", "right_knee", "right_ankle"]}
  ],
  "spend": {"usd": 0.0123, "ledger_purpose": "ask", "calls": 2, "input_tokens": 2100, "output_tokens": 190,
            "cached_tokens": 0, "estimated": false}
}
```
- `source`: `model` (the model's own words, which passed the validator and the word guard), `cache` (the cached
  answer of the demo take, see Cache), `measured_facts` (Part 5's template answer from the tool results).
- `model`: `muse-wonder-1.0` when a model call was made for this question or the cached answer came from one, else
  null. Part 7's models-used panel lists Muse Wonder for the take from it (hub AC-5); `live` says whether a call was
  made now.
- `live`: true when at least one model call was sent for this question.
- `validated`: true only when `answer` is the model's own words and every number in it was found in a tool result of
  the exchange. False for the measured facts.
- `replaced_numbers`: the numbers of the model's answer that no tool result held, in the order written, when the
  answer was replaced for that reason; empty otherwise.
- `fallback_reason`: null when `source` is `model`; otherwise why the model's answer is not shown: `no key`,
  `live calls are off (...)`, a call failure as the second opinion words it (`HTTP 429 on responses`,
  `timeout on responses`, `estimated $0.62 over the per-call limit of $0.50`, `spend cap reached`, ...; an HTTP
  failure whose error body has a type and message adds them after a colon, `HTTP 400 on responses:
  invalid_request_error: <message>`, scrubbed of the key, a masked key, a URL and a bearer token, with control and bidi
  characters dropped, cut to 160 characters and left off when it fails `guard.unsafe_problem` or the status is 401 or
  403, TICKET-099 and R4 of the 1.14.1 review),
  `a number in the answer is not in any tool result`, the word guard's reason, `no answer`, `answer too long`, or
  `no answer within the turn limit`. It never holds the key, and the model's answer is never put in it; the API's own
  error text is the one third-party text a reason can hold, scrubbed as `meta_api._scrubbed` does, a heuristic that
  is a hint for the operator, not a promise.
- `take_sha256`: the SHA-256 of the take's tool data (the `get_faults` result and the replay's joints, frames, times
  and alignment, and, when a body mask leaves anything out, its masked joints and measures not scored, as canonical
  JSON). The numbers are canonical too (1.14.1, TICKET-100): every number is taken as a float and -0.0 as 0.0, so a
  copy the page's JavaScript re-serialised (`6` for `6.0`, `0` for `-0.0`) and one Python wrote carry the same value;
  floats are not rounded, since both sides write the shortest text that parses back to the same double. Two requests
  about one take carry the same value. The 1.14.0 review's R3 added the mask's lists to the data only for a take whose mask
  leaves something out, so a take with no mask, or the `full_body` preset, kept its digest through R3; the 1.14.1 number
  form then changed every digest once (that take's too, and the cached example's with it), and no digest has changed since.
- `tool_calls`: every tool call of the exchange in the order run: `name`, `arguments` (as parsed, or `{}` when they
  were not a JSON object), `ok` and `result` (the object the model was sent; `{"error": "..."}` when `ok` is false).
  A call Part 5 made itself for the measured facts (none of the model's results held a fact) carries `"by": "part5"`.
- `ui_actions`: the `seek` and `spotlight` calls that were valid, in call order. `seek`: `{type, t, limb: null}`.
  `spotlight`: `{type, t, limb, joints}`, `joints` the canonical joints to highlight (as `faults[].joints`).
  Nothing on the server acts on them; the player applies them in order.
- `spend`: what the model calls of this question cost as the ledger records them: `usd`, `ledger_purpose` (`ask`),
  `calls`, the token counts and `estimated` (true when a line was recorded at the pre-call estimate). Zero calls and
  $0 for a cached or measured-facts answer that made no call. A call that failed is in the ledger and not in `spend`.

## The tools
Each tool reads only the take it was given; none reads a file, the network or another take. Every argument is
validated by Part 5 (the API's `strict` defaults to false): a bad one is an error result the model sees, `ok: false`,
and changes nothing. An error never echoes an argument name or any other text the model sent; it names only what the
tool takes (`unknown argument; this tool takes t`). Every string of the model's arguments, each key and each value, must
pass the answer's word guard (`guard.shown_problem`: no control character, a bidi override included, no link, none of
the words this product never uses, no praise), since the arguments ship in `tool_calls` and the stream: a call that
fails it is not run, and its record, in the document and the stream alike, is `arguments: {}`, `ok: false` and the
error `arguments hold text that cannot be shown` (R1 of the 1.14.0 review).

| Tool | Arguments | Result |
|---|---|---|
| `get_faults` | none | `{count, faults, take: {start_s, end_s}, warnings}`: each fault's `index`, `measure`, `measure_kind`, `joint`, `joints`, `body_part`, `side`, `direction`, `magnitude_deg`, `peak_deg`, `threshold_deg`, `unit`, `at_s`, `follower_t_s`, `text`, `text_timed`, `cue`, `lateral` and `lateral_m` as the analysis holds them (a field the fault lacks is left out); `warnings` the warning codes |
| `get_joint_angle` | `joint` (a name of `replay.joints`), `t0`, `t1` (seconds on the take's clock, inside the take, `t0` not after `t1`) | `{joint, t0, t1, frames, measures}`: per measure read at that joint (`measures.MEASURES` whose joint it is), `measure`, `side`, `means`, `unit`, `min`, `max`, `mean` (degrees, 1 decimal), `min_at_s`, `max_at_s` (2 decimals) and `seen_frames`, from the replay's follower frames in that range (the nearest frame when none falls inside) |
| `compare_with_teacher` | `joint`, `t` | `{joint, t, take_t_s, example_t_s, measures}`: the follower frame nearest `t`, the example frame the alignment shows with it (`replay.exp_to_fol`: the middle of the example frames mapped to that follower frame, else the nearest), and per measure `take_deg`, `example_deg` and `difference_deg` (take minus example, the sign of `magnitude_deg`) |
| `seek` | `t` | `{type: "seek", t, limb: null}`; recorded as a UI action |
| `spotlight` | `limb`, `t` | `{type: "spotlight", t, limb, joints}`; `limb` is a name of `replay.joints` or one of `left_arm`, `right_arm`, `left_leg`, `right_leg`, `torso`, `head`; recorded as a UI action |

A joint at which no measure is read (the face points, the wrists) is an error naming the joints that have one. A time
outside the take (`replay.follower_t` first to last) is an error naming the range. A measure a frame cannot give (a
joint not seen) is null.

A take whose analysis declares a body mask (`body_mask`, ADR-0023, `docs/design/specs/body-mask.md`) answers only about the
body it scored (R3 of the 1.14.0 review): the replay still holds the masked limbs' made-up motion, and the tools never
read it. `tools.Take` reads `body_mask.masked_joints` and `body_mask.not_scored_measures`. `get_joint_angle` and
`compare_with_teacher` refuse a masked joint, or a joint whose every measure is not scored (the hips of a seated take,
whose thigh measures read the knee), with the error `that joint is not scored in this take, by the follower's setting;
it has no measurement to give`; at a scored joint they leave out a measure the mask drops. `spotlight` refuses a limb
or joint that holds a masked joint (`that limb is not scored in this take, by the follower's setting; it cannot be
highlighted`). The block must pass the analysis's own check (`mask.validate_mask_block`), else the request is refused,
`400` field `analysis`.

## The validator (hub AC-2)
- The numbers of an answer are its digit runs (`12`, `9.8`, `0.70`) and the number words the student word test
  counts (`template.NUMBER`'s words: zero, two to twenty, the tens, hundred, thousand); "one" is not a number here.
- The numbers of the exchange are every number in every successful tool result (`ok` true), including numbers inside
  a result's text, and every argument the result echoes. An error result counts for nothing: it holds no measurement,
  and counting it would let the model launder a number through a refused call (R1 of the 1.14.0 review: `seek`
  sent `{"87.5": 1}`, the error echoed `87.5`, and an answer saying 87.5 degrees passed).
- A number `a` written with `d` decimals is found when some number `v` of the exchange has
  `abs(abs(v) - abs(a)) <= 0.5 * 10^-d` (so `10` is found for 9.8 and `9.8` for 9.81; a sign is not a number: "9.8
  degrees less" reads the tool's -9.8).
- An answer with a number not found is replaced by the measured facts: `validated` false, `replaced_numbers` the
  numbers, `fallback_reason` `a number in the answer is not in any tool result`, and one warning line on the
  `part5.ask` logger with the numbers (never the model's text or the key).
- An answer that counts in words, which no tool returns, is replaced the same way with the reason `a count in words
  is not in any tool result` and `replaced_numbers` empty (R2 of the 1.14.0 review): the second opinion's
  `guard.QUANTITY` (twice, thrice, double, triple, halves, a dozen or dozens, and "half" as an amount but not as a
  stretch of the take, "the second half"), and `guard.COUNT_WORDS`, an ordinal or a fraction past "second" ("the fifth
  rep", "a third", "a quarter") and the plural of a number word ("tens", "hundreds", "thousands"). "first" and "second"
  are not counts here ("at first", "a second"). The numbers are checked first, so an answer holding both a number no
  tool returned and a count word lists its numbers.
- The answer is also refused, and replaced the same way with the guard's reason, when it is empty, over 1200
  characters (`answer too long`) or fails `opinion.guard.shown_problem` (`unsafe_problem`: a control character, a
  link, a word this product never uses; and praise). Runs of blanks and line breaks are joined to one space before the
  checks.
- The measured facts are built from the exchange's results: each fault as its `text_timed` and size ("Right foot too
  far right at 1.9 s: 9.8 degrees more than the example."), each joint range, each comparison. When no result holds a
  fact, Part 5 calls `get_faults` itself (`by: "part5"`). Every number in them comes from a result, so they pass the
  validator by construction, and a test proves it. They are held to the schema's `answer.maxLength`, 4000 characters
  (`guard.MAX_FACTS_CHARS`, R13 of the 1.14.0 review): when every fact does not fit, the facts are kept whole and in
  order from the first while they fit, followed by `The rest of the measured facts are in the tool calls.`; a sentence
  is never cut.

## The agent loop
- One Responses body per turn: `model` `muse-wonder-1.0`, `max_output_tokens` 3000 (`ASK_MAX_OUTPUT_TOKENS`),
  `tools` (the five, `{"type": "function", "name", "description", "parameters"}` at the top level), and `input`: on the
  first turn one user message (the instructions, the take's span and joint names, then the question, stable text
  first); on a later turn `previous_response_id` and one `function_call_output` item per `call_id` (`output` the
  result as JSON text).
- An `output` item of type `function_call` is a tool call (`name`, `arguments` as JSON text, `call_id`); several in
  one turn are run in order. A turn with no tool call ends the exchange with its text (`meta_api.output_text`). A
  body that is not a JSON object, or whose `output` is not a list (`{"output": 5}`), is an `unreadable answer`, a
  failed call like any other (R5 of the 1.14.0 review). So is an `output` item that is not an object, and a message whose
  `content` is not a list of objects (`"content": 5`, `null`, missing, `[5]`): N1 of the 1.14.0 recheck, which raised
  TypeError through the reader the second opinion and the history opinion share (`meta_api.output_text`).
  `tool_choice` is left at `auto`, so a plain text reply on the first turn is an answer like any other.
- Limits: at most 4 model calls (`MAX_TURNS`) and 8 tool calls (`MAX_TOOL_CALLS`). A call past the tool limit gets
  the error result `tool call limit reached`. The last allowed turn is sent without `tools`, so the model answers,
  and its input ends, after the tool results, with one user message that says so plainly (`prompt.ASK_LAST_TURN`:
  no more tools are available, a tool call now cannot be answered, answer now in text from the tool results already
  had; N4 of the 1.14.0 recheck, prompt `ask-3`), since the model asked for tools on that turn in one of the two live
  exchanges before it. An exchange that still has no text, a tool call on the last turn included, ends with the
  measured facts, `no answer within the turn limit`.
- The turn before the last (the third of four) keeps its `tools` and its input ends, after the tool results, with one
  user message (`prompt.ASK_SEEK_TURN`, `prompt.ask_request(..., seek=True)`, prompt `ask-4`, lane/askseek): this is
  the last turn with tools and the next has none, so call `seek` with the time of the moment the answer is about and
  `spotlight` with the limb or joint it is about, in this turn and beside any read still needed; a `seek` or
  `spotlight` already made for that moment need not be repeated. The two live answers of N4 had spent every tool turn
  reading and had no UI action, so the page's replay never moved to the moment the answer talks about (hub AC-3). The
  message is sent on that turn only: an exchange that answers earlier never sees it, and the last turn is exactly
  what N4 made it (no `tools`, `ASK_LAST_TURN` last, never both messages). The model still chooses the time and the
  limb; Part 5 only asks, and runs a `seek` or `spotlight` as it runs any other call (arguments checked, `ui_action`
  only for a valid one).
- Each model call goes through `meta_api.call(client, body, "ask", rates=WONDER_RATES, model=..., prompt_version=...,
  turn=n)`: counted, priced at muse-wonder-1.0's list rates (per million tokens: input $4.00, cached input $0.20,
  output $20.00; dev.meta.ai pricing, checked 2026-11-02), checked against the per-call ceiling
  (`PART5_META_CALL_MAX_USD`, $0.50) and the spend cap (`PART5_META_SPEND_CAP_USD`, $5.00) under the locked ledger,
  sent and recorded: one line per call with `model` `muse-wonder-1.0`, `purpose` `ask`, `prompt_version`, `turn`, the
  HTTP status, the tokens and USD, never the key or text.
- The estimate of the first turn is its counted input (`/responses/input_tokens` on `model` and `input`, as for the
  other calls) plus the tool declarations at one token per 3 characters. A later turn is not counted (its input
  answers calls the count endpoint has not seen): its estimate is the previous turn's input and output tokens (the
  API bills the stored context of `previous_response_id` as input), plus its own input and the tool declarations at
  one token per 3 characters. Both add the full output allowance at the output rate. The whole question is held to
  the per-call ceiling as well: a later turn whose estimate, added to what the question has already spent, passes it
  is refused before it is sent (`estimated $x for this question over the per-call limit of $y`). An oversize request
  is refused before any call (hub AC-4).
- Live calls need the Meta Model API key file AND live mode (`--live`, `SIMON5_LIVE=1` or `META_LIVE=1`), as for the
  second opinion (`meta_api.unavailable`). The key is read at the call by `meta_api.read_key` and used for the
  `Authorization` header only: never printed, logged, written or put in a reason.
- Each HTTP call has a 50 s timeout on the API route (`ASK_TIMEOUT_S`) and the client's 300 s on the command line.

## Cache (the demo)
`fixtures/output/ask.example.json` is the document of one live exchange through `part5 ask --live` on the seed 5
Take 03 (`exercise_front_good_03_foot_out-right`, fitness, template wording) and its replay, as `POST api/analyse`
builds them for Part 5's page from the two samples (`docs/meta-api-spend.md` records the exchange). When no call can be made
or a call fails, and the question (blanks joined, case folded) and `take_sha256` are the example's, the response is the
example's `answer` with `source` `cache`, `model` `muse-wonder-1.0`, `validated` true (its numbers are checked again
against its own tool results, and its arguments pass the word guard) and the `fallback_reason` of this request.
The `take_sha256` match is on the canonical number form (every number a float, -0.0 as 0.0), so the files the page
re-serialised and the ones Python wrote reach the same cached answer (TICKET-100); the example's digest was recomputed
for that form in 1.14.1 from the same take, with no new call.

One rule holds whether or not a call was made first (R4 of the 1.14.0 review), so the document, the stream and AC-ASK-08
agree:
- `tool_calls` and `ui_actions` are the ones this exchange already made, kept, followed by the example's own. The stream
  sends the example's as `tool_call` and `ui_action` events after the live ones, so its events are the document's lists.
- `live` is true when a call was sent for this question, and `spend` is what the answered calls cost as the ledger
  recorded them, as for any answer: zero when no call was made, and a call that failed is in the ledger and not in
  `spend`.
- The example is used only when the calls already made and its own together fit `tool_calls` (at most 9,
  `MAX_LISTED_CALLS`); otherwise the response is the measured facts of the calls already made.

Any other question gets the measured facts.

## Streaming (`stream: true`)
The route answers `200` with `Content-Type: text/event-stream` and these events, each `event: <name>` and one
`data: <JSON>` line and a blank line:

| Event | Data | When |
|---|---|---|
| `tool_call` | one `tool_calls[]` item | as each tool call is run |
| `ui_action` | one `ui_actions[]` item | right after the `tool_call` of a valid `seek` or `spotlight` |
| `answer` | the whole `simon.ask.v1` document | last; the stream then ends |
| `error` | `{"error": {"field": "server", "message": "..."}}` | only if the server fails after the stream started; it ends the stream |

The answer's text is not streamed: it is shown only after the validator has passed or replaced it. A request that is
refused (400, 405, 413, 429) is refused before the stream starts, with the usual JSON error. `part5 ask --stream`
prints the same events on stdout.

## The command
```
part5 ask <analysis.json> <replay.json> "<question>" [--live] [--stream] [--out FILE]
```
- Exit `0` when a document was produced, whatever its `source`; `1` for an input or output problem (a file missing,
  unreadable, over 32 MiB, not JSON, not an analysis or a replay, the two not of one take, `--out` not writable);
  `2` for a usage error (no question, a question over 500 characters).
- Without `--out` the document is the only thing on stdout and a summary line goes to stderr; with `--out` the
  document is written there and the summary goes to stdout. `--stream` prints the events on stdout instead of the
  document (with `--out`, the document is written as well).

## The route
`POST api/ask` with the request above. `200` with the document (or the stream). `413` for a body over
`MAX_BODY_BYTES`; `400` naming the field for a body that is not JSON or not an object, a `question`, `analysis`,
`replay` or `stream` that is wrong, and two documents not of one take; `405` for any other method.

The limits of the route (R6 and R12 of the 1.14.0 review):
- Frames: the replay's example and take frames together at most 12,000 (`api.MAX_ASK_FRAMES`, two clips of
  `pipeline.MAX_FRAMES` 6,000, the bound `POST api/analyse` puts on each upload; counted together because a replay
  compared rep by rep tiles the example's reps, so its example side alone can pass 6,000). Over it: `400` field `replay`,
  `replay: <n> frames in the example and the take together, the limit is 12000`.
- Per client: a request that will make a model call counts against the same per-client Muse limit as the other paid
  routes (6 a minute, one at a time); one that cannot (no key, live mode off) counts against the route's own limit
  (`api.ASK_FREE_PER_MINUTE`, 30 a minute, one at a time), since it still parses a body of up to `MAX_BODY_BYTES` and
  runs the tools. A refused request (`400`, `405`, `413`) takes no slot. A slot is released when the exchange ends, on
  the exchange's own thread for a stream.
- Over either limit: `429` with `Retry-After`, field `question` and the message `Too many questions from this address.
  Wait a moment, then ask again.` (the Ask box shows it), not the phrasing route's Muse Spark wording.

## Acceptance Criteria
- AC-ASK-01 (tools equal the files, hub AC-1): on the shipped golden take (`fixtures/output/analysis.example.json`
  and `replay.example.json`), `get_faults` returns each listed field equal to the analysis file's;
  `get_joint_angle` returns the min, max and mean of the knee and elbow bends computed by hand from the replay
  file's follower frames; `compare_with_teacher` returns the take's and the example's values at the frames the
  replay file's `exp_to_fol` pairs. The cached example's tool results equal the tools run again on Take 03.
- AC-ASK-02 (arguments): an unknown joint, a joint with no measure, a time outside the take, `t0` after `t1`, a
  non-number, a bool, NaN, an unknown limb, and arguments that are not a JSON object each give `ok: false` with a
  reason and no UI action.
- AC-ASK-03 (validator, hub AC-2): a forged model answer holding a number no tool returned is replaced by the measured
  facts, with `validated` false, the number in `replaced_numbers`, the reason, and a log line; an answer whose numbers
  are all found, within rounding, is kept with `validated` true. The measured facts pass the validator.
- AC-ASK-04 (word guard): an answer with a link, a control character or a banned word is replaced with the guard's
  reason; an empty answer is `no answer`.
- AC-ASK-05 (loop): tool calls are run in order, their results are sent back by `call_id` with
  `previous_response_id`; plain text on the first turn is an answer; the turn and tool call limits hold; the last
  turn has no `tools` and says so; the turn before it keeps its `tools` and asks for the `seek` and the `spotlight`, and
  a model that calls them there ends with those `ui_actions` in the document.
- AC-ASK-06 (spend, hub AC-4): every model call writes one ledger line with `model` `muse-wonder-1.0`, `purpose`
  `ask`, tokens and USD at the Wonder rates; `spend` sums them; an oversize request is refused before any call
  (nothing sent, no ledger line) with the ceiling's reason; the cap and an unreadable ledger refuse as elsewhere.
- AC-ASK-07 (live switch and key): no key or live mode off makes no call and no ledger line and gives the cache or
  the measured facts with the reason; the key never appears in a document, a log line, stdout or stderr.
- AC-ASK-08 (fallback): a failed call (HTTP error, timeout, unreadable answer) gives the cache or the measured facts
  with the reason, and keeps the tool calls already made.
- AC-ASK-09 (cache): the demo question on the demo take gives the cached answer with `source` `cache`; another
  question gets the measured facts. After a failed call the cached answer keeps the calls already made before its
  own, with `live` and `spend` as made, and the stream's events equal the document's lists; calls that would not fit
  beside the cache's give the measured facts.
- AC-ASK-10 (model named, hub AC-5): every response names `model` as above and `live`.
- AC-ASK-11 (stream): `stream: true` gives the events in order, `tool_call` before its `ui_action`, the `answer` last
  and equal to the JSON route's document for the same exchange.
- AC-ASK-12 (route and command): the status codes and exit codes above; the route is listed in `ROUTES`.
- AC-ASK-13 (nothing else changes): `analysis.json`, its schema and the score are unchanged; `make check-5` stdout
  is byte-identical; no test makes a live call.

## Error Cases
| Case | Result |
|---|---|
| No question, or a question over 500 characters | exit 2; `400` field `question` |
| A file missing, unreadable, over 32 MiB, not JSON | exit 1; route: `400` field `body` (not JSON) or `413` |
| Not an analysis, not a replay, or not of one take | exit 1; `400` field `analysis` or `replay` |
| `stream` not a bool | `400` field `stream` |
| No key, live mode off | `cache` or `measured_facts`, reason `no key` or `live calls are off (...)`, no call |
| HTTP error, timeout, unreadable answer, no response id | `cache` or `measured_facts`, the call's reason |
| Over the per-call ceiling (one turn or the question), over the cap | the same, the ceiling's or the cap's reason, before the call |
| A limit variable that is not an amount, a ledger not readable or not writable | the same, the ledger's reason |
| A number not in any tool result | `measured_facts`, `replaced_numbers`, a log line |

## Edge Cases
- A correct take with no fault: `get_faults` returns `count` 0; the measured facts say no difference was found.
- A take compared one repetition at a time: `exp_to_fol` runs over the tiled references; the comparison reads the
  tiled example frame and its `expected_t`.
- A joint not seen in every frame: its measure is null where it cannot be computed; `seen_frames` counts the rest.
- The model asks for the same tool twice: both are run and listed.
- A number in the question the model repeats: found only when a tool returned it (the tools echo their arguments).

## Negative Requirements (What This Feature Must NOT Do)
- It must not read a file, a take or a network address from a tool, or act on a UI action on the server.
- It must not change `analysis.json`, its schema, the rules, the profiles or the score.
- It must not make a call in tests, `make check-5`, `make check-5-contract` or the goldens; tests use a fake client.
- It must not print, log or store the key, or put the model's text in a reason or a log line.
- It must not decide who may ask about a take: that is Part 7's (Overview).

## Compromises
- The validator proves each number came from a tool, not that the sentence uses it for the right thing. Trigger to
  revisit: a read of live answers shows a misattributed number; the answer is then structured claims (measure, side,
  time, value) that code checks one by one.
- The answer is English only. Trigger: Part 7 passes a language; the measured facts and the instructions then take a
  `lang` as the history opinion does.
- Spend is reported, not charged to a person: Part 5 has no users, and the ledger is per host. Part 7 owns any
  per-user budget.
- The model calls are not streamed from the API (`response.function_call_arguments.delta`): the ledger needs the
  usage of a completed response, and the page needs the result of a tool, which exists only after the call is run.
  Trigger: an answer slow enough that text streaming matters; the answer text would still wait for the validator.

- Placement. The lane wrote the code into existing modules (`part5/replay.py` for the take and its tools,
  `part5/opinion/` for the prompt, the validator, the loop and the run, and `api.py`, `server.py`, `cli.py` and
  `contract.py` for the surfaces), not a new `part5/ask/` package: its worktree's write gate read the main checkout's
  specs, which did not hold this one (the history opinion met the same gate, TICKET-076 R3). With this spec on main,
  the 1.14.0 round moved, unchanged, the take and its tools to `part5/ask/tools.py` and the agent (the readers of a
  request, the loop, the budget, the cache, the fallback and the document) to `part5/ask/agent.py`. Still where the
  lane put them: the event stream (`sse`, `ask_events`) in `part5/opinion/__init__.py`, because the gate refused
  `part5/ask/stream.py`, a name no spec on main held; the validator (`check_answer`, `measured_facts`) in
  `part5/opinion/guard.py` and the prompt in `part5/opinion/prompt.py`, which that round did not move; and the
  shared finite number check `opinion.prompt._number`, not yet folded into TICKET-076 R13's helper. Trigger to
  revisit: a round whose specs on main name `part5/ask/stream.py` and `part5/ask/validator.py`.

## Assumptions
- ASM-016: the Meta Model API bills a `previous_response_id` follow-up's stored context as input tokens, and its
  `/responses/input_tokens` count of `model` and `input` does not include the tool declarations, so Part 5 counts
  the first turn and adds the declarations, and estimates a later turn from the context it carries.

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket |
|---|---|---|
| `docs/design/specs/ask-this-take.md`, `contracts/ask.schema.json`, `docs/assumptions/ASM-016.yaml` | this spec, the request and response schema, the estimate's assumption | TICKET-081 |
| `part5/ask/tools.py` (in `part5/replay.py` until the 1.14.0 round) | `Take`, the five tools (`run_tool`), their argument checks, `strict_json` | TICKET-081 |
| `part5/ask/__init__.py` | the package: what each module holds, and what stays in `part5/opinion/` | TICKET-081 |
| `part5/ask/agent.py` (in `part5/opinion/__init__.py` until the 1.14.0 round) | `ask_take`, `ask_question`, `ask_request_from`, `ask_files`; the loop, the fallback, the cache, the document (`ask_run`) | TICKET-081 |
| `part5/opinion/__init__.py` | `sse` and `ask_events`, the event stream (the gate refused `part5/ask/stream.py`) | TICKET-081 |
| `part5/opinion/guard.py` | `check_answer`, `answer_numbers`, `result_numbers`, `measured_facts` | TICKET-081 |
| `part5/opinion/prompt.py` | muse-wonder-1.0, its rates, the instructions, `ask_tools`, `ask_opening`, `ask_request`; the last turn's message `ASK_LAST_TURN` (N4 of the 1.14.0 recheck) and, for the turn before it, `ASK_SEEK_TURN` (lane/askseek, prompt `ask-4`) | TICKET-081 |
| `part5/opinion/meta_api.py` | `call` and the usage helpers take the model's rates and name the body's model; `call_ceiling`, `function_calls`, `response_id` | TICKET-081 |
| `part5/api.py`, `part5/server.py` | `POST api/ask`; a streamed body | TICKET-081 |
| `part5/cli.py` | `part5 ask` | TICKET-081 |
| `part5/contract.py` | `FEATURE_SCHEMAS` (the `ask` schema, checked by `make check-5-contract` and named in CONTRACT.md's own section, not in its schema table) and the check of the `simon.ask.v1` example | TICKET-081 |
| `fixtures/output/ask.example.json` | the cached demo answer from one live exchange | TICKET-081 |
| `web/index.html`, `web/app.js`, `web/style.css` | the Ask this take box under the replay, its stream applied to the page's own replay | TICKET-081 |
| `web/api.js`, `web/joints.js` | `ask` and `splitEvents` (the stream); `askTarget`, `nearestFrame`, `askStep`, `askSource` | TICKET-081 |
| `qa/recipes/compare/ask-this-take.md` | the QA recipe of the box (the demo question, the cached answer, the seek and the spotlight) | TICKET-081 |
| `tests/test_ask_tools.py`, `tests/test_ask_validator.py`, `tests/test_ask_agent.py`, `tests/test_ask_cli_api.py`, `tests/test_web_ask.py`; `tests/test_contract_cli.py`, `tests/test_history_opinion_cli.py` | the ACs and the page's helpers; the golden list leaves out the live example, the route list holds `api/ask` | TICKET-081 |
| `docs/design/adr/ADR-0022-ask-this-take.md`, `docs/meta-api-spend.md`, `CONTRACT.md`, `docs/design/` | the decision, the spend notes, the contract section, the design copies | TICKET-081 |

## Delivery Verification Plan
- While building: `uv run pytest -q tests/test_ask_tools.py tests/test_ask_validator.py tests/test_ask_agent.py
  tests/test_ask_cli_api.py`; at the end `make test` once.
- `make check-5` stdout byte-identical to main `fb9d87f`; `make check-5-contract` 0; `make contracts-check` 0;
  `python scripts/make_design_copies.py --check` 0; `scripts/qa-recipe-lint.sh` 0; no em dash, en dash or spaced
  hyphen in changed files.
- At most 3 live exchanges for the whole lane, each through `part5 ask --live`, each in the ledger; one of them on
  Take 03 becomes `fixtures/output/ask.example.json`. Their USD is reported.

### Device/Platform Strategy
Command line and API; Part 5's own viewer gets a small box (QA recipe `qa/recipes/compare/ask-this-take.md`). Part
7's player is Part 7's.

### Data (created through the product's own UI with synthetic accounts; never a DB or API seed)
- Synthetic accounts: none (Part 5 has no users). Data: the committed goldens and the seed 5 Take 03.

### Ratchet Initialization Plan
Not applicable.

### Boundary Layer Testing Plan
| Mapping Function | Input Format | Output Format | Test File |
|-----------------|-------------|---------------|-----------|
| `tools.Take`, `tools.run_tool` | analysis, replay, arguments | tool results | `tests/test_ask_tools.py` |
| `guard.check_answer`, `guard.measured_facts` | answer, tool calls | numbers not found, the facts | `tests/test_ask_validator.py` |
| `agent.ask_run` (the loop) | Responses payloads | tool calls, answer, spend | `tests/test_ask_agent.py` |
| `agent.ask_request_from`, the route, the command | request body, argv | document, status, exit code | `tests/test_ask_cli_api.py` |

## Dissent Review (MANDATORY, hooks block implementation without this)
Reviewed by: lane ask (implementer, self-review). Independent review: the one consolidated review at the merge.
Date: 2026-11-02

### Concern 1: a validated answer that is still wrong
Challenge: the numbers are real and the sentence misuses them. Impact: a follower trusts a wrong statement.
Mitigation: few named numbers per tool, the tool calls shipped beside the answer, the label of a model answer.
Resolution: ACCEPTED_RISK (Compromises).

### Concern 2: cost of a chatty agent
Challenge: a model that calls tools in a loop spends on every turn. Impact: the cap is reached by one page.
Mitigation: 4 turns, 8 tool calls, the whole question held to the per-call ceiling, the per-client route limit.
Resolution: ADDRESSED_IN_SPEC.

### Concern 3: the stream outlives the client
Challenge: a page closed mid-answer leaves the exchange running. Impact: a call is paid for and not shown.
Mitigation: at most 4 calls of at most 50 s; the spend is in the ledger. Resolution: ACCEPTED_RISK.

### Pre-Mortem: It's 6 months from now and this feature was a disaster. Why?
1. The preview model is withdrawn. Likelihood: M, Impact: L, Mitigation: the measured facts and the cache; the model
   is one constant.
2. Part 7 shows the answer for another user's take. Likelihood: L, Impact: H, Mitigation: the contract names the
   refusal as Part 7's job ownership; Part 5 never sees a user.
3. A follower reads a model sentence as a judgement. Likelihood: M, Impact: M, Mitigation: the instructions, the word
   guard, the label, and the measured facts on any doubt.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|-------------------|---------|------|--------|
| hub AC-1 tool outputs equal file values | AC-ASK-01, AC-ASK-02 | `tests/test_ask_tools.py` | built on the branch |
| hub AC-2 forged number replaced and logged | AC-ASK-03, AC-ASK-04 | `tests/test_ask_validator.py`, `tests/test_ask_agent.py` | built on the branch |
| hub AC-3 player seeks; per-user refusal | AC-ASK-11; Part 7's | `tests/test_ask_cli_api.py`; QA recipe | built on the branch; refusal is Part 7's |
| hub AC-4 ledger and per-call cap | AC-ASK-06 | `tests/test_ask_agent.py` | built on the branch |
| hub AC-5 models-used panel | AC-ASK-10 | `tests/test_ask_cli_api.py` | built on the branch |
| loop, fallback, cache, surfaces | AC-ASK-05, 07 to 09, 12, 13 | `tests/test_ask_agent.py`, `tests/test_ask_cli_api.py` | built on the branch |

## Deviations from PRD
| PRD item | Deviation | Reason |
|----------|-----------|--------|
| hub AC-3 negative (another user's take refused) | not in Part 5 | Part 5 has no users; Part 7 owns jobs and users |
