# ADR-0014: Coaching cues, tempo and insights as an additive contract (schema 1.5.0)
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-31

## Context
The operator asked on 2026-10-30 for actionable insights where the follower's movement does not match the
trainer's: "too fast", "lower your hip", "twist your ankle". The analysis already says what was wrong
(`faults[].text`: "left knee not bent enough") and, since ADR-0013, where and at what cost
(`score.timeline[].misses[]`). It does not say what to do, it says nothing about speed, and a result screen
has to pick from up to a dozen misses on its own. Part 7 computes no analysis (Part 7 ADR-0006), so the
advice belongs in Part 5's output.

## Options Considered

### Option 1: Part 7 turns `text` into advice
- Pros: no contract change.
- Cons: analysis logic in the app, against Part 7 ADR-0006; Part 7 would re-derive direction from prose.
- Effort: Low

### Option 2: the phrasing backend (Muse Spark) writes the advice
- Pros: natural wording.
- Cons: not deterministic, needs the network, and a model can change the meaning ("bend" for "straighten").
- Effort: Medium

### Option 3: template cues from measure, direction and side, plus tempo from the alignment (chosen)
- Pros: deterministic, testable against every measure, direction and side the contract allows; tempo is
  measured from data the pipeline already has.
- Cons: fixed wording; one cue per measure, direction and side.
- Effort: Medium

## Decision
- **Cue per fault and per miss.** `faults[].cue` is an imperative of at most 6 words from the fault's
  `measure`, `direction` and `side` (`part5/cues.py`): "Bend your knees more", "Raise your left arm higher",
  "Lean forward more", "Lower your hips more". Every cue moves the follower toward the example: `direction`
  is the sign of follower minus example. `cue_kind` is `range` (how far a joint bends or a limb lifts:
  elbow and knee flexion, upper arm out and forward, thigh forward) or `position` (where a part is placed or
  how it is aligned: forearm, thigh and foot out, knee valgus, trunk lean, shoulder tilt, head forward). Each
  `score.timeline[].misses[]` repeats its fault's `cue`, `cue_kind` and `direction`.
- **Tempo.** Each compared window carries `tempo: {ratio, cue}`, where `ratio` is follower seconds per example
  second: for a take compared as a whole, the follower span over the example span of the expected frames
  matched into the window (from the alignment's `exp_to_fol`); for a rep, the rep's length over the example
  rep's. `ratio` is null when the example side spans under 1 s. Below 0.85 the cue is "Slow down to match the
  trainer", above 1.15 "Speed up to match the trainer", otherwise null. `score.tempo` is the same for the take
  (the whole span, or the median of the reps). Tempo is not scored: the score is unchanged.
- **Insights.** The top-level `insights` lists at most 5 `{cue, why, kind, at_s, window, points, measure,
  side, joint}`. With a timeline: one item per distinct cue among the misses, ranked by `points`, the cue's
  summed miss points over the compared windows divided by their number (the score is the mean of the
  windows, so this is the cue's share of the score); `at_s` and `window` are its first miss, where a viewer
  seeks to; `why` says what was seen and how often ("Left arm too close to the body (3 of 8 reps)"). When
  `score.tempo.cue` is set, a tempo item (`points` null, `why` "Your reps took 37% of the trainer's time")
  is added last and always kept, so the fault items take at most 4 places (except a slow take under rehab, whose
  "Slower is fine" is a reassurance and no item; ADR-0016, Amendment 2). Without a timeline (a producer
  that does not score): one item per distinct fault cue in the order of `faults`, `points` null.
- **Deterministic.** The same document always gives the same insights. Cues and `why` are template text. No phrasing
  backend rewrites a cue: a live backend phrases `coaching` only (ADR-0005), so the cue keeps its meaning whatever the
  backend. A `why` repeats a validated live line only where Amendment 2 says so, and then it repeats a line the
  document already holds.
- **Version.** Every new document is `1.5.0`, since every document now carries `insights`. The schema file
  is `1.5.0`. The earlier groups (`1.2.0` time fields, `1.3.0` rep fields, `1.4.0` warnings) stay optional
  and are told apart by their fields. A document without cues validates and reads as before.

## What is not measured: the foot beyond the ankle
The pipeline carries the 17 COCO joints, which end at the ankle. Nothing measures foot rotation, toe-out
angle or an ankle twist, so there is no "twist your ankle" or "turn your foot out" cue; the vocabulary test
asserts that no cue names the ankle, heel, toes or a twist. `foot_out` is where the ankle sits sideways,
not which way the foot points. Making foot cues possible needs per-foot keypoints from Part 2's body model:
the heel, the big toe and the small toe of each foot (the COCO-WholeBody foot points), carried by Part 3
through `simon.animation.v1` as optional joints, then a `foot_rotation` measure (the heel-to-big-toe vector
against the hip line, in the ground plane) and an `ankle_inversion` measure (the heel, ankle and toe midpoint
angle). Follow-up: TICKET-040, decided in ADR-0015 (amendment of 2026-10-31): Part 3 does not carry the points, so
Part 5 reads them from Part 2's pose3d.json as an optional side input, and `ankle_inversion` is the roll of the foot
plane against the shin, since the triangle named here is rigid. A cue may now name the ankle, in `ankle_inversion` cues only.

## Consequences
- **Positive**: a result screen can show "what to work on" with no analysis of its own; each cue is checked
  against the whole vocabulary; tempo on the real fast lateral-raise follower reads 0.37 (Slow down) and on
  the dummy takes matches the generator's own speed to within 0.05.
- **Negative**: every new document changes `schema_version` to `1.5.0`, so the goldens and tests that read
  `1.2.0` to `1.4.0` from new documents were updated. Fixed wording, one cue per measure, direction and side.
- **Neutral**: `make check-5` is unchanged (detection and the score are unchanged); the golden examples gain
  cues and `insights`.

## Assumptions
- None new. The tempo bounds (0.85, 1.15) come from the dispatch of 2026-10-31 and are not calibrated.

## Amendment 1 (2026-10-31): an insight uses its fault's timed words
Context: the delivery review put a fault row and its insight side by side. The row said "Right foot too far right
at 1.9 s" (`text_timed`, ADR-0009) and the insight said "Right foot too far out at 1.9 s" (the plain `text`
vocabulary): two words for one fault on one screen. The same review found that the timed words for a thigh that
is not lifted ("thigh too low") read as squatting too deep, the opposite of the fault.

Decision (operator, 2026-10-31):
- An insight's `why` that points at a reported fault reuses that fault's timed words: its `text_timed` in sentence
  case, with the time ("Right foot too far right at 1.9 s"). "Points at a fault" means a `faults[]` entry with
  the same `measure`, `side` and `direction` as the insight's miss (or, without a timeline, the fault itself).
  Where the cue missed more than once the count follows: "(3 of 8 reps)" for a take compared rep by rep,
  "(2 times)" otherwise; the time stays the first miss's, which is the insight's `at_s`. A phrase that ends in
  advice ("more upright than the example, lean forward more") still keeps its observation clause only, since the
  cue says what to do.
- A miss no reported fault matches (a rep's own miss that the take does not report) and a tempo item keep the
  plain-words templates of the Decision above. Nothing else about insights changes: order, points, `at_s`,
  `window`, the cap of 5 and the tempo item last.
- `thigh_forward` with direction `less` says "not raised enough" in the timed words too (`part5/words.py`:
  "right thigh not raised enough", sizes "not quite", "nowhere near"), not "too low". The cue ("Lower your hips
  more") and `text` are unchanged. `upper_arm_forward` with direction `less` keeps "too low". The live timed
  validator holds a Muse Spark line to the same meaning: for this fault the words "low", "lower", "hang" and
  "drop" carry no direction, so "thigh too low" fails the word test and the line falls back to `text_timed`.

Consequences: `why` is still template text and deterministic. The schema is unchanged (`why` stays a non-empty
string), the goldens are rebuilt, and `make check-5` is unchanged (it reads faults, not their words).

## Amendment 2 (2026-11-01): an insight repeats a live line's observation clause
Context: a live English line is what the fault row shows, so an insight that pointed at the same fault in the
template's timed words ("Right foot too far right at 1.9 s") read as a second wording of one fault on one screen.

Decision (stakeholder-proxy, 2026-11-01, TICKET-057):
- Scope: an insight that points at a reported fault F (same `measure`, `side` and `direction`, as in Amendment 1)
  where F's `phrasing.faults[i]` has a backend other than `template`, a null `fallback_reason`, and `lang` `en` or
  absent. Its `why` is then built from F's `coaching`:
  1. Keep only the text before the first ";".
  2. Drop any closing run of ".", "!" and "?" ("...", "?!" and "?" too, so no mark is left before the count; the
     review of 2026-11-01 found "at 1.7 s.. (2 times)" and "?" before the count under the first wording, "one closing
     '.' or '!'").
  3. Run `template.line_problem(F, clause, timed=True)`. If it fails, the `why` is the template form of Amendment 1.
  4. Replace the one time number, F's `at_s` to 0.1, with the insight's `at_s` to 0.1, keeping the unit as written.
  5. Capitalise the first letter and append " (n of m reps)" or " (n times)" exactly as before.
- Examples: "At 1.4 s, your knees are not bent enough." gives "At 1.4 s, your knees are not bent enough (2 of 2 reps)".
  "Your right foot drifts too far to the right at 1.9 s; keep it under your hip", with the first miss at 1.7 s in 3
  of 8 reps, gives "Your right foot drifts too far to the right at 1.7 s (3 of 8 reps)".
- A template line, a line that fell back and a translated line (`lang` other than `en`) keep the `why` of Amendment 1;
  so do a miss no reported fault matches and a tempo item. The cue, `kind`, `at_s`, `window`, `points`, the order and
  the cap of 5 are unchanged.
- **Deterministic.** The same document always gives the same insights, because the `why` is a function of the
  document: the faults, the `phrasing` record and the timeline. A `why` that points at a live line repeats a line
  that already passed the word test, cut and tested again, so it adds no word the validator has not seen.

Consequences: the schema is unchanged (`why` stays a non-empty string). The goldens, `make check-5` and every
template-phrased document are byte-identical, because the template backend never meets the scope above.
`pipeline._phrased` makes the insights again after the lines are written, so a document phrased by a live model keeps
the rule whether or not it is scored.
