# Spec: `make check-2` on committed reproducible outputs, the CPU 3D bar and the one-person ladder

> Copy of `docs/specs/check-2.md` from the maintainers' working repo at `843de10`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-28
Linked PRD: none. Requirements source: README "Definition of done", registry milestones M2 and M3,
use case uc-done-check, stakeholder-proxy decisions 2, 3 and 4 (2026-10-28).
Request Type: feature-mod
Risk Level: medium
Tickets: TICKET-016 (3D bar), TICKET-018 (stamps, `make outputs`, scored outputs), TICKET-019 (baseline),
TICKET-020 and TICKET-021 (ladder), TICKET-022 (M3 close-out), TICKET-037 (COCO one-person set), TICKET-044 (the CPU
mode the 3D bar scores, and the committed `cpu-sam3db-single` set).
ADRs: ADR-0004 (ladder, gold read-only), ADR-0006 (reproducible outputs and stamps), ADR-0002 (backends),
ADR-0003 (tracker order).

## Overview
`make check-2` today scores `out/<mode>/`, which is gitignored and was produced on the HPC cluster, so a clean
clone fails with "missing output" (exit 2 from make, audit 2026-10-28). Recorded on HPC outputs: one
person 3 of 20 frames over 5% (mean 3.78, p95 5.26, max 5.29), multi-person pass (7 people, coverage
1.0, 0 swaps). This spec makes the outputs reproducible on this host (`make outputs`), commits the scored
outputs with a v2 stamp under `fixtures/output/scored/<mode>/`, scores them by default, reports the CPU
backend's 3D bar as a separate block, and fixes the order of model-side improvements (the ladder) that
may turn the one-person check green. The scoring code, thresholds and labels do not change.

Operator rulings of 2026-10-28 add two things. The multi-person block is scored on `api-sam31` outputs (as the
team's recorded pass was), and `local-open`'s numbers on the class clip are printed as a second block that is
never gated. A second one-person block scores openly licensed, human-annotated COCO val2017 keypoints at any
angle (ruling on #337: camera angle must not matter); the one-person gate passes only when every scored
one-person set passes the unchanged 5% every-frame rule.

## Why This Is Wrong (Dissent-First)
- Committing outputs lets a clean clone pass without running a model. The stamp ties them to code,
  frames, weights and the environment lock, and `make outputs` reproduces them on this host; the check
  says which host and backend made them.
- 3 of 20 frames over 5% with a max of 5.29 is close to the bar; a rung could pass by noise. Every rung
  is measured on the same committed frames and its numbers are recorded, pass or fail.
- The 3D bar measures the CPU backend against the GPU output, not against ground truth. It catches a
  stretched skeleton; it cannot prove the GPU is right.

## User Story
As the team, I run `make check-2` on a clean clone and read one metrics JSON that says whether the README
DoD passes, on which outputs, made by which backend and tracker.

## Scoring rules (read-only; ADR-0004)
| Rule | Value | Owner |
|---|---|---|
| One-person metric | reprojection error in % of body height on the 20 clicked frames of `fixtures/input/single/labels_2d.json` | `part2/eval_reproj.py`, unchanged |
| Threshold | 5% | unchanged |
| Pass rule | every frame (`every_frame`) | unchanged (#18 decision 2) |
| Body height | clip max of clicked nose to ankle-midpoint distance in px | unchanged |
| Multi-person | at least 5 GT people, each covered on at least 95% of keyframes, at most 1 id swap per minute, each matched id has a pose3d stream | `part2/eval_tracks.py`, unchanged |
| Second one-person set | at least 20 COCO val2017 single-person images (every keypoint labelled, nose and both ankles visible, body height at least 150 px; occluded joints null and unscored as in the seated set; ruling of 2026-10-29) (`fixtures/input/coco/labels_2d.json`), same metric, 5% threshold and every-frame rule; body height is the nose to ankle-midpoint distance with each image its own clip | TICKET-037 (operator ruling on #337) |
| One-person gate | passes only when every scored one-person set passes; the 20 seated frames stay scored and gated, unchanged | operator ruling 2026-10-28 |
| Multi-person tracker | scored on `api-sam31` outputs; `local-open` on the class clip reported in `multi_person_local_open`, never gated | operator ruling 2026-10-28 (ADR-0003) |
| Labels | `labels_2d.json`, `gt_tracks.json`, `fixtures/input/coco/labels_2d.json` | never edited, never re-clicked by an agent; COCO labels are the dataset's human annotations, mapped by joint name only |

## Scored outputs and stamps (ADR-0006)
- Default scored dir: `fixtures/output/scored/<mode>/` for `single` (`pose3d.json`, `camera.json`,
  `stamp.json`), `coco-single` (one photo run per selected image, plus `stamp.json`), `class` (`tracks.json`,
  `pose3d.json`, `camera.json`, `stamp.json`, tracker `api-sam31`) and `class-local-open` (same files, tracker
  `local-open`). `make check-2
  SCORED=out` (env `PART2_SCORED_DIR`) scores `out/<mode>/` for experiments.
- `make outputs [BACKEND=gpu] [TRACKER=<name>]` (`part2 outputs`) regenerates every mode on this host straight
  into the scored dir; with no `TRACKER` the class mode walks the `scored` order (`api-sam31`, then
  `local-open`, ADR-0003) and `class-local-open` always runs `local-open`; `make outputs BACKEND=cpu` writes `fixtures/output/scored/cpu-single/`.
- Two CPU dirs sit in the scored dir beside the gated modes, and `make check-2` gates neither: `cpu-single` (backend
  `cpu`, RTMPose-x with the default lifter `bones-prior`) and `cpu-sam3db-single` (backend `cpu-sam3db`, SAM 3D Body on
  the CPU device, unrefined, no lifter; `make outputs BACKEND=cpu-sam3db` writes it, TICKET-044). The CPU 3D bar below
  scores either.
- Stamp `part2.stamp/2`:
  `{schema, mode, backend, tracker, lifter, refine: [rung names], models: [{name, source, weights_sha256}],
  env_profile, env_lock_sha256, code_sha256, frames_sha256, created_utc, host_gpu}`.
  `code_sha256` covers only the files the mode, backend, tracker, lifter and rungs import (listed per
  registry entry), plus `part2/frames.py`, `joints.py`, `canonical.py`, and `part2/output_steps.py` (every mode
  lists it in `modules`, AC-K15). `stamp.NOT_OUTPUT_CODE` names the modules that validate, document or read keys
  (`schema`, `contract`, `doctor`, `keys`, `provenance`, the package `__init__`) and `part2/mesh3d.py`, which writes only
  the optional mesh pair of `part2 run --mesh` (TICKET-048); they are left out of `code_files` even when a covered
  file reaches them. The import walk still passes through them (`canonical.py` imports `contract.py`, which reaches
  `doctor.py`, which reads a `mesh3d.json`), so a module only they import would join every stamp: that is why `mesh3d.py`
  is named, and a test recomputes every mode's closure to hold it out (AC-K15). `env_lock_sha256` hashes the lock
  of the recorded profile only (`envs/gpu-cu128/constraints.txt`, `envs/cpu/requirements.txt` or the
  team's `k8s/constraints-gpu.txt`), so a change to another profile never stales this mode.
- Freshness: the check recomputes `code_sha256`, `frames_sha256` and `env_lock_sha256` from the stamp's
  own names; any mismatch fails that mode with the name of what changed. A v1 stamp (`{"fingerprint"}`)
  is read as stale with "stamp v1 from HPC; run make outputs".
- The fingerprint is taken before inference starts (unchanged from `check.py`).

## CPU 3D bar (decision 2, Muse's bar adopted unchanged)
On `fixtures/input/single`, `cpu-single` against the GPU reference `single` (frame by frame, canonical
frame, both hip-centred):
- mean per-joint distance over all frames and the 17 joints <= 0.10 m;
- bone-length CV <= 0.05, where bone-length CV = the mean over the 12 non-face bones of `part2.joints.BONES`
  (its 16 edges minus the 4 face edges) of that bone's std/mean over frames; the max over bones is reported beside it.
Printed as block `cpu_backend_3d` in the check-2 JSON; not part of the top-level `pass` (README DoD).
`make check-2-cpu` exits 0 only when this block passes. Missing `cpu-single` gives
`{"pass": false, "status": "no cpu outputs; run make outputs BACKEND=cpu"}`.

### Which CPU dir the block scores (TICKET-044)
The block scores `cpu-single` unless a CPU mode is named. The name is, in order: the flag
(`python -m part2.check --block cpu_backend_3d --cpu-mode NAME`), the environment `PART2_CPU_MODE`, then the default
`cpu-single`; `make check-2-cpu CPU_MODE=NAME` sets the environment variable. `NAME` is a dir of the scored dir, where
the reference `single` is, never a path: a name with a path separator, or `.` or `..`, fails the block with exit 1 and
the status `error: ValueError: PART2_CPU_MODE or --cpu-mode names a mode dir of the scored dir, not the path "<x>"`.
`--cpu-mode` goes with `--block cpu_backend_3d` only; with any other block, or none, it is an argument error (exit 2).
The reference is always `single`; the eval, the stamp checks and the exit codes are the same for every name (a named
dir with no `pose3d.json` gives `no cpu outputs; run make outputs BACKEND=<b>` and exit 2, where `<b>` is the backend
that makes the mode asked for: `cpu-sam3db` for `cpu-sam3db-single`, `cpu` for `cpu-single` and any other name).
`PART2_CPU_MODE` also picks the dir of the block printed inside the full `make check-2` report; the top-level `pass`
never reads that block.

The block scores a CPU backend's output only. A named dir that exists is refused, with exit 1 and `pass: false`, when
it is the reference `single` (by name) or when its `stamp.json` names a backend other than `cpu` and `cpu-sam3db`; the
`status` is one line naming the dir and its backend, and the eval does not run (`make check-2-cpu CPU_MODE=single`
used to score the reference against itself and pass with a mean of 0.0). A dir whose stamp is missing or v1 names no
backend, so the stamp check reports it as it does for any mode.

Speed block: when the scored CPU file's `provenance.timing` carries `seconds_per_frame` (the `cpu-sam3db` backend
writes `timing: {load_s, seconds, frames, seconds_per_frame, threads, warm}`; a file made before `warm` was added has
the first five), the block adds `seconds_per_frame` and the whole `timing` object, whatever keys it has, beside the
bar. A file without it, such as `cpu-single`, adds neither key and its block is unchanged.

The two committed CPU sets, each against the refined `single` (the GPU reference is refined with `focal` then
`kp2d-fit`; both CPU runs are unrefined), 111 of 111 frames:

| Command | Dir | Backend and lifter | `mean_m` | `bone_cv_mean` | Bar | Exit | Speed keys |
|---|---|---|---|---|---|---|---|
| `make check-2-cpu` | `cpu-single` | `cpu`, `bones-prior` | 0.145 | 0.016 | fails the 0.10 m limit | 1 from `python -m part2.check`, 2 through make | none |
| `make check-2-cpu CPU_MODE=cpu-sam3db-single` | `cpu-sam3db-single` | `cpu-sam3db`, no lifter | 0.0363 | 0.0408 | passes | 0 | `seconds_per_frame` 31.74 on 8 threads (2026-10-31 run) and 46.95 under host load (committed set, 2026-11-01), `load_s` 23.7 (2026-10-31) and 23.4 (2026-11-01) |

## Gold set is the test set (ADR-0004, setup review B2)
The 20 labelled frames of `labels_2d.json`, the COCO set (`fixtures/input/coco/labels_2d.json`) and the class
`gt_tracks.json` score; they never select. The COCO image selection rule is committed before any scoring and
never changed after one.
1. No rung, rung parameter or tracker parameter is chosen by its score on the gold set. Parameters are
   fixed before any gold scoring from label-free objectives only: agreement with RTMPose 2D on the
   single clip's 91 unlabelled frames and on the dance clip, temporal smoothness (mean joint
   acceleration), and bone-length stability (bone CV).
2. `part2/refine/**` and `part2/trackers/**` never import `part2.eval_reproj` or `part2.eval_tracks`
   and never open `labels_2d.json` (either set) or `gt_tracks.json`; `tests/test_gold_isolation.py` checks
   imports by AST and path strings by scan.
3. Each configuration is committed, then scored once by `make check-2`. Every gold scoring, pass or
   fail, gets a row in `progress/ladder.md`; the running count appears in STATUS.md and in the DONE? or
   STATUS comment.
4. At most one revision per rung, justified by a label-free diagnostic written in `progress/ladder.md`
   before the rescore.
5. `ensemble` combines per frame by a label-free rule: the per-joint median across members, or the member
   with the best RTMPose 2D agreement on that frame.
6. Tracker tuning (re-prompt interval, IoU, ByteTrack thresholds) uses the dance clip or a label-free
   id-consistency measure (id changes per minute from mask continuity); each tuned configuration is
   scored once on the class gold and gets a row.

## One-person ladder (decision 3, ADR-0004)
Order, each a distinct model-side family, each a refine rung in `part2/refine/`:
0. Reproduce: `make outputs BACKEND=gpu` on the local RTX 5090 (cu128 profile), scored; numbers recorded
   beside the cluster's (TICKET-019). If it is already green, the ladder is skipped and recorded. If the cu128
   port fails inside its timebox, the record says the HPC reference could not be reproduced on this
   host, with the error, and the ladder runs on the CPU backend from its own unrefined score; no HPC
   number is reported as measured here.
1. `kp2d_fit`: fit the SAM 3D Body pose per frame to RTMPose-x 2D keypoints, keeping SAM's bone lengths
   (fixed per person over the clip) and its depth as a prior (TICKET-020).
2. `temporal`: temporal smoothing of joint trajectories (TICKET-021).
3. `focal`: fit focal length and FOV per clip instead of MoGe-2's estimate (TICKET-021).
4. `ensemble`: combine rungs or model runs per frame (TICKET-021).
Stop rule: stop at the first rung whose committed outputs pass every one-person check on every scored
one-person set (seated clip and COCO); later rungs are
recorded as not run. Each rung's outputs are produced by `make outputs` with the rung named in the stamp,
scored by the unchanged check, and the 3D distance to the unrefined GPU output is reported beside the
reprojection numbers so a 2D gain that bends the body is visible. Never: change thresholds, labels,
the body-height rule or the every-frame rule; drop or select frames; tune on the labels themselves
(section "Gold set is the test set").
DEGRADED ending: still red after rung 4, publish the best rung's outputs and numbers honestly, STATUS
names it DEGRADED with mean, p95, max and frames over, per set. No new filming (operator ruling on #337): the
second set is human-annotated open data at any angle (TICKET-037). Rung `temporal` does not apply to the COCO
images (each is its own one-frame clip) and passes them through unchanged.
Foot points (TICKET-043): the rungs keep pose3d.json's optional `extra_joints` with the refined skeleton. `kp2d-fit`
and `temporal` do not fit them: each moves rigidly with its own ankle's displacement. `focal` takes the feet of the
run it chooses. Every score here reads the 17 joints only, so the foot points change no number of `make check-2`;
their own measure is `make check-feet` (`docs/design/specs/integration-contract.md` AC-C16), reported and never gated.

### Ladder parameters (label-free, committed before each rung's gold scoring)
Each rung's values come from the objectives below and are committed before its one `make check-2`.
`part2.refine.objectives` computes them; no label file is read, except the `frame` field of
`fixtures/input/single/labels_2d.json` to leave those frames out.

| Input | What is used |
|---|---|
| seated | the 91 frames of `fixtures/input/single/frames` not in labels_2d.json (all but 0, 6, 12, 17, 23, 29, 35, 41, 46, 52, 58, 64, 69, 75, 81, 87, 93, 98, 104, 110); unrefined local gpu body3d (TICKET-019 run) |
| dance | Pexels video 8956007 (HD, 1080x1920, 25 fps) re-extracted by `part2 frames --fps 5`: 79 frames with the `t_ms` of `fixtures/output/dance/`; SAM 3D Body joints rebuilt from its `pose3d.json` and `camera.json` (p_cam = R p + t), boxes from its `tracks.json`; 5 people, 289 person-frames |
| COCO | the 20 photos' unrefined gpu body3d; image-level agreement only (a photo has no time axis) |
| 2D | RTMPose-x (`part2.backends.cpu_rtm.Rtm2D`) on each person's own body3d box |

| Objective | Definition |
|---|---|
| agreement | score-weighted mean px distance to RTMPose-x, in % of H (the person's largest nose to ankle-midpoint distance in the unrefined projection) |
| 2D acceleration | mean joint acceleration of the projection, % of H per s^2, over runs of three consecutive kept frames |
| 3D acceleration | the same on camera-space joints, m/s^2 |
| bone CV | mean over the 12 body bones of std/mean over frames |
| 3D move | mean distance of refined to unrefined camera-space joints, m |

Rung 1 `kp2d-fit` (2026-10-29). Rule: over the grid BETA {0.5, 0.75, 1, 1.5, 2} x C {0.1, 0.2, 0.3} x
GAMMA {0, 1, 2} x SIGMA_Z {0.01, 0.02, 0.05, 0.1} x SIGMA_L {0.005, 0.01, 0.03} (S2D 0.01, 15 iterations;
540 points), take the lowest mean of (refined / unrefined 2D acceleration) on seated and dance, among the
points whose 3D acceleration is no higher than the unrefined one and whose bone CV is at most 0.01 on both
clips (119 points). Agreement is reported, never maximised: it only grows with BETA. Chosen: BETA 1,
GAMMA 2, C 0.2, SIGMA_Z 0.02, SIGMA_L 0.01 (rule value 0.9294; next 0.9298 at C 0.3).

| Set | agreement % | 2D acceleration | 3D acceleration | bone CV | 3D move m |
|---|---|---|---|---|---|
| seated, unrefined | 5.91 | 32.16 | 0.543 | 0.0408 | |
| seated, kp2d-fit | 4.75 | 28.71 | 0.522 | 0.0041 | 0.017 |
| dance, unrefined | 4.32 | 102.65 | 7.684 | 0.0638 | |
| dance, kp2d-fit | 3.80 | 99.16 | 7.673 | 0.0027 | 0.016 |
| COCO, unrefined (mean, max image) | 1.63, 4.31 | | | | |
| COCO, kp2d-fit (mean, max image) | 1.19, 3.34 | | | | 0.007 |

Rung 1 gold scoring (a3396e1 config, outputs 0165a98): seated pass (0 of 20 over, max 4.983%); COCO fail
(1 of 20 over, image 229553 at 5.119%). The ladder goes on, and each rung keeps the ones below it: rung 2's
outputs apply `kp2d-fit` then `temporal`.

Rung 2 `temporal` (2026-10-29). Rule: the bandwidth with the lowest mean leave-one-out 2D error
(`temporal.cv_error`, % of H) over seated and dance, on the `kp2d-fit` output, over SIGMA_T {0.1, 0.15,
0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8} s (0.1 s is the narrowest that has a neighbour at 5 fps). Chosen:
SIGMA_T 0.1 s. Photos pass through unchanged, so this rung cannot change the COCO block.

| SIGMA_T s | 0.1 | 0.15 | 0.2 | 0.25 | 0.3 | 0.4 | 0.5 | 0.6 | 0.8 |
|---|---|---|---|---|---|---|---|---|---|
| seated leave-one-out % | 0.587 | 0.608 | 0.662 | 0.743 | 0.849 | 1.085 | 1.340 | 1.602 | 2.132 |
| dance leave-one-out % | 2.308 | 2.669 | 2.917 | 3.307 | 4.116 | 4.919 | 4.969 | 5.434 | 6.395 |

| Set | agreement % | 2D acceleration | 3D acceleration | bone CV | 3D move m |
|---|---|---|---|---|---|
| seated, kp2d-fit + temporal | 4.75 | 21.70 | 0.369 | 0.0054 | 0.018 |
| dance, kp2d-fit + temporal | 3.80 | 75.19 | 5.829 | 0.0136 | 0.040 |

Rung 2 gold scoring (75cb7e0 config, outputs bf5ed17): seated fail (1 of 20 over, frame 29 at 5.031%); COCO
fail (unchanged, 229553 at 5.119%).

Rung 2 revision, label-free diagnostic (written after rung 2's scoring, before any rescore): the
leave-one-out error rises with SIGMA_T from the narrowest candidate on both clips, so the label-free evidence
favours less smoothing than any candidate, down to none; 0.1 s was picked only because the grid held no
narrower bandwidth with a neighbour. Revised rung 2: no smoothing. That configuration is rung 1's, already
scored (outputs 0165a98), so the revision adds no gold scoring, and rung 3 builds on `kp2d-fit` alone:
its outputs apply `focal`, then `kp2d-fit`.

Rung 3 `focal` (2026-10-29). Per clip (per photo for COCO), SAM 3D Body runs again at f = s x f_MoGe2 for
each s in SCALES and the run whose projection agrees best with RTMPose-x replaces the input (agreement
capped per joint at CAP H, weights score^GAMMA; CAP 0.2 and GAMMA 2 as rung 1's C and GAMMA). Rule for
SCALES: wide enough that the seated clip's optimum on its unlabelled frames is inside the range. With
{0.7, 0.85, 1.0, 1.2, 1.4} the optimum sat on the edge (1.4); adding 1.7 and 2.0 put it inside. Chosen:
SCALES {0.7, 0.85, 1.0, 1.2, 1.4, 1.7, 2.0}.

| s | 0.7 | 0.85 | 1.0 | 1.2 | 1.4 | 1.7 | 2.0 |
|---|---|---|---|---|---|---|---|
| seated capped agreement, unlabelled frames % | 4.864 | 4.710 | 4.626 | 4.556 | 4.549 | 4.557 | 4.562 |

COCO photos pick 0.7 (3), 0.85 (2), 1.2 (2), 1.4 (2), 1.7 (3) and 2.0 (8); image 229553 picks 2.0 (capped
agreement 3.08 at s 1 to 2.90). After `kp2d-fit` on the chosen run, unrefined -> focal + kp2d-fit: seated
agreement 5.91 -> 4.76 (kp2d-fit alone 4.75), 2D acceleration 32.16 -> 32.31, 3D acceleration 0.543 -> 0.789
(the subject sits farther from a longer-focal camera), bone CV 0.0408 -> 0.0043; COCO agreement 1.63 ->
1.17 (kp2d-fit alone 1.19), max image 4.31 -> 3.32.

Rung 3 gold scoring (ac242c9 config, outputs f642222): seated pass (0 of 20 over, mean 3.839%, p95 4.816%,
max 4.877% at frame 29); COCO pass (0 of 20 over, mean 2.018%, p95 4.092%, max 4.904% at image 229553);
`make check-2` exit 0. The ladder stops here: rung 4 `ensemble` is not needed and was not run. The seated
subject sits 0.81 m farther from the camera than in the unrefined output (camera space, focal 1.4 x MoGe-2);
the hip-centred canonical pose moves 0.036 m on average (p95 0.081 m), COCO 0.025 m (max 0.042 m).

## Metrics JSON (shape)
```json
{
  "one_person": {"metric": "reprojection_error_pct_of_body_height", "threshold_pct": 5.0, "rule": "every_frame",
                 "n_frames": 20, "n_failed_frames": 0, "mean_pct": 0.0, "max_pct": 0.0, "worst_frame": 0,
                 "checks": {}, "pass": true, "body_height": "...",
                 "outputs": {"dir": "fixtures/output/scored/single", "backend": "gpu", "tracker": null,
                             "lifter": null, "refine": [], "stamp": "fresh", "code_sha256": "..."}},
  "one_person_coco": {"metric": "reprojection_error_pct_of_body_height", "threshold_pct": 5.0, "rule": "every_frame",
                      "n_frames": 20, "n_failed_frames": 0, "mean_pct": 0.0, "max_pct": 0.0, "pass": true,
                      "body_height": "per image nose->ankle", "outputs": {"dir": "fixtures/output/scored/coco-single"}},
  "multi_person": {"metric": "tracking_coverage_and_id_swaps", "n_gt_people": 7, "mean_coverage": 1.0,
                   "total_id_swaps": 0, "checks": {}, "pass": true,
                   "outputs": {"tracker": "api-sam31", "...": "as above"}},
  "multi_person_local_open": {"n_gt_people": 7, "mean_coverage": 0.0, "total_id_swaps": 0, "pass": false,
                              "gated": false, "outputs": {"dir": "fixtures/output/scored/class-local-open",
                                                          "tracker": "local-open"}},
  "cpu_backend_3d": {"pass": true, "lifter": "fixed-bones", "mean_joint_distance_m": 0.0,
                     "bone_length_cv_mean": 0.0, "bone_length_cv_max": 0.0, "frames": 111,
                     "reference": "fixtures/output/scored/single"},
  "pass": true
}
```
Values above are placeholders for the shape; real numbers come from the run. Top-level `pass` is
`one_person.pass and one_person_coco.pass and multi_person.pass`.
In `cpu_backend_3d`, `lifter` is the lifter that made the scored CPU dir (`bones-prior` for the committed `cpu-single`,
`null` for `cpu-sam3db-single`) and `cpu` names that dir; the optional `seconds_per_frame` and `timing` follow
"Which CPU dir the block scores".

## Files
| File | Role |
|---|---|
| `part2/check.py` | modified: scored dir, stamp v2, `cpu_backend_3d` block, `outputs` names; TICKET-044: `--cpu-mode` and `PART2_CPU_MODE` pick the CPU dir, the block reports `seconds_per_frame` and `timing` when the file has them and refuses a dir that is not a CPU backend's output |
| `part2/stamp.py` | stamp v2 write, read, freshness |
| `part2/outputs.py` | `part2 outputs` driver; takes the host GPU lock through `output_steps.gpu_locked` and measures `part2_commit` once per run (AC-K16) |
| `part2/output_steps.py` | the steps `part2 run`, `part2 stock` and `make outputs` share to write a run's outputs: pose3d extras and provenance, the refine rungs, the tracks stamp, the GPU lock (`gpu_locked`, the one copy of the rule "gpu backend means the host lock, else nothing" that `part2 run`, `part2 stock` and `make outputs` all use). Moved out of `part2/cli.py` (review residual R19) so a stamp can hash it; every mode in `outputs.py` lists it in `modules` |
| `part2/eval_3d.py` | the 3D bar; `no_cpu(backend)`: the `no cpu outputs` status for the mode asked for (AC-K17) |
| `part2/coco_set.py` | COCO fetch, licence filter, selection rule, keypoint mapping to the canonical 17 (TICKET-037) |
| `part2/eval_coco.py` | scores `coco-single` with the unchanged `eval_reproj` rules, each image its own clip (TICKET-037) |
| `fixtures/input/coco/` | selected images, `labels_2d.json`, `SOURCE.md` (per-image licence and URL), `SELECTION.md` (the rule) |
| `part2/refine/__init__.py`, `kp2d_fit.py`, `temporal.py`, `focal.py` | ladder rungs |
| `part2/refine/ensemble.py` | rung 4: not built, rung 4 not needed |
| `part2/hashing.py` | shared sha256 of a file (stamps, weights digests, cache checks; TICKET-030) |
| `Makefile` | `outputs`, `check-2` (SCORED), `check-2-cpu` (`CPU_MODE`, TICKET-044) |
| `fixtures/output/scored/{single,class,cpu-single,cpu-sam3db-single}/` | committed outputs and stamps |
| `tests/test_check.py`, `tests/test_stamp.py`, `tests/test_outputs.py`, `tests/test_output_steps.py`, `tests/test_provenance.py`, `tests/test_eval_3d.py`, `tests/test_refine.py` | tests |
| `tests/test_cpu_sam3db.py` | TICKET-044: the CPU mode selection and the speed block (AC-K17), beside the backend's own tests |
| `tests/test_gold_isolation.py` | no import of the evals and no label path under `part2/refine/` or `part2/trackers/` |
| `tests/test_coco_set.py`, `tests/test_eval_coco.py` | licence filter, selection rule, mapping and scorer on hand-made data |
| `fixtures/output/scored/{coco-single,class-local-open}/` | committed outputs and stamps |

## Acceptance Criteria
### AC-K01: Clean clone scores committed outputs
Given a fresh clone with `fixtures/output/scored/` committed and no `out/`
When `make check-2` runs with no GPU
Then it prints the metrics JSON for both modes from the scored dir and exits by the DoD.
### AC-K02: SCORED override
`make check-2 SCORED=out` scores `out/<mode>/` with the same rules.
### AC-K03: Stamp freshness per mode
Changing a file in `code_sha256`'s list stales only the modes that list it; changing
`envs/cpu/requirements.txt` never stales a gpu-made mode (tests with temp roots).
### AC-K04: Stamp v1 is stale
A `{"fingerprint": ...}` stamp fails its mode with the v1 message.
### AC-K05: Outputs name what made them
Each mode block carries `outputs` with dir, backend, tracker, lifter, refine and stamp state.
### AC-K06: Scoring rules unchanged
`eval_reproj.py`, `eval_tracks.py`, `labels_2d.json` and `gt_tracks.json` have no diff against the
upstream `7e11a7f` versions except comments (test compares sha256 of the label files with recorded values).
### AC-K07: CPU 3D bar
`eval_3d` on hand-made pairs returns the expected distance and CV; `cpu_backend_3d` is printed and does
not change top-level `pass`; `make check-2-cpu` exits by it.
### AC-K17: the 3D bar scores a named CPU dir
Without `CPU_MODE`, `PART2_CPU_MODE` or `--cpu-mode` the block scores `cpu-single` and, for a file with no
`provenance.timing`, adds no speed key. With a name (the flag wins over the environment) it scores that dir of the
scored dir against `single`; the block then carries `seconds_per_frame` and `timing` when the file has them; a missing
dir exits 2 with the `make outputs` command for that mode, a stale one fails with its stamp status, a name with a
separator or dots fails with exit 1, so does the reference `single` or a dir whose stamp names a backend other than
`cpu` and `cpu-sam3db` (one status line with the dir and the backend), and `--cpu-mode` with another block is an
argument error. `make check-2-cpu CPU_MODE=NAME` passes the name through as
`PART2_CPU_MODE`; without it the command carries no such variable. Test:
`tests/test_cpu_sam3db.py` (the default block, the environment and flag with the speed keys, the missing, stale and
path cases, the reference and a gpu dir refused, the missing-dir hint per mode, and `make -n check-2-cpu`); it is AC-B25 of `backends-gpu-cpu.md` seen from the check.
### AC-K08: `make outputs` reproduces
Running `make outputs` twice on this host with no code change gives stamps with identical
`code_sha256`, `frames_sha256` and `env_lock_sha256`, and joints within 1.5 mm (GPU nondeterminism bound,
measured at TICKET-018: peak 1.273 mm, mean 0.057 mm).
### AC-K09: Ladder record
Every rung run has a row in `progress/ladder.md` (firm-only): rung, commit, mean, p95, max, frames over,
3D distance to the unrefined output; the scored dir holds the chosen rung's outputs.
### AC-K11: Gold isolation
`tests/test_gold_isolation.py` fails when any module under `part2/refine/` or `part2/trackers/` imports
`part2.eval_reproj` or `part2.eval_tracks` (any import form) or names `labels_2d.json` or `gt_tracks.json`.
### AC-K12: Every gold scoring counted
`progress/ladder.md` has one row per gold scoring (rung or tracker configuration, commit, label-free
objective values fixed before scoring, result) and the revision diagnostic, when any, precedes its rescore
row; STATUS.md states the count. Verification: inspection at TICKET-022 and in the review.
### AC-K13: COCO one-person block
`one_person_coco` is printed with the same metric, 5% threshold and every-frame rule; only images whose licence
field allows commercial use are in the set; the selection rule in `SELECTION.md` is committed before the first
scoring (git history shows it); top-level `pass` needs it. Tests on hand-made annotations plus inspection.
### AC-K14: local-open reported, never gated
`multi_person_local_open` is printed with `gated: false` and never changes top-level `pass`; `multi_person`
names `api-sam31`. Test.
### AC-K10: Missing outputs
No scored dir and no `SCORED`: each mode fails with "missing output ...; run make outputs", exit 1.
### AC-K15: The shared output steps are hashed
`part2 run`, `part2 stock` and `make outputs` build the `pose3d.json` extras and provenance, run the refine rungs and
stamp `tracks.json` through `part2/output_steps.py`. Every mode in `outputs.MODES` lists `part2.output_steps` in
`modules`, so its `code_files` hash that file, and an edit to it makes `stamp.check` report the mode stale with the
file named in `changed_files`. `part2/cli.py` itself is not hashed (a help-text edit stales nothing), and neither is
`part2/mesh3d.py` (an edit to the mesh writer stales nothing: it makes no scored file). Tests:
`tests/test_stamp.py` (an edit stales every mode that lists it; every mode lists it; no mode's closure holds `cli.py` or
`mesh3d.py`; pruning the walk at `NOT_OUTPUT_CODE` changes no mode's closure).
### AC-K16: One commit measure per run
`make outputs` takes `provenance.part2_commit()` (HEAD, plus `+dirty` when a tracked file differs) once, before the
first mode writes anything, and passes it to every mode: every `pose3d.json` and every `tracks.json` of the run
records that one value (`output_steps.pose_extras` and `output_steps.tracks_extras` take it as `commit`; the
`cpu-single` backend and the trackers would otherwise each name a commit of their own). Measured per file, a run's own earlier outputs
(tracked files under `fixtures/output/`) would make later modes read `+dirty` on a clean tree (review residual R14).
A tree dirty before the run still reads `+dirty` in every mode. `part2 stock` does the same across its takes, and
`part2 run` and `part2 track` still measure when they write their file. There is one rule (review residual N3):
the tracker adapters (`part2/trackers/__init__.py`) and the cpu backend (`part2/backends/cpu_rtm.py`) call
`provenance.part2_commit()` and keep no commit helper of their own, so no writer spells the suffix `-dirty`,
reads `part2/` alone or reads HEAD alone. Tests: `tests/test_outputs.py` (two modes whose first write
dirties the tree record the same clean commit in `tracks.json` and `pose3d.json`; a tree dirty before the run
records `+dirty` in both), `tests/test_stock.py`, `tests/test_output_steps.py` (`tracks_extras` takes the run's
commit), `tests/test_cpu_rtm.py` and `tests/test_provenance.py` (the shared rule).

### Rule-Based ACs
- AC-K-NFR-01: `make check-2` runs in under 60 s without a GPU. Verification: timed at TICKET-022.
- AC-K-NFR-02: no thresholds or rule constants change. Verification: AC-K06 test plus review.

## Error Cases
| Condition | Behavior | Message Format | AC Reference |
|---|---|---|---|
| Scored files missing | mode fails | `missing output <dir>/<file>; run make outputs` | AC-K10 |
| Stamp stale | mode fails | `<dir> is stale: <code|frames|env lock> changed since <created_utc>; run make outputs` | AC-K03 |
| Stamp v1 | mode fails | `stamp v1 from HPC; run make outputs` | AC-K04 |
| Eval crashes | mode fails, JSON still printed | `error: <Type>: <msg>` | AC-K01 |
| `make outputs BACKEND=gpu` without CUDA | exit 1 | `outputs: backend gpu needs CUDA (make setup-gpu)` | AC-K08 |
| `CPU_MODE`, `PART2_CPU_MODE` or `--cpu-mode` names a path | block fails, exit 1 | `error: ValueError: PART2_CPU_MODE or --cpu-mode names a mode dir of the scored dir, not the path "<x>"` | AC-K17 |
| `CPU_MODE`, `PART2_CPU_MODE` or `--cpu-mode` names the reference `single` | block fails, exit 1 | `<dir> is the GPU reference (backend <b>), not a CPU mode dir; choose a dir made by cpu or cpu-sam3db` | AC-K17 |
| `CPU_MODE`, `PART2_CPU_MODE` or `--cpu-mode` names a dir whose stamp backend is not `cpu` or `cpu-sam3db` | block fails, exit 1 | `<dir> was made by backend <b>, not a CPU backend; choose a dir made by cpu or cpu-sam3db` | AC-K17 |
| the named CPU dir has no `pose3d.json` | block fails, exit 2 | `no cpu outputs; run make outputs BACKEND=<cpu or cpu-sam3db>` | AC-K17 |
| `--cpu-mode` without `--block cpu_backend_3d` | exit 2 | `python -m part2.check: error: --cpu-mode goes with --block cpu_backend_3d` | AC-K17 |

## Edge Cases
- A labelled frame where the person is not detected: scored as failed (unchanged eval).
- The class clip at 17.6 s: swap allowance uses `max(1, clip_min)` (unchanged).

## Locked defaults (final)
| Item | Decision |
|---|---|
| Scored outputs | committed under `fixtures/output/scored/` (`.gitignore` already keeps `!fixtures/**/*.json`) |
| Default scored dir | `fixtures/output/scored`; override `SCORED` / `PART2_SCORED_DIR` |
| Bone set for the bar | the 12 non-face bones of `part2.joints.BONES` (16 edges minus the 4 face edges) |
| CV aggregate | mean over bones; max reported |
| Ladder record | `progress/ladder.md`, one row per gold scoring (rung or tracker configuration), pass or fail |
| Gold set | test set only: parameters fixed from label-free objectives, committed, scored once; at most one revision per rung after a label-free diagnostic |
| Ensemble rule | per frame, label-free (per-joint median or best RTMPose 2D agreement) |
| One-person sets | seated clip (20 frames) and COCO val2017 (20 or more images), each gated by the unchanged rule |
| Class tracker | scored on `api-sam31`; `local-open` reported beside it, never gated |
| Reference reproduction | local RTX 5090 cu128 backend; if that fails, recorded as not reproduced on this host |
| Publish check | `scripts/simon-publish.sh` uses `make -s test` until TICKET-022 commits scored outputs, then `make -s check-2` |

## Negative Requirements
- MUST NOT re-click, edit or filter labels. Why: gold read-only (ADR-0004).
- MUST NOT fold the CPU 3D bar into the README DoD. Why: decision 2.
- MUST NOT commit `out/`, weights or videos. Why: size and licence.

## Compromises
### Committed outputs instead of CI inference
Short-term: committed outputs plus stamps. Long-term: a GPU CI runner. Trigger: a runner exists.

## Assumptions
ASM-002, ASM-003, ASM-006 (reproduction on this host), ASM-011 (fixture representative).

## Dissent Review
Reviewed by: setup lane (architect, opus), 2026-10-28.
### Concern 1: reproduction differs from HPC
Challenge: V100 vs RTX 5090, torch 2.5.1 vs 2.7+, ViTDet vs detector boxes. Impact: baseline moves.
Mitigation: TICKET-019 records both numbers; the host's number is the baseline. Resolution: ACCEPTED_RISK.
### Concern 2: rung 1 overfits the 2D model
Challenge: RTMPose is close to the labels' convention. Impact: green 2D, bent 3D. Mitigation: 3D distance
to the unrefined output reported per rung. Resolution: ADDRESSED_IN_SPEC.
### Concern 3: stamps too strict
Challenge: any comment change stales outputs. Impact: frequent regeneration. Mitigation: per-mode file
lists keep it narrow. Resolution: ACCEPTED_RISK.
### Pre-Mortem
1. Ladder exhausts the deadline. M H, Mitigation: timeboxes in the brief, DEGRADED ending.
2. Scored outputs and code drift apart in a merge. M M, Mitigation: stale stamp fails loudly.
3. GPU nondeterminism above 1 mm. L L, Mitigation: AC-K08 records the bound (it happened: peak 1.273 mm at
   TICKET-018, so the bound is 1.5 mm).

## Requirements Traceability
| Requirement | AC | Ticket |
|---|---|---|
| README DoD via `make check-2` | AC-K01, K05, K06, K10 | TICKET-018, 022 |
| Decision 4 reproducible outputs | AC-K02, K03, K04, K08 | TICKET-018 |
| Review residual R19 (output helpers outside every stamp) | AC-K15 | R19 |
| Review residual R14 (a run's own outputs read as a dirty tree) | AC-K16 | R14 |
| Decision 2 CPU 3D bar | AC-K07 | TICKET-016 |
| TICKET-044 CPU mode selection and speed block | AC-K17 | TICKET-044 |
| Decision 3 ladder | AC-K09, K11, K12 | TICKET-017, 019, 020, 021, 022 |
| Operator ruling on #337 (COCO set) | AC-K13 | TICKET-037 |
| Operator ruling 2026-10-28 (class tracker) | AC-K14 | TICKET-018 |

## Delivery Verification Plan
`make outputs` exit 0 on this host, `make check-2` exit code and JSON recorded in STATUS.md, fresh clone
of upstream `make check-2` at M5, `progress/ladder.md` complete.
