# ADR-0022: Ask this take: muse-wonder-1.0 with tools over one take, a number validator, spend reported only
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted (TICKET-081, Part 5's share of the hub's TICKET-269; the contract went to Part 7 first and Part 7
accepted it as written, asking only that a `validated: false` answer carry its replaced numbers).
Spec: `docs/design/specs/ask-this-take.md`. Contract: `contracts/ask.schema.json` (`simon.ask.v1`), CONTRACT.md "Ask this take".
Date: 2026-11-02
Amends: nothing. The second opinion and the history opinion (Muse Spark 1.3) keep their model, prompt and guard; they
share the one spend path this decision extends.

## Context
The Meta review named a weakness: no agentic or tool-calling use of Muse Spark or Muse Wonder. The hub's TICKET-269 asks
for an agent on one result: tools that read only the job's files, UI actions that move the player, every number in the
answer found in a tool result of that turn, spend through Part 5's ledger and cap, and a cached answer for the demo.
Three questions had to be settled: which model, how to keep a model's answer honest about numbers, and how to account
for its spend in a part that has no users.

## Options Considered

### Option 1: Muse Spark 1.3 with a JSON answer, no tools
- Pros: the model and the guard Part 5 already runs; one call per question.
- Cons: the model sees only what the prompt holds, so the whole take (frames, alignment) would have to be sent, or the
  answer could only restate the faults; no UI actions; not tool calling, which is what the review asked for.
- Effort: Low

### Option 2: muse-wonder-1.0 with tools, a sentence guard on the answer
- Pros: real tool calling on the Responses API; the model reads what it needs and moves the player.
- Cons: a sentence guard (the second opinion's `text_problem`) refuses every number, and an answer about a take is
  mostly numbers (degrees, seconds).
- Effort: Medium

### Option 3: muse-wonder-1.0 with tools, a number validator and measured facts (chosen)
- Pros: the answer may use numbers, but only numbers a tool returned in that exchange (within their rounding); anything
  else is replaced by a template answer built from the same tool results, which passes by construction. The tool calls
  ship beside the answer as its evidence.
- Cons: it checks where a number came from, not what the sentence says about it; a preview model that may change.
- Effort: Medium

## Decision
Option 3.

- **Model.** `muse-wonder-1.0` on the Meta Model API Responses endpoint, the preview model with tool calling (Standard
  pay-as-you-go: input $4.00, cached input $0.20, output $20.00 per million tokens; 3,000 requests and 4,000,000
  tokens a minute per team; dev.meta.ai, checked 2026-11-02). Tools are declared at the top level of `tools`; each
  `function_call` is answered by `call_id` with `previous_response_id`; `tool_choice` stays `auto`, so plain text is
  an answer too; arguments are validated by Part 5 (`strict` is off by default).
- **Tools.** `get_faults`, `get_joint_angle(joint, t0, t1)`, `compare_with_teacher(joint, t)` through the replay's
  alignment map, and the UI actions `seek(t)` and `spotlight(limb, t)`, which the server records and never carries out.
  They read only the analysis and the replay they are given; no path, take id or address is a tool argument.
- **Validator.** Every number of the answer (digits, and the number words the student word test counts) must be within
  half a unit of its last place of a number in a successful tool result of the exchange (an error result holds no
  measurement and counts for nothing); the answer must also pass the student word
  guard (`unsafe_problem`, praise). Otherwise the measured facts replace it, `replaced_numbers` lists the numbers, and
  one log line records the replacement with the numbers and the reason, never the model's text.
- **Spend, reported only.** Every model call goes through `meta_api.call` (count, budget under the locked ledger, send,
  record) with `purpose` `ask`, its own rates and its own model name in the line. The per-call ceiling holds for each
  turn and for the question as a whole; the spend cap is the one all Meta calls share. The answer's `spend` reports what
  the question cost. Nothing is charged to a person: Part 5 has no users, and whether a person may ask about a take, or
  has a budget, is Part 7's job ownership.
- **Fallback.** No key, live mode off or a failed call give the cached demo answer when the question and the take are
  its own (`fixtures/output/ask.example.json`, one live exchange on the seed 5 Take 03), else the measured facts, each
  with its reason.

## Consequences
- **Positive**: a tool-calling Meta model in the product, whose answers hold only numbers a successful tool call
  returned for the take (a refused call's error counts for nothing, and the model's text in tool arguments passes the
  word guard; R1 of the 1.14.0 review); the page
  moves while the agent answers (a `text/event-stream` of tool calls and UI actions); the demo works with no key.
- **Negative**: up to 4 paid calls per question (the one live exchange cost $0.109195, most of it the model's
  reasoning billed as output); a validated sentence can still attach a true number to the wrong thing.
- **Neutral**: `analysis.json`, its schema, the rules and the score are unchanged; `make check-5` never calls it.

## Assumptions
- ASM-016: a `previous_response_id` follow-up is billed with its stored context, and the count endpoint does not
  include the tool declarations; a later turn is estimated, not counted.

## Reversal Cost
Low. The route, the command and the schema are additive; removing them removes one route, one command, one schema and
one fixture. The model is one constant (`prompt.ASK_MODEL`) and its rates another.

## Pre-Mortem (MANDATORY)
It's 6 months from now and this decision was a disaster. Why?
1. The preview model is withdrawn or renamed. Likelihood: M, Impact: L, Mitigation: every failure falls back to the
   measured facts or the cache; the model is one constant.
2. A follower trusts a validated but misleading sentence. Likelihood: M, Impact: M, Mitigation: the tool calls beside
   the answer, the label of a model answer; the structured-claims check named in the spec's Compromises.
3. A page left open asks in a loop and spends the cap. Likelihood: L, Impact: M, Mitigation: 6 requests a minute per
   client, 4 turns per question, the per-call ceiling on the question, the shared $5.00 cap.

## Dissent (MANDATORY)
Reviewed by: lane ask (implementer, self-review); the consolidated review at the merge reviews it independently.
Concerns:
- "A number found anywhere in the results is too loose": the tools return few, named numbers, and frame indexes are
  left out of `get_faults` so they cannot license a number; a time the model passes to a UI tool is echoed, but it
  must lie inside the take. Accepted, with the trigger in the spec.
- "The cached answer hides a broken live path in the demo": the document says `source` `cache` and the reason, so the
  models-used panel can tell a cached answer from a live one. `live` is false when no call was made; after a failed
  call it is true and `spend` keeps what the answered calls cost, and the calls already made stay in `tool_calls`
  before the cache's own (R4 of the 1.14.0 review, the spec's Cache section).
- "Streaming a second response shape": opt-in, and the stream's last event is the JSON route's document.

## Code Backlinks (updated as code is written)
- `part5/ask/tools.py` (the section "Ask this take: the take and its tools" of `part5/replay.py` until the 1.14.0
  round): the tools and their argument checks
- `part5/opinion/guard.py` "Ask this take's validator": `check_answer`, `measured_facts`
- `part5/ask/agent.py` (the section "Ask this take" of `part5/opinion/__init__.py` until the 1.14.0 round): the loop, the
  budget (ASM-016), the cache, the document; `part5/opinion/__init__.py` keeps the stream (`sse`, `ask_events`)
- `part5/opinion/prompt.py` "Ask this take": the model, its rates, the instructions, the tool declarations
- `part5/opinion/meta_api.py` `call`: the model's rates and name in the one spend path
