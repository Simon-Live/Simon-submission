# ADR-0009: Time, direction and replay as an additive contract (analysis 1.2.0, replay 1.0.0)
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-30

## Context
Part 7 needs, per fault, when it happened in the viewer's own recording, which way the body part was off, and a
replay file it can load without calling the staging API. `analysis.json` 1.1.0 gives expected and follower frame
indices (the longest run only for the follower), `side` and `direction`; the replay payload exists only inside
`POST api/analyse`. Readers of 1.1.0 (Part 7 at its last check, the staging viewer) must keep working.

## Options Considered
### Option 1: add optional fields; keep every 1.1.0 field and replay key as it is
- Pros: no reader breaks; one minor version.
- Cons: some redundancy (`follower_frames` and `follower_runs`, `text` and `text_timed`).
- Effort: Low
### Option 2: reshape (frames as `{t, joints}`, `text` timed)
- Pros: tidier files.
- Cons: breaks the staging viewer and every reader of `text`; a major version.
- Effort: Medium

## Decision
Option 1.
- Faults gain `follower_t_s`, `at_s`, `follower_runs`, `text_timed`, `lateral` and, on `foot_out`, `lateral_m`.
  Times come from the follower file's own `t`, in seconds, as written; `at_s` is the start rounded half up to 0.1 s.
- `lateral` is `left`, `right` or `null` in the subject's own frame, like `side`: an out fault of the right foot is
  `right`, an in fault `left`; caving knees point to the midline; `trunk_lean_side` maps `more` to `left`. Part 7
  mirrors it only when it draws a mirrored view.
- `simon.replay.v1` is today's payload plus `format`, `schema_version`, `expected_t`, `follower_t` and
  `coordinate_frame`, written by `part5 analyse --replay`; the API returns the same keys.
- Schema versions: analysis 1.2.0, replay 1.0.0, metrics 1.1.0; all additions optional.

## Consequences
- **Positive**: Part 7 builds the timeline, the "too far right at 1.9 s" line and the 3D compare from files.
- **Negative**: two time representations per fault (frames and seconds) must agree; a test pins them.
- **Neutral**: `coaching` for template runs now equals `text_timed` (ADR-0008).

## Assumptions
- Part 3 `--view part5` files carry `t` from 0 at the first frame (its contract); a file that starts later keeps its
  own clock, and Part 7 reads `at_s` on that clock.

## Reversal Cost
Low: optional fields can be dropped in a later minor version without breaking a reader that ignores them.

## Pre-Mortem (MANDATORY)
1. Part 7 shows `lateral` on a non-mirrored front view and the arrow points the wrong way. Likelihood: M, Impact: M,
   Mitigation: `CONTRACT.md` names the frame and the mirror rule; Part 7's contract test covers it.
2. `follower_runs` and `follower_frames` disagree after a refactor. Likelihood: L, Impact: M, Mitigation: AC-T02.
3. The replay file grows large for long takes. Likelihood: L, Impact: L, Mitigation: the existing 6000-frame cap and
   4 decimals.

## Dissent (MANDATORY)
Reviewed by: journey follow-up lane (the author; the independent review is part of TICKET-038)
Concerns:
- "Screen direction" in the brief suggests the screen's frame: rejected, because the screen depends on the camera and
  the mirror; the subject's frame is stable and matches `side`.
- Arrays beside frames are less tidy than per-frame objects: kept for compatibility.

## Code Backlinks (updated as code is written)
- `part5/pipeline.py`, `part5/lateral.py`, `part5/words.py`, `part5/replay.py`, `contracts/analysis.schema.json`,
  `contracts/replay.schema.json`
