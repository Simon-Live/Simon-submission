# ADR-0013: Score a take window by window, and show the windows as a timeline
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-30

## Context
`simon.score.v1` takes 10.5 points or more off per fault, whatever the length of the take, so a long take
with the same rate of mistakes scored far worse than a short one. A take compared rep by rep (ADR-0010) was
already the mean of its reps, but it was scored only on the faults found in at least half of the reps. So a
follower who was clean for three reps and drifted for five reported no faults and an A. The team asked for a
score that is a share of the take (one miss in a minute about even with ten in ten minutes) and for a timeline
that shows the score over time, each miss with its feedback, so the overall number can be justified.

## Decision
- **Windows.** A take compared rep by rep has one window per follower rep. A take compared as a whole is cut
  into `max(1, round(span / 5 s))` equal windows on the follower's clock (`score.WINDOW_S`), by the follower
  time each expected frame was matched to.
- **Window score.** The `simon.score.v1` formula and calibrated parameters, unchanged, on the window's frames:
  each fault that has frames in the window costs `penalty(r) * (0.5 + 0.5 * dur) * coverage` with `dur` its
  share of the window, plus the similarity term over the window's frames.
- **Take score.** The mean of the windows that were compared (a rep that did not match the example is shown
  and not scored); the warning cap of ADR-0012 applies after.
- **Rep windows use the rep's own misses**, not only the faults the take reports. The take-level `faults`
  keep the majority rule of ADR-0010, so the list of faults stays short, while the timeline says where each
  rep lost its points.
- **Contract (additive).** `score.basis` (`windows` or `reps`) and `score.timeline`:
  `[{t_s: [start, end], compared, value, grade, components, misses: [{text, measure, side, joint, t_s, at_s, points}]}]`.
  `per_rep` stays for reps. `version` stays `simon.score.v1`: the formula is the same, and a take of one window
  (under 7.5 s, or one rep) scores exactly as before.

## Consequences
- The synthetic fixtures (all under 7.5 s) and `make check-5` are unchanged.
- Long takes score by their rate of mistakes. A persistent fault costs points in every window it spans.
- Multi-rep takes can score lower than before. The real fast lateral-raise follower (8 reps) goes from no faults
  and 90+ to 77 (C): reps 1 to 3 at 97, reps 4 to 8 between 54 and 83 with one to three misses each. A miss
  found in one rep only may be detector noise, which the majority rule used to hide; it now shows with its
  points, so it can be checked.
- `score.aggregate` (the mean of per-rep blocks, ADR-0010) is gone: the timeline replaced it, and nothing called it.
- The similarity term of every window reads only the measures the camera saw (ADR-0011). A measure that visibility
  excluded is missing in the score's input, also in the frames where its joints happen to be visible.

## Acceptance Criteria
- AC-TL-01: a take compared as a whole is cut into `max(1, round(span / 5 s))` windows, `score.basis` `windows`,
  and the windows tile the follower span without a gap (`tests/test_score_timeline.py`).
- AC-TL-02: `score.value` is the mean of the compared windows; a window that was not compared is listed with
  `compared: false` and not scored; with none compared the value is 0 and the timeline is still listed
  (`tests/test_score_timeline.py`).
- AC-TL-03: each window's value is 100 minus its misses' points and its similarity component; the value of a
  take of one window equals `score.compute`; one miss in a minute scores like ten in ten minutes
  (`tests/test_score_timeline.py`).
- AC-TL-04: the warning cap applies after the mean and keeps `basis`, `timeline` and the components
  (`tests/test_score_timeline.py`).
- AC-TL-05: a take compared rep by rep has `basis` `reps`, one window per follower rep, scored on that rep's own
  misses, and `per_rep` beside it (`tests/test_reps.py`).
- AC-TL-06: `basis` is `windows` or `reps` and `timeline` is typed in `contracts/analysis.schema.json`; any other
  basis or a window without a two-number `t_s` fails it (`tests/test_score_timeline.py`).
- AC-TL-07: a partially visible take scores the same as with its excluded measures removed, and a full-body take
  exactly as before (`tests/test_review_fixes.py`).
