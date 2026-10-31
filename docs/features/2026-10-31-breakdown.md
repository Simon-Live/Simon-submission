# Breakdown: shape or timing, and the standard body (2026-10-31)

Branch `lane/breakdown`. Spec: `docs/specs/breakdown.md`. Tickets: TICKET-074 (R4), TICKET-075 (R5).

## R5 Tempo versus shape (TICKET-075)
Added: a "Shape or timing?" panel on the result screen. It splits the points lost to shape into "Where a body part is"
(position) and "How far you move" (range), words the overall tempo ("On the beat", "Rushing", "Dragging"), lists the
windows that were off the beat, and gives a one-line verdict. A note says timing is coached but does not lower the score.
Every coaching row with `data-cue-kind` gets a "Shape" or "Timing" chip.
- Files: `web/breakdown.js`, `web/breakdown.css`. Mounted by `web/result.js` (coach lane) through `breakdown-slot`.
- Routes: none. Event: `simon:seek {at_s}` on `document` (bubbles to `window`) when a moment is tapped.
- Test ids: `breakdown`, `breakdown-verdict`, `shape-position`, `shape-range`, `tempo-line`, `tempo-moment`, `timing-note`, `kind-tag`.
- Tests: `tests/part7/breakdown.unit.test.mjs`, `tests/part7/breakdown.browser.mjs` (harness `tests/part7/harness/breakdown.html`,
  fixtures `tests/part7/fixtures/input/breakdown-*.json`), `staging/checks-breakdown.mjs`.
- Try on staging: finish a follow job, open `#/result/<job>`, read the panel under the score, tap a moment.
- Limits: the numbers are Part 5's. Shape points are summed miss points and can exceed the score loss. Moments need a
  Part 5 1.5.0 timeline. The "close" cut-off (5 points) is a display grouping.

## R4 Body-adjusted scoring (TICKET-074)
Confirmed: Part 3 retargets everyone to one standard 1.70 m body and Part 5 compares joint angles and directions, so
height and limb length do not change the score. Added: the "Scored on a standard body" note (`body-note`), a closed
details that opens to the plain explanation. No scoring changed; per-person proportions are not modelled by design: one standard body for everyone keeps the score fair (operator
2026-10-31). The note says so.
- Files: `web/breakdown.js` (same panel module). Tests as above.
- Limits: the note describes the pipeline and does not show the person's own measurements.
