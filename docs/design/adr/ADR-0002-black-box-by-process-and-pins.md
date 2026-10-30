# ADR-0002: Parts as black boxes, run by process from pinned upstream clones

> Copy of `docs/adr/ADR-0002-black-box-by-process-and-pins.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted
Date: 2026-10-28

## Context
Part 7's README says it consumes other parts "only through their shared files ... No importing another
part's code". The DoD compares the app against "running Parts 2 to 5 directly", which needs each part
to run as its owners publish it. Parts 1 and 4 belong to the the team team and Part 1 is still changing
(e84e92b on 2026-10-28). Parts 2 and 5 were still in development; Parts 3 and 6 were done.

## Options Considered
### Option 1: vendor copies of each part into this repo
- Pros: offline, frozen. Cons: copies code, which the README forbids; drifts from upstream. Effort: Medium.
### Option 2: use the development workspaces of Parts 2, 3, 5 and 6 on this host
- Pros: no clone. Cons: those trees carry workspace tooling and unmerged work; Parts 2 and 5 are running and
  must not be touched. Effort: Low.
### Option 3: pinned clones of each upstream `main`, run through the CLI or HTTP API the part publishes
- Pros: exactly what a teammate would run; the pin makes every check reproducible; no code crosses.
  Cons: setup time per pin (Part 2 GPU profile). Effort: Medium.

## Decision
Option 3.
- Each part runs from `~/.local/state/simon-part-7/parts/<n>@<sha12>/`, a clone of its the team upstream
  checked out detached at the pinned commit. Part 7 calls only the commands and endpoints the part
  documents in its README or CONTRACT ([`parts-harness.md`](../specs/parts-harness.md) lists each, read at the pin).
- The pins live in `parts.lock.json` (committed): per part the repo URL, the 40-character SHA, the time
  pinned and the part's status at that time. At run start every part is
  pinned to its upstream `main`. Re-pinning is one explicit command (`make repin`), which reruns
  `make chain` and is recorded as a commit.
- Exchange is files only: Part 7 writes inputs to a part's command and reads its outputs. The one
  inbound seam is Part 6's processor plug-in, where Part 6 imports `part7.processor` by the name Part 6
  documents (`SIMON6_PROCESSOR`); that module is Part 7's own code.
- Every hand-off is checked by a `doctor` where the producer or consumer has one: Part 2
  `doctor --for part3`, Part 3 `doctor --for part4|part5`, Part 4 `simon_anim.contract validate`
  (Part 4 has no doctor), Part 5 `doctor --for part7`, Part 6 `doctor <entry>`. A failed doctor stops
  the chain at that step and names it.
- Part 7 never modifies another part. Defects are reported:
  - Parts 2, 3, 5 and 6: a note to that part's maintainers naming the part, the pin and the evidence;
  - Parts 1 and 4: a `QUESTION` or `HANDOFF` comment on that repo's issue #1 with the COLLABORATION
    header, Track A, @mentioning no one, deduplicated against existing Track A comments.
  Part 7 then works around the defect only with options the part already offers. When none exists, the
  run ends DEGRADED with the evidence.

## Consequences
- **Positive**: check-7 compares like with like; any teammate can rerun it at the recorded pins.
- **Negative**: a part's breaking change lands only after a re-pin; setup of a new pin costs time.
- **Neutral**: Part 1's key channel is its documented `.env` file in its own clone (ASM-004).

## Assumptions
- ASM-003: each upstream `main` is cloneable with the host's `gh` login (all seven answered
  `git ls-remote` at setup).
- ASM-004: Part 1 reads `MODEL_API_KEY` only from `<clone>/.env`.
- ASM-005: Part 2 single mode runs on this host's GPU from a clone of its upstream.

## Reversal Cost
Medium: the harness is one module; switching to vendored copies would break the README rule.

## Pre-Mortem (MANDATORY)
1. A part's published CLI changes between pins. Likelihood: M, Impact: M. Mitigation: the adapter reads
   the command from the part's CONTRACT at the pin; `make chain` after each re-pin catches drift.
2. Part 2 is still running at run start and its upstream lacks `--backend` (true at setup: `b45a91d`
   has no `--backend`, and its `body3d.py` needs CUDA plus `/workspace` pod paths). Likelihood: H,
   Impact: H. Mitigation: the TICKET-002 probe, fixtures for S0, the app and check-7, an hourly re-check
   until 2026-11-03T06:00Z, re-pin through TICKET-026; still missing then, M1 BLOCKED with the evidence
   and a message to the Part 2 maintainers.
3. Part 1 spends money per new video. Likelihood: H, Impact: L. Mitigation: Part 1's own $5-mark guard;
   clips are named by content hash so Part 1 reuses its saved results; Part 3 `--keyframes every:<n>`
   is the documented fallback when Part 1 refuses or stops ([`processor.md`](../specs/processor.md)).

## Dissent (MANDATORY)
Reviewed at setup (architect review), 2026-10-28.
- Part 6 importing `part7.processor` is code crossing a boundary. Resolution: it is Part 6's published
  seam, the code is Part 7's, and Part 7 imports nothing of Part 6.
- Using Part 3's `every:<n>` keys when Part 1 fails changes what the catalog holds. Resolution: the
  entry's provenance names Part 3 as the keyframes producer and the job result says so.

## Code Backlinks (updated as code is written)
- `part7/pins.py`, `part7/runner.py`, `part7/parts/*`, `parts.lock.json`.
