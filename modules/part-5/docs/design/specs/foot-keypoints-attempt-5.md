# Spec record: foot keypoints, attempt 5 (a foot that is not steady is not measured)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted (attempt 5 scored green on seed 71 and confirmed on seed 73, both frozen at 4c55af0)
Date: 2026-11-01
Request Type: feature-mod
Risk Level: medium
Master spec: `foot-keypoints.md`. This file is that spec's "Attempt 5" record, moved out at TICKET-051 so the master stays
under 800 lines; the acceptance criteria (AC-FOOT-22 to AC-FOOT-27), the compromises, the files table and the delivery
plan stay in the master. ADRs: ADR-0015 (Amendment 4), ADR-0017 (the second held-out series), ADR-0003. Tickets:
TICKET-040 (the family), TICKET-051 (the split and the known limit under "Costs and limits, stated").

## Attempt 5: a foot that is not steady is not measured (ADR-0015 Amendment 4)
Attempts 3 and 4 were both red on one take type, and this section is the family that answers it. It changes how a foot
measure is made visible, not how it is defined, and not a threshold or a floor alone.

**The ruling** (stakeholder-proxy, 2026-11-01T03:15Z, confidence high), verbatim: "attempt 5 is TICKET-040's foot-measure
family per ADR-0017's red-on-67 row. Its core is a change to foot-measure definition or visibility (for example a
view-aware far-foot rule), never a threshold or foot-floor nudge alone. It is tuned on seed 5 only with ADR-0015's go/no-go,
the retimed bar and a seed 5 count of far-foot labels found, reviewed before the freeze, frozen by 2026-11-02T06:00Z and
scored once on seed 71."

**The failure.** `ankle_inversion` reported the far foot of a correct take filmed from the side as rolling out: 21.5 degrees
on `dance_side_good_01_correct` (seed 37), 22.4 on `exercise_side_good_00_correct` (seed 67); each take scored B where a
correct good-light take must be an A. In a side view the far foot is occluded, its heel and toe points are noisy, and the
roll reads the noise (the toe pair is 7 cm across, so a centimetre of vertical error is 8 degrees). In the generator the
camera noise of the far side is multiplied by `1 + yaw / 90` on every axis (ASM-013). On the 12 seed 5 correct good-light
takes the standard deviation of the `ankle_inversion` series is 4.6 to 7.5 degrees at the front, 4.3 to 6.9 for the near
foot at 45, 5.8 to 10.9 for the near foot at the side, and 8.9 to 13.3 (45) and 14.4 to 28.1 (side) for the far foot.
Persistence cannot remove noise that is smooth over a few frames; the threshold cannot be raised past the planted faults
(15 to 25 degrees; the sweep falls off a cliff above 15).

### What the files carry, and the candidates
| # | Candidate | Evidence | Verdict |
|---|---|---|---|
| 1 | A view-aware rule from the camera axis (the hip or shoulder line against the line of sight) or from the foot points' `conf` | The clip is in the subject's frame (hip line along x, forward along z) in every take, and so is Part 2's canonical frame: the hip line of all three real files lies exactly along x in every frame (yaw 0.0 degrees, the side-view example included), so the camera is in neither; Part 2's `provenance` names the source of the focal length and no direction; the foot `conf` of all three real files is 1.0 and Part 2 writes a joint's `conf` as 1.0, or 0.3 outside the image (ADR-0011); the seed 5 base takes carry no `conf`, and the dropout copies that do (a far-side loss of `CONF_FAR_LOSS` 0.25 at 90 degrees) are reported slices the failing takes are not in | Not buildable from the files. The camera is unknown; only the foot says it is not seen |
| 1b | The far foot is the one that jitters more than the other | Right over left jitter of `ankle_inversion` at good light: front 0.72 to 1.43, 45 0.98 to 2.56, side 1.28 to 2.86 (26 takes each). The ranges overlap, and two bad feet (low light) show no ratio | Rejected |
| 2a | The foot's shape: the change of the three heel and toe distances over the clip | Toe-pair distance spread (standard deviation over median) at good light: left foot 0.16 (front), 0.10 (45), 0.17 (side); right foot 0.16, 0.31, 0.31. It depends on how the toe pair lies against the line of sight (a ratio of 3 at 45 and 2 at the side) and is blind to the vertical error that makes the roll | Rejected |
| 2b | The measure's own frame-to-frame jitter | The table below | Chosen |
| 3 | The roll against the shin | ADR-0015 Amendment 1 (attempt A: NO-GO on seed 5). The far-foot error is in the toes, which the shin does not carry | Not rebuilt |
| 4 | A threshold or a floor alone | The ruling excludes it | Excluded |

### The rule
`feet.jitter(values)` is the median of the absolute change between consecutive frames of the measure's series (degrees a
frame), over the pairs where both are numbers; NaN with fewer than `JITTER_MIN_PAIRS` (5) such pairs. A median step reads
the noise and not the fault: noise that is smooth over a few frames still changes almost independently from one frame to the
next, while a fault grows over many frames, so its steps are a minority and a squat's or a ramp's rise moves few of them.
`feet.jitter_limits(rules)` gives `{foot measure: limit}` from the `max_jitter_deg` of each foot measure's entry in
`rules.json` (the side-less name, both sides; no key, no limit). `feet.load_side(..., limits)` computes the jitter of each
limited series on the side file's own frames from the first to the last one the clip takes, so a clip sampled slower than
the file reads the file's consecutive frames and a file longer than the clip reads the clip's stretch of it; a measure
above its limit (the limit itself is kept) is left out of `usable`, its series is unchanged, and `FootSide.unsteady` names
it. A series too short to judge is kept: the 80% rule is the one for missing data. `pipeline.run` passes the limits of the
rules it detects with, for both clips, so a trainer's own file that jitters is no reference either. The pair is formed as
before on `usable` (`compared`, `hidden_reason`; when nothing is left the reason names the worst measure, its jitter and
the limit, and, when the other measures were not seen in 80% of the frames, says so too: ", and the rest are not seen in
80% of them"; TICKET-051). A body measure has no such key and is never gated; a profile relaxes thresholds and keeps the limit
(it is a property of the points, not a tolerance).

`max_jitter_deg` is **4 degrees a frame on `foot_rotation` and `ankle_inversion`**, the thresholds stay 14 and 14.

### The jitter of the feet on seed 5 (26 takes per row, every take of the cell: the planted foot is rigid whatever the fault)
Degrees a frame, minimum / median / maximum. "Near" is a foot the camera sees: both feet at the front, the left foot at 45
and at the side; the generator's far side is the right.

| Good light | `ankle_inversion` | `foot_rotation` |
|---|---|---|
| front, left / right | 1.94 / 2.58 / 3.58 and 1.80 / 2.63 / 3.10 | 1.38 / 1.92 / 2.42 and 1.55 / 1.89 / 2.56 |
| 45, left (near) | 1.98 / 2.61 / 3.53 | 1.81 / 2.36 / 3.04 |
| 45, right (far) | 2.63 / 3.96 / 5.99 | 1.94 / 2.79 / 4.03 |
| side, left (near) | 1.92 / 2.91 / 3.71 | 1.72 / 2.16 / 2.65 |
| side, right (far) | 3.38 / 5.53 / 8.35 | 3.39 / 3.88 / 4.91 |

At low light (noise 2.3 times as large) every row sits above 3.2 and the medians are 5.8 to 8.5 for `ankle_inversion` and 4.5
to 8.8 for `foot_rotation`. The three real Part 2 files (10 fps) jitter 0.34 to 0.56 (`ankle_inversion`) and 0.46 to 0.89
(`foot_rotation`): the rule does nothing on them.

### Why 4, and why on both measures
The selection rule, written before the sweep was read: the lowest value on a 0.5 grid that costs seed 5 nothing at good light
(every slice's precision, recall and faults on correct takes, every foot label found, every correct take an A). It is not read
off the held-out seeds or the failure, and a recall or precision sweep cannot choose it, because seed 5 has no false fault from
a foot at good light for the gate to remove (the thresholds were chosen against exactly that), so every limit that costs
nothing ties and the objective is flat on that side. The sweep of the limit (`ankle_inversion` alone, then `foot_rotation`
on top of `ankle_inversion` 4):

| ankle limit, rotation none | foot labels found, good | good/front | good/45 | good/side | low/front R | low/45 R | low/side R |
|---|---:|---|---|---|---:|---:|---:|
| none (attempt 4) | 22 of 24 | 0.96 / 0.96 / 0 | 1.00 / 1.00 / 0 | 0.88 / 0.96 / 0 | 0.96 | 0.92 | 0.67 |
| 3.0 | 18 | 0.96 / 0.92 / 0 | 1.00 / 0.96 / 0 | 0.88 / 0.88 / 0 | 0.83 | 0.83 | 0.62 |
| 3.5 | 21 | 0.96 / 0.96 / 0 | 1.00 / 1.00 / 0 | 0.88 / 0.92 / 0 | 0.83 | 0.83 | 0.62 |
| 3.8, **4.0**, 4.5 | 22 | as none | as none | as none | 0.83 | 0.83 | 0.62 |
| 5.0 | 22 | as none | as none | as none | 0.88 | 0.83 | 0.62 |
| 6.0 | 22 | as none | as none | as none | 0.96 | 0.88 | 0.62 |

| rotation limit, ankle 4.0 | foot labels found, good | good/side R | low/front R | low/45 R | low/side R |
|---|---:|---:|---:|---:|---:|
| none | 22 | 0.96 | 0.83 | 0.83 | 0.62 |
| 2.5 / 3.0 / 3.5 | 20 / 21 / 21 | 0.92 | 0.67 / 0.67 / 0.71 | 0.67 | 0.54 |
| **4.0** / 4.5 / 5.0 | 22 | 0.96 | 0.71 / 0.71 / 0.79 | 0.67 / 0.71 / 0.71 | 0.54 / 0.54 / 0.58 |

4 is the lowest that costs nothing for both measures, it is above the jitter of every foot the camera sees at good light
(3.71 for `ankle_inversion`, 3.04 for `foot_rotation`: none of the 104 near feet is hidden) and below the median of the far
foot at the side (5.53 and 3.88). The thresholds were re-swept first (`progress/calibrate-feet-seed5-attempt5.log`): both
tie at the best objective on a plateau of 11 to 15 and 14 is strictly inside it, so the 00:05Z rule keeps 14 and 14 (the plain
rule would say 13; `calibrate --feet` now follows the re-sweep rule and prints the plain choice beside it). The default sweep
of the other 17 keys moves none of them (`progress/calibrate-seed5-attempt5.log`).

`foot_rotation` is gated by the same rule and the same cost test, not because it failed. It has the same far-foot noise
(3.9 degrees a frame at the side against 2.2 for the near foot), and its first false fault at a lowered threshold comes 4
degrees under the shipped 14 where `ankle_inversion`'s comes 2 under (below): a wider margin, but one a held-out seed's
far feet (about as many as seed 5 has) can still cross. The gate costs seed 5 nothing at good light, and ADR-0017 does not
count a later change of this family's values as a new family, so a `foot_rotation` false fault on seed 71 could not be
answered by another attempt. The cost is a lower reported recall at low light, which is stated below.

**What the gate does to a lower threshold** (faults no label asks for at good light on seed 5, the threshold lowered to
find where the far foot first fires; every one is a fault on a take labelled with something else or a correct take):

| threshold | `ankle_inversion` without / with the gate | `foot_rotation` without / with |
|---|---|---|
| 14 (shipped) | 0 / 0 | 0 / 0 |
| 12 | 1 / 0 (far foot, jitter 5.0) | 0 / 0 |
| 10 | 5 / 2 (near the limit, 3.0 and 3.6) | 3 / 1 (far foot, jitter 3.7) |
| 8 | 9 / 5 | 9 / 7 |

### Seed 5 record (all measures; `progress/calibrate-feet-seed5-attempt5.log`, `progress/calibrate-seed5-attempt5.log`)
Good light, precision / recall / faults on correct takes (all faults, body and foot), before (attempt 4) and after:

| slice | before | after |
|---|---|---|
| good/front | 0.96 / 0.96 / 0 | 0.96 / 0.96 / 0 |
| good/45 | 1.00 / 1.00 / 0 | 1.00 / 1.00 / 0 |
| good/side | 0.88 / 0.96 / 0 | 0.88 / 0.96 / 0 |
| low/front (reported) | 0.66 / 0.96 / 1 | 0.71 / 0.71 / 0 |
| low/45 (reported) | 0.42 / 0.92 / 3 | 0.41 / 0.67 / 3 |
| low/side (reported) | 0.18 / 0.67 / 14 | 0.17 / 0.54 / 13 |

Every good-light fault list is as it was except two (below). The 32 low-light takes whose faults changed lose 36 foot faults
and gain none: 15 of them were labelled faults found and 21 were faults no label asks for. Correct good-light takes: A 12 of
12. Score slices (`python -m part5.score_report`, reported): good/0 A 12, good/1 A 6, B 46, C 8 and good/2 D 5, F 1, as before.
At low light (no target) the slices move: low/0 A 5, B 3, C 2, D 1, F 1 becomes A 6, B 2, C 2, D 1, F 1, and low/1 A 4, B 10,
C 18, D 8, F 20 becomes A 13, B 13, C 14, D 8, F 12. The nine more A among the single-fault takes are exactly nine
low-light foot-fault takes (B or C before) whose one fault the gate now leaves unread; that is the cost, in the score's own
terms.

ADR-0015's per-measure go/no-go at the shipped values (good light, tp / fp / fn, precision / recall, faults on correct takes,
directions found), identical before and after at good light:

| measure | front | 45 | side | directions |
|---|---|---|---|---|
| `foot_rotation` | 4 / 0 / 0, 1.00 / 1.00, 0 | 4 / 0 / 0, 1.00 / 1.00, 0 | 4 / 0 / 0, 1.00 / 1.00, 0 | more, less |
| `ankle_inversion` | 3 / 0 / 1, 1.00 / 0.75, 0 | 4 / 0 / 0, 1.00 / 1.00, 0 | 3 / 0 / 1, 1.00 / 0.75, 0 | more, less |
Both measures are GO. At low light (reported) the gate hides `ankle_inversion` on 155 of the 156 feet of the 78 takes and
`foot_rotation` on 147; the foot labels found there fall from 16 of 24 to 1 of 24.

Foot labels found at good light, the count the ruling asks for (24 labels, 12 per measure):

| kind of label | labels | found before | found after |
|---|---:|---:|---:|
| a foot the camera sees (front, or the left foot at 45 and side) | 10 | 10 | 10 |
| both feet (`both`) | 11 | 10 | 10 |
| the far foot (the right foot at 45 and side) | 3 | 2 | 2 |
| **all** | **24** | **22** | **22** |

The 3 far-foot labels are `exercise_45_good_10_foot_turned_in-right` and `dance_side_good_10_foot_turned_in-right`
(`foot_rotation`, found before and after: their jitter is under 4) and `dance_side_good_11_ankle_rolled_in-right`
(`ankle_inversion`, missed before and after). So hiding the far foot turned **none** of the 3 into a miss on seed 5. Two
`both` labels (`dance_45_good_12_ankle_rolled_out-both` and `dance_side_good_12_ankle_rolled_out-both`) are now found from
the near foot alone (the right ankle is withdrawn; a `both` label accepts either side, `evaluate.py`), which changes their
fault from `both` to `left`. The one `both` label not found, `exercise_front_good_12_ankle_rolled_out-both`, was missed before.
On a held-out seed the expected cost is small: a quarter of seed 5's foot labels at good light are one-sided on the right (6
of 24, 3 of them at 45 and side), and the far foot of such a take is hidden 11 times in 26 at 45 and 24 in 26 at the side
(`ankle_inversion`), so a label or two per seed, against the 0.75 bar with seed 5's good-light recall at 0.96 to 1.00.

The retimed bar (the 27 seed 5 exercise takes 00 to 08 at six speeds and rates, 24 planted faults per row; the clips carry no
feet, so the rule cannot touch them): 24, 24, 24, 24, 24 and 24 of 24 in the rows 15 fps, 10 fps, 5 fps, 2 s squat, 1.5 s
squat and 1.5 s squat at 15 fps (`tests/test_retimed.py`).

`make report-real` (reported, never gated; the real files jitter under 1, so nothing moves): Part 3's kit 15 takes tp 10, fp 4,
fn 2 (P 0.7143, R 0.8333); stock tp 1, fp 7, fn 0 (P 0.125, R 1.0); Part 2's 3 different-movement clips warned and graded F; 2
of 2 multi-rep clips matched, 10 of 10 reps. `make report-profiles` (reported, never gated; good light is as before in all
three profiles):

| profile | good light P / R | overall P / R, before | overall P / R, after | faults not in fitness |
|---|---|---|---|---|
| fitness | 0.95 / 0.97 | 0.53 / 0.91 | 0.55 / 0.81 | 0 |
| dance | 0.95 / 0.75 | 0.62 / 0.74 | 0.60 / 0.65 | 0 |
| rehab | 0.95 / 0.72 | 0.62 / 0.72 | 0.60 / 0.65 | 0 |

### Costs and limits, stated
- Low light: the foot measures are off on nearly every take, so the reported low-light recall falls (above) while its
  precision moves by 0.05 at most. A coach silent about a foot it cannot see is the better product, and low light is never
  gated (ADR-0003).
- The rule is built and measured on the synthetic noise model, which is also the model of the held-out series (ASM-002,
  ASM-013). It says nothing yet about whether Part 2's far foot jitters (on the three real files it does not).
- The limit is per frame of the side file, so it assumes frames 1/30 to 1/10 s apart; a much faster file would read a smaller
  step for the same noise.
- **Known limit of the statistic, and the candidate for a later held-out family** (TICKET-051; pre-freeze review of
  attempt 5, residual 4). The median step is frozen with attempt 5's record and is never changed outside a new held-out
  family (ADR-0017). It has three weaknesses. It reads a quick real foot movement as jitter: a steady swing of 2 degrees
  a frame reads 2.0 (the test case `[2 * i]`), so a twist-style dance whose foot turns faster than the limit would hide
  `foot_rotation` on both clips with `hidden_reason` null (the ADR's Dissent states this risk). It depends on the frame
  rate: the step is per frame of the side file, so the same movement reads a smaller step at a higher rate. And duplicated
  frames (a file that repeats frames) add pairs with a step of 0 and pull the median down, so noise reads steadier than it
  is. The candidate that separates movement from noise is the median absolute second difference of the series (or the
  residual from a 3-frame median): a steady movement has a second difference of 0 whatever its speed, and noise does not.
  Its limit would be measured on a seed 5 table like the one above and scored on a fresh held-out seed.
- A far foot with a real fault is not found when it jitters above the limit; on seed 5 that is nothing at good light.
- Which foot was hidden is visible only as the missing names in `diagnostics.feet.<clip>.usable` and `compared`; the schema,
  its version and the shape of `diagnostics.feet` are unchanged.

## Dissent Review
Reviewed by: the pre-freeze reviewer (reviewer, model: opus), progress/review-20261101-prefreeze-attempt5.md; TICKET-051.
Date: 2026-11-01

### Concern 1: a quick real foot movement reads as jitter
Challenge: the median absolute frame-to-frame change cannot tell a fast real movement from noise.
Impact if right: a real foot fault in a fast movement is hidden.
Mitigation: recorded as a limit and pinned by a test; the median absolute second difference is named as the candidate for
a later held-out family; on seed 5 good light nothing real is lost.
Resolution: ACCEPTED_RISK

### Concern 2: the statistic depends on the frame rate and on duplicated frames
Challenge: at a low frame rate a steady foot moves more per frame; duplicated frames pull the median down.
Impact if right: the same foot is read at one frame rate and hidden at another.
Mitigation: recorded with Concern 1 in ADR-0015 Amendment 4; held-out seeds 71 and 73 passed with it.
Resolution: ACCEPTED_RISK

### Concern 3: a hidden far foot is not visible to the reader
Challenge: a reader cannot tell a measured foot with no fault from a foot that was not read.
Impact if right: "no foot fault" is read as "the foot was fine".
Mitigation: `diagnostics.feet.<clip>.usable` and `compared` name what was read, and the why_not message names both causes
(TICKET-051).
Resolution: ADDRESSED_IN_SPEC
