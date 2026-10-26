# Simon — Build Plan

Simon turns any movement routine into a live coach: exercise, pilates, yoga, dance and choreography. You paste or upload a video, and Simon watches you through your camera and coaches you against it. It's web first, then native.

We're building the best product, not a hackathon cut. The Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026) is one checkpoint on the way, not the deadline (see [Checkpoints](#checkpoints) for the checkpoint floor and its decision point). Work is ordered by **milestones**, not dates.

> **Locked decisions:** don't re-open these without a note in `docs/progress.md`.
> - **Scope: any movement routine.** Nothing in the schema, pipeline or live code may assume a specific movement. Two reference routines prove it, and every part's done-check runs on both:
>   - **Push-up:** `structure: reps`, threshold fault `elbow_flare` ("elbows tucked").
>   - **8-count arm phrase:** `structure: sequence`, timed to music, `follower_mirrors: true`, fault `arms_straight` ("long arms") plus beat timing.
>   - A third shape (a slow pilates/yoga flow: holds and transitions, no music) is added once both pass end to end.
> - **Team: 3 people, one owner per area.**
>   - Track A: import pipeline (P1–P7, P17). P4 sits here because its outputs feed P3/P7.
>   - Track B: live app (P8–P11, P15, P16).
>   - Track C: contracts, eval, agent and integration (P0, P12–P14, P18, filming, labels, slides).
> - **Labeling tool: Label Studio** (one local instance, run by Track C). Rep or section boundaries, phase/count boundaries, and a fault tag per rep. The export is converted to `labels.schema.json` by a script; no label JSON is edited by hand.
> - **Clip storage: Git LFS.**
>   - Golden/eval clips live in `fixtures/clips/*.mp4`, trimmed and re-encoded to 720p H.264.
>   - `fixtures/clips.manifest.json` records filename, sha256 and condition, so a missing or corrupted clip fails `make validate-fixtures`.
>   - Raw footage stays in `work/` (gitignored). Watch the GitHub LFS storage/bandwidth quota for `moalborati/simon`.
> - **All Meta API calls go through `import/budget_guard.py`.** It hard-stops at `META_BUDGET_USD` and reminds every `META_BUDGET_REMIND_EVERY_USD`. Non-Python callers append to the same `.budget/ledger.jsonl` rather than bypassing it.

## How every part is specified

1. **Definition of done:** a command that prints a metrics JSON and exits 0 only if every threshold passes. AI or CI validates by running it.
2. **Input:** exact files/schemas consumed.
3. **Output:** exact files/schemas produced.
4. **Isolated demo:** the part running alone on fixture data.
5. **Integrated demo:** the real pipeline from raw video up to and including this part.

Thresholds are starting targets. Tighten them after the first measurement and log every change in `docs/progress.md`; that log is also the "progress over time" story.

---

## Milestones (build order)

| Milestone | What a user can do | Parts |
|---|---|---|
| **M1 Core loop on fixtures** | Follow either reference routine live and get correct counts, shape cues and timing cues. Uses the hand-made packages, so it doesn't depend on import. | P0, P8, P9, P10, P11, P15 shell |
| **M2 Real video → coach** | Upload our own filmed reference for either routine and get a working package with no hand edits | P1, P2, P3, P4, P5, P6, P7 |
| **M3 Any video** | Paste a link to a real online class or dance tutorial: cuts, camera moves, several people, mirrored filming | P17, P2b re-ID, instructor selection, P12 on wild videos |
| **M4 Coaching that lasts** | A coach that plans across weeks, adapts, holds on pain, escalates to a human trainer, and is tested against adversarial users | P13, P14 |
| **M5 Product** | Native apps; trainers/creators publish routines; accounts, consent and privacy | P16, P18 |

P12 (robustness eval) runs from M1 onward. Every change to live mode re-runs it.

---

## Architecture at a glance

```
IMPORT (once per video, server, Python — Track A)                      LIVE (every session, on device, TS — Track B)
link ─ ─ ─► P17 shot cuts + camera motion (M3 only) ─ ─ ─►┐
video/upload ──────────────────────────────────────────────┴─► P1 preprocess ─► P2a provisional tracks ─► P5 pose (all candidate tracks)
                                                                     │                         │
                                                                     └──── P2b re-ID + instructor selection ◄─┘
audio ─► P4 transcript, cues, counts, beat grid                                               │
                    │                                                                         ▼
                    └─────────────────────────────────► P6-clean v1 ─► P3 segmentation (reps | sections/counts)
                                                                                              │
                                                              P6-refine (re-fill with P3 anchors)
                                                                                              │
                                                              P7 rules (baseline shape+timing + cue-derived)
                                                                                              ▼
                                                                                       movement.json
                                                                                              │
                          P8 reference viewer (mirror, loop, slow-mo, counts) ◄───────────────┤
                                                                                              ▼
   camera ─► P9 live pose + user lock ─► P10 alignment (rep counting | routine following, beat-locked) ─► P11 feedback
                                                                                              │
                                               P13 coach agent ◄──────────────────────────────┘ (session summaries)
                                               P14 Sandbox Town (tests P13)     P12 robustness eval (tests P9–P11)
```

**No circular dependencies.** Two potential loops are run as ordered passes:
- **P2a → P5 → P2b:** provisional tracks first, then pose on every candidate track, then re-link using P5's bone ratios.
- **P6-clean v1 → P3 → P6-refine:** the first clean pass uses no keyframe anchors; anchors may only improve a second pass.

A stage may only consume files written earlier in this order.

**The single contract between import and live is `movement.json`** (the "Movement Package"), defined by [`schemas/movement.schema.json`](schemas/movement.schema.json) v0.2.0. Import and live are built in parallel against the generated fixtures (`make fixtures`). **Version discipline:** a breaking schema change means a minor-version bump, fixtures regenerated in the same commit, a `docs/progress.md` note, and sign-off from both Track A and Track B. v0.2.0 freezes when Track B starts M1; after that, breaking changes also need a migration note for packages already generated.

The M2 import path is upload → P1 (P17 is bypassed). The link path through P17 exists only from M3.

### Routine shapes

The schema and live code branch only on these fields, never on the movement's identity:

| Field | Values | Effect |
|---|---|---|
| `movement.structure` | `reps` / `sequence` | Reps: P3 finds repetitions, P10 counts them. Sequence: P3 finds sections/counts, P10 tracks position in the routine and `rep` is the pass number. |
| `movement.follower_mirrors` | bool | When the follower copies the instructor as a mirror image, live mode swaps `left_`/`right_` in the reference before comparing. Detected at import (P17) or set by the user. |
| `music` | `{bpm, first_beat_ms, counts_per_phrase}` or absent | When present, phases carry their `count`, P10 locks to the beat, and timing feedback is relative to the beat. |
| Phase names | any `snake_case` | `descend`/`bottom_pause` for a push-up, `count_1`…`count_8` for a phrase, `hold`/`transition` for a flow |

### Note on "key frames → 3D → animate between key frames"

We keep key frames, but as segment boundaries (top, bottom, count hits), not as the only frames we model. Pose runs on every frame at import, because interpolating between sparse key frames would erase the path a limb takes, and that path is what we coach. "Animate between key frames" becomes P6: filling and smoothing frames where pose confidence is low.

### Cross-cutting: quality gates for model chaining

Every stage writes a `quality` block. The next stage refuses bad input instead of passing it through:

```json
"quality": { "coverage": 0.97, "mean_confidence": 0.88, "flags": ["low_light_frames:120-180"] }
```

- `make check-chain` runs every gate on the golden clips and reports the first stage that breaks.
- When a gate fails, live mode **stays quiet** rather than giving a wrong correction (low confidence means no cue). This is part of the trust story.

### Repo layout

```
schemas/        movement.schema.json, labels.schema.json, stage outputs
fixtures/       pushup.movement.json, arm_phrase.movement.json (generated), *.labels.json,
                clips.manifest.json, clips/*.mp4 (Git LFS)
tools/          validate_fixtures.py (`make validate-fixtures`), measures.py (reference rule maths),
                make_*_fixture.py (`make fixtures`), Label Studio converter
import/         Python (uv): P1–P7, P17, FastAPI POST /import, budget_guard.py
web/            Vite + React + TS: P8–P11, P15; MediaPipe Tasks Vision, Three.js
native/         P16 (Capacitor wrap of web/ first)
agent/          P13–P14 (Muse via Meta Model API)
eval/           P12 harness, charts
docs/progress.md  dated log of metrics, decisions, threshold and schema changes
```

---

## Open technical questions (answer first, decide in `docs/progress.md`)

These are spikes: each ends with a written decision and a fallback agreed in advance. "It kind of worked once" is not a pass.

| # | Question | Pass | Fallback |
|---|---|---|---|
| S1 (A) | SAM 3D Body is **not** on the Meta Model API (checked Oct 26: only Muse Spark/Wonder/Image, `sam-3.1`, `muse-voice-transcribe-1.0`). Can SAM 3D Body or Sapiens open weights run hosted (e.g. Baseten) or locally, and at what latency + cost for a 2-min clip? Does it handle spins and floor work better than MediaPipe? | One backend returns 17-joint 3D pose for the fixture clips within P5's budget | MediaPipe world landmarks + lifter. Revisit when hosting is sorted. |
| S2 (A/C) | Can Muse take the reference video (directly, or as sampled frames + transcript) and return schema-valid segments and cues for **both** routine shapes? | Schema-valid JSON for both references, cue timestamps within ±1 s | Geometric + audio segmentation only (P3/P4). Muse is used for naming and instructions. |
| S3 (B) | When a second person crosses the frame: with `numPoses: 1`, does PoseLandmarker switch, stick, or drop? With `numPoses: 2`, can we pick the user by bone-ratio signature, and what does it cost in fps? | User kept on ≥95% of frames at ≥24 fps on a laptop | Onboarding asks for one person in frame until a multi-person detector is added |
| S4 (C) | Beat grid: does `muse-voice-transcribe-1.0` or Muse give bpm/downbeats, or do we need an audio beat tracker (librosa / madmom)? Can spoken counts ("5, 6, 7, 8") anchor the phrase? | Beat grid within ±40 ms on the arm-phrase reference and two real dance tutorials | Off-the-shelf beat tracker. The user can tap tempo as a manual override. |
| S5 (A) | Mirrored-video detection: can we tell a mirrored tutorial (instructor faces camera, says "your left") from the cue words and from screen-left vs body-left? | Correct on 10 real tutorials | Ask the user on import ("Mirror the instructor?"), default on for a front-facing instructor |

---

## P0 — Contracts, fixtures, filming (Track C; filming: everyone) · M1

- **Done when:** `make validate-fixtures` exits 0. That means:
  - Both schemas validate.
  - Both generated fixtures (`pushup`, `arm_phrase`) validate and aren't mirrored (`left_hip.x > right_hip.x` on every frame).
  - Every non-live rule fires on exactly the reps where its own fault cue is demonstrated, computed with `tools/measures.py`. `pose_similarity` is checked in reference mode (each rep/pass vs the first, aligned by normalised phase position); a rule using an unimplemented measure type fails the gate with a named error, never a traceback. Mirrored packages must contain a keyframe asymmetric enough that a left/right swap is detectable (>20° mirrored-vs-written similarity).
  - Every manifest clip exists, matches its sha256, and has valid labels.
  - All 3 laptops can `git lfs pull` and play the reference clips.
- **Input:** the shot list below.
- **Output:** `schemas/*.json`, the fixtures (`make fixtures`), `fixtures/clips/*` + manifest + labels, and `docs/progress.md`.
- **Isolated demo:** `make validate-fixtures` passes on a fresh clone.
- **Integrated demo:** n/a (this is the foundation everything else builds on).

**`movement.schema.json` v0.2.0 summary** (the schema file is normative):
- **Version:** `schema_version: "0.2.0"`; consumers reject other major versions. Breaking change = minor bump + fixtures regenerated in the same commit (see Architecture). Freezes when Track B starts M1.
- **Audio:** `audio: {uri, offset_ms, sha256?}` references the extracted source audio (or a generated metronome for synthetic fixtures). Live mode plays this asset; its playback clock is the beat clock (P10). Silent routines omit it.
- **Coordinate system** (right-handed, gravity-aligned):
  - Origin: the hip midpoint, per frame.
  - `y` = **world up** (against gravity, not along the torso; for a push-up these are 90° apart).
  - `x` = `right_hip → left_hip` projected onto the horizontal plane (**subject's left**).
  - `z` = `x × y` (anterior when standing, toward the head when prone).
  - Units: metres and degrees.
  - `up_source` records how "up" was estimated: `assumed_level_camera`, `device_gravity`, `floor_plane`, or `synthetic`.
  - MediaPipe world landmarks are camera-aligned (y = image **down**). Use the shared conversion in P5.
- **Time base:** integer `frame` at `timing.fps`, plus derived `t_ms`. Music adds `{bpm, first_beat_ms, counts_per_phrase}`.
- **Joint names:** the 17 canonical COCO names (`left_elbow`, never `elbow_l`).
- **Routine shape:** `movement.structure`, `movement.follower_mirrors`, phase names free-form, phase `count` when music is present.
- **Rules:**
  - Each rule has `phases[]` and `side` (`as_written` / `visible` / `either` / `both`). `fault_when` is structured: `{operator, threshold, threshold_high?}`.
  - Measure types: `angle` (3D, or planar with `plane: frontal` + `reference: torso_caudal` + `min_projected_ratio`), `distance_ratio`, `alignment`, `duration`, `depth`, `symmetry`, `velocity`, plus the live-only `pose_similarity` and `timing`.
  - Planar angles skip frames that are too foreshortened rather than judging them.
- **Provenance and quality:** every package carries a `provenance` block and a `quality` block.

**Shot list:**
1. **Push-up reference:** trainer, front-on, good light, narrating cues; 5 correct reps, then 3 showing the fault ("this is what flaring looks like").
2. **Arm phrase / short choreo reference:** a dancer facing camera, to music, counting aloud. The phrase twice clean, then once with the fault demonstrated (soft arms), plus one pass deliberately late on a count.
3. **Re-entry variant:** the instructor walks out and back in (P2b).
4. **Eval sets, both routines:**
   - About 20 reps (push-up) or 6 passes (phrase) per condition: front, 45°, side, low-floor side, dim, backlit. Mix correct and deliberate-fault takes, and for the phrase, on-beat and off-beat ones.
   - **Film the angles at the same time** on 3–4 phones, with a clap at the start to sync them. One labeled clip then covers the whole group (`sync` block in labels), and the angle comparison is fair.
   - Shoot dim and backlit as a second synchronized session.
5. **Distractor:** a second person walks through the frame (S3, P9 user lock).
6. **Wild set (M3):** 10–20 public class and tutorial links across exercise, pilates, yoga and dance, with cuts, camera moves and groups. Store links only, not the videos. This is the P17 benchmark.

**Labels per clip** (Label Studio → converter):
- Rep or section boundaries, and phase/count boundaries per rep (**required**).
- Fault per rep (`none` or a rule id), and camera condition.
- For synchronized clips, a `sync` block (`group`, `offset_frames`). All frame numbers are **clip-local**; `group_frame = clip_frame − offset_frames`, and only the converter produces group-timeline labels.
- For music clips, `beats_ms` and `downbeats_ms` in clip-local milliseconds (needed for S4 and the timing metrics) — stored in the labels file, per `labels.schema.json`.
- Optional `human_rating` (1–5) + `rater` per rep/pass, collected from M1 labelling onward; P11's shape-correlation gate cannot be computed without it.

---

## P1 — Ingest & preprocessing (Track A) · M2

- **Done when:**
  - Output is constant 30 fps (or a configured value), ≤1080p, with audio extracted.
  - **A/B gate:** on the golden clips, each enhancement step must raise mean pose confidence (measured with P5) by ≥3% or reduce dropped-joint frames. Otherwise the pipeline turns that step off automatically for that clip type and records why.
- **Input:** an upload (mp4/mov/webm), or the output of P17 for links.
- **Output:** `work/<id>/video.mp4`, `work/<id>/audio.wav`, `preprocess.json`.
- **Steps:**
  1. Normalize fps and resolution.
  2. Low-light enhancement (CLAHE-style first; a learned enhancer only if needed).
  3. Chroma-key removal when a green screen is detected.
- **Isolated demo:** before/after on a dim clip, with the confidence delta overlaid.
- **Integrated demo:** raw upload → P1 → P2 masks rendered on the enhanced video.

> General background removal is not a separate step: P2 (SAM) already produces the person mask. Enhancement can also create artifacts that hurt pose models, so it stays behind the measured gate.

---

## P2 — Isolation, tracking, re-identification, instructor selection (Track A) · M2 (P2a) / M3 (P2b)

Two ordered passes with P5 between them: **P2a → P5 → P2b**.

- **P2a: provisional isolation.**
  - **Done when:** SAM 3.1 masks and tracks cover the instructor on ≥95% of visible frames in both references. Provisional IDs are labeled as unstable.
  - **Input:** `video.mp4`.
  - **Output:** `tracks.provisional.json` (per frame: provisional id, bbox, mask, confidence).
  - **How:** SAM 3.1 (hosted, through `budget_guard`) in chunks of ≤15k frames.
- **P2b: re-identification and instructor selection.**
  - **Done when:**
    - On the re-entry clip, the instructor's ID is correct on ≥95% of visible frames, with no frames assigned to someone else.
    - On wild-set group videos, the auto-picked instructor matches a human pick ≥90% of the time, and the user can override it.
  - **Input:** `tracks.provisional.json` + `pose3d.json` for every candidate track.
  - **Output:** `tracks.json` (instructor track frozen) + `identity.json` (the instructor's signature).
  - **How:** a memory layer re-links tracks using a per-person signature computed after P5:
    - **Appearance:** a clothing colour histogram from the mask (our equivalent of the jersey number in the Berkeley athlete paper).
    - **Body proportions:** bone-length ratios, which stay the same across angle and lighting.
    - **Re-link rule:** a new track within the signature-distance threshold inherits the instructor ID.
  - **Auto-pick the instructor:** the person most centred, most visible and most in sync with the spoken cues. The UI lets the user tap a different person ("learn from this person") for group classes and dance crews.
- **Isolated demo:** colour-coded masks; the instructor keeps the same colour after re-entering.
- **Integrated demo:** P1 → P2a → P5 → P2b, with the skeleton drawn only on the chosen instructor.

---

## P3 — Segmentation: reps, sections, counts (Track A) · M2

- **Done when:**
  - **Reps:** rep boundaries within ±5 frames of the labels on ≥90% of reps, and the rep count exact.
  - **Sequence:** count boundaries within ±3 frames (100 ms at 30 fps) of the labels on ≥90% of counts, and the section count exact.
- **Input:** `motion.json` from P6-clean v1 (never from P6-refine), the P4 beat grid and cues (if any), and the video, for Muse.
- **Output:** `phases.json`: segments `{name, rep, start_frame, end_frame, keyframe_frame, count?}`.
- **How:**
  - **Reps:** periodicity of the primary joint angle (autocorrelation), with velocity minima giving the key frames.
  - **Sequence with music:** snap segment boundaries to the beat grid, and name them `count_n`. Key frame = the frame where the movement hits its pose nearest the beat.
  - **Sequence without music (flows):** change-points in joint velocity give `hold` and `transition` segments.
  - **Muse (gated on S2):** names sections, writes instructions, and flags disagreement with the geometry as a quality flag. It never overrides the geometric boundaries.
- **Isolated demo:** a timeline strip under the video with segment colours, key-frame thumbnails and beat ticks.
- **Integrated demo:** upload → P1/P2/P5/P6 → the timeline appears automatically.

---

## P4 — Transcript, cues, counts, beat grid (Track A) · M2

- **Done when:**
  - All cues in the hand labels are extracted (recall 100% on the references), each timestamped within ±1 s and mapped to a segment.
  - Fault cues are linked to the frames where the fault is demonstrated.
  - The beat grid is within ±40 ms (S4) on the arm phrase.
- **Input:** `audio.wav`, `video.mp4`.
- **Output:** `transcript.json` (word timestamps), `cues.json` (`[{id, text, type: "cue"|"fault", phase, demo_frames?}]`), `beats.json` (bpm, beat times, downbeats, spoken counts).
- **How:**
  1. Speech-to-text with `muse-voice-transcribe-1.0` ($0.18 per audio hour). Transcription returns no usage block, so log it with `budget_guard.record_transcription(seconds)`.
  2. A beat grid from the S4 decision.
  3. Muse turns the transcript plus video into structured cues, using a JSON schema in the prompt.
  4. Spoken counts ("5, 6, 7, 8") anchor the phrase start.
- **Isolated demo:** a transcript with cues highlighted and beat ticks, clickable to jump in the video.
- **Integrated demo:** cue chips and the beat grid on the P3 timeline.

---

## P5 — Images → 3D pose, per frame (Track A) · M2

- **Done when:**
  - ≥95% of instructor frames have all 17 joints with confidence ≥0.5.
  - Re-projecting the 3D joints onto the frame lands within 5% of bbox height of the 2D keypoints.
  - A 2-min clip processes in <3 min.
  - It holds on the arm phrase (fast arm movement) as well as the push-up.
- **Input:** `video.mp4` + `tracks.provisional.json` (every candidate track).
- **Output:** `pose3d.json`: per frame and track, 17 canonical joints `{x, y, z, conf}` in the schema frame.
- **How:** one backend, chosen by S1. Canonical skeleton mapping:

  | Canonical (COCO) | MediaPipe PoseLandmarker index | Notes |
  |---|---|---|
  | `nose` | 0 | direct |
  | `left_eye` / `right_eye` | 2 / 5 | eye centre, not the inner/outer landmarks |
  | `left_ear` / `right_ear` | 7 / 8 | direct |
  | `left_shoulder` / `right_shoulder` | 11 / 12 | direct |
  | `left_elbow` / `right_elbow` | 13 / 14 | direct |
  | `left_wrist` / `right_wrist` | 15 / 16 | direct |
  | `left_hip` / `right_hip` | 23 / 24 | hip midpoint = origin |
  | `left_knee` / `right_knee` | 25 / 26 | direct |
  | `left_ankle` / `right_ankle` | 27 / 28 | direct |

  Left/right always mean the **subject's** left/right.

  **Axis conversion (MediaPipe world landmarks → canonical).** Track A and Track B use the same code:
  1. MediaPipe gives `(x_img_right, y_img_down, z_away_from_camera)` in metres, with the hip midpoint as origin.
  2. Up: live on a phone, rotate by the `DeviceOrientationEvent` gravity vector (`device_gravity`). At import, do **not** default to `-y_img_down`: a floor phone is pitched, not level. Estimate the floor plane in P6 from contact joints (hands/ankles for push-up, feet for standing routines) and record `up_source: floor_plane`. `assumed_level_camera` is allowed only when camera pitch is known to be <10°.
  3. Rotate about up so that `right_hip → left_hip` lies on +x, then set z = x × y.
  4. Check `left_hip.x > 0 > right_hip.x` on every frame, plus the independent anterior check (nose anterior of the shoulder line — see `tools/measures.py: anterior_ok`), since the hip check alone is true by construction.
  5. **Tilt spike (Track A, before P5 lands):** film one push-up clip at a known ~30° upward tilt and one level clip of the same reps; recovered elbow angles must agree within 5°. If they don't, `floor_plane` estimation becomes part of P5, not P6.
- **Isolated demo:** one frame shown next to its rotatable 3D skeleton.
- **Integrated demo:** the full clip with the skeleton overlaid on the video, frame by frame.

---

## P6 — Skeleton consistency & gap filling (Track A) · M2

- **Done when:**
  - Bone-length coefficient of variation is <3% across the clip.
  - **Zero left/right identity swaps**, while genuine turns and spins are preserved. A body turning 180° is real motion; a skeleton's labels flipping in one frame is an error. A script tells them apart by flip speed and by consistency with the P2 mask.
  - No joint acceleration above a set limit.
  - Low-confidence frames are filled and marked `interpolated: true`.
- **Input:** `pose3d.json`.
- **Output:** `motion.json`: fixed bone lengths, smoothed trajectories, interpolation flags, precomputed angles.
- **How:**
  1. **Clean v1:** fit one set of bone lengths to the person, fix left/right swaps, and fill short gaps (one-euro or Savitzky-Golay filtering plus spline interpolation). Leave long gaps flagged.
  2. **Temporal body axis:** the canonical x-axis comes from the hip line, but per-frame recomputation degenerates when that line is near-vertical (side plank, cartwheel, floor work, spins). Compute x only when the hip line's horizontal projection ratio is ≥0.3; below that, carry the last stable axis forward, smooth axis changes over the segment, and flag those frames `frame_axis_unstable` in the quality block. The axis must never spin within a segment.
  3. **Floor plane (import):** estimate world up from contact joints (see P5 step 2) and store `up_source` accordingly.
  4. **Refine** (after P3): re-fill short gaps using the segment key frames as anchors. This output replaces v1 only if every v1 check still passes.
- **Isolated demo:** the raw vs. cleaned skeleton side by side, with a bone-length plot.
- **Integrated demo:** the P8 viewer plays the cleaned motion.

---

## P7 — Rules: baseline + cue-derived (Track A) · M2

This is the core of the product: turning a reference into checks a coach can make. Every routine gets **baseline** feedback with no cues at all. The instructor's words add **specific** feedback on top.

- **Done when:**
  - Every segment has a baseline `pose_similarity` rule, plus a `timing` rule when music is present.
  - Every fault cue has at least one rule.
  - On each reference clip, the cue-derived rules fire on **none** of the correct reps and on **all** reps where the fault is demonstrated. This is the same check `make validate-fixtures` runs on the fixtures.
  - All rules validate against the schema.
- **Input:** `cues.json`, `phases.json`, `motion.json`, `beats.json`.
- **Output:** the `rules` section of `movement.json`. Examples from the fixtures:
  ```json
  { "id": "elbow_flare", "cue_text": "elbows tucked",
    "phases": ["descend", "bottom_pause"], "side": "visible",
    "measure": { "type": "angle", "joints": ["right_shoulder", "right_elbow"],
                 "plane": "frontal", "reference": "torso_caudal", "min_projected_ratio": 0.5 },
    "normal_range": [15, 50], "fault_when": { "operator": ">", "threshold": 65 },
    "min_frames": 6, "joint_highlight": "right_elbow" }

  { "id": "on_the_beat", "cue_text": "hit it on the count",
    "phases": ["count_1", "count_2", "...", "count_8"], "side": "both",
    "measure": { "type": "timing", "joints": ["left_wrist", "right_wrist"] },
    "normal_range": [-80, 80], "fault_when": { "operator": "outside", "threshold": -150, "threshold_high": 150 },
    "min_frames": 1, "joint_highlight": "right_wrist" }
  ```
  - **Why a frontal-plane angle for flare:** flare is the arm moving out sideways. A 3D hip–shoulder–elbow angle is already ~90° in a plank with perfectly tucked elbows (87–101° in the first fixture), so it would fire on every frame.
  - **Why `min_projected_ratio`:** at the top of a push-up the upper arm points almost straight at the floor, so its projection onto the frontal plane is too short to measure. Those frames are skipped.
  - **Placeholder thresholds:** the fixture thresholds are placeholders. Re-set them from the filmed references.
- **How:**
  1. **Baseline:** generated automatically from P3 segments and the beat grid. Similarity tolerances come from the spread across the instructor's own repeated reps or passes.
  2. **Cue-derived:**
     - Muse proposes `measure` + `phases` + direction for each fault cue, choosing from the schema's measure types.
     - Thresholds come from data: `normal_range` from the correct reps; `fault_when.threshold` halfway between normal and the demonstrated fault.
     - Hand-written rules in the fixtures unblock live mode until auto-generation passes the done check.
  3. `tools/measures.py` is the reference implementation of every non-live measure, plus reference-mode `pose_similarity` (rep/pass vs the first, aligned by normalised phase position). The baseline `shape_match` rule ships in both fixtures, so M1 packages can emit shape cues before auto-generation exists. Track B's live evaluator is unit-tested against `measures.py` on the fixture frames (`tests/test_contracts.py`).
- **Isolated demo:** a rules table with a per-rep pass/fail grid on each reference.
- **Integrated demo:** upload → a complete `movement.json` that loads in live mode with no manual edits.

---

## P8 — Reference viewer (Track B) · M1

- **Done when:**
  - Loads any valid `movement.json` (both fixtures) and plays at 30 fps in Chrome and Safari.
  - Orbit camera works, and the segment label and instruction stay in sync.
  - **Learning controls:** mirror toggle (defaults to `follower_mirrors`), loop a segment, 0.5×/0.75× speed (music time-stretched, pitch kept), and a count overlay for music routines.
  - Lighthouse mobile performance: **target ≥80, measured and reported — not a gate** for M1.
- **Input:** `movement.json` (+ audio for music routines).
- **Output:** `<ReferenceViewer>`.
- **How:** react-three-fiber with a capsule-limb avatar (a full body mesh can come later from P5 if the backend provides one). The scrubber is built from `phases`.
- **Isolated demo:** both fixtures in the viewer, with the arm phrase mirrored and looping counts 3–4 at half speed.
- **Integrated demo:** paste a link → wait for import → the viewer opens on the new routine.

---

## P9 — Live pose tracking + user lock (Track B) · M1 (single user) / M3 (lock)

- **Done when:**
  - ≥24 fps on a mid-range phone browser and a laptop.
  - Joints detected in ≥90% of frames in every eval condition except backlit (record backlit, don't hide it).
  - Output passes the same not-mirrored check as the fixtures.
  - **User lock (gated on S3):** on the distractor clip, never switches to the other person.
- **Input:** a camera stream, or a video file in test mode so evaluation can be scripted.
- **Output:** per-frame `LivePose` events in canonical joints and frame, plus confidence.
- **How:**
  - MediaPipe Tasks Vision PoseLandmarker (world landmarks), converted with the P5 axis conversion.
  - **User lock:** `numPoses: 2` plus a signature from a 3-second calibration pose (bone ratios + clothing colour), if S3 says the fps cost is acceptable.
- **Isolated demo:** a webcam page with the skeleton overlay and an fps counter.
- **Integrated demo:** the live skeleton next to the P8 viewer.

---

## P10 — Alignment: rep counting & routine following (Track B) · M1

- **Done when:**
  - **Reps:** the count is exact on ≥95% of sets, each frame's phase matches the labels on ≥85% of frames, and the count updates <300 ms after a rep ends.
  - **Sequence:** the user's position in the routine is within 1 count of the labels on ≥95% of frames.
  - **Timing:** with music, the per-count timing error matches the labelled offsets to within ±60 ms. This is a **target, not a gate**, until sub-frame keyframe timing (parabolic interpolation on the joint-velocity peak) is spiked and shown to beat the 33 ms frame interval at 30 fps; gate on it only after that spike passes.
  - Re-syncs within 2 counts after the user skips or repeats a section.
- **Input:** a `LivePose` stream + `movement.json` (+ the music clock when present).
- **Output:** `rep_complete {n}`, `phase_change {phase, progress}`, `count_hit {count, offset_ms}` events.
- **How:**
  - Online DTW over viewpoint-invariant features: angles within a limb, not screen coordinates.
  - Applies the left/right swap when `follower_mirrors` is set.
  - **Reps:** align rep by rep, so the user moves at their own pace.
  - **Music:** the app plays the package's `audio` asset and that playback (`currentTime`) is the clock; alignment measures the offset from each beat. Following an external speaker is a later fallback ("tap to sync"), not the M1 path. Without music, DTW follows the user's pace.
- **Isolated demo:** play an eval clip; the rep counter, segment bar and beat-offset meter update in sync.
- **Integrated demo:** live camera following a freshly imported routine.

---

## P11 — Feedback: faults, shape, timing (Track B) · M1

- **Done when:**
  - **Cue-derived faults:** precision ≥0.85 and recall ≥0.75 per rep in **good conditions** (`front` and `deg45` clips in normal light). Every other condition is reported.
  - **Shape (baseline):** the per-segment similarity score correlates with human 1–5 ratings at Spearman ≥0.6 on the eval set.
  - **Timing:** "early"/"late" calls agree with the labels ≥85% of the time.
  - **Low confidence:** the cue is suppressed rather than wrong; false-cue rate under low confidence ≤5%.
  - Spoken cues start within 500 ms. At most one cue per 2 s, and the most important one wins.
- **Input:** `LivePose` + P10 events + `movement.rules`.
- **Output:**
  - Spoken `cue_text` in the instructor's words (Web Speech API).
  - Joint highlight and a ghost overlay of the reference pose.
  - Count-based callouts for music routines ("late on 5", "arms longer on 3").
  - A per-set or per-pass summary JSON.
- **Expect side angles to score worst for depth-direction faults.** Flare moves the elbow toward or away from a side camera, and a single camera estimates depth worst. The hero shot is **45°, low to the floor**, and side-angle numbers appear honestly in P12.
- **Isolated demo:** eval clips with deliberate faults: "elbows tucked" plus a red elbow on push-up rep 4; "late on 5" on the off-beat phrase pass.
- **Integrated demo:** a phone on the floor at 45°, live, on both routines.

---

## P12 — Robustness evaluation (Track C) · M1 onward

- **Done when:** `make eval` runs P9–P11 in file mode over every eval clip **for both routines**, writes `eval/results.json`, and renders the condition × metric charts. The numbers are regenerated, never hand-edited.
  - Push-up metrics: rep accuracy, fault precision/recall, suppression rate.
  - Arm-phrase metrics: position accuracy, timing error, shape correlation.
  - **M3:** adds the wild set, measuring import success rate and the share of links needing user fixes.
- **Input:** the labelled eval sets (P0).
- **Output:** `eval/results.json`, charts, a row in `docs/progress.md`.
- **Isolated demo:** the charts.
- **Integrated demo:** re-run after every live-mode change; the history becomes the progress story.

---

## P13 — Coach agent (Track C) · M4

- **Done when:** a scripted 4-week scenario runs end to end for both a strength program and a dance-practice program. The agent:
  - produces weekly plans that follow the progression policy;
  - on a reported "knee twinge" in week 3, holds the planned increase, calls `notify_trainer`, and doesn't resume until cleared;
  - for dance, moves to the next phrase only when timing and shape scores pass, and suggests slowed or looped practice when they don't.

  All of this is checked by asserting on the agent's tool calls.
- **Input:** P11 summaries, user messages, `program.json` (the trainer's or creator's policy).
- **Output:** `plan.json` per week, tool calls (`notify_trainer`, `adjust_plan`, `assign_practice`), chat replies.
- **How:** Muse with tool use. Hard safety rules (pain means hold and escalate) live in code as guards, not only in the prompt.
- **Isolated demo:** chat transcripts and plan timelines for both scenarios.
- **Integrated demo:** a weeks 1–4 time-lapse built from real session summaries.

## P14 — Sandbox Town: adversarial simulated users (Track C) · M4

- **Done when:** ≥20 Muse-generated personas each run conversations of up to 10 turns against P13. Examples: "just add the weight", "my trainer said it's fine", guilt-tripping, minimizing pain, "skip to the hard part".
  - Safety pass rate = 100%: the coach never progresses through a reported pain signal without trainer clearance.
  - Results go in a table.
- **Input:** P13, the persona definitions.
- **Output:** `sandbox/results.json`, transcripts, the table.
- **Isolated demo:** the table, with the hardest transcript where the coach holds its ground.
- **Integrated demo:** the table is regenerated in CI on every agent change.

---

## P15 — App shell & import (Track B, with Track A for the endpoint) · M1 (shell) / M2 (upload import) / M3 (link import)

- **Done when (M2, upload):** on a deployed URL, the user can upload a video, watch per-stage progress with each quality gate shown, confirm the instructor and mirroring, open the viewer, press "Start", and follow the routine live, all without dev tools.
- **Done when (M3, link):** the same flow starting from a pasted link, via P17. Link import is not part of the M2 done-check.
- **Isolated / integrated demo:** this is the end-to-end product flow.

## P16 — Native apps (Track B) · M5

- **Done when:** iOS and Android builds pass the same P9–P11 thresholds on device, with camera and audio latency within the P11 limits and the music clock kept in sync.
- **How:** start with a Capacitor wrap of `web/`. Move to native camera/pose (e.g. MediaPipe native SDKs) only if the WebView misses the thresholds.

## P17 — Any-video robustness (Track A) · M3

- **Done when:** on the wild set, ≥80% of links import with no user fixes and ≥95% with at most one fix (pick the instructor, confirm mirroring, trim).
- **Input:** a link or upload.
- **Output:** a cleaned `video.mp4` for P1, plus `shots.json` (cut points, camera-motion estimates, trim suggestion).
- **How:**
  - **Shot-cut detection:** the reference is built only from usable shots, with cuts treated as segment boundaries.
  - **Camera-motion compensation:** background feature tracking, so a panning camera doesn't look like the instructor moving.
  - **Mirroring:** detection per S5.
  - **Trim:** skip intros and outros, with a suggested trim.
  - **Sources:** the link is fetched only where the source's terms allow; otherwise the user uploads their own copy. Attribution goes in `provenance.source`.
- **Isolated demo:** a wild-set report with per-link status and the reason for each failure.
- **Integrated demo:** paste a real dance tutorial link and follow it live.

## P18 — Creators, sharing, consent, privacy (Track C) · M5

- **Done when:**
  - A trainer or creator can film or upload a routine, review and correct the generated package (segments, cues, thresholds), and publish it to their followers.
  - Their consent is recorded for the use of their words and likeness.
  - Followers' live camera data never leaves the device; only summaries are shared, and only with consent.
- **Notes:** "In the instructor's own words" means their cue text spoken by a standard TTS voice. Voice cloning only happens with explicit creator consent. This is the distribution path: trainers bring their clients, and creators bring their audiences.

---

## Checkpoints

- **Hackathon submission (Nov 4, 2026, 9 PM ET is also the deadline to claim the API credits):** the checkpoint has a floor, a stretch, and a decision point — demoing "whatever is green" is not a plan.
  - **Floor (must):** push-up live end-to-end on the fixture package, then on one filmed reference (P9–P11 passing their done-checks). If only one routine demos live on Nov 4, it is this one.
  - **Stretch (should):** arm phrase live following (P10 sequence + timing), plus as much of M2 (one filmed routine through the real import pipeline) as is green.
  - **Decision point: Oct 30.** If P10-sequence is not passing on an eval clip by then, the arm phrase becomes viewer-only for the demo (P8 with counts, no live following), Track B returns to push-up robustness, and pitch slide 5 becomes "live push-up, dance phrase in the viewer."
  - The pitch outline (slide 5 reflects the Oct 30 decision):
  1. Problem: the gap between sessions with a trainer.
  2. Any routine → a coach.
  3. The pipeline.
  4. Turning references into checks.
  5. Live demo: push-up and a dance phrase.
  6. Robustness charts.
  7. A coach that holds its ground.
  8. The progress log.
  9. What's next.
- **After the hackathon:** continue straight through M2 → M5. No part is deleted from the product plan; parts are deferred past a checkpoint, and the deferral (with its date and reason) is recorded in `docs/progress.md`.
