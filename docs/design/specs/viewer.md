# Spec: 3D replay viewer, fault list with joint highlight, result preview (`web/`)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADR: ADR-0006 (viewer and joint mapping). Companion: `staging.md`.
Tickets: TICKET-007 (S0 page), TICKET-019 (per-fault joints), TICKET-021 (replay, `make demo`),
TICKET-022 (upload, refusal, phrasing switch, real-takes list), TICKET-023 (result preview).
Upstream: #16 (isolated demo). Milestone: M3.

## Overview
The page served by `python -m part5 serve` (staging and `make demo`) replays the follower's take over a
ghost of the expected clip, time-matched through the alignment, with the fault list beside it. Tapping a
fault jumps to its `follower_frames` and highlights its joints. It also takes uploads, shows the
refusal for a different movement, switches the phrasing backend, lists the real takes, and has a
phone-width result preview screen labelled as Part 5's preview of its published result contract, not a
Part 7 build. three.js r170 is vendored from npm `three@0.170.0` with hashes in `web/vendor/README.md`;
it is never copied from another part's repo.

## Why This Is Wrong (Dissent-First)
1. Highlighting `elbow` or `spine` needs a mapping the viewer can get wrong. Answer: the producer writes
   canonical `faults[].joints` (TICKET-019); the viewer's table is a fallback for 1.0 files only.
2. Two skeletons overlaid at hip centre can hide a small fault. Answer: the ghost is translucent, the
   highlighted joint is enlarged and coloured, and Front, Side and Top views are one tap away.
3. A preview screen invites being mistaken for Part 7. Answer: its heading says what it is.

## User Story
As a follower, I see my take replayed over the expected one and tap a fault to see where it happened.

## Files (`web/`, published)
| File | Role |
|---|---|
| `index.html` | page shell, import map for `vendor/three/` |
| `app.js` | state, pickers, Analyse, fault list, download, screens |
| `api.js` | calls to `api/*` relative to the base path |
| `viewer.js` | three.js scene: follower, ghost, bones, highlight, playback, camera presets |
| `joints.js` | bones list, the fallback joint mapping and `sizeSentence` (the fault's size in words, shared by the fault list and the preview) |
| `preview.js` | result preview screen |
| `style.css`, `icon.svg` | look and icon |
| `vendor/three/` | `three.module.js`, `OrbitControls.js`, `LICENSE`, unchanged (r170 ships no `three.core.js`; it arrived in r171) |

## Replay payload (from `api/analyse`, `staging.md`)
`{fps, expected: [frame][17][x,y,z], follower: [frame][17][x,y,z], exp_to_fol: [follower frame index per
expected frame]}`. The timeline runs on expected frames; at expected frame i the follower shows
`follower[exp_to_fol[i]]`. A fault's jump target is the expected frame whose `exp_to_fol` value first reaches
`follower_frames[0]`; its highlight lasts until `follower_frames[1]`.

## Fallback joint mapping (only when `faults[].joints` is absent)
| `joint` with `side` | Highlight |
|---|---|
| `<x>` with `both` | `left_<x>` and `right_<x>` |
| `left_<x>` or `right_<x>` | that joint |
| `spine` | both shoulders and both hips |
| `shoulders` | both shoulders |
| `neck` | `nose` and both shoulders |

## Controls (each has a `data-testid`)
Expected picker, follower picker, upload expected, upload follower, Analyse, play, pause, scrub slider,
speed, Front, Side, Top, ghost toggle, each fault row, download `analysis.json`, phrasing select, real
takes tab, preview tab. Orbit and zoom by pointer and touch.

## Acceptance Criteria
### AC-V01: replay time-matched
Given an analysis with `exp_to_fol`, when played, the follower frame shown at expected frame i is `exp_to_fol[i]`.
### AC-V02: fault jump and highlight
Given a fault row tapped, the scrubber moves to the jump target and every joint in `faults[].joints` is
drawn highlighted until the run ends; other joints are not.
### AC-V03: fallback mapping
Given a 1.0 analysis with `joint: "elbow"`, `side: "both"`, both elbows highlight; `spine` highlights both
shoulders and both hips.
### AC-V04: camera and playback
Front, Side and Top move the camera to the preset; play, pause and scrub work by mouse, touch and keyboard.
### AC-V05: upload with plain errors
Given a bad file, the message from the API shows next to the upload control; nothing else changes.
### AC-V06: refusal panel
Given `status.code: "different_movement"`, the status text shows and no fault rows render.
### AC-V07: correct take
Given `faults: []` with status `ok`, the list says no faults were found.
### AC-V08: phrasing switch
Given the select set to a backend, the request carries it and the panel shows `phrasing.backend` and any
`fallback_reason`.
### AC-V09: real takes list
Given `api/real-takes`, each take lists source, labels and faults found, marked "reported, not gated".
### AC-V10: result preview at phone width
Given 390 px width, the preview screen fits without horizontal scroll and its heading names it as Part 5's
preview of its published result contract.
### AC-V11: `make demo`
Given `make demo`, the page loads on `http://127.0.0.1:8735/` with the fixtures and the replay works,
while `scripts/dev.sh` may hold 8725.
### AC-V12: vendored library intact
Given `web/vendor/three/`, its sha256 values match `web/vendor/README.md`.
### AC-V13: sizes read without a sign
Given a fault whose `magnitude_deg` is negative (`direction: "less"`), the fault row and the preview card
read "29.9 degrees less than the example", never "-29.9 degrees less". The file keeps its signed value.
Verified by `tests/test_web_logic.py` (the shared sentence) and `staging/verify.mjs` (both screens, on a
shallow squat take).

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| API error | inline under the control | the API's `message` | AC-V05 |
| WebGL missing | fault list still works; a note replaces the canvas | `3D view unavailable in this browser` | AC-V04 |

## Edge Cases
- Masked joints (NaN) in a frame: not drawn in that frame.
- A fault with one frame: highlight lasts one frame and the scrubber still jumps.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | Playback | 30 fps on a 300-frame take in desktop Chromium | AC-V01 |
| Accessibility | Labels | every control has an accessible name; colour is not the only cue for the highlight | AC-V02 |
| Compatibility | Browsers | Chromium desktop and phone width (Playwright) | AC-V10 |

## Negative Requirements
- MUST NOT load scripts from a CDN at run time. MUST NOT copy code from another part's `web/`.
- MUST NOT present the preview as Part 7.

## Non-Requirements
- Editing clips, recording takes, accounts.

## Assumptions
ASM-010 (WebGL availability in the verify browser, `docs/assumptions/ASM-010.yaml`).

## Delivery Verification Plan
- Staging verify M3 drive and QA recipes (`staging.md`); screenshots of a highlighted joint for
  uc-analyse-take.

## Dissent Review
### Concern 1: overlay versus side by side
Kept: overlay shows the difference in place; the ghost toggle gives the plain view.
### Concern 2: vendoring a 1 MB library
Kept: offline, pinned, hashed, same version as the neighbouring parts use.

## Deviations from PRD
None.
