# ADR-0005: Coaching phrasing registry (template, local-llm, muse-spark)
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28

## Context
The README says Part 5 needs no frontier model: rule maths measures and templates word the faults (#9).
#20 (Muse leads) asks for optional Meta hooks: Muse Spark coaching phrasing, off by default, never in
`check-5`, no live call unless `META_LIVE=1`, never an invented model response. Operator decision 4
asks for a backend switch. This host has no Ollama (`command -v ollama` exit 1 on 2026-10-28). Update
2026-10-28: the operator supplied a Muse Spark key served by Baseten (the hackathon email), which
satisfies the Muse Spark item of operator ask #335. One verification call returned HTTP 200 with empty
content: Muse Spark is a reasoning model, and 37 of the 40 completion tokens went to reasoning.

## Options Considered
### Option 1: template only
- Pros: deterministic; nothing to fail.
- Cons: #20 and the operator's switch are not met.
- Effort: Low
### Option 2: one hard-wired Muse Spark hook
- Pros: follows #20 literally.
- Cons: no key on this host; no local option; untestable live path.
- Effort: Medium
### Option 3: a small registry with fail-closed backends
- Pros: one switch; template stays the default and the scored path; new backends are one module.
- Cons: two backends cannot run live on this host today.
- Effort: Medium

## Decision
Option 3. `--phrasing template|local-llm|muse-spark` on the CLI and a switch on staging.
- `template`: default; the only backend in tests and `check-5`.
- `local-llm`: Ollama on `127.0.0.1:11434` when present, model from `PART5_OLLAMA_MODEL`; any failure
  falls back to `template`.
- `muse-spark`: Muse Spark through Baseten's OpenAI-compatible chat completions,
  `POST https://inference.baseten.co/v1/chat/completions` with `Authorization: Bearer <key>`, model
  exactly `meta-models/muse-spark-open-1026` (the key works with no other model), `max_tokens` 512 or
  more, timeout 10 s, stdlib `urllib` (no `openai` dependency: one POST does not justify one). The key is
  the Baseten key file (firm convention: the file is named after the env var;
  directory 700, file 600; path overridable by `PART5_BASETEN_KEY_FILE` for tests), read at the call,
  whitespace stripped, never printed, logged, written or copied into the repo, tickets or issues. Live
  calls only with the key file and `META_LIVE=1`. Without them, falls back to `template`.
- Input is the measured fault record only: measure, joint, side, direction, magnitude, threshold,
  frames. The backend never invents a fault or a number.
- Per fault, the line must name the same body part and side and carry the direction's meaning, and adds
  no number. A failed check, a timeout, an HTTP error or empty content falls back to `text` for that
  fault.
- The backend's line goes in `faults[].coaching`; `text`, `measure`, `side`, `direction` and every
  scored field never depend on the backend.
- `analysis.json` records `phrasing: {requested, backend, model, fallback_reason, faults: [{backend,
  fallback_reason}]}`.
- Usage ledger: each call appends its `usage` token counts (with model, UTC time, HTTP status; never the
  key or the text) to `~/.simon/baseten_usage.jsonl`.
- Tests and `check-5` use `template` only; the adapter is tested through an injected client. One opt-in
  live smoke, `make smoke-muse-spark`, is excluded from `make test`, `make check-5` and the publish check.
- Staging offers `muse-spark` in the switch only when the key file exists on the server; the key never
  reaches the browser; requests that ask for `muse-spark` are rate limited per client
  (`docs/design/specs/staging.md`).
- #20 is Muse's lane: the DECISION comment on #18 says the registry exists, the `muse-spark` adapter
  follows #20's rules and invites Muse to object or take it over.

## Consequences
- **Positive**: the switch exists; the check stays deterministic; keys never leak.
- **Negative**: `local-llm` falls back on this host (no Ollama). Live Muse Spark calls cost tokens and
  add up to 10 s per fault; the ledger makes the spend visible.
- **Neutral**: the Muse Spark endpoint, model and key name are fixed by the operator's evidence above,
  not guessed.

## Assumptions
- ASM-007: Ollama is absent on this host, so `local-llm` falls back to `template`.

## Reversal Cost
Low: the registry is one package; removing a backend removes one module and one choice.

## Pre-Mortem (MANDATORY)
1. A backend line contradicts the measured fault. Likelihood: M, Impact: M, Mitigation: the word check
   replaces it with `text` and records the fallback.
2. The key leaks into an error message. Likelihood: L, Impact: H, Mitigation: a sentinel-key test over
   output, logs and errors.
3. A reasoning model returns empty content when its token budget runs out. Likelihood: H, Impact: L,
   Mitigation: `max_tokens` 512 or more, and empty content counts as a failure that falls back.
4. Live calls run up spend on staging. Likelihood: M, Impact: M, Mitigation: per-request rate limit,
   `META_LIVE=1` only where set, and the usage ledger.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect)
Concerns:
- #20 is Muse's lane: the DECISION comment says so and Muse's objection overrides.
- A local model on a host without Ollama is dead code today: it is small, tested and switchable.
- Two text fields (`text`, `coaching`) may confuse Part 7: `CONTRACT.md` says `text` is the scored
  template line and `coaching` the display line.

## Code Backlinks (updated as code is written)
- `part5/phrasing/__init__.py`, `template.py`, `local_llm.py`, `muse_spark.py`, `smoke.py`;
  `part5/cli.py` (`--phrasing`)
