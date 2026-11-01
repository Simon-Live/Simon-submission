# ADR-0015: Foot points enter as an optional side input from Part 2, with two measures: the foot's heading against the pelvis and its roll against world up
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-31

## Context
ADR-0014 ("What is not measured") records that the pipeline carries the 17 COCO joints, which end at the ankle,
so there is no "turn your foot out" or "keep your ankle straight" cue. Part 2 accepted adding six optional foot
points per person (left and right heel, big toe and small toe) as an `extra_joints` object beside `joints` in
`pose3d.json`, in the same frame, units and `conf` as the 17 (its TICKET-043, commit `e8ac336`, CONTRACT.md "Extra
joints (optional)"). Part 2's contract also says Part 3 does not touch `extra_joints`, and Part 3 never answered the
request for a field of its own. Part 4's expected clips carry no foot points. The operator ruled on 2026-10-31
(STATUS.md, Decisions, 13:30Z) that Part 5 reads the feet from Part 2's `pose3d.json` as an optional side input. The
spec is `docs/design/specs/foot-keypoints.md`. ADR-0014 named the measures in one line each; read closely, one of them cannot
measure what its name says.

## Options Considered

### Measure definitions
**`foot_rotation`**
- A: heel to big toe against the hip line, in the ground plane, signed per side (the ticket's wording).
  Pros: scale and camera free; a pelvis that twists with the feet reads 0; the constant offset between the big toe
  line and the foot's own axis cancels in a follower minus example difference. Cons: the big toe is the noisiest
  of the three points for a forward-facing camera.
- B: heel to the middle of the two toes. Pros: the two toes average their noise, and it sits nearer the clinical
  foot-progression axis. Cons: departs from the ticket; needs both toes where A needs one. Not chosen: A needs
  fewer points to be seen, so it is hidden less often, and the offset cancels.
- C: against the camera or world forward. Cons: changes with the viewing angle. Rejected.

**`ankle_inversion`**
- A: the angle at the ankle between the shin and the heel-to-toe-midpoint line (one reading of ADR-0014's "heel,
  ankle and toe midpoint angle"). Cons: a line has no roll about itself, so this is dorsiflexion plus toe-out, and
  a normal squat moves it by tens of degrees. The literal triangle (heel, ankle, toe midpoint) is rigid in a rigid
  foot and does not change with an inversion at all. Rejected.
- B: the normal of the foot plane against world up. Cons: a planted foot that collapses keeps the plane on the
  floor and reads 0. Rejected.
- C: the roll of the foot plane (heel, big toe, small toe) against the shin, about the foot's long axis (chosen first;
  NO-GO on seed 5 and replaced, see Amendment 1).
  Pros: reads the ankle joint's frontal-plane angle; the shin's part along the foot is dropped, so forward knee
  travel does not matter. Cons: needs all three foot points plus the knee, the roll comes from a toe pair 6 to 9 cm
  apart (the noisiest quantity in the feature), and a foot turned out under a shin that travels straight forward
  reads as a roll, which is real geometry and is handled by `explained_by` on seed 5.

### Where the foot points enter
- A: six new optional joints appended to `JOINTS` (23 joints). Pros: one array. Cons: the "canonical 17 in order"
  check in `io`, `MIRROR`, `ALL_JOINTS`, the `(F, 17, 3)` shape in the measures, alignment, visibility and the
  contracts of Parts 3 and 4 all change; every pair is touched whether it has feet or not.
- B: a side table inside `Clip`, parsed from Part 3's clip (`Clip.feet`). Was the plan while Part 3 might carry the
  points. Not possible: Part 3 does not carry `extra_joints` and has not agreed to.
- C: `compute(positions)` takes an optional second array. Same coupling as A without the registry, and every caller
  of `compute` needs the second argument.
- D: an optional side input, one Part 2 `pose3d.json` per clip, read by one module (`part5.feet`), with the foot
  measures in a separate registry (`FOOT_MEASURES`, as `VIEW_MEASURES` is) and added to the measure dicts only for a
  pair where both sides have usable feet (chosen). Pros: it follows the operator ruling and Part 2's contract; a pair
  without a feet file is untouched byte for byte; the clips, the alignment, the guard and the score's similarity term
  cannot move. Cons: a second input to carry (`--expected-feet`, `--follower-feet`), a time mapping between two files
  that were made from the same video, and a second registry that `detect` and the output vocabulary must learn.

### Which frame the foot measures are computed in
- A: the clip's frame, using Part 3's hips, knee and ankle with the side file's foot points. Cons: the two files can
  differ (Part 3 smooths, picks one person, and un-mirrors), so the foot and the shin would come from different
  skeletons. Rejected.
- B: the side file's own frame, from its own hips and foot points (chosen; the knee and ankle are not read). The result is a per-frame
  series on the side file's clock, mapped onto the clip's frames by time. Cons: the body in the side file and the body
  in the clip are not guaranteed to be the same person (the person id and the time check are the guard).

## Decision
- `foot_rotation`: option A. `degrees(atan2(sigma * (v . h), v . f))` in the ground plane, `v` heel to big toe, `h`
  the unit hip line (left minus right), `f` its quarter turn, `sigma` +1 left and -1 right; positive = toes away
  from the midline. NaN for a foot or hip line with under 25% of its length in the ground plane, a foot 90 degrees
  or more from the pelvis's forward, and any missing point.
- `ankle_inversion` (as amended, Amendment 1): the foot's roll about its long axis against world up,
  `degrees(atan2(-(y . outer), y . up))` with `y` = (0, 1, 0), `up` the plane normal (heel, big toe, small toe) out
  of the sole and `outer` = `up x axis` signed per side. It reads the three foot points and nothing else. Positive
  (`more`) = the foot on its outer edge, the sole turning toward the midline, the ankle rolling out; negative
  (`less`) = the inner edge down, the arch collapsing, the ankle rolling or caving in. Words and cues name the
  direction the ankle rolls ("left ankle rolling out" / "left ankle rolling in"), not inversion or eversion. (The
  first decision here, option C against the shin, was `degrees(atan2(-(s . outer), s . up))` with `s` knee minus
  ankle; it is withdrawn.)
- Foot points: option D. `--expected-feet PATH` and `--follower-feet PATH` (and `expected_feet`, `follower_feet` in
  `pipeline.run` and `analyse`), each a Part 2 `pose3d.json` shape (`frames[].people[]` with `joints` and
  `extra_joints`, top-level `t0_pts_ms`, optional `mirrored`). The person is `--expected-feet-person N` and
  `--follower-feet-person N` (default 0), matched to `people[].id`.
- Frame and time: the foot measures are computed per side-file frame in the side file's own frame (option B above).
  A clip frame at time `t` takes the side frame with the nearest `(t_ms - t0_pts_ms) / 1000` within half the side
  file's median frame step over all its frames (at least 0.008 s, half a 60 fps frame); otherwise NaN. A `mirrored: true` file has its left and right foot
  series swapped.
- Visibility: a point is seen when it is present, finite and `conf >= 0.5` (provisional); this applies to every point
  a measure reads, the hips included. A foot measure is usable in a clip when it is a number in at
  least 80% of the clip's frames; a pair is compared on the measures usable on both sides. A file with no
  `extra_joints`, or a pair where only one clip has feet, is not an error: the foot measures are hidden and
  `diagnostics.feet.hidden_reason` says why. A file that cannot be read, is not this shape, lacks the person or
  matches no clip frame in time is an `InputError` (exit 1). A take compared repetition by repetition hides the foot
  measures ("rep mode"; withdrawn by Amendment 3).
- Schema: `schema_version` 1.6.0 on every new document (the 1.5.0 precedent), body part `feet`, joint an ankle.
  The alternative, 1.6.0 only when a foot measure was compared, keeps every other golden byte for byte and costs a
  conditional in `output.py` and a version that depends on the data; rejected because a writer should have one
  version. The cost is a mechanical golden rebuild, as in ADR-0014.
- Calibration (ADR-0003): thresholds (`foot_rotation` 12, `ankle_inversion` 15 as starting values) and `explained_by`
  entries on seed 5 only; a per-measure go/no-go on seed 5 before the freeze; a new measure is a distinct approach
  family, so the one attempt left (seed 37) may be used; a red result ends the run DEGRADED. Synthetic feet are planted
  flat so the real co-firing (a knee caving, a leg swung out, a foot turned out under a forward shin) is tuned, not
  assumed away. A foot measure with no `rules.json` entry is computed and reported in `diagnostics.feet` but never
  raises a fault: it has no default threshold.
- Not decided here: what an example without feet is compared with. The foot measures are hidden for that pair (spec,
  open question 6); the real fix is the trainer's own Part 2 file through `--expected-feet`.

## Consequences
- **Positive**: the "twist your ankle" ask becomes measurable; pairs without a feet file are unchanged; the geometry
  is tested with hand-computed cases; the whole feature sits in one new module and one registry, and Parts 2 and 3
  need nothing from Part 5's side.
- **Negative**: a second input and a second registry; the roll of `ankle_inversion` is sensitive to toe noise; the
  synthetic proof is only as good as ASM-013; every golden changes by the version.
- **Neutral**: the viewer needs no change (the fault highlights `*_ankle`); `make check-5` moves only by design when
  `rules.json` gains the foot keys (`rules_sha256` and `detection_sha256` change at the freeze), and the seed 31 numbers
  are identical because its takes carry no feet.

## Assumptions
- ASM-013: synthetic planted feet are a fair proxy for Part 2's estimated feet (confidence low).
- Part 2's `pose3d.json` is in the canonical frame (x subject-left, y up, z anterior, metres) with `conf` on every
  point, and its foot points share that frame and `conf` meaning (its TICKET-043 acceptance).

## Reversal Cost
Low before the freeze: the helpers are private, the side input is one module and two options. Medium after the
freeze: seed 37 is spent and the schema is 1.6.0, though the foot measures can be switched off by removing their
`rules.json` entries and the grid fault types, since they are additive.

## Pre-Mortem (MANDATORY)
It's 6 months from now and this decision was a disaster. Why?
1. The toe pair is too noisy on real takes and `ankle_inversion` fires on nothing. Likelihood: M, Impact: M,
   Mitigation: the confidence gate, thresholds from the noise on correct takes, the go/no-go on seed 5, real takes
   reported and never gated, and the option to ship `foot_rotation` alone.
2. Seed 37 is red and the delivered run ends DEGRADED. Likelihood: L, Impact: H, Mitigation: the freeze happens only
   after a clean differential on seed 5 (old fault types and correct takes unchanged); if no foot measure passes
   there is no freeze.
3. The example has no feet file, so the feature does nothing in the product. Likelihood: H, Impact: M, Mitigation:
   the trainer's own Part 2 `pose3d.json` goes to `--expected-feet`; without it the pair-level exclusion keeps the
   result honest rather than inventing a foot.
4. A follower reads the ankle words the wrong way round. Likelihood: M, Impact: L, Mitigation: the sign is tested on
   both sides in the geometry tests, and the words name the direction the ankle rolls ("rolling out" for the foot
   on its outer edge); the Writer skill reviews them. This did happen once: after Amendment 1 the sign flipped from
   the shin to the foot's own roll but the words ("leaning in" for `more`) still read the old way, so they pointed
   the wrong way until the pre-freeze review (R6, fixed in Amendment 2).
5. The side file and the clip are from different takes or people, and the time mapping lines up two unrelated
   skeletons. Likelihood: L, Impact: M, Mitigation: no frame within the time window is an error, the person id is
   explicit, and the foot measures never mix the two files' joints.

## Dissent (MANDATORY)
Reviewed by: TICKET-040 feet-core lane (implementer, self-review); independent review pending at the consolidated review.
Concerns:
- Why not use the heel to toe midpoint for `foot_rotation`: it is the nearer-to-anatomy axis and less noisy. The
  ticket says big toe, the offset cancels, and fewer points means fewer hidden frames. Revisit if the real-take
  report shows the big toe is the noisy one.
- Why a separate registry rather than 23 joints: honest cost is a second code path in `detect` and `output`; the
  benefit is that no pair without a feet file can change, which the held-out protocol (ADR-0003) needs to be provable.
- Why spend the last seed on this: the stakeholder-proxy ruled on 2026-10-31 that new detection keys need seed 37.
  The go/no-go rule makes the attempt conditional on a clean seed 5 result; the run's delivered green is not put at
  risk by a measure that is not ready.
- Why read Part 2's file when Part 5 is meant to consume Part 3's: Part 3 does not carry the points and its owner did
  not answer. The operator ruled for the side input; the cost is one extra option per clip and the time mapping.
- The 1.6.0 bump on every document touches goldens for no change in most documents: kept for one writer, one
  version, with the data-dependent alternative recorded above.

## Amendment 1 (2026-10-31): `ankle_inversion` option C was NO-GO on seed 5; the foot's roll against world up replaces it
Option C (the roll against the shin) was calibrated on seed 5 first (`progress/calibrate-feet-seed5-attempt-a.log`)
and failed the go/no-go: it raised faults on correct takes and on `knee_caving` takes at the thresholds low enough to
find the planted faults, and found almost none of its own (recall 0.00 to 0.25 at good light, `more` never) at the
thresholds that stopped those. The shin is a second moving quantity, so the knee's travel in a squat reached it. The
bounded second attempt, decided on seed 5 only, is a variant of option B that keeps the pitch out:
`degrees(atan2(-(y . outer), y . up))` with `y` = (0, 1, 0) world up, `up` and `outer` as in option C. The measure
reads the heel, big toe and small toe and nothing else; positive = the sole turning toward the midline (the outer
edge down). It is 0 for a flat foot whatever its heading or pitch, and no knee or ankle movement reaches it. The
blind spot recorded for option B stays: an ankle that collapses over a foot planted flat on the floor reads 0. The
seed 5 result is `progress/calibrate-feet-seed5-attempt-b.log` (both measures GO; `docs/design/specs/foot-keypoints.md`,
"Seed 5 result"). This text first said the words and cues were unchanged; that was wrong (Amendment 2).

## Amendment 2 (2026-10-31): the ankle words follow the foot's roll, not the shin
Amendment 1 changed what `ankle_inversion` measures but left the words as they had been for the shin, so `more` (the
foot on its outer edge, the ankle rolling out) read "ankle leaning in" and `less` (the inner edge down, the ankle
rolling in) read "ankle leaning out": each pointed the wrong way. The pre-freeze review found it. Now `more` reads
"left ankle rolling out" with the cue "Keep your left ankle straight" and `less` reads "left ankle rolling in" with
the cue "Stop your left ankle rolling in"; `lateral` for `more` is the fault's own side (the outer edge) and for `less`
the other side; the live validator takes "out" words as `more` and "in" words as `less`; and the ankle's timed
lines may name no knee or thigh, because the measure reads neither. The label type ids `ankle_rolled_in` and
`ankle_rolled_out` are kept unchanged as identifiers (the take id seeds the foot's random stream): `ankle_rolled_in`
is the planted roll for `ankle_inversion` `more`, which now reads "rolling out", and `ankle_rolled_out` the one for
`less`, which reads "rolling in". No measured number changes. The label file keeps its old `text`, but the staging page
does not show it for a foot take: the picker label and `api/samples` `faults[].text` use the analysis words for the
label's measure, direction and side (delivery review N1; `docs/design/specs/foot-keypoints.md`, "The ankle label ids read the
old way round", and `docs/design/specs/staging.md` AC-S10), so a take's name and its result point the same way.

## Code Backlinks (updated as code is written)
- `part5/feet.py` (the side file, the time mapping, usable and hidden), `part5/measures.py` (`_foot_rotation`,
  `_ankle_inversion`, `FOOT_MEASURES`, `compute_feet`), `part5/pipeline.py` (`run`, `_foot_series`), `part5/detect.py`
- `part5/output.py` (1.6.0), `part5/words.py`, `part5/cues.py`, `part5/lateral.py`, `part5/phrasing/template.py`
- `part5/cli.py`, `part5/doctor.py`, `part5/contract.py`, `part5/evaluate.py`, `part5/rules.json`
- `tests/test_foot_geometry.py`, `tests/test_feet.py`, `tests/test_feet_faults.py`
<!-- In code: # ADR-0015: reason -->

## Amendment 3 (2026-10-31, ADR-0017, TICKET-044): the foot measures are compared rep by rep
Rep mode no longer hides the foot measures. When an example of two or more reps made every take of it a rep-by-rep
comparison (attempt 4), hiding them would have taken the dance's foot labels out of the gated slices (8 per angle on seed
37) and half of them on seed 5 (11 of 24 found at good light, against 22 with them), so `pipeline.run` hands the foot
series to `repwise.compare`, which cuts the expected one with the reference and resamples the follower's with each rep like
the joints. The definitions, the visibility rule (80% of the frames, `conf` 0.5), the thresholds (14 and 14 degrees) and the
words are not touched: those are this ADR's, and a change to them is a distinct family (TICKET-040). `REP_MODE_REASON` is
gone; `docs/design/specs/rep-persistence.md` has the record.

## Amendment 4 (2026-11-01, attempt 5, ADR-0017, TICKET-040): a foot measure that jitters is not read
Attempts 3 and 4 were both red on the same cause. `ankle_inversion` reported the far foot of a correct take filmed from
the side as rolling out (21.5 degrees on `dance_side_good_01_correct` at seed 37, 22.4 on `exercise_side_good_00_correct`
at seed 67), and a correct good-light take must report no fault and score A. The stakeholder-proxy ruled on 2026-11-01T03:15Z
(confidence high), verbatim: "attempt 5 is TICKET-040's foot-measure family per ADR-0017's red-on-67 row. Its core is a
change to foot-measure definition or visibility (for example a view-aware far-foot rule), never a threshold or foot-floor
nudge alone. It is tuned on seed 5 only with ADR-0015's go/no-go, the retimed bar and a seed 5 count of far-foot labels
found, reviewed before the freeze, frozen by 2026-11-02T06:00Z and scored once on seed 71."

**Why the far foot reads a roll that is not there.** The roll is the height difference of the big and small toe over their
lateral spread, 6 to 9 cm, so a centimetre of vertical error is 8 degrees and the foot the camera sees least (the far one
in a side view; in the synthetic takes the camera noise of the far side is multiplied by `1 + yaw / 90`, ASM-013) reads
tens of degrees. On the seed 5 correct good-light takes the series of the far foot at the side has a standard deviation of
14 to 28 degrees, against 4 to 11 for the near foot. Persistence cannot remove it: the noise is smooth over a few frames,
and a stretch of 32 frames past 14 degrees happened by chance on two of the eight correct side takes of seeds 37 and 67.

**What the files carry, which decides the options.** The clip is in the subject's own frame (hip line along x, forward along
z), and so is Part 2's canonical frame (the hip line of all three real files lies exactly along x in every frame, the side-view
example included), so the camera's direction is nowhere in either; Part 2's `provenance` names the source of the focal length
and no direction; the foot points of all three real Part 2 files have `conf` 1.0, and Part 2 writes a joint's `conf` as 1.0, or 0.3 for a joint outside the image (ADR-0011), so `conf`
says nothing about which foot is occluded. The synthetic base takes carry no `conf`, and the dropout copies that do are reported slices the failing takes
are not in. A rule that reads the camera axis or the foot's `conf` therefore cannot reach the failing takes; the one thing
the data carry about a foot the camera does not see is that its points move about. The options and their seed 5 numbers are in
`docs/design/specs/foot-keypoints.md` ("Attempt 5").

**Decision.** A foot measure whose rules entry has a `max_jitter_deg` is not used in a clip when its jitter is above it. The
jitter is the median absolute change of the measure between consecutive frames of the side file, in degrees a frame, over
the stretch of the file the clip takes (`feet.jitter`, `feet.jitter_limits`). A median step reads the noise and not a fault:
a fault grows over many frames, so its steps are a minority, while smooth noise still changes almost independently from
one frame to the next. The rule is the definition of "unseen" for a foot whose camera is not known: the foot says for itself
that it is not seen, and no view has to be guessed. It acts per measure and per foot, before the pair is formed, so the
near foot of the same take and the other measure of the same foot are untouched. A hidden measure is out of `usable` and
`compared` (the 1.6.0 fields, unchanged in shape), and `hidden_reason` names it when nothing else is left. `max_jitter_deg` is
4 degrees a frame on `foot_rotation` and `ankle_inversion` in `part5/rules.json` (which moves `rules_sha256` and
`detection_sha256`); it is not swept, and not a tolerance a profile relaxes.

**How 4 was chosen, and why it is not a threshold nudge.** The value is not read off the held-out seeds or the failure. It is
the lowest value on a 0.5 grid that costs seed 5 nothing at good light: every slice's precision, recall and faults on correct
takes, every foot label found (22 of 24, far foot included) and every correct take an A are as before at 4 and above, and 3.5
already loses a label. It sits above the jitter of every foot the camera sees at good light (largest 3.7 degrees a frame for
`ankle_inversion`, 3.0 for `foot_rotation`) and below the median of the far foot at the side (5.5 and 3.9). The thresholds
(14 and 14) are the 00:05Z rule's: they tie at the best objective strictly inside their plateau (11 to 15) and are kept. The
change that matters is the rule, which takes the feet that were the failure out of the comparison; the number only says
how unsteady is too unsteady.

**Costs, stated.** (1) Low light: every foot jitters above 4 there (2.3 times the good-light noise), so both foot measures are
hidden on nearly every low-light take, and the reported low-light recall falls (seed 5 low/front 0.96 to 0.71, low/45 0.92
to 0.67, low/side 0.67 to 0.54) while precision moves by 0.05 at most (0.66 to 0.71, 0.42 to 0.41, 0.18 to 0.17). This is the
rule working, not a side effect: those readings were noise, and a coach that is silent about a foot it cannot see is the
better product. Low light is reported and never gated (ADR-0003). (2) A far foot with a real
fault the camera cannot show is not found: on seed 5 at good light there is one far-foot `ankle_inversion` label and it was
already missed; a `both` label is still found from the near foot. (3) A near foot above the limit by chance is hidden too;
none of the 104 near feet on seed 5 at good light is. (4) The real Part 2 files jitter by 0.3 to 0.9 degrees a frame, so
the rule does nothing on them today (`make report-real` is unchanged); it is a synthetic-noise rule until a real far foot
shows otherwise (ASM-013). (5) The limit is per frame of the side file, so it assumes frames 1/30 to 1/10 s apart.

**Not chosen.** A camera or `conf` rule (no signal, above); the far foot as the one that jitters more than the other (the
ratio of the two feet's jitter overlaps between views: right over left 0.72 to 1.43 at the front, 1.28 to 2.86 at the side
on seed 5, and it cannot see two bad feet); the change of the foot's shape between frames (the distances between heel and
toes), which is blind to the vertical error that makes the roll and depends on the view; the roll against the shin (this
ADR's Amendment 1: NO-GO on seed 5, and the far-foot error is in the toes, which the shin does not carry); a threshold or floor
change alone (the ruling). Reversal: remove the two `max_jitter_deg` keys and the pipeline reads the feet as Amendment 3 had
them (`feet.jitter_limits` returns nothing).

**Dissent.** The rule is tuned to a synthetic noise model, and the held-out series is the same model (ASM-002), so a green seed
71 says the rule fits that model, not that Part 2's far foot behaves so. A median step also hides a real foot that moves fast
(a dance step at a low frame rate) if its roll changes more than 4 degrees between frames for half the clip; no seed 5 take does
(the largest jitter of a near foot is 3.7). If a real far foot shows a bias with no jitter, this rule will not see it, and a
view-aware rule from a camera Part 3 could pass on would be the next candidate.

Code (`# ADR-0015` backlinks): `part5/feet.py` (`jitter`, `jitter_limits`, `_unsteady`, `FootSide.unsteady`), `part5/pipeline.py`
(`run` hands the limits to both `load_side` calls), `part5/rules.json` (`max_jitter_deg`), `part5/calibrate.py` (`--feet` as a
re-sweep, `held_table`), `tests/test_feet_steady.py`. The record is `docs/design/specs/foot-keypoints.md` "Attempt 5".
