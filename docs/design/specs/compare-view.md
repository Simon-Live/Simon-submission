# Spec: the 3D compare view (`web/compare.js`, `web/viewer.js`, `web/joints.js`)

> Copy of `docs/specs/compare-view.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted (rescope, 2026-10-30)
Date: 2026-10-30
Request Type: new-feature
Risk Level: medium
ADR: ADR-0006. Master: `part7-stitching.md`. Journey steps 3 and 6 (`journey.md`).
Tickets: TICKET-045 (compare), TICKET-040 (single mode on Watch), TICKET-047 (seek from a fault).

## Overview
The result screen shows the trainer's movement (Part 4's `animation.json`) and the follower's take
(Part 3's `--view part5` skeleton) as two 3D figures on one clock, aligned by Part 5's `exp_to_fol`,
under one orbit camera, so a viewer can rotate, scrub and compare. The Watch screen uses the same viewer
with one figure.

## Input: `GET api/results/<job>/replay.json`
Part 5's replay file, written by `part5 analyse --replay` and validated by Part 7 against Part 5's
`contracts/replay.schema.json` at the pin before it is served (`part7/replay.py`): `fps`, `expected`
and `follower` per-frame `t` and joints, `exp_to_fol` (the follower frame for each expected frame),
`bones`. Part 7 adds nothing computed; it serves the file as written. Until the Part 5 re-pin, the
fixture `fixtures/input/replay.json` (shaped as the schema) feeds `#/result/fixture`.
Watch reads the entry's `animation.json` from Part 6's API and draws it alone.

## Behaviour
- **Clock.** One clock in follower seconds. The follower figure shows frame `round(t * fps)`; the
  expected figure shows the expected frame `e` whose `exp_to_fol[e]` is the largest value not above the
  follower frame (the first `e` when none is). The clock text reads `<t to one decimal> s` and sits in
  `data-testid="clock"` with `data-t` holding the exact seconds.
- **Play and pause.** `play` toggles; the clock advances in real time at 1x and stops at the end.
  While paused the clock never moves.
- **Scrub.** `scrub` is a range input over follower time; moving it pauses and sets the clock.
- **Modes.** `mode-toggle` switches `data-mode` on `compare` between `side` (figures 0.8 m apart on x,
  each centred on its own pelvis) and `overlay` (both pelvises at the origin; the follower drawn in the
  accent colour, the expected figure translucent). The toggle's `aria-pressed` is true in overlay.
- **Camera.** One perspective camera with OrbitControls (three@0.170.0 `examples/jsm/controls`,
  vendored from the same npm tarball). Drag rotates, pinch or wheel zooms. Both figures share the
  camera, so a drag rotates both. `view-front`, `view-side`, `view-top` set fixed azimuth and
  elevation. `compare` carries `data-camera-azimuth` and `data-camera-elevation` in degrees, updated on
  every camera change.
- **Highlight.** `highlight(joints)` colours the named joints on the follower figure and writes them,
  comma separated, to `data-highlighted-joints`; an empty call clears both.
- **Seek.** `seek(at_s)` pauses and sets the clock to `at_s`; the fault list calls it with the fault's
  `at_s` and then `highlight(fault.joints)`.
- **Single mode (Watch).** One figure, the same camera, play, scrub and view buttons; no mode toggle.
- **Labels.** Legend: `Trainer` and `You`, in the figures' colours. Text written with the writer skill.

## Acceptance Criteria
- AC-C1 With a fixture replay, the two figures at clock `t` use follower frame `round(t * fps)` and the
  expected frame from the rule above (unit test on the frame-picking function, no WebGL).
- AC-C2 A pointer drag across the canvas changes `data-camera-azimuth` by more than 10 degrees and
  changes both figures' projected screen positions (browser test).
- AC-C3 `mode-toggle` switches `data-mode` and `aria-pressed`; in `overlay` both pelvises project to
  the same screen point within 2 px.
- AC-C4 `seek(1.9)` sets `data-t` to 1.9 within one frame and leaves the clock paused.
- AC-C5 `view-top` sets elevation to 90 degrees within 1 degree; `view-front` sets azimuth 0.
- AC-C6 Paused, the clock text is unchanged after 2 s.
- AC-C7 A replay that fails the schema check is not served (`api/results/<job>/replay.json` 422 with
  `The replay file could not be read.`) and the result screen shows the fault list and score without
  the 3D view.
- AC-C8 At 412x915 the canvas fills the width, the controls are 44 px tap targets, and nothing scrolls
  sideways; on desktop the canvas is at most 960 px wide.

## Error Cases
| Condition | Behaviour | Message |
|---|---|---|
| WebGL unavailable | fault list and score only | `3D view is not available in this browser.` |
| Replay fails the schema | 422, as AC-C7 | `The replay file could not be read.` |
| Entry animation missing (Watch) | video only | `This movement has no 3D animation yet.` |

## Edge Cases
- Follower longer than expected: `exp_to_fol` decides; after the last mapped expected frame the expected
  figure holds its last pose.
- Joints with `null` positions in a frame: the bone touching them is hidden for that frame.

## Dissent Review
Reviewed at the rescope, 2026-10-30.
- Concern: Part 6's player already draws an animation; a second viewer duplicates it. Resolution:
  Part 6's player draws one figure per instance and has no shared clock; the compare needs two figures
  under one camera. Watch still frames Part 6's entry page.

## Delivery Verification Plan
Unit tests for frame picking and the schema check; QA recipe `compare-3d` (firm-only) on staging; the
submission video shows a drag and the overlay toggle.
