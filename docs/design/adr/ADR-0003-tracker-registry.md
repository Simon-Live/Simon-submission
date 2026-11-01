# ADR-0003: Tracker registry with SAM 3.1 first and an open local fallback

> Copy of `docs/adr/ADR-0003-tracker-registry.md` from the maintainers' working repo at `843de10`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted (stakeholder-proxy, 2026-10-28; tracker order revised by the operator on 2026-10-28 once both SAM 3.1 keys were verified)
Date: 2026-10-28

## Context
`part2/track.py` tracks people with SAM 3.1 through the paid Meta Model API (`MODEL_API_KEY`). The team also
had gated Hugging Face access to `facebook/sam3.1`. `facebook/sam2.1-hiera-large` is ungated, Apache-2.0, and
answered a HEAD request at setup. The class fixture's recorded result (SAM 3.1 API on HPC) is 7 people,
coverage 1.0, 0 swaps.

Operator facts of 2026-10-28 (issue #335):
- The Meta key arrived and is verified: file `<key dir>/MODEL_API_KEY`, mode 600.
  `GET https://api.meta.ai/v1/models` returned HTTP 200 listing `sam-3.1`. A real SAM 3.1 tracking call through
  `part2.track.api_tracker` on the first 50 frames of `fixtures/input/single/frames` returned 50 frames,
  50 detections and one id (0), at $0.01 per call.
- The Hugging Face token arrived and is verified: file `<key dir>/HF_TOKEN`, mode 600.
  `huggingface.co/api/whoami-v2` returned HTTP 200 (a fine-grained token), and `resolve/main/config.json`
  returned HTTP 200 for both `facebook/sam3.1` and `facebook/sam3`, so the gated weights are reachable.

## Options Considered
### Option 1: wait for a key
- Pros: keeps the frontier tracker. Cons: blocks the multi-person mode and staging on a human. Effort: Low.
### Option 2: replace SAM 3.1 with an open tracker
- Pros: no key needed. Cons: loses the frontier model the README names. Effort: Medium.
### Option 3: a registry; SAM 3.1 first; open local tracker as the fallback
- Pros: the frontier model runs whenever its key and budget allow; every path still runs without them.
  Cons: four adapters to test; a paid adapter in the order. Effort: Medium.

## Decision
Option 3. `--tracker api-sam31|local-sam31|local-open|bytetrack` (env `PART2_TRACKER`, the flag wins). With no
tracker named, the registry walks a fixed order and records which tracker ran:
- Scored outputs and the reference (`make outputs`, check-2): `api-sam31` first, because it is proven, then
  `local-open`.
- Staging and bulk runs (`part2 run` with no tracker named): `local-sam31` once it has passed the parity check,
  else `api-sam31` within its cap, else `local-open`.
- Parity check (TICKET-038): `local-sam31` against `api-sam31` on the class clip gives the same id count and a
  coverage within 1 percentage point. Coverage here is label-free (share of frames each id is present, compared
  between the two runs); it is never scored against `gt_tracks.json` for selection. The result is committed in
  `progress/sam31-parity.md`; without a pass, `local-sam31` is skipped in the order.
- A step is skipped only when its key file is absent, its budget is exhausted, or (`local-sam31`) parity has
  not passed. Provenance records the tracker that ran, plus `fallback_from` and `fallback_reason` when an
  earlier step was skipped. A tracker named explicitly never falls back: `--tracker api-sam31` or `local-sam31`
  without its key exits 1 naming the key file (`<key dir>/MODEL_API_KEY`,
  `<key dir>/HF_TOKEN`; each file named after its environment variable, directory 700,
  files 600).
- `api-sam31` is the existing `part2.track.api_tracker` through `part2.meta_api` and its budget guard. The adapter
  reads the key file at use and passes it to `part2.meta_api` as `MODEL_API_KEY` in its own process environment
  only. Budget: `META_BUDGET_USD=25` for the whole run on the default ledger (`~/.simon/meta_spend.jsonl`), spend
  recorded in STATUS.md at every milestone. Staging has its own cap: ledger `~/.simon/meta_spend_staging.jsonl`,
  $10 in total and $0.50 per job; when a cap is hit the job moves to the next step and says so in its result.
- `local-sam31` runs the gated weights on the RTX 5090 at no per-frame cost. The SAM 3 code is pinned per the
  team's note in `k8s/README.md`; weights are cached under `~/.cache/huggingface`; the token is read from the key
  file at use as `HF_TOKEN`. It shares the cu128 port risk with SAM 3D Body.
- `local-open` is SAM 2.1 hiera-large prompted by detector person boxes; `bytetrack` is the second open option.
- No key value is ever printed, logged or written. `check-2` output and every `pose3d.json`/`tracks.json` record
  the tracker and backend in an optional `provenance` block that never changes the existing shape.
Spec: `docs/design/specs/tracker-registry.md`. Operator ask #335 is answered: both keys received 2026-10-28.

## Consequences
- **Positive**: the frontier model the README names runs by default; once parity passes it runs locally at no
  per-frame cost; the class mode and staging still run with no key or no budget left.
- **Negative**: the API step spends money (capped); `local-sam31` depends on the cu128 port; the fallback must be
  measured too, so check-2 reports `local-open` on the class clip as a second block, never gated.
- **Neutral**: the existing `track.py` stays as the `api-sam31` implementation.

## Assumptions
- ASM-004 (SAM 2.1 plus a detector meets coverage and swap thresholds on the class fixture; now the fallback).

## Reversal Cost
Low: the order is one table.

## Pre-Mortem (MANDATORY)
1. The cu128 port fails, so `local-sam31` never runs. Likelihood: M, Impact: L. Mitigation: parity never passes,
   the order skips it, `api-sam31` serves within its cap.
2. A key leaks into a log. Likelihood: L, Impact: H. Mitigation: adapter-only reads, a test that greps
   captured output for the fake key; Hugging Face library loggers set to WARNING.
3. The Meta API changes or goes down. Likelihood: L, Impact: M. Mitigation: a named `api-sam31` exits 1 with the
   error; the order skips a step only for a missing key, an exhausted budget or no parity, so an outage is
   never hidden.
4. Spend runs past the plan. Likelihood: L, Impact: M. Mitigation: `meta_api.Budget` reserves before each call;
   run and staging ledgers are separate; staging also caps each job.
5. SAM 2.1 drifts on all-fours poses (fallback only). Likelihood: M, Impact: M. Mitigation: re-prompt every 2 s;
   ByteTrack as the second open option; report honestly.

## Dissent (MANDATORY)
Reviewed by: setup lane (architect role); order revised on the operator's rulings of 2026-10-28.
- A paid step spends on every run: capped ($25 for the run; $10 on staging, $0.50 per job), and the local steps
  cost nothing per frame.
- Parity against the API is not accuracy: accepted; the scored result stays on `api-sam31` and parity only
  decides where bulk work runs.
- A detector adds a model and a licence: listed in ADR-0005.

## Code Backlinks (updated as code is written)
- `part2/trackers/`.
