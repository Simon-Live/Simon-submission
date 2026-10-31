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

## Amendments (live review `docs/phrasing-review.md`, then the consolidated review fixes)
- **Request**: `reasoning_effort: low` is part of the Baseten request (`muse_spark.OPTIONS`). Muse Spark is a reasoning
  model. At the default effort, round 1 of the review had 9 of 20 calls come back empty (reasoning used all 2048
  tokens) and round 3, with 4096 tokens, had 4 of 20 run past the 10 s timeout. At `low` a call takes about 3 s and 990
  completion tokens, and 0 of 20 fell back. `max_tokens` stays 2048.
- **Prompt record**: the model also receives `may_mention`, the landmark list for the measure (`foot_out`: hip,
  shoulder; empty for a measure without landmarks), so that the one landmark the validator allows is something the
  model was told it may use. The system text allows "is", "are" and "looks" around the `text_timed` words. The validator
  was not changed by the review.
- **Live default without a key**: when the server is in live mode but has no key file, `muse-spark` is not on offer.
  A request that named no backend is still analysed: the live default runs, every fault falls back to its template
  line with `fallback_reason: "no key"`, and `selected_by` is `live` (HTTP 200, no model call, no use of the per-client
  limit). A request that names `muse-spark` on such a server is still a 400. `analyse --live` behaves the same way.
- **Reasons**: a reason that is not about one call is plain: `no key`, `live calls are off (...)`, `rate limited`,
  `time budget spent`. A call that ran and failed reads `muse-spark: <what>`.
- **Deterministic targets (AC-P02)**: besides `check-5`, `check-5-contract` and `output-examples` forcing `template`,
  `tests/conftest.py` takes `META_LIVE` and `SIMON5_LIVE` out of every test, points the key file at nothing and the
  ledger at a temp dir, and refuses connects and name lookups outside the loopback. `staging/env.sh` exports
  `META_LIVE=1` when the key file exists, so without it `make test` from that shell would spend real calls.
- **The staging page follows the live default (2026-10-31, delivery review residual R1)**: the page used to start
  its "Wording of the faults" select on Template whatever the server's mode. `api/samples` now also returns
  `phrasing_default`, the backend `select_backend` picks for a request that names none, or `template` when that
  backend is not on offer. The page preselects it, so a visitor to the staging page (live mode, key file present)
  reads Muse Spark wording unless they choose Template, and a server without the key still starts on Template.
  The page keeps sending `phrasing`, so a result from the page records `selected_by: flag`, and `live` stays what
  the API records for a request that names none. Verify, the walkthrough and every recipe that does not test
  wording choose Template explicitly, so none of them makes a live call (viewer.md AC-V19).

- **No praise in a fault line (2026-10-31, delivery review residual R2)**: live Muse Spark wrote "Your knees are not
  bent enough at 1.4 s, nice effort." (QA runs 20261031T070638Z, 093546Z and 170636Z; a blind auditor), because the timed
  prompt offered "Nice effort" and "almost there" as examples. Stakeholder-proxy ruling, confidence medium, verbatim:
  "R2 fixed now; the timed prompt is rewritten through the writer skill with no praise in a fault line, the timed
  validator rejects praise phrases and falls back to the template line, proven by tests, a 20-line live re-review and a
  re-drive of uc-timed-coaching." Done: the prompt names no praise phrase and asks for none (an ending such as "keep
  going" is allowed); the timed validator rejects `template.PRAISE_PHRASES` (word-bounded, any case) with the reason
  `muse-spark: adds praise`, and the fault falls back to `text_timed`. `fallback_reason` is a free string in the schema,
  so the schema is unchanged. This only makes the validator stricter. The untimed test is unchanged. Measured in
  `docs/phrasing-review.md` ("Re-review 2026-10-31").
- **The praise check also guards the untimed line, and the list is wider (2026-10-31, review residuals)**: the
  independent review of the R2 fix found that the untimed validator had no praise check, so a live fault line without a
  time that praised would pass, and that common forms went through ("nice try", "great start", "looking good",
  "excellent work", "solid effort", "you're doing great", "you are doing great", a hyphenated "nice-effort", a
  zero-width character between the words). Done: `template.line_problem` runs the same praise check on both paths, so an
  untimed praised line falls back with `<backend>: adds praise`; the list holds those forms; the words of a phrase may be
  joined by spaces or hyphens; zero-width characters (U+200B, U+200C, U+200D, U+2060, U+FEFF) are ignored, as removed
  and as a space. This supersedes "The untimed test is unchanged" above for praise only. Still stricter only: a line
  that failed before fails now, and one that fails now falls back to the template line.

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
  `part5/api.py`, `part5/phrasing/prompt.py` (`may_mention`), `tests/conftest.py`, `tests/test_no_live_calls.py`,
  `tests/test_live_fallback.py`, `tests/test_api_live.py`, `tests/test_web_wording.py`, `web/app.js` and `web/joints.js`
  (the preselected wording), `staging/verify.mjs`
