# Spec: Part 3, skeleton consistency (`pose3d.json` in, `skeleton.json` out)

> Copy of the maintainers' working spec `docs/specs/part3-skeleton.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Status: agreed at setup 2026-10-27 with the operator's answers of the same day; feasibility audit the
same day changed the DTW signal, the frame map, the synthetic noise, the flip penalty and added the
step 5b filter (each with its numbers below). Timebox: 3 hours wall clock for the one-prompt run.
Done = `make check-3` exit 0 with every threshold, one consolidated independent review with
blockers fixed, published to the team main, DONE? on issue #1 (operator 2026-10-27).
Scope source: moalborati/simon `docs/MINI-APPS.md` Part 3 and this repo's `README.md`. Shared-file
contracts: `docs/design/specs/contract-pose3d-input.md` (input) and `docs/design/specs/contract-skeleton-output.md`
(output). ADRs: 0001 (workspace and publish), 0002 (stack), 0003 (one phone at a time, 4 separate
takes, phase alignment), 0004 (body-based frame, one standard body), 0005 (mirror option, one person).

## Overview
Part 3 reads one `pose3d.json` from Part 2 (one phone, any camera angle, any phone tilt) and writes one
`skeleton.json` for exactly one person: the same frames and motion, expressed in a canonical body frame
whose up comes from the body and the ground, never from the camera, rebuilt on one standard reference
body, with no left/right label flips. The same movement filmed from any angle gives the same skeleton
within the 10-degree criterion. `make check-3` prints a metrics JSON and exits 0 only when every
threshold passes.

## Why This Is Wrong (Dissent-First)
- One standard body makes the output bone-length variation zero by construction, so the 2% threshold
  alone proves little. The check also reports the input variation and measures the other thresholds
  on data with ground truth.
- No real multi-angle recording exists. The 10-degree agreement is measured on synthetic takes derived
  from real motion; the metrics JSON and DONE? say so (`data_source: synthetic`).
- Phase alignment can flatter the agreement metric. A negative control must stay above the threshold.
- Mirroring cannot be seen in a pose (the body is near-symmetric), so `flip` auto relies on a hint.

## User Story
As Part 4 or Part 5, I read only `skeleton.json` and can compare any two recordings joint by joint,
because camera angle, phone tilt, body size and label flips are already removed.

### Jobs-to-be-Done
Registry `use_cases`: `uc-clean-real-clip`, `uc-four-take-agreement`, `uc-demo-viewer`. The hub
registry still lists a boundary `uc-real-four-take-capture`; it is permanently out of scope (real input
is one take at any angle, operator 2026-10-27) and needs no action. No camera is involved in Part 3:
inputs are `pose3d.json` files.

## Configuration
| Option | Values | Default | Meaning |
|---|---|---|---|
| `--flip` (Makefile `FLIP=`) | `auto`, `on`, `off` | `auto` | Mirror correction for selfie-mode recordings (ADR-0005). `on` mirrors the movement back. `off` never mirrors. `auto` reads only the top-level key `mirrored`: `true` mirrors, `false` or absent does not. Any other key (for example a camera-facing hint) is ignored by `auto`, because a front camera does not imply a mirrored file. The output records the setting, whether it was applied and why. |

Mirroring (step 3) in the person's frame: every joint's x becomes -x, then every left/right pair
swaps its label (eyes, ears, shoulders, elbows, wrists, hips, knees, ankles). The two together keep
the left hip at positive x. `mirror.reason` is one of `flag on`, `flag off`, `auto: input mirrored
true`, `auto: input mirrored false`, `auto: no mirrored key in input`.

No other options: everything else is fixed by this spec.

## Pipeline (in this order)
| Step | Module | What it does |
|---|---|---|
| 1 Read and validate | `part3/schema.py` | Validate against `contract-pose3d-input.md`. |
| 2 Pick the person | `part3/person.py` | Keep exactly one person id (rule below). |
| 3 Mirror | `part3/mirror.py` | Apply the `--flip` setting. |
| 4 Label-flip repair | `part3/flips.py` | Detect and undo left/right label swaps; record them per frame. |
| 5 Body frame | `part3/facing.py` | Body-based up, then the per-frame canonical body frame (below). |
| 5b Temporal filter | `part3/temporal.py` | Centred mean over 1/3 s of every joint position in the body frame: 5 frames at 15 fps (below). |
| 6 Standard body | `part3/bones.py`, `part3/standard.py` | Rebuild every frame on the one standard reference body. |
| 7 Write | `part3/cli.py` | Write `skeleton.json` per `contract-skeleton-output.md`; validate it first. |

No change of timing: the output keeps every input frame and `t_ms`. One fixed temporal filter (step
5b) removes per-frame jitter; nothing else smooths.

### Step 5b: temporal filter (locked by the audit, 2026-10-27)
Each joint position (body frame, after steps 4 and 5) becomes the mean of a centred window of frames,
within each run of consecutive frames that have the chosen person; at a run's ends the end frame is
repeated. The window spans 1/3 s: its width is the odd number of frames nearest to fps / 3, the
smaller one on a tie, at least 1, where fps is 1000 over the median step between input `t_ms`
(`temporal.window_for`). At 15 fps, the rate the filter was calibrated on, that is 5 frames (the
mean of itself and the two frames on each side); at 5 fps it is 1 (no filter); at 30 fps it is 9.
Stitching (2026-10-28, ASM-018): a fixed 5 frames spans 1 s on Part 2's 5 fps clips and moved a
real dancer's knee angle by up to 28.6 degrees. `conf` is copied unchanged. Why: 8 of the 9 metric angles are interior angles,
which no rotation changes, so only noise sets the 4-take spread; a scratch simulation of this spec
(audit 2026-10-27) gave p95 about 11 to 16 degrees without the filter at the calibrated noise below
and about 6 to 10 with it. The filter moves the real squat's deepest knee angle by under 1 degree.

### Step 2: one person
Part 3 works on exactly one person. When the input holds several ids, it keeps the id present in the
most frames; a tie goes to the id with the larger median hip-to-ankle extent (the person nearer the
camera), then to the first id in input order. The output names the chosen id, the rule and the
candidates with their frame counts. Frames without the chosen person keep an empty `people` list.
No other multi-person handling.

### Step 4: label-flip repair
- **Whole body** (hip labels swapped). Part 2 builds x from the hip labels, so the frame comes out
  rotated 180 degrees about y: the face points to -z and knees bend backwards. Per-frame detector:
  nose and eyes ahead of the ear midpoint (z) and the knee flexion direction.
- **Limb group** (legs only, arms only, eyes and ears only), common in side views.
Repair: a two-state Viterbi pass over the clip per group (kept or swapped). State cost: distance of the
group's joints to the previous repaired frame plus deviation of its bone lengths from the clip medians;
a switching penalty stops one noisy frame from starting a swap. Groups (locked): `legs` = knees and
ankles, `arms` = elbows and wrists, `face` = eyes and ears, `body` = every pair (hip swap, found by the
per-frame 180-degree signature below). Starting constants: state cost = mean joint distance in metres
+ 1.0 x mean |L / median - 1| over the group's bones, joints at `conf` < 1 weighted 0.3; switching
penalty per group = 0.25 x the clip median of the mean distance between the group's left and right
joints. A fixed 0.15 m penalty can never repair a face swap: a swapped run is repaired only when the
penalty is below the left-right separation, and the eyes and ears are about 0.06 to 0.15 m apart
(audit 2026-10-27). The constants are internal tuning: the session may change them to pass AC-005
and records the final values here. Final values (one-prompt run, 2026-10-27, `part3/flips.py`):
transition cost = weighted mean joint distance between consecutive repaired frames (pairwise over
both states, joints at `conf` < 1 weighted 0.3) + the switching penalty 0.25 x the group's clip median
left-right separation; unary cost = 0.25 x mean |L / median - 1| over the group's bones (lowered from
1.0: the face bones are near rigid, so at 1.0 their noisy length term invented swap runs in about 1 of
60 re-noised clips; 0 in 300 at 0.25), plus for `body` the 180-degree signature relu(-(nose z - ear
midpoint z + mean knee-forward offset)) with weight 1; a virtual kept frame precedes the clip. A swap
in the first 3 frames of a fast-moving clip is not reliably repaired. A whole-body repair swaps every
left/right label and rotates the frame 180 degrees about y. `flips_repaired` lists what was repaired
per frame (`body`, `legs`, `arms`, `face`).

### Step 5: canonical body frame (camera angle and phone tilt removed)
Part 2 frames use the camera's up. Part 3 replaces it with an up taken from the body and the ground:
1. **Up.** `up` = the normalised clip mean of the vector from the ankle midpoint to the shoulder
   midpoint (`neck`) over standing frames (both knee angles above 160 degrees). Standing on the ground
   with straight legs, that line is close to vertical whatever the camera does. With fewer than 5
   standing frames, the input's own +y is used and `up_source` says `input_up`: Part 2 defines y as
   world up for a level camera, and a clip with no standing frame (floor work, a seated stretch)
   has no body line that is vertical. Stitching (2026-10-28, ASM-019): the old fallback, the mean
   ankle-to-shoulder vector over all frames, stood Part 2's cat-cow class clip upright (spine 86
   degrees from vertical in the input, 13 in the output). `PART3_UP_FALLBACK=all_frames` restores
   it, and `up_source` then says `all_frames`.
   One-legged exercises (TICKET-038): two-footed frames are standing frames whose ankles are level along
   the frame's own trunk line (height gap at most 0.05 of the median hip-to-ankle length). When at least
   5 exist and at least 5 standing frames have one ankle more than 0.20 higher along the two-footed
   frames' up (a straight leg raised, as in leg abduction), `up` is the two-footed frames' mean and
   `up_source` says `two_footed_frames`. A raised straight leg moves the ankle midpoint sideways and tilts
   the line; on REHAB24-6 clip PM_005 (leg abduction, whole clip) the tilt from vertical drops from 6.25
   to 2.74 degrees. Any other clip, a side bend on a wide stance included, is computed exactly as before.
   Floor work (TICKET-040, ADR-0004 amendment 2): only when the caller marks the exercise as floor work
   (`--floor-work`), a standing-frame `up` more than 30 degrees from the input's +y is a leaning or lying body (an
   incline push-up, a plank); the input's +y is used and `up_source` says `input_up_floor_work`. Without the mark
   nothing changes, so the camera's tilt never matters for an unmarked take. Limit: a marked floor-work clip
   filmed by a tilted phone keeps that tilt (the phone's gravity, TICKET-041, removes it).
2. **Per-frame axes.** y = `up`; x = left hip minus right hip with its `up` component removed;
   z = x cross y (anterior); origin at the hip midpoint. Every frame is re-expressed in these axes.
3. **True up for AC-006.** `truth.json` `up_in_input` is the up this same rule gives on the clean truth
   frames, rotated into the take's camera, not the fixture's +y: on the real squat the two differ by
   2.7 degrees (audit 2026-10-27), which alone would fail the 3-degree check on take 4.
Result: the camera's azimuth is gone (x follows the hips, as in Part 2) and the camera's pitch and roll
are gone (y follows the body). Real trunk lean during the movement stays, because `up` is one vector
for the clip. Trunk rotation relative to the pelvis stays, because only the hips set x. A whole-body
turn on the spot is not representable (Part 2 removes it per frame; ASM-009).

### Step 6: one standard reference body
Every skeleton is rebuilt on the same body, so two people and two recordings are directly comparable.
- Table: binding, fixed and source-checked on 2026-10-27 (table below). `part3/standard.py` loads
  `part3/standard_body.json` (already committed; produced by `docs/research/standard_body_derivation.py`)
  and never recomputes or edits it. `skeleton.json` `standard.sources` lists that file's `sources`.

| Bone | Length (m) | Derivation (stature H = 1.70 m) | Source |
|---|---|---|---|
| left_pelvis, right_pelvis | 0.1250 | Human3.6M hip joint centre half-width 132.95 mm, scaled by Winter thigh / Human3.6M thigh (416.5 / 442.9) | [H36M] |
| spine (root to neck) | 0.4896 | (0.818 - 0.530) H: shoulder level minus hip level | [W] |
| left_clavicle, right_clavicle | 0.1979 | ANSUR II biacromial breadth 0.2328 H, halved | [A] |
| left_upper_arm, right_upper_arm | 0.3162 | 0.186 H | [W] |
| left_forearm, right_forearm | 0.2482 | 0.146 H | [W] |
| left_thigh, right_thigh | 0.4165 | (0.530 - 0.285) H | [W] |
| left_shank, right_shank | 0.4182 | (0.285 - 0.039) H | [W] |
| head (neck to nose) | 0.1907 | neutral head model below | [W], [A], [MP], [K] |
| left_eye_link, right_eye_link (nose to eye) | 0.0618 | neutral head model below | [A], [MP] |
| left_ear_link, right_ear_link (eye to ear) | 0.0774 | neutral head model below | [W], [A], [MP], [K] |

  Neutral head model (origin at the neck, x left, y up, z anterior, metres): eyes at (±0.0314, 0.2006,
  0.0604), nose (0, 0.1633, 0.0984), ears (±0.0756, 0.1807, 0). Eye height: Winter eye level 0.936 H
  minus shoulder level 0.818 H. Eye spacing: ANSUR II interpupillary breadth 0.03696 H. Ear spacing:
  ANSUR II head breadth 0.0889 H (the COCO ear keypoint sits on the auricle, outside the tragion).
  Ear height: ANSUR II tragion-to-top-of-head 0.0757 H against Winter's vertex-to-eye 0.064 H. Ear
  depth 0: the ideal-posture plumb line runs through the ear and the shoulder [K]. Nose and eye
  depth: the MediaPipe canonical face, scaled so its eye spacing equals ANSUR II's.

  Sources (each read on 2026-10-27; SHA-256 of the copy read):
  - [W] Winter DA, *Biomechanics and Motor Control of Human Movement*, 4th ed., Wiley 2009, Fig. 4.1,
    after Drillis and Contini 1966. Read from the page scan at
    https://courses.grainger.illinois.edu/me481/sp2021/Anthro-Winter.pdf (c2e96f4b...).
  - [A] ANSUR II public data (Gordon CC et al., NATICK/TR-15/007), 4,082 men and 1,986 women, mean of
    per-subject ratios to stature: https://www.openlab.psu.edu/ansur2/ (men 0547aea0..., women
    ed7e800a...). `interpupillarybreadth` is stored in tenths of a millimetre.
  - [H36M] Human3.6M skeleton offsets (Ionescu et al. 2014) as published in
    https://github.com/facebookresearch/QuaterNet `short_term/dataset_h36m.py`.
  - [MP] Google MediaPipe `canonical_face_model.obj` (Apache-2.0), eye centre = mean of vertices 33,
    133, 159, 145; nose tip vertex 1; tragus-side contour vertex 234 (8bac8044...).
  - [K] Kendall FP et al., *Muscles: Testing and Function with Posture and Pain*, 5th ed. 2005, ideal
    lateral plumb line through ear lobe and acromion (as summarised in Nel, S Afr J Occup Ther 39(3),
    https://scielo.org.za/pdf/sajot/v39n3/02.pdf).

  Why not Winter for the two widths (ASM-004): Winter's shoulder width 0.259 H (0.440 m) and hip width
  0.191 H (0.325 m) are outer body breadths. COCO shoulder and hip keypoints sit near the joints: the
  Part 2 fixture measures 0.318 m and 0.172 m. ANSUR II biacromial breadth (0.396 m, acromion to
  acromion) and the Human3.6M hip joint centres (0.250 m) are the nearest published standards to
  where the keypoints are. Cross-checks: ANSUR II acromial height 0.8201 H agrees with Winter's
  0.818 H; ANSUR II and MediaPipe eye spacing agree (62.8 and 63.3 mm); Human3.6M forearm 251.7 mm
  against 248.2 mm here.
- Retarget: each frame is rebuilt from the hip midpoint outward; every bone keeps its input unit
  direction and takes its standard length. Low-confidence joints keep their input direction and `conf`.
- `bone_lengths_m` in the output is the standard set. `measured_bone_lengths_m` (median per bone over
  frames whose endpoints have `conf` 1.0, or all frames when under 10% qualify) is kept for context.

### Bone tree (18 bones; trunk through two virtual midpoints)
`root` = hip midpoint (origin), `neck` = shoulder midpoint.

| Bone name | From | To |
|---|---|---|
| left_pelvis, right_pelvis | root | left_hip, right_hip |
| spine | root | neck |
| left_clavicle, right_clavicle | neck | left_shoulder, right_shoulder |
| left_upper_arm, right_upper_arm | left/right_shoulder | left/right_elbow |
| left_forearm, right_forearm | left/right_elbow | left/right_wrist |
| left_thigh, right_thigh | left/right_hip | left/right_knee |
| left_shank, right_shank | left/right_knee | left/right_ankle |
| head | neck | nose |
| left_eye_link, right_eye_link | nose | left_eye, right_eye |
| left_ear_link, right_ear_link | left_eye, right_eye | left_ear, right_ear |

Bone-length variation is measured on these 18 edges (left_shoulder to left_hip is not a bone: it
changes with real trunk twist).

## Phase alignment for the 4-take agreement (operator ruling 2026-10-27, ADR-0003)
Movement is only ever recorded from one phone at a time. "The same movement filmed from 4 phones" means
4 separate single-phone takes of the same movement from 4 camera angles. Takes share no clock, no
calibration and no simultaneous view, and the performer moves slightly differently each time.
The 10-degree metric below is a DECISION (operator Mo, scope owner, delegated it on 2026-10-27;
locked by the prep lane the same day). It is posted on issue #1 as a DECISION, not asked.
- **Angles** (`part3/angles.py`), computed on the output `skeleton.json` joints, in this order:
  `left_elbow`, `right_elbow`, `left_shoulder`, `right_shoulder`, `left_hip`, `right_hip`,
  `left_knee`, `right_knee`, `trunk_inclination`. The first 8 are interior angles at B of (A, B, C),
  same side: elbow (shoulder, elbow, wrist), shoulder (elbow, shoulder, hip), hip (shoulder, hip,
  knee), knee (hip, knee, ankle). Interior angle = degrees(arccos(clip(u.v / (|u||v|), -1, 1))) with
  u = A - B, v = C - B, range 0 to 180. `trunk_inclination` = angle between (neck - root) and +y, so
  the check also catches tilt left in the frame.
- **Alignment** (`part3/align.py`): dynamic time warping of each take to the reference take 1 (front,
  azimuth 0) on a one-dimensional phase signal: the mean of the 8 interior angles in degrees (no
  z-scoring), smoothed by a centred 5-frame moving average with edge values repeated. Changed by the
  audit (2026-10-27): the z-scored mean cancels in a squat (the arm angles move against the knees and
  hips), the signal goes flat while the knees move fastest, and DTW then misplaces those frames; with
  zero synthetic error the z-scored signal gave p95 16.6 degrees and the degree mean 6.3.
  Local cost |a_i - b_j|; steps (1,0), (0,1), (1,1), weight 1;
  path from (0,0) to (n-1,m-1); Sakoe-Chiba band: cell (i,j) allowed when
  |i(m-1)/(n-1) - j| <= ceil(0.25 max(n,m)); ties prefer the diagonal, then (1,0), then (0,1). Frame
  map: for take-1 frame i, the take-k frame is the middle of the sorted j paired with i (index
  (count-1)//2); that sequence of positions is smoothed by a centred 3-frame mean (edges repeated),
  giving a fractional position, and take k's 9 angles are linearly interpolated there. At 15 fps the
  knee and hip angles change up to 12 degrees per frame, so whole-frame mapping alone costs several
  degrees of spread (audit 2026-10-27). Aligning on a summary signal, not on the measured angles, keeps the alignment from
  optimising the metric. Each take needs at least 10 frames with a person, else the check fails with
  `take <k> too short`.
- **Per-frame statistic**: for every take-1 frame where all 4 takes have a person at both frames
  around their mapped position, and every one of the 9 angles, the spread = max minus min across the 4 takes (equal to the
  largest pairwise absolute difference).
- **Pass rule**: `joint_angle_agreement_p95_deg` = `numpy.percentile(all spreads, 95)` (default linear
  method) must be at most 10.0. Reported beside it: `agreement_median_deg`, `agreement_mean_deg`,
  `agreement_max_deg`, `agreement_per_angle_p95_deg` (one value per angle name) and `frames_compared`.
  The max is reported, not gated: one frame of a far-side joint at `conf` 0.3 must not fail the part.
- **Context**: the same p95 under plain linear time normalisation (`agreement_linear_p95_deg`; take-k
  frame = rint(i(m-1)/(n-1))).
- **Negative control**: takes 1, 2 and 3 of the squat plus the arm-raise take (synthetic set below),
  through the same pipeline, DTW and statistic. `negative_control_p95_deg` must be strictly above 10.0,
  or the check fails with `alignment too permissive`.
- Rejected: Part 1 `keyframes.json` (not in this part's shared files), triangulation or multi-view
  fusion (no simultaneous views exist).

## Synthetic validation set (`part3/synth.py`, committed under `fixtures/input/synthetic-4take/`)
Deterministic (fixed seed) from the real Part 2 squat; a test proves regeneration is byte-identical.
Each take has its own `pose3d.json` and a ground-truth `truth.json`; `SOURCE.md` says it is synthetic.

| Layer | What is simulated |
|---|---|
| Ground-truth motion | The Part 2 squat, each joint smoothed by a 5-frame moving average, rebuilt at fixed bone lengths with clean labels, in a true body frame. |
| Take differences | Per take: start offset (0 to 1 s of standing), tempo factor 0.85 to 1.15 plus a smooth time warp, smooth per-angle performance variation up to 3 degrees. |
| Camera per take | Azimuth 0 (front), 45, 90 (side), 180 (back) degrees; phone pitch up to 20 degrees and roll up to 8 degrees, different per take. |
| Part-2-like errors | Depth error along the camera axis (per-take bias 10%); per-bone length jitter 3%; joint noise at the jitter measured on the real Part 2 fixture; far-side joints in side views at `conf` 0.3 with 2.67 times that noise; whole-body swaps in short runs in the back view, leg swaps in side views, one arm swap, one face swap. |
| Mirror | A fifth file, take 1 mirrored with `"mirrored": true`, for the `--flip` tests (not part of the 4-take metric). |
| Re-canonicalisation | Each take is put into Part 2's per-frame pelvis frame with the camera's up, as Part 2 would. |

Exact parameters (locked 2026-10-27):
- Randomness: `numpy.random.default_rng([20261027, k])`, k = 1 to 4 for the takes and 6 for the arm
  raise; the mirrored file reuses take 1 and draws nothing. Draw order inside a take is fixed by the
  code and documented in `synth.py`.
- Ground truth: the fixture's own frame is taken as the true body frame; frame rate 15 fps;
  `t_ms = round(1000 * frame / 15, 3)`; bone lengths = the fixture's median measured lengths.
- Per take:

| Take | Azimuth | Pitch | Roll | Start offset (standing) | Tempo |
|---|---|---|---|---|---|
| 1 | 0 (front) | +12 | -5 | 0.4 s | 1.00 |
| 2 | 45 | -8 | +6 | 0.0 s | 0.88 |
| 3 | 90 (camera on the subject's left) | +20 | +3 | 0.8 s | 1.12 |
| 4 | 180 (back) | -15 | -8 | 0.6 s | 0.95 |

- Start offset: the first truth frame repeated. Time warp: tau(t) = t + 0.03 D sin(2 pi t / D + phi),
  phi ~ U(0, 2 pi), D = clip duration (monotone because 0.03 x 2 pi < 1), then resampled at 15 fps
  by linear interpolation of joint positions.
- Performance variation: each of the 8 limb bones (upper arms, forearms, thighs, shanks) rotates about
  the body x axis by A sin(2 pi t / D + psi), A ~ U(0, 1.5) degrees, psi ~ U(0, 2 pi), applied down
  the chain, so each interior angle varies by at most 3 degrees.
- Tempo and warp: take time u (seconds after the start offset) shows truth time tau(tempo x u),
  clipped to [0, D]; the take has floor(15 D / tempo) + 1 motion frames after the offset frames.
- Errors, in this order: bone length factor N(1, 0.03) per frame and bone; depth along the camera
  axis (relative to the hip midpoint) times (1 + b), b ~ U(-0.10, 0.10) per take; joint noise
  N(0, sigma_j) per coordinate, where sigma_j for joint j is the root mean square over x, y and z of
  std(second difference of the fixture's joint j) / sqrt(6), computed by `synth.py` from the fixture
  (0.03 cm at the hips, about 0.4 to 1.0 cm elsewhere). Take 3: right elbow, right wrist, right knee
  and right ankle at `conf` 0.3 with 2.67 sigma_j instead.
- Why the error model changed (audit 2026-10-27): at the original values (joint noise 1.5 cm, far
  side 4 cm, per-frame depth noise 3%) a scratch simulation gave p95 about 22 degrees with perfect
  alignment, about twice the threshold, and no pipeline can fix it because 8 of the 9 angles do not
  depend on the normalisation. The original noise was 2 to 3 times the jitter the real Part 2 fixture
  shows; the per-frame depth noise counted that jitter twice. The ratio of far-side to normal noise
  (4 / 1.5) is kept.
- Injected label swaps (frame indices of the take's own file, inclusive): take 4 whole body 20-24 and
  61-65; take 3 legs 30-35 and 80-83, face 86-88; take 2 arms 50-53. `flips_injected` = 27 frames.
- Mirrored take: take 1's camera-space joints with x negated and every left/right pair swapped (a pose
  model labels a mirrored image by appearance), then Part 2-style canonicalisation; top-level
  `"mirrored": true`.
- Arm raise (negative control): the first truth frame held for 7.0 s (105 frames, t = f / 15) with
  legs and trunk fixed; both arms abduct in the frontal plane by 85 (1 - cos(2 pi t / 3.5)) degrees
  (0 to 170 and back, twice), elbows straight; camera and error parameters of take 4, drawn from its
  own stream (k = 6). No start offset, tempo 1, no warp, no performance variation, no injected swaps.
- Files: `fixtures/input/synthetic-4take/take-<k>/pose3d.json` and `truth.json` (k = 1 to 4),
  `take-1-mirrored/pose3d.json`, `negative-armraise/pose3d.json` and `truth.json`, `SOURCE.md`.
  `truth.json`: `{"take", "camera": {"azimuth_deg", "pitch_deg", "roll_deg"}, "start_offset_s",
  "tempo", "frames": [{"frame", "up_in_input": [x, y, z], "swapped": [...], "joints": {...}}]}`.
- These parameters are final. If the 10-degree threshold fails, follow "If the agreement check is
  red" below. A generator parameter or seed never changes to make the check pass, and the threshold
  never changes.

### If the agreement check is red (locked ladder)
1. Run the same metric on the truth frames (`truth.json` joints, through steps 5b and 6 only). If the
   truth spread is already near 10, the generator floor is the cause; if the truth passes and the
   pipeline output fails, a pipeline step is wrong (flip repair, up, retarget): fix it.
2. Check the frame map against truth time (each take's `truth.json` gives it): an error over 1 frame
   means an alignment bug; fix it.
3. Nothing else is tuned. If it is still red: the run ends DEGRADED with the measured numbers (goal
   brief, KNOWN RISKS).

## Files (source and tests this spec covers)
| File | Role |
|---|---|
| `part3/__init__.py`, `part3/__main__.py` | package; `python3 -m part3 run` entry |
| `part3/joints.py` | 17 canonical names, left/right pairs, groups, the bone tree |
| `part3/schema.py` | input and output validators; `python3 -m part3.schema` |
| `part3/person.py`, `part3/mirror.py`, `part3/flips.py`, `part3/facing.py` | pipeline steps 2 to 5 |
| `part3/temporal.py` | step 5b |
| `part3/io.py`, `part3/geometry.py` | optional shared helpers (JSON read and write, vector maths) |
| `part3/bones.py`, `part3/standard.py` | step 6; `standard.py` loads the committed table |
| `part3/standard_body.json` | the binding standard body (data, already committed; derivation in `docs/research/standard_body_derivation.py`) |
| `part3/cli.py` | pipeline wiring and writing |
| `part3/angles.py`, `part3/align.py`, `part3/metrics.py` | joint angles, DTW, the `make check-3` metrics |
| `part3/synth.py` | synthetic take generator |
| `Makefile`, `requirements.txt` | targets and pins (ADR-0002) |
| `tests/part3/test_*.py`, `tests/part3/conftest.py` | tests (section Test Scenarios); `tests/part3/` is exempt from the spec gate |

A new file under `part3/` or `web/` must be named in this table (or in `demo-viewer.md`) before it is
written: the write gate refuses any file there that no spec names.

## Acceptance Criteria
### AC-001: Input contract enforced
A file that breaks `contract-pose3d-input.md` makes `python3 -m part3 run` exit 2, names the failing
path (for example `pose3d.frames[3].people[0].joints.nose.conf`) and writes nothing.
### AC-002: Output is valid and mirrors the input
`skeleton.json` passes `python3 -m part3.schema`, has the same `frame` and `t_ms` sequence, and is
itself a valid `pose3d.json`.
### AC-003: One person
An input with several ids gives one person, chosen by the step 2 rule, recorded in `person`.
### AC-004: One standard body
Bone lengths recomputed from the output joints equal the standard table within 0.5% in every frame of
every clip, for any input body size.
### AC-005: Label flips repaired
Every injected whole-body, leg, arm and face swap in the synthetic takes is repaired, labels agree
with truth in every frame, and the real Part 2 output has zero frames still flagged.
### AC-006: Camera angle and tilt removed
For every synthetic take, the output's up is within 3 degrees of the true up (`up_in_input`, step 5 item 3) and the hip line is along
x (left hip at positive x, face at positive z), whatever the injected azimuth, pitch and roll.
### AC-007: Mirror option
`--flip on` on the mirrored take reproduces take 1's output within 1 degree per joint angle; `auto`
does the same when the hint is present and leaves an unhinted file unmirrored; `off` never mirrors;
the output records setting, applied and reason.
### AC-008: 4-take agreement
After DTW, the p95 of the per-frame spread of the 9 angles across the 4 takes is at most 10 degrees
and the negative control p95 is strictly above 10 degrees (section "Phase alignment").
### AC-009: Done-check
`make check-3` prints one metrics JSON (contract section "Metrics") naming `data_source: synthetic` and
exits 0 only when every threshold passes.
### AC-010: Output fixture
`fixtures/output/part2-single/skeleton.json` and `fixtures/output/synthetic-4take/take-<n>/skeleton.json`
ship with a README for Parts 4 and 5.
### AC-011: Demo viewer
A local static 3D page shows the 4 input takes and the 4 output skeletons overlapping on the shared
phase, rotatable, with play, pause and scrub (spec `demo-viewer.md`). No staging.
### Rule-Based ACs
- Deterministic: the same input and options give a byte-identical `skeleton.json`.
- A 1,000-frame clip runs in under 10 s on this host.

## API / Interface Contract
```
python3 -m part3 run --in <pose3d.json> --out <skeleton.json> [--flip auto|on|off]   # 0 ok, 2 invalid
python3 -m part3.schema <file>                                  # validate a skeleton.json, 0 or 2
python3 -m part3.synth --out fixtures/input/synthetic-4take     # regenerate the synthetic set
make run IN=... OUT=... [FLIP=auto]    make check-3    make test    make demo    make demo-stop
```

## Error Cases
| Case | Behaviour |
|---|---|
| Input fails the contract | exit 2, path named, nothing written |
| `frames` empty, or no person in any frame | exit 2 with the reason |
| `--flip` value not auto, on or off | exit 2 with the allowed values |
| Hips coincide in a frame | that frame's `people` is empty; counted in `person.frames_dropped` |
| Chosen person in fewer than 5 frames | output written; `person.few_frames: true` |
| Output path not writable | exit 1 with the OS error |

## Edge Cases
- Ids may be int or string and are kept as given.
- `right_ankle` at `conf` 0.3 in every frame of the real fixture: kept, direction from the input.
- No standing frames (floor exercise): `up_source: all_frames`.

## Locked defaults (2026-10-27; final, nothing here is asked)
| Item | Decision | Why |
|---|---|---|
| No standing frames | Fewer than 5 frames with both knees above 160 degrees: up from all frames, `up_source: all_frames` | A floor movement still gets a deterministic up and says so. |
| Turning on the spot | Not represented; documented in the output fixture README | Part 2 removes rotation per frame (ASM-009). |
| Low-confidence joints (`conf` < 1) | Kept with input direction and `conf`; weighted 0.3 in flip costs; excluded from `measured_bone_lengths_m` unless under 10% of frames qualify; included in the angle metric | Dropping them would empty the real clip's right ankle. |
| Minimum clip | `frames` empty or no person anywhere: exit 2. Chosen person in under 5 frames: written with `few_frames: true`. Metric takes need 10 frames each | Short clips still produce output; the metric needs a phase. |
| Several ids | Keep one (step 2) | Operator ruling. |
| Hips coincide | Distance under 1e-6 m: that frame's `people` is empty, counted in `frames_dropped` | No x axis exists. |
| Output numbers | Joint coordinates and lengths rounded to 4 decimals (0.1 mm), `-0.0` written as `0.0`; `t_ms` and `frame` copied | Byte-identical reruns; below Part 2's noise. |
| Output serialisation | `json.dumps(obj, ensure_ascii=False)` (default separators, one line) plus a trailing newline, keys in contract order | Same style as the Part 2 input; deterministic. |
| Metrics JSON | Printed with `indent=2`, numbers rounded to 3 decimals for printing only (pass/fail on unrounded values), also written to `out/check-3/metrics.json` (gitignored) | Readable in the DONE? comment. |
| `make check-3` working files | Pipeline outputs for the check go to `out/check-3/` | Never touches committed fixtures. |
| File names | `fixtures/output/part2-single/skeleton.json`, `fixtures/output/synthetic-4take/take-<k>/skeleton.json`, `fixtures/output/README.md` | AC-010. |
| DTW window | Sakoe-Chiba band, ceil(0.25 max(n,m)) frames | Covers the 0.85 to 1.15 tempo range and the 1 s offsets. |
| Demo viewer | Port 8733 on 127.0.0.1; three.js r170 vendored in `web/vendor/three/` | `demo-viewer.md`. |
| Temporal filter | Step 5b, centred mean over 1/3 s (5 frames at 15 fps), fixed | Audit 2026-10-27, numbers in step 5b. |
| Flip groups and penalty | Step 4: four groups, penalty 0.25 x the group's median left-right separation | A fixed 0.15 m cannot repair face swaps. |
| Makefile | `PYTHON ?= python3`; `make test` = `$(PYTHON) -m pytest tests/part3 -q`; `make check-3` = `$(PYTHON) -m part3.metrics`; `make demo` starts the server detached (`setsid nohup`) and returns; port 8733 busy: `make demo` exits 1 naming the port | Runs the same in a clean clone; never blocks the session. |
| Python and packages | System `python3` 3.12.3 with numpy 2.4.6 and pytest 9.1.0 (verified 2026-10-27) | ADR-0002. |

## Non-Functional Requirements Checklist
Local files only, no network; no video; viewer usable by keyboard and at phone width.

## Negative Requirements (What This Feature Must NOT Do)
- Must not read, import or copy code from any other Simon part.
- Must not use the camera's up, a shared clock, camera calibration or simultaneous views.
- Must not handle more than one person beyond the step 2 rule.
- Must not retime the motion or smooth it beyond the fixed step 5b filter; must not call any model or API.

## Compromises
### Bone-length threshold is met by construction
The check prints the input variation beside it so it is not mistaken for a Part 2 quality figure.

## Non-Requirements (Explicitly NOT Building)
Multi-person output, whole-body turn recovery, multi-view fusion, Part 1 key frames, mirror detection
from the pose itself, video I/O.

## Assumptions
`docs/assumptions/ASM-001` to `ASM-011`.

## Implied Requirements Discovered
- Part 5 compares segment directions, so the body-based up matters beyond interior angles.
- `skeleton.json` staying a valid `pose3d.json` lets Parts 4 and 5 reuse a pose3d reader.
- Part 3 asks producers for an optional top-level `"mirrored": true` (contract-pose3d-input.md).

## Delivery Verification Plan (MANDATORY, from CRD)
`make test` (tests in `tests/part3/`), `make check-3`, one consolidated `reviewer` agent review with
blockers fixed (TICKET-010), and the viewer driven in a headless browser with screenshots and a
short video in `demo/` (demo-viewer.md) for DONE?.
### Device/Platform Strategy
Desktop and phone-width browser for the local viewer; command line on Linux, Python 3.11 or later.
### Data
Real Part 2 fixture plus the synthetic set; no personal data.

## Dissent Review (MANDATORY, hooks block implementation without this)
### Concern 1: synthetic data proves the method, not Part 2 in the wild
Errors are modelled on the real fixture (its measured per-frame jitter, input bone variation up to 24%,
an always-extrapolated ankle). Real input is one take at any angle, so the synthetic set is the
permanent angle-invariance test (ASM-008, ASM-011).
### Concern 2: one standard body hides real body differences
`measured_bone_lengths_m` stays in the output for context; the operator chose comparability.
### Concern 3: the standing-frames up assumes straight legs mean an upright body
It uses feet to shoulders, one vector per clip; the fallback is reported in `up_source`.
### Pre-Mortem
A teammate objects to p95, or a real take shows a flip pattern the Viterbi costs miss. The metric goes
to issue #1 as a DECISION early (median, mean, max and per-angle p95 are printed beside it, so another
reading can be checked without a rerun); the real-clip detector count stays in the metrics JSON.

## Requirements Traceability
| Requirement | AC | Ticket |
|---|---|---|
| reads pose3d.json, any angle | AC-001, AC-002 | TICKET-001, TICKET-003 |
| one person (operator) | AC-003 | TICKET-003 |
| fixed bone lengths, standard limb lengths, one standard body (operator) | AC-004 | TICKET-002 |
| no left/right label flips | AC-005 | TICKET-004 |
| standard facing; angle and tilt not a factor (operator) | AC-006 | TICKET-005 |
| mirror option (operator) | AC-007 | TICKET-003 |
| 4 angles agree within 10 degrees | AC-008 | TICKET-006, TICKET-007 |
| `make check-3` | AC-009 | TICKET-007 |
| ship an output fixture | AC-010 | TICKET-008 |
| isolated demo | AC-011 | TICKET-009 |
| independent review | all | TICKET-010 |
| publish and DONE? | AC-009 | TICKET-011, TICKET-012 |

## Test Scenarios (maps 1:1 to acceptance criteria)
`tests/part3/test_schema.py` (AC-001, AC-002), `test_person.py` (AC-003), `test_bones.py` (AC-004),
`test_flips.py` (AC-005), `test_facing.py` (AC-006), `test_mirror.py` (AC-007), `test_align.py`
(AC-008), `test_metrics.py` (AC-009), `test_fixtures.py` (AC-010, regeneration, determinism).

## Deviations from PRD
- "4 synced phones" is read as 4 separate single-phone takes (operator ruling 2026-10-27, ADR-0003).
- "One fixed set of bone lengths per person" becomes one standard body for every skeleton, and the
  part handles one person (operator answers 2026-10-27, ADR-0004, ADR-0005).
Upstream text is not edited by this workspace; the execution session posts a DECISION comment on
issue #1 first.
