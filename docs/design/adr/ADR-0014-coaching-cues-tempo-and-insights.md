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
  "Lean forward more", "Raise your thighs higher". Every cue moves the follower toward the example: `direction`
  is the sign of follower minus example. `cue_kind` is `range` (how far a joint bends or a limb lifts:
  elbow and knee flexion, upper arm out and forward, thigh forward) or `position` (where a part is placed or
  how it is aligned: forearm, thigh and foot out, knee valgus, trunk lean, shoulder tilt, head forward). Each
  `score.timeline[].misses[]` repeats its fault's `cue`, `cue_kind` and `direction`.
- **Tempo.** Each compared window carries `tempo: {ratio, cue}`, where `ratio` is follower seconds per example
  second: for a take compared as a whole, the follower span over the example span of the expected frames
  matched into the window (from the alignment's `exp_to_fol`); for a rep, the rep's length over the example
  rep's. `ratio` is null when the example side spans under 1 s, and for every tempo of a low match (Amendment 4).
  Below 0.85 the cue is "Slow down to match the trainer", above 1.15 "Speed up to match the trainer", otherwise
  null. `score.tempo` is the same for the take (the whole span, or the median of the reps). Tempo is not scored (except
  under dance, ADR-0016): the score is unchanged.
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
  "right thigh not raised enough", sizes "not quite", "nowhere near"), not "too low". The cue (then "Lower your
  hips more"; reworded in Amendment 3) and `text` are unchanged by this amendment. `upper_arm_forward` with
  direction `less` keeps "too low". The live timed validator holds a Muse Spark line to the same meaning: for this
  fault the words "low", "lower", "hang" and "drop" carry no direction, so "thigh too low" fails the word test and the
  line falls back to `text_timed`.

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

## Amendment 3 (2026-11-01): the both-sides `thigh_forward` cues agree with their fault lines
Context: the insights show a fault's cue beside its words. After Amendment 1 the words say "Thighs nowhere near raised
enough", and the cue still said "Lower your hips more", which a reader takes as the opposite instruction (the third
walkthrough frame review, TICKET-062 R3). The delta review of that fix found the same fault in the other direction:
the `more` cue "Keep your hips higher" sat beside the line "thighs raised too high" (`part5/words.py`), which reads as
the opposite instruction too.

Decision (stakeholder-proxy, 2026-11-01, TICKET-062):
- The cue for `thigh_forward`, direction `less`, side `both` is "Raise your thighs higher" (four words). It uses the
  words of the fault line, so the two read as one instruction, and it stays true for a squat, where sitting deeper is
  what raises the thighs. The one-side cue "Lift your {side} knee higher" and every other cue are unchanged.
- The cue for `thigh_forward`, direction `more`, side `both` is "Keep your thighs lower" (four words), the mirror of
  the `less` cue: it names the thighs as the line "thighs raised too high" does and moves them the way the line asks,
  with no word about the hips. The one-side cue "Keep your {side} knee lower" and every other cue are unchanged.
- Detection, faults, scores, the schema and `text` are unchanged; `make check-5` stdout is byte-identical.

## Amendment 4 (2026-11-01): a low match has no tempo
Context: Part 7's QA sent a follower take that was the matching clip slowed to half speed (staging job 1538d81126c2,
rehab, 23.9 s against a 6.9 s example). Part 5 returned `score.tempo` `{ratio: 0.66, cue: "Slow down to match the
trainer"}` and Part 7 showed "Rushing", the opposite of what happened. The match was low (residual 0.6233 against the
limit 0.5677). The alignment had put all 208 example frames on take frames 59 to 195, which span 4.53 s of the take, and
the ratio is the follower time the matched frames span over the example's time, so it measured how long the stretch the
alignment found lasted and not how fast the take was done. ADR-0012 already gives every fault of a low match the
confidence "low"; the tempo carried no such mark and was shown as an action.

Decision (stakeholder-proxy, 2026-11-01T19:10Z, TICKET-063):
- When the document's `match.quality` is "low", every tempo in it is unmeasured: `score.tempo` and the `tempo` of each
  window (each rep, for a take compared rep by rep) are `{ratio: null, cue: null}`. A stretch of the example under 1 s
  already has that value, and the contract already says to show a window's `tempo.cue` only when it is not null.
- Nothing else is switched off by hand. With no `score.tempo.cue` the insights hold no tempo item, so the fault items
  keep all five places (this narrows "a tempo item is added last and always kept" to a measured tempo). Under the dance
  profile (ADR-0016) a null ratio is charged nothing, so `components.tempo` is 0.0 on each window and on the take, and
  the value is what the faults and the similarity give.
- One function decides: `score.tempo_ratio`. The windows of a take compared as a whole, the reps of a take compared rep
  by rep and the take itself all take their ratio from it. A take is accepted rep by rep only when its reps pass the
  guard, so today its quality is ok; the rule is written for both bases so it holds on whichever path a later change
  sends a refused take down.
- A match of quality "ok" is unchanged, and so is a take that could not be aligned at all: its zero score has no
  timeline and no tempo.
- No corrected ratio is offered. A partial alignment does not say how much of the take it left out, so any figure
  would be a second guess shown as a measurement.
- The case against: a take that is both rushed and a low match gets no "Slow down" either. That is the price of not
  telling a follower the wrong thing, and such a take already carries the `low_match` warning and grade F. Why the
  alignment of a slowed take is partial is a separate question (TICKET-064); this amendment changes no alignment,
  detection or guard.

Consequences: the schema is unchanged (`ratio` and `cue` are already nullable). The goldens and the stdout of
`make check-5` are byte-identical: no golden is a low match, and `make check-5` runs the fitness profile, which charges
no tempo. Part 7's half speed take still grades F on `low_match`; what changes is that it no longer carries a pace
instruction the alignment could not support. Tests: `tests/test_score_timeline.py` (the window basis under fitness,
rehab and dance, and the dance charge), `tests/test_reps.py` (the rep basis) and `tests/test_profiles_tempo.py` (half
speed copies of two committed seed 5 takes, one a good match and one a low match).
