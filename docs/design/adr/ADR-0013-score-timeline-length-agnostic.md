# ADR-0013: Score a take window by window, and show the windows as a timeline
> Design copy of an architecture decision record. Where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
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
