# Spec: foot keypoints, `foot_rotation` and `ankle_inversion` (TICKET-040, Part 5 side)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted (the cue wording follows the ticket's two phrases and the table below; the Writer review is recorded at the consolidated review)
Date: 2026-10-31
Request Type: feature-mod
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADRs: ADR-0015 (this feature), ADR-0014 ("What is not measured"), ADR-0003
(held-out calibration), ADR-0011 (compare only what the camera sees), ADR-0004 (a measure added after the first
calibration). Ticket: TICKET-040. Companion specs: `calibration.md`, `check-5.md`.

## Overview
Part 5 could not say "turn your left foot out" or "keep your left ankle straight" because the pipeline carries the 17
COCO joints, which end at the ankle. Part 2 publishes six more points per person (heel, big toe and small toe of each
foot) as an `extra_joints` object beside `joints` in its `pose3d.json`, in the same canonical frame, units and `conf`
as the 17 (its TICKET-043, commit `e8ac336`, CONTRACT.md "Extra joints (optional)"). Part 2's contract also says Part 3
does not touch `extra_joints`, so a Part 3 `skeleton.json` has no feet. The operator ruled on 2026-10-31 (STATUS.md,
Decisions) that Part 5 reads the feet from Part 2's `pose3d.json` as an optional side input, one file per clip.

This spec covers Part 5's side: that input and how it is mapped onto a clip, two new measures computed from it, when
they are hidden, their cues and words, the output, and the calibration on seed 5 with the single held-out attempt
left (seed 37). It is built in two lanes. The code, the tests, the contracts and the docs are the feet-core lane
(AC-FOOT-01 to AC-FOOT-18). The synthetic side files, the thresholds, the freeze and the held-out attempt are the
data lane (AC-FOOT-19 to AC-FOOT-21).

## Why This Is Wrong (Dissent-First)
1. **The toes are too close together to give a roll.** The big and small toe are 6 to 9 cm apart; a 3D estimate
   from video is good to a few centimetres in depth. The roll of the foot plane can therefore be mostly noise on
   real takes, and the synthetic points (below) are built from our own rigid foot, so they will look cleaner than
   Part 2's. Answer: the roll is measured against world up, which is a known direction and not a second noisy
   quantity, and the follower is compared with the example's own roll; low-confidence points hide the measure; the thresholds come from the noise on correct takes (seed 5); a go/no-go rule below keeps a
   measure that cannot be separated from noise out of detection; real takes are reported, never gated.
2. **ADR-0014's own definition of `ankle_inversion` cannot measure inversion.** "The heel, ankle and toe midpoint
   angle" is the angle of a triangle inside a rigid foot, which a roll leaves unchanged, and the angle between the
   shin and the heel-to-toe line is dorsiflexion, which changes by tens of degrees in a normal squat and would read
   the squat as a fault. Answer: the roll of the foot plane about the foot's long axis against world up (below);
   ADR-0015 records why the earlier wording is not used.
3. **Seed 37 is the last held-out seed and the run is already green.** Attempts on seeds 29 and 31 passed. A new
   measure is a distinct approach family (ADR-0003), so a third attempt is allowed, but a red result on seed 37 ends
   the run DEGRADED with every attempt published. Answer: the go/no-go rule below decides at the freeze, on seed 5
   only, whether a foot measure ships; if none passes, the freeze does not happen and seed 37 stays unused.
4. **The example has no feet unless the trainer's own Part 2 file is given.** Part 4's expected clips carry no foot
   points. Answer: `--expected-feet` takes the trainer's own Part 2 `pose3d.json`; without it the pair is compared on
   what both sides show (ADR-0011), the foot measures are hidden and `diagnostics.feet` says why (open question 6).
5. **The first definition read the shin, and a moving leg moved it.** The first version of `ankle_inversion` measured
   the foot plane's roll against the shin. A knee caving in, a leg swung out, or a squat's forward knee travel over a
   turned foot tilts the shin across a flat foot, so it raised `ankle_inversion` on correct takes (45 degrees and
   side) and on `knee_caving` takes, and at the thresholds that stopped those it found almost none of its own faults at good
   light (recall 0 to 0.25; seed 5, `progress/calibrate-feet-seed5-attempt-a.log`: NO-GO). Answer: the measure now reads the foot
   alone, its roll about its long axis against world up (below), so no leg movement can reach it. Cost: it needs
   the foot points to be levelled by the same world up as the 17 joints (open question 5), and a foot that really
   leans on its edge under a loaded ankle reads that lean, which is the fault being looked for.
6. **Two files describe the same person.** The side file's skeleton and the clip's skeleton come from the same video
   but not the same pass: Part 3 smooths, picks one person and un-mirrors. A foot measure that mixed the hips from
   one with the toes from the other would measure the disagreement. Answer: every foot measure is computed inside the
   side file from its own hips and foot points; the clip only supplies its frame times and the pair's
   timing. A wrong file shows up as no frame matching in time (an error) or a person id that is absent (an error).

## User Story
As a follower, I want to be told when my foot points the wrong way or my ankle rolls, in plain words and as a cue,
so that I fix what the 17 joints cannot show. As Part 7, I want these faults in the same `analysis.json` shape,
with `joint` an ankle, so the viewer needs no change.

## The two measures
Frame: the side file's own frame, which is Part 2's canonical frame (hip-centred, x subject-left, y up, z anterior),
so the ground plane is x-z. Both are angles of directions, so body size, translation and the camera angle do not
matter. Sides are the subject's own. `kind` is `direction`, `body_part` is `feet`, and the fault is reported at joint
`{side}_ankle` (so `faults[].joints` is the ankle, a canonical joint, ADR-0006).

### `foot_rotation` (left and right)
Toe-out of the foot against the pelvis, degrees, positive = the toes point away from the midline.
With `h` = (left hip minus right hip) and `v` = (big toe minus heel), both taken in the ground plane (x, z), and
`f` = `h` turned a quarter turn (forward of the pelvis, `f = (-h_z, h_x)` in (x, z)):
`foot_rotation = degrees(atan2(sigma * (v . h/|h|), v . f/|h|))`, `sigma` = +1 left, -1 right.
- The heel to big toe vector is the foot axis the ticket names. Anatomically the foot's own axis sits a few degrees
  toward the little toe; that is a constant offset in every foot, and a fault is a follower minus example
  difference, so it cancels.
- Against the hip line, not the camera or the world: a pelvis that twists with the feet reads 0, and the measure
  is the same from every camera angle.
- Height is ignored: a heel lifted off the floor does not change the heading.

### `ankle_inversion` (left and right)
Roll of the foot about its long axis against world up, degrees, positive = the sole turns toward the midline
(inversion, the outer edge going down).
The foot has a frame: long axis `a` from the heel to the middle of the two toes; `up` the normal of the plane
through heel, big toe and small toe, pointing out of the sole; `outer` = `up x a`, pointing to the foot's outer
edge (signed per side, so it points away from the midline on both feet). World up is `y` = (0, 1, 0). Seen down
the long axis it has a part along `up` and a part along `outer`:
`ankle_inversion = degrees(atan2(-(y . outer), y . up))`.
A foot flat on the floor reads 0 whatever its heading and whatever its pitch (a raised heel or lifted toes: the part
of `y` along `a` drops out of both terms, and the pitch scales both by the same cosine). Rolled by `r` degrees about
`a` with the outer edge going down it reads `+r` on either foot; the mirrored foot reads the same. It does not read
the knee or the ankle, so a knee travelling over the toes, caving in or swung out, and a pelvis that tilts, move
nothing.

**Why this definition (the choice the ticket asked for, and the second attempt at it).** Four candidates:
1. *Angle at the ankle between the shin and the heel-to-toe-midpoint line.* A line has no roll about itself, so
   this is dorsiflexion plus toe-out, not inversion, and a deep squat moves it by tens of degrees. Rejected.
2. *Roll of the foot plane about its long axis against world up.* It reads how far the foot has tipped onto an
   edge, from the three foot points and the vertical alone. It is the first attempt's rejected candidate, taken up
   again after the shin version failed on seed 5 (below). Its blind spot is the one the first attempt named: an ankle
   that collapses over a foot planted flat on the floor reads 0, because the foot plane has not moved. What it
   reports is the foot's own roll (the foot tipping onto its inner or outer edge), and the planted faults of
   ASM-013 are exactly that, so the seed 5 result says the measure is clean and separable, not that it sees every
   real ankle collapse. Chosen in its long-axis form, which a raised heel does not move (the plain normal against
   vertical would read the pitch as a roll).
3. *Roll of the foot plane against the shin, about the long axis* (the first definition, `ADR-0015` option C). It
   reads the ankle joint's frontal-plane angle, but the shin is a second moving quantity: the knee's travel in a
   squat, a knee caving and a leg swung out all move it. On seed 5 it raised faults on correct takes at the
   thresholds low enough to find the planted faults, and fell to recall 0 to 0.25 at the thresholds that stopped
   those: NO-GO (`progress/calibrate-feet-seed5-attempt-a.log`). Replaced.
4. *The same roll against the hip to ankle line.* No better than the shin for the same reason. Not built.
Cost accepted: the roll depends on the toe pair (Why This Is Wrong, 1), on the foot points being levelled by the
same world up as the joints (open question 5; a side file whose frame is tilted reads a constant roll in both
clips, which cancels in follower minus example), and it does not see an ankle that collapses over a planted foot.

### Geometry guards (not detection thresholds)
A frame is NaN, never a guess, when the points cannot give a number. The limits are constants in
`part5/measures.py` and may be changed only with the spec:
| Guard | Value | Meaning |
|---|---|---|
| `MIN_GROUND_SHARE` | 0.25 | the hip line and the foot axis each need this share of their length in the ground plane (a foot standing on its toe has no heading) |
| `MIN_CROSS_SHARE` | 0.25 | world up needs this share of its length across the foot's long axis (a foot pitched more than about 75 degrees, standing on its toes, has no roll) |
| `MIN_TOE_SPREAD` | 0.1 | sine of the angle at the heel between the two toes (collinear points have no foot plane) |
Also NaN: a foot 90 degrees or more from the pelvis's forward (heel and toe swapped, not a stance); world up on the
sole's side of the foot plane (toes swapped, or a foot rolled 90 degrees or more); any NaN input. An unknown `side` is a
`ValueError`.

## When a foot measure is hidden
- **Per frame.** A point is seen when it is present, finite and its `conf` is at least `FOOT_MIN_CONF` (0.5,
  provisional; open question 4). A point with no `conf` is seen; `conf` null is not seen. The 0.3 mark that Part 2
  uses for a joint outside the image (ADR-0011) is below 0.5, so such a point is hidden. The rule applies to every
  point a measure reads, the hips included: `foot_rotation` reads both hips, the heel and the big toe;
  `ankle_inversion` reads the heel, big toe and small toe of that side (not the knee or the ankle). A foot measure is NaN in a side
  frame where any point it reads is not seen or the geometry guards say so.
- **Per clip (ADR-0011).** A foot measure is usable in a clip when it is a number in at least 80% of the clip's
  frames (`MIN_SEEN_SHARE`). Clip frames with no side frame in the time window count as not a number. A clip with no
  feet file, or a file with no foot points, has no usable foot measure; it is not "unknown", unlike a body clip with
  no `conf`, because points that were never given cannot be taken from the other clip.
- **Per pair.** The pair is compared on the foot measures usable in both clips. Hidden measures are not scored, not
  aligned on and cannot produce a fault. A take compared repetition by repetition (ADR-0010) hides all four ("rep
  mode"); so does a take that could not be aligned.
- **`diagnostics.feet`** is `{expected, follower, compared, hidden_reason}`, present exactly when a feet file was
  given for either clip. `expected` and `follower` are `{source, person, frames_matched, usable}` (`source` is the
  path or null, `frames_matched` how many of the clip's frames took a side frame, `usable` the measures seen in 80% of
  them). `compared` lists the measures the pair was compared on. `hidden_reason` is null when any was compared, and
  otherwise plain words: `no expected feet file was given`, `the follower feet file has no extra_joints (no foot
  points)`, `no foot measure is seen in 80% of the follower frames`, `no foot measure is usable in both clips`,
  `rep mode: the foot measures are not compared repetition by repetition`, or `the take could not be aligned, so
  nothing was compared`; two reasons (one per clip) are joined with `; `. A pair where no feet file was given is
  analysed and written exactly as before apart from `schema_version`.

## Cues and words
`direction` is the sign of follower minus example, as for every cue (ADR-0014). All cues are at most 6 words,
`cue_kind` is `position`. The two phrases in the ticket ("Turn your left foot out", "Keep your left ankle straight")
are kept word for word; the rest follow them.
| Measure | Direction | One side | Both sides | Plain words (`text`, `{q}` as in `words.py`) |
|---|---|---|---|---|
| `foot_rotation` | `more` | Turn your left foot in | Turn your feet in | left foot turned out {q}more than the example |
| `foot_rotation` | `less` | Turn your left foot out | Turn your feet out | left foot {nq} turned out enough |
| `ankle_inversion` | `more` | Keep your left ankle straight | Keep your ankles straight | left ankle rolling out{aq} |
| `ankle_inversion` | `less` | Stop your left ankle rolling in | Stop your ankles rolling in | left ankle rolling in{aq} |
AC-CUE-01 asks that opposite directions differ, which is why `ankle_inversion` has a second cue. The ankle words name
the direction the ankle rolls: `more` is the foot on its outer edge (a positive roll, the sole turning toward the
midline), which reads "rolling out"; `less` is the inner edge down (the arch collapsing, the ankle caving in), which
reads "rolling in". They avoid inversion and eversion, whose everyday and clinical uses disagree. (The first words,
"leaning in" for `more`, were written for the shin version of the measure and pointed the wrong way once the measure
became the foot's own roll; ADR-0015 Amendment 2.) ADR-0014's rule that no cue names the ankle, heel or toes is
narrowed in AC-FOOT-14. `lateral` (the side the body part is too far toward, ADR-0009) is the fault's side for
`foot_rotation` `more` and the other side for `less` (the toes point toward it), and the same for `ankle_inversion`:
the fault's side for `more` (the outer edge goes down) and the other side for `less` (the inner edge goes down);
`lateral_m` is not written. The timed words are the plain words plus the time, as for every measure with no lateral
noun. The live validators (`phrasing/template.py`) read an "out" word as `more` and an "in" word as `less` for the
ankle, and a timed ankle line may name no knee or thigh because the measure reads neither.

## Input mapping
The written contract with the data lane and with anyone who produces a feet file.

**The side file** is a Part 2 `pose3d.json`:
`{"frames": [{"frame": int, "t_ms": float, "people": [{"id": int, "joints": {<17 COCO names>: {x, y, z, conf}},
"extra_joints": {left_big_toe, left_small_toe, left_heel, right_big_toe, right_small_toe, right_heel: {x, y, z, conf}}}]}],
"t0_pts_ms": float, "mirrored": bool (optional), "provenance": {...}}`. A synthetic side file uses the same shape with
`provenance.source` `synthetic`. Only the two hips and the six foot points are read; other names, the knees and ankles
included, are ignored, and a missing, text or low-`conf` knee or ankle is no error and changes nothing.
`t0_pts_ms` defaults to 0, `mirrored` to false, `extra_joints` to absent.

**Per side frame**, inside the side file's own frame, `foot_rotation` and `ankle_inversion`, left and right, are
computed from the person's own hips and `extra_joints` with the geometry above, following the naming and
sidedness of `measures.py` (`left_foot_rotation`, `right_foot_rotation`, `left_ankle_inversion`,
`right_ankle_inversion`). If the file's top-level `mirrored` is true the left and right foot series are swapped (Part 3
un-mirrors the body; Part 2 CONTRACT.md "mirrored").

**Time.** A clip frame at time `t` (seconds, the clip's own `t`) takes the side frame whose
`(t_ms - t0_pts_ms) / 1000` is nearest, provided it is within half the side file's median frame step, taken over
every frame of the file (not only the frames where the person is present), and at least 0.008 s (`MIN_MATCH_S`, half
a 60 fps frame); otherwise that frame's foot values are NaN. The window has a microsecond of slack (`TIME_SLACK_S`),
because `t_ms` is written to three decimals and a 60 fps clip frame midway between two 30 fps side frames is exactly
half a step from both. The follower's series is then resampled onto the expected clock with its joints.

**Person.** `--expected-feet-person N` and `--follower-feet-person N`, default 0, matched to `people[].id`. A person
missing from some frames gives NaN there.

**Errors** (`InputError`, exit 1, `part5 analyse: <file>: ...`, nothing written): the file is unreadable or not this
shape (not JSON, no `frames`, a frame without a numeric `t_ms` or a `people` list, a `people` entry that is not an
object, a point that is not an object or has a text coordinate or `conf`, `t0_pts_ms` or `mirrored` of the wrong
type); the person id is absent from every frame (the message lists the ids present, a text id included, as in
`[0, 7, 'left-dancer']`); no clip frame matches a frame of the file in time. **Not errors:** a file with no `extra_joints` (Part 2's cpu
backend) and a pair where only one clip has feet: the foot measures are hidden for the pair, with the reason in
`diagnostics.feet`.

**API.** `part5.pipeline.run(expected, follower, rules=None, *, ..., expected_feet=None, follower_feet=None,
expected_feet_person=0, follower_feet_person=0)` takes paths or None; `analyse(...)` passes the four through.
`part5 analyse ... [--expected-feet PATH] [--follower-feet PATH] [--expected-feet-person N] [--follower-feet-person N]`.
`labels.json` takes may carry `expected_feet` and `follower_feet`, paths from the repository root like `expected` and
`follower`; the label types are in AC-FOOT-18. `rules.json` gains `measures.foot_rotation.threshold_deg` (starting
value 12.0) and `measures.ankle_inversion.threshold_deg` (15.0); a foot measure with no entry is computed but never
raises a fault.

## Pipeline integration
Foot measures are a separate registry, not part of `MEASURES`, so alignment, the guard, the score's similarity
term, `diagnostics.visibility` and every pair without a feet file stay as they are (the same reason `VIEW_MEASURES`
is separate). The clips (`Clip`, `io`, `normalise`, `repwise`) are untouched.
1. `pipeline.run` loads the two sides right after the clips (`feet.load_side(label, path, person, clip.t)`), so a bad
   file is an error whatever the take does later, and pairs them (`feet.pair_of`; None when neither file was given).
2. `feet.load_side` parses the file (`_parse`), computes the four series per side frame (`measures.compute_feet`),
   swaps them if `mirrored`, maps them onto the clip's frames by time and lists the usable measures.
3. For the whole-clip comparison, `pipeline._foot_series` takes the measures compared on both sides: the expected
   series on its own frames, the follower's resampled onto the expected clock like its joints. They are merged into the
   measure dicts handed to `detect` only; `check_movement`, `align` and the rep comparison get the body dicts.
4. `detect.differences` visits `MEASURES` plus the foot measures present in both dicts; `detect` skips a foot
   measure with no `rules.json` entry. Smoothing, persistence, overlap, `explained_by` and the side merge apply
   unchanged; `Fault.joint` and `body_part` come from `measures.ALL_SPECS`.
5. Output: `ALL_SPECS` feeds `GENERIC_MEASURES`; `contracts/analysis.schema.json` 1.6.0 gains the two names in the
   `measure` enum, `feet` in `body_part`, a pinned joint per side, and `diagnostics.feet`; `schema_version` is `1.6.0`
   on every new document, as 1.5.0 was (ADR-0015 weighs the alternative of bumping only when foot measures were
   compared). A document written before 1.6.0 still validates.
6. `score`: foot faults cost points like any fault; `mean_z` keeps reading `MEASURES` only, so a take without foot
   faults scores as before.

## Calibration plan (seed 5 only; ADR-0003)
1. **Synthetic feet, derived how.** `scripts/make_dummy_followers.py --feet` adds the six points to every take,
   after the 17 joints are final (faults, natural variation, time warp) and before camera noise, from a rigid foot
   template scaled by the take's body scale: heel 0.07 m behind and 0.08 m below the ankle; big toe 0.17 m ahead,
   0.035 m to the inner side; small toe 0.12 m ahead, 0.035 m to the outer side; both toes 0.08 m below the ankle.
   The foot is planted flat: its up is world up and its heading is the pelvis's forward (the hip line turned a
   quarter turn) turned out by a per-take toe-out drawn from 4 to 10 degrees plus the 1.2 degree drift
   `natural_variation` gives other joints. The six points then get camera noise at the take's sigma, with the far
   side multiplied as for the other joints, and the hip midpoint of the (noisy) joints is taken off them as it is
   off the joints. The expected side is the same derivation from Part 4's clip with a fixed toe-out of 7 degrees
   and no drift or noise.
   **Where they are written (the operator ruling of 2026-10-31T13:30Z: feet come from Part 2's `pose3d.json` as an
   optional side input).** Every foot file is Part 2's `pose3d.json` shape, read by `pipeline.run(...,
   expected_feet=PATH, follower_feet=PATH)`: `frames[].people[0]` with the 17 `joints` and the six `extra_joints`
   (`{x, y, z, conf}`), `t_ms` = `t` times 1000, `t0_pts_ms` 0, and `provenance` `{source: synthetic, generator,
   seed}`. A take's file holds the take's own final 17 joints (the same bytes as its `skeleton.json`, `conf` 1.0)
   so the foot measures are computed inside it, in one frame, and the six points. It sits beside the take as
   `feet.json`. The expected file is a derived fixture, the same for every seed:
   `fixtures/input/expected-feet/<set>/feet.json` (provenance `seed` null; synthetic, not Part 2's or Part 4's).
   `labels.json` gains `expected_feet` and `follower_feet` (paths from the repo root) on every take of a set made
   with `--feet`, written before `expected` and `follower` so an older labels file only gains lines.
   **Nothing else moves.** Everything foot-related draws from random streams of its own, keyed by the take id
   (`<seed>/<take_id>/feet` and `/body`, `<seed>/<set>/<angle>/<light>/foot-plan`), so the 17-joint data of every
   base take, its label keys and its dropout copy are byte-identical with or without `--feet` (proved by a test
   and, for the committed seed 5 set, by `git diff --stat`: labels.json gains lines and loses none).
   **Dropout copies** keep the clean positions with the copy's per-joint `conf` (Part 2 writes no null), and a
   foot's three points take the `conf` of their ankle in the frames where it is below 0.3, 1.0 elsewhere: the same
   bursts that mask a far-side ankle mask its foot.
2. **Fault types, additive.** Four types, each on a side (`left`, `right` or `both`) drawn from the cell's foot-plan
   stream, sized 15 to 25 degrees (rounded to 0.1, exact by construction) under the same cosine-ramped window as
   the body faults: `foot_turned_out` (`foot_rotation`, `more`: the toe-out grows), `foot_turned_in`
   (`foot_rotation`, `less`: the toe-out shrinks, the case "Turn your left foot out" answers), `ankle_rolled_in`
   (`ankle_inversion`, `more`: the foot plane rolled about its long axis through the ankle, the outer edge going
   down) and `ankle_rolled_out` (`ankle_inversion`, `less`: the opposite roll). The type ids are identifiers kept
   as they were (the take id seeds the foot's random stream, so renaming one would move every foot byte), and they
   read the old way round: `ankle_rolled_in` is the roll the analysis words "rolling out" and `ankle_rolled_out`
   the one it words "rolling in" (see Compromises). A label is matched by measure, side and direction, never by
   words. The foot labels carry `body_part` `feet`, as the faults the analysis writes do. The 17 joints of these
   takes are those of a correct take; the fault is in the feet only. `contracts/labels.schema.json` and
   `evaluate.LABEL_TYPE_TO_MEASURE` learn the four types.
   **The amended take grid.** The master spec's locked grid of 9 takes per cell (2 correct, 6 single fault, 1
   double fault) gains 4 foot-fault takes per cell, numbered 09 to 12 after the nine and written after every base
   take in `labels.json`; the nine keep their numbers, bytes and order.
   | Per set, angle and light cell | takes |
   |---|---|
   | correct (00, 01) | 2 |
   | single fault, one per body fault type (02 to 07) | 6 |
   | double fault (08) | 1 |
   | foot fault, one per foot type: out, in, rolled in, rolled out (09 to 12) | 4 |
   | **cell** | **13** |
   Twelve cells make **156 takes per seed** (108 base + 48 foot), 24 correct takes and 144 labelled faults (96 body
   + 48 foot); with `--dropout-variant` the 8 side and 45 degree cells add 104 copies (72 + 32), 260 takes. Each
   take has a `feet.json`, and each of the two expected sets one. Seeds 29 and 31 were scored without feet and
   regenerate without `--feet` (`make heldout-data` passes it from seed 37 on).
3. **Co-firing.** With the first definition (the roll against the shin) the planted feet co-fired: a knee caving in
   tilts the shin inward over a flat foot (`ankle_inversion` `more`), a leg swung out tilts it outward (`less`), and a
   foot turned out under a shin that travels straight forward reads as a roll `more`. The second definition does
   not read the shin, so none of these reaches it. A differential run on seed 5 (old fault types and correct takes,
   foot code on against off) lists every new fault they raise; each is resolved by an `explained_by` or
   `explained_by_opposite` entry (candidates: `ankle_inversion` by `foot_rotation` and by `knee_valgus`, same
   direction; by `foot_out` and `thigh_out`, opposite direction) or, if it is not a co-fire, by a threshold. The
   entries are decided on seed 5. `rules.json` carries none until then. Result with the second definition: see
   "Seed 5 result" below.
4. **Thresholds.** Starting values `foot_rotation` 12 degrees, `ankle_inversion` 15 degrees; the sweep of
   `calibration.md` on the seed 5 good-light slices, precision first with 0 faults on correct takes, then recall.
   **Go/no-go per measure, decided on seed 5 before the freeze:** a foot measure ships in detection only if, in good
   light at front, 45 and side, it raises 0 faults on correct takes and no fault on the old fault types after step 3,
   and reaches recall 0.75 on its own fault types with precision 0.85. A measure that fails stays computed and
   reported in `diagnostics.feet` but has no rules entry and no fault type in the grid. The deliverable then
   shrinks, or if neither passes there is no freeze and seed 37 stays unused.
   **The tool.** `python -m part5.calibrate --feet [--write] [--workers N] [--radius N]` sweeps the two
   `threshold_deg` keys one at a time (the plateau middle of the best objective, as for every key) on the good-light
   takes of seed 5, each run through `pipeline.run` with its own `expected_feet` and `follower_feet`; the objective
   counts only the measure being swept (its faults against its labels), a fault on a take labelled with something
   else is listed and counts in precision, and the default sweep leaves the 48 foot takes out because it cannot see
   them. It then prints the go/no-go per measure at the chosen value, on the good-light slices at every angle:
   precision 0.85, recall 0.75, 0 faults on correct takes, both directions found. `--write` writes the chosen value
   of every measure that is a GO into `part5/rules.json` and nothing for a NO-GO (whose rules entry is then removed
   by hand). It reads seed 5 only.
   **Seed 5 result (the go/no-go, decided before the freeze).** Two runs of the tool, both on seed 5 only:
   - *Attempt A, `ankle_inversion` against the shin* (`progress/calibrate-feet-seed5-attempt-a.log`): `foot_rotation`
     GO at 14 degrees; `ankle_inversion` NO-GO. At thresholds 3 to 5 it raised faults on correct takes (1 to 5 at
     front, 5 to 6 at 45, 4 to 6 at side) with precision 0.07 to 0.12; at 6 to 13 it still raised them at 45 and side
     (1 to 4) with precision under 0.85 at every angle; no threshold gave precision 0.85, recall 0.75 and no fault on
     a correct take together. The chosen 25 had recall 0.00 at front and side (0.25 at 45), and `more` was never found
     at good light. At low light it also co-fired on `knee_caving` takes.
   - *Attempt B, `ankle_inversion` the roll of the foot plane against world up* (`progress/calibrate-feet-seed5-attempt-b.log`,
     run with `--write`): both measures GO. Chosen values `foot_rotation` 14 (plateau 12..15) and `ankle_inversion` 14
     (plateau 13..14, grid 9..21), written to `part5/rules.json`. The objective on `ankle_inversion` falls off a cliff
     above the plateau (front recall 0.25 at 15 and 0.00 at 16, the planted faults being 15 to 25 degrees under a
     ramped window), so the value 14 sits one degree under the smallest planted fault; seed 37 is a fresh draw.
   | Good light, at the chosen value | tp | fp | fn | precision | recall | faults on correct takes | directions found |
   |---|---|---|---|---|---|---|---|
   | `foot_rotation` front | 4 | 0 | 0 | 1.00 | 1.00 | 0 | more, less |
   | `foot_rotation` 45 | 4 | 0 | 0 | 1.00 | 1.00 | 0 | more, less |
   | `foot_rotation` side | 3 | 0 | 1 | 1.00 | 0.75 | 0 | more, less |
   | `ankle_inversion` front | 3 | 0 | 1 | 1.00 | 0.75 | 0 | more, less |
   | `ankle_inversion` 45 | 4 | 0 | 0 | 1.00 | 1.00 | 0 | more, less |
   | `ankle_inversion` side | 3 | 0 | 1 | 1.00 | 0.75 | 0 | more, less |
   No foot fault was raised at good light on a take labelled with something else, so the step 3 differential needs no
   `explained_by` or `explained_by_opposite` entry for either measure and `rules.json` carries none. Low light is
   reported, not gated. `ankle_inversion` raises 8 faults there that no label asks for (45: 3, front: 4, side: 1), one
   of them on a correct take (front); the 7 on other takes are all `less`, 6 of them on a take whose labelled fault has
   no foot link (arms, elbows, knees) or is on the other side, and one (`foot_turned_in` on both feet, right `less`) is
   the pairing the candidate entry `ankle_inversion` by `foot_rotation` would remove. One instance at low light is
   not the support the step asks for, so no entry is added. `foot_rotation` raises 16 there (45: 5, side: 11, one of
   them on a correct take at side), as in attempt A. Both lists are in the logs.
   - *Attempt C, a re-run without `--write`* (`progress/calibrate-feet-seed5-attempt-c.log`), after the pre-freeze
     review's fixes (the ankle words, the side-file reader, the labels' body part): both measures are still GO, the
     chosen values still 14 and 14 with the same plateaus (12..15 and 13..14), and every slice row and low-light list
     is the same as in attempt B. Only the sweep grid moved (8..20), because it is centred on the current value.
   **The seed 5 `good/1` score slice misses its target.** `score_report.TARGETS` asks single-fault good-light takes
   for a B or C. With the 48 foot-fault takes in the set, 3 of the 60 score A because their one fault is a foot fault
   no measure found: `exercise_front_good_12_ankle_rolled_out-both`, `dance_side_good_10_foot_turned_in-right` and
   `dance_side_good_11_ankle_rolled_in-right`, the 3 missed faults of the table above. `python -m part5.score_report
   --set fixtures/input/followers` therefore prints `good/1` as fail, while `good/0` (all A) and `good/2` pass. The
   target is not changed and no foot take is dropped; `tests/test_score_report.py` pins the cause (every good/1 take
   outside B or C has a labelled fault no prediction matches). The same kind of miss is expected on seed 37: a foot
   fault no measure finds leaves its take at A. The score slices are reported, not gated.
   The foot measures were planted by `scripts/make_dummy_followers.py --feet` as rolls and turns of a rigid foot
   (ASM-013), which `ankle_inversion` reads directly: the result shows the measure is clean and separable on those
   takes, not how it behaves on Part 2's estimated feet.
5. **Freeze and one attempt.** One commit freezes `rules.json`, the generator and the code; `docs/thresholds.md`
   gets attempt 3 (hash, rationale, `Approach family: a new measure, foot keypoints`). Adding the two threshold
   keys moves `detection_sha256`, so `make check-5` exits 2 at its freeze check until that attempt is recorded; the
   numbers of the seed 31 takes, which carry no feet, are identical with the foot code in place. Then `make heldout-data
   SEED=37` once and `make check-5` once. Green is reported "no seed left to confirm". Red is published and the
   run ends DEGRADED. Seed 37 is retired either way and never used to tune.
6. **Not gated.** Part 3's kit and Part 2's stock takes are reported with the foot measures where those clips
   carry foot points; low light and dropout slices are reported as for every measure. The stock pairs have real
   feet: Part 2's published `pose3d.json` files (moalborati/simon-part-2-images-to-3d at e8ac336, SAM 3D Body, gpu
   backend), copied byte for byte to `fixtures/input/eval/real/<clip>/feet.json` for Pexels 5034562 (the example)
   and 5034577 and 8837221 (the followers), each with a sha256 note in its `SOURCE.md`. `make report-real` hands them
   to `pipeline.run` as `expected_feet` and `follower_feet` (through `score_report.feet_kwargs`, the way `make check-5`
   does it), and the take then carries
   `diagnostics.feet`. Nobody has labelled their feet by eye, so a foot fault found on them is listed as unlabelled,
   like any fault no label asks for.

## Acceptance Criteria
Geometry (`tests/test_foot_geometry.py`):
- AC-FOOT-01: a foot along the pelvis's forward reads 0 on both sides.
- AC-FOOT-02: a foot turned out reads positive and turned in negative, on both sides: a 30 degree toe-out reads 30
  and a 20 degree toe-in reads -20, from vectors worked out by hand.
- AC-FOOT-03: the mirrored pose (x negated, sides swapped) reads the same on the other side.
- AC-FOOT-04: a pelvis rotated 40 degrees with a foot 15 degrees more out reads 15; a lifted heel changes nothing.
- AC-FOOT-05: NaN for a zero, vertical or steeply pitched foot, a foot at or past 90 degrees, coincident or vertical
  hips, collinear toes (cross product 0 and sine under 0.1), a foot pitched until under a quarter of world up lies
  across its long axis, world up on the sole's side of the foot plane (swapped toes, a foot rolled past 90 degrees)
  and any NaN input; a series is measured per frame; one point or many; an unknown side is a `ValueError`; the
  guard values are 0.25, 0.25 and 0.1.
- AC-FOOT-06: `ankle_inversion` reads 0 for a flat foot, +15 for a sole rolled 15 degrees toward the midline (the outer
  edge down), -10 for 10 the other way, on both sides, and a foot mirrored in x reads the same on the other side.
- AC-FOOT-07: the foot's heading, its pitch (toes up or a heel raised), a turn of the whole pose about the vertical
  and anything the knee and ankle do (forward travel, caving in, a leg swung out) do not change it.
- AC-FOOT-08: the foot measures are a separate registry: not in `MEASURES` or `compute()`.

Wiring (`tests/test_feet.py` for AC-FOOT-09 to 11, `tests/test_feet_faults.py` for AC-FOOT-12 to 18 unless named):
- AC-FOOT-09 (the file): a Part 2 `pose3d.json` loads per person into the four series, equal to the hand-computed
  values of `tests/fixtures/feet/`; a point missing, null, non-finite or under `FOOT_MIN_CONF` (including a hip) makes
  every measure that reads it NaN in that frame, and `conf` exactly 0.5 is seen; the knee and ankle are not read, so a
  bad one is no error and changes nothing; unknown names are ignored and `t0_pts_ms` is the time origin; `mirrored` swaps the left and right series; a measure is usable when a
  number in 80% of the clip's frames; a file without `extra_joints` loads with no usable measure; a file not in this
  shape, with a `people` entry that is not an object, with a text coordinate or `conf`, or unreadable is an `InputError`
  that names the file and, for a point, the frame, person and field.
- AC-FOOT-10 (time and person): a clip frame takes the nearest side frame within half the side file's median step over
  all its frames (at least 0.008 s) and is NaN otherwise, for faster and slower side files, more clip frames than side frames, and a person
  absent from some frames; no clip frame matched is an `InputError` giving both time ranges; a person id absent from
  every frame is an `InputError` listing the ids present, text ids included.
- AC-FOOT-11 (hidden and unchanged): a pair given no feet file is analysed byte for byte as before apart from
  `schema_version` (a golden rebuilds equal modulo the version) and has no `diagnostics.feet`; one file only, a file
  with no `extra_joints`, or a measure under 80% hides the measure with the reason in `diagnostics.feet` and no error;
  the pair is compared on the intersection; a hidden stretch gives no fault; a take compared rep by rep hides all four
  with the reason `rep mode` and reports the same faults as without; a take that cannot be aligned says so; a foot
  measure with no `rules.json` entry raises nothing.
- AC-FOOT-12 (rotation fault): follower and example both with feet, the follower's left foot turned out 20 degrees
  over the middle of the clip: one fault, `foot_rotation`, side `left`, direction `more`, joint `left_ankle`, body
  part `feet`, the cue "Turn your left foot in"; turned in: `less` and "Turn your left foot out"; both feet: merged to
  side `both` with joint `ankle`. A foot fault leaves the body faults of the same take unchanged. A turned foot
  raises no `ankle_inversion` fault (the measure does not read the shin; Why This Is Wrong, 5).
- AC-FOOT-13 (ankle fault): the follower's foot rolled 25 degrees over the middle: one `ankle_inversion` fault,
  `more`, "Keep your left ankle straight", words "left ankle rolling out", `lateral` `left`; rolled the other way:
  `less`, "Stop your left ankle rolling in", words "left ankle rolling in", `lateral` `right`.
- AC-FOOT-14 (words and cues): every measure, direction and side has a cue of 1 to 6 words, capitalised, no dash;
  opposite directions differ; a sided cue names its side; no cue names a heel, toes or a twist; "ankle" appears
  only in `ankle_inversion` cues. This amends AC-CUE-03, which said no cue names the ankle. `words.describe`,
  `describe_timed`, the live validators (`phrasing/template.py` NAMES, RULES, LANDMARKS) and the prompts cover the two
  measures: the template's own lines pass the word test and a line with the wrong direction, side, body part or a
  number is refused; the live ankle line reads "out" as `more` and "in" as `less` and may name no knee or thigh.
- AC-FOOT-15 (output): the two names validate against `contracts/analysis.schema.json` 1.6.0 with their joints and
  `diagnostics.feet`; 1.5.0 documents validate against it; `validate_analysis` rejects a foot fault with a wrong
  joint, body part, kind or side and a malformed `diagnostics.feet`; `part5 doctor --for part7` notes the feet;
  `part5 doctor` on a Part 2 `pose3d.json` exits 0 with a note, naming the foot points or "no foot points", and says
  it is not a clip; `part5 contract` lists the Part 2 foot points row checked against `e8ac336` and the schema
  `input-feet` (1.0.0, a file with no `format`, Part 2 or synthetic provenance); `make check-5-contract` classifies,
  validates and loads (through `part5.feet`) every `feet.json` under `fixtures/input/followers`,
  `fixtures/input/expected-feet` and `fixtures/input/eval/real`; CONTRACT.md and `docs/schemas.md` carry the input and
  the fields.
- AC-FOOT-16 (score): a take with no foot fault scores as before; a foot fault costs points like any other and its cue
  reaches the timeline and the insights.
- AC-FOOT-17 (command line and API): the four options reach the pipeline and a foot fault is written; the person
  options pick the person; a feet file that is unreadable, not this shape, lacks the person or matches no frame in time
  exits 1 with `part5 analyse: <file>: ...` and writes nothing; a file with no foot points exits 0; a person that is
  not a number is a usage error (exit 2); `analyse` passes the four through.
- AC-FOOT-18 (labels): the label types `foot_turned_out`, `foot_turned_in`, `ankle_rolled_in` and `ankle_rolled_out`
  map to `foot_rotation` and `ankle_inversion` (the direction is the label's own); `labels.schema.json` accepts them,
  body part `feet` and the `expected_feet` and `follower_feet` paths; `score_report.run_set` (so `scored_set`,
  `rows_of_set` and `calibrate_set`) and `score_report.analyse` pass a take's `expected_feet` and `follower_feet`
  to `pipeline.run` (`score_report.feet_kwargs(take, base)`), a take that names none runs as before. The callers that
  build their own analyses (`part5/check.py` `analyse_set`) pass `feet_kwargs(take, root)` the same way, and so does the
  real-take report (`part5/real.py` `_entry`, for the stock pairs, after naming the `feet.json` beside each clip when
  its label names none). There is no other way to pick a take's feet files and no probe of `pipeline.run`'s signature.
- AC-FOOT-19 (calibration, data lane): steps 1 to 4 above on seed 5 only, the go/no-go result recorded in
  `docs/thresholds.md` before the freeze commit; the freeze commit predates the generation of seed 37
  (`tests/test_heldout_protocol.py` already asserts the order).
- AC-FOOT-20 (old faults, data lane): on seed 5 at good light, front, 45 and side, the six old fault types and the
  correct takes report no foot fault: `foot_rotation` and `ankle_inversion` each raise nothing on a take labelled with
  something else and 0 faults on correct takes (`progress/calibrate-feet-seed5-attempt-b.log`, the `good/` rows of the
  slice tables, which have no "fault on a take labelled with something else" line; re-run unchanged in
  `progress/calibrate-feet-seed5-attempt-c.log`). At low light the extras are reported, not gated: `ankle_inversion`
  raises 8 faults no label asks for (45: 3, front: 4, side: 1), one of them on a correct take (front), and
  `foot_rotation` raises 16 (45: 5, side: 11), one of them on a correct take (side); both lists are in the same log.
- AC-FOOT-21 (gate, data lane): `make check-5` exits 0 on seed 37 with good light front, 45 and side at precision
  0.85 or more, recall 0.75 or more and 0 faults on correct takes; its result is in `attempts[]`.

## API / Interface Contract
- `part5.measures._foot_rotation(hip_l, hip_r, heel, big_toe, side)` and `_ankle_inversion(heel, big_toe,
  small_toe, side)`: arguments (F, 3) or (3,) float arrays, result (F,) degrees or a 0-d array, NaN as
  above, `ValueError` for a side other than `left` or `right`.
- `part5.measures.FOOT_MEASURES: dict[str, MeasureSpec]` (the four, joint `{side}_ankle`, body part `feet`),
  `ALL_SPECS` (body plus foot) and `compute_feet(points) -> dict[str, ndarray]`: `points` is `{name: (F, 3)}` for
  `left_hip`, `right_hip` and the six foot points (the loader reads no other joint); four (F,) series.
- `part5.feet`: `FOOT_POINTS`, `BODY_POINTS`, `FOOT_MIN_CONF`, `MIN_SEEN_SHARE`, `MIN_MATCH_S`,
  `load_side(label, path, person, clip_t) -> FootSide`, `pair_of(expected, follower) -> FootPair | None`,
  `file_summary(doc, source) -> {frames, people, with_points, mirrored}` (for `part5 doctor`). `FootSide` has `source`,
  `person`, `frames_matched`, `has_points`, `series` (by measure name, on the clip's frames), `usable`.
  `FootPair` has `compared`, `hidden_reason`, `diagnostics()` and `hidden(why)`.
- `part5.pipeline.run` and `analyse`: `expected_feet`, `follower_feet`, `expected_feet_person`, `follower_feet_person`.
- `part5.output`: `SCHEMA_VERSION` `1.6.0`; `validate_analysis` checks `diagnostics.feet`.

## Error Cases
| Condition | Behavior | Message | AC |
|---|---|---|---|
| The feet file cannot be read or is not JSON | `InputError`, exit 1, nothing written | `<file>: cannot read JSON (...)` | AC-FOOT-09, 17 |
| Not a Part 2 pose3d.json (no `frames`, a frame without numeric `t_ms` or a `people` list, a `people` entry that is not an object, `t0_pts_ms` or `mirrored` of the wrong type) | same | `<file>: not a Part 2 pose3d.json (...)`, `<file>: frames[i].t_ms must be a number, got ...`, `<file>: frames[i].people[j] must be an object, got int` | AC-FOOT-09 |
| A point is not an object, or a coordinate or `conf` is text | same | `<file>: frames[i].people[id N].extra_joints.<name>.x must be a number or null, got ...` | AC-FOOT-09 |
| The person id is in no frame | same | `<file>: person N is in no frame (ids present: [...])` | AC-FOOT-10 |
| No clip frame matches a frame of the file in time | same | `<file>: no frame of the <expected or follower> clip matches a frame of this file in time (file a to b s, clip c to d s)` | AC-FOOT-10 |
| A feet file for one clip only, or a file with no `extra_joints` | analysed; the foot measures are hidden; `diagnostics.feet` says so | none | AC-FOOT-11 |
| Every foot point under `FOOT_MIN_CONF` | the file counts as having points but no usable measure | none | AC-FOOT-09, 11 |
| Geometry cannot give a number | NaN for that frame | none | AC-FOOT-05 |
| The feet option's person is not a number | usage error, exit 2 | argparse | AC-FOOT-17 |

## Edge Cases
- Expected clip from Part 4 with no `--expected-feet`: foot measures hidden, no foot fault (AC-FOOT-11).
- Trainer's own Part 2 file given to `--expected-feet` and the follower's to `--follower-feet`: compared.
- A foot hidden in a burst (dropout, far side in a side view): NaN there, `coverage` drops, no fault from missing
  data, as for `knee_valgus` (AC-FOOT-11).
- A heel lifted (calf raise, step): the heading holds and so does the roll; `ankle_inversion` is NaN when the foot is
  pitched so steeply that under a quarter of world up lies across its long axis (AC-FOOT-05).
- Both feet turned out: merged to side `both` by the existing rule (AC-FOOT-12).
- A reps-mode comparison: the foot measures are hidden with the reason `rep mode` (kept small on purpose).
- A mirrored side file: left and right swapped (AC-FOOT-09).
- The clip is faster or slower than the side file: each clip frame takes the nearest side frame within the window.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | One analysis with feet | under 2 s on a 300-frame take (as the master spec) | AC-FOOT-11 |
| Security | Data protection | N/A: no new secret, network or storage; a feet file is read, never fetched | |
| Reliability | Determinism | byte-identical reruns, template phrasing | master AC-012 |
| Reliability | Missing data | NaN, never a guess | AC-FOOT-05, AC-FOOT-09 |
| Maintainability | Tests | every AC named in a test | all |
| Compatibility | Old inputs and outputs | every existing file loads; 1.5.0 documents validate | AC-FOOT-11, AC-FOOT-15 |
| Accessibility, Scalability | N/A: no UI, one more file of the same order as the pose3d.json already produced | | |

## Negative Requirements
- MUST NOT guess a foot point or a foot measure. Why: a rolled ankle invented from a lift's noise is a false fault.
- MUST NOT change what a pair without a feet file produces, apart from `schema_version`. Why: the gate
  (`make check-5`) and the held-out protocol (ADR-0003).
- MUST NOT tune any foot threshold or `explained_by` entry on seed 37 or any held-out number. Why: ADR-0003.
- MUST NOT import or copy code from Part 2 or Part 3. Why: black box; only their files are read.
- MUST NOT put foot measures in `MEASURES`, the alignment, the guard or the score's similarity term. Why: it would
  change every pair, including those without feet.
- MUST NOT mix the side file's foot points with the clip's joints in one measure. Why: two skeletons, two passes
  (Why This Is Wrong, 6).

## Compromises
### Planted synthetic feet
Short-term: the synthetic foot is a rigid template planted flat, with fault types made by yaw and roll. Long-term:
Part 2's real foot estimates on filmed takes. Migration path: the real-take report (`make report-real`) carries the
foot measures wherever a real Part 2 file with `extra_joints` is given. Trigger to revisit: the first filmed take with
known foot faults, or a real-take disagreement with seed 37 (ASM-013).
### One cue for both feet of one direction
Short-term: a `both` cue per direction. Long-term: per-foot nuance. Trigger: an operator ask.
### The ankle label ids read the old way round
Short-term: the label types `ankle_rolled_in` (`ankle_inversion` `more`) and `ankle_rolled_out` (`less`) keep their ids,
and the label `text` ("left ankle rolled in") keeps its wording, while the analysis now says "rolling out" for `more` and
"rolling in" for `less` (ADR-0015 Amendment 2). Why: the take id seeds the foot's random stream, so a new id would move
every foot byte of every set. Matching never reads the words. Long-term: rename the types in a schema 2.0 with a new
set. Trigger: the next regeneration of the tuning set for any other reason.
### Rep mode hides the feet
Short-term: a take compared rep by rep reports no foot fault. Long-term: per-rep foot series. Trigger: a real take of
a repeated movement with a known foot fault.
### The foot measures keep their own visibility rule (pre-freeze review R8)
Short-term: a foot measure is usable from the side file's own `conf` (`FOOT_MIN_CONF` 0.5, 80% of the clip's frames),
not from the clip's visibility check (ADR-0011). All three real Part 2 files at e8ac336 carry `conf` 1.0 on every foot
point, so on real data the rule hides nothing and a foot hidden behind the other leg is still measured. Long-term: Part
2's own per-point confidence, or the clip's visibility of the matching ankle. Trigger: the first real Part 2 file with
a foot `conf` below 1.0, or a real take whose far foot reads a fault the frame does not show.
### Low-light side dropout copies can hide `foot_rotation` (pre-freeze review R9)
Short-term: in low-light side-view dropout copies, the hips' `conf` hovers near 0.55 and sometimes drops under 0.5, so
`foot_rotation` is hidden for both feet in those frames while the body pipeline (its cutoff 0.3) still uses the hips.
Only reported slices are affected; the gated good-light slices carry no dropout copies. Long-term: one cutoff for the
hips in both pipelines. Trigger: a reported dropout slice whose foot recall falls with no foot fault missed in good
light.

## Non-Requirements (Explicitly NOT Building)
- Reading the foot from video or inventing foot points when a clip has none (Part 2's job).
- Drawing the feet in the replay viewer (Part 7); the fault highlights the ankle.
- Toe-off, heel-strike, foot pressure or arch measures; a trained model (rule maths only, README).
- A neutral-stance prior for an example that has no feet (open question 6, not decided here).
- Carrying the foot points in `simon.animation.v1` or through Part 3.

## Assumptions
- ASM-013: synthetic feet from a rigid planted template, written as Part 2 shaped side files, are a fair proxy for
  Part 2's estimated feet; limit, they are cleaner and share the generator's fault model
  (`docs/assumptions/ASM-013.yaml`).
- Part 2's `pose3d.json` is in the canonical frame and its foot points use the 17 joints' frame, units and `conf`
  semantics (stated in its acceptance, TICKET-043); `FOOT_MIN_CONF` is provisional until its real range is known
  (open question 4).

## Implied Requirements Discovered
- The live-phrasing validators key on the measure name (`phrasing/template.py` NAMES and RULES), so a new
  measure without entries would fail a live line: found by grepping every table keyed by measure.
- `labels.schema.json` enumerates fault types and `evaluate.LABEL_TYPE_TO_MEASURE` maps them, so a new fault type
  needs both.
- `tests/test_heldout_protocol.py` regenerates the held-out set on disk byte for byte with `gen.generate(seed, ...,
  dropout_variant=True)`; once seed 37 carries feet that call must pass the same `feet` option, and seed 31's bytes
  must still regenerate without it (AC-FOOT-11): found by reading the protocol tests. The test now takes the `feet`
  option from the committed labels (`follower_feet` on any take), compares each take's `feet.json` and the two expected
  sets' `feet.json` too, and a second test runs the same branch on the tuning set.
- A foot measure needs its own threshold: `detect` falls back to the default threshold for an unknown measure, which
  would make a measure with no `rules.json` entry fire at 10 degrees; it is skipped instead.
- A turned foot raised `ankle_inversion` under a forward-leaning shin: found when the first rotation tests also
  reported a roll. Gone with the second definition, which does not read the shin.
- The hips of the side file are part of `foot_rotation`: a hip below `FOOT_MIN_CONF` hides both feet in that frame.

## Open questions
1. **Closed (operator ruling 2026-10-31):** how Part 3 carries the six points. It does not; Part 5 reads Part 2's file.
2. **Closed:** the format Part 3 bumps to. None.
3. **Closed:** whether an interpolated frame interpolates the foot points. Not applicable; the side file is read as
   written.
4. **Part 2:** the range of a foot point's `conf` and whether the 0.3 outside-the-image mark applies to it, to
   confirm or replace `FOOT_MIN_CONF` 0.5.
5. **Part 2:** that the foot points are levelled by the same world-up as the 17 joints (the ground plane is x-z).
   `ankle_inversion` reads the vertical directly, so it depends on this more than any other measure here; a constant
   tilt cancels in follower minus example only if both files share it.
6. **Operator or Part 4:** what the example's foot is when no `--expected-feet` is given. Default in this spec: the
   foot measures are hidden for the pair. The trainer's own Part 2 file through `--expected-feet` answers it when it
   exists. Alternatives: Part 4 adds foot points to its expected clips; or Part 5 compares against a neutral stance
   prior (a different meaning of "differs", needs its own ADR).
7. **Data lane:** the `explained_by` entries, decided by the seed 5 differential (Calibration, step 3).

## Files (every new or changed source file; the write gate reads this table)
| File | Change | Ticket | Published |
|---|---|---|---|
| `docs/design/specs/foot-keypoints.md` | this spec | TICKET-040 | yes |
| `docs/design/adr/ADR-0015-foot-keypoints-and-foot-measures.md`, `docs/assumptions/ASM-013.yaml` | decision and assumption | TICKET-040 | yes |
| `docs/design/specs/foot-keypoints.md`, `docs/design/adr/ADR-0015-foot-keypoints-and-foot-measures.md`, `docs/design/README.md` | neutralised copies written by `make design-copies`, and their lines in the hand-written index (`tests/test_design_copies.py` fails without them) | TICKET-040 | yes |
| `part5/measures.py` | `_foot_rotation`, `_ankle_inversion`, guard constants, `FOOT_MEASURES`, `ALL_SPECS`, `compute_feet` | TICKET-040 | yes |
| `part5/feet.py` (new) | the side file: `FOOT_POINTS`, `FOOT_MIN_CONF`, `load_side`, `pair_of`, `file_summary` | TICKET-040 | yes |
| `part5/pipeline.py` | `run` and `analyse` take the feet options, load the sides, `_foot_series`, `diagnostics.feet` | TICKET-040 | yes |
| `part5/detect.py` | visit foot measures present in both dicts, skip one with no rules entry, `ALL_SPECS` | TICKET-040 | yes |
| `part5/words.py`, `part5/cues.py`, `part5/lateral.py`, `part5/phrasing/template.py`, `part5/phrasing/prompt.py`, `part5/phrasing/local_llm.py` | words, cues, lateral, NAMES, RULES, LANDMARKS, spec lookup | TICKET-040 | yes |
| `part5/output.py`, `part5/doctor.py`, `part5/contract.py`, `part5/cli.py` | `ALL_SPECS` vocabulary, 1.6.0, `diagnostics.feet`, notes, the table row, the four options | TICKET-040 | yes |
| `part5/evaluate.py` | label types to measures | TICKET-040 | yes |
| `part5/score_report.py` | `feet_kwargs`; `run_set` and `analyse` pass a take's foot side files to `run` | TICKET-040 | yes |
| `part5/check.py`, `part5/real.py`, `part5/calibrate.py` | one way to pick a take's foot files (`score_report.feet_kwargs`); the `pipeline.run` signature probe, `analyse_with_feet` and the second `FEET_KEYS` are gone | TICKET-040 | yes |
| `contracts/input-feet.schema.json` | the feet side file schema (1.0.0); `part5/contract.py` lists it, classifies and loads `feet.json` files | TICKET-040 | yes |
| `part5/rules.json` | `foot_rotation` and `ankle_inversion` thresholds (starting values); `explained_by` entries are the data lane's | TICKET-040 | yes |
| `contracts/analysis.schema.json`, `contracts/labels.schema.json` | measure enum, `feet`, `diagnostics.feet`, fault types, the feet paths | TICKET-040 | yes |
| `tests/test_feet.py`, `tests/test_feet_faults.py`, `tests/fixtures/feet/*`, `tests/test_foot_geometry.py` | AC-FOOT-01 to AC-FOOT-18 and the hand-made side files | TICKET-040 | yes |
| `tests/test_cues.py`, `test_words.py`, `test_output.py`, `test_doctor.py` and the tests that read `schema_version` | amended cases (AC-CUE-03 narrowed, 1.6.0) | TICKET-040 | yes |
| `docs/schemas.md`, `CONTRACT.md` | the input, the fields, the table row | TICKET-040 | yes |
| `scripts/make_dummy_followers.py`, `Makefile` | `--feet`, the foot fault types, a separate stream; `heldout-data` passes `--feet` | TICKET-040 | yes (upstream-owned, data lane) |
| `fixtures/input/expected-feet/*`, `fixtures/input/followers/*` (seed 5 regenerated), `fixtures/input/heldout/*` (seed 37), `fixtures/output/*` (golden version) | derived example side files, takes with side files, goldens | TICKET-040 | yes (data lane) |
| `docs/thresholds.md`, `tests/test_heldout_protocol.py` | attempt 3, the regeneration call gains the `feet` option | TICKET-040 | yes (data lane) |

## Delivery Verification Plan
- feet-core lane: `uv run pytest -q tests/test_foot_geometry.py tests/test_feet.py tests/test_feet_faults.py` 0; `make
  test` 0 apart from the tests that read the freeze hash and the goldens (`make output-examples` rebuilds the goldens for
  the version); `make check-5-contract` 0; `make report-real` 0; the em-dash gate on the tree; the seed 31 numbers
  unchanged with the foot code in place.
- data lane and coordinator: the seed 5 differential of Calibration step 3 recorded; the freeze commit; `make
  heldout-data SEED=37`, then `make check-5` once, result published in `docs/thresholds.md`; staging `up` and `verify`
  0; one consolidated review.

### Device/Platform Strategy
| Platform | Tool | Viewport | Assigned To |
|---|---|---|---|
| Desktop Chromium | Playwright 1.61.1 (`staging/verify.mjs`), only to show a foot fault's text and cue unchanged in the existing UI | 1440 | viewer lane |

### Data
Synthetic takes only (seed 5, then seed 37 once); a real Part 2 `pose3d.json` with foot points when it exists. No
UI-created data.

### Ratchet Initialization Plan
Not applicable: no new milestone; the existing floors in `progress/ratchets.json` must not drop.

## Dissent Review
Reviewed by: TICKET-040 feet-core lane (implementer, self-review). Independent review: pending, at the consolidated review.
### Concern 1: the feature could be inert on real use
Challenge: with Part 4's expected clips carrying no feet, no foot fault ever appears on a real take unless the trainer's
own Part 2 file is supplied.
Impact if right: weeks of work with no visible effect. Mitigation: `--expected-feet` takes the trainer's file; the
result says plainly when the feet were hidden and why (`diagnostics.feet`); open question 6 stays open for the operator
and Part 4. Resolution: ADDRESSED_IN_SPEC.
### Concern 2: the sign and words of the ankle measure are easy to get backwards
Challenge: inversion and eversion are used in opposite ways by coaches and clinicians. Impact if right: a cue that
tells a follower the wrong way. Mitigation: the measure is defined geometrically and its sign is tested in both
sides (AC-FOOT-06, AC-FOOT-13); the words name the direction the ankle rolls ("rolling out" for the foot on its outer
edge, "rolling in" for the inner edge) and the pinned lines are tested in the plain, timed and live forms. This
concern came true once: the first words were written for the shin version and pointed the wrong way after the measure
changed; the pre-freeze review found it and ADR-0015 Amendment 2 fixed it. Resolution: ADDRESSED_IN_SPEC.
### Concern 3: seed 37 is spent on a feature the gate does not need
Challenge: the run is green on seeds 29 and 31. Impact if right: a red attempt 3 turns a delivered result into
DEGRADED. Mitigation: the go/no-go rule on seed 5 before the freeze, and the freeze may not happen. Resolution:
ACCEPTED_RISK (the stakeholder-proxy ruled on 2026-10-31 that new detection keys need seed 37).
### Concern 4: a second input is one more thing to get wrong
Challenge: a follower must give two files per clip, and the wrong one lines up with the wrong person. Impact if right:
a plausible foot fault that belongs to someone else. Mitigation: the person id is explicit, a file matching no frame in
time is an error, and the measures never mix the two skeletons. Resolution: ACCEPTED_RISK.

### Pre-Mortem: it is six months on and this feature was a disaster. Why?
1. Part 2's toes are too noisy and the measure fires on nothing real. Likelihood: M, Impact: M, Mitigation:
   confidence gate, thresholds from the noise population, real takes reported, go/no-go.
2. The planted synthetic feet taught the thresholds a coupling real feet do not have. Likelihood: M, Impact: M,
   Mitigation: the co-firing entries are physical, not fitted; the report on real takes shows the disagreement.
3. Part 2 changed the shape of `extra_joints`. Likelihood: L, Impact: L, Mitigation: all names live in
   `part5/feet.py`, and the contract table row records the commit the shape was checked against.

## Requirements Traceability
| Requirement Source | Spec AC | Test | Status |
|---|---|---|---|
| TICKET-040: `foot_rotation`, heel to big toe against the hip line in the ground plane | AC-FOOT-01 to 05 | `tests/test_foot_geometry.py` | passing |
| TICKET-040: `ankle_inversion` (heel, ankle, toe) | AC-FOOT-05 to 07 | `tests/test_foot_geometry.py` | passing |
| Operator ruling: feet from Part 2's pose3d.json as a side input | AC-FOOT-09, 10, 17 | `tests/test_feet.py`, `tests/test_feet_faults.py` | passing |
| TICKET-040: hidden when the foot points are absent | AC-FOOT-11 | `tests/test_feet.py` | passing |
| TICKET-040: detection and cues | AC-FOOT-12 to 14 | `tests/test_feet_faults.py`, `tests/test_cues.py` | passing |
| TICKET-040: schema minor bump, ADR | AC-FOOT-15 | `tests/test_feet_faults.py`, `tests/test_contract_cli.py` | passing |
| TICKET-040: thresholds on seed 5 only, held-out unchanged or better | AC-FOOT-19 to 21 | `make check-5`, `tests/test_heldout_protocol.py` | pending (data lane) |

## Test Scenarios (maps 1:1 to acceptance criteria)
AC-FOOT-01 to AC-FOOT-08 to the named functions in `tests/test_foot_geometry.py`; AC-FOOT-09 to AC-FOOT-11 to
`tests/test_feet.py`; AC-FOOT-12 to AC-FOOT-18 to `tests/test_feet_faults.py` and the amended tests named in Files;
AC-FOOT-19 to AC-FOOT-21 to the data lane and `make check-5`.

## Deviations from PRD
| PRD item | Deviation | Reason |
|---|---|---|
| ADR-0014: `ankle_inversion` is "the heel, ankle and toe midpoint angle" | the roll of the foot plane about its long axis against world up | the triangle is rigid and cannot move with an inversion (Why This Is Wrong, 2); the roll against the shin was NO-GO on seed 5 (Why This Is Wrong, 5) |
| ADR-0014 / AC-CUE-03: no cue names the ankle | "ankle" allowed in `ankle_inversion` cues only | the measure now exists |
| TICKET-040: Part 3 carries the points through `--view part5` | Part 5 reads Part 2's pose3d.json as an optional side input | Part 2's contract says Part 3 does not carry `extra_joints`; operator ruling 2026-10-31 |
