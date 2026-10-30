# ADR-0008: AI phrasing is the user-facing default in live mode
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-30
Amends: ADR-0005 (the default backend in live mode; template stays the default everywhere else)

## Context
Operator directive of 2026-10-30, verbatim: "fault text should be dynamic, using AI to generate a human understandable
message". ADR-0005 made `template` the default and `muse-spark` an opt-in backend gated by `META_LIVE=1`. Its
validator bans every number and every second body part, so a line that says the time ("at 1.9 s") or gives a cue
("keep it under your hip") always falls back today. The key file `BASETEN_API_KEY` exists on the host.

## Options Considered
### Option 1: keep the template default; Part 7 opts in per request
- Pros: no change.
- Cons: the directive asks for AI text by default for users.
- Effort: Low
### Option 2: `muse-spark` the default in live mode, template everywhere deterministic
- Pros: users get the model's line; tests, `check-5` and goldens stay byte-stable; one switch per host.
- Cons: two defaults to explain.
- Effort: Medium
### Option 3: `muse-spark` the default everywhere
- Pros: one default.
- Cons: tests and goldens would depend on a network call; breaks AC-NFR-002 of the parent spec.
- Effort: Medium

## Decision
Option 2. Live mode is `--live` on `analyse` or `serve`, `SIMON5_LIVE=1`, or the existing `META_LIVE=1`; in live mode
the default backend is `muse-spark`, and an explicit `--phrasing` always wins. `check-5`, `check-5-contract`,
`output-examples` and tests force `template`.
- The model receives the measured fault record plus `at_s` and `lateral`, and writes one friendly sentence that
  includes the time.
- Validator, timed mode: one line of at most 160 characters; the time `{at_s:.1f}` exactly once with ` s`, `s` or
  ` seconds`, and no other number; the measured side, with any other left or right equal to `lateral`; the measured
  body part plus a short landmark list per measure (`foot_out`: hip, shoulder; `knee_valgus`: foot, hip;
  `thigh_out`: foot; `upper_arm_out`: trunk; `forearm_out`: elbow); the direction's meaning, with "too far
  <lateral>" counting as the direction.
- Any failure falls back to the timed template (`text_timed`) for that fault, with `backend`, `model` and
  `fallback_reason` per fault. The template backend also writes `coaching = text_timed`.
- Limits: per-client 6 requests a minute on the server (unchanged), 30 model calls a minute per process, 20 s of
  phrasing per analysis; `max_tokens` 2048; usage ledger unchanged.

## Consequences
- **Positive**: users read friendly, timed lines; a wrong fact still cannot pass.
- **Negative**: live analyses take longer (up to 20 s) and cost tokens; the landmark list is a judgement.
- **Neutral**: `coaching` for template runs changes from `text` to `text_timed`.

## Assumptions
- The Baseten endpoint and model of ADR-0005 stay available; if not, every line falls back and says why.

## Reversal Cost
Low: the live default is one selection function; removing it restores ADR-0005.

## Pre-Mortem (MANDATORY)
1. The model names the wrong side in a way the word test misses ("your other foot"). Likelihood: L, Impact: M,
   Mitigation: the side test needs the measured side word; TICKET-037 samples 20 live lines for fact fidelity.
2. Spend grows on a busy staging day. Likelihood: M, Impact: M, Mitigation: per-client and per-process limits, the
   ledger, and the 20 s budget.
3. A tester sets `SIMON5_LIVE=1` and goldens change. Likelihood: M, Impact: L, Mitigation: deterministic targets force
   `template` (AC-P02).

## Dissent (MANDATORY)
Reviewed by: journey follow-up lane (the author; the independent review is part of TICKET-038)
Concerns:
- README says no frontier model is needed: true for scoring and detection, which stay rule maths; only display text
  uses the model.
- `META_LIVE=1` now also changes the default: documented in `CONTRACT.md` and README; `--phrasing template` keeps the
  old behaviour.
- The landmark list could let a misleading cue through: each landmark is a reference point for that measure, never
  a second fault, and the review ticket checks it.

## Code Backlinks (updated as code is written)
- `part5/phrasing/__init__.py`, `template.py` (`line_problem(..., timed=True)`), `muse_spark.py`, `part5/cli.py`,
  `part5/api.py`
